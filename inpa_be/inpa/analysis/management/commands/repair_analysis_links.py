"""손상 복구 — 끊어진 InsuranceDetail.analysis_detail M2M 링크 재연결 (LB-1 repair).

배경: 과거 seed_normalization이 부팅마다 [표준] 트리를 delete-recreate 하면서
CASCADE로 InsuranceDetail.analysis_detail M2M 링크가 끊겼다(스캔 고객 보유금액이
히트맵에서 0으로 집계). 이 커맨드는 CustomerInsuranceDetail이 실제로 사용하는
카탈로그 InsuranceDetail 중 analysis_detail 링크가 0개인 행을 찾아, OCR 저장 시와
동일한 해석 경로(coverage_bridge.resolve_std_detail — 카탈로그 cat/sub/det 이름)로
재해석해 다시 연결한다. 새 매칭 로직을 만들지 않음(기존 브리지 그대로 재사용).

사용법:
    python manage.py repair_analysis_links            # dry-run (기본): 보고만
    python manage.py repair_analysis_links --apply    # 실제 재연결

멱등: 이미 연결된 행은 후보에서 빠지고, .add()는 중복을 만들지 않는다.
배포 후 Render Shell에서 1회 실행(PM 런북): python manage.py repair_analysis_links --apply
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from inpa.insurances.coverage_bridge import resolve_std_detail
from inpa.insurances.models import InsuranceDetail


class Command(BaseCommand):
    help = (
        '고객 스캔이 사용하는 카탈로그 담보 중 표준 담보(analysis_detail) 링크가 '
        '끊긴 행을 기존 브리지로 재연결합니다. 기본 dry-run, --apply 로 실제 반영.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='실제로 M2M 링크를 재연결 (기본은 dry-run 보고만)')

    @transaction.atomic
    def handle(self, *args, **options):
        apply_mode = options['apply']
        mode = 'APPLY' if apply_mode else 'DRY-RUN'
        self.stdout.write(f'=== repair_analysis_links ({mode}) 시작 ===')

        # 고객 케이스(CustomerInsuranceDetail)가 쓰는 카탈로그 담보 중 링크 0개
        candidates = (
            InsuranceDetail.objects
            .filter(customerinsurancedetail__isnull=False,
                    analysis_detail__isnull=True)
            .select_related('sub_category__category')
            .distinct()
        )

        relinked = 0
        unresolved = 0
        for det in candidates:
            cat_name = det.sub_category.category.name
            sub_name = det.sub_category.name
            std = resolve_std_detail(cat_name, sub_name, det.name)
            if std is None:
                unresolved += 1
                self.stdout.write(
                    f'  [미해석] {cat_name}/{sub_name}/{det.name} (pk={det.pk}) '
                    '— 브리지 맵 미대응(의도적 미연결 포함)')
                continue
            relinked += 1
            if apply_mode:
                det.analysis_detail.add(std)
                self.stdout.write(
                    f'  [재연결] {cat_name}/{sub_name}/{det.name} (pk={det.pk}) '
                    f'→ [표준] {std.name} (pk={std.pk})')
            else:
                self.stdout.write(
                    f'  [연결예정] {cat_name}/{sub_name}/{det.name} (pk={det.pk}) '
                    f'→ [표준] {std.name} (pk={std.pk})')

        self.stdout.write(self.style.SUCCESS(
            f'=== repair_analysis_links 완료 ({mode}) ==='))
        self.stdout.write(
            f'  후보 {relinked + unresolved}건 / '
            f'{"재연결" if apply_mode else "연결예정"} {relinked}건 / '
            f'미해석 {unresolved}건')
        if not apply_mode and relinked:
            self.stdout.write('  실제 반영: python manage.py repair_analysis_links --apply')
