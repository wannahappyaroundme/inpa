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
import hmac

from django.contrib.auth import get_user_model
from django.conf import settings as django_settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle

from inpa.analysis.golden_eval import (
    EVALUATION_SCOPE, EVALUATION_SCOPE_NOTE, GOLDEN_SET_MIN_ACCURACY,
    evaluate_golden_set, find_golden_expected,
)
from inpa.analysis.models import AnalysisDetail, CoverageFlag, NormalizationDict, UnmatchedLog
from inpa.analytics.events import billing_terminal_event_gap
from inpa.billing.gates import (
    card_registration_enabled,
    reconciliation_enabled,
    recurring_charge_enabled,
)
from inpa.billing.models import (
    BillingAdminAction,
    BillingAgreement,
    Coupon,
    CouponClaim,
    PaymentMethodToken,
    PaymentOrder,
    Plan,
    RuntimeConfig,
    Subscription,
    UsageMeter,
)
from inpa.billing.tasks import (
    reconcile_unknown_order_task,
    revoke_payment_token_task,
)
from inpa.consultations.comparison import ConsultationComparisonService
from inpa.consultations.comparison_audio import ComparisonAudioError
from inpa.consultations.providers.comparison_base import (
    ComparisonDeadline,
    ComparisonOutcomeUnknown,
    ComparisonProviderFailure,
)
from inpa.consultations.quota import release_meter
from inpa.boards.models import (
    BlogPost,
    Comment,
    Faq,
    Inquiry,
    InquiryReply,
    Notice,
    Post,
    Report,
    blog_review_content_digest,
)
from inpa.boards.serializers import BlogLegalReviewRecordSerializer
from inpa.core.copyguard import scan_blog_content
from inpa.core.internal_accounts import (
    block_showcase_external_action,
    internal_user_q,
)
from inpa.core.permissions import IsAdmin
from inpa.customers.models import ConsentLog, Customer
from inpa.consultations.cleanup import SOURCE_PRESENT_STATUSES
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRecording,
    ConsultationRuntimeConfig,
    ConsultationSummaryRun,
)
from inpa.consultations.recording_policy import current_retention_snapshot
from inpa.consultations.services import get_recording_storage
from inpa.notifications.models import Notification, NotifType
from inpa.promotion.models import PromotionOrder

from .models import PolicyVersion
from .serializers import (
    AdminBlogPostSerializer,
    AdminBillingCouponCreateSerializer,
    AdminBillingCouponSerializer,
    AdminBillingCouponUpdateSerializer,
    AdminBillingSettingsSerializer,
    AdminConsultationComparisonSerializer,
    AdminConsultationConfigSerializer,
    AdminConsultationPilotCreateSerializer,
    AdminConsultationPilotSerializer,
    AdminConsultationPilotUpdateSerializer,
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


def _billing_environment():
    credentials_ready = all((
        django_settings.KICC_MALL_ID,
        django_settings.KICC_CLIENT_SECRET,
        django_settings.KICC_API_BASE_URL,
        django_settings.PAYMENT_TOKEN_ENCRYPTION_KEY,
    ))
    return {
        'card_registration_env':
            django_settings.BILLING_CARD_REGISTRATION_ENABLED,
        'recurring_charge_env':
            django_settings.BILLING_RECURRING_CHARGE_ENABLED,
        'reconciliation_env':
            django_settings.BILLING_WEBHOOK_RECONCILIATION_ENABLED,
        'provider_credentials_ready': credentials_ready,
        'card_registration_effective': card_registration_enabled(),
        'recurring_charge_effective': recurring_charge_enabled(),
        'reconciliation_effective': reconciliation_enabled(),
    }


def _billing_settings(config):
    return {
        'free_tier_unlimited': config.free_tier_unlimited,
        'billing_card_registration_enabled':
            config.billing_card_registration_enabled,
        'billing_recurring_charge_enabled':
            config.billing_recurring_charge_enabled,
        'billing_reconciliation_enabled':
            config.billing_reconciliation_enabled,
    }


def _admin_action(
    request,
    *,
    action,
    target_type,
    target_id='',
    details=None,
):
    request_key = (
        request.headers.get('Idempotency-Key', '').strip()[:100]
    )
    defaults = {
        'admin': request.user,
        'action': action,
        'target_type': target_type,
        'target_id': str(target_id),
        'details': details or {},
    }
    if request_key:
        return BillingAdminAction.objects.get_or_create(
            request_key=request_key,
            defaults=defaults,
        )
    return (
        BillingAdminAction.objects.create(
            request_key='',
            **defaults,
        ),
        True,
    )


def _coupon_payload(coupon):
    return AdminBillingCouponSerializer(coupon).data


def _agreement_row(agreement):
    token = agreement.payment_tokens.filter(
        status__in=('active', 'revocation_pending'),
    ).order_by('status', '-created_at').first()
    return {
        'id': str(agreement.pk),
        'user_email': agreement.user.email,
        'plan_code': agreement.plan.code,
        'status': agreement.status,
        'trial_duration_months': agreement.trial_duration_months,
        'current_period_starts_on':
            agreement.current_period_starts_on,
        'current_period_ends_on':
            agreement.current_period_ends_on,
        'next_charge_date': agreement.next_charge_date,
        'cycle_sequence': agreement.cycle_sequence,
        'card_label': token.display_label if token else None,
        'payment_token_id': token.pk if token else None,
        'payment_token_status': token.status if token else None,
        'updated_at': agreement.updated_at,
    }


def _order_row(order):
    return {
        'id': order.pk,
        'agreement_id': str(order.agreement_id),
        'user_email': order.agreement.user.email,
        'cycle_sequence': order.cycle_sequence,
        'merchant_order_id': order.merchant_order_id,
        'amount_krw': order.amount_krw,
        'due_date': order.due_date,
        'status': order.status,
        'failure_code': order.failure_code,
        'unknown_since': order.unknown_since,
        'temporary_access_until': order.temporary_access_until,
        'created_at': order.created_at,
        'updated_at': order.updated_at,
    }


class AdminBillingOverviewView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        agreements = (
            BillingAgreement.objects.select_related('user', 'plan')
            .prefetch_related('payment_tokens')
            .exclude(internal_user_q('user'))
            .order_by('-updated_at')
        )
        orders = (
            PaymentOrder.objects.select_related(
                'agreement__user')
            .exclude(internal_user_q('agreement__user'))
            .order_by('-created_at')
        )
        return Response({
            'status': {
                'agreement_count': agreements.count(),
                'trial_count':
                    agreements.filter(status='trialing').count(),
                'active_count':
                    agreements.filter(status='active').count(),
                'unknown_order_count':
                    orders.filter(status='unknown').count(),
                'revocation_pending_token_count':
                    PaymentMethodToken.objects.filter(
                        status='revocation_pending',
                    ).exclude(
                        internal_user_q('agreement__user'),
                    ).count(),
                'held_coupon_claim_count':
                    CouponClaim.objects.filter(status='held').exclude(
                        internal_user_q('user'),
                    ).count(),
                'terminal_event_gap_count':
                    billing_terminal_event_gap(),
            },
            'environment': _billing_environment(),
            'settings': _billing_settings(RuntimeConfig.solo()),
            'recent_agreements': [
                _agreement_row(item) for item in agreements[:20]
            ],
            'recent_orders': [
                _order_row(item) for item in orders[:20]
            ],
        })


class AdminBillingCouponListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        coupons = Coupon.objects.select_related('plan').filter(
            coupon_kind='recurring_trial',
        ).order_by('-created_at')[:200]
        return Response(
            AdminBillingCouponSerializer(
                coupons, many=True).data)

    def post(self, request):
        request_key = request.headers.get(
            'Idempotency-Key', '').strip()[:100]
        serializer = AdminBillingCouponCreateSerializer(
            data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        plan = get_object_or_404(
            Plan,
            code=data['plan_code'],
            is_active=True,
        )
        with transaction.atomic():
            action_record = None
            if request_key:
                action_record, reserved = (
                    BillingAdminAction.objects.get_or_create(
                        request_key=request_key,
                        defaults={
                            'admin': request.user,
                            'action': 'coupon_create_reserved',
                            'target_type': 'coupon',
                        },
                    )
                )
                if not reserved:
                    if (
                        action_record.action == 'coupon_created'
                        and action_record.target_id
                    ):
                        coupon = get_object_or_404(
                            Coupon.objects.select_related('plan'),
                            pk=action_record.target_id,
                        )
                        return Response(_coupon_payload(coupon))
                    return Response(
                        {
                            'detail': (
                                '같은 요청의 쿠폰 발행 상태를 '
                                '잠시 뒤 다시 확인해 주세요.'
                            ),
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
            coupon = Coupon.objects.create(
                plan=plan,
                coupon_kind='recurring_trial',
                duration_days=30,
                duration_months=data['duration_months'],
                redeem_by=data['redeem_by'],
                max_redemptions=data['max_redemptions'],
                note=data.get('note', ''),
            )
            details = {
                'plan_code': plan.code,
                'duration_months': coupon.duration_months,
                'max_redemptions': coupon.max_redemptions,
            }
            if action_record:
                action_record.action = 'coupon_created'
                action_record.target_id = str(coupon.pk)
                action_record.details = details
                action_record.save(update_fields=[
                    'action', 'target_id', 'details'])
            else:
                _admin_action(
                    request,
                    action='coupon_created',
                    target_type='coupon',
                    target_id=coupon.pk,
                    details=details,
                )
        return Response(
            _coupon_payload(coupon),
            status=status.HTTP_201_CREATED,
        )


class AdminBillingCouponDetailView(APIView):
    permission_classes = [IsAdmin]

    def patch(self, request, coupon_id):
        request_key = request.headers.get(
            'Idempotency-Key', '').strip()[:100]
        if request_key and BillingAdminAction.objects.filter(
            request_key=request_key,
            action='coupon_updated',
            target_id=str(coupon_id),
        ).exists():
            coupon = get_object_or_404(
                Coupon.objects.select_related('plan'),
                pk=coupon_id,
            )
            return Response(_coupon_payload(coupon))
        serializer = AdminBillingCouponUpdateSerializer(
            data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            coupon = get_object_or_404(
                Coupon.objects.select_for_update().select_related('plan'),
                pk=coupon_id,
                coupon_kind='recurring_trial',
            )
            data = serializer.validated_data
            if (
                'max_redemptions' in data
                and data['max_redemptions'] < coupon.redeemed_count
            ):
                return Response(
                    {
                        'detail': (
                            '이미 사용된 수보다 큰 최대 사용 횟수를 '
                            '입력해 주세요.'
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            update_fields = []
            for field, value in data.items():
                setattr(coupon, field, value)
                update_fields.append(field)
            if update_fields:
                coupon.save(update_fields=update_fields)
            _admin_action(
                request,
                action='coupon_updated',
                target_type='coupon',
                target_id=coupon.pk,
                details={'updated_fields': sorted(update_fields)},
            )
        return Response(_coupon_payload(coupon))


class AdminBillingAgreementListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        agreements = (
            BillingAgreement.objects.select_related('user', 'plan')
            .prefetch_related('payment_tokens')
            .exclude(internal_user_q('user'))
            .order_by('-updated_at')[:200]
        )
        return Response([_agreement_row(item) for item in agreements])


class AdminBillingOrderListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        orders = (
            PaymentOrder.objects.select_related(
                'agreement__user')
            .exclude(internal_user_q('agreement__user'))
            .order_by('-created_at')[:200]
        )
        return Response([_order_row(item) for item in orders])


class AdminBillingOrderReconcileView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, order_id):
        order = get_object_or_404(
            PaymentOrder, pk=order_id, status='unknown')
        request_key = request.headers.get(
            'Idempotency-Key', '').strip()[:100]
        if request_key and BillingAdminAction.objects.filter(
                request_key=request_key).exists():
            return Response(
                {'order_id': order.pk, 'queued': True},
                status=status.HTTP_202_ACCEPTED,
            )
        _, created = _admin_action(
            request,
            action='order_reconciliation_queued',
            target_type='payment_order',
            target_id=order.pk,
        )
        if created:
            reconcile_unknown_order_task.delay(order.pk)
        return Response(
            {'order_id': order.pk, 'queued': True},
            status=status.HTTP_202_ACCEPTED,
        )


class AdminBillingTokenRevokeView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, token_id):
        request_key = request.headers.get(
            'Idempotency-Key', '').strip()[:100]
        if request_key and BillingAdminAction.objects.filter(
                request_key=request_key).exists():
            return Response(
                {'token_id': token_id, 'queued': True},
                status=status.HTTP_202_ACCEPTED,
            )
        with transaction.atomic():
            token = get_object_or_404(
                PaymentMethodToken.objects.select_for_update(),
                pk=token_id,
                status__in=('active', 'revocation_pending'),
            )
            if token.status == 'active':
                token.status = 'revocation_pending'
                token.save(update_fields=['status', 'updated_at'])
            _, created = _admin_action(
                request,
                action='payment_token_revocation_queued',
                target_type='payment_token',
                target_id=token.pk,
            )
        if created:
            revoke_payment_token_task.delay(token.pk)
        return Response(
            {'token_id': token.pk, 'queued': True},
            status=status.HTTP_202_ACCEPTED,
        )


class AdminBillingSettingsView(APIView):
    permission_classes = [IsAdmin]

    @staticmethod
    def _response(config):
        return {
            'environment': _billing_environment(),
            'settings': _billing_settings(config),
        }

    def get(self, request):
        return Response(self._response(RuntimeConfig.solo()))

    def patch(self, request):
        serializer = AdminBillingSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            config = RuntimeConfig.objects.select_for_update().get(
                pk=RuntimeConfig.solo().pk)
            desired = {
                **_billing_settings(config),
                **data,
            }
            environment = _billing_environment()
            if (
                desired['billing_card_registration_enabled']
                and not (
                    environment['card_registration_env']
                    and environment['provider_credentials_ready']
                )
            ):
                return Response(
                    {
                        'code': 'BILLING_CARD_ENV_CLOSED',
                        'detail': (
                            '카드 등록 환경 확인을 마치면 '
                            '운영 스위치를 켤 수 있어요.'
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            if (
                desired['billing_reconciliation_enabled']
                and not (
                    environment['reconciliation_env']
                    and environment['provider_credentials_ready']
                )
            ):
                return Response(
                    {
                        'code': 'BILLING_RECONCILIATION_ENV_CLOSED',
                        'detail': (
                            '결제 조회와 취소 환경 확인을 마치면 '
                            '운영 스위치를 켤 수 있어요.'
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            if desired['billing_recurring_charge_enabled']:
                recurring_ready = all((
                    environment['recurring_charge_env'],
                    desired['billing_card_registration_enabled'],
                    desired['billing_reconciliation_enabled'],
                    not desired['free_tier_unlimited'],
                    not django_settings.FREE_TIER_UNLIMITED,
                ))
                if not recurring_ready:
                    return Response(
                        {
                            'code': 'BILLING_RECURRING_PREREQUISITES',
                            'detail': (
                                '카드 등록, 결제 조회, 유료 한도 설정을 '
                                '마치면 정기결제를 켤 수 있어요.'
                            ),
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
            for field, value in data.items():
                setattr(config, field, value)
            if data:
                config.save(update_fields=[
                    *data.keys(),
                    'updated_at',
                ])
                _admin_action(
                    request,
                    action='billing_settings_updated',
                    target_type='runtime_config',
                    target_id=config.pk,
                    details={'updated_fields': sorted(data.keys())},
                )
        return Response(self._response(config))


def consultation_status_snapshot():
    now = timezone.now()
    recording_rows = ConsultationRecording.objects.exclude(
        internal_user_q('owner'),
    )
    source_rows = recording_rows.filter(
        storage_key__isnull=False,
        status__in=SOURCE_PRESENT_STATUSES,
    )
    audit_key = 'admin:consultation-storage-audit:v1'
    storage_audit = cache.get(audit_key)
    if storage_audit is None:
        storage_audit = {
            'storage_audit_available': False,
            'orphan_object_count': None,
            'missing_object_count': None,
        }
        if django_settings.CONSULTATION_RECORDING_ENABLED:
            try:
                db_keys = set(source_rows.values_list('storage_key', flat=True))
                object_keys = set(get_recording_storage().iter_keys())
                storage_audit = {
                    'storage_audit_available': True,
                    'orphan_object_count': len(object_keys - db_keys),
                    'missing_object_count': len(db_keys - object_keys),
                }
            except Exception:
                pass
        cache.set(audit_key, storage_audit, 300)
    summary_rows = ConsultationSummaryRun.objects.exclude(
        internal_user_q('recording__owner'),
    )
    succeeded_seconds = list(
        summary_rows.filter(
            status=ConsultationSummaryRun.STATUS_SUCCEEDED,
        ).order_by('processing_seconds').values_list(
            'processing_seconds',
            flat=True,
        )
    )

    def percentile(values, percent):
        if not values:
            return None
        index = min(
            len(values) - 1,
            max(0, int(round((len(values) - 1) * percent))),
        )
        return values[index]

    summary_totals = summary_rows.aggregate(
        processing_minutes=Sum('processing_minutes_reserved'),
        estimated_cost_krw=Sum('estimated_cost_krw'),
    )
    summary_run_fields = (
        'id',
        'status',
        'stt_provider',
        'summary_provider',
        'summary_model',
        'processing_minutes_reserved',
        'processing_seconds',
        'input_tokens',
        'output_tokens',
        'estimated_cost_krw',
        'outcome',
        'error_code',
        'created_at',
        'completed_at',
    )
    showcase_email = django_settings.SHOWCASE_ACCOUNT_EMAIL
    pilot_summary_rows = ConsultationSummaryRun.objects.none()
    if showcase_email:
        pilot_summary_rows = ConsultationSummaryRun.objects.filter(
            recording__owner__email=showcase_email,
            recording__owner__profile__is_showcase=True,
        )
    return {
        'active_upload_count': recording_rows.filter(
            status=ConsultationRecording.STATUS_UPLOADING,
        ).count(),
        'ready_source_count': source_rows.exclude(
            status=ConsultationRecording.STATUS_UPLOADING,
        ).count(),
        'deleted_count': recording_rows.filter(
            status=ConsultationRecording.STATUS_DELETED,
        ).count(),
        'overdue_source_count': source_rows.filter(
            expires_at__isnull=False,
            expires_at__lte=now,
        ).count(),
        'delete_failure_count': recording_rows.filter(
            delete_result='retry_required',
        ).count(),
        'summary_queued_count': summary_rows.filter(
            status=ConsultationSummaryRun.STATUS_QUEUED,
        ).count(),
        'summary_processing_count': summary_rows.filter(
            status__in=(
                ConsultationSummaryRun.STATUS_TRANSCRIBING,
                ConsultationSummaryRun.STATUS_SUMMARIZING,
            ),
        ).count(),
        'summary_success_count': summary_rows.filter(
            status=ConsultationSummaryRun.STATUS_SUCCEEDED,
        ).count(),
        'summary_failed_count': summary_rows.filter(
            status=ConsultationSummaryRun.STATUS_FAILED,
        ).count(),
        'summary_ambiguous_count': summary_rows.filter(
            status=ConsultationSummaryRun.STATUS_AMBIGUOUS,
        ).count(),
        'summary_cancelled_count': summary_rows.filter(
            status=ConsultationSummaryRun.STATUS_CANCELLED,
        ).count(),
        'summary_processing_minutes':
            summary_totals['processing_minutes'] or 0,
        'summary_estimated_cost_krw':
            summary_totals['estimated_cost_krw'] or 0,
        'summary_p50_seconds': percentile(succeeded_seconds, 0.50),
        'summary_p95_seconds': percentile(succeeded_seconds, 0.95),
        'recent_summary_runs': list(
            summary_rows.order_by('-created_at').values(
                *summary_run_fields,
            )[:20]
        ),
        'pilot_recent_summary_runs': list(
            pilot_summary_rows.order_by('-created_at').values(
                *summary_run_fields,
            )[:20]
        ),
        **storage_audit,
    }


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
        # ★ KST 기준(§7): __date 룩업은 TIME_ZONE(Asia/Seoul) 버킷이라 오늘 카운트도
        #   localdate() 로 맞춰야 UTC/KST 월·일 경계에서 어긋나지 않는다.
        today = timezone.localdate()

        data = {
            # 오늘 현황
            'today_new_users': User.objects.exclude(
                internal_user_q()).filter(date_joined__date=today).count(),
            'today_new_orders': PromotionOrder.objects.exclude(
                internal_user_q('owner'),
            ).filter(created_at__date=today).count(),
            'open_inquiries': Inquiry.objects.exclude(
                internal_user_q('owner'),
            ).filter(status=Inquiry.STATUS_OPEN).count(),
            'pending_reports': Report.objects.exclude(
                internal_user_q('reporter'),
            ).filter(status=Report.STATUS_PENDING).count(),
            # 누적 지표 (사실 카운트만 — "활성화율 낮음/위험" 등 판정 금지)
            'total_users': User.objects.exclude(internal_user_q()).count(),
            'total_customers': Customer.objects.exclude(
                internal_user_q('owner')).count(),
            # 요금제 분포
            'plan_distribution': _get_plan_distribution(),
            # 미처리 항목
            'pending_orders': PromotionOrder.objects.exclude(
                internal_user_q('owner'),
            ).filter(
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
        Subscription.objects.exclude(internal_user_q('user'))
        .values('plan__code')
        .annotate(count=Count('id'))
    )
    result = {row['plan__code']: row['count'] for row in dist}
    # 구독 없는 설계사(미초기화) 카운트 포함
    subbed_count = sum(result.values())
    total = User.objects.exclude(internal_user_q()).count()
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
        from inpa.billing.credit import add_months
        from inpa.billing.models import RuntimeConfig

        user = get_object_or_404(User, pk=user_id)
        serializer = AdminSubscriptionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        plan_code = serializer.validated_data['plan_code']
        plan = get_object_or_404(Plan, code=plan_code, is_active=True)
        billing_cycle = serializer.validated_data.get('billing_cycle')

        sub, created = Subscription.objects.get_or_create(
            user=user,
            defaults={'plan': plan, 'status': 'active'},
        )
        old_plan = None if created else sub.plan.display_name
        sub.plan = plan
        if 'status' in serializer.validated_data:
            sub.status = serializer.validated_data['status']

        # ── 만료·주기·첫 유료 보너스 ─────────────────────────────────────
        # 무료 플랜은 무기한(expires_at=None) 유지. 유료 + billing_cycle 지정 시에만
        # 만료를 계산한다(하위호환: cycle 미지정 유료 부여는 기존 expires_at 보존 =
        # 수동 무기한 부여 관례). 월=1개월/연=12개월. 첫 유료 보너스(토글 ON·미소진)면 +1개월.
        if plan.code == 'free':
            sub.expires_at = None
        elif billing_cycle:
            now = timezone.now()
            sub.billing_cycle = billing_cycle
            months = 1 if billing_cycle == 'monthly' else 12
            expires = add_months(now, months)
            if RuntimeConfig.solo().first_paid_bonus_enabled and not sub.first_paid_bonus_used:
                expires = add_months(expires, 1)
                sub.first_paid_bonus_used = True
            sub.expires_at = expires

        sub.save()

        # 설계사 본인에게 알림 (고객 자동발송 금지 원칙).
        # ★ EXPIRY_SOON(만기 임박, 일정 배지) 재사용은 잘못된 배지·라벨을 만든다.
        #   요금제 변경은 운영팀이 계정에 보낸 안내이므로 게시판(받은함) 버킷으로 라우팅.
        _notify_user(
            owner=user,
            notif_type=NotifType.INQUIRY_ANSWERED,
            title='요금제가 변경되었습니다',
            body=f'요금제가 {plan.display_name}({plan.code})으로 변경되었습니다.',
        )

        return Response({
            'user_id': user.id,
            'plan_code': plan.code,
            'plan_display': plan.display_name,
            'status': sub.status,
            'billing_cycle': sub.billing_cycle,
            'expires_at': sub.expires_at.isoformat() if sub.expires_at else None,
            'first_paid_bonus_used': sub.first_paid_bonus_used,
            'changed': not created or old_plan != plan.display_name,
        })


class AdminUserSendResetEmailView(APIView):
    """POST /api/v1/admin/users/:id/send_reset_email/
    비밀번호 재설정 이메일 발송 (admin이 직접 변경 불가 — 보안 원칙).
    """
    permission_classes = [IsAdmin]

    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        block_showcase_external_action(user)
        from inpa.accounts.views import _send_reset_email
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
        qs = (
            Inquiry.objects.select_related('owner')
            .prefetch_related('replies__author')
            .exclude(internal_user_q('owner'))
        )

        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        category_filter = request.query_params.get('category')
        if category_filter:
            qs = qs.filter(category=category_filter)

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
                notif_type=NotifType.INQUIRY_ANSWERED,  # 문의 답변 도착(게시판 버킷)
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
        qs = (
            Report.objects.select_related('reporter', 'resolved_by')
            .exclude(internal_user_q('reporter'))
            .order_by('-created_at')
        )

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
            # ★ 신고 처리 결과는 게시글 모더레이션(게시판) 안내 → 받은함 버킷.
            #   EXPIRY_SOON(일정 배지, '만기 임박') 재사용 금지.
            _notify_user(
                owner=report.reporter,
                notif_type=NotifType.INQUIRY_ANSWERED,
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
        qs = (
            PromotionOrder.objects.select_related('owner', 'sample')
            .exclude(internal_user_q('owner'))
            .order_by('-created_at')
        )

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

        order.refresh_from_db()

        # 설계사 본인에게 알림 (고객 자동발송 금지).
        # ★ 판촉물 주문 상태 알림은 PROMOTION_STATUS(전자자료면 PROMOTION_DIGITAL_READY)로
        #   라우팅해야 판촉물 배지에 정확히 잡힌다. 기존 EXPIRY_SOON 재사용은 '만기 임박'으로
        #   잘못 표시되고 PROMOTION_STATUS 경로를 사장시켰다. 판촉물 도메인의 공용 헬퍼를
        #   재사용(전자자료 준비 완료 분기 포함, em-dash 없는 카피).
        from inpa.promotion.views import _send_order_status_notification
        _send_order_status_notification(order)

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
            'exact_auto_mapped': result['exact_auto_mapped'],
            'safe_human_review': result['safe_human_review'],
            'unsafe_auto_mapped': result['unsafe_auto_mapped'],
            'safe_decision_rate': result['safe_decision_rate'],
            'evaluation_scope': EVALUATION_SCOPE,
            'evaluation_scope_note': EVALUATION_SCOPE_NOTE,
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


class AdminBlogLegalReviewView(APIView):
    """저장된 한 버전에 법률 검토를 명시적으로 결합하고 선택적으로 게시한다."""
    permission_classes = [IsAdmin]

    def post(self, request, post_id):
        serializer = BlogLegalReviewRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            post = get_object_or_404(
                BlogPost.objects.select_for_update(), pk=post_id,
            )
            if post.review_gate != BlogPost.REVIEW_GATE_LEGAL:
                return Response(
                    {'review_gate': ['법률 검토 대상 글에서 사용할 수 있어요.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            current_digest = blog_review_content_digest(post)
            if not hmac.compare_digest(
                serializer.validated_data['content_digest'], current_digest,
            ):
                return Response(
                    {
                        'content_digest': [
                            '글이 다른 곳에서 수정되었어요. 최신 내용을 다시 확인해 주세요.'
                        ],
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            reviewed_at = timezone.now()
            review = {
                'reviewer': serializer.validated_data['reviewer'],
                'credential': serializer.validated_data['credential'],
                'reviewed_at': reviewed_at.isoformat(),
                'reference': serializer.validated_data['reference'],
            }
            post.legal_review = review
            post.legal_review_reviewer = review['reviewer']
            post.legal_review_credential = review['credential']
            post.legal_reviewed_at = reviewed_at
            post.legal_review_reference = review['reference']
            post.legal_review_content_digest = current_digest
            post.is_published = serializer.validated_data['publish']
            update_fields = [
                'legal_review', 'legal_review_reviewer', 'legal_review_credential',
                'legal_reviewed_at', 'legal_review_reference',
                'legal_review_content_digest', 'is_published', 'updated_at',
            ]
            if post.is_published and post.published_at is None:
                post.published_at = reviewed_at
                update_fields.append('published_at')
            post.save(update_fields=update_fields)

        data = AdminBlogPostSerializer(post, context={'request': request}).data
        data['warnings'] = _blog_copy_warnings(post)
        return Response(data)


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
    ★ 내부 계정은 제외. days=0 이면 전체 기간(시간 필터 없음).

    ★ 이벤트를 두 갈래로 나눠 본다:
      - planner_activity: 설계사가 직접 한 행동(증권 스캔·분석 조회·공유 발급·복사).
      - customer_response: 고객이 공유 링크에 반응한 것(공유 열람·연락 요청·소개 귀속).
    순위는 planner_activity 합계 기준 — 고객이 공유를 여러 번 열람해도 설계사 '사용량'을
    부풀리지 않는다(고객 반응은 설계사가 한 일이 아님).
    """
    permission_classes = [IsAdmin]

    # 이벤트 분류 (analytics.NorthStarEvent event_type 안정값 기준).
    _PLANNER_ACTIVITY = frozenset({'ocr_upload', 'analysis_view', 'share_created', 'clipboard_copy'})
    _CUSTOMER_RESPONSE = frozenset({'share_view', 'callback_request', 'referral_attributed', 'cta_click'})

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
              .exclude(internal_user_q('sender')))
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
                'total': 0,               # 전체 이벤트 합(하위호환 유지)
                'planner_activity': 0,    # 설계사 직접 행동 합
                'customer_response': 0,   # 고객 반응 합
                'events': {},  # event_type → count
            })
            etype = r['event_type']
            cnt = r['c']
            u['events'][etype] = cnt
            u['total'] += cnt
            if etype in self._PLANNER_ACTIVITY:
                u['planner_activity'] += cnt
            elif etype in self._CUSTOMER_RESPONSE:
                u['customer_response'] += cnt

        # ★ 순위 = planner_activity 우선(동률 시 전체 합) — 고객 반응이 순위를 부풀리지 않게.
        ranked = sorted(
            users.values(),
            key=lambda x: (x['planner_activity'], x['total']),
            reverse=True,
        )

        feature_totals = {}
        planner_activity_total = 0
        customer_response_total = 0
        for u in ranked:
            for k, v in u['events'].items():
                feature_totals[k] = feature_totals.get(k, 0) + v
            planner_activity_total += u['planner_activity']
            customer_response_total += u['customer_response']

        return Response({
            'days': days,
            'active_users': len(ranked),
            'feature_totals': feature_totals,  # event_type → 전체 합
            'group_totals': {                  # 두 갈래 합계
                'planner_activity': planner_activity_total,
                'customer_response': customer_response_total,
            },
            'users': ranked,                   # planner_activity 내림차순
        })


class AdminClaudeCostView(APIView):
    """Claude 호출당 비용·파싱결과 계측 — GET /api/v1/admin/claude-cost/?days=30 (IsAdmin).

    ★ 프리런치 리뷰 #17. billing.ClaudeApiLog(호출 1건=1행, PII-safe: 토큰수·추정비용·
    outcome enum·회사코드 int·매칭/미매칭 건수만)를 창(days) 내 집계한다.
    cost_krw 는 어드민 관측용 **추정치**(billing/pricing.py — 토큰×모델계열단가×환율)이며
    실제 청구서와 다를 수 있다(§6 정직성 — 판정어 없이 사실 수치만).
    ★ 내부 계정은 제외(AdminUsageView 관례). user=null(예: /d 공개 경로)
    행은 내부 계정이 아니므로 제외되지 않는다.
    """
    permission_classes = [IsAdmin]

    _INITIAL_METRICS_SCHEMA = 'insurance-extraction-initial-metrics-v1'
    _INITIAL_STATES = (
        'review_ready', 'needs_review', 'no_evidence',
        'unmatched', 'invalid', 'manual',
    )
    _SAFE_ACTIONS = frozenset({
        'ocr_parse', 'insurance_extraction', 'ocr_verify',
        'compare_guide', 'self_diagnosis', 'message_gen',
    })
    _SAFE_OUTCOMES = frozenset({
        'success', 'empty', 'json_invalid', 'api_error', 'timeout',
        'no_key', 'package_missing', 'schema_invalid',
        'privacy_rejected', 'transport_failure', 'config_failure',
    })
    _PROVIDER_FAILURE_RESULT_OUTCOMES = frozenset({
        'empty', 'schema_invalid', 'privacy_rejected',
        'transport_failure', 'config_failure',
        'post_provider_persistence_failure',
    })

    @staticmethod
    def _safe_enum(value, allowed):
        return value if value in allowed else 'other'

    @staticmethod
    def _duration_summary(values, invalid_count):
        import math

        ordered = sorted(values)

        def nearest_rank(percentile):
            if not ordered:
                return None
            index = max(0, math.ceil(percentile * len(ordered)) - 1)
            return ordered[index]

        return {
            'sample_count': len(ordered),
            'invalid_timing_count': invalid_count,
            'p50': nearest_rank(0.50),
            'p95': nearest_rank(0.95),
        }

    @staticmethod
    def _duration_ms(start, end):
        if start is None or end is None:
            return None
        value = round((end - start).total_seconds() * 1000)
        return value if value >= 0 else False

    def _validated_initial_metrics(self, job, result):
        from inpa.insurances.import_validation import ALLOWED_CARRIER_CODES

        summary = job.validation_summary
        system = summary.get('_system') if isinstance(summary, dict) else None
        if not isinstance(system, dict) or system.get('provider_started') is not True:
            return None
        if job.status in {'review_required', 'confirmed'}:
            if result is None or result.outcome != 'review_required':
                return None
        elif job.status == 'failed':
            if (result is None
                    or result.outcome
                    not in self._PROVIDER_FAILURE_RESULT_OUTCOMES):
                return None
        else:
            return None
        metrics = (
            system.get('initial_metrics')
            if isinstance(system, dict) else None)
        expected_keys = {
            'schema_version', 'carrier_code',
            'detected_candidates', 'assigned', 'unmatched',
            'intentionally_excluded', 'coverage_row_count',
            'coverage_state_counts', 'policy_field_count',
            'policy_state_counts', 'provider_rows', 'zero_provider_rows',
        }
        if (not isinstance(metrics, dict)
                or set(metrics) != expected_keys
                or metrics.get('schema_version') != self._INITIAL_METRICS_SCHEMA):
            return None
        required_counts = (
            'detected_candidates', 'assigned', 'unmatched',
            'intentionally_excluded', 'coverage_row_count',
            'policy_field_count', 'provider_rows',
        )
        if any(
                type(metrics.get(key)) is not int or metrics[key] < 0
                for key in required_counts):
            return None
        carrier_code = metrics.get('carrier_code')
        if (carrier_code is not None
                and (type(carrier_code) is not int
                     or carrier_code not in ALLOWED_CARRIER_CODES)):
            return None
        zero_provider_rows = metrics.get('zero_provider_rows')
        if (type(zero_provider_rows) is not int
                or zero_provider_rows not in (0, 1)
                or (zero_provider_rows == 1 and metrics['provider_rows'] != 0)):
            return None
        coverage_states = metrics.get('coverage_state_counts')
        policy_states = metrics.get('policy_state_counts')
        expected_states = set(self._INITIAL_STATES)
        for counts, count_key in (
                (coverage_states, 'coverage_row_count'),
                (policy_states, 'policy_field_count')):
            if (not isinstance(counts, dict)
                    or set(counts) != expected_states
                    or any(type(value) is not int or value < 0
                           for value in counts.values())
                    or sum(counts.values()) != metrics[count_key]):
                return None
        if metrics['detected_candidates'] != sum(
                metrics[key]
                for key in (
                    'assigned', 'unmatched', 'intentionally_excluded')):
            return None
        return {
            'carrier_code': carrier_code,
            **{key: metrics[key] for key in required_counts},
            'zero_provider_rows': zero_provider_rows,
            'coverage_state_counts': {
                state: coverage_states[state]
                for state in self._INITIAL_STATES
            },
            'policy_state_counts': {
                state: policy_states[state]
                for state in self._INITIAL_STATES
            },
        }

    def _insurance_review_metrics(self, *, since, extraction_outcome_counts):
        from inpa.insurances.models import (
            InsuranceExtractionJob,
            InsuranceExtractionResult,
        )
        safe_statuses = {
            value for value, _label in InsuranceExtractionJob.STATUS_CHOICES
        }

        jobs_qs = (
            InsuranceExtractionJob.objects
            .exclude(internal_user_q('owner'))
            .select_related('owner')
        )
        if since is not None:
            jobs_qs = jobs_qs.filter(created_at__gte=since)
        jobs = list(jobs_qs)
        job_ids = [job.pk for job in jobs]
        results = {
            result.job_id: result
            for result in InsuranceExtractionResult.objects.filter(
                job_id__in=job_ids,
                provider='claude',
            )
        }
        status_counts = {}
        for job in jobs:
            bucket = self._safe_enum(job.status, safe_statuses)
            status_counts[bucket] = status_counts.get(bucket, 0) + 1

        queue_values = []
        current_queue_values = []
        processing_values = []
        review_values = []
        queue_invalid = current_queue_invalid = processing_invalid = review_invalid = 0
        now = timezone.now()
        for job in jobs:
            if job.started_at is not None:
                value = self._duration_ms(job.created_at, job.started_at)
                if value is False:
                    queue_invalid += 1
                elif value is not None:
                    queue_values.append(value)
            elif job.status == 'queued':
                value = self._duration_ms(job.created_at, now)
                if value is False:
                    current_queue_invalid += 1
                elif value is not None:
                    current_queue_values.append(value)

            result = results.get(job.pk)
            process_end = (
                result.created_at if result is not None else job.completed_at)
            if (job.status in {'review_required', 'confirmed', 'failed'}
                    and job.started_at is not None
                    and process_end is not None):
                value = self._duration_ms(job.started_at, process_end)
                if value is False:
                    processing_invalid += 1
                else:
                    processing_values.append(value)
            if job.confirmed_at is not None and result is not None:
                value = self._duration_ms(result.created_at, job.confirmed_at)
                if value is False:
                    review_invalid += 1
                else:
                    review_values.append(value)

        job_count = len(jobs)
        attempts_total = sum(job.attempt_count for job in jobs)
        retry_attempts = sum(max(job.attempt_count - 1, 0) for job in jobs)
        retry_jobs = sum(job.attempt_count > 1 for job in jobs)
        expired = sum(job.lease_expired_count for job in jobs)
        expired_jobs = sum(job.lease_expired_count > 0 for job in jobs)

        state_counts = {state: 0 for state in self._INITIAL_STATES}
        policy_state_counts = {state: 0 for state in self._INITIAL_STATES}
        validation_totals = {
            'provider_rows': 0,
            'row_count': 0,
            'policy_field_count': 0,
            'detected_candidates': 0,
            'assigned': 0,
            'unmatched': 0,
            'intentionally_excluded': 0,
        }
        initial_sample_count = 0
        no_provider_count = 0
        pending_provider_count = 0
        invalid_initial_count = 0
        carriers = {}
        for job in jobs:
            summary = (
                job.validation_summary
                if isinstance(job.validation_summary, dict) else {})
            system = summary.get('_system')
            system = system if isinstance(system, dict) else {}
            if system.get('provider_started') is not True:
                no_provider_count += 1
                continue
            has_metrics = 'initial_metrics' in system
            if not has_metrics and job.status == 'validating':
                pending_provider_count += 1
                continue
            metrics = self._validated_initial_metrics(
                job, results.get(job.pk))
            if metrics is None:
                invalid_initial_count += 1
                continue
            initial_sample_count += 1
            validation_totals['provider_rows'] += metrics['provider_rows']
            validation_totals['row_count'] += metrics['coverage_row_count']
            for key in (
                    'policy_field_count', 'detected_candidates', 'assigned',
                    'unmatched', 'intentionally_excluded'):
                validation_totals[key] += metrics[key]
            for state in self._INITIAL_STATES:
                state_counts[state] += metrics['coverage_state_counts'][state]
                policy_state_counts[state] += metrics['policy_state_counts'][state]
            carrier_code = metrics['carrier_code']
            if carrier_code is not None:
                carrier = carriers.setdefault(carrier_code, {
                    'carrier_code': carrier_code,
                    'sample_count': 0,
                    'assigned': 0,
                    'unmatched': 0,
                })
                carrier['sample_count'] += 1
                carrier['assigned'] += metrics['assigned']
                carrier['unmatched'] += metrics['unmatched']

        row_count = validation_totals['row_count']
        state_rates = {
            state: (
                round(state_counts[state] / row_count * 100, 1)
                if row_count else None)
            for state in self._INITIAL_STATES
        }
        by_carrier = []
        for carrier in carriers.values():
            total = carrier['assigned'] + carrier['unmatched']
            by_carrier.append({
                **carrier,
                'unmatched_rate': (
                    round(carrier['unmatched'] / total * 100, 1)
                    if total else None),
            })
        by_carrier.sort(
            key=lambda row: (
                -(row['unmatched_rate'] or 0), row['carrier_code']))

        confirmed_jobs = [job for job in jobs if job.status == 'confirmed']
        jobs_with_edits = sum(job.planner_edit_count > 0 for job in confirmed_jobs)
        provider_calls = sum(extraction_outcome_counts.values())
        successful_calls = extraction_outcome_counts.get('success', 0)
        failed_calls = provider_calls - successful_calls

        return {
            'job_count': job_count,
            'status_counts': status_counts,
            'queue_wait_ms': self._duration_summary(
                queue_values, queue_invalid),
            'current_queue_wait_ms': self._duration_summary(
                current_queue_values, current_queue_invalid),
            'processing_ms': self._duration_summary(
                processing_values, processing_invalid),
            'review_ms_proxy': self._duration_summary(
                review_values, review_invalid),
            'attempts': {
                'job_count': job_count,
                'total': attempts_total,
                'retry_attempts': retry_attempts,
                'retry_jobs': retry_jobs,
                'retry_job_rate': (
                    round(retry_jobs / job_count * 100, 1)
                    if job_count else None),
            },
            'leases': {
                'job_count': job_count,
                'expired': expired,
                'expired_jobs': expired_jobs,
                'expired_job_rate': (
                    round(expired_jobs / job_count * 100, 1)
                    if job_count else None),
            },
            'validation': {
                'initial_metrics_sample_count': initial_sample_count,
                'no_provider_job_count': no_provider_count,
                'pending_provider_metrics_count': pending_provider_count,
                'invalid_initial_metrics_count': invalid_initial_count,
                **validation_totals,
                'state_counts': state_counts,
                'state_rates': state_rates,
                'policy_state_counts': policy_state_counts,
                'confirmed_coverages': sum(
                    job.confirmed_coverage_count for job in jobs),
            },
            'corrections': {
                'confirmed_jobs': len(confirmed_jobs),
                'jobs_with_edits': jobs_with_edits,
                'job_correction_rate': (
                    round(jobs_with_edits / len(confirmed_jobs) * 100, 1)
                    if confirmed_jobs else None),
                'edit_actions': sum(
                    job.planner_edit_count for job in confirmed_jobs),
            },
            'failures': {
                'provider_calls': provider_calls,
                'failed_calls': failed_calls,
                'failure_rate': (
                    round(failed_calls / provider_calls * 100, 1)
                    if provider_calls else None),
                'zero_provider_rows': extraction_outcome_counts.get(
                    'empty', 0),
            },
            'by_carrier': by_carrier,
        }

    def get(self, request):
        from datetime import timedelta

        from django.db.models import Count, Sum
        from django.db.models.functions import TruncDate

        from inpa.billing.models import ClaudeApiLog

        try:
            days = int(request.query_params.get('days', 30))
        except (TypeError, ValueError):
            days = 30
        if days != 0:
            days = max(1, min(days, 365))

        qs = ClaudeApiLog.objects.exclude(internal_user_q('user'))
        since = None
        if days > 0:
            since = timezone.now() - timedelta(days=days)
            qs = qs.filter(created_at__gte=since)

        total_calls = qs.count()
        total_values = qs.aggregate(
            cost=Sum('cost_krw'),
            input=Sum('input_tokens'),
            output=Sum('output_tokens'),
            cache_read=Sum('cache_read_input_tokens'),
            cache_creation=Sum('cache_creation_input_tokens'),
        )
        total_cost_krw = total_values['cost'] or 0

        # outcome 분포 + 성공률
        outcome_counts = {}
        for row in qs.values('parse_outcome').annotate(c=Count('id')):
            bucket = self._safe_enum(
                row['parse_outcome'], self._SAFE_OUTCOMES)
            outcome_counts[bucket] = outcome_counts.get(bucket, 0) + row['c']
        success_count = outcome_counts.get(ClaudeApiLog.OUTCOME_SUCCESS, 0)
        success_rate = round(success_count / total_calls * 100, 1) if total_calls else None

        extraction_outcome_counts = {}
        for row in (
                qs.filter(action='insurance_extraction')
                .values('parse_outcome').annotate(c=Count('id'))):
            bucket = self._safe_enum(
                row['parse_outcome'], self._SAFE_OUTCOMES)
            extraction_outcome_counts[bucket] = (
                extraction_outcome_counts.get(bucket, 0) + row['c'])

        # 기능(action)별 호출수·추정비용
        action_totals = {}
        for row in (
                qs.values('action')
                .annotate(calls=Count('id'), cost=Sum('cost_krw'))):
            bucket = self._safe_enum(row['action'], self._SAFE_ACTIONS)
            total = action_totals.setdefault(
                bucket, {'action': bucket, 'calls': 0, 'cost_krw': 0})
            total['calls'] += row['calls']
            total['cost_krw'] += row['cost'] or 0
        by_action = sorted(
            action_totals.values(),
            key=lambda row: (-row['cost_krw'], row['action']),
        )

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
        from inpa.insurances.import_validation import ALLOWED_CARRIER_CODES

        by_carrier = []
        for r in (
            qs.filter(carrier_code__in=ALLOWED_CARRIER_CODES)
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
            'total_tokens': {
                'input': total_values['input'] or 0,
                'output': total_values['output'] or 0,
                'cache_read': total_values['cache_read'] or 0,
                'cache_creation': total_values['cache_creation'] or 0,
            },
            'cost_is_estimate': True,  # ★ FE 표기용 — 판정어 아닌 사실 플래그
            'usd_krw_rate': float(getattr(dj_settings, 'CLAUDE_USD_KRW_RATE', 1400.0)),
            'success_rate': success_rate,
            'outcome_counts': outcome_counts,
            'by_action': by_action,
            'daily': daily,
            'by_carrier': by_carrier,
            'insurance_review': self._insurance_review_metrics(
                since=since,
                extraction_outcome_counts=extraction_outcome_counts,
            ),
        })


class AdminInsuranceImportSettingsView(APIView):
    """증권 검토 worker 상한은 runtime, 출시 경계는 env 읽기 전용."""

    permission_classes = [IsAdmin]
    _EDITABLE_FIELDS = frozenset({
        'per_owner_concurrency',
        'global_concurrency',
        'force_manual_carrier_codes',
    })

    @staticmethod
    def _locked_config():
        from django.conf import settings as dj_settings

        from inpa.insurances.models import InsuranceImportRuntimeConfig

        config, _created = (
            InsuranceImportRuntimeConfig.objects
            .select_for_update()
            .get_or_create(pk=1, defaults={
                'per_owner_concurrency': getattr(
                    dj_settings, 'INSURANCE_IMPORT_PER_OWNER_LIMIT', 2),
                'global_concurrency': getattr(
                    dj_settings, 'INSURANCE_IMPORT_GLOBAL_LIMIT', 4),
            })
        )
        return config

    @staticmethod
    def _response(config):
        from django.conf import settings as dj_settings
        from inpa.insurances.import_validation import (
            sanitize_force_manual_carrier_codes,
        )

        return {
            'runtime': {
                'per_owner_concurrency': config.per_owner_concurrency,
                'global_concurrency': config.global_concurrency,
                'force_manual_carrier_codes': (
                    sanitize_force_manual_carrier_codes(
                        config.force_manual_carrier_codes)),
                'updated_at': config.updated_at,
            },
            'deployment': {
                'insurance_review_gate_enabled': bool(getattr(
                    dj_settings, 'INSURANCE_REVIEW_GATE_ENABLED', False)),
                'source_retention_hours': int(getattr(
                    dj_settings, 'INSURANCE_SOURCE_RETENTION_HOURS', 24)),
            },
        }

    def get(self, request):
        from inpa.insurances.models import InsuranceImportRuntimeConfig

        return Response(self._response(InsuranceImportRuntimeConfig.solo()))

    def patch(self, request):
        from inpa.insurances.import_validation import (
            ALLOWED_CARRIER_CODES,
            sanitize_force_manual_carrier_codes,
        )

        if not hasattr(request.data, 'keys'):
            return Response(
                {'code': 'INVALID_IMPORT_RUNTIME_CONFIG'},
                status=status.HTTP_400_BAD_REQUEST)
        unknown = set(request.data.keys()) - self._EDITABLE_FIELDS
        if unknown:
            return Response(
                {'code': 'INVALID_IMPORT_RUNTIME_CONFIG'},
                status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            config = self._locked_config()
            per_owner = request.data.get(
                'per_owner_concurrency', config.per_owner_concurrency)
            global_limit = request.data.get(
                'global_concurrency', config.global_concurrency)
            for value in (per_owner, global_limit):
                if type(value) is not int or not 1 <= value <= 100:
                    return Response(
                        {'code': 'INVALID_IMPORT_RUNTIME_CONFIG'},
                        status=status.HTTP_400_BAD_REQUEST)
            if per_owner > global_limit:
                return Response(
                    {'code': 'INVALID_IMPORT_RUNTIME_CONFIG'},
                    status=status.HTTP_400_BAD_REQUEST)

            codes = request.data.get(
                'force_manual_carrier_codes',
                config.force_manual_carrier_codes,
            )
            if (not isinstance(codes, list)
                    or any(type(code) is not int
                           or code not in ALLOWED_CARRIER_CODES
                           for code in codes)):
                return Response(
                    {'code': 'INVALID_IMPORT_RUNTIME_CONFIG'},
                    status=status.HTTP_400_BAD_REQUEST)
            config.per_owner_concurrency = per_owner
            config.global_concurrency = global_limit
            config.force_manual_carrier_codes = (
                sanitize_force_manual_carrier_codes(codes))
            config.save(update_fields=(
                'per_owner_concurrency',
                'global_concurrency',
                'force_manual_carrier_codes',
                'updated_at',
            ))
        return Response(self._response(config))


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
    가입 코호트(창 days 내 date_joined) 기준, 내부 계정 제외(AdminUsageView 관례).
    사실 카운트 + 단계별(직전 단계 대비) 전환율(%)만(§6 판정어 금지). UTM(utm_source, 없으면
    'direct') 별 가입·활성화 분해, 검색·AI·직접·기타 채널별 전 단계, 활성화 코호트 평균
    활성화 소요일수도 함께 반환.
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

        cohort_qs = User.objects.exclude(internal_user_q())
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
        channel_labels = {
            'search': '검색', 'ai': 'AI', 'direct': '직접', 'other': '기타',
        }
        channel_breakdown = {
            channel: {
                'channel': channel, 'label': label, 'signups': 0, 'verified': 0,
                'first_customers': 0, 'first_analyses': 0, 'first_shares': 0,
                'activated': 0,
            }
            for channel, label in channel_labels.items()
        }

        search_sources = {
            'google', 'google_organic', 'naver', 'naver_organic',
            'bing', 'bing_organic', 'daum', 'daum_organic',
        }
        ai_sources = {
            'chatgpt', 'openai', 'perplexity', 'gemini', 'bard',
            'claude', 'anthropic', 'copilot',
        }

        def _channel_for(source):
            normalized = source.strip().lower()
            if not normalized or normalized == 'direct':
                return 'direct'
            if normalized in search_sources:
                return 'search'
            if normalized in ai_sources:
                return 'ai'
            return 'other'

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

            channel_bucket = channel_breakdown[_channel_for(source)]
            channel_bucket['signups'] += 1
            channel_bucket['verified'] += int(reached_verified)
            channel_bucket['first_customers'] += int(reached_customer)
            channel_bucket['first_analyses'] += int(reached_analysis)
            channel_bucket['first_shares'] += int(reached_share)
            channel_bucket['activated'] += int(activated)

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
        acquisition_channels = [
            {
                **values,
                'activation_rate': _rate(values['activated'], values['signups']),
            }
            for values in channel_breakdown.values()
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
            'acquisition_channels': acquisition_channels,
            'avg_days_to_activation': avg_days_to_activation,
        })


class AdminConsultationSettingsView(APIView):
    permission_classes = [IsAdmin]

    @staticmethod
    def _response(config):
        pilots = ConsultationPilotAccess.objects.select_related('user').order_by(
            'user__email',
        )
        return {
            'environment_gate_open': bool(
                django_settings.CONSULTATION_RECORDING_ENABLED
            ),
            'ai_environment_gate_open': bool(
                django_settings.CONSULTATION_AI_SUMMARY_ENABLED
            ),
            'retention_days': current_retention_snapshot()['days'],
            'settings': AdminConsultationConfigSerializer(config).data,
            'status': consultation_status_snapshot(),
            'pilot_users': AdminConsultationPilotSerializer(
                pilots,
                many=True,
            ).data,
        }

    def get(self, request):
        return Response(self._response(ConsultationRuntimeConfig.solo()))

    def patch(self, request):
        if (
            request.data.get('recording_enabled') is True
            and not django_settings.CONSULTATION_RECORDING_ENABLED
        ):
            return Response(
                {
                    'code': 'CONSULTATION_ENV_GATE_CLOSED',
                    'detail': (
                        '환경 설정 검토를 마친 뒤 운영 스위치를 켤 수 있어요.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        if (
            request.data.get('ai_summary_enabled') is True
            and not django_settings.CONSULTATION_AI_SUMMARY_ENABLED
        ):
            return Response(
                {
                    'code': 'CONSULTATION_AI_ENV_GATE_CLOSED',
                    'detail': (
                        'AI 설정 검토를 마친 뒤 요약 스위치를 켤 수 있어요.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        with transaction.atomic():
            config = ConsultationRuntimeConfig.objects.select_for_update().get(
                pk=ConsultationRuntimeConfig.solo().pk,
            )
            serializer = AdminConsultationConfigSerializer(
                config,
                data=request.data,
                partial=True,
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(self._response(config))


_COMPARISON_AUDIO_ERROR_CODES = frozenset({
    'AUDIO_EMPTY',
    'AUDIO_FORMAT_UNSUPPORTED',
    'AUDIO_INVALID',
    'AUDIO_ONLY_REQUIRED',
    'AUDIO_TOO_LARGE',
    'AUDIO_TOO_LONG',
})


def _consultation_comparison_ready():
    return all((
        django_settings.OPENAI_API_KEY,
        django_settings.OPENAI_TRANSCRIPTION_MODEL,
        django_settings.OPENAI_COMPARISON_MODEL,
        django_settings.ANTHROPIC_API_KEY,
        django_settings.ANTHROPIC_COMPARISON_MODEL,
    ))


class AdminConsultationComparisonView(APIView):
    permission_classes = [IsAdmin]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consultation_comparison'

    def post(self, request):
        if not django_settings.CONSULTATION_AI_COMPARISON_ENABLED:
            return Response(
                {
                    'code': 'CONSULTATION_COMPARISON_CLOSED',
                    'detail': (
                        '내부 비교 설정을 켜면 바로 확인할 수 있어요.'
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if not _consultation_comparison_ready():
            return Response(
                {
                    'code': 'CONSULTATION_COMPARISON_NOT_READY',
                    'detail': (
                        '두 AI 연결 설정을 마치면 비교를 시작할 수 있어요.'
                    ),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        deadline = ComparisonDeadline.for_request()
        serializer = AdminConsultationComparisonSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data['synthetic_confirmed'] is not True:
            return Response(
                {
                    'code': 'SYNTHETIC_CONFIRMATION_REQUIRED',
                    'detail': '가상 녹음 확인을 선택해 주세요.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = ConsultationComparisonService().compare(
                serializer.validated_data['audio'],
                deadline=deadline,
            )
        except ComparisonAudioError as exc:
            code = (
                exc.code
                if exc.code in _COMPARISON_AUDIO_ERROR_CODES
                else 'AUDIO_INVALID'
            )
            return Response(
                {
                    'code': code,
                    'detail': '음성 파일을 확인한 뒤 다시 선택해 주세요.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ComparisonOutcomeUnknown:
            return Response(
                {
                    'code': 'TRANSCRIPTION_OUTCOME_UNKNOWN',
                    'detail': (
                        '처리 상태를 확인한 뒤 새 비교를 시작해 주세요.'
                    ),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ComparisonProviderFailure:
            return Response(
                {
                    'code': 'TRANSCRIPTION_FAILED',
                    'detail': (
                        '음성을 글로 바꾸는 단계를 다시 시작해 주세요.'
                    ),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(payload)


class AdminConsultationSummaryCompensateView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, run_id):
        with transaction.atomic():
            run = get_object_or_404(
                ConsultationSummaryRun.objects.select_for_update()
                .select_related('recording__owner'),
                pk=run_id,
            )
            if run.admin_compensated_at is None:
                owner = run.recording.owner
                if run.status == ConsultationSummaryRun.STATUS_SUCCEEDED:
                    release_meter(
                        user=owner,
                        action='consultation_summary',
                        amount=1,
                        year_month=run.usage_year_month,
                    )
                if (
                    run.provider_reserved_at is not None
                    and run.processing_minutes_reserved > 0
                    and run.minute_reservation_released_at is None
                ):
                    release_meter(
                        user=owner,
                        action='consultation_minute',
                        amount=run.processing_minutes_reserved,
                        year_month=run.usage_year_month,
                    )
                    run.minute_reservation_released_at = timezone.now()
                run.admin_compensated_at = timezone.now()
                run.save(update_fields=[
                    'minute_reservation_released_at',
                    'admin_compensated_at',
                    'updated_at',
                ])
        return Response({
            'id': run.id,
            'status': run.status,
            'admin_compensated_at': run.admin_compensated_at,
        })


class AdminConsultationPilotListView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = AdminConsultationPilotCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = get_object_or_404(
            User,
            email__iexact=serializer.validated_data['email'],
        )
        pilot, _ = ConsultationPilotAccess.objects.update_or_create(
            user=user,
            defaults={
                'recording_allowed': serializer.validated_data[
                    'recording_allowed'
                ],
                'summary_allowed': serializer.validated_data[
                    'summary_allowed'
                ],
            },
        )
        return Response(
            AdminConsultationPilotSerializer(pilot).data,
            status=status.HTTP_201_CREATED,
        )


class AdminConsultationPilotDetailView(APIView):
    permission_classes = [IsAdmin]

    def _pilot(self, user_id):
        return get_object_or_404(
            ConsultationPilotAccess.objects.select_related('user'),
            user_id=user_id,
        )

    def patch(self, request, user_id):
        pilot = self._pilot(user_id)
        serializer = AdminConsultationPilotUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(pilot, field, value)
        pilot.save(update_fields=[
            *serializer.validated_data.keys(),
            'updated_at',
        ])
        return Response(AdminConsultationPilotSerializer(pilot).data)

    def delete(self, request, user_id):
        self._pilot(user_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminLogoutView(APIView):
    """POST /api/v1/admin/auth/logout/ — 토큰 폐기."""
    permission_classes = [IsAdmin]

    def post(self, request):
        from rest_framework.authtoken.models import Token
        Token.objects.filter(user=request.user).delete()
        return Response({'message': '로그아웃되었습니다.'})
