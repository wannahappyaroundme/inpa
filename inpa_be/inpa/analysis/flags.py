"""담보 사전 피드백 루프 — 설계사용 API (2026-07-09, 프리런치 리뷰 #26).

엔드포인트 (analysis/urls.py 에서 customers/<id>/ 네임스페이스로 마운트):
  GET  /api/v1/customers/<customer_pk>/coverage-cases/?detail_id=
    해당 고객·해당 표준 담보(leaf)에 연결된 담보 케이스 목록. 플래그 모달용.
  POST /api/v1/customers/<customer_pk>/coverage-flags/
    {analysis_detail_id, case_id?, note?} → CoverageFlag 생성 + 어드민 알림 fan-out.

★ 격리: 부모 Customer 를 owner 스코프 쿼리로 잡는다(없으면 404 = 존재 은폐).
  히트맵(views.py::CustomerHeatmapView)과 동일 패턴 — 어드민은 read 우회.
★ 스냅샷: raw_name/company 는 서버가 case 에서 복사(클라이언트 입력 불신).
  case.raw_name 이 비면(레거시/직접 입력) detail.name 폴백.
"""
import logging

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.core.permissions import IsEmailVerified
from inpa.customers.models import Customer
from inpa.insurances.models import CustomerInsuranceDetail

from .models import AnalysisDetail, CoverageFlag

logger = logging.getLogger(__name__)


def _notify_admins(notif_type, title, body) -> None:
    """관리자(profile.is_admin) 전원 인앱 알림 (promotion/views.py 패턴). 실패 무시."""
    try:
        from django.contrib.auth import get_user_model
        from inpa.notifications.models import Notification
        User = get_user_model()
        for admin in User.objects.filter(profile__is_admin=True):
            Notification.objects.create(owner=admin, notif_type=notif_type, title=title, body=body)
    except Exception:
        pass


class _CustomerScopedView(APIView):
    """owner 스코프 Customer 확보 공통 (히트맵 뷰와 동일 패턴).

    owner_only=True 면 어드민 read 우회 없이 소유자만 통과 — 쓰기(플래그 생성)는
    남의 고객에 행을 만드는 행위라 어드민도 우회 금지(우회 관례는 READ 한정).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def _get_customer(self, customer_pk, owner_only=False):
        qs = Customer.objects.all()
        if owner_only or not self._is_admin():
            qs = qs.filter(owner=self.request.user)
        try:
            return qs.get(pk=customer_pk)
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')


class CustomerCoverageCasesView(_CustomerScopedView):
    """GET /api/v1/customers/<customer_pk>/coverage-cases/?detail_id=

    응답: [{case_id, insurance_id, insurance_title, name, raw_name, assurance_amount}]
    name = 카탈로그 담보명(detail.name), raw_name = 증권에서 읽은 원문(빈 값 가능).
    """

    def get(self, request, customer_pk):
        customer = self._get_customer(customer_pk)

        try:
            detail_id = int(request.query_params.get('detail_id'))
        except (TypeError, ValueError):
            return Response({'code': 'DETAIL_ID_REQUIRED',
                             'detail': 'detail_id(표준 담보 id)가 필요합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        cases = (
            CustomerInsuranceDetail.objects
            .filter(insurance__customer=customer, detail__analysis_detail__id=detail_id)
            .select_related('insurance', 'detail')
            .order_by('insurance_id', 'id')
        )
        return Response([
            {
                'case_id': c.id,
                'insurance_id': c.insurance_id,
                'insurance_title': c.insurance.name,
                'name': c.detail.name,
                'raw_name': c.raw_name or '',
                'assurance_amount': c.assurance_amount,
            }
            for c in cases
        ])


class CustomerCoverageFlagView(_CustomerScopedView):
    """POST /api/v1/customers/<customer_pk>/coverage-flags/

    body: {analysis_detail_id: int, case_id?: int, note?: str(<=300)}
    서버가 raw_name_snapshot(case.raw_name → detail.name 폴백)·company(보험의 감지
    보험사 코드)를 스냅샷하고, 어드민 전원에게 검수 알림을 fan-out 한다.
    """

    def post(self, request, customer_pk):
        # ★ 쓰기 = 소유자 전용(어드민 read 우회 없음) — 타인 고객이면 404(존재 은폐).
        customer = self._get_customer(customer_pk, owner_only=True)

        # ── 1) 표준 담보 leaf 검증 ──
        try:
            detail_id = int(request.data.get('analysis_detail_id'))
        except (TypeError, ValueError):
            return Response({'code': 'ANALYSIS_DETAIL_REQUIRED',
                             'detail': 'analysis_detail_id(표준 담보 id)가 필요합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        leaf = AnalysisDetail.objects.filter(pk=detail_id).first()
        if leaf is None:
            return Response({'code': 'ANALYSIS_DETAIL_NOT_FOUND',
                             'detail': '표준 담보를 찾을 수 없습니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # ── 2) case (선택) — 반드시 이 고객의 케이스여야 함(타인/타고객 = 404 은폐) ──
        case = None
        case_id = request.data.get('case_id')
        if case_id not in (None, ''):
            try:
                case_id = int(case_id)
            except (TypeError, ValueError):
                raise NotFound('담보 내역을 찾을 수 없습니다.')
            case = (
                CustomerInsuranceDetail.objects
                .filter(pk=case_id, insurance__customer=customer)
                .select_related('insurance', 'detail')
                .first()
            )
            if case is None:
                raise NotFound('담보 내역을 찾을 수 없습니다.')

        note = str(request.data.get('note') or '').strip()[:300]

        # ── 3) 서버측 스냅샷 (SET_NULL 로 원본이 지워져도 검수 가능하도록 복사) ──
        raw_name_snapshot = ''
        company = None
        if case is not None:
            raw_name_snapshot = (case.raw_name or case.detail.name or '')[:200]
            company = case.insurance.company

        flag = CoverageFlag.objects.create(
            owner=request.user,
            customer=customer,
            analysis_detail=leaf,
            case=case,
            raw_name_snapshot=raw_name_snapshot,
            company=company,
            note=note,
        )

        # ── 4) 어드민 fan-out (실패해도 주 동작 보호) ──
        shown = raw_name_snapshot or leaf.name
        _notify_admins(
            'coverage_flag_requested',
            f'담보 위치 확인 요청: {leaf.name}',
            f'{request.user.email} 설계사가 "{shown}" 담보의 위치 확인을 요청했어요. '
            '관리자 콘솔의 정규화 화면에서 검토할 수 있어요.')

        return Response({'id': flag.id, 'status': flag.status},
                        status=status.HTTP_201_CREATED)
