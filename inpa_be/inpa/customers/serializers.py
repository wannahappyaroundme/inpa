"""고객 도메인 시리얼라이저 (dev/12 §5 API 계약).

owner는 절대 클라이언트 입력으로 받지 않는다 — ViewSet의 perform_create(OwnedQuerySetMixin)가
request.user를 주입한다. 하위 라우트(태그/가족/병력/동의)도 부모 customer를 URL에서 잡아 격리한다.
"""
from rest_framework import serializers

from .models import (
    ConsentLog, Customer, CustomerMedicalHistory, CustomerTag, FamilyMember,
    PlannerBaseline,
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


class CustomerListSerializer(serializers.ModelSerializer):
    """목록 카드용 경량 직렬화 (dev/12 §5.1)."""
    tags = CustomerTagSerializer(many=True, read_only=True)
    family_count = serializers.IntegerField(source='family_members.count', read_only=True)

    class Meta:
        model = Customer
        fields = ('id', 'name', 'gender', 'birth_day', 'mobile_phone_number',
                  'consent_overseas_at', 'color', 'tags', 'family_count',
                  'sales_stage', 'share_token', 'created_at')


class CustomerSerializer(serializers.ModelSerializer):
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

    class Meta:
        model = Customer
        fields = ('id', 'name', 'mobile_phone_number', 'birth_day', 'gender', 'job_code',
                  'memo', 'color', 'is_agree_term', 'consent_overseas_at', 'sales_stage',
                  'share_token', 'share_expires_at', 'share_sent_at', 'user_view_at',
                  'tags', 'tag_ids', 'family_members', 'medical_histories',
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
