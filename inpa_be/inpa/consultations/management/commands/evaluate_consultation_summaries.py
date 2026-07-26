import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inpa.consultations.evaluation import (
    InvalidEvaluationRow,
    evaluate_rows,
    read_evaluation_files,
)


class Command(BaseCommand):
    help = 'Aggregate the private consultation summary gold-set review.'

    def handle(self, *args, **options):
        private_root = (
            Path(settings.BASE_DIR) / 'private' / 'consultation-eval'
        ).resolve()
        paths = sorted(private_root.glob('*.jsonl'))
        if not paths:
            raise CommandError(
                'private/consultation-eval/*.jsonl 평가 파일을 확인해 주세요.',
            )
        if any(path.resolve().parent != private_root for path in paths):
            raise CommandError('평가 파일 경로를 확인해 주세요.')
        try:
            result = evaluate_rows(
                read_evaluation_files(paths),
                prompt_version=settings.CONSULTATION_SUMMARY_PROMPT_VERSION,
                model=settings.CONSULTATION_SUMMARY_MODEL,
            )
        except InvalidEvaluationRow as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                result.as_report(),
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
