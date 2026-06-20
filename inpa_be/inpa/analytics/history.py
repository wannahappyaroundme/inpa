"""고객 이력 타임라인 — GET /api/v1/customers/<customer_pk>/history/.

한 고객에게 일어난 영업 행동·동의·자산 등록 이벤트를 시간 역순 단일 타임라인으로 병합한다.
설계사가 "이 고객에게 무엇을 했나"를 한 화면에서 보게 하는 고객상세 보조 패널 데이터.

소스(여러 도메인 병합 — append-only 사실만, AI 없음):
  ① analytics.NorthStarEvent — share_created/share_view/clipboard_copy/ocr_upload/
     analysis_view/referral_attributed (해당 고객 customer FK 보유분만).
  ② customers.ConsentLog — 동의/철회 감사 로그 (customer FK).
  ③ insurances.CustomerInsurance — 증권/포트폴리오 등록(보유=1·제안=2·템플릿=0).

표준 형태(계약 — BE/FE 정확히 일치):
  GET /api/v1/customers/<id>/history/ → { events:[{type, label, at(iso), meta}] }
  - type : 안정 문자열 키(FE 아이콘/필터 매핑용 — 재정의 금지).
  - label: 사람이 읽는 한국어 요약(설계사 화면 표기).
  - at   : ISO8601 발생 시각(UTC 저장값 그대로 직렬화 — FE가 KST 표기).
  - meta : 타입별 부가 정보(object, 없으면 {}).
  데이터 없으면 events:[] (빈 배열, 200).

owner 격리: 부모 Customer 를 owner 스코프 쿼리로 잡는다(없으면 404 = 존재 자체 은폐).
  이벤트 소스 3종 모두 해당 customer 로만 필터 → 타 설계사 고객 이력 유출 물리 차단.

정직성 레드라인: 이력은 '사실'만 기록·표기한다. clipboard_copy 는 '복사'로 표기(자동발송 사칭 금지),
  '발송 완료' 류 단정 금지. 동의/철회는 감사 로그 사실 그대로.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.core.permissions import IsEmailVerified

from .models import NorthStarEvent

# NorthStarEvent.event_type(안정 문자열) → 사람이 읽는 한국어 라벨.
# ★ 키(왼쪽)는 모델 안정값 재사용 — 재정의 금지. 라벨(오른쪽)은 표기 변경 자유.
# clipboard_copy = '복사'(자동발송 사칭 금지, 정직성 레드라인).
_NORTHSTAR_LABELS = {
    NorthStarEvent.OCR_UPLOAD: '증권 OCR 업로드',
    NorthStarEvent.ANALYSIS_VIEW: '보장분석 조회',
    NorthStarEvent.SHARE_CREATED: '공유링크 발급',
    NorthStarEvent.CLIPBOARD_COPY: '공유뷰 복사',
    NorthStarEvent.SHARE_VIEW: '고객 공유뷰 열람',
    NorthStarEvent.REFERRAL_ATTRIBUTED: '인바운드 귀속',
}

# CustomerInsurance.portfolio_type → 라벨(증권/포트폴리오 등록 종류).
_PORTFOLIO_LABELS = {
    0: '템플릿 등록',
    1: '보유 증권 등록',
    2: '제안 보험 등록',
}


def _iso(dt):
    """datetime → ISO8601 문자열(없으면 None). UTC 저장값 그대로 — FE가 KST 표기."""
    return dt.isoformat() if dt is not None else None


def _northstar_events(customer):
    """① NorthStarEvent — 해당 고객 customer FK 보유 이벤트만 표준 형태로."""
    events = []
    qs = (NorthStarEvent.objects
          .filter(customer=customer)
          .only('event_type', 'channel', 'created_at', 'payload'))
    for ev in qs:
        events.append({
            'type': ev.event_type,
            'label': _NORTHSTAR_LABELS.get(ev.event_type, ev.event_type),
            'at': _iso(ev.created_at),
            'meta': {
                'channel': ev.channel or '',
                **(ev.payload or {}),
            },
        })
    return events


def _consent_events(customer):
    """② ConsentLog — 동의/철회 감사 로그(동의 1건이 철회되면 동의·철회 2개 이벤트로)."""
    events = []
    for log in customer.consent_logs.all():
        # 동의 이벤트
        events.append({
            'type': 'consent_agreed',
            'label': f'{log.get_scope_display()} 동의',
            'at': _iso(log.agreed_at),
            'meta': {
                'scope': log.scope,
                'doc_version': log.doc_version or '',
            },
        })
        # 철회 이벤트(있을 때만 — revoked_at 기록 시점)
        if log.revoked_at is not None:
            events.append({
                'type': 'consent_revoked',
                'label': f'{log.get_scope_display()} 철회',
                'at': _iso(log.revoked_at),
                'meta': {'scope': log.scope},
            })
    return events


def _insurance_events(customer):
    """③ CustomerInsurance 생성 — 증권/포트폴리오 등록 이벤트(보유/제안/템플릿)."""
    events = []
    qs = (customer.customer_insurance_list
          .only('id', 'name', 'portfolio_type', 'insurance_type', 'created_at'))
    for ci in qs:
        events.append({
            'type': 'insurance_registered',
            'label': _PORTFOLIO_LABELS.get(ci.portfolio_type, '증권 등록'),
            'at': _iso(ci.created_at),
            'meta': {
                'insurance_id': ci.id,
                'name': ci.name or '',
                'portfolio_type': ci.portfolio_type,
                'insurance_type': ci.insurance_type,
            },
        })
    return events


class CustomerHistoryView(APIView):
    """고객 이력 타임라인 — GET /api/v1/customers/<customer_pk>/history/ (인증·소유자).

    응답(계약 — BE/FE 정확히 일치):
      { events:[{type, label, at(iso), meta}] }  — created_at 기준 시간 역순.

    ★ owner 격리: 본인 고객이 아니면 404(존재 은폐). 데이터 없으면 events:[].
    크레딧 차감 없음(읽기 전용 집계).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def _get_customer(self, customer_pk):
        from rest_framework.exceptions import NotFound
        from inpa.customers.models import Customer
        qs = Customer.objects.all()
        if not self._is_admin():
            qs = qs.filter(owner=self.request.user)
        try:
            return qs.get(pk=customer_pk)
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')

    def get(self, request, customer_pk):
        customer = self._get_customer(customer_pk)

        events = (
            _northstar_events(customer)
            + _consent_events(customer)
            + _insurance_events(customer)
        )

        # 시간 역순 병합(at=None 은 맨 뒤로 — 시각 미상 이벤트 가드).
        events.sort(key=lambda e: e['at'] or '', reverse=True)

        return Response({'events': events})
