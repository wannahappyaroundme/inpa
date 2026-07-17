import argparse
import json
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import asdict

from .import_contract import (
    COVERAGE_MARKERS,
    CoverageCandidate,
    ExtractedPDF,
    MaskedLine,
    PDFImportError,
)
from .import_pdf_mask import pseudonymize_page_lines


PROTOCOL_VERSION = 1
_AMOUNT_RE = re.compile(
    r'(?:[0-9][0-9,]{0,24}(?:\.[0-9]{1,4})?[ \t]*'
    r'(?:억|천|백)?[ \t]*만?[ \t]*원)')
_PERIOD_RE = re.compile(
    r'(?:[0-9]{1,3}[ \t]*(?:년|개월|세)[ \t]*'
    r'(?:납입|보장|만기|갱신)|'
    r'(?:납입|보장|만기|갱신)(?:기간)?[ \t]*'
    r'[0-9]{1,3}[ \t]*(?:년|개월|세))')
def apply_process_limits(*, cpu_seconds, memory_bytes):
    """Apply hard child limits on production Linux, report support honestly."""
    if not sys.platform.startswith('linux'):
        return False
    if cpu_seconds <= 0 or memory_bytes <= 0:
        raise ValueError('sandbox limits must be positive')

    import resource

    resource.setrlimit(
        resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(
        resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    return True


def _open_pdf(source_path):
    # This import stays behind apply_process_limits() in the child entrypoint.
    import pdfplumber

    return pdfplumber.open(source_path)


def _is_password_error(exception):
    from pdfminer.pdfdocument import PDFPasswordIncorrect

    if isinstance(exception, PDFPasswordIncorrect):
        return True
    return any(
        isinstance(item, PDFPasswordIncorrect)
        for item in getattr(exception, 'args', ())
    )


def _is_candidate_line(text):
    if any(marker in text for marker in COVERAGE_MARKERS):
        return True
    if '원' in text and _AMOUNT_RE.search(text):
        return True
    if any(marker in text for marker in ('납입', '보장', '만기', '갱신')):
        return _PERIOD_RE.search(text) is not None
    return False


def parse_pdf_path(source_path, *, file_sha256, file_size, max_pages,
                   max_chars, max_candidates):
    """Parse one private local PDF path and return masked contracts only."""
    masked_lines = []
    candidates = []
    masked_character_count = 0

    try:
        with _open_pdf(source_path) as pdf:
            pdf_document = getattr(pdf, 'doc', None)
            if getattr(pdf_document, 'encryption', None) is not None:
                raise PDFImportError('ENCRYPTED_PDF')

            page_count = len(pdf.pages)
            if page_count == 0:
                raise PDFImportError('IMAGE_PDF')
            if page_count > max_pages:
                raise PDFImportError('TOO_MANY_PAGES')

            page_source_lines = []
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                source_lines = tuple(page_text.splitlines())
                page_source_lines.append(source_lines)

            image_only_pages = tuple(
                page_number
                for page_number, source_lines in enumerate(
                    page_source_lines, start=1)
                if not any(line.strip() for line in source_lines)
            )
            image_only_page_count = len(image_only_pages)
            if image_only_page_count == page_count:
                raise PDFImportError('IMAGE_PDF')

            pseudonymized = pseudonymize_page_lines(tuple(page_source_lines))
            for page_number, (source_lines, masked_page) in enumerate(
                    zip(page_source_lines, pseudonymized.pages), start=1):
                if (any(line.strip() for line in source_lines)
                        and not any(line.strip() for line in masked_page)):
                    raise PDFImportError('PII_REDACTION_UNCERTAIN')
            for page_number, page_lines in enumerate(
                    pseudonymized.pages, start=1):
                for line_number, masked_text in enumerate(page_lines, start=1):
                    masked_text = masked_text.strip()
                    if not masked_text:
                        continue
                    masked_character_count += len(masked_text)
                    if masked_character_count > max_chars:
                        raise PDFImportError('DOCUMENT_TOO_LONG')

                    line = MaskedLine(
                        line_id=f'p{page_number:02d}-l{line_number:03d}',
                        page=page_number,
                        line=line_number,
                        text_masked=masked_text,
                    )
                    masked_lines.append(line)
                    if _is_candidate_line(masked_text):
                        candidate_number = len(candidates) + 1
                        if candidate_number > max_candidates:
                            raise PDFImportError('TOO_MANY_CANDIDATES')
                        candidates.append(CoverageCandidate(
                            candidate_id=f'c{candidate_number:05d}',
                            evidence_line_ids=(line.line_id,),
                            text_masked=masked_text,
                        ))
    except PDFImportError:
        raise
    except MemoryError:
        raise
    except Exception as exc:
        if _is_password_error(exc):
            raise PDFImportError('ENCRYPTED_PDF') from exc
        raise PDFImportError('INVALID_PDF') from exc

    return ExtractedPDF(
        file_sha256=file_sha256,
        file_size=file_size,
        page_count=page_count,
        masked_lines=tuple(masked_lines),
        candidates=tuple(candidates),
        pseudonymization_counts=pseudonymized.category_counts,
        residual_scan_passed=pseudonymized.residual_scan_passed,
        image_only_page_count=image_only_page_count,
        image_only_pages=image_only_pages,
        quarantined_line_count=pseudonymized.quarantined_line_count,
        quarantined_line_ids=pseudonymized.quarantined_line_ids,
        analysis_signal_quarantined_line_count=(
            pseudonymized.analysis_signal_quarantined_line_count),
        analysis_signal_quarantined_line_ids=(
            pseudonymized.analysis_signal_quarantined_line_ids),
    )


def encode_success(result):
    return json.dumps({
        'protocol_version': PROTOCOL_VERSION,
        'ok': True,
        'result': asdict(result),
    }, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def encode_error(code):
    return json.dumps({
        'protocol_version': PROTOCOL_VERSION,
        'ok': False,
        'error': code,
    }, separators=(',', ':')).encode('ascii')


@contextmanager
def _silenced_parser_output():
    protocol_fd = os.dup(sys.stdout.fileno())
    null_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(null_fd, sys.stdout.fileno())
        os.dup2(null_fd, sys.stderr.fileno())
        yield protocol_fd
    finally:
        os.close(null_fd)


def _write_protocol(protocol_fd, payload):
    remaining = memoryview(payload)
    while remaining:
        written = os.write(protocol_fd, remaining)
        remaining = remaining[written:]
    os.close(protocol_fd)


def _parser():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--child', action='store_true', required=True)
    parser.add_argument('--source-path', required=True)
    parser.add_argument('--file-sha256', required=True)
    parser.add_argument('--file-size', type=int, required=True)
    parser.add_argument('--max-pages', type=int, required=True)
    parser.add_argument('--max-chars', type=int, required=True)
    parser.add_argument('--max-candidates', type=int, required=True)
    parser.add_argument('--cpu-seconds', type=int, required=True)
    parser.add_argument('--memory-bytes', type=int, required=True)
    return parser


def _execute_child(args):
    try:
        apply_process_limits(
            cpu_seconds=args.cpu_seconds,
            memory_bytes=args.memory_bytes,
        )
        result = parse_pdf_path(
            args.source_path,
            file_sha256=args.file_sha256,
            file_size=args.file_size,
            max_pages=args.max_pages,
            max_chars=args.max_chars,
            max_candidates=args.max_candidates,
        )
        return 0, encode_success(result)
    except MemoryError:
        return 3, encode_error('PDF_PARSE_RESOURCE_LIMIT')
    except PDFImportError as exc:
        return 2, encode_error(exc.code)
    except BaseException:
        return 3, encode_error('PDF_PARSE_FAILED')


def main(argv=None):
    args = _parser().parse_args(argv)
    with _silenced_parser_output() as protocol_fd:
        return_code, payload = _execute_child(args)
        _write_protocol(protocol_fd, payload)
    return return_code


if __name__ == '__main__':
    raise SystemExit(main())
