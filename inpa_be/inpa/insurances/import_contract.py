from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist


_MAX_REVIEW_PAGE_COUNT = 300
_MAX_REVIEW_LINE_COUNT = 500_000
_MANUAL_COVERAGE_GUIDANCE = (
    '해당 페이지의 원문을 확인한 뒤, 필요한 담보를 '
    '직접 추가하거나 수정해 주세요.'
)


PSEUDONYMIZATION_CATEGORY_TOKENS = (
    ('customer_name', '고객'),
    ('planner_name', '설계사'),
    ('address', '주소'),
    ('rrn', '주민번호'),
    ('phone', '전화'),
    ('email', '이메일'),
    ('contract_id', '계약번호'),
    ('policy_id', '증권번호'),
    ('customer_id', '고객번호'),
    ('certificate_id', '증서번호'),
    ('application_id', '청약번호'),
    ('planner_id', '설계사번호'),
    ('recruiter_id', '모집자번호'),
    ('license_id', '등록번호'),
    ('birth_date', '생년월일'),
    ('account_id', '계좌번호'),
    ('card_id', '카드번호'),
    ('business_id', '사업자번호'),
)
PSEUDONYMIZATION_CATEGORIES = tuple(
    category for category, _token in PSEUDONYMIZATION_CATEGORY_TOKENS
)
COVERAGE_MARKERS = (
    '담보명', '보장명', '특약명', '가입금액', '보장내용', '보험금',
    '진단비', '수술비', '입원비', '일당', '치료비',
)


class PDFImportError(Exception):
    """A fail-closed PDF error whose code is safe to persist or return."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PseudonymizedDocument:
    pages: tuple[tuple[str, ...], ...]
    category_counts: tuple[tuple[str, int], ...]
    residual_scan_passed: bool
    quarantined_line_count: int = 0
    quarantined_line_ids: tuple[str, ...] = ()
    analysis_signal_quarantined_line_count: int = 0
    analysis_signal_quarantined_line_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MaskedLine:
    line_id: str
    page: int
    line: int
    text_masked: str


@dataclass(frozen=True)
class CoverageCandidate:
    candidate_id: str
    evidence_line_ids: tuple[str, ...]
    text_masked: str
    review_status: str = 'needs_review'


@dataclass(frozen=True)
class ExtractedPDF:
    file_sha256: str
    file_size: int
    page_count: int
    masked_lines: tuple[MaskedLine, ...]
    candidates: tuple[CoverageCandidate, ...]
    pseudonymization_counts: tuple[tuple[str, int], ...] = ()
    residual_scan_passed: bool = False
    image_only_page_count: int = 0
    image_only_pages: tuple[int, ...] = ()
    quarantined_line_count: int = 0
    quarantined_line_ids: tuple[str, ...] = ()
    analysis_signal_quarantined_line_count: int = 0
    analysis_signal_quarantined_line_ids: tuple[str, ...] = ()


def extracted_source_readability(extracted):
    """Return the exact, JSON-safe readability proof for one extraction."""
    quarantined_pages = sorted({
        int(line_id[1:line_id.index('-l')])
        for line_id in extracted.quarantined_line_ids
    })
    analysis_quarantined_pages = sorted({
        int(line_id[1:line_id.index('-l')])
        for line_id in extracted.analysis_signal_quarantined_line_ids
    })
    return {
        'page_count': extracted.page_count,
        'image_only_page_count': extracted.image_only_page_count,
        'image_only_pages': list(extracted.image_only_pages),
        'quarantined_line_count': extracted.quarantined_line_count,
        'quarantined_pages': quarantined_pages,
        'analysis_signal_quarantined_line_count': (
            extracted.analysis_signal_quarantined_line_count),
        'analysis_signal_quarantined_pages': analysis_quarantined_pages,
        'pages_requiring_manual_source_review': sorted(set(
            extracted.image_only_pages) | set(analysis_quarantined_pages)),
    }


def normalize_source_readability(value, *, expected_page_count):
    """Validate server-owned readability metadata without coercion."""
    if (not isinstance(value, dict)
            or set(value) != {
                'page_count', 'image_only_page_count', 'image_only_pages',
                'quarantined_line_count', 'quarantined_pages',
                'analysis_signal_quarantined_line_count',
                'analysis_signal_quarantined_pages',
                'pages_requiring_manual_source_review'}):
        return None
    page_count = value['page_count']
    image_only_page_count = value['image_only_page_count']
    image_only_pages = value['image_only_pages']
    quarantined_line_count = value['quarantined_line_count']
    quarantined_pages = value['quarantined_pages']
    analysis_line_count = value[
        'analysis_signal_quarantined_line_count']
    analysis_pages = value['analysis_signal_quarantined_pages']
    review_pages = value['pages_requiring_manual_source_review']
    if (type(expected_page_count) is not int
            or expected_page_count <= 0
            or expected_page_count > _MAX_REVIEW_PAGE_COUNT
            or type(page_count) is not int
            or page_count != expected_page_count
            or type(image_only_page_count) is not int
            or image_only_page_count < 0
            or image_only_page_count >= page_count
            or not isinstance(image_only_pages, list)
            or len(image_only_pages) != image_only_page_count
            or type(quarantined_line_count) is not int
            or not 0 <= quarantined_line_count <= _MAX_REVIEW_LINE_COUNT
            or not isinstance(quarantined_pages, list)
            or len(quarantined_pages) > quarantined_line_count
            or type(analysis_line_count) is not int
            or not 0 <= analysis_line_count <= quarantined_line_count
            or not isinstance(analysis_pages, list)
            or len(analysis_pages) > analysis_line_count
            or not isinstance(review_pages, list)):
        return None

    def valid_pages(pages):
        previous = 0
        for page in pages:
            if (type(page) is not int
                    or page <= previous
                    or page > page_count):
                return False
            previous = page
        return True

    if (not valid_pages(image_only_pages)
            or not valid_pages(quarantined_pages)
            or not valid_pages(analysis_pages)
            or not valid_pages(review_pages)
            or bool(quarantined_line_count) != bool(quarantined_pages)
            or bool(analysis_line_count) != bool(analysis_pages)
            or not set(analysis_pages).issubset(quarantined_pages)
            or set(image_only_pages) & set(quarantined_pages)
            or review_pages != sorted(
                set(image_only_pages) | set(analysis_pages))):
        return None
    return {
        'page_count': page_count,
        'image_only_page_count': image_only_page_count,
        'image_only_pages': list(image_only_pages),
        'quarantined_line_count': quarantined_line_count,
        'quarantined_pages': list(quarantined_pages),
        'analysis_signal_quarantined_line_count': analysis_line_count,
        'analysis_signal_quarantined_pages': list(analysis_pages),
        'pages_requiring_manual_source_review': list(review_pages),
    }


def _source_review_response(readability):
    analysis_count = readability[
        'analysis_signal_quarantined_line_count']
    requires_manual_coverage_entry = bool(
        readability['pages_requiring_manual_source_review'])
    return {
        'required': bool(
            readability['pages_requiring_manual_source_review']),
        'image_only_page_count': readability['image_only_page_count'],
        'image_only_pages': readability['image_only_pages'],
        'quarantined_line_count': readability['quarantined_line_count'],
        'quarantined_pages': readability['quarantined_pages'],
        'analysis_signal_quarantined_line_count': analysis_count,
        'analysis_signal_quarantined_pages': readability[
            'analysis_signal_quarantined_pages'],
        'pages_requiring_manual_source_review': readability[
            'pages_requiring_manual_source_review'],
        'requires_manual_coverage_entry': requires_manual_coverage_entry,
        'guidance': (
            _MANUAL_COVERAGE_GUIDANCE
            if requires_manual_coverage_entry else ''),
    }


def safe_source_review(summary, *, expected_page_count):
    """Expose only validated page numbers and fail closed for legacy damage."""
    system = summary.get('_system') if isinstance(summary, dict) else None
    raw = system.get('source_readability') if isinstance(system, dict) else None
    readability = normalize_source_readability(
        raw, expected_page_count=expected_page_count)
    if readability is None:
        # A job without a valid server proof must never silently imply that
        # every source page was read. The bounded PDF contract caps this list.
        pages = (
            list(range(1, expected_page_count + 1))
            if (type(expected_page_count) is int
                and 0 < expected_page_count <= _MAX_REVIEW_PAGE_COUNT)
            else []
        )
        return {
            'required': True,
            'image_only_page_count': len(pages),
            'image_only_pages': pages,
            'quarantined_line_count': 0,
            'quarantined_pages': [],
            'analysis_signal_quarantined_line_count': 0,
            'analysis_signal_quarantined_pages': [],
            'pages_requiring_manual_source_review': pages,
            'requires_manual_coverage_entry': True,
            'guidance': _MANUAL_COVERAGE_GUIDANCE,
        }
    return _source_review_response(readability)


def safe_confirmation_requirements(source_review):
    """Describe the exact planner acknowledgements required by confirm."""
    unread_pages_required = bool(
        isinstance(source_review, dict) and source_review.get('required'))
    return {
        'planner_confirmed_source_match': {'required': True},
        'planner_confirmed_unread_pages': {
            'required': unread_pages_required,
        },
    }


def safe_import_target(job):
    """Return a refresh-safe replacement reference without cross-tenant IDs."""
    empty = {
        'target_insurance_id': None,
        'target_insurance_version': None,
    }
    if job.intent != 'replace' or job.target_insurance_id is None:
        return empty
    try:
        target = job.target_insurance
    except ObjectDoesNotExist:
        return empty
    if target.customer_id != job.customer_id:
        return empty
    return {
        'target_insurance_id': target.pk,
        'target_insurance_version': job.target_insurance_version,
    }


def apply_source_review_issue(draft, summary, source_review):
    """Attach one fixed, non-sensitive issue for redacted analysis lines."""
    result_summary = dict(summary)
    result_summary.update({
        'pages_requiring_manual_source_review': list(
            source_review['pages_requiring_manual_source_review']),
        'analysis_signal_quarantined_line_count': source_review[
            'analysis_signal_quarantined_line_count'],
        'quarantined_line_count': source_review['quarantined_line_count'],
    })
    validation = draft.setdefault('validation', {})
    issues = validation.setdefault('issues', [])
    issue = {
        'code': 'SOURCE_PAGE_MANUAL_REVIEW_REQUIRED',
        'state': 'needs_review',
        'scope': 'document',
        'row_id': None,
        'field': 'source_page',
    }
    issues[:] = [
        item for item in issues
        if not isinstance(item, dict)
        or item.get('code') != issue['code']
    ]
    if source_review['requires_manual_coverage_entry']:
        issues.append(issue)
    result_summary['issue_count'] = len(issues)
    return draft, result_summary
