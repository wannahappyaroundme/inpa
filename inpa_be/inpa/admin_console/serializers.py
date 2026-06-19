"""admin_console 직렬화기 (dev/19 §5 API 계약).

모든 시리얼라이저는 IsAdmin 권한 아래에서만 사용됨.
★ PII 마스킹 원칙 (dev/19 §7):
  - ConsentLog 고객명은 '홍**' 형태 마스킹.
  - admin도 원칙 동일 적용.
★ planner_baseline neutral 강제: 담보 보유 금액(사실)만 표기, 판정어 금지.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from inpa.accounts.models import Profile
from inpa.analysis.models import AnalysisDetail, NormalizationDict, UnmatchedLog
from inpa.billing.models import Plan, Subscription, UsageMeter
from inpa.boards.models import (
    Faq,
    Inquiry,
    InquiryReply,
    Notice,
    Report,
)
from inpa.customers.models import ConsentLog, Customer
from inpa.promotion.models import PromotionOrder, PromotionOrderStatusLog

User = get_user_model()


# ─── 설계사 관리 ─────────────────────────────────────────────────────

class AdminProfileSerializer(serializers.ModelSerializer):
    """설계사 Profile 상세 (admin 전용 읽기)."""
    class Meta:
        model = Profile
        fields = [
            'affiliation', 'agent_type', 'license_self_declared', 'license_no',
            'career_years', 'onboarding_completed_at',
            'is_admin', 'is_dormant', 'dormant_at', 'will_delete_at',
            'email_verified_at', 'tos_agreed_at', 'pp_agreed_at', 'marketing_agreed_at',
            'ref_code',
        ]
        read_only_fields = fields


class AdminUserListSerializer(serializers.ModelSerializer):
    """설계사 목록 행 — 검색·필터 결과용."""
    affiliation = serializers.SerializerMethodField()
    plan_code = serializers.SerializerMethodField()
    plan_display = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()
    is_dormant = serializers.SerializerMethodField()
    will_delete_at = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'date_joined', 'last_login',
            'affiliation', 'plan_code', 'plan_display', 'subscription_status',
            'is_dormant', 'will_delete_at',
        ]

    def get_affiliation(self, obj):
        profile = getattr(obj, 'profile', None)
        return profile.affiliation if profile else None

    def get_plan_code(self, obj):
        sub = getattr(obj, 'subscription', None)
        return sub.plan.code if sub else 'free'

    def get_plan_display(self, obj):
        sub = getattr(obj, 'subscription', None)
        return sub.plan.display_name if sub else 'Free'

    def get_subscription_status(self, obj):
        sub = getattr(obj, 'subscription', None)
        return sub.status if sub else None

    def get_is_dormant(self, obj):
        profile = getattr(obj, 'profile', None)
        return profile.is_dormant if profile else False

    def get_will_delete_at(self, obj):
        profile = getattr(obj, 'profile', None)
        return profile.will_delete_at if profile else None


class AdminUserDetailSerializer(serializers.ModelSerializer):
    """설계사 상세 (admin 전용)."""
    profile = AdminProfileSerializer(read_only=True)
    plan_code = serializers.SerializerMethodField()
    plan_display = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()
    usage_this_month = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'is_active', 'date_joined', 'last_login',
            'profile', 'plan_code', 'plan_display', 'subscription_status',
            'usage_this_month',
        ]

    def get_plan_code(self, obj):
        sub = getattr(obj, 'subscription', None)
        return sub.plan.code if sub else 'free'

    def get_plan_display(self, obj):
        sub = getattr(obj, 'subscription', None)
        return sub.plan.display_name if sub else 'Free'

    def get_subscription_status(self, obj):
        sub = getattr(obj, 'subscription', None)
        return sub.status if sub else None

    def get_usage_this_month(self, obj):
        year_month = UsageMeter.current_month()
        meters = UsageMeter.objects.filter(user=obj, year_month=year_month)
        return {m.action: m.count for m in meters}


class AdminSubscriptionUpdateSerializer(serializers.Serializer):
    """요금제 변경 (admin용)."""
    plan_code = serializers.ChoiceField(choices=Plan.PLAN_CODE)
    status = serializers.ChoiceField(choices=Subscription.STATUS, required=False)


# ─── 대시보드 ──────────────────────────────────────────────────────────

class DashboardSerializer(serializers.Serializer):
    """운영 지표 집계 응답 (사실 카운트만, 판정어 금지)."""
    # 오늘 현황
    today_new_users = serializers.IntegerField()
    today_new_orders = serializers.IntegerField()
    open_inquiries = serializers.IntegerField()
    pending_reports = serializers.IntegerField()
    # 누적 지표
    total_users = serializers.IntegerField()
    total_customers = serializers.IntegerField()
    # 요금제 분포 (판정어 금지 — 수치만)
    plan_distribution = serializers.DictField(child=serializers.IntegerField())
    # 미처리 항목
    pending_orders = serializers.IntegerField()
    unresolved_unmatched = serializers.IntegerField()


# ─── 1:1 문의 ─────────────────────────────────────────────────────────

class AdminInquiryListSerializer(serializers.ModelSerializer):
    """문의 목록 (admin용)."""
    owner_email = serializers.CharField(source='owner.email', read_only=True)

    class Meta:
        model = Inquiry
        fields = ['id', 'owner_email', 'category', 'title', 'status', 'created_at', 'updated_at']


class AdminInquiryReplySerializer(serializers.ModelSerializer):
    """문의 답변 읽기."""
    author_email = serializers.CharField(source='author.email', read_only=True)

    class Meta:
        model = InquiryReply
        fields = ['id', 'author_email', 'body', 'created_at', 'updated_at']


class AdminInquiryDetailSerializer(serializers.ModelSerializer):
    """문의 상세 (답변 포함, admin용)."""
    owner_email = serializers.CharField(source='owner.email', read_only=True)
    replies = AdminInquiryReplySerializer(many=True, read_only=True)

    class Meta:
        model = Inquiry
        fields = ['id', 'owner_email', 'category', 'title', 'body', 'status',
                  'created_at', 'updated_at', 'replies']


class AdminInquiryReplyWriteSerializer(serializers.ModelSerializer):
    """답변 작성 (admin용)."""
    class Meta:
        model = InquiryReply
        fields = ['body']


class AdminInquiryStatusSerializer(serializers.Serializer):
    """문의 상태 변경 (admin용)."""
    status = serializers.ChoiceField(choices=Inquiry.STATUS_CHOICES)


# ─── 신고 ─────────────────────────────────────────────────────────────

class AdminReportSerializer(serializers.ModelSerializer):
    """신고 목록·상세 (admin용)."""
    reporter_email = serializers.SerializerMethodField()
    resolved_by_email = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            'id', 'reporter_email', 'content_type', 'object_id', 'reason', 'detail',
            'status', 'resolved_by_email', 'resolved_at', 'created_at',
        ]

    def get_reporter_email(self, obj):
        return obj.reporter.email if obj.reporter else None

    def get_resolved_by_email(self, obj):
        return obj.resolved_by.email if obj.resolved_by else None


class AdminReportActionSerializer(serializers.Serializer):
    """신고 처리 액션 (admin용)."""
    ACTION_RESOLVED = 'resolved'
    ACTION_DISMISSED = 'dismissed'
    ACTION_CHOICES = [(ACTION_RESOLVED, '처리(숨김)'), (ACTION_DISMISSED, '기각')]

    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    action_note = serializers.CharField(required=False, allow_blank=True, default='')


# ─── 판촉물 주문 ───────────────────────────────────────────────────────

class AdminOrderStatusLogSerializer(serializers.ModelSerializer):
    """주문 상태 이력 (admin용)."""
    changed_by_email = serializers.SerializerMethodField()
    to_status_display = serializers.SerializerMethodField()

    class Meta:
        model = PromotionOrderStatusLog
        fields = ['id', 'to_status', 'to_status_display', 'changed_by_email', 'changed_at', 'note']

    def get_changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by else None

    def get_to_status_display(self, obj):
        return obj.get_to_status_display()


class AdminOrderListSerializer(serializers.ModelSerializer):
    """판촉물 주문 목록 (admin용)."""
    owner_email = serializers.SerializerMethodField()
    sample_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PromotionOrder
        fields = ['id', 'owner_email', 'sample_name', 'status', 'status_display',
                  'admin_note', 'created_at', 'updated_at']

    def get_owner_email(self, obj):
        return obj.owner.email if obj.owner else '(탈퇴)'

    def get_sample_name(self, obj):
        return obj.sample.name if obj.sample else None


class AdminOrderDetailSerializer(serializers.ModelSerializer):
    """판촉물 주문 상세 (admin용)."""
    owner_email = serializers.SerializerMethodField()
    sample_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    status_logs = AdminOrderStatusLogSerializer(many=True, read_only=True)

    class Meta:
        model = PromotionOrder
        fields = [
            'id', 'owner_email', 'sample_name', 'form_response',
            'status', 'status_display', 'admin_note',
            'tracking_number', 'carrier', 'created_at', 'updated_at',
            'status_logs',
        ]

    def get_owner_email(self, obj):
        return obj.owner.email if obj.owner else '(탈퇴)'

    def get_sample_name(self, obj):
        return obj.sample.name if obj.sample else None


class AdminOrderStatusUpdateSerializer(serializers.Serializer):
    """주문 상태 변경 (admin용)."""
    status = serializers.ChoiceField(choices=PromotionOrder.STATUS_CHOICES)
    admin_note = serializers.CharField(required=False, allow_blank=True, default='')
    tracking_number = serializers.CharField(required=False, allow_blank=True, default='')
    carrier = serializers.CharField(required=False, allow_blank=True, default='')
    note = serializers.CharField(required=False, allow_blank=True, default='',
                                 help_text='PromotionOrderStatusLog 전이 메모')


# ─── 동의 로그 ────────────────────────────────────────────────────────

def _mask_name(name: str) -> str:
    """PII 마스킹: '홍길동' → '홍**' (dev/19 §7)."""
    if not name:
        return ''
    return name[0] + '**'


class AdminConsentLogSerializer(serializers.ModelSerializer):
    """동의 로그 읽기 전용 (admin용). 고객명 마스킹."""
    customer_name_masked = serializers.SerializerMethodField()
    owner_email = serializers.SerializerMethodField()

    class Meta:
        model = ConsentLog
        fields = [
            'id', 'customer_name_masked', 'owner_email', 'scope', 'purpose',
            'doc_version', 'agreed_at', 'ip', 'revoked_at', 'revoke_ip',
        ]

    def get_customer_name_masked(self, obj):
        return _mask_name(obj.customer.name)

    def get_owner_email(self, obj):
        return obj.customer.owner.email if obj.customer and obj.customer.owner_id else None


# ─── 정규화 사전 ───────────────────────────────────────────────────────

class AdminUnmatchedLogSerializer(serializers.ModelSerializer):
    """미매칭 큐 (admin 검수용)."""
    class Meta:
        model = UnmatchedLog
        fields = ['id', 'company', 'raw_name', 'occurrence', 'sample_ctx', 'resolved',
                  'created_at', 'updated_at']


class AdminNormalizationMapSerializer(serializers.Serializer):
    """매핑 등록 (UnmatchedLog → NormalizationDict, admin용)."""
    unmatched_log_id = serializers.PrimaryKeyRelatedField(queryset=UnmatchedLog.objects.all())
    std_detail_id = serializers.PrimaryKeyRelatedField(queryset=AnalysisDetail.objects.all())
    confidence = serializers.IntegerField(min_value=0, max_value=100, default=100)


class AdminNormalizationDictSerializer(serializers.ModelSerializer):
    """정규화 사전 조회 (admin용)."""
    std_detail_name = serializers.CharField(source='std_detail.name', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    verified_by_email = serializers.SerializerMethodField()

    class Meta:
        model = NormalizationDict
        fields = [
            'id', 'std_detail', 'std_detail_name', 'company', 'raw_name',
            'source', 'source_display', 'confidence', 'verified_by_email',
            'hit_count', 'created_at', 'updated_at',
        ]

    def get_verified_by_email(self, obj):
        return obj.verified_by.email if obj.verified_by else None


# ─── 공지사항 ─────────────────────────────────────────────────────────

class AdminNoticeSerializer(serializers.ModelSerializer):
    """공지사항 읽기."""
    author_email = serializers.SerializerMethodField()

    class Meta:
        model = Notice
        fields = ['id', 'title', 'body', 'is_pinned', 'is_published',
                  'published_at', 'author_email', 'created_at', 'updated_at']

    def get_author_email(self, obj):
        return obj.author.email if obj.author else None


class AdminNoticeWriteSerializer(serializers.ModelSerializer):
    """공지사항 작성·수정 (admin용)."""
    class Meta:
        model = Notice
        fields = ['title', 'body', 'is_pinned', 'is_published', 'published_at']


# ─── FAQ ─────────────────────────────────────────────────────────────

class AdminFaqSerializer(serializers.ModelSerializer):
    """FAQ 읽기."""
    author_email = serializers.SerializerMethodField()

    class Meta:
        model = Faq
        fields = ['id', 'category', 'question', 'answer', 'order',
                  'is_published', 'author_email', 'created_at', 'updated_at']

    def get_author_email(self, obj):
        return obj.author.email if obj.author else None


class AdminFaqWriteSerializer(serializers.ModelSerializer):
    """FAQ 작성·수정 (admin용)."""
    class Meta:
        model = Faq
        fields = ['category', 'question', 'answer', 'order', 'is_published']


# ─── 요금제/설정 ───────────────────────────────────────────────────────

class AdminPlanSerializer(serializers.ModelSerializer):
    """Plan 한도 조회·수정 (admin용)."""
    class Meta:
        model = Plan
        fields = [
            'id', 'code', 'display_name', 'price_krw', 'description',
            'limit_ocr', 'limit_ai_compare', 'limit_analysis', 'limit_promotion',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'code', 'created_at']


class AdminPlanUpdateSerializer(serializers.ModelSerializer):
    """Plan 한도 변경 (admin용). code 변경 불가."""
    class Meta:
        model = Plan
        fields = [
            'display_name', 'price_krw', 'description',
            'limit_ocr', 'limit_ai_compare', 'limit_analysis', 'limit_promotion',
            'is_active',
        ]
