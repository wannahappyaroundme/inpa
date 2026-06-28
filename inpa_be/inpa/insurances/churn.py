"""환수 레이더(A/S) — 유지율(13/25회차)·환수예상액 집계 + 수기입력.

★ 정직성/컴플라이언스 레드라인:
  - 납입회차·환수예상액은 설계사 '수기입력' 추정치. 정확액은 보험사/회사 전산 권위 → 모두 '추정' 라벨.
  - owner 전용 격리(CustomerInsurance.customer__owner). 타 설계사 데이터 접근 불가.
  - Claude 호출 없음(국외이전 무관). 알림 자동발송 없음(클립보드/카톡열기까지만 — 본 라운드는 표시만).
  - 보유(portfolio_type=1) 계약만 대상. 제안(=2)은 가상이라 환수 대상 아님.

엔드포인트(config/urls.py → /api/v1/ 마운트, insurances/urls.py 배선):
  GET   /api/v1/churn-radar/             ChurnRadarView     (집계 + 전체 보유정책 리스트)
  PATCH /api/v1/insurances/<pk>/churn/   InsuranceChurnView (4개 환수 필드 수기 저장)
"""
import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.core.permissions import IsEmailVerified
from inpa.customers.models import Customer
from inpa.insurances.models import CustomerInsurance
from inpa.notifications.models import NotifType, Notification

RISK_DUE_WINDOW_DAYS = 7
CHARGEBACK_PERIOD = 25  # 25회차 전까지 환수 구간(보수적 기준)

CHURN_DISCLAIMER = (
    '납입회차·환수예상액은 설계사가 입력한 추정치입니다. '
    '정확한 환수금액과 납입상태는 보험사·회사 전산에서 확인하세요.'
)


def _persistency_stage(period):
    """납입회차 → 유지율 단계. 13/25회차가 환수·정착의 분기점."""
    if period is None:
        return 'unknown'
    if period < 13:
        return 'pre_13'
    if period < CHARGEBACK_PERIOD:
        return 'pre_25'
    return 'safe'


def _assess(ci, today):
    """한 보유계약 위험 평가 → (is_at_risk, reason, stage)."""
    stage = _persistency_stage(ci.current_payment_period)
    in_window = ci.current_payment_period is None or ci.current_payment_period < CHARGEBACK_PERIOD
    reasons = []
    if ci.payment_status == 2:
        reasons.append('연체')
    elif ci.payment_status == 3:
        reasons.append('납입중단')
    if ci.next_payment_date is not None:
        days = (ci.next_payment_date - today).days
        if days < 0:
            reasons.append('납입일 경과')
        elif days <= RISK_DUE_WINDOW_DAYS:
            reasons.append(f'납입 D-{days}')
    is_at_risk = bool(reasons) and in_window
    return is_at_risk, ' · '.join(reasons), stage


def _serialize(ci, today):
    is_at_risk, reason, stage = _assess(ci, today)
    return {
        'insurance_id': ci.id,
        'customer_id': ci.customer_id,
        'customer_name': ci.customer.name,
        'insurance_name': ci.name,
        'current_payment_period': ci.current_payment_period,
        'payment_status': ci.payment_status,
        'next_payment_date': ci.next_payment_date.isoformat() if ci.next_payment_date else None,
        'expected_recovery_amount': ci.expected_recovery_amount,
        'persistency_stage': stage,
        'is_at_risk': is_at_risk,
        'risk_reason': reason,
        'is_cancelled': ci.is_cancelled,
        'cancelled_at': ci.cancelled_at,
    }


class _OwnerScopedMixin:
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def _owned_held_insurances(self):
        """보유(portfolio_type=1) 계약을 owner 스코프로. 관리자는 전체."""
        qs = CustomerInsurance.objects.select_related('customer').filter(portfolio_type=1)
        if not self._is_admin():
            qs = qs.filter(customer__owner=self.request.user)
        return qs


class ChurnRadarView(_OwnerScopedMixin, APIView):
    """환수 위험 집계 + 보유정책 리스트(수기입력 대상)."""

    def get(self, request):
        today = datetime.date.today()
        items = [_serialize(ci, today) for ci in self._owned_held_insurances()]
        at_risk = [it for it in items if it['is_at_risk']]
        expected_total = sum(it['expected_recovery_amount'] or 0 for it in at_risk)
        # 위험 먼저, 그다음 다음납입일 빠른 순(없으면 맨 뒤).
        items.sort(key=lambda it: (not it['is_at_risk'], it['next_payment_date'] or '9999-99-99'))
        return Response({
            'risk_count': len(at_risk),
            'expected_recovery_total': expected_total,
            'items': items,
            'disclaimer': CHURN_DISCLAIMER,
        })


class InsuranceChurnView(_OwnerScopedMixin, APIView):
    """PATCH /api/v1/insurances/<pk>/churn/ — 4개 환수 필드 수기 저장(owner 전용)."""
    ALLOWED = ('current_payment_period', 'payment_status', 'next_payment_date',
               'expected_recovery_amount', 'is_cancelled', 'cancelled_at')

    def patch(self, request, pk):
        try:
            ci = self._owned_held_insurances().get(pk=pk)
        except CustomerInsurance.DoesNotExist:
            raise NotFound('보험을 찾을 수 없습니다.')

        errors = {}
        for field in self.ALLOWED:
            if field not in request.data:
                continue
            val = request.data.get(field)
            if field == 'is_cancelled':
                # 해지 여부(bool). 빈값 = False.
                ci.is_cancelled = str(val).lower() in ('1', 'true', 'yes', 'on')
                continue
            if val in ('', None):
                setattr(ci, field, None)
                continue
            if field == 'cancelled_at':
                # 해지일은 'YYYY-MM-DD' 문자열로 보관(형식 검증만).
                parsed = None
                for fmt in ('%Y-%m-%d', '%Y.%m.%d', '%Y/%m/%d'):
                    try:
                        parsed = datetime.datetime.strptime(val, fmt).date()
                        break
                    except (ValueError, TypeError):
                        parsed = None
                if parsed is None:
                    errors[field] = '날짜 형식(YYYY-MM-DD)이 올바르지 않습니다.'
                else:
                    ci.cancelled_at = parsed.isoformat()
                continue
            if field == 'next_payment_date':
                parsed = None
                for fmt in ('%Y-%m-%d', '%Y.%m.%d', '%Y/%m/%d'):
                    try:
                        parsed = datetime.datetime.strptime(val, fmt).date()
                        break
                    except (ValueError, TypeError):
                        parsed = None
                if parsed is None:
                    errors[field] = '날짜 형식(YYYY-MM-DD)이 올바르지 않습니다.'
                else:
                    ci.next_payment_date = parsed
            elif field == 'payment_status':
                try:
                    iv = int(val)
                except (ValueError, TypeError):
                    errors[field] = '납입상태 값이 올바르지 않습니다.'
                    continue
                if iv not in (1, 2, 3):
                    errors[field] = '납입상태는 1(정상)/2(연체)/3(납입중단)만 허용됩니다.'
                else:
                    ci.payment_status = iv
            else:  # current_payment_period, expected_recovery_amount
                try:
                    iv = int(val)
                except (ValueError, TypeError):
                    errors[field] = '숫자만 입력하세요.'
                    continue
                if iv < 0:
                    errors[field] = '0 이상 값만 허용됩니다.'
                else:
                    setattr(ci, field, iv)

        if errors:
            return Response({'code': 'VALIDATION', 'errors': errors},
                            status=status.HTTP_400_BAD_REQUEST)

        ci.save(update_fields=list(self.ALLOWED) + ['updated_at'])
        if 'is_cancelled' in request.data or 'cancelled_at' in request.data:
            Customer.objects.filter(pk=ci.customer_id).update(last_contacted_at=timezone.now())
        return Response(_serialize(ci, datetime.date.today()))


class ChurnSyncAlertsView(_OwnerScopedMixin, APIView):
    """POST /api/v1/churn-radar/sync-alerts/ — 환수 위험을 인앱 Notification으로 생성(cron 아님).

    ★ 위험 보유계약마다 고객당 당일 1건(unique 제약 + get_or_create dedup). 자동발송 없음(인앱만).
    홈 진입 시 조용히 호출 → 벨에 반영.
    """

    def post(self, request):
        today = datetime.date.today()
        created = 0
        for ci in self._owned_held_insurances():
            is_at_risk, reason, _ = _assess(ci, today)
            if not is_at_risk:
                continue
            _, was_created = Notification.objects.get_or_create(
                owner=request.user,
                notif_type=NotifType.UNPAID_D_ALERT,
                target_date=today,
                customer=ci.customer,
                defaults={
                    'title': f'{ci.customer.name}님 환수 위험',
                    'body': f'{ci.name or "보유 보험"} — {reason}. 환수(차지백) 전 확인하세요.',
                },
            )
            if was_created:
                created += 1
        return Response({'created': created})
