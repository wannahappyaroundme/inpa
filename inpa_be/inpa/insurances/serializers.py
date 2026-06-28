"""보험/계산 시리얼라이저 (♻ foliio weapon/insurances/serializers.py 포팅).

calculate.py 가 의존하는 CustomerInsuranceSerializer 가 핵심. foliio 와의 차이:
  - 표준 담보 트리(AnalysisCategory/SubCategory/Detail)는 inpa.analysis.models 에 산다
    (foliio 는 insurances 한 곳에 몰아둠) → import 경로만 분리.
  - CustomerInsuranceSerializer.image: insurance.image (Insurance FK) 경유 — foliio 동일.
  - customer_name: customer__owner 격리 모델(소유자 전용)에서 고객명을 평면화.

가시성: 시리얼라이저 자체는 격리하지 않는다 — 격리는 ViewSet.get_queryset(customer__owner)
  이 책임진다(dev/02 §0). 여기서는 직렬화 형태만 정의.
"""
from rest_framework import serializers

from inpa.analysis.models import (
    AnalysisCategory, AnalysisDetail, AnalysisSubCategory,
)

from .models import (
    CustomerInsurance, CustomerInsuranceDetail, CustomerInsuranceRefundSchedule,
    Insurance, InsuranceCategory, InsuranceDetail, InsuranceSubCategory,
    InsuranceTag,
)


class InsuranceTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsuranceTag
        fields = "__all__"


class InsuranceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Insurance
        fields = "__all__"


class CustomerInsuranceRefundScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerInsuranceRefundSchedule
        fields = ['id', 'year', 'refund_amount']


class CustomerInsuranceDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerInsuranceDetail
        fields = "__all__"


class CustomerInsuranceManualSerializer(serializers.ModelSerializer):
    """수기 보험 등록(보유/제안) — OCR 없이 기본 정보만. 담보 트리 없이 환수레이더·요약용.

    회사 전용 필드는 모델에 없어 상품명에 포함(예 '삼성생명 무배당...'). portfolio_type
    1=보유 / 2=제안 만 허용(0=템플릿 금지). 격리는 ViewSet(customer__owner)이 책임.
    """
    class Meta:
        model = CustomerInsurance
        fields = ('id', 'name', 'insurance_type', 'portfolio_type',
                  'monthly_premiums', 'contract_date', 'expiry_date',
                  'contractor_name', 'insured_name', 'is_same_insured',
                  'payment_status', 'is_cancelled', 'cancelled_at', 'created_at')
        read_only_fields = ('id', 'created_at')

    def validate_portfolio_type(self, value):
        if value not in (1, 2):
            raise serializers.ValidationError('보유(1) 또는 제안(2)만 선택할 수 있어요.')
        return value


class CustomerInsuranceSerializer(serializers.ModelSerializer):
    """포트폴리오 기본정보 직렬화 (calculate.py 의존, ♻ foliio 무변경).

    image 는 연결된 Insurance(카탈로그) 이미지를 read-only 로 평면화한다(없으면 None).
    """
    image = serializers.ImageField(source="insurance.image", read_only=True)
    customer_name = serializers.SerializerMethodField()
    refund_schedule = serializers.SerializerMethodField()

    class Meta:
        model = CustomerInsurance
        fields = "__all__"

    def get_customer_name(self, instance):
        if instance.customer:
            return instance.customer.name
        return None

    def get_refund_schedule(self, instance):
        schedule = instance.refund_schedule.all()
        return CustomerInsuranceRefundScheduleSerializer(schedule, many=True).data


class CustomerInsuranceSerializerForDetail(serializers.ModelSerializer):
    """담보 케이스 목록까지 펼친 상세 직렬화 (♻ foliio 무변경)."""
    image = serializers.ImageField(source="insurance.image", read_only=True)
    case_list = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    refund_schedule = serializers.SerializerMethodField()

    class Meta:
        model = CustomerInsurance
        fields = "__all__"

    def get_case_list(self, instance):
        case_list = instance.case_list.all()
        return CustomerInsuranceDetailSerializer(case_list, many=True).data

    def get_customer_name(self, instance):
        if instance.customer:
            return instance.customer.name
        return None

    def get_refund_schedule(self, instance):
        schedule = instance.refund_schedule.all()
        return CustomerInsuranceRefundScheduleSerializer(schedule, many=True).data


class InsuranceDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsuranceDetail
        fields = "__all__"


class InsuranceSubCategorySerializer(serializers.ModelSerializer):
    detail_list = serializers.SerializerMethodField()

    class Meta:
        model = InsuranceSubCategory
        fields = "__all__"

    def get_detail_list(self, instance):
        detail_list = instance.details.all()
        return InsuranceDetailSerializer(detail_list, many=True).data


class InsuranceCategorySerializer(serializers.ModelSerializer):
    sub_category_list = serializers.SerializerMethodField()

    class Meta:
        model = InsuranceCategory
        fields = "__all__"

    def get_sub_category_list(self, instance):
        sub_category_list = instance.sub_categories.all()
        return InsuranceSubCategorySerializer(sub_category_list, many=True).data


# ── 표준 담보 트리 시리얼라이저 (inpa.analysis 모델 — 히트맵 트리/입력) ─────────
class AnalysisDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisDetail
        fields = "__all__"


class AnalysisSubCategorySerializer(serializers.ModelSerializer):
    detail_list = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisSubCategory
        fields = "__all__"

    def get_detail_list(self, instance):
        detail_list = instance.details.all()
        return AnalysisDetailSerializer(detail_list, many=True).data


class AnalysisCategorySerializer(serializers.ModelSerializer):
    sub_category_list = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisCategory
        fields = "__all__"

    def get_sub_category_list(self, instance):
        sub_category_list = instance.sub_categories.all()
        return AnalysisSubCategorySerializer(sub_category_list, many=True).data
