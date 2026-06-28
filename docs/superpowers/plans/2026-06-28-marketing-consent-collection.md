# 마케팅·개인정보 동의 수집 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고객 DB를 합법적으로 보유·활용할 근거(개인정보 수집·이용 + 마케팅 수신 동의)를 분리 수집해 감사 로그로 쌓는다.

**Architecture:** 기존 `ConsentLog`(append-only) + `subject`(본인/대리) + `/c` 공개 동의 동선을 재사용한다. scope 1개(`personal_info`) 추가, 토큰을 다목적화(하위호환), `/c` 페이지를 다항목 동의로 일반화, 시리얼라이저에서 동의 상태 파생. 고객 테이블 신규 칼럼 0개.

**Tech Stack:** Django 4.2 + DRF(BE, `inpa_be/`), Next.js 16 + React 19 + TS(FE, `inpa_fe/`). 설계서: `docs/superpowers/specs/2026-06-28-marketing-consent-collection-design.md`.

## Global Constraints

- **정직성 레드라인**: 자동발송 없음(클립보드 복사/카톡 열기까지만). "본인 동의"와 "설계사 기록(대리)"을 화면에서 구분 표기. AI/분석 단정 금지.
- **분리 동의(개보법)**: 개인정보 수집·이용(필수)과 마케팅 수신(선택)은 별도 체크. 묶음 강제 금지.
- **대리기록 강등**: 설계사가 찍는 동의는 `subject=planner_attested`로만 서버 강제(`serializers.py:51` read_only + `views.py:151`). 국외이전 게이트를 열지 못함.
- **토큰 하위호환 필수**: 이미 발급된 구 토큰(서명된 int pk)은 `overseas_medical`로 해석. OCR 동선 동작 무변경.
- **테마 가드레일**: 서비스 페이지 라이트 고정. `dark:` 변형 추가 금지(어드민 외).
- **쉬운 말 카피**: 제품 UI에 `§`·법조문 표기 금지. 동의 고지문은 보수적 표준 + "유료 전 법무 재검토" 정신.
- **FE 테스트 러너 없음**: FE 검증 = `npm run build`(타입체크 겸함). BE 검증 = `python manage.py test`.
- **Next 16 주의**(`inpa_fe/AGENTS.md`): 새 API 사용 시 `node_modules/next/dist/docs/` 확인. 이 플랜은 기존 컴포넌트·문자열 수정 위주라 신규 Next API 없음.
- 명령 실행 위치: BE는 `inpa_be/`에서, FE는 `inpa_fe/`에서.

---

## File Structure

**백엔드 (`inpa_be/inpa/`)**
- `customers/models.py` — `ConsentLog.SCOPE_PERSONAL_INFO` 추가 (Task 1)
- `customers/tokens.py` — 토큰 다목적화 + 하위호환 (Task 1)
- `customers/migrations/00XX_*.py` — choices 상태 마이그레이션 (Task 1)
- `customers/public_consent.py` — 다항목 동의 GET/POST (Task 2)
- `customers/views.py` — `ConsentRequestCreateView` scopes 수용 (Task 3)
- `customers/serializers.py` — `_consent_state` 파생 + 필드 (Task 4)
- `insurances/self_diagnosis.py` — personal_info 항상 + marketing 선택 (Task 5)
- `customers/tests.py`, `insurances/tests.py` — 테스트

**프론트엔드 (`inpa_fe/`)**
- `lib/api.ts` — 타입·함수 (Task 6, 7)
- `app/c/[token]/page.tsx` — 다항목 동의 UI (Task 7)
- `app/customer/[id]/page.tsx` — 동의 배지 2종 + 링크 버튼 (Task 8)
- `components/customer-create-modal.tsx` — 등록 동의 체크 (Task 9)
- `app/d/[ref]/page.tsx` — 마케팅 수신 선택 (Task 10)

---

## Task 1: BE — ConsentLog scope + 토큰 다목적화

**Files:**
- Modify: `inpa_be/inpa/customers/models.py:273-280`
- Modify: `inpa_be/inpa/customers/tokens.py`
- Create: `inpa_be/inpa/customers/migrations/00XX_consentlog_personal_info.py` (makemigrations 자동 생성)
- Test: `inpa_be/inpa/customers/tests.py`

**Interfaces:**
- Produces: `ConsentLog.SCOPE_PERSONAL_INFO = 'personal_info'`. `make_consent_token(customer, scopes=None) -> str`. `read_consent_token(token) -> {'pk': int, 'scopes': list[str]}` (항상 dict; 구 int 토큰 → `{'pk', 'scopes':['overseas_medical']}`).

- [ ] **Step 1: 실패 테스트 작성** — `inpa_be/inpa/customers/tests.py` 끝에 추가

```python
from .tokens import make_consent_token, read_consent_token  # 파일 상단에 이미 import됨(20행) — 중복이면 생략


class ConsentTokenScopeTests(TestCase):
    """토큰 다목적화 + 하위호환 + personal_info scope."""

    def setUp(self):
        self.user, self.client = _make_planner('tok@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')

    def test_personal_info_scope_exists(self):
        self.assertEqual(ConsentLog.SCOPE_PERSONAL_INFO, 'personal_info')
        self.assertIn('personal_info', dict(ConsentLog.SCOPE_CHOICES))

    def test_token_roundtrip_with_scopes(self):
        tok = make_consent_token(self.customer, scopes=['personal_info', 'marketing'])
        data = read_consent_token(tok)
        self.assertEqual(data['pk'], self.customer.pk)
        self.assertEqual(set(data['scopes']), {'personal_info', 'marketing'})

    def test_token_default_scope_is_overseas(self):
        data = read_consent_token(make_consent_token(self.customer))
        self.assertEqual(data['scopes'], ['overseas_medical'])

    def test_legacy_int_token_backward_compat(self):
        from .tokens import CONSENT_SALT
        legacy = signing.dumps(self.customer.pk, salt=CONSENT_SALT)  # 구 형식: pk(int) 직접
        data = read_consent_token(legacy)
        self.assertEqual(data['pk'], self.customer.pk)
        self.assertEqual(data['scopes'], ['overseas_medical'])
```

- [ ] **Step 2: 실패 확인**

Run (in `inpa_be/`): `python manage.py test inpa.customers.tests.ConsentTokenScopeTests -v 2`
Expected: FAIL — `AttributeError: SCOPE_PERSONAL_INFO` / token이 int 반환.

- [ ] **Step 3: models.py scope 추가** — `customers/models.py:273` 블록 교체

```python
    SCOPE_OVERSEAS_MEDICAL = 'overseas_medical'
    SCOPE_MEDICAL_SENSITIVE = 'medical_sensitive'
    SCOPE_MARKETING = 'marketing'
    SCOPE_PERSONAL_INFO = 'personal_info'          # ✦ 개인정보 수집·이용(DB 보유 근거)
    SCOPE_CHOICES = (
        (SCOPE_OVERSEAS_MEDICAL, '병력 국외이전 (Claude API, 미국)'),
        (SCOPE_MEDICAL_SENSITIVE, '민감정보(병력) 처리'),
        (SCOPE_MARKETING, '마케팅 수신'),
        (SCOPE_PERSONAL_INFO, '개인정보 수집·이용'),
    )
```

- [ ] **Step 4: tokens.py 다목적화** — `customers/tokens.py` 전체 교체

```python
"""고객 동의 요청 토큰 — 별도 DB 테이블 없는 stateless 서명 방식 (P3c).

설계사가 '동의 요청 링크'를 만들면 customer.pk + 요청 동의 scope를 서명한 토큰을 발급한다.
고객이 본인 기기에서 /c/<token> 로 열어 해당 동의를 직접 한다.
accounts/tokens.py(이메일 인증) 패턴 — TimestampSigner(max_age).
★ 하위호환: 구 토큰(서명된 int pk)은 국외이전(overseas_medical) 단일 동의로 해석.
"""
from django.conf import settings
from django.core import signing

from .models import ConsentLog

CONSENT_SALT = 'inpa-consent-request'


def make_consent_token(customer, scopes=None):
    """customer.pk + 요청 scope 목록을 서명한 동의요청 토큰 발급.
    scopes 미지정 시 국외이전 단일(기존 OCR 동선 호환)."""
    payload = {'pk': customer.pk,
               'scopes': scopes or [ConsentLog.SCOPE_OVERSEAS_MEDICAL]}
    return signing.dumps(payload, salt=CONSENT_SALT)


def read_consent_token(token):
    """유효하면 {'pk': int, 'scopes': [str]} 반환. 만료/위조면 signing 예외.
    구 토큰(int pk)은 국외이전 단일로 정규화."""
    max_age = settings.CONSENT_TOKEN_TTL_HOURS * 3600
    data = signing.loads(token, salt=CONSENT_SALT, max_age=max_age)
    if isinstance(data, int):
        return {'pk': data, 'scopes': [ConsentLog.SCOPE_OVERSEAS_MEDICAL]}
    return data
```

- [ ] **Step 5: 마이그레이션 생성**

Run (in `inpa_be/`): `python manage.py makemigrations customers`
Expected: `Migrations for 'customers': 00XX_..._alter_consentlog_scope.py` (DB 스키마 무변경 상태 마이그레이션).

- [ ] **Step 6: 통과 확인**

Run: `python manage.py test inpa.customers.tests.ConsentTokenScopeTests -v 2`
Expected: PASS (4 tests).

- [ ] **Step 7: 커밋**

```bash
git add inpa_be/inpa/customers/models.py inpa_be/inpa/customers/tokens.py inpa_be/inpa/customers/migrations/ inpa_be/inpa/customers/tests.py
git commit -m "feat(동의): ConsentLog personal_info scope + 토큰 다목적화(하위호환)"
```

---

## Task 2: BE — 공개 동의 페이지 다항목화 (`/c`)

**Files:**
- Modify: `inpa_be/inpa/customers/public_consent.py` (전체 재작성)
- Test: `inpa_be/inpa/customers/tests.py`

**Interfaces:**
- Consumes: `read_consent_token(token) -> {'pk','scopes'}` (Task 1).
- Produces:
  - `GET /api/v1/c/<token>/` → `{customer:{name_masked}, planner:{affiliation}, items:[{scope,title,required,already,lines:[str],notice}], all_required_done:bool, disclaimer:str}`
  - `POST /api/v1/c/<token>/` body `{agreed:[scope,...]}` → 필수 미동의 시 412, 아니면 동의 scope마다 `ConsentLog(customer_self)` 생성(멱등) + overseas면 `consent_overseas_at` 스냅샷. 응답 `{results:[{scope,consented,agreed_at}], all_required_done:true}`.

- [ ] **Step 1: 실패 테스트 작성** — `customers/tests.py` 끝에 추가

```python
class PublicConsentMultiScopeTests(TestCase):
    """공개 /c 다항목 동의 — 개인정보(필수)+마케팅(선택)."""

    def setUp(self):
        cache.clear()  # throttle 격리
        self.user, _ = _make_planner('pc@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')
        self.anon = APIClient()  # 비인증(공개 경로)

    def _token(self, scopes):
        return make_consent_token(self.customer, scopes=scopes)

    def test_get_returns_requested_items(self):
        tok = self._token(['personal_info', 'marketing'])
        r = self.anon.get(f'/api/v1/c/{tok}/')
        self.assertEqual(r.status_code, 200)
        scopes = [it['scope'] for it in r.json()['items']]
        self.assertEqual(scopes, ['personal_info', 'marketing'])
        pi = next(it for it in r.json()['items'] if it['scope'] == 'personal_info')
        self.assertTrue(pi['required'])

    def test_post_agreed_creates_customer_self_logs(self):
        tok = self._token(['personal_info', 'marketing'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['personal_info', 'marketing']}, format='json')
        self.assertEqual(r.status_code, 201)
        logs = ConsentLog.objects.filter(customer=self.customer)
        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(l.subject == ConsentLog.SUBJECT_CUSTOMER_SELF for l in logs))

    def test_post_missing_required_returns_412(self):
        tok = self._token(['personal_info', 'marketing'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['marketing']}, format='json')  # 필수 누락
        self.assertEqual(r.status_code, 412)
        self.assertEqual(ConsentLog.objects.filter(customer=self.customer).count(), 0)

    def test_overseas_token_sets_snapshot(self):
        tok = self._token(['overseas_medical'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['overseas_medical']}, format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)
```

- [ ] **Step 2: 실패 확인**

Run: `python manage.py test inpa.customers.tests.PublicConsentMultiScopeTests -v 2`
Expected: FAIL — 응답에 `items` 없음 / `agreed` 미처리.

- [ ] **Step 3: public_consent.py 재작성** — 전체 교체

```python
"""고객 본인 동의 — 공개(비로그인) 다항목 경로 (P3c).

설계사가 만든 동의요청 링크(/c/<token>)를 고객이 본인 기기에서 연다. 토큰에 담긴
요청 scope만 고지·수집한다(개인정보 수집·이용 / 마케팅 수신 / 병력 국외이전).
  GET  /api/v1/c/<token>/  → 요청 항목 고지(필수/선택·고지문·이미 동의 여부)
  POST /api/v1/c/<token>/  → {agreed:[scope]} 동의 scope마다 ConsentLog(customer_self) 생성

★ 컴플라이언스: 정보주체 본인 동의만 기록. 필수(개인정보·국외이전) 미동의 시 412.
  마스킹 외 PII 미반환. noindex. 멱등(기존 동의 비파괴). 유료 전 법무 재검토.
"""
from django.core import signing
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.analytics.views import _NoIndexMixin, _mask_name

from .models import ConsentLog, Customer
from .tokens import read_consent_token

_DISCLAIMER = ('AI 분석 결과는 보조 자료이며, 최종 판단과 책임은 담당 설계사에게 있습니다. '
               '인파는 보험을 중개·권유하지 않습니다.')

# scope별 고지 메타 — 보수적 베타 표준문구(유료 전 법무 확정).
_SCOPE_META = {
    ConsentLog.SCOPE_PERSONAL_INFO: {
        'title': '개인정보 수집·이용 (필수)',
        'required': True,
        'purpose': '개인정보 수집·이용 동의(고객 본인)',
        'lines': [
            '수집 항목: 이름·연락처·생년월일 등 상담에 필요한 정보',
            '이용 목적: 보험 상담·계약 관리·고객 응대',
            '보유 기간: 거래 종료 후 관계 법령이 정한 기간',
        ],
        'notice': '동의를 거부하실 수 있으며, 거부 시 상담 진행이 제한될 수 있어요.',
    },
    ConsentLog.SCOPE_MARKETING: {
        'title': '마케팅·광고 정보 수신 (선택)',
        'required': False,
        'purpose': '마케팅·광고 정보 수신 동의(고객 본인)',
        'lines': [
            '이용 목적: 상품·이벤트 안내(문자·카카오톡 등)',
            '보유 기간: 동의를 철회하실 때까지',
        ],
        'notice': '거부하셔도 상담·계약에는 영향이 없어요. 언제든 수신을 거부할 수 있어요.',
    },
    ConsentLog.SCOPE_OVERSEAS_MEDICAL: {
        'title': '보험 정보 국외이전 (Claude API, 미국)',
        'required': True,
        'purpose': '고객 본인 국외이전 동의(Claude API, 미국)',
        'lines': [
            '이전 국가·수탁자: 미국 Anthropic(Claude API)',
            '이전 항목: 증권의 보험정보(담보·보험료 등)',
            '보유 기간: 처리 후 즉시 삭제',
        ],
        'notice': '증권 분석을 위한 국외이전에 한합니다.',
    },
}


def _truthy(v):
    return str(v).lower() in ('1', 'true', 'on', 'yes', 'y')


class PublicConsentView(_NoIndexMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consent_public'

    def _resolve(self, token):
        """토큰 → (customer, scopes, err). 만료=410, 위조/없음=404(존재 은폐)."""
        try:
            data = read_consent_token(token)
        except signing.SignatureExpired:
            return None, None, Response(
                {'code': 'LINK_EXPIRED',
                 'detail': '동의 링크가 만료됐어요. 담당 설계사에게 새 링크를 요청해 주세요.'},
                status=status.HTTP_410_GONE)
        except signing.BadSignature:
            return None, None, Response(
                {'code': 'LINK_INVALID', 'detail': '유효하지 않은 링크입니다.'},
                status=status.HTTP_404_NOT_FOUND)
        scopes = [s for s in data.get('scopes', []) if s in _SCOPE_META]
        customer = Customer.objects.filter(pk=data['pk']).select_related('owner__profile').first()
        if customer is None or not scopes:
            return None, None, Response(
                {'code': 'LINK_INVALID', 'detail': '유효하지 않은 링크입니다.'},
                status=status.HTTP_404_NOT_FOUND)
        return customer, scopes, None

    def _already(self, customer, scope):
        if scope == ConsentLog.SCOPE_OVERSEAS_MEDICAL:
            return customer.consent_overseas_at is not None
        return ConsentLog.objects.filter(
            customer=customer, scope=scope, revoked_at__isnull=True).exists()

    def get(self, request, token):
        customer, scopes, err = self._resolve(token)
        if err is not None:
            return err
        profile = getattr(customer.owner, 'profile', None)
        affiliation = getattr(profile, 'affiliation', '') or ''
        items = [{
            'scope': sc,
            'title': _SCOPE_META[sc]['title'],
            'required': _SCOPE_META[sc]['required'],
            'already': self._already(customer, sc),
            'lines': _SCOPE_META[sc]['lines'],
            'notice': _SCOPE_META[sc]['notice'],
        } for sc in scopes]
        all_required_done = bool(items) and all(
            it['already'] for it in items if it['required'])
        return Response({
            'customer': {'name_masked': _mask_name(customer.name)},
            'planner': {'affiliation': affiliation},
            'items': items,
            'all_required_done': all_required_done,
            'disclaimer': _DISCLAIMER,
        })

    def post(self, request, token):
        customer, scopes, err = self._resolve(token)
        if err is not None:
            return err
        agreed = request.data.get('agreed') or []
        if not isinstance(agreed, list):
            agreed = []
        agreed = [s for s in agreed if s in scopes]  # 토큰 밖 scope 무시(위조 방지)

        required = [s for s in scopes if _SCOPE_META[s]['required']]
        missing = [s for s in required if s not in agreed and not self._already(customer, s)]
        if missing:
            return Response(
                {'code': 'CONSENT_REQUIRED', 'detail': '필수 동의 항목에 동의가 필요합니다.'},
                status=status.HTTP_412_PRECONDITION_FAILED)

        ip = request.META.get('REMOTE_ADDR')
        results = []
        with transaction.atomic():
            for sc in agreed:
                if self._already(customer, sc):
                    results.append({'scope': sc, 'consented': True, 'agreed_at': None})
                    continue
                log = ConsentLog.objects.create(
                    customer=customer, scope=sc,
                    subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                    purpose=_SCOPE_META[sc]['purpose'], ip=ip)
                if (sc == ConsentLog.SCOPE_OVERSEAS_MEDICAL
                        and customer.consent_overseas_at is None):
                    customer.consent_overseas_at = log.agreed_at
                    customer.save(update_fields=['consent_overseas_at'])
                results.append({'scope': sc, 'consented': True, 'agreed_at': log.agreed_at})
        return Response({'results': results, 'all_required_done': True},
                        status=status.HTTP_201_CREATED)
```

- [ ] **Step 4: 통과 확인**

Run: `python manage.py test inpa.customers.tests.PublicConsentMultiScopeTests -v 2`
Expected: PASS (4 tests).

- [ ] **Step 5: 회귀 확인(기존 동의 테스트)**

Run: `python manage.py test inpa.customers -v 1`
Expected: PASS (기존 ConsentLog/owner 격리 테스트 포함 전부 통과).

- [ ] **Step 6: 커밋**

```bash
git add inpa_be/inpa/customers/public_consent.py inpa_be/inpa/customers/tests.py
git commit -m "feat(동의): 공개 /c 다항목 동의(개인정보·마케팅·국외이전)"
```

---

## Task 3: BE — 동의 요청 링크에 scopes

**Files:**
- Modify: `inpa_be/inpa/customers/views.py:204-212` (`ConsentRequestCreateView.post`)
- Test: `inpa_be/inpa/customers/tests.py`

**Interfaces:**
- Consumes: `make_consent_token(customer, scopes)` (Task 1).
- Produces: `POST /api/v1/customers/<id>/consent-requests/` body `{scopes?:[str]}` → 화이트리스트(`personal_info`/`marketing`/`overseas_medical`) 검증, 미지정 시 `['overseas_medical']`. 응답 기존과 동일(`token`, `consent_url`, `already_consented`).

- [ ] **Step 1: 실패 테스트 작성** — `customers/tests.py` 끝에 추가

```python
class ConsentRequestScopeTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('cr@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')

    def test_default_scope_overseas(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/consent-requests/',
                             {}, format='json')
        self.assertEqual(r.status_code, 201)
        data = read_consent_token(r.json()['token'])
        self.assertEqual(data['scopes'], ['overseas_medical'])

    def test_custom_scopes_encoded(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/consent-requests/',
                             {'scopes': ['personal_info', 'marketing']}, format='json')
        self.assertEqual(r.status_code, 201)
        data = read_consent_token(r.json()['token'])
        self.assertEqual(set(data['scopes']), {'personal_info', 'marketing'})

    def test_unknown_scope_rejected(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/consent-requests/',
                             {'scopes': ['hacker']}, format='json')
        self.assertEqual(r.status_code, 400)
```

- [ ] **Step 2: 실패 확인**

Run: `python manage.py test inpa.customers.tests.ConsentRequestScopeTests -v 2`
Expected: FAIL — scopes 무시되고 항상 overseas / 400 안 남.

- [ ] **Step 3: views.py 수정** — `customers/views.py:204` `post` 메서드 교체

```python
    # 허용 동의 scope 화이트리스트(요청 링크로 받을 수 있는 것).
    _ALLOWED_REQUEST_SCOPES = {
        ConsentLog.SCOPE_PERSONAL_INFO,
        ConsentLog.SCOPE_MARKETING,
        ConsentLog.SCOPE_OVERSEAS_MEDICAL,
    }

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
```

(파일 상단 import에 `ValidationError`는 이미 있음 — `views.py:15`.)

- [ ] **Step 4: 통과 확인**

Run: `python manage.py test inpa.customers.tests.ConsentRequestScopeTests -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: 커밋**

```bash
git add inpa_be/inpa/customers/views.py inpa_be/inpa/customers/tests.py
git commit -m "feat(동의): 동의요청 링크 scopes 파라미터(화이트리스트)"
```

---

## Task 4: BE — 시리얼라이저 동의 상태 파생

**Files:**
- Modify: `inpa_be/inpa/customers/serializers.py:63-130`
- Test: `inpa_be/inpa/customers/tests.py`

**Interfaces:**
- Produces: List 응답에 `personal_info_consent: 'agreed'|'revoked'|'none'`. Detail 응답에 추가로 `consents: {marketing:{status,subject,agreed_at}, personal_info:{...}}`.

- [ ] **Step 1: 실패 테스트 작성** — `customers/tests.py` 끝에 추가

```python
class ConsentSerializerTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('ser@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')

    def test_list_has_personal_info_consent_none(self):
        r = self.client.get('/api/v1/customers/')
        row = next(c for c in r.json()['results'] if c['id'] == self.customer.id)
        self.assertEqual(row['personal_info_consent'], 'none')

    def test_detail_consents_reflect_logs(self):
        ConsentLog.objects.create(customer=self.customer,
                                  scope=ConsentLog.SCOPE_PERSONAL_INFO,
                                  subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        ConsentLog.objects.create(customer=self.customer,
                                  scope=ConsentLog.SCOPE_MARKETING,
                                  subject=ConsentLog.SUBJECT_PLANNER_ATTESTED)
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/')
        consents = r.json()['consents']
        self.assertEqual(consents['personal_info']['status'], 'agreed')
        self.assertEqual(consents['personal_info']['subject'], 'customer_self')
        self.assertEqual(consents['marketing']['subject'], 'planner_attested')
```

- [ ] **Step 2: 실패 확인**

Run: `python manage.py test inpa.customers.tests.ConsentSerializerTests -v 2`
Expected: FAIL — `personal_info_consent`/`consents` 키 없음(KeyError).

- [ ] **Step 3: serializers.py 수정** — `_CustomerComputedMethods`(63행)에 헬퍼·메서드 추가

`get_marketing_consent`(80-85행)를 아래로 교체하고 메서드 3개 추가:

```python
    def _consent_state(self, obj, scope):
        # consent_logs는 Meta ordering=-agreed_at + ViewSet prefetch → 최신 1건.
        log = next((c for c in obj.consent_logs.all() if c.scope == scope), None)
        if log is None:
            return {'status': 'none', 'subject': None, 'agreed_at': None}
        return {
            'status': 'revoked' if log.revoked_at else 'agreed',
            'subject': log.subject,
            'agreed_at': log.agreed_at,
        }

    def get_marketing_consent(self, obj):
        return self._consent_state(obj, ConsentLog.SCOPE_MARKETING)['status']

    def get_personal_info_consent(self, obj):
        return self._consent_state(obj, ConsentLog.SCOPE_PERSONAL_INFO)['status']

    def get_consents(self, obj):
        return {
            'marketing': self._consent_state(obj, ConsentLog.SCOPE_MARKETING),
            'personal_info': self._consent_state(obj, ConsentLog.SCOPE_PERSONAL_INFO),
        }
```

- [ ] **Step 4: List 시리얼라이저에 필드 추가** — `CustomerListSerializer`(88행)

선언부에 추가:
```python
    personal_info_consent = serializers.SerializerMethodField()
```
`Meta.fields` 끝(`'marketing_consent'` 뒤)에 `'personal_info_consent'` 추가.

- [ ] **Step 5: Detail 시리얼라이저에 필드 추가** — `CustomerSerializer`(105행)

선언부에 추가:
```python
    personal_info_consent = serializers.SerializerMethodField()
    consents = serializers.SerializerMethodField()
```
`Meta.fields`의 `'marketing_consent'` 뒤에 `'personal_info_consent', 'consents'` 추가.

- [ ] **Step 6: 통과 확인**

Run: `python manage.py test inpa.customers.tests.ConsentSerializerTests -v 2`
Expected: PASS (2 tests).

- [ ] **Step 7: 커밋**

```bash
git add inpa_be/inpa/customers/serializers.py inpa_be/inpa/customers/tests.py
git commit -m "feat(동의): personal_info_consent·consents 파생 직렬화"
```

---

## Task 5: BE — 셀프진단 동의 확장

**Files:**
- Modify: `inpa_be/inpa/insurances/self_diagnosis.py:125-128`
- Test: `inpa_be/inpa/insurances/tests.py`

**Interfaces:**
- Consumes: `ConsentLog.SCOPE_PERSONAL_INFO`(Task 1).
- Produces: `/d/<refcode>` 리드 생성 시 `ConsentLog(personal_info, customer_self)` 항상 추가. body `consent_marketing` truthy면 `ConsentLog(marketing, customer_self)` 추가. 게이트(국외이전+전달) 로직 불변.

- [ ] **Step 1: 실패 테스트 작성** — `inpa_be/inpa/insurances/tests.py`

기존 셀프진단 테스트 패턴(파일 상단 import·헬퍼) 확인 후, 동의 검증 테스트 추가. ANTHROPIC 미설정 환경에서 OCR이 503 나므로, **claude_parse를 mock**해 리드 생성 경로까지 도달시킨다:

```python
from unittest.mock import patch
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.customers.models import ConsentLog, Customer
from django.utils import timezone

_OCR_STUB = {'insurances': []}  # _persist_ocr가 견딜 최소 형태(빈 보험)


def _planner_with_ref(email, ref):
    u = User.objects.create_user(email=email, password='inpaPass123!')
    u.is_active = True
    u.save(update_fields=['is_active'])
    Profile.objects.create(user=u, email_verified_at=timezone.now(), ref_code=ref)
    return u


@override_settings(ANTHROPIC_API_KEY='test-key')
class SelfDiagnosisConsentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.planner = _planner_with_ref('sd@test.com', 'REF123')
        self.anon = APIClient()

    def _pdf(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        # _extract_pdf_lines가 텍스트를 못 뽑으면 IMAGE_PDF — 그래서 추출도 mock한다.
        return SimpleUploadedFile('p.pdf', b'%PDF-1.4 test', content_type='application/pdf')

    @patch('inpa.insurances.self_diagnosis._persist_ocr')
    @patch('inpa.insurances.self_diagnosis.claude_parse', return_value=_OCR_STUB)
    @patch('inpa.insurances.self_diagnosis._extract_pdf_lines', return_value=(['line'], None))
    def test_lead_gets_personal_info_consent(self, *_):
        r = self.anon.post('/api/v1/d/REF123/', {
            'file': self._pdf(), 'consent_overseas': 'true', 'consent_share': 'true',
            'name': '셀프김', 'phone': '010-9999-0000',
        }, format='multipart')
        self.assertEqual(r.status_code, 201)
        cust = Customer.objects.get(owner=self.planner, mobile_phone_number='010-9999-0000')
        self.assertTrue(ConsentLog.objects.filter(
            customer=cust, scope=ConsentLog.SCOPE_PERSONAL_INFO,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF).exists())

    @patch('inpa.insurances.self_diagnosis._persist_ocr')
    @patch('inpa.insurances.self_diagnosis.claude_parse', return_value=_OCR_STUB)
    @patch('inpa.insurances.self_diagnosis._extract_pdf_lines', return_value=(['line'], None))
    def test_marketing_optional(self, *_):
        r = self.anon.post('/api/v1/d/REF123/', {
            'file': self._pdf(), 'consent_overseas': 'true', 'consent_share': 'true',
            'consent_marketing': 'true', 'phone': '010-8888-0000',
        }, format='multipart')
        self.assertEqual(r.status_code, 201)
        cust = Customer.objects.get(owner=self.planner, mobile_phone_number='010-8888-0000')
        self.assertTrue(ConsentLog.objects.filter(
            customer=cust, scope=ConsentLog.SCOPE_MARKETING).exists())
```

(주의: `_planner_with_ref`의 `Profile` 필드는 기존 `insurances/tests.py`의 셀프진단 셋업과 맞춰 조정. ref_code 필드명이 다르면 기존 테스트 헬퍼 재사용.)

- [ ] **Step 2: 실패 확인**

Run: `python manage.py test inpa.insurances.tests.SelfDiagnosisConsentTests -v 2`
Expected: FAIL — personal_info/marketing 로그 없음.

- [ ] **Step 3: self_diagnosis.py 수정** — `:125` 기존 overseas ConsentLog 생성 직후에 추가

```python
            ConsentLog.objects.create(
                customer=customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,  # 잠재고객 본인 동의(P3c)
                purpose='셀프진단 증권 OCR 국외이전(Claude, 미국)', ip=ip)
            # ✦ DB 자산화: 본인이 직접 제출 + 설계사 전달 동의 = 개인정보 수집·이용 동의로 명시 기록.
            ConsentLog.objects.create(
                customer=customer, scope=ConsentLog.SCOPE_PERSONAL_INFO,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                purpose='셀프진단 본인 제출·담당 설계사 전달', ip=ip)
            # ✦ 마케팅 수신(선택) — 체크 시에만.
            if _truthy(request.data.get('consent_marketing')):
                ConsentLog.objects.create(
                    customer=customer, scope=ConsentLog.SCOPE_MARKETING,
                    subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                    purpose='셀프진단 마케팅 수신 동의', ip=ip)
            _persist_ocr(customer, ocr_data)
```

- [ ] **Step 4: 통과 확인**

Run: `python manage.py test inpa.insurances.tests.SelfDiagnosisConsentTests -v 2`
Expected: PASS (2 tests). 실패 시 mock 대상 경로(import 위치)를 기존 테스트와 맞춰 조정.

- [ ] **Step 5: BE 전체 회귀 + 커밋**

Run: `python manage.py test inpa.customers inpa.insurances -v 1` → PASS.
Run: `python manage.py check` → System check OK.

```bash
git add inpa_be/inpa/insurances/self_diagnosis.py inpa_be/inpa/insurances/tests.py
git commit -m "feat(동의): 셀프진단 리드에 personal_info(필수)·marketing(선택) 동의 기록"
```

---

## Task 6: FE — api.ts 타입·함수 (추가형, build green 유지)

**Files:**
- Modify: `inpa_fe/lib/api.ts:375,406,410-422,1559-1569`

**Interfaces:**
- Produces: `CustomerListItem.personal_info_consent`, `CustomerDetail.consents?`, `ConsentState`/`ConsentSubject` 타입, `createConsentRequest(customerId, scopes?)`.

- [ ] **Step 1: 타입 추가** — `lib/api.ts:375` `MarketingConsent` 아래에 추가

```typescript
export type MarketingConsent = "agreed" | "revoked" | "none";
export type ConsentStatus = MarketingConsent;
export type ConsentSubject = "customer_self" | "planner_attested" | null;
export interface ConsentState {
  status: ConsentStatus;
  subject: ConsentSubject;
  agreed_at: string | null;
}
```

- [ ] **Step 2: CustomerListItem 필드** — `:406` `marketing_consent` 아래에 추가

```typescript
  marketing_consent: MarketingConsent;
  personal_info_consent: ConsentStatus;
```

- [ ] **Step 3: CustomerDetail 필드** — `:410` `CustomerDetail` 본문 끝에 추가

```typescript
  // 동의 상태(본인/대리 구분) — 상세에서만.
  consents?: { marketing: ConsentState; personal_info: ConsentState };
```

- [ ] **Step 4: createConsentRequest scopes** — `:1560` 함수 교체

```typescript
/** POST /api/v1/customers/<id>/consent-requests/ — 설계사가 동의 요청 링크 생성(인증).
 *  scopes 미지정 시 BE 기본=국외이전(OCR 동선 호환). */
export async function createConsentRequest(
  customerId: number,
  scopes?: string[]
): Promise<ConsentRequestResponse> {
  return request<ConsentRequestResponse>(
    "POST",
    `/customers/${customerId}/consent-requests/`,
    scopes ? { scopes } : undefined,
    true
  );
}
```

- [ ] **Step 5: 빌드(타입체크)**

Run (in `inpa_fe/`): `npm run build`
Expected: 성공(전 라우트 컴파일). 기존 `createConsentRequest(customerId)` 호출(ocr-upload.tsx:90)은 옵셔널 인자라 그대로 통과.

- [ ] **Step 6: 커밋**

```bash
git add inpa_fe/lib/api.ts
git commit -m "feat(동의): FE api 타입(personal_info/consents) + createConsentRequest scopes"
```

---

## Task 7: FE — `/c` 다항목 동의 페이지 + api 연결

**Files:**
- Modify: `inpa_fe/lib/api.ts:1571-1606` (ConsentDisclosure·submitConsent 교체)
- Modify: `inpa_fe/app/c/[token]/page.tsx` (전체 재작성)

**Interfaces:**
- Consumes: Task 2의 GET items / POST `{agreed}`.
- Produces: `ConsentItem`, 새 `ConsentDisclosure`(items), `submitConsent(token, agreed: string[])`.

- [ ] **Step 1: api.ts ConsentDisclosure·submit 교체** — `:1571-1606`

```typescript
export interface ConsentItem {
  scope: string;
  title: string;
  required: boolean;
  already: boolean;
  lines: string[];
  notice: string;
}

export interface ConsentDisclosure {
  customer: { name_masked: string };
  planner: { affiliation: string };
  items: ConsentItem[];
  all_required_done: boolean;
  disclaimer: string;
}

/** GET /api/v1/c/<token>/ — 고객 본인이 보는 동의 고지(공개, 비인증) */
export async function getConsentDisclosure(token: string): Promise<ConsentDisclosure> {
  const res = await fetch(`${API_BASE}/c/${encodeURIComponent(token)}/`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "링크를 열 수 없어요.");
  }
  return data as ConsentDisclosure;
}

/** POST /api/v1/c/<token>/ — 동의 scope 배열 제출(공개, 비인증) */
export async function submitConsent(
  token: string,
  agreed: string[]
): Promise<{ results: { scope: string; consented: boolean }[]; all_required_done: boolean }> {
  const res = await fetch(`${API_BASE}/c/${encodeURIComponent(token)}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agreed }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "동의 처리에 실패했어요.");
  }
  return data as { results: { scope: string; consented: boolean }[]; all_required_done: boolean };
}
```

- [ ] **Step 2: `/c` 페이지 재작성** — `app/c/[token]/page.tsx` 전체 교체

```tsx
"use client";

// 고객 본인 동의 (공개·비로그인) — 다항목(개인정보·마케팅·국외이전) P3c.
// ★ 명시 체크박스 + 버튼(사전체크·자동제출 금지). 필수 항목 모두 체크해야 제출 가능.

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { Card } from "@/components/ui";
import {
  getConsentDisclosure,
  submitConsent,
  ApiError,
  type ConsentDisclosure,
} from "@/lib/api";

export default function CustomerConsentPage() {
  const params = useParams();
  const token = typeof params?.token === "string" ? params.token : "";

  const [disclosure, setDisclosure] = useState<ConsentDisclosure | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    getConsentDisclosure(token)
      .then((d) => {
        if (cancelled) return;
        setDisclosure(d);
        if (d.all_required_done) setDone(true);
        // 이미 동의한 항목은 체크 표시(비활성)
        setChecked(Object.fromEntries(d.items.filter((i) => i.already).map((i) => [i.scope, true])));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadError(
          e instanceof ApiError ? e.message
            : "링크를 열 수 없어요. 담당 설계사에게 새 링크를 요청해 주세요."
        );
      });
    return () => { cancelled = true; };
  }, [token]);

  const requiredOk =
    !!disclosure &&
    disclosure.items.filter((i) => i.required).every((i) => checked[i.scope] || i.already);

  const submit = useCallback(async () => {
    if (!disclosure) return;
    setSubmitting(true);
    setSubmitError(null);
    const agreed = disclosure.items.filter((i) => checked[i.scope]).map((i) => i.scope);
    try {
      await submitConsent(token, agreed);
      setDone(true);
    } catch (e: unknown) {
      setSubmitError(
        e instanceof ApiError ? e.message : "동의 처리에 실패했어요. 잠시 후 다시 시도해 주세요."
      );
    } finally {
      setSubmitting(false);
    }
  }, [token, disclosure, checked]);

  if (loadError) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 flex items-center justify-center px-5">
        <Card className="px-6 py-8 text-center">
          <div className="text-[15px] font-bold text-ink">링크를 열 수 없어요</div>
          <p className="mt-2 text-[13px] text-ink3 leading-5">{loadError}</p>
        </Card>
      </div>
    );
  }

  if (done) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
        <header className="px-5 pt-5 pb-3 bg-accent-tint">
          <div className="text-[13px] font-bold text-brand">⌃ 인파 동의</div>
        </header>
        <main className="px-5 pb-10 flex flex-col items-center text-center">
          <div className="mt-16 text-[40px]">✅</div>
          <h1 className="mt-4 text-[20px] font-extrabold text-ink">동의가 완료됐어요</h1>
          <p className="mt-2 text-[14px] text-ink3 leading-6">
            담당 설계사가 이어서 도와드릴 거예요. 이 창은 닫으셔도 됩니다.
          </p>
        </main>
      </div>
    );
  }

  if (!disclosure) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 flex items-center justify-center">
        <div className="text-[13px] text-ink3">불러오는 중…</div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
      <header className="px-5 pt-5 pb-3 bg-accent-tint">
        <div className="text-[13px] font-bold text-brand">⌃ 인파 동의</div>
      </header>
      <main className="px-5 pb-10">
        <h1 className="pt-6 text-[22px] font-extrabold text-ink leading-8">동의 요청</h1>
        <p className="mt-2 text-[14px] text-ink3 leading-6">
          {disclosure.customer.name_masked}님, 담당 설계사
          {disclosure.planner.affiliation ? ` (${disclosure.planner.affiliation})` : ""}가
          아래 내용에 <b>본인 동의</b>를 요청했어요.
        </p>

        <div className="mt-5 space-y-3">
          {disclosure.items.map((item) => (
            <Card key={item.scope} className="px-4 py-4">
              <label className="flex items-start gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!checked[item.scope]}
                  disabled={item.already}
                  onChange={(e) =>
                    setChecked((p) => ({ ...p, [item.scope]: e.target.checked }))
                  }
                  className="mt-0.5"
                />
                <span className="text-[13px] text-ink2 leading-5">
                  <b>{item.required ? "(필수) " : "(선택) "}</b>
                  {item.title}
                  {item.already ? " — 이미 동의함" : ""}
                </span>
              </label>
              <ul className="mt-2.5 ml-7 space-y-1 text-[12px] text-ink3 leading-5">
                {item.lines.map((l, i) => (<li key={i}>{l}</li>))}
              </ul>
              <p className="mt-2 ml-7 text-[11px] text-muted leading-5">{item.notice}</p>
            </Card>
          ))}
        </div>

        <p className="mt-3 text-[12px] text-muted leading-5">{disclosure.disclaimer}</p>

        {submitError && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
            {submitError}
          </div>
        )}

        <button
          onClick={submit}
          disabled={!requiredOk || submitting}
          className="mt-4 w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 disabled:opacity-50 active:scale-[0.99] transition"
        >
          {submitting ? "처리 중…" : "동의합니다"}
        </button>
        <p className="mt-3 text-[11px] text-ink3 leading-5 text-center">
          인파는 보험을 중개·권유하지 않습니다.
        </p>
      </main>
    </div>
  );
}
```

- [ ] **Step 3: 빌드**

Run (in `inpa_fe/`): `npm run build`
Expected: 성공. `/c/[token]` 컴파일.

- [ ] **Step 4: 수동 검증(로컬)**

BE `python manage.py runserver` + FE `npm run dev` 상태에서:
1. 설계사 로그인 → 고객 상세에서 (Task 8 후) 개인정보+마케팅 링크 생성, 또는 임시로 `createConsentRequest` 호출.
2. `/c/<token>` 열기 → 개인정보(필수)·마케팅(선택) 2개 카드 표시 확인. 필수 미체크 시 버튼 비활성, 체크 시 활성 → 제출 → "동의 완료" 화면.
Expected: 통과. (Task 8 전이면 OCR 동선의 국외이전 링크로 단일 항목 표시도 확인.)

- [ ] **Step 5: 커밋**

```bash
git add inpa_fe/lib/api.ts inpa_fe/app/c/[token]/page.tsx
git commit -m "feat(동의): /c 다항목 동의 페이지(필수/선택 분리)"
```

---

## Task 8: FE — 고객 상세 동의 배지 2종 + 링크 보내기

**Files:**
- Modify: `inpa_fe/app/customer/[id]/page.tsx:462-464` 및 인접 정보 탭 영역
- 참조(재사용): `inpa_fe/lib/clipboard.ts`(`copyText`), `lib/api.ts createConsentRequest`

**Interfaces:**
- Consumes: `customer.consents`(Task 6), `createConsentRequest(id, ['personal_info','marketing'])`(Task 6), `copyText`.

- [ ] **Step 1: clipboard 헬퍼 확인**

Run: `grep -n "export" inpa_fe/lib/clipboard.ts`
Expected: `copyText`가 export됨(06.28 도입). 시그니처 확인(예: `copyText(text: string): Promise<boolean>`).

- [ ] **Step 2: 배지 라벨 확장** — `customer/[id]/page.tsx:462` `consentLabel` 교체

```tsx
  const piState = customer.consents?.personal_info;
  const mkState = customer.consents?.marketing;
  const subjectTag = (s: string | null | undefined) =>
    s === "customer_self" ? "본인 동의" : s === "planner_attested" ? "설계사 기록" : "";
  const consentLine = (label: string, state: { status: string; subject: string | null } | undefined) => {
    if (!state || state.status === "none") return `${label} 미동의`;
    if (state.status === "revoked") return `${label} 철회`;
    const tag = subjectTag(state.subject);
    return `${label} 동의${tag ? ` · ${tag}` : ""}`;
  };
```

- [ ] **Step 3: 동의 배지 + 링크 버튼 UI 추가** — 명함/정보 영역(상세 정보 카드)에 블록 추가

정보 탭의 적절한 카드(예: 상세 우측 카드 하단)에 아래 블록을 삽입. 상태·핸들러는 컴포넌트 상단 훅 영역에 추가:

```tsx
  // 동의 요청 링크 — 클립보드 복사까지만(자동발송 없음).
  const [consentBusy, setConsentBusy] = useState(false);
  const sendConsentLink = useCallback(async () => {
    setConsentBusy(true);
    try {
      const res = await createConsentRequest(customer.id, ["personal_info", "marketing"]);
      const ok = await copyText(res.consent_url);
      flash(ok ? "동의 요청 링크를 복사했어요. 고객에게 보내세요." : res.consent_url);
    } catch {
      fail("링크 생성에 실패했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setConsentBusy(false);
    }
  }, [customer.id]);
```

UI 블록(정보 탭 카드 내부):
```tsx
  <div className="mt-3 rounded-xl border border-line bg-surface px-4 py-3">
    <div className="text-[12px] font-semibold text-ink3">동의</div>
    <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
      <span className="rounded-full bg-accent-tint px-2 py-0.5 text-brand">{consentLine("개인정보", piState)}</span>
      <span className="rounded-full bg-accent-tint px-2 py-0.5 text-brand">{consentLine("마케팅", mkState)}</span>
    </div>
    <button
      onClick={sendConsentLink}
      disabled={consentBusy}
      className="mt-2.5 w-full rounded-xl border border-brand text-brand text-[13px] font-semibold py-2 disabled:opacity-60"
    >
      {consentBusy ? "링크 생성 중…" : "동의 요청 링크 복사(고객 본인용)"}
    </button>
    <p className="mt-1.5 text-[11px] text-ink3 leading-4">
      가장 안전한 건 고객 본인이 링크로 직접 동의하는 거예요. (자동발송 없음 — 복사해 전달)
    </p>
  </div>
```

(파일 상단 import에 `createConsentRequest`, `copyText` 추가. `flash`/`fail`는 이 컴포넌트에 이미 존재 — 명함 업로드에서 사용 중.)

- [ ] **Step 4: 빌드**

Run (in `inpa_fe/`): `npm run build`
Expected: 성공.

- [ ] **Step 5: 수동 검증**

고객 상세 정보 탭 → 동의 배지("개인정보 미동의" 등) 표시 + "동의 요청 링크 복사" 클릭 → 토스트 "복사했어요" → `/c` 붙여넣어 열림 확인. 고객이 동의 후 상세 새로고침 → 배지가 "개인정보 동의 · 본인 동의"로 바뀜.

- [ ] **Step 6: 커밋**

```bash
git add inpa_fe/app/customer/[id]/page.tsx
git commit -m "feat(동의): 고객상세 동의 배지(본인/설계사 구분) + 요청 링크 복사"
```

---

## Task 9: FE — 등록 모달 동의 체크(설계사 기록)

**Files:**
- Modify: `inpa_fe/components/customer-create-modal.tsx`

**Interfaces:**
- Consumes: `createConsentLog(customerId, {scope})`(기존, `lib/api.ts:1537`).

- [ ] **Step 1: 상태·import 추가** — `customer-create-modal.tsx:6-7,24`

import에 `createConsentLog` 추가:
```tsx
import { createCustomer, createConsentLog, LEAD_SOURCES, ApiError, type CustomerDetail } from "@/lib/api";
```
상태 추가(`:24` leadSource 아래):
```tsx
  const [piConsent, setPiConsent] = useState(false);
  const [mkConsent, setMkConsent] = useState(false);
```

- [ ] **Step 2: 생성 후 동의 기록** — `submit`(`:36-46`)에서 `onCreated(c)` 직전에 추가

```tsx
      const c = await createCustomer({ /* ...기존 동일... */ });
      // 설계사 기록(planner_attested) — 체크된 동의를 감사 로그로 남김(법적 강건성은 본인 링크).
      const scopes: string[] = [];
      if (piConsent) scopes.push("personal_info");
      if (mkConsent) scopes.push("marketing");
      await Promise.allSettled(scopes.map((scope) => createConsentLog(c.id, { scope })));
      onCreated(c);
```

`useCallback` 의존성 배열(`:54`)에 `piConsent, mkConsent` 추가.

- [ ] **Step 3: 체크박스 UI** — 유입 경로 select(`:158`) 아래에 추가

```tsx
          {/* 동의(설계사 기록) — 분리 체크. 본인 동의 링크는 등록 후 고객상세에서. */}
          <div className="flex flex-col gap-2 rounded-xl border border-line bg-surface px-3.5 py-3">
            <span className="text-[12px] font-semibold text-ink3">동의 받음 기록 (선택)</span>
            <label className="flex items-start gap-2 cursor-pointer">
              <input type="checkbox" checked={piConsent} onChange={(e) => setPiConsent(e.target.checked)} className="mt-0.5" />
              <span className="text-[12px] text-ink2 leading-4">개인정보 수집·이용 동의를 받았어요</span>
            </label>
            <label className="flex items-start gap-2 cursor-pointer">
              <input type="checkbox" checked={mkConsent} onChange={(e) => setMkConsent(e.target.checked)} className="mt-0.5" />
              <span className="text-[12px] text-ink2 leading-4">마케팅 수신 동의를 받았어요</span>
            </label>
            <p className="text-[11px] text-ink3 leading-4">
              여기 체크는 <b>설계사 기록(메모)</b>이에요. 법적으로 가장 안전한 건 고객 본인이 링크로 직접 동의하는 것 — 등록 후 ‘동의 요청 링크 복사’를 쓰세요.
            </p>
          </div>
```

- [ ] **Step 4: 빌드 + 검증**

Run (in `inpa_fe/`): `npm run build` → 성공.
수동: 고객 등록 시 체크 → 등록 → 상세에서 "개인정보 동의 · 설계사 기록" 배지 확인.

- [ ] **Step 5: 커밋**

```bash
git add inpa_fe/components/customer-create-modal.tsx
git commit -m "feat(동의): 등록 모달 동의 기록 체크(설계사 기록)"
```

---

## Task 10: FE — 셀프진단 `/d` 마케팅 수신(선택)

**Files:**
- Modify: `inpa_fe/app/d/[ref]/page.tsx:24,42-47,121-134`

**Interfaces:**
- Consumes: Task 5의 `consent_marketing` form 필드.

- [ ] **Step 1: 상태 추가** — `:24` consentShare 아래

```tsx
  const [consentMarketing, setConsentMarketing] = useState(false);
```

- [ ] **Step 2: FormData에 전달** — `submit`(`:45`) consent_share 다음 줄

```tsx
    fd.append("consent_share", "true");
    if (consentMarketing) fd.append("consent_marketing", "true");
```

`useCallback` 의존성 배열(`:55`)에 `consentMarketing` 추가.

- [ ] **Step 3: 선택 체크박스 UI** — 필수 동의 Card(`:134`) 닫기 직전, consentShare label 다음에 추가

```tsx
          <label className="flex items-start gap-2.5 cursor-pointer">
            <input type="checkbox" checked={consentMarketing} onChange={(e) => setConsentMarketing(e.target.checked)} className="mt-0.5" />
            <span className="text-[13px] text-ink2 leading-5">
              <b>(선택)</b> 보장 관련 유용한 정보·이벤트 안내를 받는 데 동의합니다. (거부해도 진단은 진행돼요)
            </span>
          </label>
```

- [ ] **Step 4: 빌드 + 검증**

Run (in `inpa_fe/`): `npm run build` → 성공.
수동: `/d/<ref>` → 필수 2개 + 선택 1개 표시. 선택은 미체크여도 "무료 진단 받기" 활성(필수 2개만 충족). 체크 후 진단 → 리드에 마케팅 로그 생성.

- [ ] **Step 5: 최종 통합 검증 + 커밋**

Run (in `inpa_be/`): `python manage.py test inpa.customers inpa.insurances` → PASS.
Run (in `inpa_fe/`): `npm run build` → 성공.

```bash
git add inpa_fe/app/d/[ref]/page.tsx
git commit -m "feat(동의): 셀프진단 마케팅 수신 선택 체크"
```

---

## Self-Review

**1. Spec coverage**
- BE-1 scope → Task 1 ✓ / BE-2 token → Task 1 ✓ / BE-3 요청 scopes → Task 3 ✓ / BE-4 공개 다항목 → Task 2 ✓ / BE-5 시리얼라이저 → Task 4 ✓ / BE-6 셀프진단 → Task 5 ✓
- FE-1 api → Task 6·7 ✓ / FE-2 등록 모달 → Task 9 ✓ / FE-3 상세 → Task 8 ✓ / FE-4 /c → Task 7 ✓ / FE-5 /d → Task 10 ✓
- 컴플라이언스 가드(분리 동의·대리 강등·자동발송 없음) → Task 2/9 카피·Task 8 복사전용 ✓
- 테스트 전략 → Task 1~5 각 테스트 ✓

**2. Placeholder scan** — TBD/TODO 없음. 모든 step에 실제 코드·명령·기대출력. (Task 5는 mock 경로 조정 안내가 있으나 실제 코드 제공 + 조정 사유 명시.)

**3. Type consistency**
- `make_consent_token(customer, scopes=None)` / `read_consent_token → {'pk','scopes'}`: Task 1 정의 = Task 2·3 소비 일치 ✓
- `ConsentLog.SCOPE_PERSONAL_INFO='personal_info'`: Task 1 정의 = Task 2·4·5 사용 일치 ✓
- POST `/c` 계약 `{agreed:[...]}` / 응답 `{results,all_required_done}`: Task 2 정의 = Task 7 `submitConsent` 일치 ✓
- GET items `{scope,title,required,already,lines,notice}`: Task 2 = Task 6 `ConsentItem` = Task 7 렌더 일치 ✓
- `consents:{marketing,personal_info}` + `ConsentState{status,subject,agreed_at}`: Task 4 = Task 6 = Task 8 사용 일치 ✓
- `createConsentRequest(customerId, scopes?)`: Task 6 = Task 8 호출 / ocr-upload 기존 호출 호환 ✓

이슈 없음.

---

## Execution Handoff

플랜 완료 → `docs/superpowers/plans/2026-06-28-marketing-consent-collection.md`.
