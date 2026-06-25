"""판촉물 도메인 뷰 (dev/21 §4 API 계약).

설계사 공개 엔드포인트:
  GET    /api/v1/promotion/samples/             샘플 목록 (?category, ?available)
  GET    /api/v1/promotion/samples/:id/         샘플 상세 (form_fields 포함)
  POST   /api/v1/promotion/orders/              주문 생성 (크레딧 promotion 차감)
  GET    /api/v1/promotion/orders/              내 주문 목록 (OwnedQuerySetMixin)
  GET    /api/v1/promotion/orders/:id/          내 주문 상세 + 상태 타임라인
  DELETE /api/v1/promotion/orders/:id/          주문 취소 (pending 상태만)

관리자 전용:
  GET/POST/PATCH/DELETE /api/v1/admin/promotion/samples/        샘플 CRUD
  POST                  /api/v1/admin/promotion/samples/:id/images/   이미지 추가
  DELETE                /api/v1/admin/promotion/samples/:id/images/:img_id/  이미지 삭제
  GET                   /api/v1/admin/promotion/orders/          전체 주문 목록 + 필터
  PATCH                 /api/v1/admin/promotion/orders/:id/status/  상태 변경

★ 가시성 강제 (dev/02 §0, dev/21 §5):
  - 샘플: 인증 설계사 전원 읽기, 관리자만 쓰기.
  - 주문: OwnedQuerySetMixin(owner) — 설계사는 본인 것만, 관리자는 전체.

★ 정직성 레드라인 (dev/21 §7.2):
  - 주문 = 예약 접수. 실제 제작·발송은 관리자 수동.
  - 상태 변경 시 인앱 Notification만 발송 (카카오·SMS 자동발송 X).
  - form_response는 owner + 관리자만 접근 — 타 설계사 응답에 절대 미포함.

★ 크레딧 (dev/21 §6, dev/02 §16):
  - POST /promotion/orders/ → check_and_consume(user, 'promotion').
  - 한도 초과 → 402 Payment Required (LimitExceeded → credit_exhausted 변환).
  - 베타: FREE_TIER_UNLIMITED=True → 무차감 통과.
"""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.billing.credit import LimitExceeded, check_and_consume
from inpa.core.mixins import OwnedQuerySetMixin
from inpa.core.permissions import IsAdmin, IsEmailVerified, IsOwner

from .models import (
    PromotionDownload,
    PromotionOrder,
    PromotionOrderStatusLog,
    PromotionSample,
    PromotionSampleImage,
)
from .serializers import (
    AdminOrderListSerializer,
    AdminOrderStatusPatchSerializer,
    AdminSampleWriteSerializer,
    PromotionOrderCreateSerializer,
    PromotionOrderListSerializer,
    PromotionOrderSerializer,
    PromotionSampleDetailSerializer,
    PromotionSampleImageWriteSerializer,
    PromotionSampleListSerializer,
)


# ─── 헬퍼 ─────────────────────────────────────────────────────────────

def _credit_exhausted_response(exc: LimitExceeded, user) -> Response:
    """LimitExceeded → 402 Payment Required (dev/02 §16, AC-O4)."""
    from inpa.billing.models import Subscription
    sub = Subscription.objects.select_related('plan').filter(user=user).first()
    membership = sub.plan.code if sub else 'free'
    return Response(
        {
            'detail': f'이번 달 한도({exc.limit}건)를 모두 사용했어요.',
            'code': 'credit_exhausted',
            'kind': exc.action,
            'membership': membership,
            'limit': exc.limit,
            'used': exc.current,
        },
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


def _send_order_status_notification(order: PromotionOrder) -> None:
    """상태 변경 시 주문 소유자에게 인앱 Notification 발송.

    정직성 레드라인: 설계사 본인 Notification만. 카카오·SMS 없음.
    알림 실패는 무시 — 주문 상태 변경 트랜잭션을 막으면 안 됨.
    """
    if order.owner is None:
        return
    try:
        from inpa.notifications.models import NotifType, Notification
        status_label = order.get_status_display()
        sample_name = order.sample.name if order.sample else '판촉물'
        ready = (bool(order.sample and order.sample.is_digital)
                 and order.status == PromotionOrder.STATUS_COMPLETED)
        Notification.objects.create(
            owner=order.owner,
            notif_type=NotifType.PROMOTION_DIGITAL_READY if ready else NotifType.PROMOTION_STATUS,
            title=(f'전자자료 준비 완료: {sample_name}' if ready
                   else f'판촉물 주문 상태 변경: {status_label}'),
            body=((f'"{sample_name}" 전자자료가 준비됐어요. 운영팀이 전달해 드립니다.' if ready
                   else f'"{sample_name}" 주문이 "{status_label}" 상태로 변경되었습니다.')
                  + (f' 관리자 메모: {order.admin_note}' if order.admin_note else '')),
        )
    except Exception:
        # 알림 실패 무시 — 주문 주 동작 보호
        pass


def _notify_admins(notif_type, title, body) -> None:
    """관리자(profile.is_admin) 전원에게 인앱 알림(전자자료 요청 등). 실패 무시."""
    try:
        from django.contrib.auth import get_user_model
        from inpa.notifications.models import Notification
        User = get_user_model()
        for admin in User.objects.filter(profile__is_admin=True):
            Notification.objects.create(owner=admin, notif_type=notif_type, title=title, body=body)
    except Exception:
        pass


class PromotionDigitalRequestView(APIView):
    """POST /api/v1/promotion/samples/<id>/request/ — 전자자료 1회 무료 / 2회차+ 어드민 큐 (PM 06.24).

    1회차: PromotionDownload(is_free) 기록 + digital_file URL 반환(무료 다운로드, 크레딧 무차감).
    2회차+: PromotionOrder(pending) 생성 + 관리자 알림 → 운영팀이 수동 제작·발송.
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def post(self, request, sample_id):
        sample = get_object_or_404(PromotionSample, pk=sample_id)
        if not sample.is_digital:
            return Response({'detail': '전자자료가 아니에요.', 'code': 'NOT_DIGITAL'},
                            status=status.HTTP_400_BAD_REQUEST)
        prior = PromotionDownload.objects.filter(owner=request.user, sample=sample).count()
        if prior == 0:
            PromotionDownload.objects.create(owner=request.user, sample=sample, is_free=True)
            url = request.build_absolute_uri(sample.digital_file.url) if sample.digital_file else None
            return Response({'mode': 'free', 'file_url': url,
                             'detail': '첫 1회는 무료예요. 바로 다운로드하세요.'})
        with transaction.atomic():
            order = PromotionOrder.objects.create(
                owner=request.user, sample=sample, status=PromotionOrder.STATUS_PENDING,
                form_response={'channel': 'digital', 'note': '전자자료 추가 요청(2회차+)'})
            PromotionOrderStatusLog.objects.create(
                order=order, to_status=PromotionOrder.STATUS_PENDING, changed_by=request.user)
            PromotionDownload.objects.create(owner=request.user, sample=sample, is_free=False, order=order)
        _notify_admins(
            'promotion_digital_requested',
            f'전자자료 요청: {sample.name}',
            f'{request.user.email} 설계사가 "{sample.name}" 전자자료 추가 제작을 요청했어요.')
        return Response({'mode': 'queued', 'order_id': order.id,
                         'detail': '요청이 접수됐어요. 운영팀이 제작해 전달해 드려요.'},
                        status=status.HTTP_201_CREATED)


# ─── 설계사 공개 — 샘플 ───────────────────────────────────────────────

class PromotionSampleListView(APIView):
    """샘플 목록 (인증 설계사 전원 읽기).

    GET /api/v1/promotion/samples/
    ?category=달력  — 카테고리 필터
    ?available=true — 주문 가능 항목만
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def get(self, request):
        qs = PromotionSample.objects.prefetch_related('images').order_by('sort_order', '-created_at')

        category = request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)

        available = request.query_params.get('available', '').lower()
        if available == 'true':
            qs = qs.filter(is_available=True)

        serializer = PromotionSampleListSerializer(qs, many=True)
        return Response({'count': qs.count(), 'results': serializer.data})


class PromotionSampleDetailView(APIView):
    """샘플 상세 — form_fields 포함 (인증 설계사 전원 읽기).

    GET /api/v1/promotion/samples/:id/
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def get(self, request, pk):
        sample = get_object_or_404(
            PromotionSample.objects.prefetch_related('images'), pk=pk
        )
        return Response(PromotionSampleDetailSerializer(sample).data)


# ─── 설계사 공개 — 주문 ───────────────────────────────────────────────

class PromotionOrderListCreateView(APIView):
    """주문 목록(GET) + 주문 생성(POST).

    GET  /api/v1/promotion/orders/    내 주문 목록 (본인 소유만 — AC-O2)
    POST /api/v1/promotion/orders/    주문 생성 (크레딧 차감 — AC-O1, AC-O4)
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def get(self, request):
        qs = (
            PromotionOrder.objects
            .filter(owner=request.user)
            .select_related('sample')
            .order_by('-created_at')
        )
        serializer = PromotionOrderListSerializer(qs, many=True)
        return Response({'count': qs.count(), 'results': serializer.data})

    def post(self, request):
        serializer = PromotionOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 크레딧 차감 (한도 초과 시 402)
        try:
            check_and_consume(request.user, 'promotion')
        except LimitExceeded as exc:
            return _credit_exhausted_response(exc, request.user)

        with transaction.atomic():
            order = PromotionOrder.objects.create(
                owner=request.user,
                sample=data['sample'],
                form_response=data.get('form_response', {}),
                status=PromotionOrder.STATUS_PENDING,
            )
            # 최초 생성 시 pending 상태 로그 1건 생성 (AC-O1)
            PromotionOrderStatusLog.objects.create(
                order=order,
                to_status=PromotionOrder.STATUS_PENDING,
                changed_by=request.user,
            )

        return Response(
            PromotionOrderSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )


class PromotionOrderDetailView(APIView):
    """주문 상세 + 상태 타임라인 (본인 소유 + 관리자).

    GET    /api/v1/promotion/orders/:id/   주문 상세 (status_logs 포함 — AC-S3)
    DELETE /api/v1/promotion/orders/:id/   주문 취소 (pending 상태만 — AC-O3)
    """
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]

    def _get_order(self, request, pk) -> PromotionOrder:
        """설계사는 본인 주문만, 관리자는 전체 조회."""
        from inpa.core.permissions import _is_admin
        qs = PromotionOrder.objects.select_related('sample').prefetch_related('status_logs')
        if _is_admin(request.user):
            return get_object_or_404(qs, pk=pk)
        return get_object_or_404(qs, pk=pk, owner=request.user)

    def get(self, request, pk):
        order = self._get_order(request, pk)
        return Response(PromotionOrderSerializer(order).data)

    def delete(self, request, pk):
        """주문 취소 — pending 상태만 허용 (실제 삭제 X, 상태 전이).

        AC-O3: reviewing 이후 취소 시도 → 400.
        """
        order = self._get_order(request, pk)

        if order.status != PromotionOrder.STATUS_PENDING:
            return Response(
                {'detail': '이미 처리 중인 주문은 취소할 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            order.transition_to(PromotionOrder.STATUS_CANCELLED, changed_by=request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PromotionOrderSerializer(order).data)


# ─── 관리자 전용 — 샘플 CRUD ─────────────────────────────────────────

class AdminSampleListCreateView(APIView):
    """관리자 샘플 목록 + 등록.

    GET  /api/v1/admin/promotion/samples/
    POST /api/v1/admin/promotion/samples/
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = PromotionSample.objects.prefetch_related('images').order_by('sort_order', '-created_at')
        category = request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)
        serializer = PromotionSampleDetailSerializer(qs, many=True)
        return Response({'count': qs.count(), 'results': serializer.data})

    def post(self, request):
        serializer = AdminSampleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample = serializer.save()
        return Response(
            PromotionSampleDetailSerializer(sample).data,
            status=status.HTTP_201_CREATED,
        )


class AdminSampleDetailView(APIView):
    """관리자 샘플 상세·수정·삭제.

    GET    /api/v1/admin/promotion/samples/:id/
    PATCH  /api/v1/admin/promotion/samples/:id/
    DELETE /api/v1/admin/promotion/samples/:id/
    """
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        sample = get_object_or_404(PromotionSample.objects.prefetch_related('images'), pk=pk)
        return Response(PromotionSampleDetailSerializer(sample).data)

    def patch(self, request, pk):
        sample = get_object_or_404(PromotionSample, pk=pk)
        serializer = AdminSampleWriteSerializer(sample, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        sample.refresh_from_db()
        return Response(PromotionSampleDetailSerializer(sample).data)

    def delete(self, request, pk):
        sample = get_object_or_404(PromotionSample, pk=pk)
        sample.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminSampleImageCreateView(APIView):
    """관리자 샘플 이미지 추가.

    POST /api/v1/admin/promotion/samples/:id/images/
    """
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        sample = get_object_or_404(PromotionSample, pk=pk)
        serializer = PromotionSampleImageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image = serializer.save(sample=sample)
        return Response(
            {'id': image.pk, 'url': image.image_url, 'is_primary': image.is_primary, 'sort_order': image.sort_order},
            status=status.HTTP_201_CREATED,
        )


class AdminSampleImageDeleteView(APIView):
    """관리자 샘플 이미지 삭제.

    DELETE /api/v1/admin/promotion/samples/:sample_id/images/:img_id/
    """
    permission_classes = [IsAdmin]

    def delete(self, request, pk, img_id):
        image = get_object_or_404(PromotionSampleImage, pk=img_id, sample_id=pk)
        image.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── 관리자 전용 — 주문 ──────────────────────────────────────────────

class AdminOrderListView(APIView):
    """관리자 전체 주문 목록 + 필터.

    GET /api/v1/admin/promotion/orders/
    ?status=pending           — 상태 필터 (복수: ?status=pending&status=reviewing)
    ?date_from=2026-06-01     — 시작일 (created_at__date__gte)
    ?date_to=2026-06-30       — 종료일 (created_at__date__lte)
    ?search=홍길동             — 설계사 이메일 검색
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = (
            PromotionOrder.objects
            .select_related('owner', 'sample')
            .order_by('-created_at')
        )

        statuses = request.query_params.getlist('status')
        if statuses:
            qs = qs.filter(status__in=statuses)

        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        search = request.query_params.get('search')
        if search:
            qs = qs.filter(owner__email__icontains=search)

        serializer = AdminOrderListSerializer(qs, many=True)
        return Response({'count': qs.count(), 'results': serializer.data})


class AdminOrderStatusPatchView(APIView):
    """관리자 주문 상태 변경 + 메모.

    PATCH /api/v1/admin/promotion/orders/:id/status/

    허용된 상태 전이만 처리 (AC-S1, AC-S2, AC-A2).
    상태 변경 시 PromotionOrderStatusLog 1건 생성 (AC-S2).
    admin_note 업데이트 설계사 상세에 즉시 반영 (AC-A3).
    상태 변경 시 설계사 인앱 Notification 발송 (정직성 레드라인: 인앱만, AC-C3).
    """
    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        order = get_object_or_404(
            PromotionOrder.objects.select_related('owner', 'sample'), pk=pk
        )

        serializer = AdminOrderStatusPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        new_status = data['status']
        update_fields = []

        # admin_note·발송정보 먼저 반영 (상태 전이와 분리)
        if 'admin_note' in data:
            order.admin_note = data['admin_note']
            update_fields.append('admin_note')
        if 'tracking_number' in data:
            order.tracking_number = data['tracking_number']
            update_fields.append('tracking_number')
        if 'carrier' in data:
            order.carrier = data['carrier']
            update_fields.append('carrier')
        if update_fields:
            update_fields.append('updated_at')
            order.save(update_fields=update_fields)

        # 상태 전이 + 이력 로그 (AC-S1, AC-S2)
        try:
            with transaction.atomic():
                log = order.transition_to(new_status, changed_by=request.user)
                # 전이 시 메모 기록
                if data.get('admin_note'):
                    log.note = data['admin_note']
                    log.save(update_fields=['note'])
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # 인앱 알림 발송 (설계사 본인 대상 — 카카오·SMS 없음)
        _send_order_status_notification(order)

        return Response(PromotionOrderSerializer(order).data)
