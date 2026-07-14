"""기본 요금제(free·plus·manager·super) 시드 + 구독 없는 사용자 백필 — 멱등.

배포 startCommand에서 매번 실행(seed_normalization 등과 동일 패턴).
  - Plan(code='free'/'plus'/'manager'/'super')이 없으면 생성. 있으면 보존(관리자 Django Admin
    수정값 유지). get_or_create라 가격·한도는 '최초 생성 시'에만 기본값 적용 → 재배포가 admin
    변경을 덮지 않는다 — ★단, 아래 한도 정합(2026-07-09) 블록은 예외(설명 참조).
  - 구독(Subscription) 없는 기존 사용자에게 free 활성 구독 생성.

★ 배경(why): billing/signals.py(User post_save)가 free Plan 부재 시 구독 생성을 스킵하고
  경고만 남겼다. 프로드에 free Plan이 시드된 적 없으면 가입자에게 구독이 없어,
  유료 전환(FREE_TIER_UNLIMITED=False) 시 한도 계산이 깨진다. 이 명령으로 정상화.

★ 가격 확정(2026-07-07, PM 재료): Plus 월 19,900원(VAT 별도) · Super 월 39,900원(VAT 별도).
  price_krw는 VAT 별도 금액. 기존 프로드 plus placeholder(29000)의 19900 전환은
  migrations/0005(조건부 데이터 마이그레이션)가 담당 — 이 명령은 CREATE 기본값만 제공.

★ 요금표 한도 정합(2026-07-09, spec pricing-limits-align, PM 확정 (A)): new.inpa.kr 랜딩
  요금표(brand-story-sections.tsx, 변경 없음 = SSOT)에 적힌 한도가 billing이 실제로 강제하는
  숫자와 정확히 일치해야 한다. limit_ocr/limit_ai_compare/limit_analysis/limit_customer 4개
  필드는 '랜딩 정합'이 목적이므로, 이번만은 get_or_create의 CREATE-only 원칙을 깨고 **기존
  행도 아래 _QUOTA_CORRECTIONS 값으로 명시 보정**한다(price_krw/display_name/description/
  limit_promotion/can_use_team/is_active는 손대지 않음 — 관리자 수정값 그대로 보존).
  limit_customer는 이번에 신설된 컬럼이라 전 플랜에 처음부터 세팅된다.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from inpa.billing.models import Plan, Subscription

PLUS_DESCRIPTION = (
    '월 19,900원 (VAT 별도). OCR 100/AI비교 50/AI분석 50/고객추가 30/판촉 100 월 한도.'
)
MANAGER_DESCRIPTION = (
    '월 19,900원 (VAT 별도) · 관리자(팀장·지점장·지사장) 전용. '
    'Plus 전체 기능 + 팀원 인사 관리 · 팀원 개별 실적 관리 · 팀 전체 실적 관리.'
)
SUPER_DESCRIPTION = '월 39,900원 (VAT 별도). 모든 월 한도 무제한(null).'

# ★ 랜딩 요금표 정합(spec 2026-07-09) — 4개 한도 필드만. limit_promotion은 랜딩 미표기라 불변
# (get_or_create defaults만 적용, 기존 행 보정 대상 아님).
_QUOTA_CORRECTIONS = {
    'free': {'limit_ocr': 5, 'limit_ai_compare': 1, 'limit_analysis': 5, 'limit_customer': 5},
    'plus': {'limit_ocr': 100, 'limit_ai_compare': 50, 'limit_analysis': 50, 'limit_customer': 30},
    'manager': {'limit_ocr': 100, 'limit_ai_compare': 50, 'limit_analysis': 50, 'limit_customer': 30},
    'super': {'limit_ocr': None, 'limit_ai_compare': None, 'limit_analysis': None, 'limit_customer': None},
}


def _correct_quota(plan):
    """_QUOTA_CORRECTIONS의 값으로 기존 행도 명시 보정(랜딩 정합 목적, 이 4필드만)."""
    corrections = _QUOTA_CORRECTIONS.get(plan.code)
    if not corrections:
        return
    changed = [f for f, v in corrections.items() if getattr(plan, f) != v]
    if not changed:
        return
    for f in changed:
        setattr(plan, f, corrections[f])
    plan.save(update_fields=changed)


class Command(BaseCommand):
    help = '기본 요금제(free·plus·manager·super) 시드 + 구독 없는 사용자에게 free 구독 백필(멱등).'

    @transaction.atomic
    def handle(self, *args, **options):
        free, free_created = Plan.objects.get_or_create(
            code='free',
            defaults={
                'display_name': '무료',
                'price_krw': 0,
                'price_annual_krw': 0,
                'description': '베타 무료 플랜. OCR 5/AI비교 1/AI분석 5/고객추가 5/판촉 5 월 한도.',
                'limit_ocr': 5, 'limit_ai_compare': 1,
                'limit_analysis': 5, 'limit_promotion': 5, 'limit_customer': 5,
            },
        )
        plus, plus_created = Plan.objects.get_or_create(
            code='plus',
            defaults={
                'display_name': 'Plus',
                'price_krw': 19900,  # VAT 별도 (확정 2026-07-07)
                'price_annual_krw': 199000,  # 월가×10 = 12개월을 10개월가로 (VAT 별도)
                'description': PLUS_DESCRIPTION,
                'limit_ocr': 100, 'limit_ai_compare': 50,
                'limit_analysis': 50, 'limit_promotion': 100, 'limit_customer': 30,
            },
        )
        manager, manager_created = Plan.objects.get_or_create(
            code='manager',
            defaults={
                'display_name': 'Manager',
                'price_krw': 19900,  # VAT 별도 (확정 2026-07-07)
                'price_annual_krw': 199000,  # 월가×10 (VAT 별도)
                'description': MANAGER_DESCRIPTION,
                'limit_ocr': 100, 'limit_ai_compare': 50,
                'limit_analysis': 50, 'limit_promotion': 100, 'limit_customer': 30,
                'can_use_team': True,  # 팀 기능 게이트(spec 2026-07-09) — manager 전용 capability
            },
        )
        # get_or_create의 defaults는 신규 생성 시에만 적용된다. can_use_team 필드가 나중에
        # 도입됐으므로(2026-07-09) 이미 존재하는 manager 행은 기본값 False로 남아있을 수 있다.
        # 다른 필드(가격·한도)는 관리자 수정값을 보존하지만, 이 필드만은 "manager=팀 가능"이
        # 항상 참이어야 하므로 재시드 시 명시적으로 보정한다.
        if not manager.can_use_team:
            manager.can_use_team = True
            manager.save(update_fields=['can_use_team'])
        superp, super_created = Plan.objects.get_or_create(
            code='super',
            defaults={
                'display_name': 'Super',
                'price_krw': 39900,  # VAT 별도 (확정 2026-07-07)
                'price_annual_krw': 399000,  # 월가×10 (VAT 별도)
                'description': SUPER_DESCRIPTION,
                # null = 무제한 sentinel (models.Plan.get_limit)
                'limit_ocr': None, 'limit_ai_compare': None,
                'limit_analysis': None, 'limit_promotion': None, 'limit_customer': None,
            },
        )

        # ★ 요금표 한도 정합(2026-07-09) — 기존 행도 4개 한도 필드를 명시 보정.
        #   (limit_ocr/limit_ai_compare/limit_analysis/limit_customer만. limit_promotion·
        #   price_krw·description 등은 손대지 않음 — _correct_quota 참조.)
        #   ★ SeedMarker 가드(§7): 이 정합은 랜딩과 맞추는 '1회성 baseline' 이다. 매 배포마다
        #     돌면 관리자가 Django Admin 에서 재배포 없이 한도를 조정한 값을 되돌린다(Plan
        #     docstring 위배). 마커로 QUOTA_ALIGN_VERSION 당 1회만 실행 → 이후 배포는 skip,
        #     관리자 편집 보존. 랜딩 숫자가 또 바뀌면 QUOTA_ALIGN_VERSION 을 bump 한다.
        from inpa.analysis.models import SeedMarker
        _QUOTA_ALIGN_KEY = 'seed_billing_quota_align'
        _QUOTA_ALIGN_VERSION = 'v1-2026-07-09'
        _marker = SeedMarker.objects.filter(key=_QUOTA_ALIGN_KEY).first()
        if not (_marker and _marker.version == _QUOTA_ALIGN_VERSION):
            for plan in (free, plus, manager, superp):
                _correct_quota(plan)
            SeedMarker.objects.update_or_create(
                key=_QUOTA_ALIGN_KEY, defaults={'version': _QUOTA_ALIGN_VERSION})

        # ★ 연 요금 백필(2026-07-15) — price_annual_krw 이 비어 있는(null) 기존 유료 플랜 행만
        #   월가×10 으로 채운다. 연구독 = 12개월을 10개월가로(2개월 무료). 관리자가 Django Admin
        #   에서 설정한 값(non-null)은 보존하므로 마커 없이도 멱등(한 번 채워지면 다시 안 건드림).
        #   무료 플랜은 연 상품이 없어 대상 아님.
        _annual = {'plus': 199000, 'manager': 199000, 'super': 399000}
        for plan in (plus, manager, superp):
            if plan.price_annual_krw is None:
                plan.price_annual_krw = _annual[plan.code]
                plan.save(update_fields=['price_annual_krw'])

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
