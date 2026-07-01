"""billing Django Admin 등록 (dev/23 §6).

관리자가 코드 배포 없이 한도·가격·구독을 직접 수정한다:
  - PlanAdmin.list_editable: limit_* 필드 인라인 편집
  - SubscriptionAdmin: 결제 확인 후 status=active, plan=Plus 로 수동 변경
  - UsageMeterAdmin: 월별 코호트 분析, 테스트 데이터 수동 삭제(CS 처리)
"""
from django.contrib import admin

from .models import ClaudeApiLog, Coupon, CouponRedemption, Plan, Subscription, UsageMeter


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    """요금제 정의 — 한도·가격 직접 편집 (dev/23 §6.1).

    코드 배포 없이 Admin에서 limit 필드 수정 → 전체 해당 플랜 설계사 즉시 반영.
    is_active=False 시 신규 Subscription 불가.
    """
    list_display = [
        'code', 'display_name', 'price_krw',
        'limit_ocr', 'limit_ai_compare',
        'limit_analysis', 'limit_promotion',
        'is_active', 'updated_at',
    ]
    list_editable = [
        'limit_ocr', 'limit_ai_compare',
        'limit_analysis', 'limit_promotion',
        'price_krw', 'is_active',
    ]
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['price_krw']


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """구독 상태 — Plus 수동 활성화 (dev/23 §6.2 결제 확인 흐름).

    결제 확인 → list_editable에서 plan=Plus, status=active 로 변경 → 저장.
    """
    list_display = [
        'user', 'plan', 'status',
        'started_at', 'expires_at', 'cancelled_at',
    ]
    list_filter = ['plan', 'status']
    search_fields = ['user__email']
    list_editable = ['status', 'plan']
    raw_id_fields = ['user']
    readonly_fields = ['started_at', 'cancelled_at', 'pg_subscription_id']
    ordering = ['-started_at']


@admin.register(UsageMeter)
class UsageMeterAdmin(admin.ModelAdmin):
    """사용량 미터 — 월별 코호트 분析, 초기화(행 삭제) (dev/23 §6.2).

    UsageMeter 행 삭제 = 해당 month count 초기화 (CS·테스트 처리).
    과거 행 영구 보존 원칙 — 실제 삭제는 관리자 재량으로 제한.
    """
    list_display = ['user', 'action', 'year_month', 'count', 'updated_at']
    list_filter = ['action', 'year_month']
    search_fields = ['user__email']
    ordering = ['-year_month', '-count']
    readonly_fields = ['updated_at']


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    """무료 쿠폰 발급 — 코드 배포 없이 Admin에서 생성(코드 비우면 자동 생성).

    발급: '추가' → 요금제(Plus)·부여 기간(일)·최대 사용 수·유효기한 지정 → 저장 → 코드 복사해 배포.
    """
    list_display = [
        'code', 'plan', 'duration_days',
        'redeemed_count', 'max_redemptions',
        'is_active', 'expires_at', 'note', 'created_at',
    ]
    list_filter = ['is_active', 'plan']
    search_fields = ['code', 'note']
    readonly_fields = ['redeemed_count', 'created_at']
    ordering = ['-created_at']


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    """쿠폰 사용 기록 — 읽기 전용(감사). 누가 어떤 코드를 언제·언제까지 부여받았는지."""
    list_display = ['coupon', 'user', 'granted_until', 'redeemed_at']
    search_fields = ['coupon__code', 'user__email']
    readonly_fields = ['coupon', 'user', 'granted_until', 'redeemed_at']
    ordering = ['-redeemed_at']

    def has_add_permission(self, request):
        return False


@admin.register(ClaudeApiLog)
class ClaudeApiLogAdmin(admin.ModelAdmin):
    """Claude API 비용 로그 — 관리자 전용 읽기 (dev/02 §14.2).

    owner FK 없음(운영 로그). 월 예산 캡 집계·모델별 비용·캐시 효율 모니터링.
    추가/수정 불가(시스템 기록), 삭제만 관리자 재량.
    """
    list_display = [
        'created_at', 'action', 'model',
        'input_tokens', 'output_tokens',
        'cache_read_input_tokens', 'cache_creation_input_tokens',
    ]
    list_filter = ['action', 'model']
    ordering = ['-created_at']
    readonly_fields = [
        'action', 'model', 'input_tokens', 'output_tokens',
        'cache_read_input_tokens', 'cache_creation_input_tokens', 'created_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
