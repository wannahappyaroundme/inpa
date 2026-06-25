"""고객 도메인 ViewSet (dev/12 §5 API 계약).

가시성 강제 3중(dev/02 §0):
  ① OwnedQuerySetMixin — get_queryset이 owner=request.user로 필터(관리자 bypass)
  ② permission [IsAuthenticated, IsEmailVerified, IsOwner] — 객체 단위 소유자 확인
  ③ 하위 라우트(태그/가족/병력/동의)는 부모 customer를 owner 격리 쿼리로 잡아 격리

★ 병력 등록 게이트(dev/12 §0 원칙 2): Customer.consent_overseas_at(국외이전 동의) 없으면
  CustomerMedicalHistory 생성을 412(PRECONDITION_FAILED)로 물리 차단. UI 숨김은 방어가 아니다.
"""
from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.core.mixins import OwnedQuerySetMixin
from inpa.core.permissions import IsEmailVerified, IsOwner

from .models import (
    ConsentLog, Customer, CustomerMedicalHistory, CustomerTag, FamilyMember,
    PlannerBaseline,
)
from .presets import (
    BASELINE_SOURCE_PRESET, PRESET_NOTE, PRESET_ORIGIN_V0, PRESET_V0,
    iter_preset_rows,
)
from .serializers import (
    ConsentLogSerializer, CustomerListSerializer, CustomerSerializer,
    CustomerMedicalHistorySerializer, CustomerTagSerializer,
    FamilyMemberSerializer, PlannerBaselineSerializer,
)
from .tokens import make_consent_token


class CustomerViewSet(OwnedQuerySetMixin, viewsets.ModelViewSet):
    """고객 CRUD — 소유자 전용.

    GET /api/v1/customers/            목록 (경량 카드 직렬화)
    POST /api/v1/customers/           생성 (owner 자동 주입)
    GET/PATCH/DELETE /api/v1/customers/{pk}/  상세/수정/삭제 (본인만)
    """
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    queryset = Customer.objects.all()

    def get_queryset(self):
        # N+1 가드 — 태그·가족·병력·동의(마케팅 배지) prefetch + 직업등급 select_related
        return (super().get_queryset()
                .select_related('job_code')
                .prefetch_related('tags', 'family_members', 'medical_histories',
                                  'consent_logs'))

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

    ★ 베타 게이트(council 2026-06-21 P0-3): settings.ANALYZE_MEDICAL_ENABLED=False면
      병력 등록 자체를 403으로 차단(베타 미수집). 법무 검토 완료 후 True로 flip.
    ★ 동의 게이트: 부모 Customer.consent_overseas_at이 없으면 등록(create)을 412로 거부.
      병력 = 민감정보 = 국외이전 동의 대상(dev/12 §0 원칙 2).
    """
    serializer_class = CustomerMedicalHistorySerializer
    queryset = CustomerMedicalHistory.objects.all()

    def create(self, request, *args, **kwargs):
        if not getattr(settings, 'ANALYZE_MEDICAL_ENABLED', False):
            return Response(
                {'code': 'MEDICAL_DISABLED_BETA',
                 'detail': '베타 기간에는 병력(민감정보)을 수집하지 않습니다. '
                           '민감정보 처리는 법무 검토 완료 후 활성화됩니다.'},
                status=status.HTTP_403_FORBIDDEN)
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
    ★ P3c(council 2026-06-21): 설계사가 찍는 동의는 subject=planner_attested(대리 기록)으로만
      남고, 국외이전 게이트(Customer.consent_overseas_at)를 열지 못한다. 게이트는 고객 본인
      동의(공개 /c/<token> 또는 셀프진단)만 연다 — 대리동의 무효 소지 차단.
    """
    serializer_class = ConsentLogSerializer
    queryset = ConsentLog.objects.all()
    http_method_names = ['get', 'post', 'head', 'options']  # PUT/PATCH/DELETE 차단(append-only)

    def perform_create(self, serializer):
        customer = self.get_customer()
        ip = self.request.META.get('REMOTE_ADDR')
        # 설계사 기록 = planner_attested. 스냅샷(consent_overseas_at)은 건드리지 않는다(대리동의 강등).
        serializer.save(customer=customer, ip=ip,
                        subject=ConsentLog.SUBJECT_PLANNER_ATTESTED)


class ConsentRequestCreateView(APIView):
    """동의 요청 링크 생성 — POST /api/v1/customers/<customer_pk>/consent-requests/ (P3c).

    설계사(소유자)가 본인 고객의 '국외이전 동의 요청' 링크를 만든다. 고객이 본인 기기에서
    /c/<token> 로 열어 직접 동의해야 OCR 게이트가 열린다(설계사 대리동의 불가).
    링크 전달은 FE에서 클립보드 복사/카톡 열기까지만(자동발송 없음 — 정직성 레드라인).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def _get_customer(self, pk):
        qs = Customer.objects.all()
        if not self._is_admin():
            qs = qs.filter(owner=self.request.user)  # owner 격리 — 타 설계사 고객은 404
        try:
            return qs.get(pk=pk)
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')

    def post(self, request, customer_pk):
        customer = self._get_customer(customer_pk)
        token = make_consent_token(customer)
        base = (getattr(settings, 'FRONTEND_BASE_URL', '') or '').rstrip('/')
        return Response(
            {'token': token,
             'consent_url': f'{base}/c/{token}',
             'already_consented': customer.consent_overseas_at is not None},
            status=status.HTTP_201_CREATED)


class PlannerBaselineViewSet(OwnedQuerySetMixin, viewsets.ModelViewSet):
    """설계사 기준선 CRUD — 소유자 전용. /api/v1/planner-baselines/

    ★ 준법 통제점. baseline_source가 null이면 분석은 neutral 강제.
    """
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = PlannerBaselineSerializer
    queryset = PlannerBaseline.objects.all()

    @action(detail=False, methods=['post'], url_path='apply-preset')
    def apply_preset(self, request):
        """v0 스타터 프리셋을 요청 설계사(owner)에게 일괄 생성.

        POST /api/v1/planner-baselines/apply-preset/  {product_group:int}

        ★ V0 스타터 데이터 한계(정직성 레드라인):
          - 프리셋 수치(recommend_min/max)는 약관·금감원 출처와 대조 검증되지 않은 v0 가설값.
          - 적용 시 baseline_source='preset' 이 되어 분석 mode 가 neutral → graded 로 켜진다.
            따라서 응답 note 로 '검토 후 사용'을 항상 고지한다.

        멱등: 동일 owner 의 UNIQUE 스코프(owner·coverage_key·product_group·age_band·gender)가
          이미 있으면 건너뛴다(덮어쓰지 않음 — 설계사가 수정한 값을 프리셋이 훼손하지 않도록).
          → 재호출 시 created=0.

        응답: {created:int, preset_origin:'v0_starter', note:str}
        """
        # ── product_group 검증 ──────────────────────────────────────────
        raw = request.data.get('product_group')
        if raw is None:
            raise ValidationError({'product_group': 'product_group(상품군)은 필수입니다.'})
        try:
            product_group = int(raw)
        except (TypeError, ValueError):
            raise ValidationError({'product_group': '정수 상품군 코드여야 합니다.'})

        valid_groups = dict(PlannerBaseline.PRODUCT_GROUP_CHOICES)
        if product_group not in valid_groups:
            raise ValidationError({
                'product_group': f'알 수 없는 상품군입니다. 허용: {sorted(valid_groups)}'})

        owner = request.user

        # ── 이미 보유한 스코프 키 집합 (멱등 — 중복 생성 회피) ───────────────
        # UNIQUE(owner, coverage_key, product_group, age_band, gender) 와 동일 키.
        existing = set(
            PlannerBaseline.objects
            .filter(owner=owner, product_group=product_group)
            .values_list('coverage_key', 'age_band', 'gender')
        )

        to_create = []
        for coverage_key, age_band, gender, recommend_min, recommend_max in \
                iter_preset_rows(product_group):
            if (coverage_key, age_band, gender) in existing:
                continue  # 이미 있음 — 설계사 값/이전 적용 보존
            to_create.append(PlannerBaseline(
                owner=owner,
                coverage_key=coverage_key,
                product_group=product_group,
                age_band=age_band,
                gender=gender,
                recommend_min=recommend_min,
                recommend_max=recommend_max,
                unit=1,  # 만원 (STANDARD_TREE 단위)
                baseline_source=BASELINE_SOURCE_PRESET,  # ★ graded 게이트 ON
                preset_origin=PRESET_ORIGIN_V0,
                is_active=True,
            ))

        if to_create:
            # ignore_conflicts: 동시성 경합 시에도 UNIQUE 충돌을 안전하게 흡수(멱등 보강).
            PlannerBaseline.objects.bulk_create(to_create, ignore_conflicts=True)

        return Response(
            {
                'created': len(to_create),
                'preset_origin': PRESET_ORIGIN_V0,
                'note': PRESET_NOTE,
            },
            status=status.HTTP_201_CREATED,
        )
