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
from inpa.analysis.models import AnalysisDetail, CoverageFlag, NormalizationDict, UnmatchedLog
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

from .models import PolicyVersion

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
    """설계사 상세 (admin 전용).

    ★ FE(admin/users/[id]) 계약: profile 필드는 평탄화해서 최상위로 노출하고,
      이번 달 사용량(4종)·활동 요약(고객/포트폴리오 수)·최근 동의로그(마스킹)를 포함한다.
      (이전엔 profile 중첩 + consent_logs 누락으로 상세 페이지가 깨졌었음.)
    """
    profile = AdminProfileSerializer(read_only=True)
    # ── 평탄화 (FE 최상위 기대) ──────────────────────────────────────────
    affiliation = serializers.SerializerMethodField()
    agent_type = serializers.SerializerMethodField()
    agent_type_display = serializers.SerializerMethodField()
    career_years = serializers.SerializerMethodField()
    license_self_declared = serializers.SerializerMethodField()
    license_no = serializers.SerializerMethodField()
    email_verified_at = serializers.SerializerMethodField()
    onboarding_completed_at = serializers.SerializerMethodField()
    is_dormant = serializers.SerializerMethodField()
    dormant_at = serializers.SerializerMethodField()
    will_delete_at = serializers.SerializerMethodField()
    # ── 요금제 ───────────────────────────────────────────────────────────
    plan_code = serializers.SerializerMethodField()
    plan_display = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()
    # ── 활동 요약 + 사용량 + 동의로그 ───────────────────────────────────
    usage_this_month = serializers.SerializerMethodField()
    usage_limits = serializers.SerializerMethodField()
    customer_count = serializers.SerializerMethodField()
    portfolio_count = serializers.SerializerMethodField()
    consent_logs = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'is_active', 'date_joined', 'last_login',
            'profile',
            'affiliation', 'agent_type', 'agent_type_display', 'career_years',
            'license_self_declared', 'license_no',
            'email_verified_at', 'onboarding_completed_at',
            'is_dormant', 'dormant_at', 'will_delete_at',
            'plan_code', 'plan_display', 'subscription_status',
            'usage_this_month', 'usage_limits', 'customer_count', 'portfolio_count',
            'consent_logs',
        ]

    # ── profile 평탄화 헬퍼 ──────────────────────────────────────────────
    def _p(self, obj):
        return getattr(obj, 'profile', None)

    def get_affiliation(self, obj):
        p = self._p(obj)
        return p.affiliation if p else None

    def get_agent_type(self, obj):
        p = self._p(obj)
        return p.agent_type if p else None

    def get_agent_type_display(self, obj):
        p = self._p(obj)
        return p.get_agent_type_display() if p and p.agent_type is not None else None

    def get_career_years(self, obj):
        p = self._p(obj)
        return p.career_years if p else None

    def get_license_self_declared(self, obj):
        p = self._p(obj)
        return p.license_self_declared if p else False

    def get_license_no(self, obj):
        p = self._p(obj)
        return p.license_no if p else None

    def get_email_verified_at(self, obj):
        p = self._p(obj)
        return p.email_verified_at if p else None

    def get_onboarding_completed_at(self, obj):
        p = self._p(obj)
        return p.onboarding_completed_at if p else None

    def get_is_dormant(self, obj):
        p = self._p(obj)
        return p.is_dormant if p else False

    def get_dormant_at(self, obj):
        p = self._p(obj)
        return p.dormant_at if p else None

    def get_will_delete_at(self, obj):
        p = self._p(obj)
        return p.will_delete_at if p else None

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
        """이번 달 사용량 4종 (없는 액션은 0으로 채워 항상 4키 보장)."""
        year_month = UsageMeter.current_month()
        meters = {
            m.action: m.count
            for m in UsageMeter.objects.filter(user=obj, year_month=year_month)
        }
        return {action: meters.get(action, 0) for action, _ in UsageMeter.ACTION_CHOICES}

    def get_usage_limits(self, obj):
        """실제 강제에 적용되는 '유효 요금제' 한도 (None = 무제한 sentinel).

        ★ 구독이 만료·해지면 강제는 Free 로 폴백하는데, 구독의 원래 plan 한도를
          그대로 보여주면 화면과 실제가 어긋난다. billing.credit.resolve_effective_plan
          으로 강제와 같은 유효 요금제를 골라 한도를 노출한다(#9 admin part).
        """
        from inpa.billing.credit import resolve_effective_plan
        plan = resolve_effective_plan(obj)
        return {action: plan.get_limit(action) for action, _ in UsageMeter.ACTION_CHOICES}

    def get_customer_count(self, obj):
        return Customer.objects.filter(owner=obj).count()

    def get_portfolio_count(self, obj):
        from inpa.insurances.models import CustomerInsurance
        return CustomerInsurance.objects.filter(customer__owner=obj).count()

    def get_consent_logs(self, obj):
        """그 설계사 고객들의 최근 동의로그 10건 (고객명 마스킹)."""
        logs = (
            ConsentLog.objects
            .filter(customer__owner=obj)
            .select_related('customer')
            .order_by('-agreed_at')[:10]
        )
        return [
            {
                'id': log.id,
                'customer_name_masked': (
                    _mask_name(log.customer.name) if log.customer_id else '(삭제된 고객)'
                ),
                'scope': log.scope,
                'scope_display': log.get_scope_display(),
                'subject_display': log.get_subject_display(),
                'agreed_at': log.agreed_at,
                'revoked_at': log.revoked_at,
            }
            for log in logs
        ]


class AdminCustomerListSerializer(serializers.ModelSerializer):
    """admin용 설계사별 고객 목록(READ-ONLY, 비민감 필드만 — dev/19 §7 PII 원칙).

    이름·연락처·영업단계·상태·등록일·최종연락 + 보유증권 수만. 병력·메모·생월일 등 민감/불필요 필드 제외.
    판정어(부족/충분) 없음 — 목록은 사실(보유 증권 수)만.
    """
    sales_stage_display = serializers.CharField(source='get_sales_stage_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    job_name = serializers.SerializerMethodField()
    insurance_count = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = ('id', 'name', 'mobile_phone_number', 'sales_stage', 'sales_stage_display',
                  'status', 'status_display', 'job_name', 'insurance_count',
                  'created_at', 'last_contacted_at')

    def get_job_name(self, obj):
        return obj.job_code.name if obj.job_code_id else None

    def get_insurance_count(self, obj):
        return obj.customer_insurance_list.count()


class AdminSubscriptionUpdateSerializer(serializers.Serializer):
    """요금제 변경 (admin용).

    plan_code 는 Plan.PLAN_CODE(free/plus) 로 제한하지 않는다 — 실제 존재하는 Plan
    코드(예: 데모 플랜)면 모두 허용하고, 뷰의 get_object_or_404(Plan, code=..., is_active=True)
    가 실제 유효성을 담당한다. (하드 제약 시 데모/추가 플랜으로 변경 불가 → 400 버그.)
    """
    plan_code = serializers.CharField(max_length=20)
    status = serializers.ChoiceField(choices=Subscription.STATUS, required=False)
    # 유료 플랜 부여 시 결제 주기. 지정하면 만료(월=1개월/연=12개월)를 계산해 세팅한다.
    # 미지정 시 만료를 강제하지 않는다(하위호환 — 기존 무기한 수동 부여 보존).
    billing_cycle = serializers.ChoiceField(
        choices=Subscription.BILLING_CYCLE, required=False)


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
    open_flags = serializers.IntegerField()  # 담보 위치 확인 요청 대기(설계사 피드백)


# ─── 1:1 문의 ─────────────────────────────────────────────────────────

class AdminInquiryListSerializer(serializers.ModelSerializer):
    """문의 목록 (admin용)."""
    owner_email = serializers.CharField(source='owner.email', read_only=True, default=None)
    owner_display = serializers.SerializerMethodField()
    category_label = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = Inquiry
        fields = ['id', 'owner_email', 'owner_display', 'category', 'category_label',
                  'title', 'status', 'rating', 'contact_email', 'created_at', 'updated_at']

    def get_owner_display(self, obj):
        # 익명(owner=None) 제출은 '비회원' 으로 표기.
        if obj.owner_id is None:
            return '비회원'
        return obj.owner.email


class AdminInquiryReplySerializer(serializers.ModelSerializer):
    """문의 답변 읽기."""
    author_email = serializers.CharField(source='author.email', read_only=True)

    class Meta:
        model = InquiryReply
        fields = ['id', 'author_email', 'body', 'created_at', 'updated_at']


class AdminInquiryDetailSerializer(serializers.ModelSerializer):
    """문의 상세 (답변 포함, admin용)."""
    owner_email = serializers.CharField(source='owner.email', read_only=True, default=None)
    owner_display = serializers.SerializerMethodField()
    category_label = serializers.CharField(source='get_category_display', read_only=True)
    replies = AdminInquiryReplySerializer(many=True, read_only=True)

    class Meta:
        model = Inquiry
        fields = ['id', 'owner_email', 'owner_display', 'category', 'category_label',
                  'title', 'body', 'status', 'rating', 'meta', 'contact_email',
                  'created_at', 'updated_at', 'replies']

    def get_owner_display(self, obj):
        if obj.owner_id is None:
            return '비회원'
        return obj.owner.email


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
            'id', 'customer_name_masked', 'owner_email', 'scope', 'subject',
            'subject_display', 'purpose', 'doc_version', 'agreed_at', 'ip',
            'revoked_at', 'revoke_ip',
        ]

    subject_display = serializers.CharField(source='get_subject_display', read_only=True)

    def get_customer_name_masked(self, obj):
        # customer는 SET_NULL — 고객 파기 후 null일 수 있음(감사기록 잔존).
        return _mask_name(obj.customer.name) if obj.customer_id else '(삭제된 고객)'

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


class NormalizationAccuracyFailureSerializer(serializers.Serializer):
    """골든셋 실패 항목 1건 (사실만 — 판정어 없음)."""
    company = serializers.IntegerField()
    raw_name = serializers.CharField()
    expected = serializers.CharField()
    got = serializers.CharField(allow_null=True)


class NormalizationAccuracySerializer(serializers.Serializer):
    """골든셋 정규화 정확도 기준선 응답 (프리런치 리뷰 #18) — 사실 수치만, 판정어 금지."""
    accuracy = serializers.FloatField()
    total = serializers.IntegerField()
    passed = serializers.IntegerField()
    anchor_passed = serializers.IntegerField()
    anchor_total = serializers.IntegerField()
    min_accuracy = serializers.FloatField()
    sample_failures = NormalizationAccuracyFailureSerializer(many=True)


class AdminCoverageFlagSerializer(serializers.ModelSerializer):
    """담보 위치 확인 요청 목록/처리 결과 (admin 검수용).

    customer_name 은 이름만(연락처·생년월일 등 추가 PII 미노출 — dev/19 §7 최소 원칙).
    current_mapping = 신고 당시 매핑돼 있던 표준 담보명(analysis_detail SET_NULL 대응).
    """
    planner_email = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    current_mapping = serializers.SerializerMethodField()

    class Meta:
        model = CoverageFlag
        fields = [
            'id', 'company', 'raw_name_snapshot', 'note', 'status',
            'planner_email', 'customer_name', 'current_mapping',
            'analysis_detail_id', 'case_id', 'resolution_memo',
            'created_at', 'updated_at',
        ]

    def get_planner_email(self, obj):
        return obj.owner.email if obj.owner_id else None

    def get_customer_name(self, obj):
        # customer SET_NULL — 고객 파기 후 null 가능(요청 이력은 잔존).
        return obj.customer.name if obj.customer_id else None

    def get_current_mapping(self, obj):
        return obj.analysis_detail.name if obj.analysis_detail_id else None


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


# ─── 인파 노트(BlogPost) ────────────────────────────────────────────────

from inpa.boards.serializers import BlogPostAdminSerializer  # noqa: E402


class AdminBlogPostSerializer(BlogPostAdminSerializer):
    """인파 노트 admin CRUD — boards.BlogPostAdminSerializer 재사용.

    슬러그 자동 생성·유니크 보장·전체 readback 은 부모가 담당. 게시 시 카피 검사
    (core.copyguard.scan_blog_content)는 뷰에서 비차단 경고로 수행한다.
    """
    pass


# ─── 요금제/설정 ───────────────────────────────────────────────────────

class AdminPlanSerializer(serializers.ModelSerializer):
    """Plan 한도 조회·수정 (admin용)."""
    class Meta:
        model = Plan
        fields = [
            'id', 'code', 'display_name', 'price_krw', 'price_annual_krw', 'description',
            'limit_ocr', 'limit_ai_compare', 'limit_analysis', 'limit_promotion',
            'limit_customer',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'code', 'created_at']


class AdminPlanUpdateSerializer(serializers.ModelSerializer):
    """Plan 한도 변경 (admin용). code 변경 불가."""
    class Meta:
        model = Plan
        fields = [
            'display_name', 'price_krw', 'price_annual_krw', 'description',
            'limit_ocr', 'limit_ai_compare', 'limit_analysis', 'limit_promotion',
            'limit_customer',
            'is_active',
        ]


# ─── 약관 버전 ─────────────────────────────────────────────────────────

class PolicyVersionSerializer(serializers.ModelSerializer):
    """약관 버전 조회 (admin용)."""
    policy_type_display = serializers.CharField(source='get_policy_type_display', read_only=True)

    class Meta:
        model = PolicyVersion
        fields = [
            'id', 'policy_type', 'policy_type_display',
            'version', 'effective_at', 'requires_reconsent', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class PolicyVersionWriteSerializer(serializers.ModelSerializer):
    """약관 버전 등록 (admin용). policy_type 검증 포함."""
    class Meta:
        model = PolicyVersion
        fields = ['policy_type', 'version', 'effective_at', 'requires_reconsent']


# ─── 기능 플래그 (읽기 전용 — env 우회 차단) ──────────────────────────

class FeatureFlagsSerializer(serializers.Serializer):
    """env 기반 기능 플래그 현재 값 (READ-ONLY).

    컴플라이언스 게이트는 환경변수로만 제어 — runtime PATCH 미구현.
    모든 필드는 read_only (Serializer.read_only_fields 은 Serializer 에 없으므로 fields 선언으로 처리).
    """
    FREE_TIER_UNLIMITED = serializers.BooleanField(read_only=True)
    COMPARE_AI_ENABLED = serializers.BooleanField(read_only=True)
    COMPARE_PUBLISH_ENABLED = serializers.BooleanField(read_only=True)
    ANALYZE_MEDICAL_ENABLED = serializers.BooleanField(read_only=True)
    BOOKING_ENABLED = serializers.BooleanField(read_only=True)
    OCR_VERIFY_ENABLED = serializers.BooleanField(read_only=True)
    REQUIRE_CUSTOMER_SELF_CONSENT = serializers.BooleanField(read_only=True)
    GOOGLE_OAUTH_ENABLED = serializers.BooleanField(read_only=True)
