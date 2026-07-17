"""Sentry 전송 직전 보험 원본과 제공자 payload를 제거한다."""

import math
import re
from uuid import UUID


_EXCEPTION_TYPE_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_.]{0,127}\Z')
_OUTCOME_RE = re.compile(r'[a-z][a-z0-9_]{0,39}\Z')
_EVENT_ID_RE = re.compile(r'[0-9a-fA-F]{32}\Z')
_SPAN_ID_RE = re.compile(r'[0-9a-fA-F]{16}\Z')
_SAFE_TRACE_OPERATIONS = frozenset({
    'cache.get', 'cache.set', 'celery.task', 'db', 'db.sql.query', 'function',
    'http.client', 'http.server', 'middleware.django', 'queue.process',
    'queue.publish', 'template.render', 'view.render',
})
_SAFE_TRACE_STATUSES = frozenset({
    'aborted', 'already_exists', 'cancelled', 'data_loss', 'deadline_exceeded',
    'failed_precondition', 'internal_error', 'invalid_argument', 'not_found',
    'ok', 'out_of_range', 'permission_denied', 'resource_exhausted', 'unauthenticated',
    'unavailable', 'unimplemented', 'unknown',
})


def _safe_extra(extra):
    safe = {}
    job_uuid = extra.get('job_uuid')
    if isinstance(job_uuid, str):
        try:
            if str(UUID(job_uuid)) == job_uuid.lower():
                safe['job_uuid'] = job_uuid
        except ValueError:
            pass

    exception_type = extra.get('exception_type')
    if isinstance(exception_type, str) and _EXCEPTION_TYPE_RE.fullmatch(exception_type):
        safe['exception_type'] = exception_type

    outcome = extra.get('outcome')
    if isinstance(outcome, str) and _OUTCOME_RE.fullmatch(outcome):
        safe['outcome'] = outcome
    return safe


def _drop_frame_variables(value):
    if isinstance(value, dict):
        value.pop('vars', None)
        for child in value.values():
            _drop_frame_variables(child)
    elif isinstance(value, list):
        for child in value:
            _drop_frame_variables(child)


def _safe_timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def _safe_trace_metadata(value, *, include_parent=False):
    if not isinstance(value, dict):
        return {}

    safe = {}
    for key, pattern in (('trace_id', _EVENT_ID_RE), ('span_id', _SPAN_ID_RE)):
        item = value.get(key)
        if isinstance(item, str) and pattern.fullmatch(item):
            safe[key] = item.lower()
    if include_parent:
        parent_span_id = value.get('parent_span_id')
        if isinstance(parent_span_id, str) and _SPAN_ID_RE.fullmatch(parent_span_id):
            safe['parent_span_id'] = parent_span_id.lower()

    operation = value.get('op')
    if operation in _SAFE_TRACE_OPERATIONS:
        safe['op'] = operation
    status = value.get('status')
    if status in _SAFE_TRACE_STATUSES:
        safe['status'] = status
    for key in ('start_timestamp', 'timestamp'):
        timestamp = _safe_timestamp(value.get(key))
        if timestamp is not None:
            safe[key] = timestamp
    return safe


def scrub_event(event, hint):
    """Mutate an event to retain diagnostics that cannot contain document text."""
    request = event.get('request')
    if isinstance(request, dict):
        method = request.get('method')
        event['request'] = {'method': method} if isinstance(method, str) else {}
    else:
        event.pop('request', None)

    # These containers accept arbitrary application/provider data. None is
    # required to diagnose an import job because safe identifiers live in extra.
    for key in ('breadcrumbs', 'contexts', 'user', 'spans', 'tags', 'fingerprint'):
        event.pop(key, None)

    _drop_frame_variables(event.get('exception'))
    _drop_frame_variables(event.get('threads'))

    extra = event.get('extra')
    if isinstance(extra, dict):
        event['extra'] = _safe_extra(extra)
    else:
        event.pop('extra', None)

    # Exception/message 문자열에 원문 조각이 섞일 수 있어 형식명 외의 자유문을 보내지 않는다.
    exception = event.get('exception')
    if isinstance(exception, dict):
        for value in exception.get('values', []):
            if isinstance(value, dict):
                value.pop('value', None)
    event.pop('message', None)
    event.pop('logentry', None)
    return event


def scrub_transaction(event, hint):
    """Build a fail-closed transaction containing only trace IDs, ops, and timing."""
    contexts = event.get('contexts')
    trace = contexts.get('trace') if isinstance(contexts, dict) else None
    safe_trace = _safe_trace_metadata(trace)
    operation = safe_trace.get('op', 'transaction')

    safe = {'type': 'transaction', 'transaction': operation}
    event_id = event.get('event_id')
    if isinstance(event_id, str) and _EVENT_ID_RE.fullmatch(event_id):
        safe['event_id'] = event_id.lower()
    for key in ('start_timestamp', 'timestamp'):
        timestamp = _safe_timestamp(event.get(key))
        if timestamp is not None:
            safe[key] = timestamp
    if safe_trace:
        safe['contexts'] = {'trace': safe_trace}

    safe_spans = []
    spans = event.get('spans')
    if isinstance(spans, list):
        for span in spans:
            safe_span = _safe_trace_metadata(span, include_parent=True)
            if safe_span:
                safe_spans.append(safe_span)
    if safe_spans:
        safe['spans'] = safe_spans
    return safe
