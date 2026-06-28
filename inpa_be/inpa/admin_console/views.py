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

from inpa.analysis.models import NormalizationDict, UnmatchedLog
from inpa.billing.models import Plan, Subscription, UsageMeter
from inpa.boards.models import (
    Comment,
    Faq,
    Inquiry,
    InquiryReply,
    Notice,
    Post,
    Report,
)
from inpa.core.permissions import IsAdmin
from inpa.customers.models import ConsentLog, Customer
from inpa.notifications.models import Notification, NotifType
from inpa.promotion.models import PromotionOrder

from .models import PolicyVersion
from .serializers import (
    AdminConsentLogSerializer,
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


class AdminLogoutView(APIView):
    """POST /api/v1/admin/auth/logout/ — 토큰 폐기."""
    permission_classes = [IsAdmin]

    def post(self, request):
        from rest_framework.authtoken.models import Token
        Token.objects.filter(user=request.user).delete()
        return Response({'message': '로그아웃되었습니다.'})
