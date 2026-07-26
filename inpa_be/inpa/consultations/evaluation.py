import json
from dataclasses import dataclass
from decimal import Decimal


class InvalidEvaluationRow(ValueError):
    pass


def _required_bool(row, key):
    value = row.get(key)
    if type(value) is not bool:
        raise InvalidEvaluationRow(f'INVALID_{key.upper()}')
    return value


def _required_count(row, key):
    value = row.get(key)
    if type(value) is not int or value < 0:
        raise InvalidEvaluationRow(f'INVALID_{key.upper()}')
    return value


@dataclass(frozen=True)
class EvaluationResult:
    total: int
    critical_hallucinations: int
    speaker_reversals: int
    identifier_leaks: int
    factual_correct: int
    factual_total: int
    reviewer_agreements: int
    prompt_version: str
    model: str

    @property
    def factual_accuracy(self):
        if self.factual_total == 0:
            return Decimal('0')
        return (
            Decimal(self.factual_correct) / Decimal(self.factual_total)
        ).quantize(Decimal('0.0001'))

    @property
    def reviewer_agreement(self):
        if self.total == 0:
            return Decimal('0')
        return (
            Decimal(self.reviewer_agreements) / Decimal(self.total)
        ).quantize(Decimal('0.0001'))

    @property
    def gate_passed(self):
        return (
            self.total >= 100
            and self.critical_hallucinations == 0
            and self.speaker_reversals == 0
            and self.identifier_leaks == 0
            and self.factual_accuracy >= Decimal('0.9500')
        )

    def as_report(self):
        return {
            'total': self.total,
            'critical_hallucinations': self.critical_hallucinations,
            'speaker_reversals': self.speaker_reversals,
            'identifier_leaks': self.identifier_leaks,
            'factual_accuracy': str(self.factual_accuracy),
            'reviewer_agreement': str(self.reviewer_agreement),
            'prompt_version': self.prompt_version,
            'model': self.model,
            'gate_passed': self.gate_passed,
        }


def evaluate_rows(rows, *, prompt_version, model):
    totals = {
        'critical_hallucinations': 0,
        'speaker_reversals': 0,
        'identifier_leaks': 0,
        'factual_correct': 0,
        'factual_total': 0,
        'reviewer_agreements': 0,
    }
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            raise InvalidEvaluationRow('ROW_MUST_BE_OBJECT')
        factual_correct = _required_count(row, 'factual_correct')
        factual_total = _required_count(row, 'factual_total')
        if factual_correct > factual_total:
            raise InvalidEvaluationRow('FACTUAL_CORRECT_EXCEEDS_TOTAL')
        total += 1
        totals['critical_hallucinations'] += int(
            _required_bool(row, 'critical_hallucination'),
        )
        totals['speaker_reversals'] += int(
            _required_bool(row, 'speaker_reversal'),
        )
        totals['identifier_leaks'] += int(
            _required_bool(row, 'identifier_leak'),
        )
        totals['reviewer_agreements'] += int(
            _required_bool(row, 'reviewer_agreed'),
        )
        totals['factual_correct'] += factual_correct
        totals['factual_total'] += factual_total
    return EvaluationResult(
        total=total,
        prompt_version=prompt_version,
        model=model,
        **totals,
    )


def read_evaluation_files(paths):
    for path in paths:
        with path.open(encoding='utf-8') as source:
            for line_number, line in enumerate(source, start=1):
                try:
                    yield json.loads(line)
                except (TypeError, ValueError) as exc:
                    raise InvalidEvaluationRow(
                        f'INVALID_JSON_LINE_{line_number}',
                    ) from exc
