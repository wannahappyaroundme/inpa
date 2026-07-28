"""billing 도메인 직렬화 (dev/23 §4 API 계약).

PlanSerializer          — GET /api/v1/billing/plans/ 공개 응답
SubscriptionSerializer  — 구독 상태 조회 (본인/관리자)
UsageItemSerializer     — 단일 action 사용량 항목
BillingUsageSerializer  — GET /api/v1/billing/usage/ 전체 응답
AdminSubscriptionPatchSerializer — PATCH /api/v1/admin/billing/subscription/<user_id>/
"""
from rest_framework import serializers

from .models import (
    ManualBenefitReview,
    Plan,
    Subscription,
    UsageMeter,
)


class PlanSerializer(serializers.ModelSerializer):
    """요금제 공개 정보 (공개 읽기 — AllowAny)."""

    class Meta:
        model = Plan
        fields = [
            'code',
            'display_name',
            'price_krw',
            'price_annual_krw',
            'description',
            'limit_ocr',
            'limit_ai_compare',
            'limit_analysis',
            'limit_promotion',
            'limit_customer',
            'is_active',
        ]
        read_only_fields = fields


class SubscriptionSerializer(serializers.ModelSerializer):
    """구독 상태 (조회 전용). plan 요약 포함."""

    plan_code = serializers.CharField(source='plan.code', read_only=True)
    plan_display_name = serializers.CharField(source='plan.display_name', read_only=True)
    plan_price_krw = serializers.IntegerField(source='plan.price_krw', read_only=True)

    class Meta:
        model = Subscription
        fields = [
            'plan_code',
            'plan_display_name',
            'plan_price_krw',
            'status',
            'billing_cycle',
            'started_at',
            'expires_at',
        ]
        read_only_fields = fields


class UsageItemSerializer(serializers.Serializer):
    """단일 action 사용량 항목 (GET /billing/usage/ 배열 원소)."""

    action = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()
    limit = serializers.IntegerField(allow_null=True)
    remaining = serializers.IntegerField(allow_null=True)


class BillingUsageSerializer(serializers.Serializer):
    """GET /api/v1/billing/usage/ 전체 응답 (dev/23 §4.1)."""

    plan = serializers.DictField()          # {code, display_name, price_krw}
    subscription = serializers.DictField()  # {status, expires_at}
    year_month = serializers.CharField()
    usage = UsageItemSerializer(many=True)


class CouponRedeemSerializer(serializers.Serializer):
    """POST /api/v1/billing/coupons/redeem/ 요청 — 설계사가 쿠폰 코드를 입력."""
    code = serializers.CharField(max_length=32, trim_whitespace=True)


class RecurringCouponPreflightSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32, trim_whitespace=True)


class PhoneVerificationRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(
        max_length=40,
        trim_whitespace=True,
    )


class PhoneVerificationConfirmSerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()
    phone = serializers.CharField(
        max_length=40,
        trim_whitespace=True,
    )
    code = serializers.RegexField(
        regex=r'^\d{6}$',
        max_length=6,
        min_length=6,
    )


class ManualBenefitReviewRequestSerializer(serializers.Serializer):
    contact_email = serializers.EmailField(max_length=254)
    reason = serializers.CharField(
        max_length=500,
        trim_whitespace=True,
        min_length=1,
    )

    def validate(self, attrs):
        unknown = set(self.initial_data) - {
            'contact_email',
            'reason',
        }
        if unknown:
            raise serializers.ValidationError(
                '연락 이메일과 확인 사유만 입력해 주세요.',
            )
        return attrs


class ManualBenefitReviewSerializer(serializers.ModelSerializer):
    phone_masked = serializers.SerializerMethodField()

    class Meta:
        model = ManualBenefitReview
        fields = [
            'id',
            'phone_masked',
            'contact_email',
            'reason',
            'status',
            'decision_reason',
            'created_at',
            'decided_at',
            'consumed_at',
        ]
        read_only_fields = fields

    def get_phone_masked(self, obj):
        return f'010-****-{obj.phone_last4}'


class AdminBenefitReviewDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=['approved', 'rejected'],
    )
    reason = serializers.CharField(
        max_length=500,
        trim_whitespace=True,
        min_length=1,
    )


class CardRegistrationStartSerializer(serializers.Serializer):
    claim_id = serializers.UUIDField()
    initial_consent_version = serializers.CharField(max_length=40)
    device_type = serializers.ChoiceField(
        choices=['pc', 'mobile'], default='mobile')


class CardRegistrationCompleteSerializer(serializers.Serializer):
    state = serializers.CharField(max_length=2000)
    authorization_id = serializers.CharField(max_length=60)
    shop_order_no = serializers.CharField(max_length=40)


class FirstChargeReconfirmationSerializer(serializers.Serializer):
    first_charge_consent_version = serializers.CharField(max_length=40)


class BillingNoticeDeviceSerializer(serializers.Serializer):
    device_id = serializers.UUIDField()


class AdminSubscriptionPatchSerializer(serializers.Serializer):
    """PATCH /api/v1/admin/billing/subscription/<user_id>/ 요청 검증 (dev/23 §4.3).

    plan_code / status / expires_at 부분 전송 허용.
    """
    plan_code = serializers.ChoiceField(choices=['free', 'plus', 'manager', 'super'], required=False)
    status = serializers.ChoiceField(
        choices=['active', 'cancelled', 'expired', 'trial'], required=False
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
