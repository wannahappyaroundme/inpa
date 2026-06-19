"""billing 도메인 직렬화 (dev/23 §4 API 계약).

PlanSerializer          — GET /api/v1/billing/plans/ 공개 응답
SubscriptionSerializer  — 구독 상태 조회 (본인/관리자)
UsageItemSerializer     — 단일 action 사용량 항목
BillingUsageSerializer  — GET /api/v1/billing/usage/ 전체 응답
AdminSubscriptionPatchSerializer — PATCH /api/v1/admin/billing/subscription/<user_id>/
"""
from rest_framework import serializers

from .models import Plan, Subscription, UsageMeter


class PlanSerializer(serializers.ModelSerializer):
    """요금제 공개 정보 (공개 읽기 — AllowAny)."""

    class Meta:
        model = Plan
        fields = [
            'code',
            'display_name',
            'price_krw',
            'description',
            'limit_ocr',
            'limit_ai_compare',
            'limit_analysis',
            'limit_promotion',
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


class AdminSubscriptionPatchSerializer(serializers.Serializer):
    """PATCH /api/v1/admin/billing/subscription/<user_id>/ 요청 검증 (dev/23 §4.3).

    plan_code / status / expires_at 부분 전송 허용.
    """
    plan_code = serializers.ChoiceField(choices=['free', 'plus'], required=False)
    status = serializers.ChoiceField(
        choices=['active', 'cancelled', 'expired', 'trial'], required=False
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
