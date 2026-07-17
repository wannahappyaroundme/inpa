import json
from pathlib import Path
from unittest import mock

from corsheaders.defaults import default_headers
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from inpa.core.sentry import scrub_event, scrub_transaction


_SYNTHETIC_CREDENTIAL = ''.join(('synthetic', '-', 'credential'))


class InsuranceImportSettingsTests(SimpleTestCase):
    def test_review_gate_is_closed_by_default(self):
        self.assertFalse(settings.INSURANCE_REVIEW_GATE_ENABLED)

    def test_model_id_has_no_code_fallback(self):
        self.assertEqual(settings.CLAUDE_MODEL_PARSE, '')
        self.assertEqual(settings.CLAUDE_MODEL_BULK, '')

    def test_source_retention_defaults_to_24_hours(self):
        self.assertEqual(settings.INSURANCE_SOURCE_RETENTION_HOURS, 24)

    def test_document_resource_limits_are_finite(self):
        self.assertEqual(settings.INSURANCE_MAX_PAGES, 300)
        self.assertEqual(settings.INSURANCE_MAX_EXTRACTED_CHARS, 500_000)
        self.assertEqual(settings.INSURANCE_MAX_CANDIDATES, 2_000)
        self.assertEqual(settings.INSURANCE_MAX_QUEUED_PER_OWNER, 10)

    def test_untrusted_pdf_process_limits_are_finite(self):
        self.assertEqual(settings.INSURANCE_PDF_SANDBOX_CPU_SECONDS, 60)
        self.assertEqual(settings.INSURANCE_PDF_SANDBOX_WALL_SECONDS, 90)
        self.assertEqual(settings.INSURANCE_PDF_SANDBOX_MEMORY_MB, 384)

    def test_celery_never_accepts_pickle(self):
        self.assertEqual(settings.CELERY_TASK_SERIALIZER, 'json')
        self.assertEqual(settings.CELERY_RESULT_SERIALIZER, 'json')
        self.assertEqual(settings.CELERY_ACCEPT_CONTENT, ['json'])

    def test_pdf_worker_has_finite_time_and_memory_recycling_boundaries(self):
        from config.celery import app as celery_app

        self.assertEqual(settings.CELERY_TASK_SOFT_TIME_LIMIT, 420)
        self.assertEqual(settings.CELERY_TASK_TIME_LIMIT, 480)
        self.assertEqual(
            settings.CELERY_WORKER_MAX_TASKS_PER_CHILD, 10)
        self.assertEqual(
            settings.CELERY_WORKER_MAX_MEMORY_PER_CHILD, 180_000)
        self.assertGreater(
            settings.CELERY_BROKER_TRANSPORT_OPTIONS['visibility_timeout'],
            settings.CELERY_TASK_TIME_LIMIT,
        )
        self.assertEqual(celery_app.conf.worker_max_tasks_per_child, 10)
        self.assertEqual(celery_app.conf.worker_max_memory_per_child, 180_000)

    def test_local_worker_runs_eager_without_redis(self):
        self.assertTrue(settings.CELERY_TASK_ALWAYS_EAGER)
        self.assertTrue(settings.CELERY_TASK_EAGER_PROPAGATES)

    def test_cors_patch_preflight_allows_idempotency_key_and_defaults(self):
        response = self.client.options(
            '/api/v1/insurance-imports/00000000-0000-0000-0000-000000000001/draft/',
            HTTP_ORIGIN='http://localhost:3000',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='PATCH',
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS=(
                'authorization,content-type,idempotency-key'),
        )

        allowed_headers = {
            value.strip().lower()
            for value in response['Access-Control-Allow-Headers'].split(',')
        }
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Access-Control-Allow-Origin'], 'http://localhost:3000')
        self.assertIn('idempotency-key', allowed_headers)
        self.assertTrue(set(default_headers).issubset(allowed_headers))

    def test_local_source_storage_is_outside_public_media(self):
        config = settings.STORAGES['insurance_sources']
        source_root = Path(config['OPTIONS']['location']).resolve()
        media_root = Path(settings.MEDIA_ROOT).resolve()

        self.assertEqual(
            config['BACKEND'], 'django.core.files.storage.FileSystemStorage')
        self.assertIsNone(config['OPTIONS']['base_url'])
        self.assertNotEqual(source_root, media_root)
        self.assertNotIn(media_root, source_root.parents)
        self.assertEqual(config['OPTIONS']['file_permissions_mode'], 0o600)
        self.assertEqual(config['OPTIONS']['directory_permissions_mode'], 0o700)

    def test_sentry_scrubber_removes_every_sensitive_container(self):
        sentinel = '홍길동-증권원문-provider-payload'
        event = {
            'message': sentinel,
            'logentry': {'message': sentinel},
            'user': {'email': sentinel},
            'breadcrumbs': {'values': [{'message': sentinel, 'data': {'body': sentinel}}]},
            'contexts': {'custom': {'draft': sentinel}, 'trace': {'description': sentinel}},
            'spans': [{'description': sentinel, 'data': {'provider': sentinel}}],
            'tags': {'customer': sentinel},
            'request': {
                'method': 'POST',
                'url': f'https://example.test/import?name={sentinel}',
                'query_string': f'name={sentinel}',
                'data': {'pdf': sentinel},
                'cookies': {'sessionid': sentinel},
                'headers': {'Authorization': sentinel, 'Cookie': sentinel},
                'env': {'REMOTE_USER': sentinel},
            },
            'exception': {'values': [{
                'type': 'ValueError',
                'value': sentinel,
                'stacktrace': {'frames': [{'vars': {'draft_payload': sentinel}}]},
            }]},
            'extra': {
                'job_uuid': '00000000-0000-0000-0000-000000000001',
                'exception_type': 'ValueError',
                'outcome': 'failed',
                'pdf_text': sentinel,
                'masked_lines': [sentinel],
                'draft_payload': {'raw': sentinel},
                'provider_payload': {'raw': sentinel},
            },
        }

        cleaned = scrub_event(event, {})
        self.assertNotIn(sentinel, json.dumps(cleaned, ensure_ascii=False))
        self.assertEqual(cleaned['request'], {'method': 'POST'})
        self.assertEqual(
            set(cleaned['extra']), {'job_uuid', 'exception_type', 'outcome'})
        for key in ('user', 'breadcrumbs', 'contexts', 'spans', 'tags'):
            self.assertNotIn(key, cleaned)

    def test_sentry_scrubber_rejects_malformed_allowlisted_values(self):
        sentinel = '홍길동-원문-payload'
        cleaned = scrub_event({
            'extra': {
                'job_uuid': sentinel,
                'exception_type': sentinel,
                'outcome': sentinel,
            },
        }, {})

        self.assertEqual(cleaned['extra'], {})
        self.assertNotIn(sentinel, json.dumps(cleaned, ensure_ascii=False))

    def test_sentry_transaction_scrubber_keeps_only_safe_trace_metadata(self):
        sentinel = '홍길동-증권원문-provider-payload'
        transaction = {
            'type': 'transaction',
            'event_id': 'a' * 32,
            'transaction': f'/api/import/{sentinel}',
            'transaction_info': {'source': sentinel},
            'start_timestamp': 10.25,
            'timestamp': 11.75,
            'request': {'url': sentinel, 'query_string': sentinel},
            'user': {'email': sentinel},
            'contexts': {
                'trace': {
                    'trace_id': 'b' * 32,
                    'span_id': 'c' * 16,
                    'op': 'http.server',
                    'status': 'ok',
                    'description': sentinel,
                    'data': {'provider': sentinel},
                    'tags': {'customer': sentinel},
                },
                'custom': {'payload': sentinel},
            },
            'spans': [{
                'trace_id': 'b' * 32,
                'span_id': 'd' * 16,
                'parent_span_id': 'c' * 16,
                'op': 'db',
                'status': 'ok',
                'start_timestamp': 10.5,
                'timestamp': 10.75,
                'description': sentinel,
                'data': {'statement': sentinel},
                'tags': {'provider': sentinel},
            }],
            'tags': {'customer': sentinel},
            'fingerprint': [sentinel],
            'extra': {'provider_payload': sentinel},
            'breadcrumbs': {'values': [{'message': sentinel}]},
            'measurements': {'custom': {'value': sentinel}},
        }

        cleaned = scrub_transaction(transaction, {})

        self.assertNotIn(sentinel, json.dumps(cleaned, ensure_ascii=False))
        self.assertEqual(cleaned['transaction'], 'http.server')
        self.assertEqual(cleaned['contexts']['trace']['op'], 'http.server')
        self.assertEqual(cleaned['spans'][0]['op'], 'db')
        self.assertEqual(cleaned['spans'][0]['start_timestamp'], 10.5)
        self.assertNotIn('request', cleaned)
        self.assertNotIn('transaction_info', cleaned)

    def test_prod_sentry_wires_transaction_scrubber(self):
        prod_settings = (Path(settings.BASE_DIR) / 'config/settings/prod.py').read_text()
        self.assertIn('before_send_transaction=scrub_transaction', prod_settings)

    @override_settings(
        CLAUDE_API_KEY=_SYNTHETIC_CREDENTIAL,
        CLAUDE_MODEL_PARSE='',
    )
    @mock.patch('anthropic.Anthropic')
    def test_parser_missing_model_fails_closed_before_provider_call(self, anthropic_client):
        from inpa.core.ocr.claude_parser import claude_parse

        meta = {}
        with self.assertLogs('inpa.core.ocr.claude_parser', level='WARNING') as logs:
            result = claude_parse(['고객 원문 sentinel'], meta=meta)

        self.assertIsNone(result)
        self.assertEqual(meta['outcome'], 'no_model')
        self.assertIsNone(meta['usage'])
        anthropic_client.assert_not_called()
        self.assertNotIn('고객 원문 sentinel', '\n'.join(logs.output))

    @override_settings(
        ANTHROPIC_API_KEY=_SYNTHETIC_CREDENTIAL,
        CLAUDE_API_KEY=_SYNTHETIC_CREDENTIAL,
        CLAUDE_MODEL_PARSE='')
    @mock.patch('anthropic.Anthropic')
    def test_verifier_missing_model_fails_closed_before_provider_call(self, anthropic_client):
        from inpa.insurances.verify import verify_extraction

        with self.assertLogs('inpa.insurances.verify', level='WARNING') as logs:
            result, usage = verify_extraction(['고객 원문 sentinel'], None)

        self.assertIsNone(result)
        self.assertIsNone(usage)
        anthropic_client.assert_not_called()
        self.assertIn('모델 미설정', '\n'.join(logs.output))
        self.assertNotIn('고객 원문 sentinel', '\n'.join(logs.output))

    @override_settings(
        CLAUDE_API_KEY=_SYNTHETIC_CREDENTIAL,
        CLAUDE_MODEL_PARSE='',
    )
    @mock.patch('anthropic.Anthropic')
    def test_compare_missing_model_fails_closed_before_provider_call(self, anthropic_client):
        from inpa.analysis.compare import _generate_guide_draft

        summary = {'monthly_premiums': 0, 'total_premiums': 0}
        meta = {}
        with self.assertLogs('inpa.analysis.compare', level='WARNING') as logs:
            text, usage = _generate_guide_draft(
                None, summary, summary, [], meta=meta)

        self.assertIsNone(text)
        self.assertIsNone(usage)
        self.assertEqual(meta['outcome'], 'no_model')
        anthropic_client.assert_not_called()
        self.assertIn('CLAUDE_MODEL_PARSE not configured', '\n'.join(logs.output))
