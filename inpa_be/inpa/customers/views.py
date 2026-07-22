"""고객 도메인 ViewSet (dev/12 §5 API 계약).

가시성 강제 3중(dev/02 §0):
  ① OwnedQuerySetMixin — get_queryset이 owner=request.user로 필터(관리자 bypass)
  ② permission [IsAuthenticated, IsEmailVerified, IsOwner] — 객체 단위 소유자 확인
  ③ 하위 라우트(태그/가족/병력/동의)는 부모 customer를 owner 격리 쿼리로 잡아 격리

★ 병력 등록 게이트(dev/12 §0 원칙 2): Customer.consent_overseas_at(국외이전 동의) 없으면
  CustomerMedicalHistory 생성을 412(PRECONDITION_FAILED)로 물리 차단. UI 숨김은 방어가 아니다.
"""
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.billing.credit import LimitExceeded, check_and_consume, check_and_consume_n
from inpa.analytics.events import log_event
from inpa.analytics.models import NorthStarEvent
from inpa.core.mixins import OwnedQuerySetMixin
from inpa.core.permissions import IsEmailVerified, IsOwner
from inpa.insurances.models import CustomerInsurance
# 날짜 파싱·다음 생일 계산은 알림 생산자와 동일 로직 재사용(단방향 import — 순환 없음).
from inpa.notifications.jobs import _next_birthday, _parse_date

from .consent_texts import CONSENT_TEXTS_VERSION, has_current_overseas_consent
from .models import (
    ConsentLog, ContactLog, ContractChecklistItem, Customer, CustomerMedicalHistory,
    CustomerMemo, CustomerTag, FamilyMember, JobRiskCode, PlannerBaseline, DEFAULT_CONTRACT_CHECKLIST,
)
from .memos import create_manual_memo, sync_legacy_memo, update_memo
from .presets import (
    BASELINE_SOURCE_PRESET, PRESET_NOTE, PRESET_ORIGIN_V0, PRESET_V0,
    iter_preset_rows,
)
from .serializers import (
    ConsentLogSerializer, ContactLogSerializer, ContractChecklistItemSerializer, CustomerListSerializer,
    CustomerMemoSerializer, CustomerSerializer, CustomerMedicalHistorySerializer, CustomerTagSerializer,
    FamilyMemberSerializer, JobRiskCodeSerializer, PlannerBaselineSerializer,
)
from .tokens import make_consent_token


def _to_int(v):
    """일괄 등록 행의 숫자 필드(직업 id 등)를 안전하게 int로. 실패 시 None."""
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _credit_exhausted_response(exc: LimitExceeded, user) -> Response:
    """LimitExceeded → 402 Payment Required (dev/02 §16 shape, insurances/views.py와 동일 패턴).

    FE는 402 + code='credit_exhausted' 수신 시 UpgradeGuideModal 표시(kind='customer').
    """
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

    SUBSTANTIVE = {
        'name', 'gender', 'birth_day', 'mobile_phone_number',
        'job_code', 'memo', 'color', 'avatar_label',
        'lead_source', 'is_agree_term', 'sales_stage', 'tag_ids',
    }

    @staticmethod
    def _log_memo_bridge_event(serializer, sender):
        event = getattr(serializer, 'memo_bridge_event', None)
        if not event:
            return
        action, memo = event
        if action == 'created':
            event_type = NorthStarEvent.CONSULTATION_MEMO_CREATED
        elif action == 'edited':
            event_type = NorthStarEvent.CONSULTATION_MEMO_EDITED
        else:
            return
        log_event(
            event_type,
            customer=memo.customer,
            sender=sender,
            payload={'source': memo.source},
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
        self._log_memo_bridge_event(serializer, self.request.user)

    def perform_update(self, serializer):
        keys = set(self.request.data.keys())
        if (keys & self.SUBSTANTIVE) - {'memo'}:
            serializer.save(last_contacted_at=timezone.now())
        else:
            serializer.save()
        self._log_memo_bridge_event(serializer, self.request.user)

    def create(self, request, *args, **kwargs):
        """단건 등록 — 신규 고객 추가 한도 강제(spec 2026-07-09 pricing-limits-align).

        ★ FREE_TIER_UNLIMITED(베타 바이패스)이면 check_and_consume이 내부에서 우회 —
          베타 기간에는 지금과 동일하게 무제한(dormant), 유료 전환(False) 시에만 발동한다.
        ★ 인바운드 자동 리드(셀프진단 /d, 소개카드 /p)는 Customer.objects.create()를 직접
          호출해 이 create()를 거치지 않으므로 이 한도와 무관하다(설계사 능동 등록만 집계).
        검증(serializer.is_valid) 통과 후에만 한도를 소비한다 — 잘못된 요청으로 소비되지 않도록
        (DRF CreateModelMixin.create()와 동일 순서, 사이에 한도 체크만 끼워 넣는다).
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            check_and_consume(request.user, 'customer')
        except LimitExceeded as exc:
            return _credit_exhausted_response(exc, request.user)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=['post'], url_path='bulk')
    def bulk_create(self, request):
        """여러 고객을 한 번에 등록 — POST /api/v1/customers/bulk/.

        body: {"customers": [{"name", "mobile_phone_number"?, "gender"?, "birth_day"?,
          "job_code"?, "memo"?, "lead_source"?, "avatar_label"?, "color"?, "sales_stage"?}, ...]}.
        단건 등록과 동일 필드 세트(전부 선택, name만 필수·빈 행 skip). 모델 제약대로 길이·선택지 검증.
        (이름+연락처) 중복(기존 고객 또는 같은 배치 내)은 건너뜀. owner 자동 주입.
        직업급수(job_code)는 전역 마스터 id — 실제 존재하는 id만 반영(없는 값·비정상은 무시).
        """
        rows = request.data.get('customers')
        if not isinstance(rows, list) or not rows:
            raise ValidationError({'customers': '등록할 고객 목록이 비었어요.'})
        if len(rows) > 200:
            raise ValidationError({'customers': '한 번에 최대 200명까지 등록할 수 있어요.'})
        owner = request.user
        existing = set(
            Customer.objects.filter(owner=owner).values_list('name', 'mobile_phone_number'))
        valid_stages = {c[0] for c in Customer.SALES_STAGE_CHOICES}
        valid_leads = {c[0] for c in Customer.LEAD_SOURCE_CHOICES}
        # 직업급수 FK — 요청에 실린 id 중 실제 존재하는 것만 미리 조회(1 쿼리).
        raw_job_ids = {
            jid for row in rows if isinstance(row, dict)
            for jid in [_to_int(row.get('job_code'))] if jid is not None
        }
        valid_job_ids = set(
            JobRiskCode.objects.filter(id__in=raw_job_ids).values_list('id', flat=True)
        ) if raw_job_ids else set()

        seen = set()
        to_create = []
        memo_bodies = []
        skipped = 0
        for row in rows:
            if not isinstance(row, dict):
                skipped += 1
                continue
            name = (row.get('name') or '').strip()[:20]
            if not name:
                skipped += 1
                continue
            phone = (row.get('mobile_phone_number') or '').strip()[:15]
            key = (name, phone)
            if key in existing or key in seen:
                skipped += 1
                continue
            seen.add(key)

            stage = row.get('sales_stage')
            if stage not in valid_stages:
                stage = Customer.STAGE_DB
            lead = row.get('lead_source')
            if lead not in valid_leads:
                lead = Customer.LEAD_DIRECT
            gender_raw = str(row.get('gender')).strip()
            gender = int(gender_raw) if gender_raw in ('1', '2') else None
            jid = _to_int(row.get('job_code'))
            job_id = jid if jid in valid_job_ids else None

            memo = (row.get('memo') or '').strip()
            to_create.append(Customer(
                owner=owner,
                name=name,
                mobile_phone_number=phone,
                gender=gender,
                birth_day=(row.get('birth_day') or '').strip()[:10],
                memo=memo,
                color=(row.get('color') or '').strip()[:10],
                avatar_label=(row.get('avatar_label') or '').strip()[:8],
                job_code_id=job_id,
                sales_stage=stage,
                lead_source=lead,
            ))
            memo_bodies.append(memo)
        if to_create:
            # ★ 신규 고객 추가 한도(spec 2026-07-09) — 실제로 만들 건수(중복·빈 행 제외한
            #   len(to_create))만큼 잔여 한도를 확인한다. 잔여 < N이면 전량 402(부분 생성 없음)
            #   — bulk_create 자체를 아예 호출하지 않는다. 베타(FREE_TIER_UNLIMITED)는 dormant.
            try:
                with transaction.atomic():
                    check_and_consume_n(owner, 'customer', len(to_create))
                    Customer.objects.bulk_create(to_create)
                    for customer, memo_body in zip(to_create, memo_bodies):
                        if not memo_body:
                            continue
                        memo, event = sync_legacy_memo(
                            customer=customer,
                            owner=owner,
                            body=memo_body,
                            source=CustomerMemo.SOURCE_MANUAL,
                        )
                        if event == 'created':
                            log_event(
                                NorthStarEvent.CONSULTATION_MEMO_CREATED,
                                customer=memo.customer,
                                sender=owner,
                                payload={'source': memo.source},
                            )
            except LimitExceeded as exc:
                return _credit_exhausted_response(exc, owner)
        return Response({'created': len(to_create), 'skipped': skipped},
                        status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='call-list')
    def call_list(self, request):
        """오늘 전화 리스트 — GET /api/v1/customers/call-list/ (spec 2026-07-05).

        pull 방식 큐: 화면을 열 때 계산(배치와 무관하게 항상 동작). 대상 = 본인 소유
        (OwnedQuerySetMixin 큐리셋 기반) + 진행중(active)만.
        `?limit=` 지원(기본 10, 최대 50, 비정상 값은 기본값) + total_candidates.
        기본 10(상한 50). 유일한 FE 호출부는 전용 화면(/call-list, limit=50).

        score(결정적·투명) =
          생일 임박(D-day ≤ 7):            100 - dday*10
          만기 임박(보유계약 최근접 0~30): 80 - dday*2  (알림 생산자와 동일 필터)
          무접촉:                          min(무접촉일수, 60)  (앵커 = last_contacted_at
                                           없으면 created_at, KST 날짜 기준)
          단계 보정: TA(contact)/FA(meeting)면 +10 — 단, 위 사유가 하나라도 있을 때만
          (사유 없는 고객은 score 0으로 제외한다는 원칙과 일치시키기 위함).
        동점은 무접촉일수 내림차순(같으면 id 오름차순 — 결정성).
        reasons 는 그대로 칩으로 렌더 가능한 한글 라벨(판정어 없음 — 연락 우선순위일 뿐).
        """
        # limit 파싱 — 비정상(숫자 아님·0 이하)은 기본 10, 상한 50 클램프.
        try:
            limit = int(request.query_params.get('limit', 10))
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 10
        limit = min(limit, 50)

        today = timezone.localdate()
        # 고객 1쿼리 — values_list 라 mixin 의 prefetch 는 실행되지 않는다.
        rows = list(
            self.get_queryset()
            .filter(status=Customer.STATUS_ACTIVE)
            .values_list('id', 'name', 'mobile_phone_number', 'sales_stage',
                         'birth_day', 'last_contacted_at', 'created_at'))
        ids = [r[0] for r in rows]

        # 보험 1쿼리 — 만기 후보는 알림 생산자(produce_expiry_soon)와 동일 필터.
        # 고객별 최근접 만기 D-day(0~30)만 유지. owner 격리는 ids 경유로 보장.
        nearest_expiry = {}
        if ids:
            ins = (CustomerInsurance.objects
                   .filter(customer_id__in=ids, portfolio_type=1, is_cancelled=False)
                   .exclude(expiry_date__isnull=True)
                   .exclude(expiry_date='')
                   .values_list('customer_id', 'expiry_date'))
            for cid, raw in ins:
                exp = _parse_date(raw)
                if exp is None:
                    continue
                dday = (exp - today).days
                if dday < 0 or dday > 30:
                    continue
                if cid not in nearest_expiry or dday < nearest_expiry[cid]:
                    nearest_expiry[cid] = dday

        candidates = []
        for cid, name, phone, stage, birth_raw, last_contacted, created in rows:
            score = 0
            reasons = []
            birth = _parse_date(birth_raw)
            if birth is not None:
                bday = _next_birthday(birth, today)
                if bday is not None:
                    d = (bday - today).days
                    if d <= 7:
                        score += 100 - d * 10
                        reasons.append('오늘 생일' if d == 0 else f'생일 D-{d}')
            if cid in nearest_expiry:
                d = nearest_expiry[cid]
                score += 80 - d * 2
                reasons.append('오늘 만기' if d == 0 else f'만기 D-{d}')
            anchor = last_contacted or created
            idle_days = max(0, (today - timezone.localtime(anchor).date()).days)
            if idle_days > 0:
                score += min(idle_days, 60)
                reasons.append(f'무접촉 {idle_days}일')
            if score <= 0:
                continue  # 사유 없음 → 제외(단계 보정 단독으로는 오르지 않음)
            if stage in (Customer.STAGE_CONTACT, Customer.STAGE_MEETING):
                score += 10  # 진행 모멘텀 보정
            candidates.append({
                'id': cid,
                'name': name,
                'mobile_phone_number': phone,
                'sales_stage': stage,
                'score': score,
                'reasons': reasons,
                'last_contacted_at': (timezone.localtime(last_contacted).isoformat()
                                      if last_contacted else None),
                '_idle': idle_days,
            })
        candidates.sort(key=lambda c: (-c['score'], -c['_idle'], c['id']))
        results = [{k: v for k, v in c.items() if k != '_idle'}
                   for c in candidates[:limit]]
        return Response({'results': results, 'total_candidates': len(candidates)})


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
        if not has_current_overseas_consent(customer):
            reason = 'reconsent' if customer.consent_overseas_at is not None else 'missing'
            return Response(
                {'code': 'CONSENT_OVERSEAS_REQUIRED', 'reason': reason,
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
                        subject=ConsentLog.SUBJECT_PLANNER_ATTESTED,
                        doc_version=CONSENT_TEXTS_VERSION)


class ContractChecklistViewSet(_CustomerScopedViewSet):
    """계약 설명의무 체크리스트 — /api/v1/customers/<customer_pk>/checklist/ (소유자 전용).

    apply-template = 기본 설명의무 항목 일괄 생성(멱등). toggle = 완료 토글(done_at 기록).
    """
    serializer_class = ContractChecklistItemSerializer
    queryset = ContractChecklistItem.objects.all()

    def perform_create(self, serializer):
        serializer.save(customer=self.get_customer(), owner=self.request.user)

    def apply_template(self, request, customer_pk=None):
        customer = self.get_customer()
        if ContractChecklistItem.objects.filter(customer=customer).exists():
            return Response({'created': 0, 'detail': '이미 체크리스트가 있어요.'})
        items = [ContractChecklistItem(owner=request.user, customer=customer, label=lbl, order=i)
                 for i, lbl in enumerate(DEFAULT_CONTRACT_CHECKLIST)]
        ContractChecklistItem.objects.bulk_create(items)
        return Response({'created': len(items)}, status=status.HTTP_201_CREATED)

    def toggle(self, request, customer_pk=None, pk=None):
        item = self.get_object()
        item.is_done = not item.is_done
        item.done_at = timezone.now() if item.is_done else None
        item.save(update_fields=['is_done', 'done_at', 'updated_at'])
        return Response(self.get_serializer(item).data)


class ContactLogViewSet(_CustomerScopedViewSet):
    """접촉 결과 로그 — /api/v1/customers/<customer_pk>/contact-logs/ (소유자 전용, append-only).

    전화·문자 결과(부재중·연결·약속·거절·보류)+메모 기록. 생성 시 Customer.last_contacted_at 동시 갱신
    (방치 경보 리셋 = 기존 '방금 연락함'과 동일 효과). UPDATE/DELETE는 차단(활동 이력 무결성).
    """
    serializer_class = ContactLogSerializer
    queryset = ContactLog.objects.all()
    http_method_names = ['get', 'post', 'head', 'options']  # append-only

    def perform_create(self, serializer):
        customer = self.get_customer()
        serializer.save(customer=customer, owner=self.request.user)
        # 접촉 기록 = 연락한 사실 → 무접촉 경보 리셋(기존 markContacted와 동일).
        customer.last_contacted_at = timezone.now()
        customer.save(update_fields=['last_contacted_at'])


class CustomerMemoViewSet(_CustomerScopedViewSet):
    """고객 상담 메모 CRUD — 생성만 고객 접촉 시각을 갱신한다."""
    serializer_class = CustomerMemoSerializer
    queryset = CustomerMemo.objects.all()
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return (super().get_queryset()
                .annotate(display_at=Coalesce('occurred_at', 'created_at'))
                .order_by('-display_at', '-created_at', '-id'))

    def perform_create(self, serializer):
        memo = create_manual_memo(
            customer=self.get_customer(), owner=self.request.user,
            body=serializer.validated_data['body'])
        serializer.instance = memo
        log_event(
            NorthStarEvent.CONSULTATION_MEMO_CREATED,
            customer=memo.customer,
            sender=self.request.user,
            payload={'source': memo.source},
        )

    def create(self, request, *args, **kwargs):
        self.get_customer()
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        memo = self.get_object()
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        revision = request.data.get('revision')
        if type(revision) is not int:
            return Response(
                {'code': 'MEMO_REVISION_REQUIRED',
                 'detail': '최신 메모를 다시 불러와 주세요.'},
                status=status.HTTP_400_BAD_REQUEST)
        if 'body' not in serializer.validated_data:
            return Response(
                {'body': ['메모 내용을 입력해 주세요.']},
                status=status.HTTP_400_BAD_REQUEST)
        try:
            memo = update_memo(
                memo=memo, body=serializer.validated_data['body'],
                expected_revision=revision)
        except ValueError as exc:
            if str(exc) == 'MEMO_EDIT_CONFLICT':
                return Response(
                    {'code': 'MEMO_EDIT_CONFLICT',
                     'detail': '다른 화면에서 수정된 메모예요. 최신 내용을 확인해 주세요.'},
                    status=status.HTTP_409_CONFLICT)
            raise
        if memo.revision != revision:
            log_event(
                NorthStarEvent.CONSULTATION_MEMO_EDITED,
                customer=memo.customer,
                sender=self.request.user,
                payload={'source': memo.source},
            )
        return Response(self.get_serializer(memo).data)


class ConsentRequestCreateView(APIView):
    """동의 요청 링크 생성 — POST /api/v1/customers/<customer_pk>/consent-requests/ (P3c).

    설계사(소유자)가 본인 고객의 '국외이전 동의 요청' 링크를 만든다. 고객이 본인 기기에서
    /c/<token> 로 열어 직접 동의해야 OCR 게이트가 열린다(설계사 대리동의 불가).
    링크 전달은 FE에서 클립보드 복사/카톡 열기까지만(자동발송 없음 — 정직성 레드라인).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    # 허용 동의 scope 화이트리스트(요청 링크로 받을 수 있는 것).
    _ALLOWED_REQUEST_SCOPES = {
        ConsentLog.SCOPE_PERSONAL_INFO,
        ConsentLog.SCOPE_MARKETING,
        ConsentLog.SCOPE_OVERSEAS_MEDICAL,
    }

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
        scopes = request.data.get('scopes')
        if scopes is None:
            scopes = [ConsentLog.SCOPE_OVERSEAS_MEDICAL]
        if not isinstance(scopes, list) or not scopes:
            raise ValidationError({'scopes': 'scopes는 비어있지 않은 배열이어야 합니다.'})
        bad = [s for s in scopes if s not in self._ALLOWED_REQUEST_SCOPES]
        if bad:
            raise ValidationError({'scopes': f'허용되지 않은 동의 종류: {bad}'})
        token = make_consent_token(customer, scopes=scopes)
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
        # ★ PRESET_DISABLED — 인파 제공 기준은 §97/무등록중개 레드라인으로 비활성.
        #    설계사 직접 입력(source='planner')만 허용. 아래 로직은 삭제하지 않고 보존.
        return Response(
            {'code': 'PRESET_DISABLED',
             'detail': '기준은 설계사님이 직접 입력해 주세요. (인파는 적정 금액을 제공하지 않습니다.)'},
            status=status.HTTP_400_BAD_REQUEST)

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


class JobSearchView(APIView):
    """직업급수 검색 — 전역 마스터(JobRiskCode). 인증만 필요(소유자 무관 = 공유 데이터).

    GET /api/v1/jobs/search/?q=시의원&limit=30
      - 이름·약명·검색어(synonym)·KIDI코드 substring 매칭(설명은 표시용이라 검색 제외).
      - 관련도(정확>접두>이름포함>약명>검색어) → 이름 길이 순으로 정렬, 최대 limit(≤50).
      - 빈 q → 빈 결과. 응답 {results: [JobRiskCode...]}.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = (request.query_params.get('q') or '').strip()
        if not q:
            return Response({'results': []})
        try:
            limit = min(int(request.query_params.get('limit', 30)), 50)
        except (TypeError, ValueError):
            limit = 30

        matches = list(JobRiskCode.objects.filter(
            Q(name__icontains=q) | Q(alt_name__icontains=q)
            | Q(synonym__icontains=q) | Q(kidi_cd__icontains=q)
        ))

        def score(j):
            n, a, s = j.name, (j.alt_name or ''), (j.synonym or '')
            if n == q:
                return 0
            if n.startswith(q):
                return 1
            if q in n:
                return 2
            if q in a:
                return 3
            if q in s:
                return 4
            return 5

        ranked = sorted(matches, key=lambda j: (score(j), len(j.name)))[:limit]
        return Response({'results': JobRiskCodeSerializer(ranked, many=True).data})
