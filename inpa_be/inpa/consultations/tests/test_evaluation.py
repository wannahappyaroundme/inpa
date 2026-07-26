from decimal import Decimal

from django.test import SimpleTestCase

from inpa.consultations.evaluation import (
    InvalidEvaluationRow,
    evaluate_rows,
)


def reviewed_row(**overrides):
    return {
        'case_id': 'private-case-id',
        'critical_hallucination': False,
        'speaker_reversal': False,
        'identifier_leak': False,
        'factual_correct': 19,
        'factual_total': 20,
        'reviewer_agreed': True,
        **overrides,
    }


class ConsultationSummaryEvaluationTests(SimpleTestCase):
    def test_gate_requires_100_cases_zero_critical_and_95_percent_accuracy(self):
        result = evaluate_rows(
            [reviewed_row() for _ in range(100)],
            prompt_version='prompt-v1',
            model='model-from-env',
        )

        self.assertTrue(result.gate_passed)
        self.assertEqual(result.factual_accuracy, Decimal('0.9500'))
        report = result.as_report()
        self.assertNotIn('case_id', report)
        self.assertNotIn('transcript', report)
        self.assertEqual(report['model'], 'model-from-env')

    def test_any_identifier_leak_closes_gate(self):
        rows = [reviewed_row() for _ in range(99)]
        rows.append(reviewed_row(identifier_leak=True))

        result = evaluate_rows(
            rows,
            prompt_version='prompt-v1',
            model='model-from-env',
        )

        self.assertFalse(result.gate_passed)

    def test_invalid_review_counts_fail_closed_without_echoing_content(self):
        with self.assertRaisesRegex(
            InvalidEvaluationRow,
            'FACTUAL_CORRECT_EXCEEDS_TOTAL',
        ):
            evaluate_rows(
                [reviewed_row(factual_correct=21)],
                prompt_version='prompt-v1',
                model='model-from-env',
            )
