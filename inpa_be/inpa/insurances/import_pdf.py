import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager

from django.conf import settings

from .import_contract import (
    CoverageCandidate,
    ExtractedPDF,
    MaskedLine,
    PDFImportError,
    PSEUDONYMIZATION_CATEGORIES,
    PSEUDONYMIZATION_CATEGORY_TOKENS,
)
from .import_pdf_mask import assert_pseudonymized_pages_safe


MAX_FILE_BYTES = 50 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_PROTOCOL_VERSION = 1
_CHILD_DOMAIN_ERRORS = {
    'ENCRYPTED_PDF',
    'IMAGE_PDF',
    'TOO_MANY_PAGES',
    'DOCUMENT_TOO_LONG',
    'TOO_MANY_CANDIDATES',
    'INVALID_PDF',
    'PDF_PARSE_RESOURCE_LIMIT',
    'PDF_PARSE_FAILED',
    'PII_REDACTION_UNCERTAIN',
}
_PSEUDONYM_CATEGORY_BY_TOKEN = {
    token: category
    for category, token in PSEUDONYMIZATION_CATEGORY_TOKENS
}
_PSEUDONYM_TOKEN_PATTERN = '|'.join(
    sorted(
        (re.escape(token) for token in _PSEUDONYM_CATEGORY_BY_TOKEN),
        key=len,
        reverse=True,
    )
)
_EXACT_PSEUDONYM_TOKEN_RE = re.compile(
    r'\[(?P<token>' + _PSEUDONYM_TOKEN_PATTERN
    + r')_(?P<index>[1-9][0-9]*)\]'
)
_ALIAS_LIKE_RE = re.compile(
    r'\[(?:'
    r'(?:' + _PSEUDONYM_TOKEN_PATTERN + r')(?:_[^\]\r\n]*)?'
    r'|[가-힣A-Za-z]{1,24}_[A-Za-z0-9-]{1,20}'
    r')(?:\]|$)'
)


@contextmanager
def _private_source_copy(uploaded_file):
    descriptor, source_path = tempfile.mkstemp(
        prefix='inpa-pdf-', suffix='.pdf')
    descriptor_open = True
    digest = hashlib.sha256()
    file_size = 0
    magic = b''

    try:
        os.fchmod(descriptor, 0o600)
        uploaded_file.seek(0)
        with os.fdopen(descriptor, 'wb') as private_file:
            descriptor_open = False
            while True:
                chunk = uploaded_file.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    raise PDFImportError('INVALID_PDF')
                file_size += len(chunk)
                if file_size > MAX_FILE_BYTES:
                    raise PDFImportError('FILE_TOO_LARGE')
                if len(magic) < 5:
                    magic += chunk[:5 - len(magic)]
                digest.update(chunk)
                private_file.write(chunk)

        if magic != b'%PDF-':
            raise PDFImportError('INVALID_PDF')
        yield source_path, digest.hexdigest(), file_size
    finally:
        if descriptor_open:
            os.close(descriptor)
        try:
            os.unlink(source_path)
        except FileNotFoundError:
            pass
        uploaded_file.seek(0)


def _child_command(source_path, file_sha256, file_size):
    return [
        sys.executable,
        '-m',
        'inpa.insurances.import_pdf_sandbox',
        '--child',
        '--source-path', source_path,
        '--file-sha256', file_sha256,
        '--file-size', str(file_size),
        '--max-pages', str(settings.INSURANCE_MAX_PAGES),
        '--max-chars', str(settings.INSURANCE_MAX_EXTRACTED_CHARS),
        '--max-candidates', str(settings.INSURANCE_MAX_CANDIDATES),
        '--cpu-seconds', str(settings.INSURANCE_PDF_SANDBOX_CPU_SECONDS),
        '--memory-bytes', str(
            settings.INSURANCE_PDF_SANDBOX_MEMORY_MB * 1024 * 1024),
    ]


def _child_environment():
    environment = {
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONHASHSEED': 'random',
    }
    path = os.environ.get('PATH')
    if path:
        environment['PATH'] = path
    return environment


def _safe_protocol_payload(stdout, max_chars, max_candidates):
    if not isinstance(stdout, bytes):
        return None
    max_protocol_bytes = max_chars * 8 + max_candidates * 1024 + 65_536
    if len(stdout) > max_protocol_bytes:
        return None
    try:
        payload = json.loads(stdout.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _strict_positive_int(value):
    return type(value) is int and value > 0


def _strict_nonnegative_int(value):
    return type(value) is int and value >= 0


def _decode_quarantined_line_ids(raw_ids, *, claimed_count,
                                 page_count, max_chars):
    if (not isinstance(raw_ids, list)
            or len(raw_ids) != claimed_count
            or claimed_count > max_chars):
        raise PDFImportError('PDF_PARSE_FAILED')
    decoded = []
    prior_coordinate = (0, 0)
    for line_id in raw_ids:
        if not isinstance(line_id, str):
            raise PDFImportError('PDF_PARSE_FAILED')
        match = re.fullmatch(r'p(?P<page>[0-9]+)-l(?P<line>[0-9]+)', line_id)
        if match is None:
            raise PDFImportError('PDF_PARSE_FAILED')
        page = int(match.group('page'))
        line = int(match.group('line'))
        coordinate = (page, line)
        if (not _strict_positive_int(page)
                or page > page_count
                or not _strict_positive_int(line)
                or line > max_chars
                or line_id != f'p{page:02d}-l{line:03d}'
                or coordinate <= prior_coordinate):
            raise PDFImportError('PDF_PARSE_FAILED')
        decoded.append(line_id)
        prior_coordinate = coordinate
    return tuple(decoded)


def _validate_pseudonym_alias_proof(
        masked_lines, claimed_counts, *, max_chars):
    occurrence_counts = Counter()
    observed_indices = defaultdict(set)

    for line in masked_lines:
        for alias_like in _ALIAS_LIKE_RE.finditer(line.text_masked):
            exact = _EXACT_PSEUDONYM_TOKEN_RE.fullmatch(alias_like.group(0))
            if exact is None:
                raise PDFImportError('PDF_PARSE_FAILED')
            category = _PSEUDONYM_CATEGORY_BY_TOKEN[exact.group('token')]
            index_text = exact.group('index')
            if len(index_text) > len(str(max_chars)):
                raise PDFImportError('PDF_PARSE_FAILED')
            index = int(index_text)
            if index > max_chars:
                raise PDFImportError('PDF_PARSE_FAILED')
            occurrence_counts[category] += 1
            observed_indices[category].add(index)

    for category, indices in observed_indices.items():
        if indices != set(range(1, max(indices) + 1)):
            raise PDFImportError('PDF_PARSE_FAILED')
        if max(indices) > occurrence_counts[category]:
            raise PDFImportError('PDF_PARSE_FAILED')

    actual_counts = tuple(
        (category, occurrence_counts[category])
        for category in PSEUDONYMIZATION_CATEGORIES
        if occurrence_counts[category]
    )
    if (claimed_counts != actual_counts
            or sum(count for _category, count in claimed_counts) > max_chars):
        raise PDFImportError('PDF_PARSE_FAILED')


def _decode_result(result, *, expected_sha256, expected_size,
                   max_pages, max_chars, max_candidates):
    expected_result_keys = {
        'file_sha256', 'file_size', 'page_count',
        'masked_lines', 'candidates', 'pseudonymization_counts',
        'residual_scan_passed', 'image_only_page_count', 'image_only_pages',
        'quarantined_line_count', 'quarantined_line_ids',
        'analysis_signal_quarantined_line_count',
        'analysis_signal_quarantined_line_ids',
    }
    if not isinstance(result, dict) or set(result) != expected_result_keys:
        raise PDFImportError('PDF_PARSE_FAILED')
    if (not isinstance(result['file_sha256'], str)
            or not secrets.compare_digest(
                result['file_sha256'], expected_sha256)):
        raise PDFImportError('PDF_PARSE_FAILED')
    if result['file_size'] != expected_size:
        raise PDFImportError('PDF_PARSE_FAILED')
    if (not _strict_positive_int(result['page_count'])
            or result['page_count'] > max_pages):
        raise PDFImportError('PDF_PARSE_FAILED')
    if (not _strict_nonnegative_int(result['image_only_page_count'])
            or result['image_only_page_count'] >= result['page_count']):
        raise PDFImportError('PDF_PARSE_FAILED')
    raw_image_only_pages = result['image_only_pages']
    if (not isinstance(raw_image_only_pages, list)
            or len(raw_image_only_pages)
            != result['image_only_page_count']):
        raise PDFImportError('PDF_PARSE_FAILED')
    image_only_pages = []
    prior_image_only_page = 0
    for page in raw_image_only_pages:
        if (not _strict_positive_int(page)
                or page > result['page_count']
                or page <= prior_image_only_page):
            raise PDFImportError('PDF_PARSE_FAILED')
        image_only_pages.append(page)
        prior_image_only_page = page
    if result['residual_scan_passed'] is not True:
        raise PDFImportError('PDF_PARSE_FAILED')
    if (not _strict_nonnegative_int(result['quarantined_line_count'])
            or result['quarantined_line_count'] > max_chars):
        raise PDFImportError('PDF_PARSE_FAILED')
    quarantined_line_ids = _decode_quarantined_line_ids(
        result['quarantined_line_ids'],
        claimed_count=result['quarantined_line_count'],
        page_count=result['page_count'],
        max_chars=max_chars,
    )
    if (not _strict_nonnegative_int(
            result['analysis_signal_quarantined_line_count'])
            or result['analysis_signal_quarantined_line_count']
            > result['quarantined_line_count']):
        raise PDFImportError('PDF_PARSE_FAILED')
    analysis_signal_quarantined_line_ids = _decode_quarantined_line_ids(
        result['analysis_signal_quarantined_line_ids'],
        claimed_count=result['analysis_signal_quarantined_line_count'],
        page_count=result['page_count'],
        max_chars=max_chars,
    )
    if not set(analysis_signal_quarantined_line_ids).issubset(
            quarantined_line_ids):
        raise PDFImportError('PDF_PARSE_FAILED')

    raw_counts = result['pseudonymization_counts']
    if (not isinstance(raw_counts, list)
            or len(raw_counts) > len(PSEUDONYMIZATION_CATEGORIES)):
        raise PDFImportError('PDF_PARSE_FAILED')
    pseudonymization_counts = []
    prior_category_position = -1
    for raw_count in raw_counts:
        if not isinstance(raw_count, list) or len(raw_count) != 2:
            raise PDFImportError('PDF_PARSE_FAILED')
        category, count = raw_count
        if (category not in PSEUDONYMIZATION_CATEGORIES
                or not _strict_positive_int(count)
                or count > max_chars):
            raise PDFImportError('PDF_PARSE_FAILED')
        category_position = PSEUDONYMIZATION_CATEGORIES.index(category)
        if category_position <= prior_category_position:
            raise PDFImportError('PDF_PARSE_FAILED')
        prior_category_position = category_position
        pseudonymization_counts.append((category, count))

    raw_lines = result['masked_lines']
    if not isinstance(raw_lines, list) or len(raw_lines) > max_chars:
        raise PDFImportError('PDF_PARSE_FAILED')
    masked_lines = []
    lines_by_id = {}
    masked_character_count = 0
    prior_coordinate = (0, 0)
    for raw_line in raw_lines:
        if not isinstance(raw_line, dict) or set(raw_line) != {
                'line_id', 'page', 'line', 'text_masked'}:
            raise PDFImportError('PDF_PARSE_FAILED')
        line_id = raw_line['line_id']
        page = raw_line['page']
        line_number = raw_line['line']
        text_masked = raw_line['text_masked']
        expected_line_id = (
            f'p{page:02d}-l{line_number:03d}'
            if _strict_positive_int(page) and _strict_positive_int(line_number)
            else None
        )
        if (not isinstance(line_id, str)
                or line_id != expected_line_id
                or page > result['page_count']
                or not isinstance(text_masked, str)
                or not text_masked
                or line_id in lines_by_id
                or (page, line_number) <= prior_coordinate):
            raise PDFImportError('PDF_PARSE_FAILED')
        prior_coordinate = (page, line_number)
        masked_character_count += len(text_masked)
        if masked_character_count > max_chars:
            raise PDFImportError('PDF_PARSE_FAILED')
        line = MaskedLine(
            line_id=line_id,
            page=page,
            line=line_number,
            text_masked=text_masked,
        )
        masked_lines.append(line)
        lines_by_id[line_id] = line

    if (set(quarantined_line_ids) & set(lines_by_id)
            or any(
                int(line_id[1:line_id.index('-l')]) in image_only_pages
                for line_id in quarantined_line_ids)):
        raise PDFImportError('PDF_PARSE_FAILED')

    pseudonymized_pages = [[] for _unused in range(result['page_count'])]
    for line in masked_lines:
        pseudonymized_pages[line.page - 1].append(line.text_masked)
    observed_image_only_pages = tuple(
        page_number
        for page_number, page_lines in enumerate(
            pseudonymized_pages, start=1)
        if not page_lines
    )
    if observed_image_only_pages != tuple(image_only_pages):
        raise PDFImportError('PDF_PARSE_FAILED')
    _validate_pseudonym_alias_proof(
        masked_lines,
        tuple(pseudonymization_counts),
        max_chars=max_chars,
    )
    assert_pseudonymized_pages_safe(tuple(
        tuple(page_lines) for page_lines in pseudonymized_pages
    ))

    raw_candidates = result['candidates']
    if (not isinstance(raw_candidates, list)
            or len(raw_candidates) > max_candidates):
        raise PDFImportError('PDF_PARSE_FAILED')
    candidates = []
    candidate_character_count = 0
    for candidate_number, raw_candidate in enumerate(
            raw_candidates, start=1):
        if not isinstance(raw_candidate, dict) or set(raw_candidate) != {
                'candidate_id', 'evidence_line_ids', 'text_masked',
                'review_status'}:
            raise PDFImportError('PDF_PARSE_FAILED')
        evidence = raw_candidate['evidence_line_ids']
        candidate_id = raw_candidate['candidate_id']
        text_masked = raw_candidate['text_masked']
        if (candidate_id != f'c{candidate_number:05d}'
                or not isinstance(evidence, list)
                or len(evidence) != 1
                or evidence[0] not in lines_by_id
                or not isinstance(text_masked, str)
                or text_masked != lines_by_id[evidence[0]].text_masked
                or raw_candidate['review_status'] != 'needs_review'):
            raise PDFImportError('PDF_PARSE_FAILED')
        candidate_character_count += len(text_masked)
        if candidate_character_count > max_chars:
            raise PDFImportError('PDF_PARSE_FAILED')
        candidates.append(CoverageCandidate(
            candidate_id=candidate_id,
            evidence_line_ids=tuple(evidence),
            text_masked=text_masked,
            review_status='needs_review',
        ))

    return ExtractedPDF(
        file_sha256=expected_sha256,
        file_size=expected_size,
        page_count=result['page_count'],
        masked_lines=tuple(masked_lines),
        candidates=tuple(candidates),
        pseudonymization_counts=tuple(pseudonymization_counts),
        residual_scan_passed=True,
        image_only_page_count=result['image_only_page_count'],
        image_only_pages=tuple(image_only_pages),
        quarantined_line_count=result['quarantined_line_count'],
        quarantined_line_ids=quarantined_line_ids,
        analysis_signal_quarantined_line_count=(
            result['analysis_signal_quarantined_line_count']),
        analysis_signal_quarantined_line_ids=(
            analysis_signal_quarantined_line_ids),
    )


def _decode_child(completed, *, expected_sha256, expected_size):
    max_pages = settings.INSURANCE_MAX_PAGES
    max_chars = settings.INSURANCE_MAX_EXTRACTED_CHARS
    max_candidates = settings.INSURANCE_MAX_CANDIDATES
    payload = _safe_protocol_payload(
        completed.stdout, max_chars, max_candidates)

    if (isinstance(payload, dict)
            and set(payload) == {'protocol_version', 'ok', 'error'}
            and payload.get('protocol_version') == _PROTOCOL_VERSION
            and payload.get('ok') is False
            and payload.get('error') in _CHILD_DOMAIN_ERRORS):
        raise PDFImportError(payload['error'])

    if completed.returncode != 0:
        if completed.returncode < 0 or completed.returncode == 137:
            raise PDFImportError('PDF_PARSE_RESOURCE_LIMIT')
        raise PDFImportError('PDF_PARSE_FAILED')

    if (not isinstance(payload, dict)
            or set(payload) != {'protocol_version', 'ok', 'result'}
            or payload.get('protocol_version') != _PROTOCOL_VERSION
            or payload.get('ok') is not True):
        raise PDFImportError('PDF_PARSE_FAILED')
    return _decode_result(
        payload['result'],
        expected_sha256=expected_sha256,
        expected_size=expected_size,
        max_pages=max_pages,
        max_chars=max_chars,
        max_candidates=max_candidates,
    )


def extract_pdf(uploaded_file):
    """Parse one untrusted PDF behind a disposable, hard-bounded process."""
    with _private_source_copy(uploaded_file) as (
            source_path, file_sha256, file_size):
        command = _child_command(source_path, file_sha256, file_size)
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=settings.INSURANCE_PDF_SANDBOX_WALL_SECONDS,
                check=False,
                cwd=str(settings.BASE_DIR),
                env=_child_environment(),
                close_fds=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise PDFImportError('PDF_PARSE_TIMEOUT') from exc
        except OSError as exc:
            raise PDFImportError('PDF_PARSE_FAILED') from exc

        return _decode_child(
            completed,
            expected_sha256=file_sha256,
            expected_size=file_size,
        )
