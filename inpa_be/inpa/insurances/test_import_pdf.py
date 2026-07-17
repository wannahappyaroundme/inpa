import base64
import hashlib
import io
import json
import subprocess
import tempfile
from dataclasses import asdict
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from .import_contract import ExtractedPDF, MaskedLine, PDFImportError
from .import_pdf import MAX_FILE_BYTES, _decode_child, extract_pdf
from .import_pdf_sandbox import encode_error, encode_success, parse_pdf_path


_ENCRYPTED_EMPTY_PASSWORD_PDF = base64.b64decode(
    'JVBERi0xLjcKJcfsj6IKJSVJbnZvY2F0aW9uOiBncyAtcSAtZE5PUEFVU0UgLWRCQVRDSCAtc0RFVklDRT1wZGZ3cml0ZSAtc093bmVyUGFzc3dvcmQ9PyAtc1VzZXJQYXNzd29yZD0gLWRFbmNyeXB0aW9uUj0zIC1kS2V5TGVuZ3RoPTEyOCAtc091dHB1dEZpbGU9PyA/CjUgMCBvYmoKPDwvTGVuZ3RoIDYgMCBSL0ZpbHRlciAvRmxhdGVEZWNvZGU+PgpzdHJlYW0K1ZxZk6saxo8O1yIDQ+UcoLF+a0JwGezFDCMEZraHFESuYP0VZ5BeqJg24xnhWwDsIpjGHFx++JLIV101fZDpHHF5Q4Mkv1C4Bcbu+rLQHGzgbM4+MkkMZW5kc3RyZWFtCmVuZG9iago0IDAgb2JqCjw8L1R5cGUvUGFnZS9NZWRpYUJveCBbMCAwIDYxMiA3OTJdCi9Sb3RhdGUgMC9QYXJlbnQgMyAwIFIKL1Jlc291cmNlczw8L1Byb2NTZXRbL1BERiAvVGV4dF0KL0ZvbnQgOSAwIFIKPj4KL0NvbnRlbnRzIDUgMCBSCj4+CmVuZG9iagozIDAgb2JqCjw8IC9UeXBlIC9QYWdlcyAvS2lkcyBbCjQgMCBSCl0gL0NvdW50IDEKPj4KZW5kb2JqCjEgMCBvYmoKPDwvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMyAwIFIKL01ldGFkYXRhIDExIDAgUgo+PgplbmRvYmoKMTAgMCBvYmoKPDwvRmlsdGVyL0ZsYXRlRGVjb2RlL0xlbmd0aCAyMzg+PnN0cmVhbQpl/u1AcDxYb/B/ptjm+NmIqijKQmLBYTBCN+Mn9BXlBjoPMqa2x0JT/rVjjV7Cf06o3g0fSu830mvk4LS8QLz2cpDbTSnpriJIRI49pI5c+DAbmH5Zmyhu3zPZpxIG3Mrs55cvwPgCQrA/Oe9kP0rRsVTZa3RpGNnx3AfAewvfNF5JOq40aQ5D4pUPFyL9ZiSLp6QnrVQMXxQ3WIyL5cWLLdzQN0yum0OYQXX0yEXoD/oXHWTIL3wtbEiHxHi3D92SHfONgVRM+oC23O/cNAnWcwzhVLmpHDaHeNfmdPP6YlPpuddGdRfwcQ8Y11jeCmVuZHN0cmVhbQplbmRvYmoKMTEgMCBvYmoKPDwvVHlwZS9NZXRhZGF0YQovU3VidHlwZS9YTUwvTGVuZ3RoIDE0NTc+PnN0cmVhbQo8P3hwYWNrZXQgYmVnaW49J++7vycgaWQ9J1c1TTBNcENlaGlIenJlU3pOVGN6a2M5ZCc/Pgo8P2Fkb2JlLXhhcC1maWx0ZXJzIGVzYz0iQ1JMRiI/Pgo8eDp4bXBtZXRhIHhtbG5zOng9J2Fkb2JlOm5zOm1ldGEvJyB4OnhtcHRrPSdYTVAgdG9vbGtpdCAyLjkuMS0xMywgZnJhbWV3b3JrIDEuNic+CjxyZGY6UkRGIHhtbG5zOnJkZj0naHR0cDovL3d3dy53My5vcmcvMTk5OS8wMi8yMi1yZGYtc3ludGF4LW5zIycgeG1sbnM6aVg9J2h0dHA6Ly9ucy5hZG9iZS5jb20vaVgvMS4wLyc+CjxyZGY6RGVzY3JpcHRpb24gcmRmOmFib3V0PSIiIHhtbG5zOnBkZj0naHR0cDovL25zLmFkb2JlLmNvbS9wZGYvMS4zLycgcGRmOlByb2R1Y2VyPSdHUEwgR2hvc3RzY3JpcHQgMTAuMDcuMCcvPgo8cmRmOkRlc2NyaXB0aW9uIHJkZjphYm91dD0iIiB4bWxuczp4bXA9J2h0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC8nPjx4bXA6TW9kaWZ5RGF0ZT4yMDI2LTA3LTE2VDAzOjEyOjMwKzA5OjAwPC94bXA6TW9kaWZ5RGF0ZT4KPHhtcDpDcmVhdGVEYXRlPjIwMjYtMDctMTZUMDM6MTI6MzArMDk6MDA8L3htcDpDcmVhdGVEYXRlPgo8eG1wOk1ldGFkYXRhRGF0ZT4yMDI2LTA3LTE2VDAzOjEyOjMwKzA5OjAwPC94bXA6TWV0YWRhdGFEYXRlPgo8eG1wOkNyZWF0b3JUb29sPidVbmtub3duQXBwbGljYXRpb24nPC94bXA6Q3JlYXRvclRvb2w+PC9yZGY6RGVzY3JpcHRpb24+CjxyZGY6RGVzY3JpcHRpb24gcmRmOmFib3V0PSIiIHhtbG5zOnhtcE1NPSdodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvbW0vJyB4bXBNTTpEb2N1bWVudElEPSd1dWlkOjRiMGRiN2VmLWI4OTUtMTFmYy0wMDAwLTczZjQ3ZmQzZWQ4ZScvPgo8cmRmOkRlc2NyaXB0aW9uIHJkZjphYm91dD0iIiB4bWxuczp4bXBNTT0naHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLycgeG1wTU06UmVuZGl0aW9uQ2xhc3M9J2RlZmF1bHQnLz4KPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wTU09J2h0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9tbS8nIHhtcE1NOlZlcnNpb25JRD0nMScvPgo8cmRmOkRlc2NyaXB0aW9uIHJkZjphYm91dD0iIiB4bWxuczpkYz0naHR0cDovL3B1cmwub3JnL2RjL2VsZW1lbnRzLzEuMS8nIGRjOmZvcm1hdD0nYXBwbGljYXRpb24vcGRmJz48ZGM6dGl0bGU+PHJkZjpBbHQ+PHJkZjpsaSB4bWw6bGFuZz0neC1kZWZhdWx0Jz4nVW50aXRsZWQnPC9yZGY6bGk+PC9yZGY6QWx0PjwvZGM6dGl0bGU+PC9yZGY6RGVzY3JpcHRpb24+CjwvcmRmOlJERj4KPC94OnhtcG1ldGE+CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKPD94cGFja2V0IGVuZD0ndyc/PgplbmRzdHJlYW0KZW5kb2JqCjggMCBvYmoKPDwvRmlsdGVyL0ZsYXRlRGVjb2RlCi9UeXBlL09ialN0bQovTiA0Ci9GaXJzdCAxOS9MZW5ndGggMTc5Pj5zdHJlYW0K+/vYTCr0z58jXtXAWQn5m5ZBwGDgbX8UnorFwl1Ov2spid7WxUxC67RmqOLHWocHRnUva4CLF9z0J5QcKqY/PBRPNeFGqHVdRrox+LQOAZfrsF2ZLLn8IFDmv4JCsyCwghd0pcEn/GfBbKNQT09XqoHPelQswFkI7Rp+ZqMwhggNP6/6G7gFP/iGGQ42GQ9F7HCGMx/9MohL+j1CZ6TgINrTGEA8LQZy1+GMa3UaYGGnI9kKZW5kc3RyZWFtCmVuZG9iagoxMiAwIG9iago8PC9GaWx0ZXIgL1N0YW5kYXJkIC9WIDIgL0xlbmd0aCAxMjggL1IgMyAvUCAtNCAvTyAokTsHP1tllUyLbaIhaZcaF3t+bZShBv91wMFilrwVQS4pCi9VICiWwdRKQ04nIZbZXHJGjaekB1wov05eTnWKQWQATlb/+gEIKT4+CmVuZG9iagoxMyAwIG9iago8PAovVHlwZSAvWFJlZgovU2l6ZSAxNAovUm9vdCAxIDAgUiAvSW5mbyAyIDAgUgovSUQgWzwyMzhBQTlBQzA1Q0RFNUE5MzA3QTQzQjBDOURFNjkzRj48MjM4QUE5QUMwNUNERTVBOTMwN0E0M0IwQzlERTY5M0Y+XQovRW5jcnlwdCAxMiAwIFIgL0luZGV4IFswIDE0IF0KL1cgWzEgMiAyXQovRmlsdGVyIC9GbGF0ZURlY29kZS9MZW5ndGggNjEKPj4Kc3RyZWFtCnicY2Bg+P+fkfE/AwMTAwcDMyPjEQYGRkZzIMEwCyIGJpgYOQsgLEZGJgegLHMRkOBqAhLcQgwMADXHBqYKZW5kc3RyZWFtCmVuZG9iagpzdGFydHhyZWYKMjgzNAolJUVPRgo='
)


class _Page:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class _PDF:
    def __init__(self, page_texts):
        self.pages = [_Page(text) for text in page_texts]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _upload(body=b'%PDF-1.7\nbody'):
    upload = io.BytesIO(body)
    upload.name = 'policy.pdf'
    return upload


class PDFImportTests(SimpleTestCase):
    def setUp(self):
        self.run_sandbox = mock.patch(
            'inpa.insurances.import_pdf.subprocess.run',
            side_effect=self._run_child_in_process,
        )
        self.run_sandbox.start()
        self.addCleanup(self.run_sandbox.stop)

    @staticmethod
    def _run_child_in_process(command, **_kwargs):
        def argument(name):
            return command[command.index(name) + 1]

        try:
            result = parse_pdf_path(
                argument('--source-path'),
                file_sha256=argument('--file-sha256'),
                file_size=int(argument('--file-size')),
                max_pages=int(argument('--max-pages')),
                max_chars=int(argument('--max-chars')),
                max_candidates=int(argument('--max-candidates')),
            )
        except PDFImportError as exc:
            return subprocess.CompletedProcess(
                command, 2, stdout=encode_error(exc.code))
        return subprocess.CompletedProcess(
            command, 0, stdout=encode_success(result))

    def assert_error_code(self, code, upload, page_texts=None):
        opener = mock.patch(
            'inpa.insurances.import_pdf_sandbox._open_pdf',
            return_value=_PDF(page_texts or ['일반암진단비 3,000만원']),
        )
        with opener, self.assertRaises(PDFImportError) as caught:
            extract_pdf(upload)
        self.assertEqual(caught.exception.code, code)

    def test_pdf_extension_without_pdf_magic_is_invalid(self):
        self.assert_error_code('INVALID_PDF', _upload(b'not a pdf'))

    def test_encrypted_pdf_has_specific_safe_error(self):
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                side_effect=PDFPasswordIncorrect), \
                self.assertRaises(PDFImportError) as caught:
            extract_pdf(_upload())

        self.assertEqual(caught.exception.code, 'ENCRYPTED_PDF')

    def test_empty_user_password_encrypted_pdf_is_rejected_from_metadata(self):
        self.run_sandbox.stop()
        try:
            with self.assertRaises(PDFImportError) as caught:
                extract_pdf(_upload(_ENCRYPTED_EMPTY_PASSWORD_PDF))
        finally:
            self.run_sandbox.start()

        self.assertEqual(caught.exception.code, 'ENCRYPTED_PDF')

    def test_password_exception_wrapped_by_pdfplumber_is_encrypted_error(self):
        wrapped = PdfminerException(PDFPasswordIncorrect())
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                side_effect=wrapped), self.assertRaises(
                    PDFImportError) as caught:
            extract_pdf(_upload())

        self.assertEqual(caught.exception.code, 'ENCRYPTED_PDF')

    def test_page_without_text_is_rejected_as_image_pdf(self):
        self.assert_error_code('IMAGE_PDF', _upload(), page_texts=[''])

    def test_mixed_image_and_text_pages_are_accepted_with_exact_metadata(self):
        pages = (
            '',
            ' ',
            '안내\n\n일반암진단비 3,000만원',
            None,
            '상해수술비 100만원',
            '',
        )
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF(pages)):
            result = extract_pdf(_upload())

        self.assertEqual(result.page_count, 6)
        self.assertEqual(result.image_only_page_count, 4)
        self.assertEqual(result.image_only_pages, (1, 2, 4, 6))
        self.assertEqual(
            [line.line_id for line in result.masked_lines],
            ['p03-l003', 'p05-l001'],
        )
        self.assertEqual(
            [candidate.evidence_line_ids for candidate in result.candidates],
            [('p03-l003',), ('p05-l001',)],
        )
        self.assertEqual(result.quarantined_line_count, 1)
        self.assertEqual(result.quarantined_line_ids, ('p03-l001',))
        self.assertEqual(result.analysis_signal_quarantined_line_count, 0)

    def test_301_pages_are_rejected_before_page_extraction(self):
        pages = [mock.Mock(spec=['extract_text']) for _ in range(301)]
        pdf = mock.MagicMock()
        pdf.__enter__.return_value.pages = pages
        pdf.__enter__.return_value.doc.encryption = None
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=pdf), self.assertRaises(PDFImportError) as caught:
            extract_pdf(_upload())

        self.assertEqual(caught.exception.code, 'TOO_MANY_PAGES')
        for page in pages:
            page.extract_text.assert_not_called()

    def test_500001_masked_characters_are_rejected_without_partial_result(self):
        text = '\n'.join(['가' * 100] * 5_000 + ['나'])
        self.assert_error_code(
            'DOCUMENT_TOO_LONG', _upload(), page_texts=[text])

    def test_exact_masked_character_limit_is_allowed(self):
        text = '\n'.join(['가' * 100] * 5_000)
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF([text])):
            result = extract_pdf(_upload())

        self.assertEqual(
            sum(len(line.text_masked) for line in result.masked_lines),
            500_000,
        )

    def test_2001_candidates_are_rejected_without_truncation(self):
        text = '\n'.join(
            f'{number}번 일반암진단비 100만원' for number in range(2_001))
        self.assert_error_code(
            'TOO_MANY_CANDIDATES', _upload(), page_texts=[text])

    def test_exact_candidate_limit_is_allowed_and_preserved(self):
        text = '\n'.join(
            f'{number}번 일반암진단비 100만원' for number in range(2_000))
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF([text])):
            result = extract_pdf(_upload())

        self.assertEqual(len(result.candidates), 2_000)
        self.assertEqual(result.candidates[-1].candidate_id, 'c02000')

    def test_line_ids_are_stable_page_and_source_line_coordinates(self):
        third_page = '\n'.join(
            [f'안내 {number}' for number in range(1, 13)]
            + ['', '일반암진단비 3,000만원'])
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF(['첫 페이지', '둘째 페이지', third_page])):
            first = extract_pdf(_upload())
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF(['첫 페이지', '둘째 페이지', third_page])):
            second = extract_pdf(_upload())

        target = first.masked_lines[-1]
        self.assertEqual((target.line_id, target.page, target.line),
                         ('p03-l014', 3, 14))
        self.assertEqual(first.masked_lines, second.masked_lines)
        self.assertEqual(first.candidates, second.candidates)

    def test_image_only_pages_are_part_of_strict_parent_proof(self):
        line = MaskedLine(
            line_id='p03-l001', page=3, line=1,
            text_masked='일반암진단비 3,000만원',
        )
        invalid_counts = (-1, True, 0, 1, 3, 4)

        for image_only_page_count in invalid_counts:
            result = ExtractedPDF(
                file_sha256='a' * 64,
                file_size=123,
                page_count=3,
                masked_lines=(line,),
                candidates=(),
                pseudonymization_counts=(),
                residual_scan_passed=True,
                image_only_page_count=image_only_page_count,
                image_only_pages=(1, 2),
            )
            with self.subTest(image_only_page_count=image_only_page_count):
                with self.assertRaises(PDFImportError) as caught:
                    _decode_child(
                        subprocess.CompletedProcess(
                            ['child'], 0, stdout=encode_success(result)),
                        expected_sha256='a' * 64,
                        expected_size=123,
                    )
                self.assertEqual(caught.exception.code, 'PDF_PARSE_FAILED')

        valid = ExtractedPDF(
            file_sha256='a' * 64,
            file_size=123,
            page_count=3,
            masked_lines=(line,),
            candidates=(),
            pseudonymization_counts=(),
            residual_scan_passed=True,
            image_only_page_count=2,
            image_only_pages=(1, 2),
        )
        decoded = _decode_child(
            subprocess.CompletedProcess(
                ['child'], 0, stdout=encode_success(valid)),
            expected_sha256='a' * 64,
            expected_size=123,
        )
        self.assertEqual(decoded.image_only_page_count, 2)
        self.assertEqual(decoded.image_only_pages, (1, 2))

        invalid_pages = (
            (),
            (1,),
            (1, 1),
            (2, 1),
            (0, 1),
            (1, 4),
            (True, 2),
            (1, 3),
        )
        for image_only_pages in invalid_pages:
            tampered = ExtractedPDF(
                file_sha256='a' * 64,
                file_size=123,
                page_count=3,
                masked_lines=(line,),
                candidates=(),
                pseudonymization_counts=(),
                residual_scan_passed=True,
                image_only_page_count=2,
                image_only_pages=image_only_pages,
            )
            with self.subTest(image_only_pages=image_only_pages), \
                    self.assertRaises(PDFImportError) as caught:
                _decode_child(
                    subprocess.CompletedProcess(
                        ['child'], 0, stdout=encode_success(tampered)),
                    expected_sha256='a' * 64,
                    expected_size=123,
                )
            self.assertEqual(caught.exception.code, 'PDF_PARSE_FAILED')

    def test_parent_rejects_unproved_blank_page_after_quarantine(self):
        line = MaskedLine(
            line_id='p02-l003', page=2, line=3,
            text_masked='일반암진단비 3,000만원',
        )
        result = ExtractedPDF(
            file_sha256='a' * 64,
            file_size=123,
            page_count=2,
            masked_lines=(line,),
            candidates=(),
            pseudonymization_counts=(),
            residual_scan_passed=True,
            image_only_page_count=0,
            image_only_pages=(),
            quarantined_line_count=1,
            quarantined_line_ids=('p01-l001',),
        )

        with self.assertRaises(PDFImportError) as caught:
            _decode_child(
                subprocess.CompletedProcess(
                    ['child'], 0, stdout=encode_success(result)),
                expected_sha256='a' * 64,
                expected_size=123,
            )

        self.assertEqual(caught.exception.code, 'PDF_PARSE_FAILED')

    def test_only_masked_lines_and_candidates_leave_extractor(self):
        raw_name = '홍길동'
        page = f'계약자 성명 {raw_name}\n일반암진단비 3,000만원'
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF([page])):
            result = extract_pdf(_upload())

        serialized = json.dumps(asdict(result), ensure_ascii=False)
        self.assertNotIn(raw_name, serialized)
        self.assertIn('계약자 성명 [고객_1]', serialized)
        self.assertFalse(hasattr(result, 'raw_text'))
        self.assertFalse(hasattr(result.masked_lines[0], 'text'))
        self.assertTrue(result.residual_scan_passed)
        self.assertEqual(result.pseudonymization_counts,
                         (('customer_name', 1),))
        self.assertFalse(hasattr(result, 'source_map'))

    def test_parent_accepts_only_safe_pseudonymization_proof(self):
        sentinels = ('TEST-CONTRACT-24680', '테스트고객')
        page = (
            f'계약번호: {sentinels[0]}\n'
            f'계약자 성명: {sentinels[1]}\n'
            '뇌혈관질환진단비 1,000만원 20년납 100세만기'
        )
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF([page])):
            result = extract_pdf(_upload())

        serialized = json.dumps(asdict(result), ensure_ascii=False)
        for sentinel in sentinels:
            self.assertNotIn(sentinel, serialized)
        self.assertTrue(result.residual_scan_passed)
        self.assertIn(('contract_id', 1), result.pseudonymization_counts)
        self.assertIn(('customer_name', 1), result.pseudonymization_counts)

    def test_parent_rescans_child_text_even_when_proof_claims_success(self):
        sentinel = 'TEST-UNMASKED-86420'
        unsafe_result = ExtractedPDF(
            file_sha256='a' * 64,
            file_size=123,
            page_count=1,
            masked_lines=(MaskedLine(
                line_id='p01-l001',
                page=1,
                line=1,
                text_masked=f'계약번호: {sentinel}',
            ),),
            candidates=(),
            pseudonymization_counts=(),
            residual_scan_passed=True,
        )
        completed = subprocess.CompletedProcess(
            ['child'], 0, stdout=encode_success(unsafe_result))

        with self.assertRaises(PDFImportError) as caught:
            _decode_child(
                completed,
                expected_sha256='a' * 64,
                expected_size=123,
            )

        self.assertEqual(caught.exception.code, 'PII_REDACTION_UNCERTAIN')
        self.assertNotIn(sentinel, str(caught.exception))

    def test_parent_requires_exact_emitted_alias_occurrence_counts(self):
        line = '계약자 성명: [고객_1] / [고객_1]'
        valid = ExtractedPDF(
            file_sha256='a' * 64,
            file_size=123,
            page_count=1,
            masked_lines=(MaskedLine(
                line_id='p01-l001', page=1, line=1, text_masked=line,
            ),),
            candidates=(),
            pseudonymization_counts=(('customer_name', 2),),
            residual_scan_passed=True,
        )

        decoded = _decode_child(
            subprocess.CompletedProcess(
                ['child'], 0, stdout=encode_success(valid)),
            expected_sha256='a' * 64,
            expected_size=123,
        )

        self.assertEqual(decoded.pseudonymization_counts,
                         (('customer_name', 2),))

    def test_parent_rejects_invalid_alias_count_proofs(self):
        line = '계약자 성명: [고객_1] / [고객_1]'
        invalid_counts = (
            (),
            (('customer_name', 1),),
            (('customer_name', 3),),
            (('customer_name', 0),),
            (('customer_name', True),),
            (('customer_name', settings.INSURANCE_MAX_EXTRACTED_CHARS + 1),),
            (('customer_name', 1), ('customer_name', 1)),
            (('planner_name', 2),),
        )

        for counts in invalid_counts:
            result = ExtractedPDF(
                file_sha256='a' * 64,
                file_size=123,
                page_count=1,
                masked_lines=(MaskedLine(
                    line_id='p01-l001', page=1, line=1,
                    text_masked=line,
                ),),
                candidates=(),
                pseudonymization_counts=counts,
                residual_scan_passed=True,
            )
            with self.subTest(counts=counts):
                with self.assertRaises(PDFImportError) as caught:
                    _decode_child(
                        subprocess.CompletedProcess(
                            ['child'], 0, stdout=encode_success(result)),
                        expected_sha256='a' * 64,
                        expected_size=123,
                    )
                self.assertEqual(
                    caught.exception.code, 'PDF_PARSE_FAILED')

    def test_parent_rejects_unknown_malformed_or_gapped_alias_tokens(self):
        unsafe_lines = (
            '안내 [미상_1]',
            '계약자 성명: [고객_0]',
            '계약자 성명: [고객_x]',
            '계약자 성명: [고객_1',
            '계약자 성명: [고객_2]',
            '안내 [고객_' + ('9' * 5_000) + ']',
        )

        for line in unsafe_lines:
            result = ExtractedPDF(
                file_sha256='a' * 64,
                file_size=123,
                page_count=1,
                masked_lines=(MaskedLine(
                    line_id='p01-l001', page=1, line=1,
                    text_masked=line,
                ),),
                candidates=(),
                pseudonymization_counts=(('customer_name', 1),),
                residual_scan_passed=True,
            )
            with self.subTest(line=line):
                with self.assertRaises(PDFImportError) as caught:
                    _decode_child(
                        subprocess.CompletedProcess(
                            ['child'], 0, stdout=encode_success(result)),
                        expected_sha256='a' * 64,
                        expected_size=123,
                    )
                self.assertEqual(
                    caught.exception.code, 'PDF_PARSE_FAILED')

    def test_name_is_masked_after_more_than_four_blank_lines(self):
        raw_name = '김민감'
        page = f'계약자 성명\n\n\n\n\n\n{raw_name}'
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF([page])):
            result = extract_pdf(_upload())

        serialized = json.dumps(asdict(result), ensure_ascii=False)
        self.assertNotIn(raw_name, serialized)
        self.assertIn('[고객_1]', serialized)

    def test_line_over_16384_characters_passes_under_document_limit(self):
        raw_phone = '010-1234-5678'
        long_line = (raw_phone + ' ' + ('보험' * 9000))[:16_385]
        self.assertEqual(len(long_line), 16_385)
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF([long_line])):
            result = extract_pdf(_upload())

        self.assertEqual(len(result.masked_lines), 1)
        self.assertGreater(len(result.masked_lines[0].text_masked), 16_000)
        self.assertNotIn(raw_phone, result.masked_lines[0].text_masked)

    def test_all_identity_sentinels_are_masked_across_page_boundary(self):
        raw_name = '박경계'
        raw_phone = '010-9876-5432'
        raw_rrn = '901231-1234567'
        pages = (
            '피보험자 성명\n\n\n\n\n',
            f'{raw_name}\n일반암진단비 3,000만원 {raw_phone} {raw_rrn}',
        )
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF(pages)):
            result = extract_pdf(_upload())

        serialized = json.dumps(asdict(result), ensure_ascii=False)
        for sentinel in (raw_name, raw_phone, raw_rrn):
            self.assertNotIn(sentinel, serialized)
        self.assertEqual(len(result.candidates), 1)
        for sentinel in (raw_phone, raw_rrn):
            self.assertNotIn(sentinel, result.candidates[0].text_masked)

    def test_header_candidate_is_preserved_as_needs_review(self):
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF(['담보명 가입금액'])):
            result = extract_pdf(_upload())

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].review_status, 'needs_review')
        self.assertEqual(result.candidates[0].evidence_line_ids, ('p01-l001',))

    def test_amount_period_and_coverage_header_candidates_are_all_preserved(self):
        page = '\n'.join((
            '월보험료 100,000원',
            '20년납입 100세만기',
            '담보명 가입금액',
        ))
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF([page])):
            result = extract_pdf(_upload())

        self.assertEqual(
            [item.evidence_line_ids for item in result.candidates],
            [('p01-l001',), ('p01-l002',), ('p01-l003',)],
        )

    def test_hash_and_size_are_computed_from_stream(self):
        body = b'%PDF-1.7\nstreamed body'
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                return_value=_PDF(['일반암진단비 3,000만원'])):
            result = extract_pdf(_upload(body))

        self.assertEqual(result.file_sha256, hashlib.sha256(body).hexdigest())
        self.assertEqual(result.file_size, len(body))

    def test_file_larger_than_50mb_is_rejected_before_pdf_open(self):
        with tempfile.TemporaryFile() as upload:
            upload.write(b'%PDF-')
            upload.truncate(MAX_FILE_BYTES + 1)
            upload.seek(0)
            with mock.patch(
                    'inpa.insurances.import_pdf_sandbox._open_pdf') as open_pdf, \
                    self.assertRaises(PDFImportError) as caught:
                extract_pdf(upload)

        self.assertEqual(caught.exception.code, 'FILE_TOO_LARGE')
        open_pdf.assert_not_called()
