import hashlib
import io
import json
import os
import stat
import subprocess
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from .import_contract import PDFImportError
from .import_pdf import extract_pdf


def _upload(body=b'%PDF-1.7\nbody', *, name='customer-hong-policy.pdf'):
    upload = io.BytesIO(body)
    upload.name = name
    return upload


def _success_protocol(body, *, text='일반암진단비 3,000만원'):
    return json.dumps({
        'protocol_version': 1,
        'ok': True,
        'result': {
            'file_sha256': hashlib.sha256(body).hexdigest(),
            'file_size': len(body),
            'page_count': 1,
            'image_only_page_count': 0,
            'image_only_pages': [],
            'masked_lines': [{
                'line_id': 'p01-l001',
                'page': 1,
                'line': 1,
                'text_masked': text,
            }],
            'candidates': [{
                'candidate_id': 'c00001',
                'evidence_line_ids': ['p01-l001'],
                'text_masked': text,
                'review_status': 'needs_review',
            }],
            'pseudonymization_counts': [],
            'residual_scan_passed': True,
            'quarantined_line_count': 0,
            'quarantined_line_ids': [],
            'analysis_signal_quarantined_line_count': 0,
            'analysis_signal_quarantined_line_ids': [],
        },
    }, ensure_ascii=False).encode()


class PDFSandboxParentBoundaryTests(SimpleTestCase):
    def test_random_0600_temp_file_is_used_and_always_deleted(self):
        body = b'%PDF-1.7\nprivate source'
        observed = {}

        def complete(command, **kwargs):
            source_path = command[command.index('--source-path') + 1]
            observed['path'] = source_path
            observed['mode'] = stat.S_IMODE(os.stat(source_path).st_mode)
            observed['body'] = Path(source_path).read_bytes()
            observed['command'] = command
            observed['kwargs'] = kwargs
            return subprocess.CompletedProcess(
                command, 0, stdout=_success_protocol(body))

        with mock.patch(
                'inpa.insurances.import_pdf.subprocess.run',
                side_effect=complete):
            result = extract_pdf(_upload(body))

        self.assertEqual(observed['mode'], 0o600)
        self.assertEqual(observed['body'], body)
        self.assertFalse(os.path.exists(observed['path']))
        self.assertNotIn('customer-hong-policy', observed['path'])
        self.assertIn('--child', observed['command'])
        self.assertIs(observed['kwargs']['stderr'], subprocess.DEVNULL)
        self.assertNotIn('ANTHROPIC_API_KEY', observed['kwargs']['env'])
        self.assertEqual(result.file_sha256, hashlib.sha256(body).hexdigest())

    def test_timeout_is_safe_and_temp_file_is_deleted(self):
        observed = {}

        def timeout(command, **_kwargs):
            observed['path'] = command[command.index('--source-path') + 1]
            raise subprocess.TimeoutExpired(
                command, 90, output=b'', stderr=b'raw Hong Gil Dong')

        with mock.patch(
                'inpa.insurances.import_pdf.subprocess.run',
                side_effect=timeout), self.assertRaises(
                    PDFImportError) as caught:
            extract_pdf(_upload())

        self.assertEqual(caught.exception.code, 'PDF_PARSE_TIMEOUT')
        self.assertNotIn('Hong', str(caught.exception))
        self.assertFalse(os.path.exists(observed['path']))

    def test_kill_and_nonzero_exit_codes_map_to_stable_safe_errors(self):
        cases = ((-9, 'PDF_PARSE_RESOURCE_LIMIT'),
                 (137, 'PDF_PARSE_RESOURCE_LIMIT'),
                 (7, 'PDF_PARSE_FAILED'))

        for return_code, expected in cases:
            completed = subprocess.CompletedProcess(
                ['child'], return_code, stdout=b'raw Hong Gil Dong')
            with self.subTest(return_code=return_code), mock.patch(
                    'inpa.insurances.import_pdf.subprocess.run',
                    return_value=completed), self.assertRaises(
                        PDFImportError) as caught:
                extract_pdf(_upload())

            self.assertEqual(caught.exception.code, expected)
            self.assertNotIn('Hong', str(caught.exception))

    def test_safe_child_domain_error_is_preserved(self):
        protocol = json.dumps({
            'protocol_version': 1,
            'ok': False,
            'error': 'ENCRYPTED_PDF',
        }).encode()
        completed = subprocess.CompletedProcess(
            ['child'], 2, stdout=protocol)

        with mock.patch(
                'inpa.insurances.import_pdf.subprocess.run',
                return_value=completed), self.assertRaises(
                    PDFImportError) as caught:
            extract_pdf(_upload())

        self.assertEqual(caught.exception.code, 'ENCRYPTED_PDF')

    def test_success_protocol_with_raw_extra_field_fails_closed(self):
        body = b'%PDF-1.7\nbody'
        payload = json.loads(_success_protocol(body))
        payload['result']['raw_text'] = 'raw Hong Gil Dong'
        completed = subprocess.CompletedProcess(
            ['child'], 0, stdout=json.dumps(payload).encode())

        with mock.patch(
                'inpa.insurances.import_pdf.subprocess.run',
                return_value=completed), self.assertRaises(
                    PDFImportError) as caught:
            extract_pdf(_upload(body))

        self.assertEqual(caught.exception.code, 'PDF_PARSE_FAILED')
        self.assertNotIn('Hong', str(caught.exception))

    def test_success_protocol_without_pseudonymization_proof_fails_closed(self):
        body = b'%PDF-1.7\nbody'
        payload = json.loads(_success_protocol(body))
        payload['result'].pop('pseudonymization_counts')
        payload['result'].pop('residual_scan_passed')
        completed = subprocess.CompletedProcess(
            ['child'], 0, stdout=json.dumps(payload).encode())

        with mock.patch(
                'inpa.insurances.import_pdf.subprocess.run',
                return_value=completed), self.assertRaises(
                    PDFImportError) as caught:
            extract_pdf(_upload(body))

        self.assertEqual(caught.exception.code, 'PDF_PARSE_FAILED')

    def test_success_protocol_without_quarantine_proof_fails_closed(self):
        body = b'%PDF-1.7\nbody'
        payload = json.loads(_success_protocol(body))
        payload['result'].pop('quarantined_line_count')
        completed = subprocess.CompletedProcess(
            ['child'], 0, stdout=json.dumps(payload).encode())

        with mock.patch(
                'inpa.insurances.import_pdf.subprocess.run',
                return_value=completed), self.assertRaises(
                    PDFImportError) as caught:
            extract_pdf(_upload(body))

        self.assertEqual(caught.exception.code, 'PDF_PARSE_FAILED')

    def test_success_protocol_rejects_invalid_quarantine_counts(self):
        body = b'%PDF-1.7\nbody'
        invalid_counts = (
            True,
            -1,
            settings.INSURANCE_MAX_EXTRACTED_CHARS + 1,
        )

        for count in invalid_counts:
            payload = json.loads(_success_protocol(body))
            payload['result']['quarantined_line_count'] = count
            completed = subprocess.CompletedProcess(
                ['child'], 0, stdout=json.dumps(payload).encode())

            with self.subTest(count=count), mock.patch(
                    'inpa.insurances.import_pdf.subprocess.run',
                    return_value=completed), self.assertRaises(
                        PDFImportError) as caught:
                extract_pdf(_upload(body))

            self.assertEqual(caught.exception.code, 'PDF_PARSE_FAILED')

    def test_success_protocol_rejects_invalid_quarantine_coordinates(self):
        body = b'%PDF-1.7\nbody'
        invalid_proofs = (
            (1, [], 0, []),
            (1, ['p01-l001'], 0, []),
            (1, ['p02-l001'], 0, []),
            (2, ['p01-l003', 'p01-l002'], 0, []),
            (1, ['p01-l002'], 1, ['p01-l003']),
            (1, ['p01-l001'], 1, ['p01-l001']),
        )

        for total, line_ids, analysis_total, analysis_line_ids in invalid_proofs:
            payload = json.loads(_success_protocol(body))
            payload['result'].update({
                'quarantined_line_count': total,
                'quarantined_line_ids': line_ids,
                'analysis_signal_quarantined_line_count': analysis_total,
                'analysis_signal_quarantined_line_ids': analysis_line_ids,
            })
            completed = subprocess.CompletedProcess(
                ['child'], 0, stdout=json.dumps(payload).encode())

            with self.subTest(line_ids=line_ids), mock.patch(
                    'inpa.insurances.import_pdf.subprocess.run',
                    return_value=completed), self.assertRaises(
                        PDFImportError) as caught:
                extract_pdf(_upload(body))

            self.assertEqual(caught.exception.code, 'PDF_PARSE_FAILED')

    def test_success_protocol_without_image_page_count_fails_closed(self):
        body = b'%PDF-1.7\nbody'
        payload = json.loads(_success_protocol(body))
        payload['result'].pop('image_only_page_count')
        completed = subprocess.CompletedProcess(
            ['child'], 0, stdout=json.dumps(payload).encode())

        with mock.patch(
                'inpa.insurances.import_pdf.subprocess.run',
                return_value=completed), self.assertRaises(
                    PDFImportError) as caught:
            extract_pdf(_upload(body))

        self.assertEqual(caught.exception.code, 'PDF_PARSE_FAILED')

    def test_success_protocol_without_exact_image_page_list_fails_closed(self):
        body = b'%PDF-1.7\nbody'
        payload = json.loads(_success_protocol(body))
        payload['result'].pop('image_only_pages')
        completed = subprocess.CompletedProcess(
            ['child'], 0, stdout=json.dumps(payload).encode())

        with mock.patch(
                'inpa.insurances.import_pdf.subprocess.run',
                return_value=completed), self.assertRaises(
                    PDFImportError) as caught:
            extract_pdf(_upload(body))

        self.assertEqual(caught.exception.code, 'PDF_PARSE_FAILED')

    def test_limits_are_passed_to_child_from_finite_settings(self):
        body = b'%PDF-1.7\nbody'
        observed = {}

        def complete(command, **kwargs):
            observed['command'] = command
            observed['timeout'] = kwargs['timeout']
            return subprocess.CompletedProcess(
                command, 0, stdout=_success_protocol(body))

        with mock.patch(
                'inpa.insurances.import_pdf.subprocess.run',
                side_effect=complete):
            extract_pdf(_upload(body))

        command = observed['command']
        self.assertEqual(observed['timeout'], 90)
        self.assertEqual(
            command[command.index('--cpu-seconds') + 1], '60')
        self.assertEqual(
            command[command.index('--memory-bytes') + 1],
            str(384 * 1024 * 1024),
        )
        self.assertEqual(settings.INSURANCE_PDF_SANDBOX_WALL_SECONDS, 90)
