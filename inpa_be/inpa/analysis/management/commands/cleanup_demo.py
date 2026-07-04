"""프로드 [DEMO] 잔재 정리 명령 (LB#7 launch trust sweep — 1회성, 멱등).

Render Shell 에서 실행 예정: `python manage.py cleanup_demo`

하는 일 (필터는 데모 마커 2종으로만 — 그 밖의 데이터는 절대 건드리지 않는다):
  1) `@inpa.local` 이메일 사용자 전부 삭제 → CASCADE 로 소유 데이터(고객/보험/일정/알림 등) 정리.
     ★ 안전 가드: `profile.is_admin=True` 사용자는 이메일이 @inpa.local 이어도 절대 삭제 금지.
     ★ SET_NULL 잔존 방지(seed_demo._cleanup 과 동일 순서): 데모 고객 ConsentLog ·
       데모 owner PromotionOrder 는 user 삭제 전에 먼저 지운다(링크 끊기면 고아로 누적).
  2) 공유 테이블의 [DEMO] 마커 행 정리(seed_demo._cleanup 과 동일 필터·순서) — 프로드가
     과거 seed_demo 를 1회 돌린 흔적(공지/FAQ/게시글/판촉샘플/카탈로그/데모 정규화 코드 등)
     이 실사용자에게 보이는 것을 차단. 마커([DEMO] prefix / 데모 보험사 코드 대역) 밖은 불가침.
  3) `code` 가 `demo_` 로 시작하는 Plan:
     - 남은 Subscription 참조가 없으면 삭제 (Coupon 등 PROTECT 참조가 남아 있으면 비활성으로 폴백).
     - 참조가 남아 있으면 `is_active=False` → 공개 /billing/plans/ 노출 즉시 차단.
  4) 결과 카운트 출력.

seed_demo 자체는 수정하지 않는다(로컬 데모 용도 유지). 재실행해도 안전(멱등).
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.deletion import ProtectedError

from inpa.analysis.models import AnalysisCategory, ChartDetail, NormalizationDict, UnmatchedLog
from inpa.billing.models import Plan, Subscription
from inpa.boards.models import Faq, Notice, Post, Report
from inpa.customers.models import ConsentLog
from inpa.insurances.models import Insurance, InsuranceCategory
from inpa.promotion.models import PromotionOrder, PromotionSample

from .seed_demo import DEMO_CATALOG_TAG, DEMO_COMPANY_CODES, DEMO_REPORT_MARK

User = get_user_model()

# ★ 데모 마커 2종 — 이 두 필터 밖의 데이터는 이 명령이 절대 건드리지 못한다.
DEMO_EMAIL_DOMAIN = '@inpa.local'
DEMO_PLAN_CODE_PREFIX = 'demo_'


class Command(BaseCommand):
    help = ('프로드 [DEMO] 잔재 정리(멱등): @inpa.local 사용자 삭제(관리자 제외) + '
            'demo_ 요금제 삭제/비활성.')

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write('=== cleanup_demo 시작 ===')

        # ── 1) 데모 사용자 (@inpa.local) — is_admin 프로필은 절대 삭제 금지 ──
        demo_users = User.objects.filter(email__endswith=DEMO_EMAIL_DOMAIN)
        protected_admins = list(
            demo_users.filter(profile__is_admin=True).values_list('email', flat=True))
        deletable = demo_users.exclude(profile__is_admin=True)
        deletable_emails = list(deletable.values_list('email', flat=True))

        # SET_NULL 고아 방지 — user 삭제 전에 먼저 정리 (seed_demo._cleanup 동일 순서)
        consent_deleted, _ = ConsentLog.objects.filter(
            customer__owner__in=deletable).delete()
        promo_deleted, _ = PromotionOrder.objects.filter(
            owner__in=deletable).delete()

        users_deleted = len(deletable_emails)
        deletable.delete()

        for email in deletable_emails:
            self.stdout.write(f'  사용자 삭제: {email}')
        for email in protected_admins:
            self.stdout.write(self.style.WARNING(
                f'  사용자 보호(관리자): {email} — is_admin 이라 삭제하지 않음'))

        # ── 2) 공유 테이블 [DEMO] 마커 행 — seed_demo._cleanup 동일 필터·순서 ──
        # (판촉주문은 sample=SET_NULL 이라 샘플 삭제 전에 마커 링크로 먼저 정리)
        PromotionOrder.objects.filter(
            sample__name__startswith=DEMO_CATALOG_TAG).delete()
        shared_deleted = 0
        for label, qs in (
            ('판촉물 샘플', PromotionSample.objects.filter(name__startswith=DEMO_CATALOG_TAG)),
            ('게시글', Post.objects.filter(title__startswith=DEMO_CATALOG_TAG)),
            ('공지', Notice.objects.filter(title__startswith=DEMO_CATALOG_TAG)),
            ('FAQ', Faq.objects.filter(question__startswith=DEMO_CATALOG_TAG)),
            ('신고', Report.objects.filter(detail__startswith=DEMO_REPORT_MARK)),
            ('미매칭 로그(데모 코드)', UnmatchedLog.objects.filter(company__in=list(DEMO_COMPANY_CODES))),
            ('정규화 사전(데모 코드)', NormalizationDict.objects.filter(company__in=list(DEMO_COMPANY_CODES))),
            ('보험 카탈로그', Insurance.objects.filter(name__startswith=DEMO_CATALOG_TAG)),
            ('보험 카탈로그 분류', InsuranceCategory.objects.filter(name__startswith=DEMO_CATALOG_TAG)),
            ('표준 트리(데모)', AnalysisCategory.objects.filter(name__startswith=DEMO_CATALOG_TAG)),
            ('차트(데모)', ChartDetail.objects.filter(name__startswith=DEMO_CATALOG_TAG)),
        ):
            n, _ = qs.delete()
            if n:
                self.stdout.write(f'  공유 정리: {label} {n}건')
            shared_deleted += n

        # ── 3) 데모 요금제 (code=demo_*) ────────────────────────────────
        plans_deleted = 0
        plans_deactivated = 0
        for plan in Plan.objects.filter(code__startswith=DEMO_PLAN_CODE_PREFIX):
            if Subscription.objects.filter(plan=plan).exists():
                if plan.is_active:
                    plan.is_active = False
                    plan.save(update_fields=['is_active'])
                plans_deactivated += 1
                self.stdout.write(f'  요금제 비활성: {plan.code} (구독 참조 잔존)')
                continue
            try:
                plan.delete()
                plans_deleted += 1
                self.stdout.write(f'  요금제 삭제: {plan.code}')
            except ProtectedError:
                # Coupon 등 PROTECT 참조가 남은 예외 케이스 → 비활성으로 폴백
                plan.is_active = False
                plan.save(update_fields=['is_active'])
                plans_deactivated += 1
                self.stdout.write(f'  요금제 비활성: {plan.code} (PROTECT 참조 잔존)')

        self.stdout.write(self.style.SUCCESS('=== cleanup_demo 완료 ==='))
        self.stdout.write(f'  삭제 사용자      : {users_deleted}명 '
                          f'(CASCADE 부속: ConsentLog {consent_deleted} · 판촉주문 {promo_deleted} 선정리)')
        self.stdout.write(f'  보호된 관리자    : {len(protected_admins)}명')
        self.stdout.write(f'  공유 [DEMO] 정리 : {shared_deleted}건')
        self.stdout.write(f'  삭제 요금제      : {plans_deleted}개')
        self.stdout.write(f'  비활성 요금제    : {plans_deactivated}개')
