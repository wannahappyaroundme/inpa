import json
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase, override_settings

from inpa.consultations.providers.anthropic_summary import (
    AnthropicConsultationSummarizer,
)
from inpa.consultations.providers.base import SummaryOutcomeUnknown
from inpa.consultations.summary_schema import (
    ANTHROPIC_SUMMARY_JSON_SCHEMA,
    ConsultationSummary,
    InvalidSummary,
    render_summary_memo,
)


def valid_payload():
    return {
        'consultation_core': ['월 납입액을 함께 확인함'],
        'customer_priorities': ['가족 보장을 중요하게 봄'],
        'items_to_confirm': ['보험료 금액 확인 필요'],
        'next_actions': ['다음 상담 날짜 확인'],
    }


class ConsultationSummarySchemaTests(SimpleTestCase):
    def test_rejects_extra_sections_and_oversized_body(self):
        with self.assertRaises(InvalidSummary):
            ConsultationSummary.from_payload({
                **valid_payload(),
                'recommendation': ['가입'],
            })
        with self.assertRaises(InvalidSummary):
            ConsultationSummary.from_payload({
                **valid_payload(),
                'consultation_core': ['가' * 301],
            })
        with self.assertRaises(InvalidSummary):
            ConsultationSummary.from_payload({
                **valid_payload(),
                'consultation_core': ['항목'] * 13,
            })

    def test_renders_exact_four_bullet_sections(self):
        summary = ConsultationSummary.from_payload(valid_payload())

        body = render_summary_memo(summary)

        self.assertIn('상담 핵심\n- 월 납입액을 함께 확인함', body)
        self.assertIn('고객이 중요하게 본 내용', body)
        self.assertIn('확인할 내용', body)
        self.assertIn('다음 할 일', body)
        self.assertLessEqual(len(body), 5_000)


@override_settings(
    ANTHROPIC_API_KEY='test-key',
    CONSULTATION_SUMMARY_MODEL='summary-model-from-env',
)
class AnthropicConsultationSummarizerTests(SimpleTestCase):
    def setUp(self):
        self.client = Mock()
        self.summarizer = AnthropicConsultationSummarizer(client=self.client)

    def _response(self, *, stop_reason='end_turn', payload=None):
        return SimpleNamespace(
            stop_reason=stop_reason,
            content=[
                SimpleNamespace(
                    type='text',
                    text=json.dumps(payload or valid_payload(), ensure_ascii=False),
                ),
            ],
            usage=SimpleNamespace(input_tokens=121, output_tokens=42),
            model='actual-summary-model',
        )

    def test_one_structured_call_returns_token_telemetry(self):
        self.client.messages.create.return_value = self._response()

        result = self.summarizer.summarize('[이름_1] 상담 내용')

        self.assertEqual(result.input_tokens, 121)
        self.assertEqual(result.output_tokens, 42)
        self.assertEqual(result.model, 'actual-summary-model')
        kwargs = self.client.messages.create.call_args.kwargs
        self.assertEqual(kwargs['model'], 'summary-model-from-env')
        self.assertEqual(
            kwargs['output_config']['format']['type'],
            'json_schema',
        )
        self.assertEqual(
            kwargs['output_config']['format']['schema'],
            ANTHROPIC_SUMMARY_JSON_SCHEMA,
        )
        self.assertNotIn('가입을 권유', render_summary_memo(result.summary))

    def test_refusal_and_max_tokens_are_rejected(self):
        for reason in ('refusal', 'max_tokens'):
            self.client.messages.create.return_value = self._response(
                stop_reason=reason,
            )
            with self.assertRaises(InvalidSummary):
                self.summarizer.summarize('가려진 상담 내용')

    def test_unknown_transport_outcome_is_not_retried(self):
        self.client.messages.create.side_effect = RuntimeError('network')

        with self.assertRaises(SummaryOutcomeUnknown):
            self.summarizer.summarize('가려진 상담 내용')

        self.client.messages.create.assert_called_once()
