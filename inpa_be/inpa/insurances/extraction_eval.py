"""Pure, private insurance-extraction evaluation contracts and scoring.

This module deliberately has no Django model or provider SDK imports. Dataset
contents stay in memory and only aggregate, non-sensitive metrics leave the
module through :meth:`EvaluationReport.to_public_dict`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


MANIFEST_SCHEMA_VERSION = 'insurance-extraction-manifest-v1'
TRUTH_SCHEMA_VERSION = 'insurance-extraction-truth-v1'
PREDICTION_SCHEMA_VERSION = 'insurance-extraction-prediction-v1'
REVIEWED_OUTPUT_SCHEMA_VERSION = 'insurance-extraction-reviewed-v1'

MIN_CASES = 100
MIN_COVERAGE_ROWS = 1000
MIN_INSURANCE_TYPE_CASES = 20
MIN_FORM_ERA_CASES = 20
MIN_DOCUMENT_LENGTH_CASES = 10
MIN_CARRIER_CASES = 5
REQUIRED_INSURANCE_TYPES = frozenset({'life', 'loss'})
REQUIRED_FORM_ERAS = frozenset({'legacy', 'current'})
REQUIRED_DOCUMENT_LENGTHS = frozenset({'short', 'long'})
REQUIRED_CARRIER_CODES = frozenset({1, 2, 7, 11, 12, 201, 206, 213})

_CASE_ID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{2,63}$')
_SAFE_CODE_RE = re.compile(r'^[A-Z][A-Z0-9_]{1,63}$')
_SAFE_TYPE_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,127}$')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_POLICY_FIELDS = (
    'carrier_code', 'product_name', 'contract_date', 'expiry_date',
    'monthly_premium',
)
_COVERAGE_FIELDS = ('assurance_amount', 'premium', 'standard_path')
_REVIEW_STATES = frozenset(
    {'needs_review', 'no_evidence', 'unmatched', 'invalid', 'manual'})


class EvalContractError(Exception):
    """A pre-provider contract error carrying only a stable safe code."""

    def __init__(self, code: str):
        self.code = code if _SAFE_CODE_RE.fullmatch(code) else 'E_EVAL_CONTRACT'
        super().__init__(self.code)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class SourceRef(_StrictModel):
    page: StrictInt = Field(ge=1, le=10000)
    line_start: StrictInt = Field(ge=1, le=1_000_000)
    line_end: StrictInt = Field(ge=1, le=1_000_000)

    @model_validator(mode='after')
    def validate_order(self):
        if self.line_end < self.line_start:
            raise ValueError('invalid line range')
        return self

    def key(self) -> tuple[int, int, int]:
        return self.page, self.line_start, self.line_end


class EvalRunContext(_StrictModel):
    model_id: StrictStr = Field(min_length=1, max_length=200)
    schema_version: StrictStr = Field(min_length=1, max_length=100)
    prompt_version: StrictStr = Field(min_length=1, max_length=100)
    normalization_snapshot: StrictStr = Field(
        pattern=r'^sha256:[0-9a-f]{64}$')


class EvalPolicy(_StrictModel):
    carrier_code: StrictInt | None
    product_name: StrictStr | None = Field(default=None, max_length=500)
    contract_date: StrictStr | None = None
    expiry_date: StrictStr | None = None
    monthly_premium: StrictInt | None = Field(default=None, ge=0)

    @field_validator('contract_date', 'expiry_date')
    @classmethod
    def validate_date(cls, value):
        if value is not None and not _DATE_RE.fullmatch(value):
            raise ValueError('date must be canonical')
        if value is not None:
            from datetime import date
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError('date must exist') from exc
        return value


class TruthCoverageRow(_StrictModel):
    gold_row_id: StrictStr = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    source_ref: SourceRef
    raw_name: StrictStr = Field(min_length=1, max_length=500)
    assurance_amount: StrictInt | None = Field(default=None, ge=0)
    premium: StrictInt | None = Field(default=None, ge=0)
    standard_path: list[StrictStr] | None = Field(
        default=None, min_length=3, max_length=3)


class ExtractionTruth(_StrictModel):
    schema_version: Literal[TRUTH_SCHEMA_VERSION]
    case_id: StrictStr = Field(pattern=_CASE_ID_RE.pattern)
    policy: EvalPolicy
    coverage_rows: list[TruthCoverageRow] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_rows(self):
        row_ids = [row.gold_row_id for row in self.coverage_rows]
        refs = [row.source_ref.key() for row in self.coverage_rows]
        if len(row_ids) != len(set(row_ids)) or len(refs) != len(set(refs)):
            raise ValueError('truth row identity must be unique')
        return self


PolicyField = Literal[
    'carrier_code', 'product_name', 'contract_date', 'expiry_date',
    'monthly_premium',
]
CoverageField = Literal['assurance_amount', 'premium', 'standard_path']
ReviewState = Literal[
    'review_ready', 'needs_review', 'no_evidence', 'unmatched', 'invalid',
    'manual',
]


class PredictionCoverageRow(_StrictModel):
    row_id: StrictStr = Field(pattern=r'^[a-zA-Z0-9_-]{1,96}$')
    source_ref: SourceRef | None
    raw_name: StrictStr = Field(min_length=1, max_length=500)
    assurance_amount: StrictInt | None = Field(default=None, ge=0)
    premium: StrictInt | None = Field(default=None, ge=0)
    standard_path: list[StrictStr] | None = Field(
        default=None, min_length=3, max_length=3)
    state: ReviewState
    review_fields: list[CoverageField]
    reason_codes: list[StrictStr]

    @field_validator('review_fields')
    @classmethod
    def unique_review_fields(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('duplicate review field')
        return value

    @field_validator('reason_codes')
    @classmethod
    def safe_reason_codes(cls, value):
        if any(not _SAFE_CODE_RE.fullmatch(code) for code in value):
            raise ValueError('unsafe reason code')
        return value


class SurfacedItem(_StrictModel):
    source_ref: SourceRef | None
    raw_name: StrictStr | None = Field(default=None, min_length=1, max_length=500)
    state: ReviewState
    reason_codes: list[StrictStr]

    @model_validator(mode='after')
    def has_identity(self):
        if self.source_ref is None and self.raw_name is None:
            raise ValueError('surface identity required')
        if any(not _SAFE_CODE_RE.fullmatch(code) for code in self.reason_codes):
            raise ValueError('unsafe reason code')
        return self


class EvalPrediction(_StrictModel):
    schema_version: Literal[PREDICTION_SCHEMA_VERSION]
    case_id: StrictStr = Field(pattern=_CASE_ID_RE.pattern)
    run_contract: EvalRunContext
    policy: EvalPolicy
    policy_review_fields: list[PolicyField]
    coverage_rows: list[PredictionCoverageRow]
    surfaced_items: list[SurfacedItem]

    @model_validator(mode='after')
    def unique_rows_and_fields(self):
        row_ids = [row.row_id for row in self.coverage_rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError('prediction row id must be unique')
        if len(self.policy_review_fields) != len(set(self.policy_review_fields)):
            raise ValueError('duplicate policy review field')
        return self


class ReviewedOutputProvenance(_StrictModel):
    reviewer_ref: StrictStr = Field(
        pattern=r'^reviewer-[a-z0-9]{8,32}$')
    reviewed_at: StrictStr = Field(
        pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
    review_tool_version: StrictStr = Field(
        pattern=r'^[a-z0-9][a-z0-9._-]{0,63}$')
    review_schema_version: StrictStr = Field(
        pattern=r'^[a-z0-9][a-z0-9._-]{0,99}$')
    truth_access: Literal[False]
    content_digest: StrictStr = Field(pattern=r'^sha256:[0-9a-f]{64}$')

    @field_validator('reviewed_at')
    @classmethod
    def valid_reviewed_at(cls, value):
        from datetime import datetime
        try:
            datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError as exc:
            raise ValueError('invalid reviewed timestamp') from exc
        return value


class ReviewedExtractionOutput(_StrictModel):
    schema_version: Literal[REVIEWED_OUTPUT_SCHEMA_VERSION]
    case_id: StrictStr = Field(pattern=_CASE_ID_RE.pattern)
    provenance: ReviewedOutputProvenance
    prediction: EvalPrediction

    @model_validator(mode='after')
    def consistent_case(self):
        if self.prediction.case_id != self.case_id:
            raise ValueError('reviewed case mismatch')
        if (
            self.provenance.review_schema_version
            != self.prediction.run_contract.schema_version
        ):
            raise ValueError('reviewed schema contract mismatch')
        return self


class EvalObservation(_StrictModel):
    outcome: Literal['success', 'provider_failure']
    run_contract: EvalRunContext
    prediction: EvalPrediction | None
    error_code: StrictStr | None = None
    error_type: StrictStr | None = None
    input_tokens: StrictInt = Field(default=0, ge=0)
    output_tokens: StrictInt = Field(default=0, ge=0)
    cache_read_input_tokens: StrictInt = Field(default=0, ge=0)
    cache_creation_input_tokens: StrictInt = Field(default=0, ge=0)
    estimated_cost_krw: StrictFloat = Field(default=0.0, ge=0)
    provider_latency_ms: StrictInt | None = Field(default=None, ge=0)
    pipeline_latency_ms: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def valid_outcome(self):
        if self.outcome == 'success':
            if self.prediction is None or self.error_code or self.error_type:
                raise ValueError('invalid success observation')
        else:
            if self.prediction is not None:
                raise ValueError('failure cannot have prediction')
            if not self.error_code or not _SAFE_CODE_RE.fullmatch(
                    self.error_code):
                raise ValueError('failure requires safe code')
            if self.error_type and not _SAFE_TYPE_RE.fullmatch(self.error_type):
                raise ValueError('failure requires safe type')
        return self


class ManifestRequirements(_StrictModel):
    min_cases: StrictInt
    min_coverage_rows: StrictInt
    required_insurance_types: list[Literal['life', 'loss']]
    min_cases_per_required_insurance_type: StrictInt
    required_carrier_codes: list[StrictInt]
    min_cases_per_required_carrier: StrictInt
    required_form_eras: list[Literal['legacy', 'current']]
    min_cases_per_required_form_era: StrictInt
    required_document_lengths: list[Literal['short', 'long']]
    min_cases_per_required_document_length: StrictInt


class ManifestStrata(_StrictModel):
    insurance_type: Literal['life', 'loss']
    carrier_code: StrictInt
    form_era: Literal['legacy', 'current']
    document_length: Literal['short', 'long']


class ManifestCase(_StrictModel):
    case_id: StrictStr = Field(pattern=_CASE_ID_RE.pattern)
    pdf_path: StrictStr = Field(min_length=1, max_length=500)
    truth_path: StrictStr = Field(min_length=1, max_length=500)
    reviewed_output_path: StrictStr | None = Field(
        default=None, min_length=1, max_length=500)
    strata: ManifestStrata


class ExtractionManifest(_StrictModel):
    schema_version: Literal[MANIFEST_SCHEMA_VERSION]
    split: StrictStr = Field(pattern=r'^[a-z0-9][a-z0-9_-]{2,31}$')
    requirements: ManifestRequirements
    cases: list[ManifestCase] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_case_ids(self):
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError('duplicate case id')
        present = [case.reviewed_output_path is not None for case in self.cases]
        if any(present) and not all(present):
            raise ValueError('reviewed outputs must be all or none')
        return self


@dataclass
class LoadedCase:
    case_id: str
    pdf_path: Path
    truth: ExtractionTruth
    reviewed_output: EvalPrediction | None
    strata: ManifestStrata

    def adapter_case(self) -> 'EvalAdapterCase':
        return EvalAdapterCase(
            case_id=self.case_id,
            pdf_path=self.pdf_path,
        )


@dataclass(frozen=True)
class EvalAdapterCase:
    case_id: str
    pdf_path: Path


@dataclass
class LoadedDataset:
    cases: list[LoadedCase]
    gold_row_count: int
    has_reviewed_outputs: bool
    strata_counts: dict[str, dict[str, int]]


class ExtractionAdapter(Protocol):
    def run(
        self, case: EvalAdapterCase, context: EvalRunContext,
    ) -> EvalObservation: ...


@dataclass
class EvaluationReport:
    case_count: int
    gold_row_count: int
    variants: dict[str, dict[str, Any]]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            'scope': 'insurance_extraction_only',
            'case_count': self.case_count,
            'gold_row_count': self.gold_row_count,
            'variants': self.variants,
        }


def _read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        raise EvalContractError(code) from None


def _private_string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _private_string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _private_string_values(child)


def _assert_private_input_pii_safe(value: Any) -> None:
    """Apply the production text privacy gate to evaluator JSON strings."""
    from .import_claude import (
        ExtractionFailure,
        assert_provider_payload_pii_safe,
    )

    scan_payload = {
        'schema_version': 'private-eval-input',
        'coverage_rows': [
            {'raw_name': item}
            for item in _private_string_values(value)
        ],
    }
    try:
        assert_provider_payload_pii_safe(scan_payload)
    except ExtractionFailure:
        raise EvalContractError('E_DATASET_PRIVACY') from None


def _json_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + hashlib.sha256(payload).hexdigest()


def _file_digest(path: Path, code: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(65536), b''):
                digest.update(chunk)
    except OSError:
        raise EvalContractError(code) from None
    return 'sha256:' + digest.hexdigest()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _overlaps_worktree(path: Path, worktree_roots: Sequence[Path]) -> bool:
    return any(
        _is_within(path, worktree) or _is_within(worktree, path)
        for worktree in worktree_roots
    )


def _reject_path_in_worktree(
    path: Path,
    worktree_roots: Sequence[Path],
) -> None:
    if any(_is_within(path, worktree) for worktree in worktree_roots):
        raise EvalContractError('E_DATASET_PATH')


def _discover_git_worktree_roots() -> tuple[Path, ...]:
    try:
        module_path = Path(__file__).resolve()
        common = subprocess.run(
            ['git', '-C', str(module_path.parent), 'rev-parse',
             '--git-common-dir'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            text=True,
        ).stdout.strip()
        common_path = Path(common)
        if not common_path.is_absolute():
            common_path = (module_path.parent / common_path).resolve()
        output = subprocess.run(
            ['git', f'--git-dir={common_path}', 'worktree', 'list',
             '--porcelain'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            text=True,
        ).stdout
    except Exception:
        raise EvalContractError('E_DATASET_PATH') from None
    roots = []
    for line in output.splitlines():
        if line.startswith('worktree '):
            try:
                roots.append(Path(line[9:]).resolve(strict=True))
            except OSError:
                raise EvalContractError('E_DATASET_PATH') from None
    if not roots:
        raise EvalContractError('E_DATASET_PATH')
    return tuple(roots)


def _resolve_dataset_file(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or '..' in candidate.parts:
        raise EvalContractError('E_DATASET_PATH')
    try:
        resolved = (root / candidate).resolve(strict=True)
    except OSError:
        raise EvalContractError('E_DATASET_PATH') from None
    if not _is_within(resolved, root) or not resolved.is_file():
        raise EvalContractError('E_DATASET_PATH')
    return resolved


def _validate_requirements(requirements: ManifestRequirements) -> None:
    if (
        requirements.min_cases < MIN_CASES
        or requirements.min_coverage_rows < MIN_COVERAGE_ROWS
        or requirements.min_cases_per_required_insurance_type
        < MIN_INSURANCE_TYPE_CASES
        or requirements.min_cases_per_required_carrier < MIN_CARRIER_CASES
        or requirements.min_cases_per_required_form_era
        < MIN_FORM_ERA_CASES
        or requirements.min_cases_per_required_document_length
        < MIN_DOCUMENT_LENGTH_CASES
        or not REQUIRED_INSURANCE_TYPES.issubset(
            requirements.required_insurance_types)
        or not REQUIRED_CARRIER_CODES.issubset(
            requirements.required_carrier_codes)
        or not REQUIRED_FORM_ERAS.issubset(requirements.required_form_eras)
        or not REQUIRED_DOCUMENT_LENGTHS.issubset(
            requirements.required_document_lengths)
        or len(requirements.required_insurance_types)
        != len(set(requirements.required_insurance_types))
        or len(requirements.required_carrier_codes)
        != len(set(requirements.required_carrier_codes))
        or len(requirements.required_form_eras)
        != len(set(requirements.required_form_eras))
        or len(requirements.required_document_lengths)
        != len(set(requirements.required_document_lengths))
    ):
        raise EvalContractError('E_MANIFEST_REQUIREMENTS')


def validate_manifest_and_truth(
    dataset_root: str | Path,
    manifest_path: str | Path,
    *,
    split: str,
    worktree_roots: Sequence[str | Path] | None = None,
) -> LoadedDataset:
    """Validate the full private dataset before any adapter or PDF read."""
    try:
        root = Path(dataset_root).resolve(strict=True)
        manifest_file = Path(manifest_path).resolve(strict=True)
    except OSError:
        raise EvalContractError('E_DATASET_PATH') from None
    if not root.is_dir() or not manifest_file.is_file():
        raise EvalContractError('E_DATASET_PATH')
    roots = (
        _discover_git_worktree_roots()
        if worktree_roots is None
        else tuple(Path(path).resolve() for path in worktree_roots)
    )
    if _overlaps_worktree(root, roots) or _overlaps_worktree(
            manifest_file, roots):
        raise EvalContractError('E_DATASET_PATH')

    raw_manifest = _read_json(manifest_file, 'E_MANIFEST_SCHEMA')
    _assert_private_input_pii_safe(raw_manifest)
    try:
        manifest = ExtractionManifest.model_validate(raw_manifest)
    except Exception:
        raise EvalContractError('E_MANIFEST_SCHEMA') from None
    if manifest.split != split:
        raise EvalContractError('E_CLI_CONTRACT')
    _validate_requirements(manifest.requirements)
    if len(manifest.cases) < manifest.requirements.min_cases:
        raise EvalContractError('E_DATASET_COUNTS')

    all_dataset_files: set[Path] = set()
    resolved_cases = []
    for case in manifest.cases:
        pdf_path = _resolve_dataset_file(root, case.pdf_path)
        truth_path = _resolve_dataset_file(root, case.truth_path)
        reviewed_path = (
            _resolve_dataset_file(root, case.reviewed_output_path)
            if case.reviewed_output_path is not None else None
        )
        case_paths = [pdf_path, truth_path]
        if reviewed_path is not None:
            case_paths.append(reviewed_path)
        for path in case_paths:
            _reject_path_in_worktree(path, roots)
        if (
            len(case_paths) != len(set(case_paths))
            or any(path in all_dataset_files for path in case_paths)
        ):
            raise EvalContractError('E_DATASET_PATH')
        all_dataset_files.update(case_paths)
        resolved_cases.append((case, pdf_path, truth_path, reviewed_path))

    loaded_cases = []
    gold_row_count = 0
    strata_counts: dict[str, Counter] = {
        'insurance_type': Counter(),
        'carrier_code': Counter(),
        'form_era': Counter(),
        'document_length': Counter(),
    }
    for case, pdf_path, truth_path, reviewed_path in resolved_cases:
        try:
            raw_truth = _read_json(truth_path, 'E_TRUTH_SCHEMA')
            _assert_private_input_pii_safe(raw_truth)
            truth = ExtractionTruth.model_validate(raw_truth)
        except EvalContractError:
            raise
        except Exception:
            raise EvalContractError('E_TRUTH_SCHEMA') from None
        if truth.case_id != case.case_id:
            raise EvalContractError('E_TRUTH_SCHEMA')
        reviewed = None
        if reviewed_path is not None:
            try:
                raw_reviewed = _read_json(
                    reviewed_path, 'E_REVIEWED_OUTPUT_SCHEMA')
                reviewed_envelope = ReviewedExtractionOutput.model_validate(
                    raw_reviewed)
            except EvalContractError:
                raise
            except Exception:
                raise EvalContractError('E_REVIEWED_OUTPUT_SCHEMA') from None
            if reviewed_envelope.case_id != case.case_id:
                raise EvalContractError('E_REVIEWED_OUTPUT_SCHEMA')
            prediction_payload = reviewed_envelope.prediction.model_dump(
                mode='json')
            content_digest = _json_digest(prediction_payload)
            truth_content_digest = _json_digest(raw_truth)
            truth_file_digest = _file_digest(
                truth_path, 'E_TRUTH_SCHEMA')
            reviewed_file_digest = _file_digest(
                reviewed_path, 'E_REVIEWED_OUTPUT_SCHEMA')
            provenance = reviewed_envelope.provenance
            if (
                provenance.content_digest != content_digest
                or provenance.content_digest
                in {truth_content_digest, truth_file_digest}
                or reviewed_file_digest == truth_file_digest
            ):
                raise EvalContractError('E_REVIEWED_OUTPUT_PROVENANCE')
            reviewed = reviewed_envelope.prediction
        gold_row_count += len(truth.coverage_rows)
        strata_counts['insurance_type'][case.strata.insurance_type] += 1
        strata_counts['carrier_code'][case.strata.carrier_code] += 1
        strata_counts['form_era'][case.strata.form_era] += 1
        strata_counts['document_length'][case.strata.document_length] += 1
        loaded_cases.append(LoadedCase(
            case_id=case.case_id,
            pdf_path=pdf_path,
            truth=truth,
            reviewed_output=reviewed,
            strata=case.strata,
        ))

    requirements = manifest.requirements
    if gold_row_count < requirements.min_coverage_rows:
        raise EvalContractError('E_DATASET_COUNTS')
    strata_rules = (
        ('insurance_type', requirements.required_insurance_types,
         requirements.min_cases_per_required_insurance_type),
        ('carrier_code', requirements.required_carrier_codes,
         requirements.min_cases_per_required_carrier),
        ('form_era', requirements.required_form_eras,
         requirements.min_cases_per_required_form_era),
        ('document_length', requirements.required_document_lengths,
         requirements.min_cases_per_required_document_length),
    )
    for key, required_values, minimum in strata_rules:
        if any(strata_counts[key][value] < minimum for value in required_values):
            raise EvalContractError('E_DATASET_STRATA')
    if any(
        case.truth.policy.carrier_code != case.strata.carrier_code
        for case in loaded_cases
    ):
        raise EvalContractError('E_TRUTH_SCHEMA')

    return LoadedDataset(
        cases=loaded_cases,
        gold_row_count=gold_row_count,
        has_reviewed_outputs=all(
            case.reviewed_output is not None for case in loaded_cases),
        strata_counts={
            key: {str(value): count for value, count in counts.items()}
            for key, counts in strata_counts.items()
        },
    )


def parse_compare(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        raise EvalContractError('E_CLI_CONTRACT')
    values = value.split(',')
    if (
        any(item not in {'legacy', 'review', 'openai_review'}
            for item in values)
        or len(values) != len(set(values))
        or not values
    ):
        raise EvalContractError('E_CLI_CONTRACT')
    return tuple(values)


def nearest_rank_summary(values: Sequence[int]) -> dict[str, int | None]:
    ordered = sorted(values)
    if not ordered:
        return {'sample_count': 0, 'p50': None, 'p95': None}

    def percentile(fraction: float) -> int:
        return ordered[math.ceil(fraction * len(ordered)) - 1]

    return {
        'sample_count': len(ordered),
        'p50': percentile(0.50),
        'p95': percentile(0.95),
    }


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        'numerator': numerator,
        'denominator': denominator,
        'rate': numerator / denominator if denominator else None,
    }


def _count_metric(count: int, denominator: int = 0) -> dict[str, Any]:
    return {'count': count, **_rate(count, denominator)}


def _normalized_name(value: str) -> str:
    return unicodedata.normalize('NFC', value).strip()


def _policy_value_exact(field: str, truth_value, predicted_value) -> bool:
    if field == 'product_name':
        if truth_value is None or predicted_value is None:
            return truth_value is predicted_value
        return _normalized_name(truth_value) == _normalized_name(
            predicted_value)
    return truth_value == predicted_value


@dataclass
class _Pairing:
    pairs: list[tuple[int, int]]
    unpaired_gold: set[int]
    unpaired_prediction: set[int]
    ambiguous_gold: set[int]
    ambiguous_prediction: set[int]
    fallback_pairs: int
    reference_violations: int


def _pair_rows(
    gold_rows: Sequence[TruthCoverageRow],
    predicted_rows: Sequence[PredictionCoverageRow],
    *,
    allow_name_fallback: bool,
) -> _Pairing:
    gold_by_ref = {row.source_ref.key(): index for index, row in enumerate(
        gold_rows)}
    pred_by_ref: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, row in enumerate(predicted_rows):
        if row.source_ref is not None:
            pred_by_ref[row.source_ref.key()].append(index)

    pairs: list[tuple[int, int]] = []
    paired_gold = set()
    paired_pred = set()
    ambiguous_gold = set()
    ambiguous_pred = set()
    for ref, prediction_indexes in pred_by_ref.items():
        gold_index = gold_by_ref.get(ref)
        if gold_index is None:
            continue
        if len(prediction_indexes) == 1:
            prediction_index = prediction_indexes[0]
            pairs.append((gold_index, prediction_index))
            paired_gold.add(gold_index)
            paired_pred.add(prediction_index)
        else:
            ambiguous_gold.add(gold_index)
            ambiguous_pred.update(prediction_indexes)

    fallback_pairs = 0
    if allow_name_fallback:
        remaining_gold_by_name: dict[str, list[int]] = defaultdict(list)
        remaining_pred_by_name: dict[str, list[int]] = defaultdict(list)
        for gold_index, row in sorted(
            enumerate(gold_rows), key=lambda item: item[1].source_ref.key()
        ):
            if (
                gold_index not in paired_gold
                and gold_index not in ambiguous_gold
            ):
                remaining_gold_by_name[_normalized_name(row.raw_name)].append(
                    gold_index)
        for prediction_index, row in enumerate(predicted_rows):
            if (
                prediction_index not in paired_pred
                and prediction_index not in ambiguous_pred
                and row.source_ref is None
            ):
                remaining_pred_by_name[_normalized_name(row.raw_name)].append(
                    prediction_index)

        for name in sorted(set(remaining_gold_by_name) & set(
                remaining_pred_by_name)):
            gold_indexes = remaining_gold_by_name[name]
            prediction_indexes = remaining_pred_by_name[name]
            if len(gold_indexes) == len(prediction_indexes):
                for gold_index, prediction_index in zip(
                        gold_indexes, prediction_indexes):
                    pairs.append((gold_index, prediction_index))
                    paired_gold.add(gold_index)
                    paired_pred.add(prediction_index)
                    fallback_pairs += 1
            elif len(gold_indexes) > 1 or len(prediction_indexes) > 1:
                ambiguous_gold.update(gold_indexes)
                ambiguous_pred.update(prediction_indexes)

    reference_violations = sum(
        row.source_ref is None for row in predicted_rows)
    reference_violations += sum(
        len(indexes) for indexes in pred_by_ref.values() if len(indexes) > 1)

    return _Pairing(
        pairs=pairs,
        unpaired_gold=set(range(len(gold_rows))) - paired_gold,
        unpaired_prediction=set(range(len(predicted_rows))) - paired_pred,
        ambiguous_gold=ambiguous_gold,
        ambiguous_prediction=ambiguous_pred,
        fallback_pairs=fallback_pairs,
        reference_violations=reference_violations,
    )


def _omission_visibility(
    gold_rows: Sequence[TruthCoverageRow],
    predicted_rows: Sequence[PredictionCoverageRow],
    surfaced_items: Sequence[SurfacedItem],
    pairing: _Pairing,
) -> tuple[int, int]:
    surfaced_refs: dict[tuple[int, int, int], deque[bool]] = defaultdict(deque)
    surfaced_names: dict[str, deque[bool]] = defaultdict(deque)
    for prediction_index in sorted(pairing.unpaired_prediction):
        row = predicted_rows[prediction_index]
        flagged = row.state in _REVIEW_STATES
        if row.source_ref is not None:
            surfaced_refs[row.source_ref.key()].append(flagged)
        else:
            surfaced_names[_normalized_name(row.raw_name)].append(flagged)
    for item in surfaced_items:
        flagged = item.state in _REVIEW_STATES
        if item.source_ref is not None:
            surfaced_refs[item.source_ref.key()].append(flagged)
        elif item.raw_name is not None:
            surfaced_names[_normalized_name(item.raw_name)].append(flagged)

    silent = 0
    caught = 0
    for gold_index in sorted(
        pairing.unpaired_gold,
        key=lambda index: gold_rows[index].source_ref.key(),
    ):
        row = gold_rows[gold_index]
        ref = row.source_ref.key()
        name = _normalized_name(row.raw_name)
        if surfaced_refs[ref]:
            caught += int(surfaced_refs[ref].popleft())
        elif surfaced_names[name]:
            caught += int(surfaced_names[name].popleft())
        else:
            silent += 1
    return silent, caught


def _empty_prediction(case_id: str, context: EvalRunContext) -> EvalPrediction:
    return EvalPrediction.model_validate({
        'schema_version': PREDICTION_SCHEMA_VERSION,
        'case_id': case_id,
        'run_contract': context.model_dump(mode='json'),
        'policy': {
            'carrier_code': None,
            'product_name': None,
            'contract_date': None,
            'expiry_date': None,
            'monthly_premium': None,
        },
        'policy_review_fields': [],
        'coverage_rows': [],
        'surfaced_items': [],
    })


def _safe_failure(context: EvalRunContext, exc: Exception) -> EvalObservation:
    error_type = type(exc).__name__
    if not _SAFE_TYPE_RE.fullmatch(error_type):
        error_type = 'AdapterFailure'
    return EvalObservation.model_validate({
        'outcome': 'provider_failure',
        'run_contract': context.model_dump(mode='json'),
        'prediction': None,
        'error_code': 'ADAPTER_RUN_FAILED',
        'error_type': error_type,
    })


def _validated_observation(
    adapter: ExtractionAdapter,
    case: LoadedCase,
    context: EvalRunContext,
) -> EvalObservation:
    try:
        observation = adapter.run(case.adapter_case(), context)
        if isinstance(observation, EvalObservation):
            observation = EvalObservation.model_validate(
                observation.model_dump(mode='json', warnings='none'))
        else:
            observation = EvalObservation.model_validate(observation)
        if (
            observation.prediction is not None
            and observation.prediction.case_id != case.case_id
        ):
            raise ValueError('case mismatch')
        return observation
    except Exception as exc:
        return _safe_failure(context, exc)


def _score_variant(
    dataset: LoadedDataset,
    observations: Sequence[EvalObservation],
    context: EvalRunContext,
    *,
    allow_name_fallback: bool,
) -> dict[str, Any]:
    policy_hits = Counter()
    paired_total = 0
    gold_total = 0
    prediction_total = 0
    assurance_hits = 0
    premium_hits = 0
    mapping_hits = 0
    mapping_denominator = 0
    silent_omission = 0
    ambiguous_rows = 0
    fallback_pairs = 0
    reference_violations = 0
    error_units = 0
    caught_error_units = 0
    correct_units = 0
    false_review_units = 0
    material_amount_errors = 0
    material_amount_denominator = 0
    provider_failures = 0
    failure_types = Counter()
    failure_codes = Counter()
    provider_latency = []
    pipeline_latency = []
    input_tokens = 0
    output_tokens = 0
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0
    total_cost = 0.0
    run_contract_match = True

    for case, observation in zip(dataset.cases, observations):
        run_contract_match = (
            run_contract_match and observation.run_contract == context)
        if observation.outcome == 'provider_failure':
            provider_failures += 1
            failure_codes[observation.error_code or 'ADAPTER_RUN_FAILED'] += 1
            if observation.error_type:
                failure_types[observation.error_type] += 1
            prediction = _empty_prediction(case.case_id, context)
        else:
            prediction = observation.prediction
            assert prediction is not None
            run_contract_match = (
                run_contract_match and prediction.run_contract == context)
        if observation.provider_latency_ms is not None:
            provider_latency.append(observation.provider_latency_ms)
        if observation.pipeline_latency_ms is not None:
            pipeline_latency.append(observation.pipeline_latency_ms)
        input_tokens += observation.input_tokens
        output_tokens += observation.output_tokens
        cache_read_input_tokens += observation.cache_read_input_tokens
        cache_creation_input_tokens += (
            observation.cache_creation_input_tokens)
        total_cost += observation.estimated_cost_krw

        truth = case.truth
        for field in _POLICY_FIELDS:
            truth_value = getattr(truth.policy, field)
            predicted_value = getattr(prediction.policy, field)
            exact = _policy_value_exact(field, truth_value, predicted_value)
            if exact:
                policy_hits[field] += 1
                correct_units += 1
                if field in prediction.policy_review_fields:
                    false_review_units += 1
            else:
                error_units += 1
                if field in prediction.policy_review_fields:
                    caught_error_units += 1
            if field == 'monthly_premium':
                material_amount_denominator += 1
                if not exact:
                    material_amount_errors += 1

        pairing = _pair_rows(
            truth.coverage_rows,
            prediction.coverage_rows,
            allow_name_fallback=allow_name_fallback,
        )
        gold_total += len(truth.coverage_rows)
        prediction_total += len(prediction.coverage_rows)
        paired_total += len(pairing.pairs)
        fallback_pairs += pairing.fallback_pairs
        reference_violations += pairing.reference_violations
        ambiguous_rows += (
            len(pairing.ambiguous_gold)
            + len(pairing.ambiguous_prediction)
        )
        case_silent, case_caught_omissions = _omission_visibility(
            truth.coverage_rows,
            prediction.coverage_rows,
            prediction.surfaced_items,
            pairing,
        )
        silent_omission += case_silent

        error_units += len(pairing.unpaired_gold)
        caught_error_units += case_caught_omissions
        error_units += len(pairing.unpaired_prediction)
        for prediction_index in pairing.unpaired_prediction:
            if prediction.coverage_rows[prediction_index].state in _REVIEW_STATES:
                caught_error_units += 1

        for gold_index, prediction_index in pairing.pairs:
            gold = truth.coverage_rows[gold_index]
            predicted = prediction.coverage_rows[prediction_index]
            for field in _COVERAGE_FIELDS:
                truth_value = getattr(gold, field)
                predicted_value = getattr(predicted, field)
                exact = truth_value == predicted_value
                if exact:
                    correct_units += 1
                    if field in predicted.review_fields:
                        false_review_units += 1
                else:
                    error_units += 1
                    if field in predicted.review_fields:
                        caught_error_units += 1
            assurance_exact = (
                gold.assurance_amount == predicted.assurance_amount)
            premium_exact = gold.premium == predicted.premium
            assurance_hits += int(assurance_exact)
            premium_hits += int(premium_exact)
            material_amount_denominator += 2
            material_amount_errors += int(not assurance_exact)
            material_amount_errors += int(not premium_exact)
            if gold.standard_path is not None:
                mapping_denominator += 1
                mapping_hits += int(
                    gold.standard_path == predicted.standard_path)

    case_count = len(dataset.cases)
    metrics = {
        'carrier_exact': _rate(policy_hits['carrier_code'], case_count),
        'product_exact': _rate(policy_hits['product_name'], case_count),
        'contract_date_exact': _rate(
            policy_hits['contract_date'], case_count),
        'expiry_date_exact': _rate(policy_hits['expiry_date'], case_count),
        'monthly_premium_exact': _rate(
            policy_hits['monthly_premium'], case_count),
        'coverage_recall': _rate(paired_total, gold_total),
        'coverage_precision': _rate(paired_total, prediction_total),
        'assurance_amount_exact': _rate(assurance_hits, paired_total),
        'coverage_premium_exact': _rate(premium_hits, paired_total),
        'mapping_accuracy': _rate(mapping_hits, mapping_denominator),
        'silent_omission': _count_metric(silent_omission, gold_total),
        'validation_catch_rate': _rate(
            caught_error_units, error_units),
        'false_review_rate': _rate(false_review_units, correct_units),
        'material_amount_error': _count_metric(
            material_amount_errors, material_amount_denominator),
        'provider_failure_rate': _rate(provider_failures, case_count),
        'ambiguous_rows': _count_metric(ambiguous_rows),
        'fallback_pairs': _count_metric(fallback_pairs),
        'reference_violations': _count_metric(reference_violations),
        'provider_latency_ms': nearest_rank_summary(provider_latency),
        'pipeline_latency_ms': nearest_rank_summary(pipeline_latency),
        'tokens': {
            'input': input_tokens,
            'output': output_tokens,
            'cache_read_input': cache_read_input_tokens,
            'cache_creation_input': cache_creation_input_tokens,
        },
        'estimated_cost_krw': {
            'total': round(total_cost, 4),
            'average_per_case': (
                round(total_cost / case_count, 4) if case_count else None),
        },
    }
    return {
        'status': 'measured',
        'metrics': metrics,
        'run_contract_match': run_contract_match,
        'reference_contract_match': (
            True if allow_name_fallback else reference_violations == 0),
        'provider_failures': provider_failures,
        'failure_codes': dict(sorted(failure_codes.items())),
        'failure_types': dict(sorted(failure_types.items())),
    }


def evaluate_dataset(
    dataset: LoadedDataset,
    adapters: Mapping[str, ExtractionAdapter],
    expected_contexts: Mapping[str, EvalRunContext] | EvalRunContext,
) -> EvaluationReport:
    if isinstance(expected_contexts, EvalRunContext):
        contexts = {name: expected_contexts for name in adapters}
    else:
        try:
            contexts = {
                name: (
                    value if isinstance(value, EvalRunContext)
                    else EvalRunContext.model_validate(value)
                )
                for name, value in expected_contexts.items()
            }
        except Exception:
            raise EvalContractError('E_RUNTIME_CONTRACT') from None
    if set(contexts) != set(adapters):
        raise EvalContractError('E_RUNTIME_CONTRACT')

    variants: dict[str, dict[str, Any]] = {}
    for adapter_name, adapter in adapters.items():
        if adapter_name not in {'legacy', 'review', 'openai_review'}:
            raise EvalContractError('E_RUNTIME_CONTRACT')
        context = contexts[adapter_name]
        observations = [
            _validated_observation(adapter, case, context)
            for case in dataset.cases
        ]
        variants[f'{adapter_name}/pre_review'] = _score_variant(
            dataset,
            observations,
            context,
            allow_name_fallback=adapter_name == 'legacy',
        )

    if 'review' in adapters:
        if dataset.has_reviewed_outputs:
            post_observations = [
                EvalObservation.model_validate({
                    'outcome': 'success',
                    'run_contract': case.reviewed_output.run_contract.model_dump(
                        mode='json'),
                    'prediction': case.reviewed_output.model_dump(mode='json'),
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'estimated_cost_krw': 0.0,
                })
                for case in dataset.cases
                if case.reviewed_output is not None
            ]
            post_report = _score_variant(
                dataset,
                post_observations,
                contexts['review'],
                allow_name_fallback=False,
            )
            post_report.update({
                'status': 'not_verified',
                'reason_code': 'TRUSTED_REVIEW_AUDIT_UNAVAILABLE',
                'report_only': True,
            })
            variants['review/post_review'] = post_report
        else:
            variants['review/post_review'] = {
                'status': 'not_measured',
                'reason_code': 'REVIEWED_OUTPUTS_ABSENT',
            }
    return EvaluationReport(
        case_count=len(dataset.cases),
        gold_row_count=dataset.gold_row_count,
        variants=variants,
    )


def _provider_failed(report: EvaluationReport) -> bool:
    return any(
        variant.get('provider_failures', 0) > 0
        for variant in report.variants.values()
    )


def _review_gates_pass(report: EvaluationReport) -> bool:
    legacy = report.variants.get('legacy/pre_review')
    pre = report.variants.get('review/pre_review')
    post = report.variants.get('review/post_review')
    if (
        not legacy
        or legacy.get('status') != 'measured'
        or not legacy.get('run_contract_match')
        or not pre
        or pre.get('status') != 'measured'
        or not pre.get('run_contract_match')
        or not pre.get('reference_contract_match')
        or pre['metrics']['silent_omission']['count'] != 0
        or not post
        or post.get('status') != 'verified'
        or not post.get('run_contract_match')
        or not post.get('reference_contract_match')
        or post['metrics']['silent_omission']['count'] != 0
        or post['metrics']['material_amount_error']['count'] != 0
    ):
        return False
    return True


def run_private_evaluation(
    dataset_root: str | Path,
    manifest_path: str | Path,
    *,
    split: str,
    compare: str,
    runtime_factory,
    fail_on_release_gates: bool = False,
    worktree_roots: Sequence[str | Path] | None = None,
) -> tuple[EvaluationReport, int]:
    """Validate first, then construct adapters and run aggregate scoring."""
    selected = parse_compare(compare)
    dataset = validate_manifest_and_truth(
        dataset_root,
        manifest_path,
        split=split,
        worktree_roots=worktree_roots,
    )
    try:
        expected_contexts, adapters = runtime_factory(selected)
        if isinstance(expected_contexts, EvalRunContext):
            contexts = {name: expected_contexts for name in selected}
        elif isinstance(expected_contexts, Mapping):
            contexts = {
                name: (
                    value if isinstance(value, EvalRunContext)
                    else EvalRunContext.model_validate(value)
                )
                for name, value in expected_contexts.items()
            }
        else:
            raise ValueError('expected context mapping required')
        if set(adapters) != set(selected):
            raise ValueError('adapter selection mismatch')
        if set(contexts) != set(selected):
            raise ValueError('context selection mismatch')
    except EvalContractError:
        raise
    except Exception:
        raise EvalContractError('E_RUNTIME_CONTRACT') from None
    report = evaluate_dataset(dataset, adapters, contexts)
    if _provider_failed(report):
        return report, 1
    if fail_on_release_gates and not _review_gates_pass(report):
        return report, 1
    return report, 0
