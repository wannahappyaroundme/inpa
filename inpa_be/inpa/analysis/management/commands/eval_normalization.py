"""골든셋 정규화 정확도 리포트 (운영/PM 확인용, 리포트 전용 — CI 게이트는 아님).

CI 게이트는 `inpa.analysis.tests.GoldenSetGateTests` 가 담당한다(정확도 회귀 방지선
+ 앵커 100% 통과). 이 커맨드는 그 숫자를 사람이 읽는 리포트로 보여줄 뿐이며,
render startCommand 에는 넣지 않는다(배포를 이 리포트로 막지 않음).

  PYTHONPATH=<inpa_be> python3 manage.py eval_normalization [--verbose]
"""
from django.core.management.base import BaseCommand

from inpa.analysis.golden_eval import GOLDEN_SET_MIN_ACCURACY, evaluate_golden_set


class Command(BaseCommand):
    help = '골든셋(NORMALIZATION_V0 + 함정 앵커) 대비 정규화 키워드 매처 정확도 리포트.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose', action='store_true',
            help='실패 항목 전체 출력(기본은 상위 20건만)')

    def handle(self, *args, **options):
        result = evaluate_golden_set()
        verbose = options['verbose']

        self.stdout.write(
            f"=== 골든셋 정규화 정확도: {result['accuracy']:.4f} "
            f"({result['passed']}/{result['total']}) — 기준선 {GOLDEN_SET_MIN_ACCURACY:.4f} ==="
        )
        if result['accuracy'] >= GOLDEN_SET_MIN_ACCURACY:
            self.stdout.write(self.style.SUCCESS('기준선 통과'))
        else:
            self.stdout.write(self.style.WARNING(
                '기준선 미달 — 정규화 코드(COVERAGE_KEYWORDS/PARSER_TO_STD/STANDARD_TREE) '
                '변경 회귀 여부 확인 필요'))

        self.stdout.write(
            f"앵커(반드시 통과): {result['anchor_passed']}/{result['anchor_total']}"
        )
        if result['anchor_failures']:
            self.stdout.write(self.style.ERROR(
                f"앵커 실패 {len(result['anchor_failures'])}건 — 실제 매처 버그일 가능성이 높음"))
            for f in result['anchor_failures']:
                self.stdout.write(
                    f"  [앵커실패] company={f['company']} raw_name={f['raw_name']!r} "
                    f"기대={f['expected']!r} 실제={f['got']!r}")

        failures = result['failures'] if verbose else result['failures'][:20]
        if failures:
            label = f"{len(result['failures'])}건 전체" if verbose else f"상위 {len(failures)}건(전체 {len(result['failures'])}건)"
            self.stdout.write(f'실패 목록({label}, --verbose 로 전체 출력):')
            for f in failures:
                self.stdout.write(
                    f"  [{f['company']}] {f['raw_name']!r} → 기대 {f['expected']!r} / 실제 {f['got']!r}")

        # 리포트 커맨드 — 항상 exit 0 (게이트는 tests.GoldenSetGateTests 가 담당).
