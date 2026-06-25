"""고객 도메인 시리얼라이저 (dev/12 §5 API 계약).

owner는 절대 클라이언트 입력으로 받지 않는다 — ViewSet의 perform_create(OwnedQuerySetMixin)가
request.user를 주입한다. 하위 라우트(태그/가족/병력/동의)도 부모 customer를 URL에서 잡아 격리한다.
"""
from rest_framework import serializers

from .models import (
    ConsentLog, Customer, CustomerMedicalHistory, CustomerTag, FamilyMember,
    PlannerBaseline, compute_insurance_age,
)


class CustomerTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerTag
        fields = ('id', 'label', 'color', 'created_at')
        read_only_fields = ('id', 'created_at')


class FamilyMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = FamilyMember
        fields = ('id', 'customer', 'relation', 'name', 'birth_day', 'gender', 'memo',
                  'created_at', 'updated_at')
        read_only_fields = ('id', 'customer', 'created_at', 'updated_at')


class CustomerMedicalHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerMedicalHistory
        fields = ('id', 'customer', 'disease_name', 'diagnosed_at', 'is_inpatient',
                  'treatment_content', 'hospital_name', 'memo', 'created_at', 'updated_at')
        read_only_fields = ('id', 'customer', 'created_at', 'updated_at')


class ConsentLogSerializer(serializers.ModelSerializer):
    """append-only — 생성만. 철회는 별도 액션(revoke)에서 revoked_at 기록."""
    class Meta:
        model = ConsentLog
        fields = ('id', 'customer', 'scope', 'subject', 'purpose', 'doc_version',
                  'agreed_at', 'ip', 'revoked_at', 'revoke_ip')
        # subject은 서버가 지정(설계사가 customer_self로 위조 못하게 read_only).
        read_only_fields = ('id', 'customer', 'subject', 'agreed_at', 'revoked_at', 'revoke_ip')


class PlannerBaselineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlannerBaseline
        fields = ('id', 'coverage_key', 'product_group', 'age_band', 'gender',
                  'recommend_min', 'recommend_max', 'unit', 'baseline_source',
                  'preset_origin', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


class _CustomerComputedMethods:
    """List/Detail 공용 계산 필드 get_* 메서드 (SerializerMethodField 선언은 각 시리얼라이저 본문).

    - insurance_age: 보험나이(상령일 — 만나이 +6개월 반올림).
    - job_risk_grade / job_name: 직업 위험등급(1/2/3/9급)·직업명.
    - marketing_consent: 'agreed'(유효 동의) | 'revoked'(철회) | 'none'(기록 없음).
      consent_logs 는 ViewSet에서 prefetch — 캐시 순회로 N+1 회피.
    """
    def get_insurance_age(self, obj):
        return compute_insurance_age(obj.birth_day)

    def get_job_risk_grade(self, obj):
        return obj.job_code.risk_grade if obj.job_code_id else None

    def get_job_name(self, obj):
        return obj.job_code.name if obj.job_code_id else None

    def get_marketing_consent(self, obj):
        log = next((c for c in obj.consent_logs.all()
                    if c.scope == ConsentLog.SCOPE_MARKETING), None)
        if log is None:
            return 'none'
        return 'revoked' if log.revoked_at else 'agreed'


class CustomerListSerializer(_CustomerComputedMethods, serializers.ModelSerializer):
    """목록 카드용 경량 직렬화 (dev/12 §5.1)."""
    tags = CustomerTagSerializer(many=True, read_only=True)
    family_count = serializers.IntegerField(source='family_members.count', read_only=True)
    insurance_age = serializers.SerializerMethodField()
    job_risk_grade = serializers.SerializerMethodField()
    marketing_consent = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = ('id', 'name', 'gender', 'birth_day', 'mobile_phone_number',
                  'consent_overseas_at', 'color', 'tags', 'family_count',
                  'sales_stage', 'share_token', 'created_at',
                  'last_contacted_at', 'is_favorite', 'is_pinned',
                  'insurance_age', 'job_risk_grade', 'marketing_consent')


class CustomerSerializer(_CustomerComputedMethods, serializers.ModelSerializer):
    """상세/생성/수정 (dev/12 §5.3·§5.4).

    tags는 쓰기 시 태그 id 배열(tag_ids)로 받고, 읽기 시 중첩 객체로 내린다.
    병력은 중첩 직렬화하되 공유뷰가 아니라 본인 상세에서만 노출(serializer 계층 분리).
    """
    tags = CustomerTagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, required=False, source='tags',
        queryset=CustomerTag.objects.all())
    family_members = FamilyMemberSerializer(many=True, read_only=True)
    medical_histories = CustomerMedicalHistorySerializer(many=True, read_only=True)
    insurance_age = serializers.SerializerMethodField()
    job_risk_grade = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()
    marketing_consent = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = ('id', 'name', 'mobile_phone_number', 'birth_day', 'gender', 'job_code',
                  'memo', 'color', 'is_agree_term', 'consent_overseas_at', 'sales_stage',
                  'share_token', 'share_expires_at', 'share_sent_at', 'user_view_at',
                  'tags', 'tag_ids', 'family_members', 'medical_histories',
                  'last_contacted_at', 'is_favorite', 'is_pinned', 'business_card',
                  'insurance_age', 'job_risk_grade', 'job_name', 'marketing_consent',
                  'created_at', 'updated_at')
        read_only_fields = ('id', 'share_token', 'consent_overseas_at', 'share_sent_at',
                            'user_view_at', 'created_at', 'updated_at')

    def validate_tag_ids(self, value):
        """다른 설계사의 태그를 붙이지 못하게 owner 격리 — 본인 태그만 허용."""
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            for tag in value:
                if tag.owner_id != request.user.id:
                    raise serializers.ValidationError('본인 소유 태그만 지정할 수 있습니다.')
        return value
