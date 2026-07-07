"""판촉물 도메인 직렬화 (dev/21 §4 API 계약).

설계사 공개:
  PromotionSampleImageSerializer   — 샘플 이미지 (목록 내 인라인)
  PromotionSampleListSerializer    — 샘플 목록 (primary_image 포함, form_fields 제외)
  PromotionSampleDetailSerializer  — 샘플 상세 (form_fields 포함 + 이미지 목록)
  PromotionOrderStatusLogSerializer — 상태 이력 (설계사 타임라인)
  PromotionOrderSerializer         — 주문 조회 (status_logs 인라인)
  PromotionOrderCreateSerializer   — 주문 생성 요청 (sample + form_response)

관리자 전용:
  AdminSampleWriteSerializer       — 샘플 등록·수정 (관리자)
  AdminOrderStatusPatchSerializer  — 상태 변경 + 관리자 메모 (PATCH)
  AdminOrderListSerializer         — 전체 주문 목록 (설계사 이메일 포함)
"""
from rest_framework import serializers

from .models import (
    PromotionOrder,
    PromotionOrderStatusLog,
    PromotionSample,
    PromotionSampleImage,
)


# ─── 샘플 이미지 ────────────────────────────────────────────────────

class PromotionSampleImageSerializer(serializers.ModelSerializer):
    url = serializers.URLField(source='image_url', read_only=True)

    class Meta:
        model = PromotionSampleImage
        fields = ['id', 'url', 'is_primary', 'sort_order']
        read_only_fields = fields


class PromotionSampleImageWriteSerializer(serializers.ModelSerializer):
    """관리자 이미지 추가."""
    class Meta:
        model = PromotionSampleImage
        fields = ['image_url', 'is_primary', 'sort_order']


# ─── 샘플 카탈로그 (설계사 공개) ─────────────────────────────────────

class PromotionSampleListSerializer(serializers.ModelSerializer):
    """샘플 목록용 — primary_image만 포함 (form_fields 제외, 데이터 경량화)."""
    primary_image = serializers.SerializerMethodField()

    class Meta:
        model = PromotionSample
        fields = [
            'id', 'name', 'category', 'description',
            'is_available', 'is_digital', 'primary_image', 'sort_order',
        ]
        read_only_fields = fields

    def get_primary_image(self, obj):
        img = obj.images.filter(is_primary=True).order_by('sort_order').first()
        if img is None:
            img = obj.images.order_by('sort_order').first()
        return img.image_url if img else None


class PromotionSampleDetailSerializer(serializers.ModelSerializer):
    """샘플 상세용 — 이미지 목록 + form_fields 포함."""
    images = PromotionSampleImageSerializer(many=True, read_only=True)

    class Meta:
        model = PromotionSample
        fields = [
            'id', 'name', 'category', 'description',
            'is_available', 'is_digital', 'images', 'form_fields', 'sort_order',
        ]
        read_only_fields = fields


# ─── 샘플 (관리자 쓰기) ──────────────────────────────────────────────

class AdminSampleWriteSerializer(serializers.ModelSerializer):
    """관리자 샘플 등록·수정."""
    class Meta:
        model = PromotionSample
        fields = [
            'name', 'category', 'description',
            'is_available', 'form_fields', 'sort_order',
        ]


# ─── 상태 이력 (설계사 타임라인) ─────────────────────────────────────

class PromotionOrderStatusLogSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()

    class Meta:
        model = PromotionOrderStatusLog
        fields = ['to_status', 'status_display', 'changed_at', 'note']
        read_only_fields = fields

    def get_status_display(self, obj):
        return obj.get_to_status_display()


# ─── 주문 (설계사) ────────────────────────────────────────────────────

class PromotionOrderSerializer(serializers.ModelSerializer):
    """주문 조회 — status_logs 인라인 (상세), sample 요약."""
    sample = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    status_logs = PromotionOrderStatusLogSerializer(many=True, read_only=True)

    class Meta:
        model = PromotionOrder
        fields = [
            'id', 'status', 'status_display',
            'sample', 'form_response',
            'admin_note', 'tracking_number', 'carrier',
            'status_logs', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_sample(self, obj):
        if obj.sample_id is None:
            return None
        return {'id': obj.sample_id, 'name': obj.sample.name if obj.sample else None}


class PromotionOrderListSerializer(serializers.ModelSerializer):
    """주문 목록용 — status_logs 제외 (경량화)."""
    sample = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PromotionOrder
        fields = [
            'id', 'status', 'status_display',
            'sample', 'admin_note', 'tracking_number',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_sample(self, obj):
        if obj.sample_id is None:
            return None
        return {'id': obj.sample_id, 'name': obj.sample.name if obj.sample else None}


class PromotionOrderCreateSerializer(serializers.Serializer):
    """주문 생성 요청 검증 (POST /promotion/orders/).

    required_fields 검증: sample.form_fields[].required=True 항목이
    form_response에 모두 있는지 서버사이드 확인 (FE 우회 방어).

    ★ `_` 접두 메타 키(2026-07-07, PM 지시): form_fields 정의에 없어도 통과.
      `_reply_email`  — 회신 받을 이메일(FE 필수, 기본값=계정 이메일). 키가 있으면 형식 검증.
      `_extra_request` — 추가 요청사항(선택 자유 텍스트, 검증 없음).
      (required 검증은 form_fields 목록만 돌므로 메타 키는 원래부터 비파괴 통과 —
       여기서는 이메일 형식만 추가로 확인한다.)
    """
    sample = serializers.PrimaryKeyRelatedField(
        queryset=PromotionSample.objects.filter(is_available=True),
        error_messages={
            'does_not_exist': '존재하지 않거나 주문 불가 상태인 샘플입니다.',
        },
    )
    form_response = serializers.JSONField(default=dict)

    def validate(self, data):
        sample: PromotionSample = data['sample']
        form_response: dict = data.get('form_response', {})

        # required 필드 서버사이드 검증
        missing = [
            f['label']
            for f in (sample.form_fields or [])
            if f.get('required') and f.get('key') not in form_response
        ]
        if missing:
            raise serializers.ValidationError(
                {'form_response': f'필수 항목 미입력: {", ".join(missing)}'}
            )

        # 메타 키 — 회신 이메일 형식 검증(키가 있을 때만; 빈 값도 형식 오류로 거절)
        if isinstance(form_response, dict) and '_reply_email' in form_response:
            try:
                serializers.EmailField().run_validation(form_response['_reply_email'])
            except serializers.ValidationError:
                raise serializers.ValidationError(
                    {'form_response': '회신 받을 이메일 주소를 확인해 주세요.'}
                )
        return data


# ─── 관리자 전용 ──────────────────────────────────────────────────────

class AdminOrderStatusPatchSerializer(serializers.Serializer):
    """PATCH /admin/promotion/orders/:id/status/ 요청 검증."""
    status = serializers.ChoiceField(choices=PromotionOrder.STATUS_CHOICES)
    admin_note = serializers.CharField(required=False, allow_blank=True)
    tracking_number = serializers.CharField(required=False, allow_blank=True)
    carrier = serializers.CharField(required=False, allow_blank=True)


class AdminOrderListSerializer(serializers.ModelSerializer):
    """관리자 주문 목록 — 설계사 이메일·샘플명 포함."""
    owner_email = serializers.SerializerMethodField()
    sample_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PromotionOrder
        fields = [
            'id', 'owner_email', 'sample_name', 'status', 'status_display',
            'admin_note', 'tracking_number', 'carrier',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_owner_email(self, obj):
        return obj.owner.email if obj.owner else None

    def get_sample_name(self, obj):
        return obj.sample.name if obj.sample else None
