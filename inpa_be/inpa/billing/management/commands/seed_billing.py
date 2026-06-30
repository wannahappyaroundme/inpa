"""기본 요금제(free·plus) 시드 + 구독 없는 사용자 백필 — 멱등.

배포 startCommand에서 매번 실행(seed_normalization 등과 동일 패턴).
  - Plan(code='free'/'plus')이 없으면 생성. 있으면 보존(관리자 Django Admin 수정값 유지).
    get_or_create라 가격·한도는 '최초 생성 시'에만 기본값 적용 → 재배포가 admin 변경을 덮지 않음.
  - 구독(Subscription) 없는 기존 사용자에게 free 활성 구독 생성.

★ 배경(why): billing/signals.py(User post_save)가 free Plan 부재 시 구독 생성을 스킵하고
  경고만 남겼다. 프로드에 free Plan이 시드된 적 없으면 가입자에게 구독이 없어,
  유료 전환(FREE_TIER_UNLIMITED=False) 시 한도 계산이 깨진다. 이 명령으로 정상화.
  가격·한도는 미확정 → 생성 후 Django Admin(/admin/)에서 조정.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from inpa.billing.models import Plan, Subscription


class Command(BaseCommand):
    help = '기본 요금제(free·plus) 시드 + 구독 없는 사용자에게 free 구독 백필(멱등).'

    @transaction.atomic
    def handle(self, *args, **options):
        free, free_created = Plan.objects.get_or_create(
            code='free',
            defaults={
                'display_name': '무료',
                'price_krw': 0,
                'description': '베타 무료 플랜. OCR 10/AI비교 5/AI분석 10/판촉 5 월 한도.',
                'limit_ocr': 10, 'limit_ai_compare': 5,
                'limit_analysis': 10, 'limit_promotion': 5,
            },
        )
        plus, plus_created = Plan.objects.get_or_create(
            code='plus',
            defaults={
                'display_name': 'Plus',
                'price_krw': 29000,  # 미확정 placeholder — Django Admin에서 조정.
                'description': 'Plus 플랜. 가격·한도는 Django Admin에서 조정(출시 전 확정).',
                'limit_ocr': 200, 'limit_ai_compare': 100,
                'limit_analysis': 200, 'limit_promotion': 100,
            },
        )

        User = get_user_model()
        backfilled = 0
        for user in User.objects.filter(subscription__isnull=True).iterator():
            _, created = Subscription.objects.get_or_create(
                user=user, defaults={'plan': free, 'status': 'active'},
            )
            if created:
                backfilled += 1

        self.stdout.write(self.style.SUCCESS(
            f'seed_billing 완료 — free({"신규" if free_created else "기존"}) · '
            f'plus({"신규" if plus_created else "기존"}) · 구독 백필 {backfilled}명. '
            f'(가격·한도 변경은 Django Admin)'
        ))
