#!/usr/bin/env python3
"""Fail-closed staging validator for the insurance import concurrency gate.

The runner deliberately keeps credentials, source paths, API identifiers, and
raw responses at the transport boundary. Its persisted report contains only
safe scenario references and aggregate counters.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import functools
import hashlib
import json
import math
import os
import re
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, TextIO


SCENARIO_SCHEMA = 'insurance-import-concurrency-scenario-v2'
AUTH_SCHEMA = 'insurance-import-concurrency-auth-v1'
RESULT_SCHEMA = 'insurance-import-concurrency-result-v2'
SAFE_REF = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
SAFE_CODE = re.compile(r'^[A-Z0-9_]{1,64}$')
RETRY_DELAYS = (1, 2, 4)
SYNTHETIC_MARKER = 'INPA_SYNTHETIC_LOAD_FIXTURE_V1'
MAX_POLL_TIMEOUT_SECONDS = 45
OUTPUT_ALLOWLIST = (
    'LOAD START\n', 'LOAD PASS\n', 'LOAD FAIL\n', 'LOAD PREFLIGHT FAIL\n',
    SCENARIO_SCHEMA, AUTH_SCHEMA, RESULT_SCHEMA,
)
PRIVACY_FIELDS = (
    'contains_auth_token',
    'contains_file_path',
    'contains_document_text',
    'contains_raw_response',
    'contains_job_id',
    'contains_customer_id',
)
ALLOWED_SERVER_CODES = frozenset({
    'CANCEL_IN_PROGRESS',
    'IMPORT_STATE_CHANGED',
    'IMPORT_TARGET_CHANGED',
    'IMPORT_UNAVAILABLE',
    'IMPORT_CONFIRM_UNAVAILABLE',
    'credit_exhausted',
})
REPORT_SCHEMA_KEYS = frozenset({
    'schema_version', 'run_id', 'started_at', 'finished_at',
    'configuration', 'workers', 'owner_count', 'request_count',
    'max_intake_p95_ms', 'max_owner_wait_p95_ms',
    'correctness', 'accepted_202', 'unexpected_http',
    'cross_owner_visible', 'owner_customer_mismatch',
    'response_job_mismatch', 'duplicate_job_excess', 'both_adds_preserved',
    'replace_success', 'replace_target_changed_409', 'stale_overwrite',
    'duplicate_analysis_amount', 'latency_ms', 'intake',
    'owner_batch_wait', 'queue_wait', 'end_to_end',
    'owner_queue_p95', 'owner_end_to_end_p95', 'count', 'p50', 'p95',
    'max', 'provider', 'review_required_count', 'not_started_count',
    'unfinished_count', 'terminal_failure_count', 'provider_complete',
    'performance_passed', 'failures', 'case_ref', 'phase', 'http_status', 'code',
    'privacy', *PRIVACY_FIELDS, 'passed',
})
REPORT_SAFE_CODES = frozenset({
    'UNEXPECTED_RESPONSE', 'POLL_TIMEOUT', 'NETWORK_ERROR', 'TIMEOUT_ERROR',
    'INVALID_RESPONSE_ERROR', 'TRANSPORT_ERROR',
    *ALLOWED_SERVER_CODES,
})
REPORT_FIXED_VALUES = frozenset({
    RESULT_SCHEMA,
    'scope', 'poll', 'foreign_scope', 'confirm', 'confirm_state', 'analysis',
    'intake',
    'true', 'false', 'null', '0', '1', '20', '60',
    '200', '202', '404', '409',
})
FIXED_REPORT_TERMS = frozenset(
    REPORT_SCHEMA_KEYS | REPORT_SAFE_CODES | REPORT_FIXED_VALUES)


class PreflightError(Exception):
    """Safe validation failure. The message is intentionally not reported."""


class SecretCollisionError(PreflightError):
    pass


class PrivacyError(Exception):
    pass


class TransportError(Exception):
    """Transport failure carrying only an allowlisted category."""

    def __init__(self, kind: str):
        self.kind = kind if kind in {'network', 'timeout', 'invalid_response'} \
            else 'network'
        super().__init__(self.kind)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: dict[str, Any]


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        token: str,
        headers: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        file_path: str | None = None,
        form_fields: Mapping[str, Any] | None = None,
        timeout: float = 30,
    ) -> HttpResponse:
        ...


class UrllibTransport:
    """Small stdlib-only HTTP adapter. No secret leaves this method."""

    _MAX_RESPONSE_BYTES = 1_048_576

    @staticmethod
    def _multipart(file_path: str, fields: Mapping[str, Any]):
        boundary = f'inpa-load-{uuid.uuid4().hex}'
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.extend((
                f'--{boundary}\r\n'.encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode('utf-8'),
                b'\r\n',
            ))
        with open(file_path, 'rb') as source:
            file_bytes = source.read()
        chunks.extend((
            f'--{boundary}\r\n'.encode(),
            b'Content-Disposition: form-data; name="file"; '
            b'filename="synthetic.pdf"\r\n',
            b'Content-Type: application/pdf\r\n\r\n',
            file_bytes,
            b'\r\n',
            f'--{boundary}--\r\n'.encode(),
        ))
        return b''.join(chunks), f'multipart/form-data; boundary={boundary}'

    @classmethod
    def _decode(cls, data: bytes) -> dict[str, Any]:
        if len(data) > cls._MAX_RESPONSE_BYTES:
            raise TransportError('invalid_response')
        if not data:
            return {}
        try:
            value = json.loads(data.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            raise TransportError('invalid_response') from None
        if not isinstance(value, dict):
            raise TransportError('invalid_response')
        return value

    def request(
        self,
        method: str,
        url: str,
        *,
        token: str,
        headers: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        file_path: str | None = None,
        form_fields: Mapping[str, Any] | None = None,
        timeout: float = 30,
    ) -> HttpResponse:
        request_headers = {
            'Authorization': f'Token {token}',
            'Accept': 'application/json',
            **dict(headers or {}),
        }
        data = None
        if file_path is not None:
            data, content_type = self._multipart(file_path, form_fields or {})
            request_headers['Content-Type'] = content_type
        elif json_body is not None:
            data = json.dumps(json_body, separators=(',', ':')).encode('utf-8')
            request_headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(
            url, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(self._MAX_RESPONSE_BYTES + 1)
                return HttpResponse(response.status, self._decode(raw))
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read(self._MAX_RESPONSE_BYTES + 1)
                body = self._decode(raw)
            except TransportError:
                body = {}
            return HttpResponse(int(exc.code), body)
        except (socket.timeout, TimeoutError):
            raise TransportError('timeout') from None
        except (urllib.error.URLError, OSError, ValueError):
            raise TransportError('network') from None


class PrivacyTrackingTransport:
    def __init__(self, transport: Transport):
        self.transport = transport
        self.raw_strings: set[str] = set()

    def request(self, *args, **kwargs) -> HttpResponse:
        response = self.transport.request(*args, **kwargs)
        self._collect(response.body)
        return response

    def _collect(self, value: Any, *, sensitive=False):
        if isinstance(value, dict):
            for key, item in value.items():
                self._collect(
                    item,
                    sensitive=sensitive or key in {
                        'detail', 'text', 'message', 'raw', 'content'},
                )
        elif isinstance(value, list):
            for item in value:
                self._collect(item, sensitive=sensitive)
        elif sensitive and isinstance(value, str) and value:
            self.raw_strings.add(value)


def _assert_no_symlink_components(path: Path, *, missing_leaf=False):
    if not path.is_absolute() or '..' in path.parts:
        raise PreflightError()
    current = Path(path.anchor)
    for index, part in enumerate(path.parts[1:]):
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if missing_leaf and index == len(path.parts[1:]) - 1:
                return
            raise PreflightError() from None
        except OSError:
            raise PreflightError() from None
        if stat.S_ISLNK(metadata.st_mode):
            raise PreflightError()


def _private_mode(path: Path) -> bool:
    try:
        _assert_no_symlink_components(path)
        metadata = path.lstat()
        return (stat.S_IMODE(metadata.st_mode) == 0o600
                and stat.S_ISREG(metadata.st_mode))
    except OSError:
        return False


def _read_private_json(path: Path) -> dict[str, Any]:
    if not _private_mode(path):
        raise PreflightError()
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise PreflightError() from None
    if not isinstance(value, dict):
        raise PreflightError()
    return value


def _exact_keys(value: Mapping[str, Any], required: set[str],
                optional: set[str] = frozenset()):
    if set(value) - required - optional or not required.issubset(value):
        raise PreflightError()


def _safe_ref(value: Any) -> str:
    if not isinstance(value, str) or not SAFE_REF.fullmatch(value):
        raise PreflightError()
    return value


def _identifier_in_text(text: str, identifier: str) -> bool:
    return re.search(
        rf'(?<!\d){re.escape(identifier)}(?!\d)', text,
    ) is not None


def _positive_int(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise PreflightError()
    return value


def _nonnegative_int(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise PreflightError()
    return value


@functools.lru_cache(maxsize=1)
def _git_worktree_roots() -> tuple[Path, ...]:
    try:
        result = subprocess.run(
            ['git', 'worktree', 'list', '--porcelain'],
            cwd=Path(__file__).resolve().parents[3],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        raise PreflightError() from None
    roots = []
    for line in result.stdout.splitlines():
        if line.startswith('worktree '):
            roots.append(Path(line.removeprefix('worktree ')).resolve())
    if not roots:
        raise PreflightError()
    return tuple(roots)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_private_root(value: Any) -> Path:
    if not isinstance(value, str):
        raise PreflightError()
    root = Path(value)
    _assert_no_symlink_components(root)
    try:
        metadata = root.lstat()
    except OSError:
        raise PreflightError() from None
    if (not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700):
        raise PreflightError()
    root = root.resolve()
    if any(_is_within(root, worktree) for worktree in _git_worktree_roots()):
        raise PreflightError()
    return root


def _require_under_private_root(path: Path, root: Path, *, output=False):
    _assert_no_symlink_components(path, missing_leaf=output)
    resolved = path.resolve(strict=not output)
    if resolved == root or not _is_within(resolved, root):
        raise PreflightError()
    if any(_is_within(resolved, worktree) for worktree in _git_worktree_roots()):
        raise PreflightError()


def _validate_pdf(path_value: Any, private_root: Path) -> tuple[str, str]:
    if not isinstance(path_value, str):
        raise PreflightError()
    path = Path(path_value)
    if not path.is_absolute() or not _private_mode(path):
        raise PreflightError()
    _require_under_private_root(path, private_root)
    try:
        with path.open('rb') as source:
            magic = source.read(5)
            remaining = source.read()
            digest = hashlib.sha256(magic + remaining).hexdigest()
    except OSError:
        raise PreflightError() from None
    if (magic != b'%PDF-' or SYNTHETIC_MARKER.encode() not in remaining
            or path.stat().st_size > 52_428_800):
        raise PreflightError()
    return str(path), digest


def _validate_scenario(scenario: dict[str, Any], private_root: Path):
    _exact_keys(scenario, {
        'schema_version', 'run_id', 'expected_host', 'owners',
        'prepared_jobs', 'confirm_groups', 'private_root', 'polling',
    })
    if scenario['schema_version'] != SCENARIO_SCHEMA:
        raise PreflightError()
    _safe_ref(scenario['run_id'])
    expected_host = scenario['expected_host']
    if (not isinstance(expected_host, str)
            or not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', expected_host)
            or '..' in expected_host or expected_host.startswith(('.', '-'))):
        raise PreflightError()
    owners = scenario['owners']
    if not isinstance(owners, list) or len(owners) != 20:
        raise PreflightError()
    owner_refs: set[str] = set()
    customer_ids: set[int] = set()
    case_ids: set[str] = set()
    hash_owners: dict[str, set[str]] = {}
    hash_digests: dict[str, set[str]] = {}
    for owner in owners:
        if not isinstance(owner, dict):
            raise PreflightError()
        _exact_keys(owner, {'owner_ref', 'customer_id', 'documents'})
        owner_ref = _safe_ref(owner['owner_ref'])
        customer_id = _positive_int(owner['customer_id'])
        if owner_ref in owner_refs or customer_id in customer_ids:
            raise PreflightError()
        owner_refs.add(owner_ref)
        customer_ids.add(customer_id)
        documents = owner['documents']
        if not isinstance(documents, list) or len(documents) != 3:
            raise PreflightError()
        for document in documents:
            if not isinstance(document, dict):
                raise PreflightError()
            _exact_keys(document, {
                'case_id', 'file_path', 'hash_group', 'intent',
                'portfolio_type',
            }, {'target_insurance_id'})
            case_id = _safe_ref(document['case_id'])
            hash_group = _safe_ref(document['hash_group'])
            if case_id in case_ids:
                raise PreflightError()
            case_ids.add(case_id)
            path, digest = _validate_pdf(document['file_path'], private_root)
            document['file_path'] = path
            hash_owners.setdefault(hash_group, set()).add(owner_ref)
            hash_digests.setdefault(hash_group, set()).add(digest)
            intent = document['intent']
            if intent not in {'add', 'replace'}:
                raise PreflightError()
            if document['portfolio_type'] not in {1, 2}:
                raise PreflightError()
            target = document.get('target_insurance_id')
            if intent == 'replace':
                _positive_int(target)
            elif target is not None:
                raise PreflightError()
    if len(case_ids) != 60:
        raise PreflightError()
    cross_owner_groups = [
        group for group, refs in hash_owners.items() if refs == owner_refs
    ]
    if not cross_owner_groups:
        raise PreflightError()
    if any(len(hash_digests[group]) != 1 for group in cross_owner_groups):
        raise PreflightError()

    prepared = scenario['prepared_jobs']
    if not isinstance(prepared, list) or not prepared:
        raise PreflightError()
    prepared_by_ref: dict[str, dict[str, Any]] = {}
    prepared_ids: set[str] = set()
    owner_customer = {item['owner_ref']: item['customer_id'] for item in owners}
    for item in prepared:
        if not isinstance(item, dict):
            raise PreflightError()
        _exact_keys(item, {
            'job_ref', 'job_id', 'owner_ref', 'customer_id', 'intent', 'status',
            'expected_confirmed_coverage_count',
        })
        job_ref = _safe_ref(item['job_ref'])
        owner_ref = _safe_ref(item['owner_ref'])
        if job_ref in prepared_by_ref or owner_ref not in owner_refs:
            raise PreflightError()
        try:
            job_id = str(uuid.UUID(str(item['job_id'])))
        except (ValueError, TypeError, AttributeError):
            raise PreflightError() from None
        if job_id in prepared_ids:
            raise PreflightError()
        prepared_ids.add(job_id)
        item['job_id'] = job_id
        if (_positive_int(item['customer_id']) != owner_customer[owner_ref]
                or item['intent'] not in {'add', 'replace'}
                or item['status'] != 'review_required'
                or _positive_int(item['expected_confirmed_coverage_count']) < 1):
            raise PreflightError()
        prepared_by_ref[job_ref] = item

    groups = scenario['confirm_groups']
    if not isinstance(groups, list) or len(groups) != 2:
        raise PreflightError()
    expected_modes = {'both_confirmed', 'one_confirmed_one_target_changed'}
    seen_modes: set[str] = set()
    referenced_jobs: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise PreflightError()
        _exact_keys(group, {
            'group_ref', 'owner_ref', 'job_refs', 'expected',
            'analysis_customer_id', 'expected_analysis_total_amount',
        }, {'target_ref'})
        _safe_ref(group['group_ref'])
        owner_ref = _safe_ref(group['owner_ref'])
        expected = group['expected']
        if owner_ref not in owner_refs or expected not in expected_modes \
                or expected in seen_modes:
            raise PreflightError()
        seen_modes.add(expected)
        refs = group['job_refs']
        if (not isinstance(refs, list) or len(refs) != 2
                or len(set(refs)) != 2):
            raise PreflightError()
        jobs = []
        for ref in refs:
            ref = _safe_ref(ref)
            if ref not in prepared_by_ref or ref in referenced_jobs:
                raise PreflightError()
            referenced_jobs.add(ref)
            jobs.append(prepared_by_ref[ref])
        intent = 'add' if expected == 'both_confirmed' else 'replace'
        if any(job['owner_ref'] != owner_ref or job['intent'] != intent
               for job in jobs):
            raise PreflightError()
        customer_id = _positive_int(group['analysis_customer_id'])
        if customer_id != owner_customer[owner_ref] \
                or any(job['customer_id'] != customer_id for job in jobs):
            raise PreflightError()
        _nonnegative_int(group['expected_analysis_total_amount'])
        if intent == 'replace':
            _safe_ref(group.get('target_ref'))
        elif 'target_ref' in group:
            raise PreflightError()
    if seen_modes != expected_modes or referenced_jobs != set(prepared_by_ref):
        raise PreflightError()
    safe_output_refs = {scenario['run_id']}
    for owner in owners:
        safe_output_refs.add(owner['owner_ref'])
        for document in owner['documents']:
            safe_output_refs.update((document['case_id'], document['hash_group']))
    for item in prepared:
        safe_output_refs.update((item['job_ref'], item['owner_ref']))
    for group in groups:
        safe_output_refs.update((
            group['group_ref'], group['owner_ref'], *group['job_refs']))
        if group.get('target_ref'):
            safe_output_refs.add(group['target_ref'])
    if any(
        _identifier_in_text(ref, str(customer_id))
        for customer_id in customer_ids for ref in safe_output_refs
    ):
        raise PreflightError()
    polling = scenario['polling']
    if not isinstance(polling, dict):
        raise PreflightError()
    _exact_keys(polling, {
        'timeout_seconds', 'drain_timeout_seconds',
        'interval_seconds', 'max_attempts'})
    timeout = polling['timeout_seconds']
    drain_timeout = polling['drain_timeout_seconds']
    interval = polling['interval_seconds']
    attempts = polling['max_attempts']
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or timeout <= 0 or timeout > MAX_POLL_TIMEOUT_SECONDS
            or not isinstance(drain_timeout, (int, float))
            or isinstance(drain_timeout, bool)
            or drain_timeout <= timeout or drain_timeout > 3600
            or not isinstance(interval, (int, float)) or isinstance(interval, bool)
            or interval <= 0 or interval > 5
            or type(attempts) is not int or not 1 <= attempts <= 3600):
        raise PreflightError()


def _validate_auth(auth: dict[str, Any], owner_refs: set[str]):
    _exact_keys(auth, {'schema_version', 'tokens'})
    if auth['schema_version'] != AUTH_SCHEMA or not isinstance(auth['tokens'], dict):
        raise PreflightError()
    if set(auth['tokens']) != owner_refs:
        raise PreflightError()
    for owner_ref, token in auth['tokens'].items():
        _safe_ref(owner_ref)
        if (not isinstance(token, str) or not token or len(token) > 4096
                or token.strip() != token or any(ch.isspace() for ch in token)):
            raise PreflightError()


def load_and_validate_inputs(
    scenario_path: str | os.PathLike[str],
    auth_path: str | os.PathLike[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario_path = Path(scenario_path)
    auth_path = Path(auth_path)
    scenario = _read_private_json(scenario_path)
    auth = _read_private_json(auth_path)
    private_root = _validate_private_root(scenario.get('private_root'))
    _require_under_private_root(scenario_path, private_root)
    _require_under_private_root(auth_path, private_root)
    _validate_scenario(scenario, private_root)
    _validate_auth(auth, {item['owner_ref'] for item in scenario['owners']})
    serialized_scenario = json.dumps(
        scenario, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    for token in auth['tokens'].values():
        if any(token in value for value in (
                serialized_scenario, *OUTPUT_ALLOWLIST, *FIXED_REPORT_TERMS)):
            raise SecretCollisionError()
    return scenario, auth


def validate_execution(
    *,
    base_url: str,
    scenario: Mapping[str, Any],
    execute_staging: str,
    max_intake_p95_ms: float | None,
    max_owner_wait_p95_ms: float | None,
    tokens: Iterable[str] = (),
) -> str:
    try:
        parsed = urllib.parse.urlsplit(base_url)
    except (TypeError, ValueError):
        raise PreflightError() from None
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or (parsed.hostname or '').lower()
            != str(scenario['expected_host']).lower()
            or parsed.path.rstrip('/') != '/api/v1'):
        raise PreflightError()
    if execute_staging != scenario['run_id']:
        raise PreflightError()
    for threshold in (max_intake_p95_ms, max_owner_wait_p95_ms):
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) \
                or not math.isfinite(threshold) or threshold <= 0:
            raise PreflightError()
    serialized_values = (
        str(max_intake_p95_ms), str(max_owner_wait_p95_ms),
        str(scenario.get('polling', {})),
    )
    if any(token in value for token in tokens for value in serialized_values):
        raise SecretCollisionError()
    return urllib.parse.urlunsplit((
        'https', parsed.netloc, '/api/v1/', '', '',
    ))


def request_with_retry(
    operation: Callable[[], HttpResponse],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> HttpResponse:
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            response = operation()
        except TransportError as exc:
            if exc.kind not in {'network', 'timeout'} or attempt >= len(RETRY_DELAYS):
                raise
        else:
            if not 500 <= response.status <= 599 or attempt >= len(RETRY_DELAYS):
                return response
        sleep(RETRY_DELAYS[attempt])
    raise TransportError('network')


def metric_summary(values: Iterable[float | int]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {'count': 0, 'p50': None, 'p95': None, 'max': None}

    def nearest_rank(percent: float):
        return ordered[max(0, math.ceil(percent * len(ordered)) - 1)]

    return {
        'count': len(ordered),
        'p50': nearest_rank(0.50),
        'p95': nearest_rank(0.95),
        'max': ordered[-1],
    }


def _drain_future_timeout_seconds(polling: Mapping[str, Any]) -> float:
    """Bound one poll future beyond the drain window and final HTTP retries."""
    return (
        float(polling['drain_timeout_seconds'])
        + float(polling['timeout_seconds']) * (len(RETRY_DELAYS) + 1)
        + sum(RETRY_DELAYS)
        + 5
    )


def _safe_code(response: HttpResponse) -> str:
    value = response.body.get('code') if isinstance(response.body, dict) else None
    if value in ALLOWED_SERVER_CODES:
        return value
    return 'UNEXPECTED_RESPONSE'


def _idempotency(run_id: str, phase: str, ref: str) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL, f'inpa-load:{run_id}:{phase}:{ref}'))


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _elapsed_ms(start: Any, end: Any) -> float | None:
    left, right = _parse_time(start), _parse_time(end)
    if left is None or right is None or right < left:
        return None
    return round((right - left).total_seconds() * 1000, 3)


def _sum_held_amount(body: Mapping[str, Any]) -> int | None:
    tree = body.get('tree')
    if not isinstance(tree, list):
        return None
    total = 0
    try:
        for category in tree:
            for subcategory in category['sub_categories']:
                for detail in subcategory['details']:
                    amount = detail['held_amount']
                    if type(amount) not in {int, float} or amount < 0:
                        return None
                    total += amount
    except (KeyError, TypeError):
        return None
    return int(total) if total == int(total) else None


def _failure(ref: str, phase: str, response: HttpResponse | None = None,
             code: str = 'UNEXPECTED_RESPONSE') -> dict[str, Any]:
    item = {'case_ref': _safe_ref(ref), 'phase': _safe_ref(phase)}
    if response is not None:
        item['http_status'] = int(response.status)
        item['code'] = _safe_code(response)
    else:
        item['code'] = code if SAFE_CODE.fullmatch(code) else 'UNEXPECTED_RESPONSE'
    return item


def _remote_preflight(base: str, scenario: Mapping[str, Any],
                      auth: Mapping[str, Any], transport: Transport,
                      sleep: Callable[[float], None]):
    first_owner = scenario['owners'][0]['owner_ref']
    response = request_with_retry(lambda: transport.request(
        'GET', base + 'insurance-imports/config/',
        token=auth['tokens'][first_owner]), sleep=sleep)
    if (response.status != 200
            or response.body.get('review_workflow_enabled') is not True
            or response.body.get('accepted_input') != 'digital_pdf'):
        raise PreflightError()
    details: dict[str, dict[str, Any]] = {}
    prepared_by_ref = {item['job_ref']: item for item in scenario['prepared_jobs']}
    for job_ref, item in prepared_by_ref.items():
        response = request_with_retry(lambda item=item: transport.request(
            'GET', base + f"insurance-imports/{item['job_id']}/",
            token=auth['tokens'][item['owner_ref']]), sleep=sleep)
        body = response.body
        if (response.status != 200 or body.get('job_id') != item['job_id']
                or body.get('customer_id') != item['customer_id']
                or body.get('status') != 'review_required'
                or body.get('intent') != item['intent']
                or type(body.get('draft_version')) is not int):
            raise PreflightError()
        details[job_ref] = body
    for group in scenario['confirm_groups']:
        group_details = [details[ref] for ref in group['job_refs']]
        if group['expected'] == 'both_confirmed':
            if any(item.get('target_insurance_id') is not None
                   for item in group_details):
                raise PreflightError()
        else:
            targets = {
                (item.get('target_insurance_id'), item.get('target_insurance_version'))
                for item in group_details
            }
            if len(targets) != 1 or next(iter(targets))[0] is None:
                raise PreflightError()
    return details


def _run_intake(
    *, base: str, scenario: Mapping[str, Any], auth: Mapping[str, Any],
    transport: Transport, workers: int, sleep: Callable[[float], None],
    clock: Callable[[], float], failures: list[dict[str, Any]],
):
    release = threading.Event()
    cases = [
        (owner, document)
        for owner in scenario['owners'] for document in owner['documents']
    ]
    released_at = 0.0

    def submit(owner, document):
        release.wait()
        owner_ref = owner['owner_ref']
        headers = {'Idempotency-Key': _idempotency(
            scenario['run_id'], 'intake', document['case_id'])}
        fields = {
            'intent': document['intent'],
            'portfolio_type': document['portfolio_type'],
        }
        if document.get('target_insurance_id') is not None:
            fields['target_insurance_id'] = document['target_insurance_id']
        observed_job_ids: set[str] = set()

        def operation():
            response = transport.request(
                'POST', base + f"customers/{owner['customer_id']}/insurance-imports/",
                token=auth['tokens'][owner_ref], headers=headers,
                file_path=document['file_path'], form_fields=fields)
            try:
                observed_job_ids.add(str(uuid.UUID(str(response.body.get('job_id')))))
            except (ValueError, TypeError, AttributeError):
                pass
            return response

        try:
            response = request_with_retry(operation, sleep=sleep)
        except TransportError as exc:
            return {
                'owner_ref': owner_ref, 'customer_id': owner['customer_id'],
                'document': document, 'response': None, 'job_id': None,
                'elapsed': round((clock() - released_at) * 1000, 3),
                'transport_code': exc.kind.upper() + '_ERROR',
                'observed_job_ids': observed_job_ids,
            }
        except Exception:
            return {
                'owner_ref': owner_ref, 'customer_id': owner['customer_id'],
                'document': document, 'response': None, 'job_id': None,
                'elapsed': round((clock() - released_at) * 1000, 3),
                'transport_code': 'TRANSPORT_ERROR',
                'observed_job_ids': observed_job_ids,
            }
        job_id = response.body.get('job_id')
        try:
            job_id = str(uuid.UUID(str(job_id)))
        except (ValueError, TypeError, AttributeError):
            job_id = None
        return {
            'owner_ref': owner_ref, 'customer_id': owner['customer_id'],
            'document': document, 'response': response, 'job_id': job_id,
            'elapsed': round((clock() - released_at) * 1000, 3),
            'transport_code': None,
            'observed_job_ids': observed_job_ids,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(submit, *case) for case in cases]
        released_at = clock()
        release.set()
        results = [future.result(timeout=180) for future in futures]
    accepted = 0
    unexpected = 0
    for item in results:
        response = item['response']
        if response is not None and response.status == 202 and item['job_id']:
            accepted += 1
        else:
            unexpected += 1
            if response is None:
                failures.append(_failure(
                    item['document']['case_id'], 'intake',
                    code=item['transport_code']))
            else:
                failures.append(_failure(
                    item['document']['case_id'], 'intake', response))
    return results, accepted, unexpected


def _run_scope_audit(
    *, base: str, scenario: Mapping[str, Any], auth: Mapping[str, Any],
    transport: Transport, results: list[dict[str, Any]],
    sleep: Callable[[float], None], failures: list[dict[str, Any]],
    workers: int, clock: Callable[[], float],
):
    owner_order = [item['owner_ref'] for item in scenario['owners']]
    next_owner = {
        owner: owner_order[(index + 1) % len(owner_order)]
        for index, owner in enumerate(owner_order)
    }
    cross_visible = 0
    owner_customer_mismatch = 0
    response_job_mismatch = 0
    queue_wait: dict[str, list[float]] = {
        owner_ref: [] for owner_ref in owner_order}
    end_to_end: dict[str, list[float]] = {
        owner_ref: [] for owner_ref in owner_order}
    polling = scenario['polling']
    finished_statuses = {
        'review_required', 'confirmed', 'failed', 'canceled', 'superseded'}

    def poll(item):
        job_id = item['job_id']
        owner_ref = item['owner_ref']
        started = clock()
        last = None
        for attempt in range(polling['max_attempts']):
            if clock() - started > polling['drain_timeout_seconds']:
                break
            try:
                last = request_with_retry(lambda: transport.request(
                    'GET', base + f'insurance-imports/{job_id}/',
                    token=auth['tokens'][owner_ref],
                    timeout=polling['timeout_seconds']), sleep=sleep)
            except TransportError as exc:
                return item, None, exc.kind.upper() + '_ERROR'
            except Exception:
                return item, None, 'TRANSPORT_ERROR'
            if last.status != 200 or last.body.get('status') in finished_statuses:
                return item, last, None
            if attempt + 1 < polling['max_attempts']:
                remaining = (
                    polling['drain_timeout_seconds'] - (clock() - started))
                if remaining <= 0:
                    break
                sleep(min(polling['interval_seconds'], remaining))
        return item, last, 'POLL_TIMEOUT'

    pollable = [item for item in results if item['job_id'] is not None]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(poll, item) for item in pollable]
        future_timeout = _drain_future_timeout_seconds(polling)
        polled = [future.result(timeout=future_timeout) for future in futures]

    provider = {
        'review_required_count': 0,
        'not_started_count': 0,
        'unfinished_count': len(results) - len(pollable),
        'terminal_failure_count': 0,
    }
    for item, response, poll_code in polled:
        job_id = item['job_id']
        if poll_code is not None:
            provider['unfinished_count'] += 1
            failures.append(_failure(
                item['document']['case_id'], 'poll', code=poll_code))
        if response is None:
            provider['not_started_count'] += 1
            owner_customer_mismatch += 1
            continue
        if response.body.get('started_at') is None:
            provider['not_started_count'] += 1
        status_value = response.body.get('status')
        if status_value == 'review_required':
            provider['review_required_count'] += 1
        elif status_value in {'failed', 'canceled', 'superseded'}:
            provider['terminal_failure_count'] += 1
        if response.status != 200:
            failures.append(_failure(item['document']['case_id'], 'scope', response))
            owner_customer_mismatch += 1
        else:
            if response.body.get('customer_id') != item['customer_id']:
                owner_customer_mismatch += 1
            if response.body.get('job_id') != job_id:
                response_job_mismatch += 1
            queue = _elapsed_ms(response.body.get('created_at'),
                                response.body.get('started_at'))
            completed = _elapsed_ms(response.body.get('created_at'),
                                    response.body.get('completed_at'))
            if queue is not None:
                queue_wait[item['owner_ref']].append(queue)
            if completed is not None:
                end_to_end[item['owner_ref']].append(completed)

    for item in pollable:
        job_id = item['job_id']
        owner_ref = item['owner_ref']
        foreign_token = auth['tokens'][next_owner[owner_ref]]
        idempotency = {'Idempotency-Key': _idempotency(
            scenario['run_id'], 'foreign', item['document']['case_id'])}
        surfaces = (
            ('GET', '', None, None),
            ('GET', 'draft/', None, None),
            ('GET', 'source-url/', None, None),
            ('POST', 'confirm/', idempotency, {
                'draft_version': 1,
                'planner_confirmed_source_match': True,
                'planner_confirmed_unread_pages': True,
            }),
            ('POST', 'cancel/', idempotency, {}),
        )
        for method, suffix, headers, body in surfaces:
            try:
                foreign = transport.request(
                    method, base + f'insurance-imports/{job_id}/{suffix}',
                    token=foreign_token, headers=headers, json_body=body)
            except TransportError as exc:
                failures.append(_failure(
                    item['document']['case_id'], 'foreign_scope',
                    code=exc.kind.upper() + '_ERROR'))
                continue
            except Exception:
                failures.append(_failure(
                    item['document']['case_id'], 'foreign_scope',
                    code='TRANSPORT_ERROR'))
                continue
            if foreign.status != 404:
                cross_visible += 1
                failures.append(_failure(
                    item['document']['case_id'], 'foreign_scope', foreign))
    return cross_visible, owner_customer_mismatch, response_job_mismatch, \
        queue_wait, end_to_end, provider


def _duplicate_job_counts(results: list[dict[str, Any]]):
    jobs_by_key: dict[tuple[Any, ...], set[str]] = {}
    keys_by_job: dict[str, set[tuple[Any, ...]]] = {}
    for item in results:
        if item['job_id'] is None:
            continue
        document = item['document']
        key = (
            item['owner_ref'], item['customer_id'], document['hash_group'],
            document['intent'], document['portfolio_type'],
            document.get('target_insurance_id'),
        )
        observed = item.get('observed_job_ids') or {item['job_id']}
        jobs_by_key.setdefault(key, set()).update(observed)
        keys_by_job.setdefault(item['job_id'], set()).add(key)
    excess = sum(max(0, len(job_ids) - 1) for job_ids in jobs_by_key.values())
    reused = sum(max(0, len(keys) - 1) for keys in keys_by_job.values())
    return excess, reused


def _run_confirm_groups(
    *, base: str, scenario: Mapping[str, Any], auth: Mapping[str, Any],
    transport: Transport, prepared_details: Mapping[str, dict[str, Any]],
    sleep: Callable[[float], None], failures: list[dict[str, Any]],
):
    prepared = {item['job_ref']: item for item in scenario['prepared_jobs']}
    both_adds_preserved = 0
    replace_success = 0
    replace_target_changed = 0
    stale_overwrite = 0
    analysis_difference: int | None = 0
    for group in scenario['confirm_groups']:
        release = threading.Event()

        def confirm(job_ref):
            release.wait()
            fixture = prepared[job_ref]
            detail = prepared_details[job_ref]
            body = {
                'draft_version': detail['draft_version'],
                'planner_confirmed_source_match': True,
                'planner_confirmed_unread_pages': True,
            }
            if detail.get('target_insurance_version') is not None:
                body['target_insurance_version'] = detail['target_insurance_version']
            headers = {'Idempotency-Key': _idempotency(
                scenario['run_id'], 'confirm', job_ref)}
            try:
                response = request_with_retry(lambda: transport.request(
                    'POST', base + f"insurance-imports/{fixture['job_id']}/confirm/",
                    token=auth['tokens'][fixture['owner_ref']], headers=headers,
                    json_body=body), sleep=sleep)
            except TransportError as exc:
                return job_ref, None, exc.kind.upper() + '_ERROR'
            except Exception:
                return job_ref, None, 'TRANSPORT_ERROR'
            return job_ref, response, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(confirm, ref) for ref in group['job_refs']]
            release.set()
            outcomes = [future.result(timeout=120) for future in futures]
        responses = [item[1] for item in outcomes if item[1] is not None]
        for job_ref, response, transport_code in outcomes:
            if response is None:
                failures.append(_failure(
                    group['group_ref'], 'confirm', code=transport_code))
            elif not (response.status == 200 or (
                    response.status == 409
                    and _safe_code(response) == 'IMPORT_TARGET_CHANGED')):
                failures.append(_failure(group['group_ref'], 'confirm', response))
        statuses = sorted(response.status for response in responses)
        if group['expected'] == 'both_confirmed':
            add_responses = {
                job_ref: response for job_ref, response, _ in outcomes
                if response is not None and response.status == 200
            }
            insurance_ids = {
                response.body.get('insurance_id')
                for response in add_responses.values()
                if type(response.body.get('insurance_id')) is int
                and response.body['insurance_id'] > 0
            }
            response_links_match = all(
                response.body.get('job_id') == prepared[job_ref]['job_id']
                and response.body.get('confirmed_coverage_count')
                == prepared[job_ref]['expected_confirmed_coverage_count']
                for job_ref, response in add_responses.items()
            )
            if (statuses == [200, 200] and len(add_responses) == 2
                    and len(insurance_ids) == 2 and response_links_match):
                both_adds_preserved = 1
        else:
            replace_success += sum(response.status == 200 for response in responses)
            replace_target_changed += sum(
                response.status == 409
                and _safe_code(response) == 'IMPORT_TARGET_CHANGED'
                for response in responses)
        final_statuses = []
        for job_ref in group['job_refs']:
            fixture = prepared[job_ref]
            try:
                final = request_with_retry(lambda fixture=fixture: transport.request(
                    'GET', base + f"insurance-imports/{fixture['job_id']}/",
                    token=auth['tokens'][fixture['owner_ref']]), sleep=sleep)
            except TransportError as exc:
                final = None
                failures.append(_failure(
                    group['group_ref'], 'confirm_state',
                    code=exc.kind.upper() + '_ERROR'))
            except Exception:
                final = None
                failures.append(_failure(
                    group['group_ref'], 'confirm_state',
                    code='TRANSPORT_ERROR'))
            final_statuses.append(
                final.body.get('status')
                if final is not None and final.status == 200 else None)
        if group['expected'] == 'both_confirmed':
            if sorted(final_statuses) != ['confirmed', 'confirmed']:
                both_adds_preserved = 0
                stale_overwrite += 1
        elif sorted(final_statuses) != ['confirmed', 'review_required']:
            stale_overwrite += 1
        try:
            analysis = request_with_retry(lambda: transport.request(
                'GET', base + f"customers/{group['analysis_customer_id']}/heatmap/",
                token=auth['tokens'][group['owner_ref']]), sleep=sleep)
        except TransportError as exc:
            analysis = None
            failures.append(_failure(
                group['group_ref'], 'analysis',
                code=exc.kind.upper() + '_ERROR'))
        except Exception:
            analysis = None
            failures.append(_failure(
                group['group_ref'], 'analysis', code='TRANSPORT_ERROR'))
        measured = (_sum_held_amount(analysis.body)
                    if analysis is not None and analysis.status == 200 else None)
        if measured is None:
            analysis_difference = None
            if group['expected'] == 'both_confirmed':
                both_adds_preserved = 0
            if analysis is not None:
                failures.append(_failure(group['group_ref'], 'analysis', analysis))
        elif analysis_difference is not None:
            difference = abs(
                measured - group['expected_analysis_total_amount'])
            analysis_difference += difference
            if group['expected'] == 'both_confirmed' and difference:
                both_adds_preserved = 0
    return {
        'both_adds_preserved': both_adds_preserved,
        'replace_success': replace_success,
        'replace_target_changed_409': replace_target_changed,
        'stale_overwrite': stale_overwrite,
        'duplicate_analysis_amount': analysis_difference,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _iter_keys_and_values(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _iter_keys_and_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_keys_and_values(item)
    else:
        yield value


def _document_strings(scenario: Mapping[str, Any]) -> set[str]:
    strings = {SYNTHETIC_MARKER}
    paths = {
        document['file_path']
        for owner in scenario['owners'] for document in owner['documents']
    }
    for path in paths:
        try:
            data = Path(path).read_bytes()
        except OSError:
            raise PreflightError() from None
        for matched in re.findall(rb'[ -~]{8,}', data):
            strings.add(matched.decode('ascii'))
    return strings


def scan_privacy(
    result: Mapping[str, Any], *, tokens: Iterable[str],
    file_paths: Iterable[str], document_strings: Iterable[str],
    raw_response_strings: Iterable[str], job_ids: Iterable[str],
    customer_ids: Iterable[int], stdout_payload: str,
) -> dict[str, bool]:
    serialized = _canonical_result_payload(result).decode('utf-8')
    keys_and_values = list(_iter_keys_and_values(result))
    string_values = [
        value for value in keys_and_values if isinstance(value, str)]
    customer_numbers = {
        value for value in customer_ids if type(value) is int and value > 0}
    customer_strings = {str(value) for value in customer_numbers}
    contains_customer_id = (
        any(
            type(value) is int and value in customer_numbers
            for value in keys_and_values)
        or any(
            _identifier_in_text(value, identifier)
            for value in string_values for identifier in customer_strings)
        or any(
            _identifier_in_text(serialized, identifier)
            for identifier in customer_strings)
    )
    return {
        'contains_auth_token': any(
            token and (token in serialized or token in stdout_payload)
            for token in tokens),
        'contains_file_path': any(
            path and path in serialized for path in file_paths)
            or any(value.startswith('/') for value in string_values),
        'contains_document_text': any(
            value and value in serialized for value in document_strings),
        'contains_raw_response': any(
            value and value in serialized for value in raw_response_strings),
        'contains_job_id': any(
            value and value in serialized for value in job_ids),
        'contains_customer_id': contains_customer_id,
    }


def _canonical_result_payload(result: Mapping[str, Any]) -> bytes:
    return (json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        + '\n').encode('utf-8')


def write_private_result(
    path: str | os.PathLike[str], result: Mapping[str, Any],
    *, canonical_payload: bytes | None = None,
):
    target = Path(path)
    if not target.parent.is_dir() or target.exists():
        raise PreflightError()
    expected_payload = _canonical_result_payload(result)
    if canonical_payload is not None and canonical_payload != expected_payload:
        raise PrivacyError()
    payload = canonical_payload if canonical_payload is not None else expected_payload
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = None
    try:
        descriptor = os.open(target, flags, 0o600)
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError()
            remaining = remaining[written:]
    except OSError:
        raise PreflightError() from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not _private_mode(target):
        raise PreflightError()


def execute_and_report(
    *,
    base_url: str,
    scenario: dict[str, Any],
    auth: dict[str, Any],
    result_path: str | os.PathLike[str],
    workers: int,
    execute_staging: str,
    max_intake_p95_ms: float,
    max_owner_wait_p95_ms: float,
    transport: Transport,
    stdout: TextIO,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    base = validate_execution(
        base_url=base_url, scenario=scenario,
        execute_staging=execute_staging,
        max_intake_p95_ms=max_intake_p95_ms,
        max_owner_wait_p95_ms=max_owner_wait_p95_ms,
        tokens=auth['tokens'].values(),
    )
    private_root = _validate_private_root(scenario['private_root'])
    result_path = Path(result_path)
    if workers != 60 or result_path.exists() or not result_path.parent.is_dir():
        raise PreflightError()
    _require_under_private_root(result_path, private_root, output=True)
    tracked_transport = PrivacyTrackingTransport(transport)
    stdout.write('LOAD START\n')
    prepared_details = _remote_preflight(
        base, scenario, auth, tracked_transport, sleep)
    started_at = _utc_now()
    failures: list[dict[str, Any]] = []
    intake, accepted, unexpected = _run_intake(
        base=base, scenario=scenario, auth=auth, transport=tracked_transport,
        workers=workers, sleep=sleep, clock=clock, failures=failures)
    cross_visible, owner_mismatch, response_mismatch, queue_wait, end_to_end, \
        provider = \
        _run_scope_audit(
            base=base, scenario=scenario, auth=auth,
            transport=tracked_transport, results=intake, sleep=sleep,
            failures=failures, workers=workers, clock=clock)
    duplicate_excess, reused_jobs = _duplicate_job_counts(intake)
    response_mismatch += reused_jobs
    confirm = _run_confirm_groups(
        base=base, scenario=scenario, auth=auth, transport=tracked_transport,
        prepared_details=prepared_details, sleep=sleep, failures=failures)
    intake_metric = metric_summary(item['elapsed'] for item in intake)
    owner_wait_values = []
    for owner in scenario['owners']:
        values = [item['elapsed'] for item in intake
                  if item['owner_ref'] == owner['owner_ref']]
        if len(values) == 3:
            owner_wait_values.append(max(values))
    owner_metric = metric_summary(owner_wait_values)
    queue_metric = metric_summary(
        value for values in queue_wait.values() for value in values)
    end_metric = metric_summary(
        value for values in end_to_end.values() for value in values)
    owner_queue_metric = metric_summary(
        metric_summary(values)['p95']
        for values in queue_wait.values() if len(values) == 3)
    owner_end_metric = metric_summary(
        metric_summary(values)['p95']
        for values in end_to_end.values() if len(values) == 3)
    performance_passed = bool(
        intake_metric['count'] == 60
        and owner_metric['count'] == 20
        and owner_queue_metric['count'] == 20
        and owner_end_metric['count'] == 20
        and intake_metric['p95'] <= max_intake_p95_ms
        and owner_end_metric['p95'] <= max_owner_wait_p95_ms
    )
    provider_complete = bool(
        queue_metric['count'] == 60 and end_metric['count'] == 60
        and owner_queue_metric['count'] == 20
        and owner_end_metric['count'] == 20
        and provider == {
            'review_required_count': 60,
            'not_started_count': 0,
            'unfinished_count': 0,
            'terminal_failure_count': 0,
        })
    correctness = {
        'accepted_202': accepted,
        'unexpected_http': unexpected,
        'cross_owner_visible': cross_visible,
        'owner_customer_mismatch': owner_mismatch,
        'response_job_mismatch': response_mismatch,
        'duplicate_job_excess': duplicate_excess,
        **confirm,
    }
    correctness_passed = correctness == {
        'accepted_202': 60,
        'unexpected_http': 0,
        'cross_owner_visible': 0,
        'owner_customer_mismatch': 0,
        'response_job_mismatch': 0,
        'duplicate_job_excess': 0,
        'both_adds_preserved': 1,
        'replace_success': 1,
        'replace_target_changed_409': 1,
        'stale_overwrite': 0,
        'duplicate_analysis_amount': 0,
    }
    passed = correctness_passed and performance_passed \
        and provider_complete and not failures
    result = {
        'schema_version': RESULT_SCHEMA,
        'run_id': scenario['run_id'],
        'started_at': started_at,
        'finished_at': _utc_now(),
        'configuration': {
            'workers': workers,
            'owner_count': 20,
            'request_count': 60,
            'max_intake_p95_ms': max_intake_p95_ms,
            'max_owner_wait_p95_ms': max_owner_wait_p95_ms,
        },
        'correctness': correctness,
        'latency_ms': {
            'intake': intake_metric,
            'owner_batch_wait': owner_metric,
            'queue_wait': queue_metric,
            'end_to_end': end_metric,
            'owner_queue_p95': owner_queue_metric,
            'owner_end_to_end_p95': owner_end_metric,
        },
        'provider': provider,
        'provider_complete': provider_complete,
        'performance_passed': performance_passed,
        'failures': failures,
        'privacy': {field: False for field in PRIVACY_FIELDS},
        'passed': passed,
    }
    final_stdout = 'LOAD PASS\n' if passed else 'LOAD FAIL\n'
    document_paths = {
        document['file_path']
        for owner in scenario['owners'] for document in owner['documents']
    }
    job_ids = {
        item['job_id'] for item in scenario['prepared_jobs']
    } | {item['job_id'] for item in intake if item['job_id']}
    privacy = scan_privacy(
        result,
        tokens=auth['tokens'].values(),
        file_paths={
            str(private_root), str(result_path), *document_paths},
        document_strings=_document_strings(scenario),
        raw_response_strings=tracked_transport.raw_strings,
        job_ids=job_ids,
        customer_ids={owner['customer_id'] for owner in scenario['owners']},
        stdout_payload='LOAD START\n' + final_stdout,
    )
    result['privacy'] = privacy
    canonical_payload = _canonical_result_payload(result)
    final_privacy = scan_privacy(
        result,
        tokens=auth['tokens'].values(),
        file_paths={
            str(private_root), str(result_path), *document_paths},
        document_strings=_document_strings(scenario),
        raw_response_strings=tracked_transport.raw_strings,
        job_ids=job_ids,
        customer_ids={owner['customer_id'] for owner in scenario['owners']},
        stdout_payload='LOAD START\n' + final_stdout,
    )
    if privacy != final_privacy or any(final_privacy.values()):
        raise PrivacyError()
    write_private_result(
        result_path, result, canonical_payload=canonical_payload)
    stdout.write(final_stdout)
    return 0 if passed else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Validate the insurance import staging concurrency gate.')
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--scenario', required=True)
    parser.add_argument('--auth-file', required=True)
    parser.add_argument('--result', required=True)
    parser.add_argument('--workers', required=True, type=int)
    parser.add_argument('--execute-staging', required=True)
    parser.add_argument('--max-intake-p95-ms', required=True, type=float)
    parser.add_argument('--max-owner-wait-p95-ms', required=True, type=float)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    transport: Transport | None = None,
    stdout: TextIO | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    output = stdout or sys.stdout
    try:
        args = _parser().parse_args(argv)
        scenario, auth = load_and_validate_inputs(args.scenario, args.auth_file)
        return execute_and_report(
            base_url=args.base_url, scenario=scenario, auth=auth,
            result_path=args.result, workers=args.workers,
            execute_staging=args.execute_staging,
            max_intake_p95_ms=args.max_intake_p95_ms,
            max_owner_wait_p95_ms=args.max_owner_wait_p95_ms,
            transport=transport or UrllibTransport(), stdout=output, sleep=sleep,
        )
    except SecretCollisionError:
        return 2
    except PreflightError:
        output.write('LOAD PREFLIGHT FAIL\n')
        return 2
    except TransportError:
        output.write('LOAD PREFLIGHT FAIL\n')
        return 2
    except PrivacyError:
        output.write('LOAD FAIL\n')
        return 1
    except Exception:
        output.write('LOAD FAIL\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
