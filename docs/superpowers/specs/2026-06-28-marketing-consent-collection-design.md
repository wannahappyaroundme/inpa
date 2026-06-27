# 설계서 — 마케팅·개인정보 동의 수집 (DB 자산화)

- **작성일**: 2026-06-28
- **스트림**: customers / 동의(ConsentLog)
- **범위**: Phase 1 + Phase 2 동시 구현 (PM 승인 2026-06-28)
- **상태**: 설계 확정 → 구현 플랜 대기
- **관련 정본**: `docs/dev/02`(데이터모델·가시성 §0/§4) · `docs/dev/12`(고객/OCR) · `docs/dev/14·16`(컴플라이언스)

---

## 1. 목표 (한 줄)

고객 DB를 **합법적으로 보유·활용할 근거(동의)** 를 받아 감사 로그로 쌓는다.
개인정보 **수집·이용 동의**(필수, DB 보유 근거)와 **마케팅 수신 동의**(선택)를 **분리**해서 받는다.

## 2. 배경 — 기존 자산을 재사용한다 (새 메커니즘 금지)

코드에 이미 "동의" 패턴이 완성형으로 있다. 이 위에 **동의 종류만 2개 더 얹는다.**

| 기존 자산 | 위치 | 재사용 방식 |
|---|---|---|
| `ConsentLog` (append-only 감사로그) | `customers/models.py:261` | scope에 `personal_info` 추가 (marketing은 이미 있음 `:275`) |
| `subject` 구분 (본인/대리) | `customers/models.py:285` | `customer_self`(법적 유효) vs `planner_attested`(감사용) 그대로 |
| `/c/<token>` 공개 동의 페이지 | `customers/public_consent.py` + `app/c/[token]/page.tsx` | "국외이전 전용" → **다목적 동의 페이지로 일반화** |
| 동의 요청 토큰(stateless 서명) | `customers/tokens.py` | 토큰 payload에 요청 scope 목록 인코딩(하위호환) |
| 동의 요청 링크 생성 | `ConsentRequestCreateView` `customers/views.py:182` | `scopes` 파라미터 추가 |
| `marketing_consent` 파생 배지 | `serializers.py:80` `get_marketing_consent` | 같은 패턴으로 `personal_info_consent` 추가 |
| "동의 요청 링크 만들기" 모달(클립보드/카톡) | `components/ocr-upload.tsx:248` `ConsentModal` | 전달 패턴 재사용(자동발송 X) |
| 셀프진단 인바운드 | `insurances/self_diagnosis.py` + `app/d/[ref]/page.tsx` | 마케팅 수신 선택 체크 + personal_info 로그 추가 |

**핵심 발견**: `Customer`에는 새 필드가 **필요 없다.** `consent_overseas_at`은 medical detect API의 하드 게이트라 스냅샷 필드가 있지만, personal_info·marketing은 API 호출을 막는 게이트가 아니므로 **`ConsentLog`에서 파생(derive)** 한다 (marketing_consent 배지가 이미 그렇게 동작 중).

## 3. 확정된 결정 (브레인스토밍 2026-06-28)

1. **동의 범위**: 개인정보 수집·이용(필수) + 마케팅 수신(선택) **둘 다, 분리 수집.**
2. **수집 지점**: 공개 동의링크 `/c` + 셀프진단 `/d` + 고객 등록 모달 — **세 곳 모두.**
3. **범위**: Phase 1 + Phase 2 **동시.**
4. **정직성**: `planner_attested`(설계사 기록)는 감사용 메모일 뿐 "본인 동의"로 위장 불가. UI가 본인/설계사를 **구분 표기.**

## 4. 상세 설계

### 4.1 백엔드

#### (BE-1) ConsentLog scope 추가 — `customers/models.py:273`
```python
SCOPE_OVERSEAS_MEDICAL = 'overseas_medical'
SCOPE_MEDICAL_SENSITIVE = 'medical_sensitive'
SCOPE_MARKETING = 'marketing'
SCOPE_PERSONAL_INFO = 'personal_info'          # ✦ 신규 — 개인정보 수집·이용
SCOPE_CHOICES = (
    ...,
    (SCOPE_PERSONAL_INFO, '개인정보 수집·이용'),
)
```
- 마이그레이션: choices 변경은 DB 스키마 무변경(상태 전용 마이그레이션 1개 생성됨 — 무해). `makemigrations customers` 1회.

#### (BE-2) 토큰 다목적화 — `customers/tokens.py`
```python
def make_consent_token(customer, scopes=None):
    payload = {'pk': customer.pk, 'scopes': scopes or [ConsentLog.SCOPE_OVERSEAS_MEDICAL]}
    return signing.dumps(payload, salt=CONSENT_SALT)

def read_consent_token(token):
    # max_age = settings.CONSENT_TOKEN_TTL_HOURS * 3600 (기존 로직 그대로)
    data = signing.loads(token, salt=CONSENT_SALT, max_age=settings.CONSENT_TOKEN_TTL_HOURS * 3600)
    if isinstance(data, int):                 # ★ 하위호환: 구 토큰 = pk(int) = 국외이전
        return {'pk': data, 'scopes': [ConsentLog.SCOPE_OVERSEAS_MEDICAL]}
    return data
```
- **하위호환 필수**: 이미 발급된 구 토큰(int pk)은 국외이전으로 해석. OCR 동선(`make_consent_token(customer)` scope 미지정)은 기본값 = 국외이전이라 **동작 무변경.**

#### (BE-3) 동의 요청 링크 생성에 scopes — `ConsentRequestCreateView` `customers/views.py:204`
- POST body에 `scopes: string[]` 선택 수용. 미지정 시 `['overseas_medical']`(OCR 동선 호환).
- 허용 scope 화이트리스트 검증: `{personal_info, marketing, overseas_medical}`. 그 외 400.
- `make_consent_token(customer, scopes)` 호출. 응답 `consent_url` 동일 형식.
- 응답에 요청된 scope별 현재 동의 상태(`already`) 포함(선택 — UI가 "이미 받음" 표시).

#### (BE-4) 공개 동의 페이지 다목적화 — `customers/public_consent.py`
**고지문 상수**(scope별, 보수적 베타 표준 + 법무 재검토 플래그):
```python
_SCOPE_META = {
  'personal_info': {'title': '개인정보 수집·이용 (필수)', 'required': True,
                    'items': '이름·연락처·생년월일 등', 'purpose': '보험 상담·계약 관리',
                    'retain': '거래 종료 후 관계법령 기간', 'notice': '동의를 거부할 권리가 있으며, 거부 시 상담 진행이 제한될 수 있습니다.'},
  'marketing':     {'title': '마케팅·광고 정보 수신 (선택)', 'required': False,
                    'purpose': '상품·이벤트 안내(문자·카톡 등)', 'notice': '거부하셔도 상담·계약에는 영향이 없습니다.'},
  'overseas_medical': {'title': '보험 정보 국외이전 (Claude API, 미국)', 'required': True,
                       # 기존 _SCOPE_TEXT/_PURPOSE_TEXT/_DISCLAIMER 상수 재사용(문구 무변경)
                       'reuse': '_SCOPE_TEXT / _PURPOSE_TEXT / _DISCLAIMER'},
}
```
- `GET /api/v1/c/<token>/`: 토큰의 scopes를 읽어 **요청된 항목만** 메타(제목·고지문·필수여부·이미 동의여부) 배열로 반환 + 마스킹 이름·설계사 소속.
- `POST /api/v1/c/<token>/`: body는 scope별 boolean(`personal_info`, `marketing`, `consent_overseas` 등).
  - 토큰에 포함된 scope만 처리(토큰 밖 scope 무시 = 위조 방지).
  - **필수 scope 미동의 → 412**(기존 국외이전 412 패턴 계승).
  - 동의된 scope마다 `ConsentLog.objects.create(scope, subject=customer_self, ip)`.
  - `overseas_medical`이면 기존대로 `consent_overseas_at` 스냅샷도 세팅(멱등).
  - 응답: scope별 `{consented: bool, agreed_at}`.

#### (BE-5) 시리얼라이저 파생 — `serializers.py`
- 공용 헬퍼 `_consent_state(obj, scope)` → `{status: 'agreed'|'revoked'|'none', subject: 'customer_self'|'planner_attested'|None, agreed_at}` (consent_logs 캐시 순회, 최신 1건).
- `get_marketing_consent`는 `_consent_state(...).status`로 리팩터(기존 문자열 계약 유지).
- **List 시리얼라이저**: `marketing_consent`(유지) + `personal_info_consent`(신규, status 문자열) 필드.
- **Detail 시리얼라이저**: 추가로 `consents` 객체 `{marketing, personal_info}`(각 status+subject+agreed_at) — 본인/설계사 구분 배지용.
- `get_queryset`은 이미 `consent_logs` prefetch 중(`views.py:53`) → N+1 없음.

#### (BE-6) 셀프진단 동의 확장 — `insurances/self_diagnosis.py`
- 리드 생성 트랜잭션(`:111`)에서:
  - **항상** `ConsentLog(personal_info, customer_self)` 추가 — 잠재고객이 본인 정보를 직접 제출 + 담당 설계사 전달 동의(`is_agree_term=True`)는 곧 수집·이용 동의이므로 감사로그로 명시.
  - body `consent_marketing` truthy면 `ConsentLog(marketing, customer_self)` 추가(선택).
- `/d` 게이트(국외이전+전달) 로직은 **불변** — 마케팅은 선택이라 412 조건에 넣지 않음.

### 4.2 프론트엔드

#### (FE-1) lib/api.ts
- 타입: `personal_info_consent: ConsentStatus` + `consents?: {marketing, personal_info}` (detail).
- `createConsentRequest(customerId, scopes?)` — scopes 파라미터 추가(미지정 시 BE 기본=국외이전).
- 공개 동의 GET/POST 헬퍼 다항목화(`getPublicConsent` → items 배열, `submitPublicConsent` → scope별 boolean).
- 셀프진단 submit에 `consent_marketing` 선택 필드.

#### (FE-2) 고객 등록 모달 — `components/customer-create-modal.tsx`
- 선택 체크박스 2개: "개인정보 수집·이용 동의 받음" / "마케팅 수신 동의 받음".
- 안내문: "여기 체크는 **설계사 기록(메모)** 이에요. 법적으로 가장 안전한 건 고객 본인이 링크로 직접 동의하는 것 — 등록 후 '동의 요청 링크 보내기'를 쓰세요."
- 동작: 고객 생성(POST) → 반환 id로 체크된 scope마다 `POST /customers/<id>/consents/`(=planner_attested).

#### (FE-3) 고객 상세 — `app/customer/[id]/page.tsx`
- 동의 배지 영역(현재 marketing 배지 `:462`) 확장: 개인정보 수집·이용 + 마케팅 각각 status + **본인/설계사 구분 표기**(예: "본인 동의" / "설계사 기록").
- **"동의 요청 링크 보내기"** 버튼 → `createConsentRequest(id, ['personal_info','marketing'])` → 링크 모달(클립보드 복사/카톡 열기). `ConsentModal`(ocr-upload.tsx) 패턴 재사용 또는 공용화.

#### (FE-4) 공개 동의 페이지 — `app/c/[token]/page.tsx`
- GET 응답 items 배열을 렌더: 필수(개인정보)·선택(마케팅) 분리, 항목별 고지문 펼침.
- 제출: 토큰이 단일(국외이전)이면 기존 UI와 동일하게 보이고, 다항목이면 체크박스 묶음.
- 필수 미체크 시 제출 비활성.

#### (FE-5) 셀프진단 페이지 — `app/d/[ref]/page.tsx`
- 기존 2개 필수 동의 아래 **선택** 체크박스 1개: "마케팅·광고 수신(선택)". 미체크여도 진행 가능.

## 5. 데이터 모델 변경 요약

| 변경 | 종류 | 마이그레이션 |
|---|---|---|
| `ConsentLog.SCOPE_PERSONAL_INFO` choice 추가 | 상태 전용 | 1개(스키마 무변경) |
| Customer 필드 | **없음** (파생) | 없음 |

## 6. 컴플라이언스 가드 (우회 0)

- **분리 동의**: 필수(개인정보)·선택(마케팅) 별도 체크 — 묶음 강제 금지(개보법).
- **대리기록 강등**: `planner_attested`는 read_only로 서버 강제(`serializers.py:51`·`views.py:151`), "본인 동의"로 위조 불가. UI 구분 표기.
- **항목별 법정 고지**: 수집 항목·이용 목적·보유 기간·거부 권리. 베타는 보수적 표준문구 + **"유료 정식출시 전 법무 재검토"** 주석 고정. 기존 `app/legal/privacy` 4조·`data-policy`와 정합.
- **자동발송 없음**: 링크는 클립보드/카톡 열기까지(정직성 레드라인).
- **게이트**: 동의 '수집'은 보수적 안전 동작이라 기능 게이트로 닫지 않음. 마케팅 '발송' 연계(아래 범위 외)는 게이트·`marketing_consent=agreed` 확인 대상.

## 7. 범위 밖 (YAGNI — 이번 스펙 제외)

- 마케팅 **발송** 기능과 `/scripts` 문자광고 가드(광고·무료수신거부·야간금지)에 `marketing_consent=agreed` **차단 연결** → 다음 라운드.
- 동의 **철회**를 고객이 공개 링크에서 직접 하는 UI(현재 철회는 설계사측 revoke 액션 가정) → 다음 라운드.
- 명함 OCR 자동등록·포인트 보상 → 별개(보류 결정).

## 8. 테스트 전략 (happy path + 게이트)

- `customers/tests.py`: ① `/c` 다목적 토큰 — personal_info+marketing 동의 POST → ConsentLog 2건(customer_self) + 배지 agreed. ② 필수(personal_info) 미동의 → 412. ③ 구 토큰(int) 하위호환 → 국외이전으로 해석. ④ 설계사 `/consents/` POST → planner_attested(본인 아님) 검증.
- `insurances/tests.py`(self_diagnosis): 리드 생성 시 personal_info 로그 자동 + consent_marketing 체크 시 marketing 로그.
- 시리얼라이저: `personal_info_consent`/`consents` 파생 정확성(none/agreed/revoked, subject).
- BE 게이트: 마케팅 미동의여도 리드/등록 진행되는지(선택 동의는 차단 아님).

## 9. 빌드 순서 (Phase 1+2 동시, 의존성 순)

1. BE-1(scope) → BE-2(token) → BE-3(요청 생성) → BE-4(/c) → BE-5(시리얼라이저) → BE-6(셀프진단) → BE 테스트.
2. FE-1(api.ts) → FE-4(/c) + FE-3(상세) [Phase 1 동선 완성] → FE-2(등록 모달) + FE-5(/d) [Phase 2].
3. `python manage.py test inpa.customers inpa.insurances` + `npm run build` 검증.

## 10. 법무 플래그 (열린 항목 — 출시 전)

- 표준 고지문(수집 항목/보유 기간) 문구는 **베타 임시값** — 유료 전 법무 확정.
- 셀프진단 리드의 personal_info 동의를 `is_agree_term`(전달 동의)로 갈음하는 해석의 적법성 — 법무 확인.
- 이상 모두 CLAUDE.md "개발 착수 전 게이트"의 컴플라이언스 보수 운영 원칙 하에서 진행.
