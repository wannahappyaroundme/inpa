import json

from django.core.management.base import BaseCommand, CommandError

from inpa.insurances.extraction_eval import (
    EvalContractError,
    run_private_evaluation,
)
from inpa.insurances.extraction_eval_adapters import build_live_runtime


class Command(BaseCommand):
    help = 'Run aggregate-only private insurance extraction evaluation.'

    def add_arguments(self, parser):
        parser.add_argument('--dataset-root', required=True)
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--split', required=True)
        parser.add_argument('--compare', default='legacy,review')
        parser.add_argument('--fail-on-release-gates', action='store_true')

    def handle(self, *args, **options):
        try:
            report, exit_code = run_private_evaluation(
                options['dataset_root'],
                options['manifest'],
                split=options['split'],
                compare=options['compare'],
                runtime_factory=build_live_runtime,
                fail_on_release_gates=options['fail_on_release_gates'],
            )
        except EvalContractError as exc:
            raise CommandError(exc.code, returncode=2) from None
        except Exception:
            raise CommandError(
                'E_EXTRACTION_EVAL_RUNTIME', returncode=1) from None

        self.stdout.write(json.dumps(
            report.to_public_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(',', ':'),
        ))
        if exit_code == 1:
            raise CommandError(
                'E_EXTRACTION_EVAL_GATE', returncode=1) from None
