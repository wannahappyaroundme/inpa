"""기본 요금제(free·plus·super) 시드 + 구독 없는 사용자 백필 — 멱등.

배포 startCommand에서 매번 실행(seed_normalization 등과 동일 패턴).
  - Plan(code='free'/'plus'/'super')이 없으면 생성. 있으면 보존(관리자 Django Admin 수정값 유지).
    get_or_create라 가격·한도는 '최초 생성 시'에만 기본값 적용 → 재배포가 admin 변경을 덮지 않음.
  - 구독(Subscription) 없는 기존 사용자에게 free 활성 구독 생성.

★ 배경(why): billing/signals.py(User post_save)가 free Plan 부재 시 구독 생성을 스킵하고
  경고만 남겼다. 프로드에 free Plan이 시드된 적 없으면 가입자에게 구독이 없어,
  유료 전환(FREE_TIER_UNLIMITED=False) 시 한도 계산이 깨진다. 이 명령으로 정상화.

★ 가격 확정(2026-07-07, PM 재료): Plus 월 19,900원(VAT 별도) · Super 월 39,900원(VAT 별도).
  price_krw는 VAT 별도 금액. 기존 프로드 plus placeholder(29000)의 19900 전환은
  migrations/0005(조건부 데이터 마이그레이션)가 담당 — 이 명령은 CREATE 기본값만 제공.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from inpa.billing.models import Plan, Subscription

PLUS_DESCRIPTION = '월 19,900원 (VAT 별도). OCR 200/AI비교 100/AI분석 200/판촉 100 월 한도.'
MANAGER_DESCRIPTION = (
    '월 19,900원 (VAT 별도) · 관리자(팀장·지점장·지사장) 전용. '
    'Plus 전체 기능 + 팀원 인사 관리 · 팀원 개별 실적 관리 · 팀 전체 실적 관리.'
)
SUPER_DESCRIPTION = '월 39,900원 (VAT 별도). 모든 월 한도 무제한(null).'


class Command(BaseCommand):
    help = '기본 요금제(free·plus·super) 시드 + 구독 없는 사용자에게 free 구독 백필(멱등).'

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
                'price_krw': 19900,  # VAT 별도 (확정 2026-07-07)
                'description': PLUS_DESCRIPTION,
                'limit_ocr': 200, 'limit_ai_compare': 100,
                'limit_analysis': 200, 'limit_promotion': 100,
            },
        )
        manager, manager_created = Plan.objects.get_or_create(
            code='manager',
            defaults={
                'display_name': 'Manager',
                'price_krw': 19900,  # VAT 별도 (확정 2026-07-07)
                'description': MANAGER_DESCRIPTION,
                'limit_ocr': 200, 'limit_ai_compare': 100,
                'limit_analysis': 200, 'limit_promotion': 100,
            },
        )
        superp, super_created = Plan.objects.get_or_create(
            code='super',
            defaults={
                'display_name': 'Super',
                'price_krw': 39900,  # VAT 별도 (확정 2026-07-07)
                'description': SUPER_DESCRIPTION,
                # null = 무제한 sentinel (models.Plan.get_limit)
                'limit_ocr': None, 'limit_ai_compare': None,
                'limit_analysis': None, 'limit_promotion': None,
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
            f'plus({"신규" if plus_created else "기존"}) · '
            f'manager({"신규" if manager_created else "기존"}) · '
            f'super({"신규" if super_created else "기존"}) · 구독 백필 {backfilled}명. '
            f'(가격·한도 변경은 Django Admin)'
        ))
