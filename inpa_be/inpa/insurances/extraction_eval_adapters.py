"""Lazy, non-persisting live adapters for private extraction evaluation.

Provider-facing application modules are imported only inside adapter methods or
the post-validation runtime factory. Predictions remain in memory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from typing import Any

from .extraction_eval import (
    EvalContractError,
    EvalObservation,
    EvalRunContext,
    PREDICTION_SCHEMA_VERSION,
)


_LINE_ID_RE = re.compile(r'^p(?P<page>\d+)-l(?P<line>\d+)$')
_DEFAULT_COST = object()


def _tokens(usage, name):
    value = (
        usage.get(name, 0)
        if isinstance(usage, dict)
        else getattr(usage, name, 0)
    ) if usage is not None else 0
    return int(value) if type(value) in {int, float} and value >= 0 else 0


def _canonical_date(value):
    from .date_utils import parse_insurance_date
    parsed = parse_insurance_date(value)
    return parsed.isoformat() if parsed is not None else None


def _source_ref(line_ids):
    positions = []
    for line_id in line_ids or ():
        match = _LINE_ID_RE.fullmatch(str(line_id))
        if match is None:
            return None
        positions.append((int(match.group('page')), int(match.group('line'))))
    if not positions or len({page for page, _line in positions}) != 1:
        return None
    page = positions[0][0]
    lines = [line for _page, line in positions]
    return {'page': page, 'line_start': min(lines), 'line_end': max(lines)}


def _policy_review_fields(policy_issues):
    field_map = {
        'company_code': 'carrier_code',
        'product_name': 'product_name',
        'contract_date': 'contract_date',
        'expiry_date': 'expiry_date',
        'monthly_premium': 'monthly_premium',
    }
    return [
        target
        for source, target in field_map.items()
        if source in policy_issues
    ]


@contextmanager
def _private_eval_logger_guard(logger: logging.Logger):
    """Prevent legacy tracebacks from emitting provider response details."""
    previous = logger.disabled
    logger.disabled = True
    try:
        yield
    finally:
        logger.disabled = previous


def _failure(context, code, *, error_type=None, usage=None,
             latency_ms=None, pipeline_latency_ms=None,
             estimated_cost_krw=_DEFAULT_COST):
    payload = {
        'outcome': 'provider_failure',
        'run_contract': context.model_dump(mode='json'),
        'prediction': None,
        'error_code': code,
        'error_type': error_type,
        'input_tokens': _tokens(usage, 'input_tokens'),
        'output_tokens': _tokens(usage, 'output_tokens'),
        'cache_read_input_tokens': _tokens(
            usage, 'cache_read_input_tokens'),
        'cache_creation_input_tokens': _tokens(
            usage, 'cache_creation_input_tokens'),
        'estimated_cost_krw': (
            _estimate_cost(context.model_id, usage)
            if estimated_cost_krw is _DEFAULT_COST
            else estimated_cost_krw
        ),
        'provider_latency_ms': latency_ms,
        'pipeline_latency_ms': pipeline_latency_ms,
    }
    return EvalObservation.model_validate(payload)


def _actual_context(context, model_id):
    payload = context.model_dump(mode='json')
    payload['model_id'] = model_id
    return EvalRunContext.model_validate(payload)


def _estimate_cost(model_id, usage):
    from inpa.billing.pricing import estimate_cost_krw
    return float(estimate_cost_krw(model_id, usage))


def _snapshot_digest(payload):
    digest = hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')).hexdigest()
    return f'sha256:{digest}'


def _legacy_prompt_version():
    from inpa.core.ocr import claude_parser

    digest = hashlib.sha256('\n'.join((
        claude_parser._SYSTEM_PROMPT,
        claude_parser._COVERAGE_CATEGORIES,
        claude_parser._USER_PROMPT_TEMPLATE,
    )).encode('utf-8')).hexdigest()
    return f'legacy-prompt-sha256:{digest}'


class LegacyExtractionAdapter:
    def __init__(self, normalization_lookup):
        self.normalization_lookup = normalization_lookup

    def _normalizer(self, raw_name, carrier_code):
        if not isinstance(raw_name, str) or type(carrier_code) is not int:
            return None
        return self.normalization_lookup.get(
            (carrier_code, raw_name),
            self.normalization_lookup.get(
                (carrier_code, raw_name.replace(' ', ''))),
        )

    def run(self, case, context):
        pipeline_started = time.perf_counter()
        from inpa.core.ocr import claude_parser
        from inpa.insurances import views
        from .import_contract import PDFImportError
        from .import_pdf import extract_pdf

        try:
            with case.pdf_path.open('rb') as source:
                extracted = extract_pdf(source)
        except PDFImportError as exc:
            code = (
                exc.code
                if re.fullmatch(r'[A-Z][A-Z0-9_]{1,63}', exc.code)
                else 'LEGACY_PDF_FAILED'
            )
            return _failure(
                context,
                code,
                error_type=(
                    'pdf_privacy'
                    if code == 'PII_REDACTION_UNCERTAIN'
                    else 'pdf_parse'
                ),
                pipeline_latency_ms=round(
                    (time.perf_counter() - pipeline_started) * 1000),
            )
        lines = [line.text_masked for line in extracted.masked_lines]

        meta = {}
        provider_started = time.perf_counter()
        with _private_eval_logger_guard(claude_parser.logger):
            ocr = claude_parser.claude_parse(
                lines, normalizer=self._normalizer, meta=meta)
        provider_latency_ms = round(
            (time.perf_counter() - provider_started) * 1000)
        if ocr is None:
            outcome = str(meta.get('outcome') or '')
            code = {
                'no_key': 'API_KEY_NOT_CONFIGURED',
                'no_model': 'MODEL_NOT_CONFIGURED',
                'package_missing': 'PROVIDER_PACKAGE_MISSING',
                'timeout': 'PROVIDER_UNAVAILABLE',
                'api_error': 'PROVIDER_REQUEST_REJECTED',
                'json_invalid': 'SCHEMA_INVALID',
            }.get(outcome, 'LEGACY_EXTRACTION_FAILED')
            return _failure(
                _actual_context(
                    context, str(meta.get('model') or context.model_id)),
                code,
                usage=meta.get('usage'),
                latency_ms=provider_latency_ms,
                pipeline_latency_ms=round(
                    (time.perf_counter() - pipeline_started) * 1000),
            )

        loss_head = ocr.dict_loss_head_data
        life_head = ocr.dict_life_head_data
        if life_head.get('생명보험', -1) >= 0:
            head = life_head
            carrier_code = 200 + life_head['생명보험']
            expiry_date = None
        elif loss_head.get('손해보험', -1) >= 0:
            head = loss_head
            carrier_code = loss_head['손해보험']
            expiry_date = _canonical_date(loss_head.get('만기일'))
        else:
            head = loss_head
            carrier_code = None
            expiry_date = _canonical_date(loss_head.get('만기일'))

        raw_map = getattr(ocr, '_raw_name_by_case', None) or {}
        rows = []
        row_number = 0
        for category, subcategories in ocr.dict_detail_data.items():
            for subcategory, details in subcategories.items():
                for detail_name, values in details.items():
                    for value in values:
                        parsed = views._parse_value(value)
                        if parsed is None:
                            continue
                        row_number += 1
                        raw_name = raw_map.get(
                            (category, subcategory, detail_name, value))
                        rows.append({
                            'row_id': f'legacy-{row_number:05d}',
                            'source_ref': None,
                            'raw_name': raw_name or detail_name,
                            'assurance_amount': parsed['amount'],
                            'premium': parsed['premium'],
                            'standard_path': [
                                category, subcategory, detail_name],
                            'state': 'review_ready',
                            'review_fields': [],
                            'reason_codes': [],
                        })
        surfaced = [
            {
                'source_ref': None,
                'raw_name': raw_name,
                'state': 'unmatched',
                'reason_codes': ['LEGACY_UNMATCHED_COVERAGE'],
            }
            for raw_name in getattr(ocr, '_unmatched_coverages', ())
            if isinstance(raw_name, str) and raw_name.strip()
        ]
        usage = meta.get('usage')
        model_id = str(meta.get('model') or context.model_id)
        actual_context = _actual_context(context, model_id)
        prediction = {
            'schema_version': PREDICTION_SCHEMA_VERSION,
            'case_id': case.case_id,
            'run_contract': actual_context.model_dump(mode='json'),
            'policy': {
                'carrier_code': carrier_code,
                'product_name': head.get('상품명') or None,
                'contract_date': _canonical_date(head.get('계약일')),
                'expiry_date': expiry_date,
                'monthly_premium': (
                    head.get('월납입보험료')
                    if type(head.get('월납입보험료')) is int else None),
            },
            'policy_review_fields': [],
            'coverage_rows': rows,
            'surfaced_items': surfaced,
        }
        return EvalObservation.model_validate({
            'outcome': 'success',
            'run_contract': actual_context.model_dump(mode='json'),
            'prediction': prediction,
            'input_tokens': _tokens(usage, 'input_tokens'),
            'output_tokens': _tokens(usage, 'output_tokens'),
            'cache_read_input_tokens': _tokens(
                usage, 'cache_read_input_tokens'),
            'cache_creation_input_tokens': _tokens(
                usage, 'cache_creation_input_tokens'),
            'estimated_cost_krw': _estimate_cost(model_id, usage),
            'provider_latency_ms': provider_latency_ms,
            'pipeline_latency_ms': round(
                (time.perf_counter() - pipeline_started) * 1000),
        })


class ReviewExtractionAdapter:
    @staticmethod
    def _extractor_module():
        from . import import_claude
        return import_claude

    @staticmethod
    def _estimated_cost(model_id, usage):
        return _estimate_cost(model_id, usage)

    def run(self, case, context):
        pipeline_started = time.perf_counter()
        import_claude = self._extractor_module()
        from .import_contract import PDFImportError
        from .import_pdf import extract_pdf
        from .import_validation import validate_draft

        try:
            with case.pdf_path.open('rb') as source:
                extracted = extract_pdf(source)
        except PDFImportError as exc:
            code = (
                exc.code
                if re.fullmatch(r'[A-Z][A-Z0-9_]{1,63}', exc.code)
                else 'REVIEW_PDF_FAILED'
            )
            return _failure(
                context,
                code,
                error_type=(
                    'pdf_privacy'
                    if code == 'PII_REDACTION_UNCERTAIN'
                    else 'pdf_parse'
                ),
                pipeline_latency_ms=round(
                    (time.perf_counter() - pipeline_started) * 1000),
                estimated_cost_krw=self._estimated_cost(context.model_id, None),
            )
        try:
            result = import_claude.extract(
                extracted.masked_lines,
                extracted.candidates,
                context.schema_version,
            )
        except import_claude.ExtractionFailure as exc:
            failure_context = _actual_context(
                context, exc.model_id or context.model_id)
            return _failure(
                failure_context,
                exc.code if re.fullmatch(r'[A-Z][A-Z0-9_]{1,63}', exc.code)
                else 'REVIEW_EXTRACTION_FAILED',
                error_type=(
                    exc.error_type
                    if re.fullmatch(
                        r'[A-Za-z_][A-Za-z0-9_]{0,127}',
                        exc.error_type or '')
                    else None
                ),
                usage=exc.usage,
                latency_ms=exc.latency_ms,
                pipeline_latency_ms=round(
                    (time.perf_counter() - pipeline_started) * 1000),
                estimated_cost_krw=self._estimated_cost(
                    failure_context.model_id, exc.usage),
            )
        validated = validate_draft(
            extracted.masked_lines,
            extracted.candidates,
            result.payload,
        )
        issues_by_row: dict[str, list[Any]] = {}
        policy_issues: dict[str, list[Any]] = {}
        for issue in validated.issues:
            if issue.scope == 'coverage' and issue.row_id:
                issues_by_row.setdefault(issue.row_id, []).append(issue)
            elif issue.scope == 'policy' and issue.field:
                policy_issues.setdefault(issue.field, []).append(issue)

        policy = validated.draft.get('policy') or {}
        value = lambda field: (policy.get(field) or {}).get('value')
        policy_review_fields = _policy_review_fields(policy_issues)
        rows = []
        for draft_row in validated.draft.get('coverage_rows') or []:
            issues = issues_by_row.get(draft_row.get('row_id'), [])
            review_fields = []
            for issue in issues:
                if issue.field in {
                    'assurance_amount', 'premium', 'standard_path',
                    'standard_category', 'standard_subcategory',
                    'standard_detail_name',
                }:
                    field = (
                        issue.field
                        if issue.field in {'assurance_amount', 'premium'}
                        else 'standard_path'
                    )
                    if field not in review_fields:
                        review_fields.append(field)
            standard_values = [
                draft_row.get('standard_category'),
                draft_row.get('standard_subcategory'),
                draft_row.get('standard_detail_name'),
            ]
            rows.append({
                'row_id': draft_row['row_id'],
                'source_ref': _source_ref(
                    draft_row.get('evidence_line_ids')),
                'raw_name': draft_row.get('raw_name') or 'private-unmatched',
                'assurance_amount': draft_row.get('assurance_amount'),
                'premium': draft_row.get('premium'),
                'standard_path': (
                    standard_values if all(standard_values) else None),
                'state': draft_row.get('state') or 'needs_review',
                'review_fields': review_fields,
                'reason_codes': list(dict.fromkeys(
                    issue.code for issue in issues)),
            })
        surfaced = [
            {
                'source_ref': _source_ref(candidate.evidence_line_ids),
                'raw_name': (
                    candidate.text_masked
                    if _source_ref(candidate.evidence_line_ids) is None
                    else None),
                'state': 'needs_review',
                'reason_codes': ['LOCAL_COVERAGE_CANDIDATE'],
            }
            for candidate in extracted.candidates
        ]
        prediction = {
            'schema_version': PREDICTION_SCHEMA_VERSION,
            'case_id': case.case_id,
            'run_contract': _actual_context(
                context, result.model_id).model_dump(mode='json'),
            'policy': {
                'carrier_code': value('company_code'),
                'product_name': value('product_name'),
                'contract_date': _canonical_date(value('contract_date')),
                'expiry_date': _canonical_date(value('expiry_date')),
                'monthly_premium': value('monthly_premium'),
            },
            'policy_review_fields': policy_review_fields,
            'coverage_rows': rows,
            'surfaced_items': surfaced,
        }
        usage = {
            'input_tokens': result.input_tokens,
            'output_tokens': result.output_tokens,
            'cache_read_input_tokens': result.cache_read_input_tokens,
            'cache_creation_input_tokens': (
                result.cache_creation_input_tokens),
        }
        return EvalObservation.model_validate({
            'outcome': 'success',
            'run_contract': _actual_context(
                context, result.model_id).model_dump(mode='json'),
            'prediction': prediction,
            'input_tokens': result.input_tokens,
            'output_tokens': result.output_tokens,
            'cache_read_input_tokens': result.cache_read_input_tokens,
            'cache_creation_input_tokens': (
                result.cache_creation_input_tokens),
            'estimated_cost_krw': self._estimated_cost(
                result.model_id, usage),
            'provider_latency_ms': result.latency_ms,
            'pipeline_latency_ms': round(
                (time.perf_counter() - pipeline_started) * 1000),
        })


class OpenAIReviewExtractionAdapter(ReviewExtractionAdapter):
    @staticmethod
    def _extractor_module():
        from . import import_openai_eval
        return import_openai_eval

    @staticmethod
    def _estimated_cost(_model_id, _usage):
        # The evaluator has no approved OpenAI price table. Token counts remain
        # authoritative; reporting Claude fallback pricing would be misleading.
        return 0.0


def _normalization_snapshots_and_lookup():
    """Read a PII-free normalization snapshot without mutating hit counts."""
    from inpa.analysis.models import NormalizationDict
    from inpa.core.ocr import claude_parser, ocrparsing
    from inpa.insurances.import_validation import (
        CARRIER_CODE_BY_NAME,
        STANDARD_COVERAGE_PATHS,
    )

    rows = list(
        NormalizationDict.objects
        .filter(source=NormalizationDict.SOURCE_ADMIN_VERIFIED)
        .select_related('std_detail__sub_category__category')
        .order_by('company', 'raw_name', 'pk')
    )
    lookup = {}
    digest_rows = []
    for row in rows:
        detail = row.std_detail
        subcategory = detail.sub_category
        path = (subcategory.category.name, subcategory.name, detail.name)
        lookup[(row.company, row.raw_name)] = path
        lookup[(row.company, row.raw_name.replace(' ', ''))] = path
        digest_rows.append([row.company, row.raw_name, *path])
    standard_paths = sorted([
        list(path) for path in STANDARD_COVERAGE_PATHS])
    legacy_payload = {
        'admin_verified': digest_rows,
        'legacy_category_map': repr(claude_parser._CATEGORY_MAP),
        'legacy_keywords': repr(ocrparsing.COVERAGE_KEYWORDS),
    }
    review_payload = {
        'carrier_codes': sorted(CARRIER_CODE_BY_NAME.items()),
        'standard_paths': standard_paths,
    }
    return (
        _snapshot_digest(legacy_payload),
        _snapshot_digest(review_payload),
        lookup,
    )


def build_live_runtime(selected):
    """Build run context/adapters only after full dataset validation."""
    from django.conf import settings
    from .tasks import PROMPT_VERSION, SCHEMA_VERSION

    claude_selected = any(
        name in {'legacy', 'review'} for name in selected)
    model_id = getattr(settings, 'CLAUDE_MODEL_PARSE', '')
    if claude_selected and not model_id:
        raise EvalContractError('E_RUNTIME_CONTRACT')
    openai_model = os.environ.get('OPENAI_EVAL_MODEL', '').strip()
    openai_key = os.environ.get('OPENAI_EVAL_API_KEY', '').strip()
    if 'openai_review' in selected and not (openai_model and openai_key):
        raise EvalContractError('E_OPENAI_EVAL_CONTRACT')
    legacy_snapshot, review_snapshot, lookup = (
        _normalization_snapshots_and_lookup())
    context_values = {
        'legacy': {
            'model_id': model_id,
            'schema_version': 'legacy-ocr-data-unversioned',
            'prompt_version': _legacy_prompt_version(),
            'normalization_snapshot': legacy_snapshot,
        },
        'review': {
            'model_id': model_id,
            'schema_version': SCHEMA_VERSION,
            'prompt_version': PROMPT_VERSION,
            'normalization_snapshot': review_snapshot,
        },
        'openai_review': {
            'model_id': openai_model,
            'schema_version': SCHEMA_VERSION,
            'prompt_version': PROMPT_VERSION,
            'normalization_snapshot': review_snapshot,
        },
    }
    contexts = {
        name: EvalRunContext.model_validate(context_values[name])
        for name in selected
    }
    adapters = {}
    for name in selected:
        if name == 'legacy':
            adapters[name] = LegacyExtractionAdapter(lookup)
        elif name == 'review':
            adapters[name] = ReviewExtractionAdapter()
        elif name == 'openai_review':
            adapters[name] = OpenAIReviewExtractionAdapter()
        else:
            raise EvalContractError('E_RUNTIME_CONTRACT')
    return contexts, adapters
