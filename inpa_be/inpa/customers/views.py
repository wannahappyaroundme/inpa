"""고객 도메인 ViewSet (dev/12 §5 API 계약).

가시성 강제 3중(dev/02 §0):
  ① OwnedQuerySetMixin — get_queryset이 owner=request.user로 필터(관리자 bypass)
  ② permission [IsAuthenticated, IsEmailVerified, IsOwner] — 객체 단위 소유자 확인
  ③ 하위 라우트(태그/가족/병력/동의)는 부모 customer를 owner 격리 쿼리로 잡아 격리

★ 병력 등록 게이트(dev/12 §0 원칙 2): Customer.consent_overseas_at(국외이전 동의) 없으면
  CustomerMedicalHistory 생성을 412(PRECONDITION_FAILED)로 물리 차단. UI 숨김은 방어가 아니다.
"""
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from inpa.core.mixins import OwnedQuerySetMixin
from inpa.core.permissions import IsEmailVerified, IsOwner

from .models import (
    ConsentLog, Customer, CustomerMedicalHistory, CustomerTag, FamilyMember,
    PlannerBaseline,
)
from .serializers import (
    ConsentLogSerializer, CustomerListSerializer, CustomerSerializer,
    CustomerMedicalHistorySerializer, CustomerTagSerializer,
    FamilyMemberSerializer, PlannerBaselineSerializer,
)


class CustomerViewSet(OwnedQuerySetMixin, viewsets.ModelViewSet):
    """고객 CRUD — 소유자 전용.

    GET /api/v1/customers/            목록 (경량 카드 직렬화)
    POST /api/v1/customers/           생성 (owner 자동 주입)
    GET/PATCH/DELETE /api/v1/customers/{pk}/  상세/수정/삭제 (본인만)
    """
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    queryset = Customer.objects.all()

    def get_queryset(self):
        # N+1 가드 — 목록/상세 모두 태그·가족·병력 prefetch
        return (super().get_queryset()
                .prefetch_related('tags', 'family_members', 'medical_histories'))

    def get_serializer_class(self):
        if self.action == 'list':
            return CustomerListSerializer
        return CustomerSerializer


class CustomerTagViewSet(OwnedQuerySetMixin, viewsets.ModelViewSet):
    """고객 태그 CRUD — 소유자 전용. /api/v1/customer-tags/"""
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = CustomerTagSerializer
    queryset = CustomerTag.objects.all()


class _CustomerScopedViewSet(viewsets.ModelViewSet):
    """부모 Customer를 URL(customer_pk)에서 잡아 owner 격리하는 하위 라우트 공통 베이스.

    소유자 격리는 customer__owner 경유 — FamilyMember/병력/동의는 직접 owner FK가 없다.
    부모 Customer가 본인 것이 아니면 404(존재 자체를 숨김 — owner 격리의 안전한 디폴트).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]
    parent_lookup = 'customer_pk'

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def get_customer(self):
        qs = Customer.objects.all()
        if not self._is_admin():
            qs = qs.filter(owner=self.request.user)
        try:
            return qs.get(pk=self.kwargs[self.parent_lookup])
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')

    def get_queryset(self):
        return super().get_queryset().filter(customer=self.get_customer())

    def perform_create(self, serializer):
        serializer.save(customer=self.get_customer())


class FamilyMemberViewSet(_CustomerScopedViewSet):
    """가족구성원 CRUD — /api/v1/customers/{customer_pk}/family/"""
    serializer_class = FamilyMemberSerializer
    queryset = FamilyMember.objects.all()


class CustomerMedicalHistoryViewSet(_CustomerScopedViewSet):
    """병력 CRUD — /api/v1/customers/{customer_pk}/medical/

    ★ 동의 게이트: 부모 Customer.consent_overseas_at이 없으면 등록(create)을 412로 거부.
      병력 = 민감정보 = 국외이전 동의 대상(dev/12 §0 원칙 2).
    """
    serializer_class = CustomerMedicalHistorySerializer
    queryset = CustomerMedicalHistory.objects.all()

    def create(self, request, *args, **kwargs):
        customer = self.get_customer()
        if customer.consent_overseas_at is None:
            return Response(
                {'code': 'CONSENT_OVERSEAS_REQUIRED',
                 'detail': '병력 등록 전 고객의 국외이전 동의가 필요합니다.'},
                status=status.HTTP_412_PRECONDITION_FAILED)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(customer=customer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ConsentLogViewSet(_CustomerScopedViewSet):
    """동의 로그 — /api/v1/customers/{customer_pk}/consents/ (append-only).

    INSERT만 허용. UPDATE/DELETE는 감사 무결성 위반이므로 차단. 철회는 revoke 액션으로 revoked_at 기록.
    overseas_medical 동의 생성 시 Customer.consent_overseas_at 스냅샷 동기화.
    """
    serializer_class = ConsentLogSerializer
    queryset = ConsentLog.objects.all()
    http_method_names = ['get', 'post', 'head', 'options']  # PUT/PATCH/DELETE 차단(append-only)

    def perform_create(self, serializer):
        customer = self.get_customer()
        ip = self.request.META.get('REMOTE_ADDR')
        log = serializer.save(customer=customer, ip=ip)
        # 국외이전 동의 → Customer 스냅샷 동기화 (detect 412 게이트 해제)
        if log.scope == ConsentLog.SCOPE_OVERSEAS_MEDICAL and customer.consent_overseas_at is None:
            customer.consent_overseas_at = log.agreed_at
            customer.save(update_fields=['consent_overseas_at'])


class PlannerBaselineViewSet(OwnedQuerySetMixin, viewsets.ModelViewSet):
    """설계사 기준선 CRUD — 소유자 전용. /api/v1/planner-baselines/

    ★ 준법 통제점. baseline_source가 null이면 분석은 neutral 강제(다음 라운드).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = PlannerBaselineSerializer
    queryset = PlannerBaseline.objects.all()
