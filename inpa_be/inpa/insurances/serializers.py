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
from .import_validation import STANDARD_COVERAGE_PATHS, validate_draft


def _manual_policy_payload(values):
    def manual(value):
        return {
            'value': value,
            'evidence_line_ids': [],
            'state': 'manual',
        }

    return {
        'carrier_name': manual(None),
        'company_code': manual(values.get('company')),
        'insurance_type': manual(
            {1: 'life', 2: 'loss'}.get(values.get('insurance_type'))),
        'product_name': manual(values.get('name')),
        'contract_date': manual(values.get('contract_date')),
        'expiry_date': manual(values.get('expiry_date')),
        'monthly_premium': manual(values.get('monthly_premiums')),
    }


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


class CaseFeeSerializer(serializers.ModelSerializer):
    """담보별 요금(사실) — 판정 없음."""
    detail_name = serializers.CharField(source='detail.name', read_only=True)
    is_renewal = serializers.SerializerMethodField()

    class Meta:
        model = CustomerInsuranceDetail
        fields = ('detail_name', 'premium', 'payment_period_type', 'is_renewal',
                  'assurance_amount', 'total_renewal_premium', 'total_non_renewal_premium')
        read_only_fields = fields

    def get_is_renewal(self, obj):
        return obj.is_renewal_case


class InsuranceFeeSerializer(serializers.ModelSerializer):
    """보험별 요금 요약 + 담보별 요금(case_fees). 수기입력 보험은 case_fees=[]."""
    case_fees = CaseFeeSerializer(source='case_list', many=True, read_only=True)

    class Meta:
        model = CustomerInsurance
        fields = ('id', 'name', 'insurance_type', 'portfolio_type',
                  'monthly_premiums', 'monthly_renewal_premium',
                  'monthly_non_renewal_premium', 'monthly_earned_premium',
                  'total_premiums', 'total_renewal_premium',
                  'total_non_renewal_premium', 'total_earned_premium',
                  'review_status', 'analysis_included', 'confirmed_at',
                  'case_fees')
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.has_mixed_case_premiums():
            for field in instance.COVERAGE_PREMIUM_COMPOSITION_FIELDS:
                data[field] = None
        return data


class CustomerInsuranceManualSerializer(serializers.ModelSerializer):
    """수기 보험 등록(보유/제안) — OCR 없이 기본 정보만. 담보 트리 없이 환수레이더·요약용.

    회사 전용 필드는 모델에 없어 상품명에 포함(예 '삼성생명 무배당...'). portfolio_type
    1=보유 / 2=제안 만 허용(0=템플릿 금지). 격리는 ViewSet(customer__owner)이 책임.
    """
    class Meta:
        model = CustomerInsurance
        fields = ('id', 'name', 'insurance_type', 'portfolio_type',
                  'monthly_premiums', 'monthly_renewal_premium',
                  'monthly_non_renewal_premium', 'monthly_earned_premium',
                  'payment_period_type', 'payment_period',
                  'warranty_period_type', 'warranty_period',
                  'contract_date', 'expiry_date',
                  'contractor_name', 'insured_name', 'is_same_insured',
                  'payment_status', 'is_cancelled', 'cancelled_at',
                  'review_status', 'analysis_included', 'data_version',
                  'confirmation_source', 'confirmed_at',
                  'review_exclusion_reason', 'created_at')
        read_only_fields = (
            'id', 'review_status', 'analysis_included',
            'confirmation_source', 'confirmed_at',
            'review_exclusion_reason', 'created_at')

    def validate(self, attrs):
        protected = {
            'review_status', 'analysis_included', 'confirmation_source',
            'confirmed_at', 'review_exclusion_reason'}
        attempted = protected.intersection(getattr(self, 'initial_data', {}))
        if attempted:
            raise serializers.ValidationError({
                field: '이 항목은 수정할 수 없어요.'
                for field in sorted(attempted)
            })
        if self.instance is None and 'data_version' in attrs:
            raise serializers.ValidationError({
                'data_version': '새 보험에는 버전을 지정할 수 없어요.'})
        if self.instance is not None and 'data_version' not in attrs:
            raise serializers.ValidationError({
                'data_version': '최신 보험 내용을 확인해 주세요.'})
        if self.instance is None and 'insurance_type' not in attrs:
            raise serializers.ValidationError({
                'insurance_type': '보험 종류를 선택해 주세요.'})

        values = {
            field: getattr(self.instance, field, None)
            for field in (
                'company', 'insurance_type', 'name', 'contract_date',
                'expiry_date', 'monthly_premiums')
        }
        values.update(attrs)
        policy_validation = validate_draft([], [], {
            'policy': _manual_policy_payload(values),
            'coverage_rows': [],
        }, allow_manual=True)
        field_map = {'monthly_premium': 'monthly_premiums'}
        policy_errors = {}
        for issue in policy_validation.issues:
            if issue.scope != 'policy' or issue.field is None:
                continue
            field = field_map.get(issue.field, issue.field)
            policy_errors[field] = '보험 기본정보를 다시 확인해 주세요.'
        for field in (
                'monthly_renewal_premium',
                'monthly_non_renewal_premium',
                'monthly_earned_premium'):
            value = values.get(field)
            if value is not None and value < 0:
                policy_errors[field] = '0 이상의 숫자를 입력해 주세요.'
        for field in ('payment_period', 'warranty_period'):
            value = attrs.get(
                field,
                getattr(self.instance, field, None)
                if self.instance is not None else None)
            if value is not None and value <= 0:
                policy_errors[field] = '1 이상의 숫자를 입력해 주세요.'
        if policy_errors:
            raise serializers.ValidationError(policy_errors)
        return attrs

    def update(self, instance, validated_data):
        validated_data.pop('data_version', None)
        return super().update(instance, validated_data)

    def validate_portfolio_type(self, value):
        if value not in (1, 2):
            raise serializers.ValidationError('보유(1) 또는 제안(2)만 선택할 수 있어요.')
        return value


class _StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if hasattr(data, 'keys'):
            unknown = set(data.keys()) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({
                    field: '이 항목은 수정할 수 없어요.'
                    for field in sorted(unknown)
                })
        return super().to_internal_value(data)


class ManualCoverageWriteSerializer(_StrictSerializer):
    PERIOD_UNITS = ('years', 'age', 'lifetime')

    data_version = serializers.IntegerField(min_value=1)
    raw_name = serializers.CharField(max_length=200)
    assurance_amount = serializers.IntegerField(min_value=0, allow_null=True)
    premium = serializers.IntegerField(min_value=0, allow_null=True)
    is_renewal = serializers.BooleanField(allow_null=True)
    renewal_period = serializers.IntegerField(
        min_value=1, allow_null=True, required=False)
    payment_period = serializers.IntegerField(
        min_value=1, allow_null=True, required=False)
    payment_period_unit = serializers.ChoiceField(
        choices=PERIOD_UNITS, allow_null=True, required=False)
    warranty_period = serializers.IntegerField(
        min_value=1, allow_null=True, required=False)
    warranty_period_unit = serializers.ChoiceField(
        choices=PERIOD_UNITS, allow_null=True, required=False)
    standard_category = serializers.CharField(max_length=80)
    standard_subcategory = serializers.CharField(max_length=80)
    standard_detail_name = serializers.CharField(max_length=80)

    def validate(self, attrs):
        path = (
            attrs.get('standard_category'),
            attrs.get('standard_subcategory'),
            attrs.get('standard_detail_name'),
        )
        if path not in STANDARD_COVERAGE_PATHS:
            raise serializers.ValidationError({
                'standard_detail_name': '표준 담보 위치를 다시 선택해 주세요.'})
        return attrs


class ManualCoveragePatchSerializer(_StrictSerializer):
    data_version = serializers.IntegerField(min_value=1)
    raw_name = serializers.CharField(max_length=200, required=False)
    assurance_amount = serializers.IntegerField(
        min_value=0, allow_null=True, required=False)
    premium = serializers.IntegerField(
        min_value=0, allow_null=True, required=False)
    is_renewal = serializers.BooleanField(allow_null=True, required=False)
    renewal_period = serializers.IntegerField(
        min_value=1, allow_null=True, required=False)
    payment_period = serializers.IntegerField(
        min_value=1, allow_null=True, required=False)
    payment_period_unit = serializers.ChoiceField(
        choices=ManualCoverageWriteSerializer.PERIOD_UNITS,
        allow_null=True, required=False)
    warranty_period = serializers.IntegerField(
        min_value=1, allow_null=True, required=False)
    warranty_period_unit = serializers.ChoiceField(
        choices=ManualCoverageWriteSerializer.PERIOD_UNITS,
        allow_null=True, required=False)
    standard_category = serializers.CharField(max_length=80, required=False)
    standard_subcategory = serializers.CharField(max_length=80, required=False)
    standard_detail_name = serializers.CharField(max_length=80, required=False)

    def validate(self, attrs):
        if len(attrs) == 1:
            raise serializers.ValidationError('수정할 담보 항목을 입력해 주세요.')
        mapping = {
            'standard_category', 'standard_subcategory',
            'standard_detail_name'}
        supplied = mapping.intersection(attrs)
        if supplied and supplied != mapping:
            raise serializers.ValidationError(
                '표준 담보 위치는 세 항목을 함께 선택해 주세요.')
        if supplied:
            path = tuple(attrs[field] for field in (
                'standard_category', 'standard_subcategory',
                'standard_detail_name'))
            if path not in STANDARD_COVERAGE_PATHS:
                raise serializers.ValidationError({
                    'standard_detail_name': '표준 담보 위치를 다시 선택해 주세요.'})
        return attrs


class ManualCoverageDeleteSerializer(_StrictSerializer):
    data_version = serializers.IntegerField(min_value=1)


class _LiteralTrueField(serializers.Field):
    default_error_messages = {
        'literal_true': '보험 기본정보와 담보 내용을 직접 확인해 주세요.',
    }

    def to_internal_value(self, data):
        if data is not True:
            self.fail('literal_true')
        return True

    def to_representation(self, value):
        return value is True


class ManualInsuranceConfirmSerializer(_StrictSerializer):
    data_version = serializers.IntegerField(min_value=1)
    planner_confirmed_contents = _LiteralTrueField()


class ManualInsuranceExcludeSerializer(_StrictSerializer):
    data_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=500, allow_blank=False)


class ManualCoverageReadSerializer(serializers.ModelSerializer):
    is_renewal = serializers.SerializerMethodField()
    payment_period_unit = serializers.SerializerMethodField()
    warranty_period_unit = serializers.SerializerMethodField()
    standard_category = serializers.SerializerMethodField()
    standard_subcategory = serializers.SerializerMethodField()
    standard_detail_name = serializers.SerializerMethodField()
    standard_detail_id = serializers.SerializerMethodField()
    review_status = serializers.SerializerMethodField()

    class Meta:
        model = CustomerInsuranceDetail
        fields = (
            'id', 'raw_name', 'assurance_amount', 'premium', 'is_renewal',
            'renewal_period', 'payment_period', 'payment_period_unit',
            'warranty_period', 'warranty_period_unit', 'standard_category',
            'standard_subcategory', 'standard_detail_name',
            'standard_detail_id', 'mapping_source', 'review_status',
            'source_page', 'source_line_start', 'source_line_end',
            'source_candidate_ids', 'evidence_line_ids', 'review_reason',
            'confirmed_at', 'created_at', 'updated_at')
        read_only_fields = fields

    def _standard(self, obj):
        cache_name = '_manual_review_standard_detail'
        if hasattr(obj, cache_name):
            return getattr(obj, cache_name)
        details = list(
            obj.effective_analysis_details().select_related(
                'sub_category__category').order_by('pk')[:2])
        detail = details[0] if len(details) == 1 else None
        setattr(obj, cache_name, detail)
        return detail

    def get_standard_category(self, obj):
        detail = self._standard(obj)
        if detail is None:
            return None
        return detail.sub_category.category.name.removeprefix('[표준]')

    def get_standard_subcategory(self, obj):
        detail = self._standard(obj)
        return detail.sub_category.name if detail is not None else None

    def get_standard_detail_name(self, obj):
        detail = self._standard(obj)
        return detail.name if detail is not None else None

    def get_standard_detail_id(self, obj):
        detail = self._standard(obj)
        return detail.pk if detail is not None else None

    def get_review_status(self, obj):
        return 'confirmed' if obj.confirmed_at is not None else 'needs_review'

    def get_is_renewal(self, obj):
        return obj.is_renewal_case

    def get_payment_period_unit(self, obj):
        if obj.payment_period_type == 4:
            return 'lifetime'
        return 'age' if obj.payment_period_type == 2 else 'years'

    def get_warranty_period_unit(self, obj):
        return {1: 'age', 2: 'years', 4: 'lifetime'}.get(
            obj.warranty_period_type)


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
