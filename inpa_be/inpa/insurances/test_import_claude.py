import inspect
import logging
import os
from types import SimpleNamespace
from unittest import mock

import anthropic
from django.test import SimpleTestCase, override_settings
from pydantic import ValidationError

from . import import_claude
from .import_contract import CoverageCandidate, MaskedLine
from .import_claude import (
    ClaudeExtractionPayload,
    ExtractionFailure,
    extract,
)


def _evidence(value, line_id='p01-l001'):
    return {'value': value, 'evidence_line_ids': [line_id]}


def _payload():
    return ClaudeExtractionPayload.model_validate({
        'schema_version': 'insurance-review-v1',
        'policy': {
            'carrier_name': _evidence('한빛생명'),
            'company_code': _evidence(1),
            'insurance_type': _evidence('life'),
            'product_name': _evidence('건강보험'),
            'contract_date': _evidence('2024.01.01'),
            'expiry_date': _evidence('2044.01.01'),
            'monthly_premium': _evidence(30_000),
        },
        'coverage_rows': [{
            'row_id': 'r00001',
            'raw_name': '일반암진단비',
            'assurance_amount': 30_000_000,
            'premium': 30_000,
            'is_renewal': False,
            'renewal_period': None,
            'payment_period': 20,
            'payment_period_unit': 'years',
            'warranty_period': 100,
            'warranty_period_unit': 'age',
            'disposition': 'assigned',
            'standard_category': '진단-암',
            'standard_subcategory': '일반암',
            'standard_detail_name': '일반암진단비',
            'exclusion_reason': None,
            'source_candidate_ids': ['c00001'],
            'evidence_line_ids': ['p01-l001'],
        }],
    })


class _RetryableTimeout(Exception):
    pass


class _RetryableConnection(Exception):
    pass


class _RetryableRateLimit(Exception):
    pass


class _RetryableServer(Exception):
    pass


class _StatusError(Exception):
    def __init__(self, status_code, message='provider error'):
        self.status_code = status_code
        super().__init__(message)


class _Messages:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _anthropic_double(messages):
    client = SimpleNamespace(messages=messages)
    module = SimpleNamespace(
        Anthropic=mock.Mock(return_value=client),
        APITimeoutError=_RetryableTimeout,
        APIConnectionError=_RetryableConnection,
        RateLimitError=_RetryableRateLimit,
        InternalServerError=_RetryableServer,
    )
    return module, client


def _lines_and_candidates():
    line = MaskedLine(
        line_id='p01-l001', page=1, line=1,
        text_masked='일반암진단비 3,000만원 보험료 30,000원')
    candidate = CoverageCandidate(
        candidate_id='c00001',
        evidence_line_ids=('p01-l001',),
        text_masked=line.text_masked,
    )
    return (line,), (candidate,)


class ClaudeStructuredExtractionTests(SimpleTestCase):
    def test_provider_privacy_gate_blocks_identifiers_in_every_free_string_leaf(self):
        string_paths = (
            ('schema_version',),
            ('policy', 'carrier_name', 'value'),
            ('policy', 'carrier_name', 'evidence_line_ids', 0),
            ('policy', 'company_code', 'evidence_line_ids', 0),
            ('policy', 'insurance_type', 'evidence_line_ids', 0),
            ('policy', 'product_name', 'value'),
            ('policy', 'product_name', 'evidence_line_ids', 0),
            ('policy', 'contract_date', 'value'),
            ('policy', 'contract_date', 'evidence_line_ids', 0),
            ('policy', 'expiry_date', 'value'),
            ('policy', 'expiry_date', 'evidence_line_ids', 0),
            ('policy', 'monthly_premium', 'evidence_line_ids', 0),
            ('coverage_rows', 0, 'row_id'),
            ('coverage_rows', 0, 'raw_name'),
            ('coverage_rows', 0, 'standard_category'),
            ('coverage_rows', 0, 'standard_subcategory'),
            ('coverage_rows', 0, 'standard_detail_name'),
            ('coverage_rows', 0, 'exclusion_reason'),
            ('coverage_rows', 0, 'source_candidate_ids', 0),
            ('coverage_rows', 0, 'evidence_line_ids', 0),
        )
        sentinels = (
            '900101-1234567',
            '900101‑12*****',
            '+82 (0)10 1234 5678',
            'privacy.person@example.test',
            '계약번호: CONTRACT-PRIVATE-9911',
            '고객번호: CUSTOMER-PRIVATE-7711',
            '설계사번호: PLANNER-PRIVATE-5511',
            '모집인등록번호: RECRUITER-PRIVATE-3311',
            '자격번호: LICENSE-PRIVATE-2211',
            '계약자: 홍길동',
            '담당설계사 김인파',
            '홍길동(계약자)',
            '보험계약자명: 홍길동',
            '피보험자명 홍길동',
            '모집인명: 김인파',
            '계약번호: privatecode',
            '계약번호: 혼합식별자ab',
            '계약번호:\nprivatecode',
            '계약번호: [계약번호_1] 확인 privatecode',
            '계약자 (성명) 테스트홍길동',
            '계약자(이름): 테스트홍길동',
            '모집인 (명) 테스트김',
            '테스트홍길동\n(계약자)',
            '계약자（성명）테스트홍길동',
            '테스트홍길동（계약자）',
            '계약자 [성명] 테스트홍길동',
            '계약자{성명}: 테스트홍길동',
            '계약자\n테스트홍길동',
            '계약자(성 명): 테스트홍길동',
            '계약자 ( 이름 ) 테스트홍길동',
            '담당설계사(성명) 테스트김',
            '계약자: 테스트A김',
            '담당설계사: Kim테스트',
            '테스트A김(계약자)',
            'a테스트kim (담당설계사)',
            '계약자: A',
            '계약자: 테스트홍길동 1980.01.01',
            '계약번호（번호）privatecode',
            '계약번호{번호}: privatecode',
            '설계사번호（TEST）abc123',
            '계약자 홍길동 보험료 납입면제',
            '피보험자 테스트A김 진단비',
            '수익자 A 보험금 지급',
            '계약자 홍길동 1980.01.01 보험료',
        )

        for path in string_paths:
            for sentinel in sentinels:
                with self.subTest(path=path, kind=sentinels.index(sentinel)):
                    payload = _payload().model_dump(mode='json')
                    parent = payload
                    for key in path[:-1]:
                        parent = parent[key]
                    parent[path[-1]] = sentinel

                    with self.assertRaises(ExtractionFailure) as caught:
                        import_claude.assert_provider_payload_pii_safe(
                            payload,
                            ('피보험자 갑상선암진단비 가입금액 1,000만원',),
                        )

                    self.assertEqual(
                        caught.exception.code, 'PROVIDER_PII_OUTPUT')
                    self.assertEqual(str(caught.exception), 'PROVIDER_PII_OUTPUT')
                    self.assertNotIn(sentinel, repr(caught.exception))

    def test_provider_privacy_gate_allows_aliases_and_insurance_role_phrases(self):
        payload = _payload().model_dump(mode='json')
        payload['policy']['product_name']['value'] = (
            '무배당 피보험자 사망보험금 특약')
        payload['coverage_rows'][0]['raw_name'] = '피보험자 사망보험금'
        payload['coverage_rows'][0]['exclusion_reason'] = (
            '계약자 [고객_1], 설계사 [설계사_1] 확인')
        payload['coverage_rows'][0]['standard_subcategory'] = (
            '피보험자 연령 기준 15세 이상')
        payload['coverage_rows'][0]['standard_detail_name'] = (
            '피보험자 직업급수 1급')
        payload['coverage_rows'][0]['standard_category'] = (
            '계약자 권리 안내')
        payload['coverage_rows'][0]['payment_period_unit'] = (
            '피보험자 조건 확인')
        payload['coverage_rows'][0]['raw_name'] = (
            '계약자 배당금 지급 안내')
        payload['policy']['contract_date']['value'] = (
            '계약번호: [계약번호_1] 확인')

        safe_source_texts = (
            '무배당 피보험자 사망보험금 특약',
            '계약자 [고객_1], 설계사 [설계사_1] 확인',
            '피보험자 연령 기준 15세 이상',
            '피보험자 직업급수 1급',
            '계약자 권리 안내',
            '피보험자 조건 확인',
            '계약자 배당금 지급 안내',
            '계약번호: [계약번호_1] 확인',
        )
        self.assertIsNone(import_claude.assert_provider_payload_pii_safe(
            payload, safe_source_texts))

    def test_provider_privacy_gate_preserves_structured_insurance_role_facts(self):
        safe_facts = (
            '피보험자 일반암진단비',
            '피보험자 질병후유장해 보험금',
            '피보험자 암 진단 확정 시',
            '계약자 보험료 납입면제',
            '피보험자 상해사망 1억원',
            '수익자 보험금 지급',
            '피보험자 치료비 특약',
            '계약자 납입기간 20년',
            '피보험자 갑상선암진단비',
            '피보험자 제자리암 진단비',
            '피보험자 다발성소아암 진단비',
            '피보험자 특정류마티스관절염 진단비',
            '피보험자 대상포진 진단비',
            '피보험자 5대장기이식수술비',
            '피보험자 깁스치료비',
            '피보험자 응급실내원비',
            '피보험자 특정감염병입원일당',
            '피보험자 중대한화상및부식진단비',
            '피보험자 여성특정질병수술비',
            '피보험자 뇌혈관질환진단비',
        )
        for safe_fact in safe_facts:
            with self.subTest(safe_fact=safe_fact):
                payload = _payload().model_dump(mode='json')
                payload['coverage_rows'][0]['raw_name'] = safe_fact
                safe_source = (
                    f'담보명 {safe_fact} 가입금액 1,000만원',
                )
                self.assertIsNone(import_claude.assert_provider_payload_pii_safe(
                    payload, safe_source))

    def test_provider_role_fact_without_source_grounding_fails_closed(self):
        payload = _payload().model_dump(mode='json')
        payload['coverage_rows'][0]['raw_name'] = '피보험자 갑상선암진단비'

        with self.assertRaises(ExtractionFailure):
            import_claude.assert_provider_payload_pii_safe(payload)

    def test_grounding_normalization_does_not_change_aliases_or_amount_digits(self):
        safe_source = ('계약자 (성명) [고객_1] 보험료 3,000원',)
        payload = _payload().model_dump(mode='json')

        payload['coverage_rows'][0]['raw_name'] = (
            '계약자 （성명） [고객_1] 보험료 3,000원')
        self.assertIsNone(import_claude.assert_provider_payload_pii_safe(
            payload, safe_source))

        for changed in (
                '계약자 (성명) ［고객_1］ 보험료 3,000원',
                '계약자 (성명) [고객_1] 보험료 ３,０００원'):
            with self.subTest(changed=changed):
                payload['coverage_rows'][0]['raw_name'] = changed
                with self.assertRaises(ExtractionFailure):
                    import_claude.assert_provider_payload_pii_safe(
                        payload, safe_source)

    @override_settings(
        CLAUDE_MODEL_PARSE='configured-model',
        ANTHROPIC_API_KEY='configured-test-key')
    def test_extract_scans_strict_provider_output_before_returning(self):
        unsafe = _payload().model_copy(deep=True)
        unsafe.policy.product_name.value = '계약자: 홍길동'
        response = SimpleNamespace(
            parsed_output=unsafe,
            usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        )
        messages = _Messages([response])
        module, _client = _anthropic_double(messages)
        lines, candidates = _lines_and_candidates()

        with mock.patch(
                'inpa.insurances.import_claude.importlib.import_module',
                return_value=module), self.assertRaises(
                    ExtractionFailure) as caught:
            extract(lines, candidates, 'insurance-review-v1')

        self.assertEqual(caught.exception.code, 'PROVIDER_PII_OUTPUT')

    def test_installed_sdk_signature_supports_stable_structured_parse(self):
        client = anthropic.Anthropic(api_key='test-only')
        signature = inspect.signature(client.messages.parse)

        self.assertEqual(anthropic.__version__, '0.111.0')
        self.assertTrue({
            'model', 'max_tokens', 'system', 'messages', 'output_format',
        }.issubset(signature.parameters))

    @override_settings(
        CLAUDE_MODEL_PARSE='', ANTHROPIC_API_KEY='configured-test-key')
    def test_missing_model_fails_before_provider_import_or_call(self):
        lines, candidates = _lines_and_candidates()

        with mock.patch(
                'inpa.insurances.import_claude.importlib.import_module') as importer, \
                self.assertRaises(ExtractionFailure) as caught:
            extract(lines, candidates, 'insurance-review-v1')

        self.assertEqual(caught.exception.code, 'MODEL_NOT_CONFIGURED')
        importer.assert_not_called()

    def test_schema_rejects_missing_evidence_and_confidence(self):
        missing_row_evidence = _payload().model_dump()
        missing_row_evidence['coverage_rows'][0].pop('evidence_line_ids')
        missing_policy_evidence = _payload().model_dump()
        missing_policy_evidence['policy']['product_name'].pop(
            'evidence_line_ids')
        extra_confidence = _payload().model_dump()
        extra_confidence['coverage_rows'][0]['confidence'] = 0.99
        wrong_policy_type = _payload().model_dump()
        wrong_policy_type['policy']['carrier_name']['value'] = 123

        with self.assertRaises(ValidationError):
            ClaudeExtractionPayload.model_validate(missing_row_evidence)
        with self.assertRaises(ValidationError):
            ClaudeExtractionPayload.model_validate(missing_policy_evidence)
        with self.assertRaises(ValidationError):
            ClaudeExtractionPayload.model_validate(extra_confidence)
        with self.assertRaises(ValidationError):
            ClaudeExtractionPayload.model_validate(wrong_policy_type)

    def test_schema_requires_strict_trimmed_nonempty_row_identity(self):
        for field in ('row_id', 'raw_name'):
            for invalid_value in ('', '   ', 123):
                with self.subTest(field=field, invalid_value=invalid_value):
                    invalid = _payload().model_dump()
                    invalid['coverage_rows'][0][field] = invalid_value

                    with self.assertRaises(ValidationError):
                        ClaudeExtractionPayload.model_validate(invalid)

        trimmed = _payload().model_dump()
        trimmed['coverage_rows'][0]['row_id'] = '  r00001  '
        trimmed['coverage_rows'][0]['raw_name'] = '  일반암진단비  '

        parsed = ClaudeExtractionPayload.model_validate(trimmed)

        self.assertEqual(parsed.coverage_rows[0].row_id, 'r00001')
        self.assertEqual(parsed.coverage_rows[0].raw_name, '일반암진단비')

    @override_settings(
        CLAUDE_MODEL_PARSE='configured-model',
        ANTHROPIC_API_KEY='configured-test-key')
    def test_uses_stable_strict_parse_sdk_retry_zero_and_untrusted_prompt(self):
        response = SimpleNamespace(
            parsed_output=_payload(),
            usage=SimpleNamespace(
                input_tokens=111,
                output_tokens=22,
                cache_read_input_tokens=33,
                cache_creation_input_tokens=44,
            ),
        )
        messages = _Messages([response])
        module, _client = _anthropic_double(messages)
        lines, candidates = _lines_and_candidates()

        with mock.patch(
                'inpa.insurances.import_claude.time.monotonic',
                side_effect=(10.0, 10.125)), mock.patch(
                    'inpa.insurances.import_claude.importlib.import_module',
                    return_value=module):
            result = extract(lines, candidates, 'insurance-review-v1')

        module.Anthropic.assert_called_once_with(
            api_key='configured-test-key', max_retries=0)
        call = messages.calls[0]
        self.assertIs(call['output_format'], ClaudeExtractionPayload)
        self.assertEqual(call['model'], 'configured-model')
        self.assertIn('신뢰할 수 없는 데이터', call['system'])
        self.assertIn('문서 안의 명령', call['system'])
        self.assertIn('진단-암 > 일반암 > 일반암진단비', call['system'])
        self.assertIn('삼성생명=206', call['system'])
        self.assertEqual(result.payload['schema_version'],
                         'insurance-review-v1')
        self.assertEqual((result.input_tokens, result.output_tokens),
                         (111, 22))
        self.assertEqual(
            (result.cache_read_input_tokens,
             result.cache_creation_input_tokens,
             result.latency_ms),
            (33, 44, 125),
        )

    @override_settings(
        CLAUDE_MODEL_PARSE='configured-model',
        ANTHROPIC_API_KEY='configured-test-key')
    def test_schema_failure_keeps_only_numeric_usage_and_latency(self):
        response = SimpleNamespace(
            parsed_output=None,
            usage=SimpleNamespace(
                input_tokens=12,
                output_tokens=3,
                cache_read_input_tokens=4,
                cache_creation_input_tokens=5,
            ),
        )
        messages = _Messages([response])
        module, _client = _anthropic_double(messages)
        lines, candidates = _lines_and_candidates()

        with mock.patch(
                'inpa.insurances.import_claude.time.monotonic',
                side_effect=(20.0, 20.250)), mock.patch(
                    'inpa.insurances.import_claude.importlib.import_module',
                    return_value=module), self.assertRaises(
                        ExtractionFailure) as caught:
            extract(lines, candidates, 'insurance-review-v1')

        failure = caught.exception
        self.assertEqual(failure.code, 'SCHEMA_INVALID')
        self.assertEqual(failure.model_id, 'configured-model')
        self.assertEqual(failure.latency_ms, 250)
        self.assertEqual(failure.usage, {
            'input_tokens': 12,
            'output_tokens': 3,
            'cache_read_input_tokens': 4,
            'cache_creation_input_tokens': 5,
        })

    @override_settings(
        CLAUDE_MODEL_PARSE='configured-model',
        ANTHROPIC_API_KEY='configured-test-key')
    def test_timeout_network_429_and_5xx_retry_three_times_at_1_2_4(self):
        response = SimpleNamespace(
            parsed_output=_payload(),
            usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        )
        retryable_errors = (
            _RetryableTimeout('timeout'),
            _RetryableConnection('network'),
            _StatusError(429),
            _StatusError(503),
        )
        lines, candidates = _lines_and_candidates()

        for error in retryable_errors:
            with self.subTest(error=type(error).__name__,
                              status=getattr(error, 'status_code', None)):
                messages = _Messages([error, error, error, response])
                module, _client = _anthropic_double(messages)
                with mock.patch(
                        'inpa.insurances.import_claude.time.sleep') as sleeper, \
                        mock.patch(
                            'inpa.insurances.import_claude.importlib.import_module',
                            return_value=module):
                    extract(lines, candidates, 'insurance-review-v1')

                self.assertEqual(len(messages.calls), 4)
                self.assertEqual(
                    [call.args[0] for call in sleeper.call_args_list],
                    [1, 2, 4],
                )

    @override_settings(
        CLAUDE_MODEL_PARSE='configured-model',
        ANTHROPIC_API_KEY='configured-test-key')
    def test_400_401_403_are_not_retried(self):
        lines, candidates = _lines_and_candidates()

        for status_code in (400, 401, 403):
            with self.subTest(status_code=status_code):
                messages = _Messages([_StatusError(status_code)])
                module, _client = _anthropic_double(messages)
                with mock.patch(
                        'inpa.insurances.import_claude.time.sleep') as sleeper, \
                        mock.patch(
                            'inpa.insurances.import_claude.importlib.import_module',
                            return_value=module), \
                        self.assertRaises(ExtractionFailure) as caught:
                    extract(lines, candidates, 'insurance-review-v1')

                self.assertEqual(
                    caught.exception.code, 'PROVIDER_REQUEST_REJECTED')
                self.assertEqual(len(messages.calls), 1)
                sleeper.assert_not_called()

    @override_settings(
        CLAUDE_MODEL_PARSE='configured-model',
        ANTHROPIC_API_KEY='configured-test-key')
    def test_logs_only_safe_metadata_not_lines_prompt_or_raw_response(self):
        sentinel = 'MASKED-POLICY-LINE-RAW-RESPONSE-SECRET'
        lines = (MaskedLine(
            line_id='p01-l001', page=1, line=1,
            text_masked=sentinel),)
        candidates = (CoverageCandidate(
            candidate_id='c00001',
            evidence_line_ids=('p01-l001',),
            text_masked=sentinel,
        ),)
        messages = _Messages([_StatusError(400, sentinel)])
        module, _client = _anthropic_double(messages)

        with mock.patch(
                'inpa.insurances.import_claude.importlib.import_module',
                return_value=module), self.assertLogs(
                    'inpa.insurances.import_claude', level='WARNING') as logs, \
                self.assertRaises(ExtractionFailure):
            extract(lines, candidates, 'insurance-review-v1')

        rendered = '\n'.join(logs.output)
        self.assertNotIn(sentinel, rendered)
        self.assertNotIn('<document_data>', rendered)
        self.assertIn('_StatusError', rendered)


class OpenAIEvaluatorExtractionTests(SimpleTestCase):
    @staticmethod
    def _sdk_double(responses):
        client = SimpleNamespace(responses=responses)
        return SimpleNamespace(
            OpenAI=mock.Mock(return_value=client),
            APITimeoutError=_RetryableTimeout,
            APIConnectionError=_RetryableConnection,
            RateLimitError=_RetryableRateLimit,
            InternalServerError=_RetryableServer,
        )

    def test_missing_dedicated_key_or_model_never_imports_sdk(self):
        from . import import_openai_eval

        lines, candidates = _lines_and_candidates()
        for configured in (
            {'OPENAI_EVAL_MODEL': 'configured-eval-model'},
            {'OPENAI_EVAL_API_KEY': 'configured-eval-key'},
        ):
            with self.subTest(configured=tuple(configured)), mock.patch.dict(
                    os.environ, configured, clear=True), mock.patch(
                        'inpa.insurances.import_openai_eval.'
                        'importlib.import_module') as sdk_import, \
                    self.assertRaises(ExtractionFailure) as caught:
                import_openai_eval.extract(
                    lines, candidates, 'insurance-review-v1')

            self.assertEqual(
                caught.exception.code,
                'API_KEY_NOT_CONFIGURED'
                if 'OPENAI_EVAL_API_KEY' not in configured
                else 'MODEL_NOT_CONFIGURED',
            )
            sdk_import.assert_not_called()

    def test_missing_sdk_is_a_safe_failure(self):
        from . import import_openai_eval

        lines, candidates = _lines_and_candidates()
        with mock.patch.dict(os.environ, {
            'OPENAI_EVAL_API_KEY': 'configured-eval-key',
            'OPENAI_EVAL_MODEL': 'configured-eval-model',
        }, clear=True), mock.patch(
            'inpa.insurances.import_openai_eval.importlib.import_module',
            side_effect=ImportError), self.assertRaises(
                ExtractionFailure) as caught:
            import_openai_eval.extract(
                lines, candidates, 'insurance-review-v1')

        self.assertEqual(caught.exception.code, 'PROVIDER_PACKAGE_MISSING')
        self.assertEqual(str(caught.exception), 'PROVIDER_PACKAGE_MISSING')

    def test_structured_response_is_non_persisting_and_uses_masked_content(self):
        from . import import_openai_eval

        lines, candidates = _lines_and_candidates()
        responses = mock.Mock()
        responses.parse.return_value = SimpleNamespace(
            output_parsed=_payload(),
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )
        client = SimpleNamespace(responses=responses)
        sdk = SimpleNamespace(OpenAI=mock.Mock(return_value=client))

        with mock.patch.dict(os.environ, {
            'OPENAI_EVAL_API_KEY': 'configured-eval-key',
            'OPENAI_EVAL_MODEL': 'configured-eval-model',
        }, clear=True), mock.patch(
            'inpa.insurances.import_openai_eval.importlib.import_module',
            return_value=sdk):
            result = import_openai_eval.extract(
                lines, candidates, 'insurance-review-v1')

        request = responses.parse.call_args.kwargs
        self.assertFalse(request['store'])
        self.assertEqual(request['model'], 'configured-eval-model')
        self.assertEqual(request['max_output_tokens'], 8192)
        self.assertIs(request['text_format'], ClaudeExtractionPayload)
        self.assertEqual(request['input'][0]['content'], import_claude.SYSTEM_PROMPT)
        user_content = request['input'][1]['content']
        self.assertIn(lines[0].text_masked, user_content)
        self.assertNotIn('configured-eval-key', repr(request))
        self.assertEqual(result.input_tokens, 11)
        self.assertEqual(result.output_tokens, 7)

    def test_provider_identifier_is_rejected_without_raw_log_or_result(self):
        from . import import_openai_eval

        unsafe = _payload().model_copy(deep=True)
        unsafe.coverage_rows[0].raw_name = '담당자 홍길동 010-1234-5678'
        responses = mock.Mock()
        responses.parse.return_value = SimpleNamespace(
            output_parsed=unsafe,
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )
        sdk = SimpleNamespace(OpenAI=mock.Mock(return_value=SimpleNamespace(
            responses=responses)))
        lines, candidates = _lines_and_candidates()

        with mock.patch.dict(os.environ, {
            'OPENAI_EVAL_API_KEY': 'configured-eval-key',
            'OPENAI_EVAL_MODEL': 'configured-eval-model',
        }, clear=True), mock.patch(
            'inpa.insurances.import_openai_eval.importlib.import_module',
            return_value=sdk), self.assertRaises(
                ExtractionFailure) as caught:
            import_openai_eval.extract(
                lines, candidates, 'insurance-review-v1')

        self.assertEqual(caught.exception.code, 'PROVIDER_PII_OUTPUT')
        self.assertNotIn('홍길동', str(caught.exception))
        self.assertNotIn('010-1234-5678', str(caught.exception))

    def test_transient_errors_retry_three_times_but_client_errors_do_not(self):
        from . import import_openai_eval

        response = SimpleNamespace(
            output_parsed=_payload(),
            usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        )
        lines, candidates = _lines_and_candidates()
        configured = {
            'OPENAI_EVAL_API_KEY': 'configured-eval-key',
            'OPENAI_EVAL_MODEL': 'configured-eval-model',
        }

        retrying = _Messages([
            _StatusError(429), _StatusError(429), _StatusError(429), response,
        ])
        with mock.patch.dict(os.environ, configured, clear=True), mock.patch(
                'inpa.insurances.import_openai_eval.time.sleep') as sleeper, \
                mock.patch(
                    'inpa.insurances.import_openai_eval.importlib.import_module',
                    return_value=self._sdk_double(retrying)):
            import_openai_eval.extract(
                lines, candidates, 'insurance-review-v1')
        self.assertEqual(len(retrying.calls), 4)
        self.assertEqual(
            [call.args[0] for call in sleeper.call_args_list], [1, 2, 4])

        rejected = _Messages([_StatusError(400)])
        with mock.patch.dict(os.environ, configured, clear=True), mock.patch(
                'inpa.insurances.import_openai_eval.time.sleep') as sleeper, \
                mock.patch(
                    'inpa.insurances.import_openai_eval.importlib.import_module',
                    return_value=self._sdk_double(rejected)), \
                self.assertRaises(ExtractionFailure) as caught:
            import_openai_eval.extract(
                lines, candidates, 'insurance-review-v1')
        self.assertEqual(caught.exception.code, 'PROVIDER_REQUEST_REJECTED')
        self.assertEqual(len(rejected.calls), 1)
        sleeper.assert_not_called()

    def test_sdk_and_http_debug_logs_cannot_emit_private_request_content(self):
        from . import import_openai_eval

        sentinel = 'PRIVATE-MASKED-DOCUMENT-REQUEST-SENTINEL'
        lines = (MaskedLine(
            line_id='p01-l001', page=1, line=1,
            text_masked=sentinel,
        ),)
        candidates = (CoverageCandidate(
            candidate_id='c00001',
            evidence_line_ids=('p01-l001',),
            text_masked=sentinel,
        ),)

        class LeakyResponses(_Messages):
            def parse(self, **kwargs):
                logging.getLogger('openai._base_client').debug(
                    'Request options: %r', kwargs)
                logging.getLogger('httpx').debug(
                    'request-body=%s', sentinel)
                return super().parse(**kwargs)

        responses = LeakyResponses([SimpleNamespace(
            output_parsed=_payload(),
            usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        )])
        configured = {
            'OPENAI_EVAL_API_KEY': 'configured-eval-key',
            'OPENAI_EVAL_MODEL': 'configured-eval-model',
        }
        loggers = [
            logging.getLogger(name)
            for name in ('openai', 'openai._base_client', 'httpx', 'httpcore')
        ]
        prior_disabled = [False, False, False, True]
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Capture()
        previous_global_disable = logging.root.manager.disable
        previous = [
            (logger.disabled, logger.level, logger.propagate)
            for logger in loggers
        ]
        try:
            for logger, disabled in zip(loggers, prior_disabled):
                logger.disabled = disabled
                logger.setLevel(logging.DEBUG)
                logger.propagate = False
                logger.addHandler(handler)
            with mock.patch.dict(os.environ, configured, clear=True), \
                    mock.patch(
                        'inpa.insurances.import_openai_eval.'
                        'importlib.import_module',
                        return_value=self._sdk_double(responses)):
                import_openai_eval.extract(
                    lines, candidates, 'insurance-review-v1')

            self.assertEqual(
                [logger.disabled for logger in loggers], prior_disabled)
            self.assertEqual(
                logging.root.manager.disable, previous_global_disable)
            self.assertNotIn(sentinel, '\n'.join(records))

            failing = LeakyResponses([_StatusError(400, sentinel)])
            with mock.patch.dict(os.environ, configured, clear=True), \
                    mock.patch(
                        'inpa.insurances.import_openai_eval.'
                        'importlib.import_module',
                        return_value=self._sdk_double(failing)), \
                    self.assertRaises(ExtractionFailure):
                import_openai_eval.extract(
                    lines, candidates, 'insurance-review-v1')
            self.assertEqual(
                [logger.disabled for logger in loggers], prior_disabled)
            self.assertEqual(
                logging.root.manager.disable, previous_global_disable)
            self.assertNotIn(sentinel, '\n'.join(records))
        finally:
            for logger, state in zip(loggers, previous):
                logger.removeHandler(handler)
                logger.disabled, logger.level, logger.propagate = state
