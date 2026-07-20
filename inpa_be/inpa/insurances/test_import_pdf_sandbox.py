import json
import resource
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from .import_contract import PDFImportError
from .import_pdf_sandbox import (
    _execute_child,
    apply_process_limits,
    encode_success,
    parse_pdf_path,
)


class _Page:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class _Document:
    encryption = None


class _PDF:
    def __init__(self, page_texts, *, encryption=None):
        self.pages = [_Page(text) for text in page_texts]
        self.doc = _Document()
        self.doc.encryption = encryption

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _parse(page_texts, **overrides):
    limits = {
        'max_pages': 300,
        'max_chars': 500_000,
        'max_candidates': 2_000,
    }
    limits.update(overrides)
    with mock.patch(
            'inpa.insurances.import_pdf_sandbox._open_pdf',
            return_value=_PDF(page_texts)):
        return parse_pdf_path(
            '/private/tmp/random-source.pdf',
            file_sha256='a' * 64,
            file_size=123,
            **limits,
        )


class PDFSandboxChildTests(SimpleTestCase):
    def test_partial_resident_id_is_absent_from_line_and_candidate_contracts(self):
        raw_rrn = '901231-1******'
        result = _parse((
            f'일반암진단비 3,000만원 주민번호 {raw_rrn}',
        ))
        protocol = encode_success(result)

        self.assertNotIn(raw_rrn.encode(), protocol)
        self.assertNotIn(b'901231', protocol)
        self.assertNotIn(b'1******', protocol)
        self.assertIn('[주민번호_1]', result.masked_lines[0].text_masked)
        self.assertIn('[주민번호_1]', result.candidates[0].text_masked)

    def test_unicode_dash_resident_id_is_absent_from_candidate_contract(self):
        sentinels = ('901231–1******', '901231 – 1******', '901231－1******')
        result = _parse((
            f'일반암진단비 3,000만원 주민번호 {" / ".join(sentinels)}',
        ))
        protocol = encode_success(result)

        for sentinel in sentinels:
            self.assertNotIn(sentinel.encode(), protocol)
        self.assertNotIn(b'901231', protocol)
        self.assertEqual(
            result.candidates[0].text_masked.count('[주민번호_1]'), 3)

    def test_parse_memory_error_escapes_for_resource_mapping(self):
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox._open_pdf',
                side_effect=MemoryError), self.assertRaises(MemoryError):
            parse_pdf_path(
                '/private/tmp/random-source.pdf',
                file_sha256='a' * 64,
                file_size=123,
                max_pages=300,
                max_chars=500_000,
                max_candidates=2_000,
            )

    def test_child_maps_parser_memory_error_to_resource_limit(self):
        args = SimpleNamespace(
            source_path='/private/tmp/random-source.pdf',
            file_sha256='a' * 64,
            file_size=123,
            max_pages=300,
            max_chars=500_000,
            max_candidates=2_000,
            cpu_seconds=60,
            memory_bytes=384 * 1024 * 1024,
        )
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox.apply_process_limits'), \
                mock.patch(
                    'inpa.insurances.import_pdf_sandbox._open_pdf',
                    side_effect=MemoryError):
            return_code, protocol = _execute_child(args)

        self.assertEqual(return_code, 3)
        self.assertEqual(
            json.loads(protocol)['error'], 'PDF_PARSE_RESOURCE_LIMIT')

    def test_child_applies_limits_before_pdf_parser_is_called(self):
        events = []
        result = _parse(('일반암진단비 3,000만원',))
        args = SimpleNamespace(
            source_path='/private/tmp/random-source.pdf',
            file_sha256='a' * 64,
            file_size=123,
            max_pages=300,
            max_chars=500_000,
            max_candidates=2_000,
            cpu_seconds=60,
            memory_bytes=384 * 1024 * 1024,
        )

        with mock.patch(
                'inpa.insurances.import_pdf_sandbox.apply_process_limits',
                side_effect=lambda **_kwargs: events.append('limits')), \
                mock.patch(
                    'inpa.insurances.import_pdf_sandbox.parse_pdf_path',
                    side_effect=lambda *_args, **_kwargs: (
                        events.append('parse') or result)):
            return_code, protocol = _execute_child(args)

        self.assertEqual(events, ['limits', 'parse'])
        self.assertEqual(return_code, 0)
        self.assertTrue(json.loads(protocol)['ok'])

    def test_child_contract_contains_masked_values_only(self):
        raw_name = '홍길동'
        raw_phone = '010-1234-5678'
        result = _parse((
            f'계약자 성명 {raw_name}\n'
            f'일반암진단비 3,000만원 {raw_phone}',
        ))

        protocol = encode_success(result)
        decoded = json.loads(protocol)

        self.assertNotIn(raw_name.encode(), protocol)
        self.assertNotIn(raw_phone.encode(), protocol)
        self.assertTrue(decoded['ok'])
        self.assertEqual(decoded['protocol_version'], 1)
        self.assertEqual(
            decoded['result']['candidates'][0]['review_status'],
            'needs_review',
        )
        self.assertTrue(decoded['result']['residual_scan_passed'])
        self.assertEqual(
            decoded['result']['pseudonymization_counts'],
            [['customer_name', 1], ['phone', 1]],
        )
        self.assertNotIn('source_map', decoded['result'])

    def test_child_contract_pseudonymizes_policy_and_planner_identifiers(self):
        sentinels = (
            'TEST-POLICY-22222',
            'TEST-PLANNER-33333',
            '테스트담당자',
        )
        result = _parse((
            f'증권번호: {sentinels[0]}\n'
            f'모집자: {sentinels[2]} '
            f'(고유번호: {sentinels[1]})\n'
            '유사암진단비(갱신형) 300만원 20년납 100세만기',
        ))
        protocol = encode_success(result)

        for sentinel in sentinels:
            self.assertNotIn(sentinel.encode(), protocol)
        self.assertIn('[증권번호_1]'.encode(), protocol)
        self.assertIn('[설계사_1]'.encode(), protocol)
        self.assertIn('[등록번호_1]'.encode(), protocol)
        self.assertTrue(result.residual_scan_passed)

    def test_identity_only_lines_are_quarantined_without_losing_coordinates(self):
        private_value = 'PRIVATE-VALUE-24680'
        result = _parse((
            f'보험계약자\n{private_value}\n일반암진단비 3,000만원',
        ))

        protocol = encode_success(result)

        self.assertNotIn(private_value.encode(), protocol)
        self.assertEqual(result.quarantined_line_count, 2)
        self.assertEqual(
            [(line.line_id, line.line) for line in result.masked_lines],
            [('p01-l003', 3)],
        )
        self.assertEqual(
            result.candidates[0].evidence_line_ids,
            ('p01-l003',),
        )

    def test_identity_and_analysis_on_same_line_fails_whole_document(self):
        private_value = '테스트고객'
        result = _parse((
            f'보험계약자 {private_value} 일반암진단비 3,000만원\n'
            '유사암진단비 1,000만원',
        ))

        protocol = encode_success(result)
        self.assertNotIn(private_value.encode(), protocol)
        self.assertEqual(result.quarantined_line_ids, ('p01-l001',))
        self.assertEqual(
            result.analysis_signal_quarantined_line_ids,
            ('p01-l001',),
        )
        self.assertEqual(
            result.candidates[0].evidence_line_ids,
            ('p01-l002',),
        )

    def test_quarantine_cannot_erase_every_text_line_on_a_page(self):
        with self.assertRaises(PDFImportError) as caught:
            _parse(('보험계약자 테스트고객 일반암진단비 3,000만원',))

        self.assertEqual(caught.exception.code, 'PII_REDACTION_UNCERTAIN')

    def test_role_insurance_golden_lines_keep_text_and_candidates(self):
        lines = (
            '피보험자 연령 기준 15세 이상 가입금액 100만원',
            '피보험자 직업급수 1급 가입금액 200만원',
            '계약자 배당금 지급 안내 가입금액 300만원',
            '계약자 권리 안내 가입금액 400만원',
            '피보험자 조건 안내 가입금액 500만원',
        )

        result = _parse(('\n'.join(lines),))

        self.assertEqual(
            tuple(line.text_masked for line in result.masked_lines),
            lines,
        )
        self.assertEqual(
            tuple(candidate.text_masked for candidate in result.candidates),
            lines,
        )

    def test_limits_fail_whole_document_without_truncation(self):
        pages = tuple('일반암진단비 100만원' for _ in range(301))
        with self.assertRaises(PDFImportError) as caught:
            _parse(pages)
        self.assertEqual(caught.exception.code, 'TOO_MANY_PAGES')

        too_many = '\n'.join(
            f'{number} 일반암진단비 100만원' for number in range(2_001))
        with self.assertRaises(PDFImportError) as caught:
            _parse((too_many,))
        self.assertEqual(caught.exception.code, 'TOO_MANY_CANDIDATES')

    def test_mixed_pdf_keeps_original_coordinates_and_counts_empty_pages(self):
        pages = (
            '',
            ' \n\t',
            '안내 첫 줄\n\n일반암진단비 3,000만원',
            '',
            '상해수술비 100만원',
            '',
        )

        result = _parse(pages)

        self.assertEqual(result.page_count, 6)
        self.assertEqual(result.image_only_page_count, 4)
        self.assertEqual(result.image_only_pages, (1, 2, 4, 6))
        self.assertEqual(
            [(line.line_id, line.page, line.line)
             for line in result.masked_lines],
            [
                ('p03-l001', 3, 1),
                ('p03-l003', 3, 3),
                ('p05-l001', 5, 1),
            ],
        )
        self.assertEqual(
            [candidate.evidence_line_ids for candidate in result.candidates],
            [('p03-l003',), ('p05-l001',)],
        )

    def test_real_sample_shape_two_image_covers_then_eight_text_pages(self):
        pages = ('', '') + tuple(
            f'{number}쪽 보장명 일반암진단비 가입금액 {number}00만원'
            for number in range(3, 11)
        )

        result = _parse(pages)

        self.assertEqual(result.page_count, 10)
        self.assertEqual(result.image_only_page_count, 2)
        self.assertEqual(result.image_only_pages, (1, 2))
        self.assertEqual(result.masked_lines[0].line_id, 'p03-l001')
        self.assertEqual(result.masked_lines[-1].line_id, 'p10-l001')
        self.assertEqual(len(result.candidates), 8)

    def test_all_image_only_pages_fail_closed(self):
        with self.assertRaises(PDFImportError) as caught:
            _parse(('', ' \n\t', None))

        self.assertEqual(caught.exception.code, 'IMAGE_PDF')

    def test_linux_limit_hook_sets_hard_cpu_and_address_space_limits(self):
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox.sys.platform', 'linux'), \
                mock.patch('resource.setrlimit') as set_limit:
            supported = apply_process_limits(
                cpu_seconds=60, memory_bytes=384 * 1024 * 1024)

        self.assertTrue(supported)
        self.assertEqual(set_limit.call_args_list, [
            mock.call(resource.RLIMIT_CPU, (60, 60)),
            mock.call(
                resource.RLIMIT_AS,
                (384 * 1024 * 1024, 384 * 1024 * 1024),
            ),
        ])

    def test_non_linux_limit_hook_reports_unsupported_without_soft_claim(self):
        with mock.patch(
                'inpa.insurances.import_pdf_sandbox.sys.platform', 'darwin'), \
                mock.patch('resource.setrlimit') as set_limit:
            supported = apply_process_limits(
                cpu_seconds=60, memory_bytes=384 * 1024 * 1024)

        self.assertFalse(supported)
        set_limit.assert_not_called()
