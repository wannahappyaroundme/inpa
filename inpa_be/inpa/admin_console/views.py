"""admin_console 뷰 (dev/19 §5 API 계약).

base path: /api/v1/admin/
권한: 전부 IsAdmin (Profile.is_admin=True).

★ 컴플라이언스 레드라인 (dev/19 §7):
  - ConsentLog DELETE API 없음 (감사 무결성 절대 보호).
  - 설계사 고객 데이터 수정 API 없음 (소유권 원칙).
  - 판정어 금지 (대시보드 사실 카운트만).
  - admin 비밀번호 직접 변경 불가 — 재설정 링크 발송만.
  - 알림 대상: 설계사 본인만 (고객 자동발송 경로 물리 부재).
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle

from inpa.analysis.golden_eval import (
    GOLDEN_SET_MIN_ACCURACY, evaluate_golden_set, find_golden_expected,
)
from inpa.analysis.models import AnalysisDetail, CoverageFlag, NormalizationDict, UnmatchedLog
from inpa.billing.models import Plan, Subscription, UsageMeter
from inpa.boards.models import (
    BlogPost,
    Comment,
    Faq,
    Inquiry,
    InquiryReply,
    Notice,
    Post,
    Report,
)
from inpa.core.copyguard import scan_blog_content
from inpa.core.permissions import IsAdmin
from inpa.customers.models import ConsentLog, Customer
from inpa.notifications.models import Notification, NotifType
from inpa.promotion.models import PromotionOrder

from .models import PolicyVersion
from .serializers import (
    AdminBlogPostSerializer,
    AdminConsentLogSerializer,
    AdminCoverageFlagSerializer,
    AdminCustomerListSerializer,
    AdminFaqSerializer,
    AdminFaqWriteSerializer,
    AdminInquiryDetailSerializer,
    AdminInquiryListSerializer,
    AdminInquiryReplyWriteSerializer,
    AdminInquiryStatusSerializer,
    AdminNormalizationDictSerializer,
    AdminNormalizationMapSerializer,
    AdminNoticeSerializer,
    AdminNoticeWriteSerializer,
    AdminOrderDetailSerializer,
    AdminOrderListSerializer,
    AdminOrderStatusUpdateSerializer,
    AdminPlanSerializer,
    AdminPlanUpdateSerializer,
    AdminReportActionSerializer,
    AdminReportSerializer,
    AdminSubscriptionUpdateSerializer,
    AdminUnmatchedLogSerializer,
    AdminUserDetailSerializer,
    AdminUserListSerializer,
    DashboardSerializer,
    NormalizationAccuracySerializer,
    FeatureFlagsSerializer,
    PolicyVersionSerializer,
    PolicyVersionWriteSerializer,
)

User = get_user_model()


# ─── 알림 생성 헬퍼 (설계사 본인 대상 — 고객 자동발송 금지) ─────────────

def _notify_user(owner, notif_type: str, title: str, body: str):
    """설계사 본인에게 인앱 알림 생성. 실패 시 조용히 무시 (주 동작 보호)."""
    try:
        Notification.objects.create(
            owner=owner,
            notif_type=notif_type,
            title=title,
            body=body,
        )
    except Exception:
        pass


# ─── A. 대시보드 ──────────────────────────────────────────────────────

class AdminDashboardView(APIView):
    """GET /api/v1/admin/dashboard/
    운영 지표 집계 — 사실 카운트만, 판정어 금지 (dev/19 §4.3-A).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        today = timezone.now().date()
        year_month = timezone.now().strftime('%Y-%m')

        data = {
            # 오늘 현황
            'today_new_users': User.objects.filter(date_joined__date=today).count(),
            'today_new_orders': PromotionOrder.objects.filter(created_at__date=today).count(),
            'open_inquiries': Inquiry.objects.filter(status=Inquiry.STATUS_OPEN).count(),
            'pending_reports': Report.objects.filter(status=Report.STATUS_PENDING).count(),
            # 누적 지표 (사실 카운트만 — "활성화율 낮음/위험" 등 판정 금지)
            'total_users': User.objects.count(),
            'total_customers': Customer.objects.count(),
            # 요금제 분포
            'plan_distribution': _get_plan_distribution(),
            # 미처리 항목
            'pending_orders': PromotionOrder.objects.filter(
                status=PromotionOrder.STATUS_PENDING
            ).count(),
            'unresolved_unmatched': UnmatchedLog.objects.filter(resolved=False).count(),
            # 담보 위치 확인 요청(설계사 피드백) 미처리 건수 — 정규화 검수 큐와 나란히.
            'open_flags': CoverageFlag.objects.filter(
                status=CoverageFlag.STATUS_OPEN
            ).count(),
        }
        serializer = DashboardSerializer(data)
        return Response(serializer.data)


def _get_plan_distribution() -> dict:
    """요금제별 설계사 수 (판정 레이블 없이 수치만 반환)."""
    from django.db.models import Count
    dist = (
        Subscription.objects
        .values('plan__code')
        .annotate(count=Count('id'))
    )
    result = {row['plan__code']: row['count'] for row in dist}
    # 구독 없는 설계사(미초기화) 카운트 포함
    subbed_count = sum(result.values())
    total = User.objects.count()
    if total > subbed_count:
        result['no_plan'] = total - subbed_count
    return result


# ─── B. 설계사 관리 ──────────────────────────────────────────────────

class AdminUserListView(APIView):
    """GET /api/v1/admin/users/
    설계사 목록 (검색·필터·페이지네이션).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = User.objects.select_related('profile', 'subscription__plan').order_by('-date_joined')

        # 검색: 이메일
        q = request.query_params.get('q')
        if q:
            qs = qs.filter(email__icontains=q)

        # 필터: 요금제
        plan_code = request.query_params.get('plan')
        if plan_code:
            qs = qs.filter(subscription__plan__code=plan_code)

        # 필터: 휴면 여부
        is_dormant = request.query_params.get('is_dormant')
        if is_dormant == 'true':
            qs = qs.filter(profile__is_dormant=True)
        elif is_dormant == 'false':
            qs = qs.filter(profile__is_dormant=False)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminUserListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminUserDetailView(APIView):
    """GET /api/v1/admin/users/:id/
    설계사 상세 + 사용량 (READ 중심, 고객 원문 수정 금지).
    """
    permission_classes = [IsAdmin]

    def get(self, request, user_id):
        user = get_object_or_404(
            User.objects.select_related('profile', 'subscription__plan'),
            pk=user_id,
        )
        return Response(AdminUserDetailSerializer(user).data)


class AdminUserCustomersView(APIView):
    """GET /api/v1/admin/users/:id/customers/
    설계사가 보유한 고객 목록 (admin READ-ONLY, 비민감 필드만 — dev/19 §7 PII 원칙).
    admin은 owner 격리를 우회(설계사 자산 운영 점검용), 단 목록은 사실 필드만 노출한다.
    """
    permission_classes = [IsAdmin]

    def get(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        qs = (Customer.objects.filter(owner=user)
              .select_related('job_code')
              .order_by('-created_at'))
        return Response({
            'count': qs.count(),
            'results': AdminCustomerListSerializer(qs, many=True).data,
        })


class AdminUserSubscriptionView(APIView):
    """PATCH /api/v1/admin/users/:id/subscription/
    요금제 변경 (Subscription 업데이트 + 설계사 알림).
    """
    permission_classes = [IsAdmin]

    def patch(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        serializer = AdminSubscriptionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        plan_code = serializer.validated_data['plan_code']
        plan = get_object_or_404(Plan, code=plan_code, is_active=True)

        sub, created = Subscription.objects.get_or_create(
            user=user,
            defaults={'plan': plan, 'status': 'active'},
        )
        if not created:
            old_plan = sub.plan.display_name
            sub.plan = plan
            if 'status' in serializer.validated_data:
                sub.status = serializer.validated_data['status']
            sub.save()
        else:
            old_plan = None

        # 설계사 본인에게 알림 (고객 자동발송 금지 원칙)
        _notify_user(
            owner=user,
            notif_type=NotifType.EXPIRY_SOON,  # 시스템 알림 — 가장 유사 타입 재사용
            title='요금제가 변경되었습니다',
            body=f'요금제가 {plan.display_name}({plan.code})으로 변경되었습니다.',
        )

        return Response({
            'user_id': user.id,
            'plan_code': plan.code,
            'plan_display': plan.display_name,
            'status': sub.status,
            'changed': not created or old_plan != plan.display_name,
        })


class AdminUserSendResetEmailView(APIView):
    """POST /api/v1/admin/users/:id/send_reset_email/
    비밀번호 재설정 이메일 발송 (admin이 직접 변경 불가 — 보안 원칙).
    """
    permission_classes = [IsAdmin]

    def post(self, request, user_id):
        from inpa.accounts.views import _send_reset_email
        user = get_object_or_404(User, pk=user_id)
        _send_reset_email(user)
        return Response({'sent': True, 'email': user.email})


# ─── F. 1:1 문의 ────────────────────────────────────────────────────

class AdminInquiryListView(APIView):
    """GET /api/v1/admin/inquiries/
    문의 목록 (admin 전체 조회 — OwnedQuerySetMixin bypass).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = Inquiry.objects.select_related('owner').prefetch_related('replies__author')

        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        qs = qs.order_by('-created_at')
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminInquiryListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminInquiryDetailView(APIView):
    """GET /api/v1/admin/inquiries/:id/
    문의 상세 + 답변 목록.
    """
    permission_classes = [IsAdmin]

    def get(self, request, inquiry_id):
        inquiry = get_object_or_404(
            Inquiry.objects.select_related('owner').prefetch_related('replies__author'),
            pk=inquiry_id,
        )
        return Response(AdminInquiryDetailSerializer(inquiry).data)


class AdminInquiryReplyView(APIView):
    """POST /api/v1/admin/inquiries/:id/reply/
    답변 등록 → status=answered + 설계사 알림.
    """
    permission_classes = [IsAdmin]

    def post(self, request, inquiry_id):
        inquiry = get_object_or_404(Inquiry.objects.select_related('owner'), pk=inquiry_id)
        serializer = AdminInquiryReplyWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            reply = InquiryReply.objects.create(
                inquiry=inquiry,
                author=request.user,
                body=serializer.validated_data['body'],
            )
            if inquiry.status == Inquiry.STATUS_OPEN:
                inquiry.status = Inquiry.STATUS_ANSWERED
                inquiry.save(update_fields=['status', 'updated_at'])

        # 설계사 본인에게 알림 (고객 자동발송 금지)
        if inquiry.owner:
            _notify_user(
                owner=inquiry.owner,
                notif_type=NotifType.EXPIRY_SOON,  # 시스템 알림 최근접 타입
                title='1:1 문의 답변이 등록되었습니다',
                body=f'"{inquiry.title}"에 답변이 달렸습니다.',
            )

        return Response(
            AdminInquiryDetailSerializer(inquiry).data,
            status=status.HTTP_201_CREATED,
        )


class AdminInquiryStatusView(APIView):
    """PATCH /api/v1/admin/inquiries/:id/status/
    문의 상태 변경 (open/answered/closed).
    """
    permission_classes = [IsAdmin]

    def patch(self, request, inquiry_id):
        inquiry = get_object_or_404(Inquiry, pk=inquiry_id)
        serializer = AdminInquiryStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inquiry.status = serializer.validated_data['status']
        inquiry.save(update_fields=['status', 'updated_at'])
        return Response(AdminInquiryDetailSerializer(inquiry).data)


# ─── C. 신고 모더레이션 ──────────────────────────────────────────────

class AdminReportListView(APIView):
    """GET /api/v1/admin/reports/
    신고 목록 (admin 전체 조회).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = Report.objects.select_related('reporter', 'resolved_by').order_by('-created_at')

        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminReportSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminReportActionView(APIView):
    """PATCH /api/v1/admin/reports/:id/action/
    신고 처리 — resolved(글 숨김) 또는 dismissed(기각).
    resolved 시 object_id 게시물 is_hidden=True 소프트 처리 + 신고자 알림.
    """
    permission_classes = [IsAdmin]

    def patch(self, request, report_id):
        report = get_object_or_404(
            Report.objects.select_related('reporter', 'resolved_by'),
            pk=report_id,
        )
        serializer = AdminReportActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data['action']
        action_note = serializer.validated_data.get('action_note', '')

        with transaction.atomic():
            report.status = action
            report.resolved_by = request.user
            report.resolved_at = timezone.now()
            report.save(update_fields=['status', 'resolved_by', 'resolved_at'])

            if action == AdminReportActionSerializer.ACTION_RESOLVED:
                # 대상 콘텐츠 숨김 처리
                if report.content_type == Report.CONTENT_POST:
                    Post.objects.filter(pk=report.object_id).update(is_hidden=True)
                elif report.content_type == Report.CONTENT_COMMENT:
                    Comment.objects.filter(pk=report.object_id).update(is_hidden=True)

        # 신고자에게 처리 결과 알림
        if report.reporter:
            result_msg = '처리되었습니다' if action == AdminReportActionSerializer.ACTION_RESOLVED else '기각되었습니다'
            _notify_user(
                owner=report.reporter,
                notif_type=NotifType.EXPIRY_SOON,
                title=f'신고가 {result_msg}',
                body=f'신고하신 콘텐츠가 검토되어 {result_msg}.',
            )

        return Response(AdminReportSerializer(report).data)


# ─── G. 판촉물 주문 ──────────────────────────────────────────────────

class AdminOrderListView(APIView):
    """GET /api/v1/admin/orders/
    판촉물 주문 목록 (admin 전체 조회).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = PromotionOrder.objects.select_related('owner', 'sample').order_by('-created_at')

        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminOrderListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminOrderDetailView(APIView):
    """GET /api/v1/admin/orders/:id/
    판촉물 주문 상세.
    """
    permission_classes = [IsAdmin]

    def get(self, request, order_id):
        order = get_object_or_404(
            PromotionOrder.objects.select_related('owner', 'sample').prefetch_related('status_logs'),
            pk=order_id,
        )
        return Response(AdminOrderDetailSerializer(order).data)


class AdminOrderStatusView(APIView):
    """PATCH /api/v1/admin/orders/:id/status/
    주문 상태 변경 → PromotionOrderStatusLog 적재 + 설계사 알림.
    form_response 수정 금지 (설계사 제출 원문 보존).
    """
    permission_classes = [IsAdmin]

    def patch(self, request, order_id):
        order = get_object_or_404(
            PromotionOrder.objects.select_related('owner'),
            pk=order_id,
        )
        serializer = AdminOrderStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data['status']
        admin_note = serializer.validated_data.get('admin_note', '')
        tracking_number = serializer.validated_data.get('tracking_number', '')
        carrier = serializer.validated_data.get('carrier', '')
        note = serializer.validated_data.get('note', '')

        try:
            with transaction.atomic():
                # 관리자 메모·발송정보 업데이트
                update_fields = ['updated_at']
                if admin_note:
                    order.admin_note = admin_note
                    update_fields.append('admin_note')
                if tracking_number:
                    order.tracking_number = tracking_number
                    update_fields.append('tracking_number')
                if carrier:
                    order.carrier = carrier
                    update_fields.append('carrier')
                if update_fields != ['updated_at']:
                    order.save(update_fields=update_fields)

                # 상태 전이 (유효성 검사 + StatusLog 적재)
                status_log = order.transition_to(new_status, changed_by=request.user)
                if note:
                    status_log.note = note
                    status_log.save(update_fields=['note'])
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # 설계사 본인에게 알림 (고객 자동발송 금지)
        _STATUS_MESSAGES = {
            PromotionOrder.STATUS_REVIEWING: '주문을 검토 중입니다',
            PromotionOrder.STATUS_PRODUCING: '제작이 시작되었습니다',
            PromotionOrder.STATUS_SHIPPING: '배송이 시작되었습니다',
            PromotionOrder.STATUS_COMPLETED: '주문이 완료되었습니다',
            PromotionOrder.STATUS_CANCELLED: '주문이 취소되었습니다',
        }
        msg = _STATUS_MESSAGES.get(new_status)
        if msg and order.owner:
            _notify_user(
                owner=order.owner,
                notif_type=NotifType.EXPIRY_SOON,
                title=f'판촉물 주문 #{order.pk} — {msg}',
                body=admin_note or msg,
            )

        order.refresh_from_db()
        return Response(AdminOrderDetailSerializer(order).data)


# ─── H. 동의 로그 ────────────────────────────────────────────────────

class AdminConsentLogListView(APIView):
    """GET /api/v1/admin/consent-logs/
    동의 로그 목록 READ-ONLY (감사 무결성 — DELETE API 물리 부재).
    고객명 마스킹('홍**') 적용.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = ConsentLog.objects.select_related('customer__owner').order_by('-agreed_at')

        # 필터: 동의 범위
        scope = request.query_params.get('scope')
        if scope:
            qs = qs.filter(scope=scope)

        # 필터: 철회 여부
        revoked = request.query_params.get('revoked')
        if revoked == 'true':
            qs = qs.exclude(revoked_at__isnull=True)
        elif revoked == 'false':
            qs = qs.filter(revoked_at__isnull=True)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminConsentLogSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    # ★ DELETE 메서드 미구현 — 감사 무결성 절대 보호 (dev/19 §7)


# ─── I. 정규화 매핑 큐 ──────────────────────────────────────────────

class AdminUnmatchedListView(APIView):
    """GET /api/v1/admin/normalization/unmatched/
    미매칭 큐 목록 (resolved=False 우선).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = UnmatchedLog.objects.order_by('resolved', '-occurrence', '-created_at')

        resolved = request.query_params.get('resolved')
        if resolved == 'false':
            qs = qs.filter(resolved=False)
        elif resolved == 'true':
            qs = qs.filter(resolved=True)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminUnmatchedLogSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminNormalizationMapView(APIView):
    """POST /api/v1/admin/normalization/map/
    매핑 등록: UnmatchedLog → NormalizationDict (source=admin_verified).
    resolved=True 설정 → 다음 OCR부터 자동 매칭.
    """
    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = AdminNormalizationMapSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        unmatched = serializer.validated_data['unmatched_log_id']
        std_detail = serializer.validated_data['std_detail_id']
        confidence = serializer.validated_data['confidence']

        with transaction.atomic():
            # NormalizationDict 생성 (중복 시 업데이트)
            norm_dict, created = NormalizationDict.objects.get_or_create(
                company=unmatched.company,
                raw_name=unmatched.raw_name,
                defaults={
                    'std_detail': std_detail,
                    'source': NormalizationDict.SOURCE_ADMIN_VERIFIED,
                    'confidence': confidence,
                    'verified_by': request.user,
                },
            )
            if not created:
                norm_dict.std_detail = std_detail
                norm_dict.source = NormalizationDict.SOURCE_ADMIN_VERIFIED
                norm_dict.confidence = confidence
                norm_dict.verified_by = request.user
                norm_dict.save()

            # 미매칭 로그 resolved 처리
            unmatched.resolved = True
            unmatched.save(update_fields=['resolved', 'updated_at'])

        return Response(
            AdminNormalizationDictSerializer(norm_dict).data,
            status=status.HTTP_201_CREATED,
        )


class AdminNormalizationDictListView(APIView):
    """GET /api/v1/admin/normalization/dict/
    정규화 사전 목록 + 검색.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = NormalizationDict.objects.select_related('std_detail', 'verified_by').order_by('-hit_count', 'raw_name')

        q = request.query_params.get('q')
        if q:
            qs = qs.filter(raw_name__icontains=q)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminNormalizationDictSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminNormalizationDictDetailView(APIView):
    """DELETE /api/v1/admin/normalization/dict/:id/
    오매핑 삭제 (§97 방어선 — 오매핑 정정).
    ★ 삭제 시 admin_note 텍스트 로깅 (dev/19 §9 A-3 기본값).
    """
    permission_classes = [IsAdmin]

    def delete(self, request, dict_id):
        norm = get_object_or_404(NormalizationDict, pk=dict_id)
        raw_name = norm.raw_name
        company = norm.company
        norm.delete()
        return Response({'deleted': True, 'raw_name': raw_name, 'company': company})


# ─── I-2. 담보 위치 확인 요청 (설계사 피드백 → 사전 반영, 2026-07-09) ───

# 표준 담보 트리 카테고리 마커 (seed_normalization.STD_MARKER / coverage_bridge 동일).
_STD_MARKER = '[표준]'


class AdminNormalizationLeavesView(APIView):
    """GET /api/v1/admin/normalization/leaves/?q=
    표준 담보(AnalysisDetail) leaf 목록 — 매핑/플래그 검수의 표준 담보 선택기용.
    [표준] 카테고리로 한정(seed_demo 동명 leaf 오선택 방지, coverage_bridge 와 동일 기준).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = (
            AnalysisDetail.objects
            .filter(sub_category__category__name__startswith=_STD_MARKER)
            .select_related('sub_category__category')
            .order_by('sub_category__category__order', 'sub_category__order', 'order', 'id')
        )
        q = request.query_params.get('q')
        if q:
            qs = qs.filter(name__icontains=q)
        return Response([
            {
                'id': d.id,
                'name': d.name,
                'category_name': d.sub_category.category.name,
                'sub_category_name': d.sub_category.name,
            }
            for d in qs
        ])


class AdminNormalizationAccuracyView(APIView):
    """GET /api/v1/admin/normalization/accuracy/
    골든셋(NORMALIZATION_V0 + 함정 앵커, 프리런치 리뷰 #18) 대비 정규화 키워드 매처
    정확도 기준선. 사실 수치만 — 판정어 없음.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        result = evaluate_golden_set()
        data = {
            'accuracy': result['accuracy'],
            'total': result['total'],
            'passed': result['passed'],
            'anchor_passed': result['anchor_passed'],
            'anchor_total': result['anchor_total'],
            'min_accuracy': GOLDEN_SET_MIN_ACCURACY,
            'sample_failures': result['failures'][:20],
        }
        return Response(NormalizationAccuracySerializer(data).data)


class AdminCoverageFlagListView(APIView):
    """GET /api/v1/admin/normalization/flags/?status=
    담보 위치 확인 요청 목록. 기본 open(대기)만, status=all 로 전체.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = (
            CoverageFlag.objects
            .select_related('owner', 'customer', 'analysis_detail')
            .order_by('-created_at')
        )
        status_q = request.query_params.get('status') or CoverageFlag.STATUS_OPEN
        if status_q != 'all':
            qs = qs.filter(status=status_q)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminCoverageFlagSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


def _substring_collision_warnings(company, raw_name, exclude_pk=None):
    """같은 회사 사전에서 raw_name 과 부분문자열 관계인 기존 항목 경고 목록.

    사전 룩업은 exact-match 라 실위험은 낮지만, 키워드(substring) 매칭 경로와의
    혼동을 어드민이 인지하도록 경고만 한다(차단 없음 — spec v1 대체안 #18).
    """
    warnings = []
    qs = NormalizationDict.objects.filter(company=company)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    for other in qs.values_list('raw_name', flat=True):
        if not other or other == raw_name:
            continue
        if other in raw_name or raw_name in other:
            warnings.append(
                f'기존 사전 원문 "{other}" 과(와) 부분 문자열 관계입니다. 혼동 여부를 확인해 주세요.')
    return warnings


class AdminCoverageFlagResolveView(APIView):
    """POST /api/v1/admin/normalization/flags/<flag_id>/resolve/
    body: {action: 'accept'|'reject', std_detail_id?, raw_name?, memo?}

    accept:
      - NormalizationDict(company, raw_name → std_detail, source=admin_verified) upsert.
        raw_name 은 어드민이 덮어쓸 수 있음(기본 = 스냅샷). company/원문이 없으면
        사전 등록은 건너뛰고(관측 불가) 연결 정정만 수행.
      - 연결 정정: 플래그된 case 의 InsuranceDetail.analysis_detail M2M 을 새 leaf 로
        교체. 카탈로그 행은 전 고객 공유 → 같은 이름 전체에 적용(사전 철학과 동일).
      - 응답: relinked(교정된 카탈로그 행 수 0|1) + warnings(부분문자열 충돌, 차단 없음).
    reject: status/memo 만.
    """
    permission_classes = [IsAdmin]

    def post(self, request, flag_id):
        flag = get_object_or_404(
            CoverageFlag.objects.select_related('case__detail', 'case__insurance'),
            pk=flag_id)
        if flag.status != CoverageFlag.STATUS_OPEN:
            return Response({'code': 'ALREADY_RESOLVED',
                             'detail': '이미 처리된 요청입니다.'},
                            status=status.HTTP_409_CONFLICT)

        action = request.data.get('action')
        memo = str(request.data.get('memo') or '').strip()[:200]

        if action == 'reject':
            flag.status = CoverageFlag.STATUS_REJECTED
            flag.resolved_by = request.user
            flag.resolution_memo = memo
            flag.save(update_fields=['status', 'resolved_by', 'resolution_memo', 'updated_at'])
            return Response({'flag': AdminCoverageFlagSerializer(flag).data})

        if action != 'accept':
            return Response({'code': 'INVALID_ACTION',
                             'detail': "action 은 'accept' 또는 'reject' 여야 합니다."},
                            status=status.HTTP_400_BAD_REQUEST)

        # ── accept ──
        std_detail = None
        try:
            std_detail = AnalysisDetail.objects.get(pk=int(request.data.get('std_detail_id')))
        except (TypeError, ValueError, AnalysisDetail.DoesNotExist):
            return Response({'code': 'STD_DETAIL_REQUIRED',
                             'detail': 'std_detail_id(표준 담보 id)가 필요합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # 원문: 어드민 덮어쓰기 > 스냅샷. 사전 컬럼 한도(120)에 맞춰 절단.
        submitted_raw = str(request.data.get('raw_name') or flag.raw_name_snapshot or '').strip()
        raw_name = submitted_raw[:120]

        dict_created = False
        dict_id = None
        warnings = []
        relinked = 0

        with transaction.atomic():
            # 1) 정규화 사전 upsert — company·원문이 있어야 별칭이 성립.
            #    company < 0 (-1 = 보험사 미감지)는 사전 등록 스킵: 파싱 시점 룩업이
            #    company_idx < 0 이면 조회 자체를 안 하므로 -1 별칭은 절대 매칭되지
            #    않는 죽은 행이 된다(연결 정정은 그대로 수행).
            if raw_name and flag.company is not None and flag.company >= 0:
                norm, dict_created = NormalizationDict.objects.get_or_create(
                    company=flag.company,
                    raw_name=raw_name,
                    defaults={
                        'std_detail': std_detail,
                        'source': NormalizationDict.SOURCE_ADMIN_VERIFIED,
                        'verified_by': request.user,
                    },
                )
                if not dict_created:
                    norm.std_detail = std_detail
                    norm.source = NormalizationDict.SOURCE_ADMIN_VERIFIED
                    norm.verified_by = request.user
                    norm.save()
                dict_id = norm.id
                warnings = _substring_collision_warnings(
                    flag.company, raw_name, exclude_pk=norm.pk)
                if len(submitted_raw) > 120:
                    # 사전 raw_name 은 120자로 잘라 저장되는데 파싱 시점 룩업은 원문
                    # 전체(exact-match)라, 잘린 별칭은 매칭되지 않을 수 있음을 고지.
                    warnings.append(
                        '원문이 120자를 넘어 잘라 등록했습니다. '
                        '등록된 별칭이 실제 파싱에서 매칭되지 않을 수 있습니다.')

            # 2) 연결 정정 — 카탈로그(InsuranceDetail) M2M 교체(전역 공유 행 = 전역 정정).
            if flag.case is not None and flag.case.detail_id:
                flag.case.detail.analysis_detail.set([std_detail])
                relinked = 1

            flag.status = CoverageFlag.STATUS_ACCEPTED
            flag.resolved_by = request.user
            flag.resolution_memo = memo
            flag.save(update_fields=['status', 'resolved_by', 'resolution_memo', 'updated_at'])

        # 골든셋(프리런치 리뷰 #18) 관점 경고 — 이 승인이 기존 골든셋 앵커/시드 기대와 다른
        # leaf 로 가면 비차단 경고. ★ 트랜잭션 밖 + try/except: 코퍼스 파일 부재 등으로 예외가
        # 나도 이미 커밋된 accept(사전 등록·연결 정정)를 절대 되돌리지 않는다. 전체 재채점은
        # 하지 않는다(238건 조회 = 매 승인마다 과부하) — 정확도는 전용 카드에서 on-demand 조회.
        if raw_name and flag.company is not None and flag.company >= 0:
            try:
                golden_expected = find_golden_expected(flag.company, raw_name)
                if golden_expected is not None and golden_expected != std_detail.name:
                    warnings.append(
                        f'골든셋 기대와 다른 매핑입니다(기대: {golden_expected}). '
                        '의도한 매핑이 맞는지 다시 확인해 주세요.')
            except Exception:
                pass

        return Response({
            'flag': AdminCoverageFlagSerializer(flag).data,
            'dict_created': dict_created,
            'dict_id': dict_id,
            'relinked': relinked,
            'warnings': warnings,
        })


# ─── D. 공지사항 ─────────────────────────────────────────────────────

class AdminNoticeListView(APIView):
    """GET /api/v1/admin/notices/ — admin 전체 목록 (임시저장 포함)
    POST /api/v1/admin/notices/ — 공지 작성
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = Notice.objects.select_related('author').order_by('-is_pinned', '-created_at')
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(AdminNoticeSerializer(page, many=True).data)

    def post(self, request):
        serializer = AdminNoticeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notice = serializer.save(author=request.user)
        if notice.is_published and notice.published_at is None:
            notice.published_at = timezone.now()
            notice.save(update_fields=['published_at'])
        return Response(AdminNoticeSerializer(notice).data, status=status.HTTP_201_CREATED)


class AdminNoticeDetailView(APIView):
    """PATCH /api/v1/admin/notices/:id/ — 공지 수정
    DELETE /api/v1/admin/notices/:id/ — 공지 삭제(소프트 = is_published=False)
    """
    permission_classes = [IsAdmin]

    def patch(self, request, notice_id):
        notice = get_object_or_404(Notice, pk=notice_id)
        serializer = AdminNoticeWriteSerializer(notice, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if notice.is_published and notice.published_at is None:
            notice.published_at = timezone.now()
            notice.save(update_fields=['published_at'])
        return Response(AdminNoticeSerializer(notice).data)

    def delete(self, request, notice_id):
        notice = get_object_or_404(Notice, pk=notice_id)
        # 소프트 삭제 — 설계사 화면에서만 안 보임, DB 보존 (dev/19 §4.3-D)
        notice.is_published = False
        notice.save(update_fields=['is_published', 'updated_at'])
        return Response({'deleted': True, 'id': notice_id})


# ─── E. FAQ ──────────────────────────────────────────────────────────

class AdminFaqListView(APIView):
    """GET /api/v1/admin/faq/ — admin 전체 목록
    POST /api/v1/admin/faq/ — FAQ 작성
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = Faq.objects.select_related('author').order_by('category', 'order', 'created_at')
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(AdminFaqSerializer(page, many=True).data)

    def post(self, request):
        serializer = AdminFaqWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        faq = serializer.save(author=request.user)
        return Response(AdminFaqSerializer(faq).data, status=status.HTTP_201_CREATED)


class AdminFaqDetailView(APIView):
    """PATCH /api/v1/admin/faq/:id/ — FAQ 수정
    DELETE /api/v1/admin/faq/:id/ — FAQ 삭제
    """
    permission_classes = [IsAdmin]

    def patch(self, request, faq_id):
        faq = get_object_or_404(Faq, pk=faq_id)
        serializer = AdminFaqWriteSerializer(faq, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(AdminFaqSerializer(faq).data)

    def delete(self, request, faq_id):
        faq = get_object_or_404(Faq, pk=faq_id)
        faq.delete()
        return Response({'deleted': True, 'id': faq_id})


# ─── F. 인파 노트(BlogPost) ──────────────────────────────────────────

def _blog_copy_warnings(post):
    """게시(is_published=True) 상태일 때만 카피 검사 경고 반환(비차단)."""
    if not post.is_published:
        return []
    return scan_blog_content({
        'title': post.title,
        'body': post.body,
        'excerpt': post.excerpt,
    })


class AdminBlogPostListView(APIView):
    """GET /api/v1/admin/blog/ — admin 전체 목록 (초안 포함, ?status=/?category=)
    POST /api/v1/admin/blog/ — 인파 노트 작성 (multipart = 커버 업로드 지원)
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = BlogPost.objects.select_related('author')
        status_param = request.query_params.get('status')
        if status_param == 'published':
            qs = qs.filter(is_published=True)
        elif status_param == 'draft':
            qs = qs.filter(is_published=False)
        category = request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)
        qs = qs.order_by('-created_at')
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(
            AdminBlogPostSerializer(page, many=True, context={'request': request}).data)

    def post(self, request):
        serializer = AdminBlogPostSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        post = serializer.save(author=request.user)
        # 게시 상태로 생성되면 게시 시각 스탬프.
        if post.is_published and post.published_at is None:
            post.published_at = timezone.now()
            post.save(update_fields=['published_at'])
        data = AdminBlogPostSerializer(post, context={'request': request}).data
        data['warnings'] = _blog_copy_warnings(post)  # 비차단 카피 경고
        return Response(data, status=status.HTTP_201_CREATED)


class AdminBlogPostDetailView(APIView):
    """GET /api/v1/admin/blog/:id/ — 상세 (초안 포함)
    PATCH /api/v1/admin/blog/:id/ — 수정 (multipart = 커버 업로드 지원)
    DELETE /api/v1/admin/blog/:id/ — 소프트 삭제(is_published=False, DB 보존)
    """
    permission_classes = [IsAdmin]

    def get(self, request, post_id):
        post = get_object_or_404(BlogPost, pk=post_id)
        return Response(AdminBlogPostSerializer(post, context={'request': request}).data)

    def patch(self, request, post_id):
        post = get_object_or_404(BlogPost, pk=post_id)
        serializer = AdminBlogPostSerializer(
            post, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # 처음 게시로 전환되는 시점에만 게시 시각 스탬프(재게시는 보존).
        if post.is_published and post.published_at is None:
            post.published_at = timezone.now()
            post.save(update_fields=['published_at'])
        data = AdminBlogPostSerializer(post, context={'request': request}).data
        data['warnings'] = _blog_copy_warnings(post)  # 비차단 카피 경고
        return Response(data)

    def delete(self, request, post_id):
        post = get_object_or_404(BlogPost, pk=post_id)
        # 소프트 삭제 — 공개 화면에서만 숨김, DB 보존 (Notice 삭제 규약 동형).
        post.is_published = False
        post.save(update_fields=['is_published', 'updated_at'])
        return Response({'deleted': True, 'id': post_id})


# ─── J. 운영 설정 — 요금제 한도 ────────────────────────────────────

class AdminPlanListView(APIView):
    """GET /api/v1/admin/settings/plans/ — Plan 목록 + 한도 조회."""
    permission_classes = [IsAdmin]

    def get(self, request):
        plans = Plan.objects.all().order_by('code')
        return Response(AdminPlanSerializer(plans, many=True).data)


class AdminPlanDetailView(APIView):
    """PATCH /api/v1/admin/settings/plans/:code/ — Plan 한도 변경."""
    permission_classes = [IsAdmin]

    def patch(self, request, plan_code):
        plan = get_object_or_404(Plan, code=plan_code)
        serializer = AdminPlanUpdateSerializer(plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(AdminPlanSerializer(plan).data)


# ─── K. 약관 버전 ──────────────────────────────────────────────────

class AdminPolicyVersionListView(APIView):
    """GET  /api/v1/admin/settings/policy-versions/ — 약관 버전 목록 (최신순)
    POST /api/v1/admin/settings/policy-versions/ — 약관 버전 등록
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = PolicyVersion.objects.all()
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        serializer = PolicyVersionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = PolicyVersionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        policy = serializer.save()
        return Response(
            PolicyVersionSerializer(policy).data,
            status=status.HTTP_201_CREATED,
        )


# ─── L. 기능 플래그 (읽기 전용 — env 우회 차단) ─────────────────────

class AdminFeatureFlagsView(APIView):
    """GET /api/v1/admin/settings/flags/ — 현재 env 기반 기능 플래그 읽기 전용 반환.

    ★ 컴플라이언스 레드라인: PATCH(runtime 변경) 미구현.
      COMPARE_PUBLISH_ENABLED 등 컴플라이언스 게이트는 env 변수로만 제어.
      'env로 제어, 코드 우회 금지' 원칙 (CLAUDE.md 설정·기능 게이트 항목).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from django.conf import settings as dj_settings
        data = {
            'FREE_TIER_UNLIMITED': getattr(dj_settings, 'FREE_TIER_UNLIMITED', True),
            'COMPARE_AI_ENABLED': getattr(dj_settings, 'COMPARE_AI_ENABLED', False),
            'COMPARE_PUBLISH_ENABLED': getattr(dj_settings, 'COMPARE_PUBLISH_ENABLED', False),
            'ANALYZE_MEDICAL_ENABLED': getattr(dj_settings, 'ANALYZE_MEDICAL_ENABLED', False),
            'BOOKING_ENABLED': getattr(dj_settings, 'BOOKING_ENABLED', True),
            'OCR_VERIFY_ENABLED': getattr(dj_settings, 'OCR_VERIFY_ENABLED', True),
            'REQUIRE_CUSTOMER_SELF_CONSENT': getattr(dj_settings, 'REQUIRE_CUSTOMER_SELF_CONSENT', False),
            'GOOGLE_OAUTH_ENABLED': getattr(dj_settings, 'GOOGLE_OAUTH_ENABLED', False),
        }
        serializer = FeatureFlagsSerializer(data)
        return Response(serializer.data)


# ─── 관리자 전용 인증 ────────────────────────────────────────────────

class AdminLoginView(APIView):
    """POST /api/v1/admin/auth/login/
    admin 전용 이메일/비밀번호 로그인.
    is_admin=False 설계사는 403 반환 (설계사 로그인과 완전 분리).
    """
    authentication_classes = []  # 공개 로그인 — 전역 TokenAuthentication 비활성화.
    # (브라우저 localStorage 의 헌 토큰이 로그인 요청에 실리면 뷰 실행 전 401 로 막히던 버그 방지.)
    permission_classes = []  # AllowAny
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'admin_login'  # 무차별 대입 방어(IP 기준)

    def post(self, request):
        from django.conf import settings as dj_settings
        from django.contrib.auth import authenticate
        from django.core.cache import cache
        from rest_framework.authtoken.models import Token

        email = (request.data.get('email') or '').lower().strip()
        password = request.data.get('password', '')

        if not email or not password:
            return Response(
                {'code': 'MISSING_CREDENTIALS', 'detail': '이메일과 비밀번호를 입력해주세요.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 무차별 대입 잠금 — 일반 로그인(LoginView)과 동일 정책. 관리자 자격은 최고가치라 필수.
        lock_key = f'admin-login-fail:{email}'
        if cache.get(lock_key, 0) >= dj_settings.LOGIN_MAX_ATTEMPTS:
            return Response(
                {'code': 'ACCOUNT_LOCKED', 'detail': '로그인 시도가 많아 잠겼습니다. 10분 후 다시 시도하세요.'},
                status=status.HTTP_423_LOCKED,
            )

        user = authenticate(request, username=email, password=password)
        if user is None:
            fails = cache.get(lock_key, 0) + 1
            cache.set(lock_key, fails, dj_settings.LOGIN_LOCKOUT_SECONDS)
            return Response(
                {'code': 'INVALID_CREDENTIALS', 'detail': '이메일 또는 비밀번호가 올바르지 않습니다.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cache.delete(lock_key)  # 비밀번호 정답 → 실패 카운터 해제

        # is_admin 게이트 — 설계사 계정으로 admin 콘솔 접근 차단
        profile = getattr(user, 'profile', None)
        if not (profile and profile.is_admin):
            return Response(
                {'code': 'FORBIDDEN', 'detail': '관리자 계정이 아닙니다.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'admin': {
                'id': user.id,
                'email': user.email,
            },
        })


class AdminUsageView(APIView):
    """설계사별 기능 사용량 집계 — GET /api/v1/admin/usage/?days=30 (IsAdmin).

    NorthStarEvent(sender=설계사, event_type별)를 집계해 '누가 어떤 기능을 많이 쓰나'를 본다.
    ★ 데모 계정(@inpa.local)은 제외. 사용량 많은 순 정렬 + 기능별 총합.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from datetime import timedelta

        from django.db.models import Count

        from inpa.analytics.models import NorthStarEvent

        try:
            days = int(request.query_params.get('days', 30))
        except (TypeError, ValueError):
            days = 30

        qs = (NorthStarEvent.objects
              .filter(sender__isnull=False)
              .exclude(sender__email__iendswith='@inpa.local'))  # 데모 계정 제외
        if days > 0:
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))

        rows = (qs.values('sender_id', 'sender__email', 'sender__profile__name', 'event_type')
                  .annotate(c=Count('id')))

        users = {}
        for r in rows:
            uid = r['sender_id']
            u = users.setdefault(uid, {
                'user_id': uid,
                'email': r['sender__email'],
                'name': r['sender__profile__name'] or '',
                'total': 0,
                'events': {},  # event_type → count
            })
            u['events'][r['event_type']] = r['c']
            u['total'] += r['c']

        ranked = sorted(users.values(), key=lambda x: x['total'], reverse=True)

        feature_totals = {}
        for u in ranked:
            for k, v in u['events'].items():
                feature_totals[k] = feature_totals.get(k, 0) + v

        return Response({
            'days': days,
            'active_users': len(ranked),
            'feature_totals': feature_totals,  # event_type → 전체 합
            'users': ranked,                   # 사용량 내림차순
        })


class AdminClaudeCostView(APIView):
    """Claude 호출당 비용·파싱결과 계측 — GET /api/v1/admin/claude-cost/?days=30 (IsAdmin).

    ★ 프리런치 리뷰 #17. billing.ClaudeApiLog(호출 1건=1행, PII-safe: 토큰수·추정비용·
    outcome enum·회사코드 int·매칭/미매칭 건수만)를 창(days) 내 집계한다.
    cost_krw 는 어드민 관측용 **추정치**(billing/pricing.py — 토큰×모델계열단가×환율)이며
    실제 청구서와 다를 수 있다(§6 정직성 — 판정어 없이 사실 수치만).
    ★ 데모 계정(@inpa.local)은 제외(AdminUsageView 관례). user=null(예: /d 공개 경로)
    행은 데모가 아니므로 제외되지 않는다.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from datetime import timedelta

        from django.db.models import Count, Sum
        from django.db.models.functions import TruncDate

        from inpa.billing.models import ClaudeApiLog

        try:
            days = int(request.query_params.get('days', 30))
        except (TypeError, ValueError):
            days = 30

        qs = ClaudeApiLog.objects.exclude(user__email__iendswith='@inpa.local')
        if days > 0:
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))

        total_calls = qs.count()
        total_cost_krw = qs.aggregate(s=Sum('cost_krw'))['s'] or 0

        # outcome 분포 + 성공률
        outcome_counts = {
            row['parse_outcome']: row['c']
            for row in qs.values('parse_outcome').annotate(c=Count('id'))
        }
        success_count = outcome_counts.get(ClaudeApiLog.OUTCOME_SUCCESS, 0)
        success_rate = round(success_count / total_calls * 100, 1) if total_calls else None

        # 기능(action)별 호출수·추정비용
        by_action = [
            {'action': r['action'], 'calls': r['calls'], 'cost_krw': r['cost'] or 0}
            for r in (
                qs.values('action')
                  .annotate(calls=Count('id'), cost=Sum('cost_krw'))
                  .order_by('-cost')
            )
        ]

        # 일별 추정비용 추이
        daily = [
            {
                'date': r['day'].isoformat() if r['day'] else None,
                'calls': r['calls'],
                'cost_krw': r['cost'] or 0,
            }
            for r in (
                qs.annotate(day=TruncDate('created_at'))
                  .values('day')
                  .annotate(calls=Count('id'), cost=Sum('cost_krw'))
                  .order_by('day')
            )
        ]

        # 회사별 미매칭율 — carrier_code 미상(null)은 제외, 총 0건(matched+unmatched)도 제외.
        by_carrier = []
        for r in (
            qs.exclude(carrier_code__isnull=True)
              .values('carrier_code')
              .annotate(matched=Sum('matched_count'), unmatched=Sum('unmatched_count'))
        ):
            matched = r['matched'] or 0
            unmatched = r['unmatched'] or 0
            total = matched + unmatched
            if total == 0:
                continue
            by_carrier.append({
                'carrier_code': r['carrier_code'],
                'matched': matched,
                'unmatched': unmatched,
                'unmatched_rate': round(unmatched / total * 100, 1),
            })
        by_carrier.sort(key=lambda x: -x['unmatched_rate'])

        from django.conf import settings as dj_settings

        return Response({
            'days': days,
            'total_calls': total_calls,
            'total_cost_krw': total_cost_krw,
            'cost_is_estimate': True,  # ★ FE 표기용 — 판정어 아닌 사실 플래그
            'usd_krw_rate': float(getattr(dj_settings, 'CLAUDE_USD_KRW_RATE', 1400.0)),
            'success_rate': success_rate,
            'outcome_counts': outcome_counts,
            'by_action': by_action,
            'daily': daily,
            'by_carrier': by_carrier,
        })


class AdminActivationFunnelView(APIView):
    """가입→인증→첫 고객→첫 분석→첫 공유→활성화 코호트 퍼널 — GET /api/v1/admin/activation-funnel/?days=30 (IsAdmin).

    프리런치 리뷰 #16. ★ 이름 충돌 주의: `dashboard/aggregation.py::compute_funnel`은 설계사
    영업단계(DB/TA/FA/청약) 퍼널이며 이 뷰와 전혀 무관하다.

    새 이벤트 배선 없이 기존 타임스탬프로 전부 계산(이벤트는 누락 위험 → 타임스탬프가 더 견고):
      signup(User.date_joined) → verified(Profile.email_verified_at not null) →
      first_customer(MIN Customer.created_at per owner) →
      first_analysis(MIN CustomerInsurance.created_at per customer__owner) →
      first_share(MIN Customer.share_sent_at per owner, not null) →
      activated(첫분석 AND 첫공유 모두 가입 후 ACTIVATION_WINDOW_DAYS(기본 7일) 이내).
    가입 코호트(창 days 내 date_joined) 기준, @inpa.local 제외(AdminUsageView 관례).
    사실 카운트 + 단계별(직전 단계 대비) 전환율(%)만(§6 판정어 금지). UTM(utm_source, 없으면
    'direct') 별 가입·활성화 분해 + 활성화 코호트 평균 활성화 소요일수도 함께 반환.
    성능: 코호트 크기와 무관하게 고정 쿼리 수(코호트 1 + owner별 MIN 3, N+1 없음).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from datetime import timedelta

        from django.conf import settings as dj_settings
        from django.db.models import Min

        from inpa.analytics.models import NorthStarEvent
        from inpa.customers.models import Customer
        from inpa.insurances.models import CustomerInsurance

        try:
            days = int(request.query_params.get('days', 30))
        except (TypeError, ValueError):
            days = 30
        days = max(0, min(days, 3650))  # 과대 입력(OverflowError)·음수 방어. 0=전체.

        window_days = int(getattr(dj_settings, 'ACTIVATION_WINDOW_DAYS', 7) or 7)
        window = timedelta(days=window_days)

        cohort_qs = User.objects.exclude(email__iendswith='@inpa.local')
        if days > 0:
            cohort_qs = cohort_qs.filter(date_joined__gte=timezone.now() - timedelta(days=days))
        cohort_rows = list(cohort_qs.values(
            'id', 'date_joined', 'profile__email_verified_at', 'profile__utm_source'))
        cohort_ids = [r['id'] for r in cohort_rows]

        def _first_per_owner(qs, owner_field, ts_field):
            """owner_id(코호트 한정) → 그 owner의 최초 ts_field. 서브쿼리 1개, N+1 없음."""
            if not cohort_ids:
                return {}
            rows = (qs.filter(**{f'{owner_field}__in': cohort_ids})
                      .values(owner_field)
                      .annotate(first_ts=Min(ts_field)))
            return {r[owner_field]: r['first_ts'] for r in rows}

        first_customer = _first_per_owner(Customer.objects, 'owner', 'created_at')
        first_analysis = _first_per_owner(CustomerInsurance.objects, 'customer__owner', 'created_at')
        # ★ 첫 공유는 불변 이벤트(NorthStarEvent.SHARE_CREATED, append-only)의 최초 시각으로 계산.
        #   Customer.share_sent_at 은 공유 재발급마다 덮어써지는 가변 필드라, 무관한 재발급이
        #   과거 코호트의 '활성화'를 사후에 뒤집는다(리뷰 blocker). sender=설계사(owner).
        first_share = _first_per_owner(
            NorthStarEvent.objects.filter(event_type=NorthStarEvent.SHARE_CREATED),
            'sender', 'created_at')

        signup_count = len(cohort_rows)
        verified_count = 0
        first_customer_count = 0
        first_analysis_count = 0
        first_share_count = 0
        activated_count = 0
        activation_days = []
        utm_breakdown = {}  # source(또는 'direct') → {signups, activated}

        for row in cohort_rows:
            uid = row['id']
            joined = row['date_joined']
            # ★ 단계 중첩(monotonic 퍼널): 각 단계는 직전 단계 도달자 부분집합으로만 집계.
            #   전환율이 100%를 넘는 착시(미인증 유저의 수동 고객 생성 등 엣지) 방지.
            reached_verified = row['profile__email_verified_at'] is not None
            reached_customer = reached_verified and (uid in first_customer)
            reached_analysis = reached_customer and (uid in first_analysis)
            reached_share = reached_analysis and (uid in first_share)

            activated = False
            if reached_analysis and reached_share:
                a_ts, s_ts = first_analysis[uid], first_share[uid]
                if (a_ts - joined) <= window and (s_ts - joined) <= window:
                    activated = True
                    activation_days.append((max(a_ts, s_ts) - joined).total_seconds() / 86400)

            verified_count += reached_verified
            first_customer_count += reached_customer
            first_analysis_count += reached_analysis
            first_share_count += reached_share
            activated_count += activated

            source = (row['profile__utm_source'] or '').strip() or 'direct'
            bucket = utm_breakdown.setdefault(source, {'signups': 0, 'activated': 0})
            bucket['signups'] += 1
            bucket['activated'] += int(activated)

        def _rate(numer, denom):
            return round(numer / denom * 100, 1) if denom else None

        steps = [
            {'step': 'signup', 'label': '가입', 'count': signup_count, 'conversion_rate': None},
            {'step': 'verified', 'label': '이메일 인증', 'count': verified_count,
             'conversion_rate': _rate(verified_count, signup_count)},
            {'step': 'first_customer', 'label': '첫 고객 등록', 'count': first_customer_count,
             'conversion_rate': _rate(first_customer_count, verified_count)},
            {'step': 'first_analysis', 'label': '첫 분석', 'count': first_analysis_count,
             'conversion_rate': _rate(first_analysis_count, first_customer_count)},
            {'step': 'first_share', 'label': '첫 공유 링크', 'count': first_share_count,
             'conversion_rate': _rate(first_share_count, first_analysis_count)},
            {'step': 'activated', 'label': '활성화', 'count': activated_count,
             'conversion_rate': _rate(activated_count, first_share_count)},
        ]
        utm_sources = [
            {'source': k, 'signups': v['signups'], 'activated': v['activated'],
             'activation_rate': _rate(v['activated'], v['signups'])}
            for k, v in sorted(utm_breakdown.items(), key=lambda kv: -kv[1]['signups'])
        ]
        avg_days_to_activation = (
            round(sum(activation_days) / len(activation_days), 1) if activation_days else None
        )

        return Response({
            'days': days,
            'activation_window_days': window_days,
            'signup_count': signup_count,
            'activated_count': activated_count,
            'activation_rate': _rate(activated_count, signup_count),
            'steps': steps,
            'utm_sources': utm_sources,
            'avg_days_to_activation': avg_days_to_activation,
        })


class AdminLogoutView(APIView):
    """POST /api/v1/admin/auth/logout/ — 토큰 폐기."""
    permission_classes = [IsAdmin]

    def post(self, request):
        from rest_framework.authtoken.models import Token
        Token.objects.filter(user=request.user).delete()
        return Response({'message': '로그아웃되었습니다.'})
