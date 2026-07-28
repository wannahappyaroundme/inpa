"""billing 도메인 뷰 (dev/23 §4 API 계약).

엔드포인트:
  GET  /api/v1/billing/plans/                     — 요금제 목록 (공개 AllowAny)
  GET  /api/v1/billing/usage/                     — 내 사용량 조회 (IsAuthenticated)
  GET  /api/v1/admin/billing/usage/               — 관리자 전체 사용량 (IsAdmin)
  PATCH /api/v1/admin/billing/subscription/<uid>/ — 관리자 구독 수동 변경 (IsAdmin)

★ 가시성 강제:
  - /billing/usage/ : request.user로 자동 스코프. user_id 파라미터 주입 차단.
  - /admin/* : IsAdmin 권한만.

★ 한도 초과 응답 shape (dev/23 §4.4, AC-B3):
  {detail, code, kind, membership, limit, used, upgrade_url}  HTTP 402
  → credit.py의 LimitExceeded를 뷰에서 잡아 변환. 이 파일에 예시 포함.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from datetime import date
import hashlib
import hmac
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView
from django.shortcuts import redirect

from inpa.analytics.events import log_billing_event
from inpa.analytics.models import NorthStarEvent
from inpa.core.internal_accounts import block_showcase_external_action
from inpa.core.permissions import BlocksShowcaseExternalActions, IsAdmin

from .coupons import CouponError, redeem_coupon
from .coupons import hold_recurring_coupon
from .cancellation import cancel_billing
from .calendar import new_anchor, period_for
from .agreements import (
    BillingFlowError,
    billing_status,
    complete_card_registration,
    confirm_first_charge,
    start_card_registration,
    vat_inclusive_amount,
)
from .legal_texts import INITIAL_BILLING_CONSENT_VERSION
from .gates import card_registration_enabled
from .notices import (
    NoticeError,
    dismiss_notice,
    lease_notice,
    mark_notice_rendered,
    notice_payload,
)
from .credit import LimitExceeded  # noqa: F401 — 뷰 사용 예시용 (실제 뷰에서 직접 catch)
from .models import (
    BenefitGrantLedger,
    BillingAgreement,
    ManualBenefitReview,
    Plan,
    Subscription,
    UsageMeter,
    VerifiedPhoneIdentity,
)
from .phone_verification import (
    OTP_TTL_SECONDS,
    PhoneVerificationError,
    create_manual_benefit_review,
    mask_kr_mobile,
    normalize_kr_mobile,
    request_phone_verification,
    verify_otp_challenge,
)
from .sms import SolapiProviderError
from .serializers import (
    AdminBenefitReviewDecisionSerializer,
    AdminSubscriptionPatchSerializer,
    CardRegistrationCompleteSerializer,
    CardRegistrationStartSerializer,
    BillingNoticeDeviceSerializer,
    CouponRedeemSerializer,
    FirstChargeReconfirmationSerializer,
    ManualBenefitReviewRequestSerializer,
    ManualBenefitReviewSerializer,
    PhoneVerificationConfirmSerializer,
    PhoneVerificationRequestSerializer,
    PlanSerializer,
    RecurringCouponPreflightSerializer,
)

User = get_user_model()

# action별 한국어 label (dev/23 §5.1 화면 구성 일치)
_ACTION_LABELS = {
    'ocr': '증권 OCR 분析',
    'ai_compare': '증권 비교',
    'analysis': 'AI 분析·메시지',
    'promotion': '판촉물 주문',
    'customer': '고객 추가',
}
_ACTION_ORDER = ['ocr', 'ai_compare', 'analysis', 'promotion', 'customer']


def _build_usage_response(user) -> dict:
    """설계사 1인의 사용량 응답 dict 구성 (내부 헬퍼).

    sub가 없으면 Free Plan으로 폴백 (비정상 상태 방어).
    Django OneToOneField 역방향 캐시를 우회해 항상 최신 DB 상태를 조회한다.
    """
    from .credit import resolve_effective_plan

    # ★ 표시 한도 = 실제 강제 한도. resolve_effective_plan 이 만료·해지 구독을 Free 로
    #   폴백하므로 화면에 보이는 한도가 402 로 실제 막히는 한도와 일치한다.
    plan = resolve_effective_plan(user)

    # select_related로 plan까지 단일 쿼리, 캐시 우회 — 폴백 여부 판정용.
    sub = (
        Subscription.objects
        .select_related('plan')
        .filter(user=user)
        .first()
    )
    if sub is not None:
        effective = (
            sub.status in ('active', 'trial')
            and (sub.expires_at is None or sub.expires_at > timezone.now())
        )
        # 폴백이 발동하면(만료·해지) 상태를 '만료'로 표기해 Free 한도 표시와 맞춘다.
        sub_data = {
            'status': sub.status if effective else 'expired',
            'billing_cycle': sub.billing_cycle,
            'expires_at': sub.expires_at.isoformat() if sub.expires_at else None,
        }
    else:
        # 가입 시그널 누락 방어 — Free Plan 폴백
        sub_data = {'status': 'active', 'billing_cycle': 'monthly', 'expires_at': None}

    ym = UsageMeter.current_month()

    # 현재 월 meters (없으면 count=0으로 처리)
    meters = {
        m.action: m.count
        for m in UsageMeter.objects.filter(user=user, year_month=ym)
    }

    usage_list = []
    for action in _ACTION_ORDER:
        lim = plan.get_limit(action) if plan else None
        cnt = meters.get(action, 0)
        remaining = (lim - cnt) if lim is not None else None
        usage_list.append({
            'action': action,
            'label': _ACTION_LABELS[action],
            'count': cnt,
            'limit': lim,
            'remaining': remaining,
        })

    return {
        'plan': {
            'code': plan.code if plan else 'free',
            'display_name': plan.display_name if plan else '무료',
            'price_krw': plan.price_krw if plan else 0,
        },
        'subscription': sub_data,
        'year_month': ym,
        'usage': usage_list,
    }


class PlanListView(APIView):
    """요금제 목록 (공개 AllowAny — 비로그인 GET 허용, dev/23 §7).

    GET /api/v1/billing/plans/
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # Token 없이도 접근 가능

    def get(self, request):
        plans = Plan.objects.filter(is_active=True).order_by('price_krw')
        serializer = PlanSerializer(plans, many=True)
        return Response(serializer.data)


class BillingEventView(APIView):
    """진행 중인 결제 이벤트 플래그 (공개 AllowAny — 비로그인 GET 허용).

    GET /api/v1/billing/event/  → {"first_paid_bonus_enabled": bool}

    첫 유료 결제 +1개월 보너스 이벤트가 실제로 켜져 있는지(RuntimeConfig 런타임 토글).
    랜딩·업그레이드 모달의 이벤트 문구는 이 값이 True일 때만 노출해, 꺼져 있는
    이벤트를 약속하지 않도록 한다(§6 정직성). 연 결제 할인(2개월 무료 = 실제 가격)은
    이 플래그와 무관하게 항상 노출한다.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # Token 없이도 접근 가능

    def get(self, request):
        from .models import RuntimeConfig
        cfg = RuntimeConfig.solo()
        return Response({'first_paid_bonus_enabled': cfg.first_paid_bonus_enabled})


class BillingUsageView(APIView):
    """내 사용량 조회 (IsAuthenticated — 본인 데이터만).

    GET /api/v1/billing/usage/
    user_id 쿼리 파라미터 주입 차단: 서버가 request.user로만 스코프.
    AC-B4 검증 포인트.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = _build_usage_response(request.user)
        return Response(data)


class CouponRedeemView(APIView):
    """무료 쿠폰 사용 — 설계사가 발급받은 코드를 입력해 Plus를 한시적으로 부여받는다.

    POST /api/v1/billing/coupons/redeem/  body {code}
      성공 200 {plan_code, plan_display_name, expires_at, duration_days}
      실패 404(없음)/409(이미 사용)/410(만료·소진·비활성) + {code, detail}
    """
    permission_classes = [
        IsAuthenticated,
        BlocksShowcaseExternalActions,
    ]

    def post(self, request):
        serializer = CouponRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = redeem_coupon(request.user, serializer.validated_data['code'])
        except CouponError as exc:
            status_map = {
                'not_found': status.HTTP_404_NOT_FOUND,
                'already': status.HTTP_409_CONFLICT,
                'active_plan': status.HTTP_409_CONFLICT,
            }
            code = status_map.get(exc.code, status.HTTP_410_GONE)
            return Response({'code': exc.code, 'detail': str(exc)}, status=code)
        return Response(result, status=status.HTTP_200_OK)


def _phone_verification_error_response(exc):
    status_map = {
        'invalid_phone': status.HTTP_400_BAD_REQUEST,
        'phone_verification_failed': status.HTTP_400_BAD_REQUEST,
        'phone_verification_required': status.HTTP_409_CONFLICT,
        'manual_benefit_review_not_required':
            status.HTTP_409_CONFLICT,
        'phone_identity_key_rotation_required':
            status.HTTP_503_SERVICE_UNAVAILABLE,
        'phone_request_cooldown': status.HTTP_429_TOO_MANY_REQUESTS,
        'phone_request_limited': status.HTTP_429_TOO_MANY_REQUESTS,
        'phone_rate_limit_unavailable':
            status.HTTP_503_SERVICE_UNAVAILABLE,
        'phone_verification_setup_required':
            status.HTTP_503_SERVICE_UNAVAILABLE,
    }
    payload = {
        'code': exc.code,
        'detail': exc.detail,
    }
    return Response(
        payload,
        status=status_map.get(
            exc.code,
            status.HTTP_400_BAD_REQUEST,
        ),
    )


def _phone_provider_error_response():
    return Response(
        {
            'code': 'phone_verification_temporarily_unavailable',
            'detail': '인증번호 발송을 다시 준비하고 있어요. 잠시 뒤 시도해 주세요.',
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class FreeTrialPhoneRequestView(APIView):
    permission_classes = [
        IsAuthenticated,
        BlocksShowcaseExternalActions,
    ]

    def post(self, request):
        serializer = PhoneVerificationRequestSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        try:
            challenge = request_phone_verification(
                user=request.user,
                raw_phone=serializer.validated_data['phone'],
                ip_address=BaseThrottle().get_ident(request),
            )
        except PhoneVerificationError as exc:
            return _phone_verification_error_response(exc)
        except SolapiProviderError:
            return _phone_provider_error_response()
        return Response({
            'challenge_id': str(challenge.pk),
            'expires_in_seconds': OTP_TTL_SECONDS,
            'phone_masked': (
                f'010-****-{challenge.phone_last4}'
            ),
        })


class FreeTrialPhoneVerifyView(APIView):
    permission_classes = [
        IsAuthenticated,
        BlocksShowcaseExternalActions,
    ]

    def post(self, request):
        if not getattr(
            settings,
            'FREE_TRIAL_PHONE_VERIFICATION_ENABLED',
            False,
        ):
            return _phone_verification_error_response(
                PhoneVerificationError(
                    'phone_verification_setup_required',
                    '휴대전화 인증 설정을 확인하고 있어요. 잠시 뒤 다시 시도해 주세요.',
                ),
            )
        serializer = PhoneVerificationConfirmSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        try:
            canonical = normalize_kr_mobile(
                serializer.validated_data['phone'],
            )
            verify_otp_challenge(
                user=request.user,
                challenge_id=serializer.validated_data[
                    'challenge_id'
                ],
                canonical_phone=canonical,
                code=serializer.validated_data['code'],
            )
        except PhoneVerificationError as exc:
            return _phone_verification_error_response(exc)
        return Response({
            'verified': True,
            'phone_masked': mask_kr_mobile(canonical),
        })


class ManualBenefitReviewRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not getattr(
            settings,
            'FREE_TRIAL_PHONE_VERIFICATION_ENABLED',
            False,
        ):
            return Response(
                {'code': 'manual_benefit_review_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        identity = VerifiedPhoneIdentity.objects.filter(
            user=request.user,
            key_version=getattr(
                settings,
                'PHONE_IDENTITY_HMAC_KEY_VERSION',
                'v1',
            ),
        ).first()
        if identity is None:
            return Response(
                {'code': 'manual_benefit_review_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        review = ManualBenefitReview.objects.filter(
            user=request.user,
            identity_hmac=identity.phone_hmac,
            key_version=identity.key_version,
            benefit_code=BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH,
        ).order_by('-created_at', '-pk').first()
        if review is None:
            return Response(
                {'code': 'manual_benefit_review_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(ManualBenefitReviewSerializer(review).data)

    def post(self, request):
        block_showcase_external_action(request.user)
        serializer = ManualBenefitReviewRequestSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        try:
            review, created = create_manual_benefit_review(
                user=request.user,
                contact_email=serializer.validated_data[
                    'contact_email'
                ],
                reason=serializer.validated_data['reason'],
            )
        except PhoneVerificationError as exc:
            return _phone_verification_error_response(exc)
        return Response(
            ManualBenefitReviewSerializer(review).data,
            status=(
                status.HTTP_201_CREATED
                if created
                else status.HTTP_200_OK
            ),
        )


class AdminBenefitReviewListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        queryset = ManualBenefitReview.objects.order_by(
            '-created_at',
            '-pk',
        )
        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            allowed = {
                choice
                for choice, _label
                in ManualBenefitReview.STATUS_CHOICES
            }
            if status_filter not in allowed:
                return Response(
                    {
                        'code': 'invalid_review_status',
                        'detail': '처리 상태를 다시 확인해 주세요.',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(status=status_filter)
        return Response({
            'results': ManualBenefitReviewSerializer(
                queryset,
                many=True,
            ).data,
        })


class AdminBenefitReviewDetailView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, review_id):
        review = get_object_or_404(
            ManualBenefitReview,
            pk=review_id,
        )
        return Response(ManualBenefitReviewSerializer(review).data)


class AdminBenefitReviewDecisionView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, review_id):
        serializer = AdminBenefitReviewDecisionSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            review = get_object_or_404(
                ManualBenefitReview.objects.select_for_update(),
                pk=review_id,
            )
            if review.status != ManualBenefitReview.STATUS_PENDING:
                return Response(
                    {
                        'code': 'benefit_review_already_decided',
                        'detail': '이미 처리한 확인 요청이에요.',
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            review.status = serializer.validated_data['decision']
            review.reviewer = request.user
            review.decision_reason = serializer.validated_data[
                'reason'
            ]
            review.decided_at = timezone.now()
            review.save(update_fields=[
                'status',
                'reviewer',
                'decision_reason',
                'decided_at',
            ])
        return Response(ManualBenefitReviewSerializer(review).data)


def _billing_error_response(exc):
    if isinstance(exc, BillingFlowError):
        return Response(
            {'code': exc.code, 'detail': exc.detail},
            status=exc.status_code,
        )
    status_map = {
        'not_found': status.HTTP_404_NOT_FOUND,
        'already': status.HTTP_409_CONFLICT,
        'active_plan': status.HTTP_409_CONFLICT,
        'phone_verification_required': status.HTTP_409_CONFLICT,
        'manual_benefit_review_required':
            status.HTTP_409_CONFLICT,
        'phone_identity_key_rotation_required':
            status.HTTP_503_SERVICE_UNAVAILABLE,
    }
    return Response(
        {'code': exc.code, 'detail': str(exc)},
        status=status_map.get(exc.code, status.HTTP_410_GONE),
    )


def _registration_gate_response():
    return Response(
        {
            'code': 'billing_setup_required',
            'detail': '결제 설정을 마치면 카드 등록을 시작할 수 있어요.',
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _log_trial_started(agreement):
    return log_billing_event(
        NorthStarEvent.BILLING_TRIAL_STARTED,
        sender=agreement.user,
        payload={
            'duration_months': agreement.trial_duration_months,
            'plan_code': agreement.plan.code,
        },
        dedupe_hours=1,
    )


class RecurringCouponPreflightView(APIView):
    permission_classes = [
        IsAuthenticated,
        BlocksShowcaseExternalActions,
    ]

    def post(self, request):
        if not card_registration_enabled():
            return _registration_gate_response()
        serializer = RecurringCouponPreflightSerializer(
            data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            claim = hold_recurring_coupon(
                request.user, serializer.validated_data['code'])
        except CouponError as exc:
            return _billing_error_response(exc)
        coupon = claim.coupon
        today = timezone.localdate()
        period = period_for(
            today,
            coupon.duration_months,
            anchor_day=new_anchor(today),
        )
        log_billing_event(
            NorthStarEvent.BILLING_COUPON_PREFLIGHTED,
            sender=request.user,
            payload={
                'duration_months': coupon.duration_months,
                'plan_code': coupon.plan.code,
            },
        )
        if BillingAgreement.objects.filter(
            user=request.user,
            status='free',
        ).exists():
            log_billing_event(
                NorthStarEvent.BILLING_RESTART_STARTED,
                sender=request.user,
                payload={'source': 'settings'},
                dedupe_hours=24,
            )
        return Response({
            'claim_id': str(claim.id),
            'claim_expires_at': claim.expires_at.isoformat(),
            'plan_code': coupon.plan.code,
            'plan_display_name': coupon.plan.display_name,
            'duration_months': coupon.duration_months,
            'redeem_by': coupon.redeem_by.isoformat(),
            'access_through': period.access_through.isoformat(),
            'next_charge_date': period.next_charge_date.isoformat(),
            'amount_krw':
                vat_inclusive_amount(coupon.plan.price_krw),
            'initial_consent_version':
                INITIAL_BILLING_CONSENT_VERSION,
        })


class CardRegistrationStartView(APIView):
    permission_classes = [
        IsAuthenticated,
        BlocksShowcaseExternalActions,
    ]

    def post(self, request):
        if not card_registration_enabled():
            return _registration_gate_response()
        serializer = CardRegistrationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = start_card_registration(
                user=request.user,
                claim_id=serializer.validated_data['claim_id'],
                consent_version=serializer.validated_data[
                    'initial_consent_version'],
                device_type=serializer.validated_data['device_type'],
            )
        except (BillingFlowError, CouponError) as exc:
            return _billing_error_response(exc)
        if result.get('already_complete'):
            return Response(billing_status(request.user))
        return Response({
            'auth_page_url': result['auth_page_url'],
            'state': result['state'],
            'shop_order_no': result['shop_order_no'],
            'claim_expires_at':
                result['claim_expires_at'].isoformat(),
            'access_through':
                result['access_through'].isoformat(),
            'next_charge_date':
                result['next_charge_date'].isoformat(),
            'amount_krw': result['amount_krw'],
        })


class CardRegistrationCompleteView(APIView):
    permission_classes = [
        IsAuthenticated,
        BlocksShowcaseExternalActions,
    ]

    def post(self, request):
        serializer = CardRegistrationCompleteSerializer(
            data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            agreement = complete_card_registration(
                user=request.user,
                raw_state=serializer.validated_data['state'],
                authorization_id=serializer.validated_data[
                    'authorization_id'],
                shop_order_no=serializer.validated_data[
                    'shop_order_no'],
            )
        except (BillingFlowError, CouponError) as exc:
            return _billing_error_response(exc)
        _log_trial_started(agreement)
        return Response(billing_status(request.user))


class CardRegistrationProviderReturnView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        raw_state = request.query_params.get('state', '')
        try:
            agreement = complete_card_registration(
                raw_state=raw_state,
                authorization_id=request.data.get(
                    'authorizationId', ''),
                shop_order_no=request.data.get('shopOrderNo', ''),
            )
            _log_trial_started(agreement)
            outcome = 'success'
        except Exception:
            outcome = 'check'
        return redirect(
            f"{settings.FRONTEND_BASE_URL.rstrip('/')}"
            f'/settings/billing?registration={outcome}'
        )


class BillingStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        response = billing_status(request.user)
        if response.get('reconfirmation_required'):
            charge_date = response.get('next_charge_date')
            days_before = (
                date.fromisoformat(charge_date)
                - timezone.localdate()
            ).days
            log_billing_event(
                NorthStarEvent.BILLING_RECONFIRMATION_VIEWED,
                sender=request.user,
                payload={'days_before': max(days_before, 0)},
                dedupe_hours=24,
            )
        return Response(response)


def _request_fingerprint(request, header_name):
    value = request.META.get(header_name, '')
    return hmac.new(
        settings.SECRET_KEY.encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest() if value else ''


class FirstChargeReconfirmationView(APIView):
    permission_classes = [
        IsAuthenticated,
        BlocksShowcaseExternalActions,
    ]

    def post(self, request):
        serializer = FirstChargeReconfirmationSerializer(
            data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            consent, snapshot = confirm_first_charge(
                user=request.user,
                consent_version=serializer.validated_data[
                    'first_charge_consent_version'],
                network_hmac=_request_fingerprint(
                    request, 'REMOTE_ADDR'),
                user_agent_hash=_request_fingerprint(
                    request, 'HTTP_USER_AGENT'),
            )
        except BillingFlowError as exc:
            return _billing_error_response(exc)
        return Response({
            'consent_id': consent.pk,
            **snapshot,
        })


class BillingCancellationView(APIView):
    permission_classes = [
        IsAuthenticated,
        BlocksShowcaseExternalActions,
    ]

    def post(self, request):
        try:
            return Response(cancel_billing(request.user))
        except BillingFlowError as exc:
            return _billing_error_response(exc)


class BillingNoticeLeaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BillingNoticeDeviceSerializer(
            data=request.data)
        serializer.is_valid(raise_exception=True)
        notice = lease_notice(
            request.user,
            serializer.validated_data['device_id'],
        )
        return Response({
            'notice': notice_payload(notice) if notice else None,
        })


class BillingNoticeRenderedView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notice_id):
        serializer = BillingNoticeDeviceSerializer(
            data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            notice = mark_notice_rendered(
                request.user,
                notice_id,
                serializer.validated_data['device_id'],
            )
        except NoticeError:
            return Response(
                {'detail': '표시할 안내를 다시 확인해 주세요.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({'notice_id': notice.pk, 'rendered': True})


class BillingNoticeDismissView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notice_id):
        try:
            notice = dismiss_notice(request.user, notice_id)
        except NoticeError:
            return Response(
                {'detail': '표시된 안내를 다시 확인해 주세요.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({'notice_id': notice.pk, 'dismissed': True})


# ─── 관리자 전용 ──────────────────────────────────────────────────


class AdminBillingUsageView(APIView):
    """관리자 — 전체 설계사 사용량 조회 (IsAdmin).

    GET /api/v1/admin/billing/usage/?user_id=<id>&year_month=2026-06
    필터 없으면 전체 UsageMeter 반환(페이지네이션 간소화 — 관리자 전용).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user_id = request.query_params.get('user_id')
        year_month = request.query_params.get('year_month', UsageMeter.current_month())

        if user_id:
            target_user = get_object_or_404(User, pk=user_id)
            data = _build_usage_response(target_user)
            data['user'] = {
                'id': target_user.pk,
                'email': target_user.email,
            }
            return Response(data)

        # 전체 설계사 목록 — 해당 월 meter가 있는 user만 (없는 user는 all-zero 처리)
        meters = (
            UsageMeter.objects
            .filter(year_month=year_month)
            .select_related('user')
            .order_by('user__email', 'action')
        )

        # user별 그룹핑
        from collections import defaultdict
        from .credit import resolve_effective_plan
        user_meters: dict = defaultdict(dict)
        user_objs = {}
        for m in meters:
            user_meters[m.user_id][m.action] = m.count
            user_objs[m.user_id] = m.user

        results = []
        for uid, cnt_map in user_meters.items():
            u = user_objs[uid]
            # 표시 한도 = 실제 강제 한도(취소·만료 구독은 무료로 폴백). 단일유저 브랜치·_consume와 동일.
            plan = resolve_effective_plan(u)
            usage_list = []
            for action in _ACTION_ORDER:
                lim = plan.get_limit(action) if plan else None
                cnt = cnt_map.get(action, 0)
                remaining = (lim - cnt) if lim is not None else None
                usage_list.append({
                    'action': action,
                    'label': _ACTION_LABELS[action],
                    'count': cnt,
                    'limit': lim,
                    'remaining': remaining,
                })
            results.append({
                'user': {'id': uid, 'email': u.email},
                'year_month': year_month,
                'usage': usage_list,
            })

        return Response({'count': len(results), 'results': results})


class AdminBillingModeView(APIView):
    """운영 토글 — 관리자. GET 현재값 / PATCH 부분 전송.

    토글:
      free_tier_unlimited      — 베타 무제한(True=한도 무시).
      first_paid_bonus_enabled — 첫 유료 결제 +1개월 이벤트(사용자당 1회, 기본 OFF).
    각 키는 선택 전송이며, 있으면 bool 이어야 한다(아니면 400).
    """
    permission_classes = [IsAdmin]

    _TOGGLE_KEYS = ('free_tier_unlimited', 'first_paid_bonus_enabled')

    def _snapshot(self, cfg):
        return {k: getattr(cfg, k) for k in self._TOGGLE_KEYS}

    def get(self, request):
        from .models import RuntimeConfig
        return Response(self._snapshot(RuntimeConfig.solo()))

    def patch(self, request):
        from rest_framework.exceptions import ValidationError
        from .models import RuntimeConfig
        cfg = RuntimeConfig.solo()
        update_fields = []
        for key in self._TOGGLE_KEYS:
            if key in request.data:
                val = request.data.get(key)
                if not isinstance(val, bool):
                    raise ValidationError({key: 'true/false 값이 필요합니다.'})
                setattr(cfg, key, val)
                update_fields.append(key)
        if update_fields:
            cfg.save(update_fields=update_fields + ['updated_at'])
        return Response(self._snapshot(cfg))


class AdminSubscriptionPatchView(APIView):
    """관리자 — 구독 수동 변경 (MVP 결제 확인 후 수동 활성화, dev/23 §4.3).

    PATCH /api/v1/admin/billing/subscription/<user_id>/
    plan_code / status / expires_at 부분 전송 허용.
    """
    permission_classes = [IsAdmin]

    def patch(self, request, user_id):
        target_user = get_object_or_404(User, pk=user_id)
        sub = get_object_or_404(Subscription, user=target_user)

        serializer = AdminSubscriptionPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_fields = []

        if 'plan_code' in data:
            plan = get_object_or_404(Plan, code=data['plan_code'])
            sub.plan = plan
            update_fields.append('plan')

        if 'status' in data:
            sub.status = data['status']
            update_fields.append('status')

        if 'expires_at' in data:
            sub.expires_at = data['expires_at']
            update_fields.append('expires_at')

        if update_fields:
            sub.save(update_fields=update_fields)

        # 변경 후 사용량 응답 반환 (AC-B7 즉시 반영 확인)
        resp_data = _build_usage_response(target_user)
        resp_data['user'] = {'id': target_user.pk, 'email': target_user.email}
        return Response(resp_data)
