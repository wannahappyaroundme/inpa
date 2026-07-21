import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
import uuid
from pathlib import Path
from unittest import mock

from scripts.load import insurance_import_concurrency as load


class FakeTransport:
    """In-memory staging contract. Secrets are accepted only at this edge."""

    def __init__(self, scenario, auth, *, incomplete=False, analysis_offset=0,
                 analysis_error=False, coalesced_add=False):
        self.calls = []
        self.incomplete = incomplete
        self.analysis_offset = analysis_offset
        self.analysis_error = analysis_error
        self.coalesced_add = coalesced_add
        self.token_owner = {token: owner for owner, token in auth['tokens'].items()}
        self.customer_owner = {
            owner['customer_id']: owner['owner_ref'] for owner in scenario['owners']
        }
        self.prepared = {
            item['job_id']: json.loads(json.dumps(item))
            for item in scenario['prepared_jobs']
        }
        self.created = {}
        self.replace_calls = 0

    def request(self, method, url, *, token, headers=None, json_body=None,
                file_path=None, form_fields=None, timeout=30):
        self.calls.append({
            'method': method,
            'url': url,
            'token': token,
            'headers': dict(headers or {}),
            'json_body': json_body,
            'file_path': file_path,
            'form_fields': form_fields,
            'timeout': timeout,
        })
        owner = self.token_owner[token]
        path = url.split('/api/v1/', 1)[1]
        if path == 'insurance-imports/config/':
            return load.HttpResponse(200, {
                'review_workflow_enabled': True,
                'accepted_input': 'digital_pdf',
            })
        if path.startswith('customers/') and path.endswith('/insurance-imports/'):
            customer_id = int(path.split('/')[1])
            if self.customer_owner[customer_id] != owner:
                return load.HttpResponse(404, {'detail': 'SECRET_RAW_DETAIL'})
            key = headers['Idempotency-Key']
            job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, key))
            self.created[job_id] = {
                'owner_ref': owner,
                'customer_id': customer_id,
                'status': 'queued',
                'poll_count': 0,
            }
            return load.HttpResponse(202, {'job_id': job_id, 'status': 'queued'})
        if path.startswith('customers/') and path.endswith('/heatmap/'):
            if self.analysis_error:
                raise load.TransportError('network')
            customer_id = int(path.split('/')[1])
            if self.customer_owner.get(customer_id, owner) != owner:
                return load.HttpResponse(404, {})
            expected = 0
            for group in SCENARIO_TEMPLATE['confirm_groups']:
                if group['analysis_customer_id'] == customer_id:
                    expected = (group['expected_analysis_total_amount']
                                + self.analysis_offset)
            return load.HttpResponse(200, {
                'tree': [{'sub_categories': [{'details': [
                    {'held_amount': expected},
                ]}]}],
            })
        if not path.startswith('insurance-imports/'):
            return load.HttpResponse(404, {})
        job_id = path.split('/')[1]
        known = self.created.get(job_id) or self.prepared.get(job_id)
        if known is None or known['owner_ref'] != owner:
            return load.HttpResponse(404, {'detail': 'SECRET_RAW_DETAIL'})
        if path.endswith('/confirm/'):
            if known.get('intent') == 'replace':
                self.replace_calls += 1
                if self.replace_calls > 1:
                    return load.HttpResponse(409, {
                        'code': 'IMPORT_TARGET_CHANGED',
                        'detail': 'SECRET_RAW_DETAIL',
                    })
            known['status'] = 'confirmed'
            insurance_id = (7001 if self.coalesced_add and known['intent'] == 'add'
                            else 7000 + int(uuid.UUID(job_id)))
            return load.HttpResponse(200, {
                'job_id': job_id,
                'status': 'confirmed',
                'insurance_id': insurance_id,
                'confirmed_coverage_count':
                    known['expected_confirmed_coverage_count'],
            })
        if path.endswith(('/draft/', '/source-url/', '/cancel/')):
            return load.HttpResponse(200, {})
        created = self.created.get(job_id)
        if created:
            created['poll_count'] += 1
            if not self.incomplete:
                if created['poll_count'] >= 3:
                    created['status'] = 'review_required'
                elif created['poll_count'] >= 2:
                    created['status'] = 'extracting'
            owner_number = int(created['owner_ref'].split('-')[-1])
            return load.HttpResponse(200, {
                'job_id': job_id,
                'customer_id': created['customer_id'],
                'status': created['status'],
                'intent': 'add',
                'draft_version': 1,
                'target_insurance_id': None,
                'target_insurance_version': None,
                'created_at': '2026-07-17T00:00:00Z',
                'started_at': (f'2026-07-17T00:00:{owner_number:02d}Z'
                               if created['poll_count'] >= 2 and not self.incomplete
                               else None),
                'completed_at': (f'2026-07-17T00:00:{owner_number + 30:02d}Z'
                                 if created['poll_count'] >= 3 and not self.incomplete
                                 else None),
            })
        return load.HttpResponse(200, {
            'job_id': job_id,
            'customer_id': known['customer_id'],
            'status': known['status'],
            'intent': known['intent'],
            'draft_version': 1,
            'target_insurance_id': 900 if known['intent'] == 'replace' else None,
            'target_insurance_version': 1 if known['intent'] == 'replace' else None,
            'created_at': '2026-07-17T00:00:00Z',
            'started_at': '2026-07-17T00:00:01Z',
            'completed_at': None,
            'confirmed_coverage_count':
                known['expected_confirmed_coverage_count'],
        })


def _scenario_template():
    owners = []
    prepared_jobs = []
    for index in range(1, 21):
        owner_ref = f'owner-{index:02d}'
        owners.append({
            'owner_ref': owner_ref,
            'customer_id': 1000 + index,
            'documents': [
                {
                    'case_id': f'o{index:02d}-d1',
                    'file_path': 'PDF_SHARED',
                    'hash_group': 'shared-a',
                    'intent': 'add',
                    'portfolio_type': 1,
                },
                {
                    'case_id': f'o{index:02d}-d2',
                    'file_path': 'PDF_B',
                    'hash_group': f'o{index:02d}-b',
                    'intent': 'add',
                    'portfolio_type': 1,
                },
                {
                    'case_id': f'o{index:02d}-d3',
                    'file_path': 'PDF_C',
                    'hash_group': f'o{index:02d}-c',
                    'intent': 'add',
                    'portfolio_type': 1,
                },
            ],
        })
    specs = (
        ('prepared-add-a', 'add', 1001),
        ('prepared-add-b', 'add', 1001),
        ('prepared-replace-a', 'replace', 1002),
        ('prepared-replace-b', 'replace', 1002),
    )
    for offset, (job_ref, intent, customer_id) in enumerate(specs, 1):
        prepared_jobs.append({
            'job_ref': job_ref,
            'job_id': str(uuid.UUID(int=offset)),
            'owner_ref': 'owner-01' if intent == 'add' else 'owner-02',
            'customer_id': customer_id,
            'intent': intent,
            'status': 'review_required',
            'expected_confirmed_coverage_count': offset,
        })
    return {
        'schema_version': 'insurance-import-concurrency-scenario-v2',
        'run_id': 'task15-staging-20260717-a',
        'expected_host': 'staging.example.test',
        'private_root': 'PRIVATE_ROOT',
        'polling': {
            'timeout_seconds': 45,
            'drain_timeout_seconds': 600,
            'interval_seconds': 1,
            'max_attempts': 600,
        },
        'owners': owners,
        'prepared_jobs': prepared_jobs,
        'confirm_groups': [
            {
                'group_ref': 'preserve-two-adds',
                'owner_ref': 'owner-01',
                'job_refs': ['prepared-add-a', 'prepared-add-b'],
                'expected': 'both_confirmed',
                'analysis_customer_id': 1001,
                'expected_analysis_total_amount': 30_000_000,
            },
            {
                'group_ref': 'single-replace-winner',
                'owner_ref': 'owner-02',
                'job_refs': ['prepared-replace-a', 'prepared-replace-b'],
                'target_ref': 'prepared-target-a',
                'expected': 'one_confirmed_one_target_changed',
                'analysis_customer_id': 1002,
                'expected_analysis_total_amount': 20_000_000,
            },
        ],
    }


SCENARIO_TEMPLATE = _scenario_template()


class LoadScriptContractTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name).resolve()
        self.root.chmod(0o700)
        self.scenario = json.loads(json.dumps(SCENARIO_TEMPLATE))
        self.scenario['private_root'] = str(self.root)
        pdfs = {}
        for marker in ('SHARED', 'B', 'C'):
            path = self.root / f'synthetic-{marker.lower()}.pdf'
            path.write_bytes(
                f'%PDF-1.4\n{load.SYNTHETIC_MARKER}\n'
                f'SENTINEL_DOCUMENT_TEXT_{marker}\n%%EOF'.encode())
            path.chmod(0o600)
            pdfs[f'PDF_{marker}'] = str(path)
        for owner in self.scenario['owners']:
            for document in owner['documents']:
                document['file_path'] = pdfs[document['file_path']]
        self.auth = {
            'schema_version': 'insurance-import-concurrency-auth-v1',
            'tokens': {
                f'owner-{index:02d}': f'SENTINEL_TOKEN_{index:02d}'
                for index in range(1, 21)
            },
        }
        self.scenario_path = self.root / 'scenario.json'
        self.auth_path = self.root / 'auth.json'
        self.result_path = self.root / 'result.json'
        self._write_private(self.scenario_path, self.scenario)
        self._write_private(self.auth_path, self.auth)

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _write_private(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')
        path.chmod(0o600)

    def _load_and_validate(self):
        return load.load_and_validate_inputs(self.scenario_path, self.auth_path)

    def _main_args(self, *, result=None):
        return [
            '--base-url', 'https://staging.example.test/api/v1',
            '--scenario', str(self.scenario_path),
            '--auth-file', str(self.auth_path),
            '--result', str(result or self.result_path),
            '--workers', '60',
            '--execute-staging', self.scenario['run_id'],
            '--max-intake-p95-ms', '5000',
            '--max-owner-wait-p95-ms', '8000',
        ]

    def test_schema_cardinality_private_modes_and_safe_refs(self):
        scenario, auth = self._load_and_validate()
        self.assertEqual(len(scenario['owners']), 20)
        self.assertEqual(sum(len(o['documents']) for o in scenario['owners']), 60)
        self.assertEqual(set(auth['tokens']), {
            item['owner_ref'] for item in scenario['owners']})
        self.assertEqual(len(scenario['confirm_groups']), 2)

    def test_rejects_bad_cardinality_auth_refs_permissions_and_missing_phase_b(self):
        mutations = []
        too_few = json.loads(json.dumps(self.scenario))
        too_few['owners'].pop()
        mutations.append(('cardinality', too_few, self.auth, 0o600, 0o600))
        missing_group = json.loads(json.dumps(self.scenario))
        missing_group['confirm_groups'] = []
        mutations.append(('phase_b', missing_group, self.auth, 0o600, 0o600))
        auth_extra = json.loads(json.dumps(self.auth))
        auth_extra['tokens']['owner-99'] = 'NOT_REPORTED'
        mutations.append(('auth_refs', self.scenario, auth_extra, 0o600, 0o600))
        unsafe = json.loads(json.dumps(self.scenario))
        unsafe['owners'][0]['owner_ref'] = '홍길동 전화'
        mutations.append(('safe_ref', unsafe, self.auth, 0o600, 0o600))
        mutations.append(('scenario_mode', self.scenario, self.auth, 0o644, 0o600))
        mutations.append(('auth_mode', self.scenario, self.auth, 0o600, 0o644))
        for label, scenario, auth, scenario_mode, auth_mode in mutations:
            with self.subTest(label=label):
                self._write_private(self.scenario_path, scenario)
                self._write_private(self.auth_path, auth)
                self.scenario_path.chmod(scenario_mode)
                self.auth_path.chmod(auth_mode)
                with self.assertRaises(load.PreflightError):
                    self._load_and_validate()

    def test_rejects_non_private_pdf_fixture(self):
        source = Path(self.scenario['owners'][0]['documents'][0]['file_path'])
        source.chmod(0o644)
        with self.assertRaises(load.PreflightError):
            self._load_and_validate()

    def test_rejects_symlink_relative_result_and_any_git_worktree_path(self):
        source = Path(self.scenario['owners'][0]['documents'][0]['file_path'])
        link = self.root / 'linked.pdf'
        link.symlink_to(source)
        self.scenario['owners'][0]['documents'][0]['file_path'] = str(link)
        self._write_private(self.scenario_path, self.scenario)
        with self.assertRaises(load.PreflightError):
            self._load_and_validate()

        self.scenario['owners'][0]['documents'][0]['file_path'] = str(source)
        self._write_private(self.scenario_path, self.scenario)
        transport = mock.Mock()
        args = self._main_args()
        args[args.index('--result') + 1] = 'relative-result.json'
        self.assertEqual(load.main(
            args, transport=transport, stdout=io.StringIO(),
            sleep=lambda _: None), 2)
        transport.request.assert_not_called()

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as repo_temp:
            repo_root = Path(repo_temp).resolve()
            repo_root.chmod(0o700)
            scenario = json.loads(json.dumps(self.scenario))
            scenario['private_root'] = str(repo_root)
            fixture = repo_root / 'synthetic.pdf'
            fixture.write_bytes(
                f'%PDF-1.4\n{load.SYNTHETIC_MARKER}\n%%EOF'.encode())
            fixture.chmod(0o600)
            for owner in scenario['owners']:
                for document in owner['documents']:
                    document['file_path'] = str(fixture)
            scenario_path = repo_root / 'scenario.json'
            auth_path = repo_root / 'auth.json'
            self._write_private(scenario_path, scenario)
            self._write_private(auth_path, self.auth)
            with self.assertRaises(load.PreflightError):
                load.load_and_validate_inputs(scenario_path, auth_path)

    def test_execution_confirmation_https_host_and_required_thresholds_fail_closed(self):
        scenario, _ = self._load_and_validate()
        valid = dict(
            base_url='https://staging.example.test/api/v1',
            scenario=scenario,
            execute_staging=scenario['run_id'],
            max_intake_p95_ms=5000,
            max_owner_wait_p95_ms=8000,
        )
        load.validate_execution(**valid)
        for key, value in (
            ('base_url', 'http://staging.example.test/api/v1'),
            ('base_url', 'https://other.example.test/api/v1'),
            ('execute_staging', 'wrong-run'),
            ('max_intake_p95_ms', None),
            ('max_owner_wait_p95_ms', 0),
        ):
            kwargs = dict(valid)
            kwargs[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(load.PreflightError):
                load.validate_execution(**kwargs)

    def test_drain_timeout_is_separate_from_each_poll_request_timeout(self):
        scenario, _ = self._load_and_validate()
        polling = scenario['polling']
        self.assertEqual(polling['timeout_seconds'], 45)
        self.assertEqual(polling['drain_timeout_seconds'], 600)
        self.assertGreaterEqual(
            load._drain_future_timeout_seconds(polling), 645)

        for label, value in (
                ('missing', None), ('not_longer', 45), ('too_long', 3601)):
            broken = json.loads(json.dumps(self.scenario))
            if value is None:
                broken['polling'].pop('drain_timeout_seconds')
            else:
                broken['polling']['drain_timeout_seconds'] = value
            self._write_private(self.scenario_path, broken)
            with self.subTest(label=label), self.assertRaises(load.PreflightError):
                load.load_and_validate_inputs(
                    self.scenario_path, self.auth_path)

    def test_retry_uses_stable_idempotency_and_only_retries_network_timeout_or_5xx(self):
        calls = []
        responses = [
            load.TransportError('network'),
            load.HttpResponse(503, {'detail': 'SENTINEL_RAW'}),
            load.HttpResponse(202, {'job_id': str(uuid.uuid4())}),
        ]

        def operation():
            calls.append('fixed-idempotency')
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        sleeps = []
        response = load.request_with_retry(operation, sleep=sleeps.append)
        self.assertEqual(response.status, 202)
        self.assertEqual(calls, ['fixed-idempotency'] * 3)
        self.assertEqual(sleeps, [1, 2])
        attempts = 0
        full_sleeps = []

        def exhausted():
            nonlocal attempts
            attempts += 1
            return load.HttpResponse(503, {})

        self.assertEqual(load.request_with_retry(
            exhausted, sleep=full_sleeps.append).status, 503)
        self.assertEqual(attempts, 4)
        self.assertEqual(full_sleeps, [1, 2, 4])
        for status in (400, 401, 403, 404, 409, 429):
            count = 0

            def non_retry():
                nonlocal count
                count += 1
                return load.HttpResponse(status, {})

            self.assertEqual(load.request_with_retry(
                non_retry, sleep=lambda _: None).status, status)
            self.assertEqual(count, 1)

    def test_nearest_rank_percentiles_are_stable(self):
        self.assertEqual(load.metric_summary([1, 2, 3, 4, 100]), {
            'count': 5, 'p50': 3, 'p95': 100, 'max': 100,
        })
        self.assertEqual(load.metric_summary([]), {
            'count': 0, 'p50': None, 'p95': None, 'max': None,
        })

    def test_full_run_has_expected_outcomes_private_report_and_no_secret_output(self):
        scenario, auth = self._load_and_validate()
        transport = FakeTransport(scenario, auth)
        stdout = io.StringIO()
        exit_code = load.execute_and_report(
            base_url='https://staging.example.test/api/v1',
            scenario=scenario,
            auth=auth,
            result_path=self.result_path,
            workers=60,
            execute_staging=scenario['run_id'],
            max_intake_p95_ms=60_000,
            max_owner_wait_p95_ms=60_000,
            transport=transport,
            stdout=stdout,
            sleep=lambda _: None,
        )
        self.assertEqual(exit_code, 0)
        result = json.loads(self.result_path.read_text())
        self.assertTrue(result['passed'])
        self.assertEqual(result['correctness']['accepted_202'], 60)
        self.assertEqual(result['correctness']['cross_owner_visible'], 0)
        self.assertEqual(result['correctness']['duplicate_job_excess'], 0)
        self.assertEqual(result['correctness']['duplicate_analysis_amount'], 0)
        self.assertEqual(result['correctness']['both_adds_preserved'], 1)
        self.assertEqual(result['correctness']['replace_success'], 1)
        self.assertEqual(result['correctness']['replace_target_changed_409'], 1)
        self.assertEqual(os.stat(self.result_path).st_mode & 0o777, 0o600)
        self.assertEqual(result['provider']['review_required_count'], 60)
        self.assertEqual(result['provider']['not_started_count'], 0)
        self.assertEqual(result['provider']['unfinished_count'], 0)
        self.assertEqual(result['latency_ms']['owner_queue_p95'], {
            'count': 20, 'p50': 10_000.0, 'p95': 19_000.0,
            'max': 20_000.0,
        })
        self.assertEqual(result['latency_ms']['owner_end_to_end_p95'], {
            'count': 20, 'p50': 40_000.0, 'p95': 49_000.0,
            'max': 50_000.0,
        })
        poll_requests = [
            call for call in transport.calls
            if call['method'] == 'GET' and call['timeout'] == 45
        ]
        self.assertEqual(len(poll_requests), 180)
        self.assertTrue(all(
            any(job_id in call['url'] for job_id in transport.created)
            for call in poll_requests
        ))
        self.assertTrue(all(value is False for value in result['privacy'].values()))
        serialized = self.result_path.read_text() + stdout.getvalue()
        for forbidden in (
            'SENTINEL_TOKEN', 'synthetic-shared.pdf', 'SECRET_RAW_DETAIL',
            'Authorization', '/insurance-imports/00000000-',
        ):
            self.assertNotIn(forbidden, serialized)
        for customer_id in (owner['customer_id'] for owner in scenario['owners']):
            self.assertFalse(load._identifier_in_text(
                serialized, str(customer_id)))
        for job_id in (*transport.created, *transport.prepared):
            self.assertNotIn(job_id, serialized)
        with self.assertRaises(load.PreflightError):
            load.write_private_result(self.result_path, result)

    def test_two_adds_coalesced_to_one_insurance_never_passes_preservation(self):
        scenario, auth = self._load_and_validate()
        code = load.execute_and_report(
            base_url='https://staging.example.test/api/v1',
            scenario=scenario, auth=auth, result_path=self.result_path,
            workers=60, execute_staging=scenario['run_id'],
            max_intake_p95_ms=60_000, max_owner_wait_p95_ms=60_000,
            transport=FakeTransport(scenario, auth, coalesced_add=True),
            stdout=io.StringIO(), sleep=lambda _: None,
        )
        self.assertEqual(code, 1)
        result = json.loads(self.result_path.read_text())
        self.assertEqual(result['correctness']['both_adds_preserved'], 0)

    def test_secrets_and_paths_reach_transport_but_never_report(self):
        scenario, auth = self._load_and_validate()
        transport = FakeTransport(scenario, auth)
        load.execute_and_report(
            base_url='https://staging.example.test/api/v1', scenario=scenario,
            auth=auth, result_path=self.result_path, workers=60,
            execute_staging=scenario['run_id'], max_intake_p95_ms=60_000,
            max_owner_wait_p95_ms=60_000, transport=transport,
            stdout=io.StringIO(), sleep=lambda _: None,
        )
        self.assertTrue(any(call['token'].startswith('SENTINEL_TOKEN_')
                            for call in transport.calls))
        self.assertTrue(any(call['file_path'] for call in transport.calls))
        report = self.result_path.read_text()
        self.assertNotIn('SENTINEL_TOKEN_', report)
        self.assertNotIn(str(self.root), report)

    def test_incomplete_provider_or_performance_or_correctness_returns_one(self):
        scenario, auth = self._load_and_validate()
        for label, incomplete, intake_limit in (
            ('provider', True, 60_000),
            ('performance', False, 0.000001),
        ):
            with self.subTest(label=label):
                result = self.root / f'{label}.json'
                code = load.execute_and_report(
                    base_url='https://staging.example.test/api/v1',
                    scenario=scenario, auth=auth, result_path=result,
                    workers=60, execute_staging=scenario['run_id'],
                    max_intake_p95_ms=intake_limit,
                    max_owner_wait_p95_ms=60_000,
                    transport=FakeTransport(scenario, auth, incomplete=incomplete),
                    stdout=io.StringIO(), sleep=lambda _: None,
                )
                self.assertEqual(code, 1)
                self.assertFalse(json.loads(result.read_text())['passed'])
                if label == 'provider':
                    body = json.loads(result.read_text())
                    self.assertEqual(body['provider']['not_started_count'], 60)
                    self.assertEqual(body['provider']['unfinished_count'], 60)
                    self.assertTrue(all(
                        failure['code'] == 'POLL_TIMEOUT'
                        for failure in body['failures']
                        if failure['phase'] == 'poll'))
        correctness_result = self.root / 'correctness.json'
        code = load.execute_and_report(
            base_url='https://staging.example.test/api/v1',
            scenario=scenario, auth=auth, result_path=correctness_result,
            workers=60, execute_staging=scenario['run_id'],
            max_intake_p95_ms=60_000, max_owner_wait_p95_ms=60_000,
            transport=FakeTransport(scenario, auth, analysis_offset=1),
            stdout=io.StringIO(), sleep=lambda _: None,
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(correctness_result.read_text())[
            'correctness']['duplicate_analysis_amount'], 2)

    def test_unmeasured_analysis_is_reported_and_blocks_full_pass(self):
        scenario, auth = self._load_and_validate()
        code = load.execute_and_report(
            base_url='https://staging.example.test/api/v1',
            scenario=scenario, auth=auth, result_path=self.result_path,
            workers=60, execute_staging=scenario['run_id'],
            max_intake_p95_ms=60_000, max_owner_wait_p95_ms=60_000,
            transport=FakeTransport(scenario, auth, analysis_error=True),
            stdout=io.StringIO(), sleep=lambda _: None,
        )
        self.assertEqual(code, 1)
        result = json.loads(self.result_path.read_text())
        self.assertIsNone(result['correctness']['duplicate_analysis_amount'])
        self.assertFalse(result['passed'])

    def test_main_returns_two_before_transport_for_schema_auth_or_phase_b_errors(self):
        broken = json.loads(json.dumps(self.scenario))
        broken['confirm_groups'] = []
        self._write_private(self.scenario_path, broken)
        transport = mock.Mock()
        stdout = io.StringIO()
        code = load.main([
            '--base-url', 'https://staging.example.test/api/v1',
            '--scenario', str(self.scenario_path),
            '--auth-file', str(self.auth_path),
            '--result', str(self.result_path),
            '--workers', '60',
            '--execute-staging', broken['run_id'],
            '--max-intake-p95-ms', '5000',
            '--max-owner-wait-p95-ms', '8000',
        ], transport=transport, stdout=stdout, sleep=lambda _: None)
        self.assertEqual(code, 2)
        transport.request.assert_not_called()
        self.assertNotIn('owner-', stdout.getvalue())

    def test_token_equal_to_or_inside_safe_output_is_exit_two_before_http(self):
        for label, token, mutate in (
            ('equal_run_id', self.scenario['run_id'], lambda value: None),
            ('substring_ref', 'SECRETSEGMENT', lambda value: value[
                'confirm_groups'][0].update({
                    'group_ref': 'group-SECRETSEGMENT-safe'})),
            ('privacy_key', 'privacy', lambda value: None),
            ('privacy_flag_key', 'contains_auth_token', lambda value: None),
            ('failure_http_key', 'http_status', lambda value: None),
            ('fallback_error_code', 'UNEXPECTED_RESPONSE', lambda value: None),
        ):
            with self.subTest(label=label):
                scenario = json.loads(json.dumps(self.scenario))
                mutate(scenario)
                auth = json.loads(json.dumps(self.auth))
                auth['tokens']['owner-01'] = token
                self._write_private(self.scenario_path, scenario)
                self._write_private(self.auth_path, auth)
                transport = mock.Mock()
                stdout = io.StringIO()
                result_path = self.root / f'{label}.json'
                self.assertEqual(load.main(
                    self._main_args(result=result_path),
                    transport=transport, stdout=stdout,
                    sleep=lambda _: None), 2)
                transport.request.assert_not_called()
                self.assertNotIn(token, stdout.getvalue())
                self.assertIn(
                    stdout.getvalue(), {'', 'LOAD PREFLIGHT FAIL\n'})
                self.assertFalse(result_path.exists())

    def test_customer_id_collision_in_safe_refs_is_preflight_failure(self):
        customer_id = str(self.scenario['owners'][0]['customer_id'])
        for label, mutate in (
            ('run_id', lambda value: value.update({'run_id': customer_id})),
            ('case_ref', lambda value: value['owners'][0]['documents'][0].update({
                'case_id': customer_id})),
        ):
            with self.subTest(label=label):
                scenario = json.loads(json.dumps(self.scenario))
                mutate(scenario)
                self._write_private(self.scenario_path, scenario)
                self._write_private(self.auth_path, self.auth)
                result_path = self.root / f'customer-{label}.json'
                args = self._main_args(result=result_path)
                args[args.index('--execute-staging') + 1] = scenario['run_id']
                transport = mock.Mock()
                stdout = io.StringIO()
                self.assertEqual(load.main(
                    args, transport=transport, stdout=stdout,
                    sleep=lambda _: None), 2)
                transport.request.assert_not_called()
                self.assertFalse(result_path.exists())
                self.assertNotIn(customer_id, stdout.getvalue())
                self.assertIn(
                    stdout.getvalue(), {'', 'LOAD PREFLIGHT FAIL\n'})

    def test_privacy_scan_finds_customer_id_in_string_values_and_keys(self):
        for candidate in (
            {'safe_value': 'case-1001-collision'},
            {'metric-1001-collision': 0},
        ):
            with self.subTest(candidate=candidate):
                privacy = load.scan_privacy(
                    candidate,
                    tokens=(), file_paths=(), document_strings=(),
                    raw_response_strings=(), job_ids=(), customer_ids={1001},
                    stdout_payload='',
                )
                self.assertTrue(privacy['contains_customer_id'])

    def test_fixed_report_vocabulary_covers_complete_report_shape(self):
        phases = {
            'intake', 'scope', 'poll', 'foreign_scope', 'confirm',
            'confirm_state', 'analysis',
        }
        safe_codes = set(load.ALLOWED_SERVER_CODES) | {
            'UNEXPECTED_RESPONSE', 'POLL_TIMEOUT', 'NETWORK_ERROR',
            'TIMEOUT_ERROR', 'INVALID_RESPONSE_ERROR', 'TRANSPORT_ERROR',
        }
        metric = {'count': 60, 'p50': 200, 'p95': 202, 'max': 404}
        ordered_phases = sorted(phases)
        failures = [
            {
                'case_ref': f'case-{index}',
                'phase': ordered_phases[(index - 1) % len(ordered_phases)],
                'http_status': 409,
                'code': code,
            }
            for index, code in enumerate(sorted(safe_codes), 1)
        ]
        report = {
            'schema_version': load.RESULT_SCHEMA,
            'run_id': 'run-safe',
            'started_at': '2026-07-17T00:00:00Z',
            'finished_at': '2026-07-17T00:00:01Z',
            'configuration': {
                'workers': 60, 'owner_count': 20, 'request_count': 60,
                'max_intake_p95_ms': 200,
                'max_owner_wait_p95_ms': 202,
            },
            'correctness': {
                'accepted_202': 60, 'unexpected_http': 0,
                'cross_owner_visible': 0, 'owner_customer_mismatch': 0,
                'response_job_mismatch': 0, 'duplicate_job_excess': 0,
                'both_adds_preserved': 1, 'replace_success': 1,
                'replace_target_changed_409': 1, 'stale_overwrite': 0,
                'duplicate_analysis_amount': 0,
            },
            'latency_ms': {
                'intake': metric, 'owner_batch_wait': metric,
                'queue_wait': metric, 'end_to_end': metric,
                'owner_queue_p95': metric,
                'owner_end_to_end_p95': metric,
            },
            'provider': {
                'review_required_count': 60, 'not_started_count': 0,
                'unfinished_count': 0, 'terminal_failure_count': 0,
            },
            'provider_complete': True,
            'performance_passed': True,
            'failures': failures,
            'privacy': {field: False for field in load.PRIVACY_FIELDS},
            'passed': False,
        }

        def keys(value):
            found = set()
            if isinstance(value, dict):
                found.update(value)
                for item in value.values():
                    found.update(keys(item))
            elif isinstance(value, list):
                for item in value:
                    found.update(keys(item))
            return found

        fixed_values = {
            load.RESULT_SCHEMA, *phases,
            'true', 'false', 'null', '0', '1', '20', '60',
            '200', '202', '404', '409',
        }
        self.assertEqual(keys(report), set(load.REPORT_SCHEMA_KEYS))
        self.assertEqual(safe_codes, set(load.REPORT_SAFE_CODES))
        self.assertEqual(fixed_values, set(load.REPORT_FIXED_VALUES))
        self.assertEqual(
            load.FIXED_REPORT_TERMS,
            load.REPORT_SCHEMA_KEYS | load.REPORT_SAFE_CODES
            | load.REPORT_FIXED_VALUES,
        )
        self.assertTrue(
            keys(report) | safe_codes | fixed_values
            <= load.FIXED_REPORT_TERMS)

    def test_prewrite_privacy_scan_blocks_file_instead_of_claiming_false(self):
        scenario, auth = self._load_and_validate()
        with mock.patch.object(load, 'scan_privacy', return_value={
            'contains_auth_token': True,
            'contains_file_path': False,
            'contains_document_text': False,
            'contains_raw_response': False,
            'contains_job_id': False,
            'contains_customer_id': False,
        }):
            with self.assertRaises(load.PrivacyError):
                load.execute_and_report(
                    base_url='https://staging.example.test/api/v1',
                    scenario=scenario, auth=auth, result_path=self.result_path,
                    workers=60, execute_staging=scenario['run_id'],
                    max_intake_p95_ms=60_000,
                    max_owner_wait_p95_ms=60_000,
                    transport=FakeTransport(scenario, auth),
                    stdout=io.StringIO(), sleep=lambda _: None,
                )
        self.assertFalse(self.result_path.exists())

    def test_existing_result_is_rejected_before_any_transport_call(self):
        self.result_path.write_text('{}')
        self.result_path.chmod(0o600)
        transport = mock.Mock()
        code = load.main([
            '--base-url', 'https://staging.example.test/api/v1',
            '--scenario', str(self.scenario_path),
            '--auth-file', str(self.auth_path),
            '--result', str(self.result_path),
            '--workers', '60',
            '--execute-staging', self.scenario['run_id'],
            '--max-intake-p95-ms', '5000',
            '--max-owner-wait-p95-ms', '8000',
        ], transport=transport, stdout=io.StringIO(), sleep=lambda _: None)
        self.assertEqual(code, 2)
        transport.request.assert_not_called()

    def test_urllib_transport_sanitizes_exception_and_raw_response(self):
        transport = load.UrllibTransport()
        with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError(
                'SENTINEL_TOKEN SECRET_PATH SECRET_RAW_DETAIL')):
            with self.assertRaises(load.TransportError) as captured:
                transport.request(
                    'GET', 'https://staging.example.test/api/v1/config/',
                    token='SENTINEL_TOKEN', timeout=1)
        self.assertNotIn('SENTINEL', str(captured.exception))


if __name__ == '__main__':
    unittest.main()
