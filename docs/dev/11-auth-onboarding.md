# 인증 & 온보딩 (Auth & Onboarding)

> 인파(Inpa) 개발 정본 · `docs/dev/11-auth-onboarding.md`
> 카카오 OAuth(foliio `KakaoLoginView` 재사용) · 설계사 가입/위촉확인 · 권한·세션 · 멀티테넌시 · 콜드스타트 온보딩
> 상위 정본: `dev/02`(모델·API) · `dev/07`(API 계약) · `dev/09`(컴플라이언스). 본 문서는 그 위에 인증/온보딩 레이어를 얹는다.

---

## 0. 한눈에 — 이 문서가 잠그는 것

| # | 영역 | 핵심 결정 | 상태 |
|---|---|---|---|
| 1 | 카카오 OAuth | foliio v2 redirect 파이프라인 통째 재사용(♻), 인파 전용 키 신규 발급 | 코드 ♻ / 콘솔작업 대기 |
| 2 | 설계사 가입 | 카카오 1-tap → 약관 동의 → 위촉확인(자기신고) → 대시보드 | 신규 설계 |
| 3 | 권한·세션 | DRF Token 재사용, `is_dormant` 미들웨어 게이트 금지(레드라인) | ♻ |
| 4 | 멀티테넌시 | row-level 격리, 단일 강제점 `OwnedQuerySetMixin` + `IsOwner` | ★Sprint0 게이트 |
| 5 | 동의 분리 | 설계사 약관(온보딩) ≠ 고객 국외이전 동의(detect 412 게이트) | ★컴플라이언스 |
| 6 | 콜드스타트 | 첫 고객 등록 유도 = 활성화 북극선, 빈 상태 전부 단일 CTA | 신규 설계 |

**레드라인 3개 (사후비용 최대 — 절대 어기지 말 것)**
1. **멀티테넌시 단일 강제점** — `request.user` 없는 데이터 접근은 코드리뷰 reject. 화이트리스트 2개(admin / 공유뷰 share_token) 외 예외 없음.
2. **동의 2종 분리** — 카카오 가입 = 설계사 본인 약관. `consent_overseas_at`은 *고객별*. 온보딩 UX가 이 둘을 섞으면 안 됨.
3. **`is_dormant` 게이트 미들웨어 금지** — foliio 함정. 재로그인 시 `KakaoLoginView`가 자동복구. 미들웨어/permission에서 휴면 차단하면 영구 락아웃.

---

## 1. 인증 파이프라인 — 카카오 OAuth (foliio ♻)

### 1.1 재사용 범위

foliio 카카오 OAuth v2 redirect 파이프라인을 **통째로 vendoring**한다. 핵심 함정 3개는 foliio에서 이미 정본화 — 인파는 *키만 새로 발급*하고 로직은 무변경.

| 항목 | foliio 정본 | 인파 |
|---|---|---|
| OAuth 시작 | JS SDK 우회, REST API 키로 `window.location.href` 직접 구성 (KOE006 회피) | ♻ 무변경 |
| JS SDK 용도 | 공유/메시지 전용 (`Kakao.Share`) | ♻ 무변경 |
| 1회용 code 이중호출 가드 | `sessionStorage(kakao_code_processed_<code>)` | ♻ 무변경 |
| BE 토큰 교환 | REST API 키로 code→access_token, `kapi.kakao.com/v2/user/me` | ♻ 무변경 |
| 클라이언트 시크릿 | 베타 비활성 (활성 시 KOE010 위험) | ♻ 비활성 유지 |
| 휴면 자동복구 | `KakaoLoginView`가 `is_dormant=False` 클리어 | ♻ 무변경 |

### 1.2 인증 흐름 (ASCII)

```
[설계사]                  [inpa_fe]                    [kauth.kakao.com]        [inpa_be]
   │  로그인 탭            │                                │                     │
   │─────────────────────>│                                │                     │
   │                      │ window.location.href =         │                     │
   │                      │  authorize?client_id=REST&...  │                     │
   │                      │───────────────────────────────>│                     │
   │  카카오 동의화면      │                                │                     │
   │<──────────────────────────────────────────────────────│                     │
   │  동의                 │                                │                     │
   │───────────────────────────────────────────────────────>│ redirect_uri?code= │
   │                      │  /auth/kakao/callback?code=     │                     │
   │                      │<───────────────────────────────│                     │
   │                      │ sessionStorage 가드 체크         │                     │
   │                      │ POST /rest-auth/kakao_login/ {code}                   │
   │                      │──────────────────────────────────────────────────────>│
   │                      │                                │  code→access_token   │
   │                      │                                │  user/me 조회         │
   │                      │                                │  User get_or_create  │
   │                      │                                │  Profile 보강(동의 race 가드)
   │                      │                                │  is_dormant 자동복구  │
   │                      │  { token, is_new, onboarding_required }               │
   │                      │<──────────────────────────────────────────────────────│
   │                      │ is_new? → /onboarding : /home                         │
```

### 1.3 인파 전용 카카오 콘솔 작업 (운영 — 대표 승인 필요)

⚠️ **코드가 아니라 카카오 콘솔 운영작업.** foliio 앱과 키를 **분리 발급**한다(같은 키 공유 시 Redirect URI 충돌 + 통계 오염).

```
신규 카카오 앱 발급 체크리스트 (담당: ___ / 승인: 대표 / 기한: ___)
□ 카카오 디벨로퍼스 신규 앱 생성 (앱 이름: 인파 / Inpa)
□ REST API 키 발급 → inpa_be .env: KAKAO_REST_API_KEY
□ JavaScript 키 발급 → inpa_fe environment.prod.ts: kakaoJsKey (Kakao.init / Share 전용)
□ Redirect URI 등록: https://www.inpa.<도메인>/auth/kakao/callback (단일 canonical www)
   ※ REST API 키 편집 모달에 등록 (JS 키 아님 — foliio KOE006 교훈)
□ 클라이언트 시크릿: 비활성 유지 (베타. 활성 시 BE도 KAKAO_CLIENT_SECRET 필수 → KOE010 위험)
□ 동의항목: 닉네임 + 카카오계정(이메일) — 최소수집 원칙
□ 비즈앱 전환 여부 확인 (이메일 필수동의 받으려면 비즈앱 필요할 수 있음 — 추정)
```

> **(추정)** 인파 도메인 미확정. `inpa.kr` / `inpa.co.kr` 등 확정 후 Redirect URI canonical 1개로 고정. foliio 교훈상 www/non-www 혼용은 OAuth 깨짐의 단골 원인 — 발급 시점에 1개로 못박을 것.

---

## 2. 설계사 가입 & 위촉확인

### 2.1 가입 = "카카오 1-tap + 약관 + 위촉 자기신고"

인파의 가입자는 **보험설계사(원수사·GA 위촉직 개인사업자)**다. 이메일/비밀번호 없음 — 카카오 OAuth만. 가입은 3단계지만 체감은 "카카오 한 번 + 약관 체크 + 위촉정보 입력".

```
카카오 동의(1-tap)
   └→ [BE] User/Profile 생성 + 베타 멤버십 자동부여(♻ foliio 패턴)
        └→ is_new=true → 온보딩 진입
             ├ STEP 1  설계사 약관 동의 (필수: 서비스/개인정보, 선택: 마케팅)
             ├ STEP 2  위촉확인 — 자기신고 (소속/자격/경력)
             └ STEP 3  첫 고객 등록 유도 (콜드스타트 — §6)
```

### 2.2 위촉확인 — "자기신고" 모델 (베타 정책)

**핵심 결정: 베타는 위촉 자격을 자동검증하지 않는다. 자기신고(self-attestation)로 받는다.** 보험설계사 자격 API(생·손보협회 e-클린보험 등) 연동은 외부 인증·비용·법무 검토가 필요 — 베타 범위 밖. 대신 자기신고 + 체크박스 면책으로 컴플라이언스 라인을 지킨다.

| 필드 | 타입 | 필수 | 용도 |
|---|---|---|---|
| `affiliation` | str | ✓ | 소속(원수사/GA명) — 자유입력 (추정: 베타는 enum 없이 자유텍스트) |
| `agent_type` | enum(life/nonlife/both) | ✓ | 생명/손해/교차 — §97 비교안내 게이트 입력 |
| `license_self_declared` | bool | ✓ | "본인은 유효한 보험모집 자격을 보유하고 있음" 자기신고 체크 |
| `career_years` | int | – | 경력연차 (성과카드/온보딩 카피 개인화) |
| `license_no` | str | – | 자격번호 (선택 입력 — 추후 검증 hook 대비 컬럼만 확보) |

**왜 자기신고로 충분한가 (컴플라이언스 입장)**: 인파는 보험을 중개·권유하지 않는다(`dev/09`). 판단·권유 주체는 라이선스 있는 설계사 본인. 인파는 *도구*다. 따라서 인파가 자격을 **검증할 의무**보다 "자격 보유자만 권유 책임을 진다"는 **면책 고지**가 본질. 단 §97 비교안내서/발굴 기능은 위촉 자격이 전제이므로, `license_self_declared=false`면 **해당 기능 진입 차단**(분석/공유는 허용).

> **(추정)** 정식 출시 시 자격 API 연동 여부는 별도 의사결정. 베타는 자기신고 + `license_no` 컬럼만 미리 확보해 마이그레이션 비용 회피.

### 2.3 `Profile` 확장 (foliio ♻ + 인파 net-new)

```
Profile (OneToOne User) — foliio 재사용 + 인파 추가
  ── foliio ♻ ──────────────────────────────────
  is_admin                bool      # 관리자 게이트
  is_dormant              bool      # 휴면 (미들웨어 게이트 금지!)
  dormant_at              datetime
  dormancy_warning_sent_at datetime
  will_delete_at          datetime
  ── 인파 net-new (위촉·온보딩) ──────────────────
  affiliation             str(null)
  agent_type              enum(1=life/2=nonlife/3=both, null)
  license_self_declared   bool(default=false)
  license_no              str(null)        # 검증 hook 대비 컬럼만
  career_years            int(null)
  onboarding_completed_at datetime(null)   # null=온보딩 미완 → 재진입
  ref_code                str(unique, null) # 북극성 귀속 — §5 연계 (Day1 컬럼만)
```

> **갭(blocking)**: `ref_code` 발급 체계(생성·유일성·위변조 방지)는 본 문서 §5 + BE/북극성 정본의 미설계 항목. Day1 스키마(`ref_code` 컬럼 + `unique`)만 박고 발급 로직은 Sprint0 게이트. 설계사 가입 시점이 `ref_code` 발급의 자연스러운 트리거 — 가입 플로우에 hook 자리만 비워둔다.

---

## 3. 권한 · 세션

### 3.1 세션 모델 (foliio ♻)

- **DRF Token** 그대로 재사용. 카카오 로그인 성공 → `{ token }` 발급 → FE가 `Authorization: Token <…>` 헤더로 모든 API 인증.
- **만료/회수 정책 (추정)**: foliio는 토큰 무기한. 인파도 베타는 무기한 유지(설계사 도구 — 매일 진입, 잦은 재로그인은 마찰). 정식 출시 시 만료/리프레시 정책 재검토.
- **로그아웃**: FE 토큰 폐기 + (추정) BE Token 삭제 엔드포인트. foliio 패턴 확인 후 ♻.

### 3.2 권한 레이어 (3단)

```
Layer 1  인증 여부      IsAuthenticated (DRF default, base.py)
Layer 2  소유권         IsOwner (request.user == obj.owner)  ★멀티테넌시 핵심
Layer 3  기능 게이트     license_self_declared / 멤버십 tier / consent
```

| 화이트리스트(인증 우회) | permission | 근거 |
|---|---|---|
| 카카오 로그인 | `AllowAny` | OAuth 진입점 |
| 멤버십 목록 | `AllowAny` | 가격표 공개 |
| 공유뷰(분석/비교) | `AllowAny` + `share_token` | 고객 열람 — §4 화이트리스트 ② |

### 3.3 휴면/탈퇴 (foliio ♻ — 미들웨어 게이트 금지)

- 휴면 시스템(`process_dormancy`: +150d 경고 / +180d 휴면 / dormant+180d 삭제) 통째 ♻.
- **레드라인 재확인**: `is_dormant`를 미들웨어/permission에서 차단하지 말 것. 재로그인 시 `KakaoLoginView`가 자동복구. admin(`is_admin=True`)은 휴면 처리 제외.
- 탈퇴: foliio `withdraw/`(익명화, no-undo) ♻. **인파 주의**: 탈퇴 설계사의 `Customer.user`가 `SET_NULL`되며 *소유자 없는 유령행* 발생 → §4.3 admin 재배정 필터 필수.

---

## 4. 멀티테넌시 — 설계사별 데이터 격리 (★ 가장 중요)

### 4.1 테넌트 = 설계사 1인 (org 멀티테넌시 아님)

foliio는 단일테넌트 가정(`Customer.user` FK)이고 인파도 **테넌트 = 설계사 1인**이다. GA 지점/조직 공유는 **범위 밖**. 격리는 **row-level: 모든 쿼리에 `filter(owner=request.user)`**.

### 4.2 단일 강제점 — `OwnedQuerySetMixin` + `IsOwner` (Sprint0 게이트)

**관점: 격리는 가장 흔한 보안 사고 지점이라 ViewSet마다 손으로 필터링하면 안 된다. 1곳만 빠뜨려도 타설계사 고객 유출.** 강제점을 코드 1곳으로 모은다.

```
# 계약 (구현 코드 아님 — 구조)
OwnedQuerySetMixin:
    get_queryset():
        qs = super().get_queryset()
        if request.user.profile.is_admin:        # 화이트리스트 ①
            return qs                              #   admin bypass
        return qs.filter(owner=request.user)       # 그 외 전부 강제 user 필터

IsOwner(BasePermission):
    has_object_permission(request, view, obj):
        return obj.owner == request.user or request.user.profile.is_admin
```

**적용 규칙 (절대원칙)**
- 모든 설계사 소유 ViewSet(`Customer`, `CustomerInsurance`, `Task`, `Schedule`, `ActivityLog`, `Suggest`…)은 `OwnedQuerySetMixin` 상속 **강제**.
- `request.user` 없는 데이터 접근 = **코드리뷰 reject**.
- 회귀테스트 Day1: "설계사 A가 설계사 B 고객 조회 → 404" 테스트를 소유 모델 전부에 작성.

### 4.3 예외 경로 — 명시적 화이트리스트 2개

| # | 경로 | 메커니즘 | 주의 |
|---|---|---|---|
| ① | admin | `Profile.is_admin` bypass | 관리 목적만. 일반 설계사에 절대 부여 금지 |
| ② | 공유뷰 | `AllowAny` + `share_token` 쿼리 | `request.user` 없음. 노출범위 = 납입현황 '사실'만(§5 컴플라이언스) |

이 둘 **외**의 `request.user` 없는 데이터 접근은 전부 reject.

### 4.4 SET_NULL 유령행 함정

**`Customer.user on_delete=SET_NULL`**(foliio 2026-05-15 탈퇴 시 데이터 보존) 그대로 유지. 단 SET_NULL이면 "소유자 없는 고객"이 격리 필터(`filter(owner=request.user)`)를 통과 못 해 **아무에게도 안 보이는 유령행**이 된다.

```
탈퇴 → Customer.user = NULL
     → filter(owner=request.user) 통과 X  (owner=NULL)
     → admin bypass(get_queryset)에서만 보임
     → admin "소유자 없는 고객" 필터로 재배정 동선 필수
```

> **갭**: foliio admin 재배정 필터 재활용 가정(추정). 인파 문맥에서 재배정 UX/동선 미검증 — admin 대시보드에 "owner=NULL 고객" 필터 + 재배정 액션 명세 필요(`dev/02` admin 영역과 교차).

---

## 5. 동의 분리 & 북극성 귀속 연계

### 5.1 동의 2종 — 절대 분리 (컴플라이언스 게이트)

**온보딩 시점이 컴플라이언스 게이트와 만나는 지점.** 카카오 가입 ≠ 국외이전 동의. 이 둘은 **주체·시점·대상이 다르다.**

| | 설계사 약관 (온보딩) | 고객 국외이전 동의 (detect 게이트) |
|---|---|---|
| 주체 | 설계사 본인 | 설계사가 받아온 *고객*의 동의 |
| 시점 | 가입 온보딩 STEP 1 | 증권 detect **직전** (412 게이트) |
| 저장 | `Profile` 약관 동의 플래그 | `Customer.consent_overseas_at` + `ConsentLog` |
| 범위 | 서비스/개인정보/마케팅(선택) | 민감정보(병력) 국외이전(Claude API US) |
| 게이트 | 온보딩 통과 조건 | `consent_overseas_at is None → 412 CONSENT_OVERSEAS_REQUIRED` |

**온보딩 UX 레드라인**: 이 분리를 온보딩 화면이 흐리면 안 된다. 설계사가 온보딩에서 약관 동의했다고 *고객* 국외이전 동의가 받아진 게 아니다. 고객 동의는 **고객별·detect별**로 별도 수집(`dev/07` detect 6단계 ①번 게이트).

### 5.2 `ConsentLog` (foliio엔 없음 — 인파 net-new, 6요건)

고객 국외이전 동의는 감사 추적 가능해야 한다. `dev/02` 모델 지도의 `ConsentLog`와 동일:

```
ConsentLog  (고객별 동의 감사로그 — 6요건)
  customer FK        # 누가(고객)
  consented_at       # 언제
  scope              # 무엇을 (overseas_transfer / medical_sensitive)
  doc_version        # 어느 약관 버전
  ip                 # 어디서
  revoked_at (null)  # 철회 시점 (철회권 보장)
```

> 설계사 약관 동의(온보딩)는 `Profile` 플래그로 충분 — 별도 `ConsentLog` 미사용. 단 마케팅 동의 철회는 추적 필요(추정: `Profile.marketing_agreed_at` + 철회 시각). 정식 출시 전 정보주체 권리(열람·철회) 동선 확정 필요.

### 5.3 `ref_code` — 가입 시 발급, 북극성 귀속 근간

설계사 가입은 `ref_code` 발급의 **자연 트리거**다. 공유링크 `?ref=<설계사코드>` × `share_token`으로 귀속(`referral_attributed`) 계측.

```
가입 완료 → Profile.ref_code 발급 (Day1: 컬럼만, 로직 Sprint0 게이트)
공유링크 생성 → URL에 ?ref=<ref_code> 임베드
고객 열람(share_view, BE 서버측정) → ref_code × share_token 매칭 → referral_attributed
```

> **갭(blocking, 정본 §8 명시)**: `ref_code` 생성·유일성·위변조 방지 로직 미설계. Day1은 스키마(`unique` 컬럼)만 동결, 발급 알고리즘은 Sprint0. 위변조 방지(예측 불가 토큰 vs 순번)는 귀속 정확도 근간이라 동결 전 확정.

---

## 6. 콜드스타트 온보딩 — 첫 고객 등록 유도

### 6.1 활성화 정의 = "첫 고객 등록 + 첫 증권 업로드"

인파의 활성화(activation) 북극선은 **첫 고객 1명 등록 → 첫 증권 detect**다. 가입만 하고 빈 대시보드를 보면 이탈한다. 온보딩 STEP 3 + 모든 빈 상태(empty state)를 **단일 CTA로 수렴**시킨다.

```
가입 직후 대시보드 (고객 0)
   ┌─────────────────────────────────┐
   │  👋 환영합니다, OO 설계사님         │
   │                                 │
   │  아직 등록된 고객이 없어요         │
   │  증권을 올리면 분석이 시작됩니다    │
   │                                 │
   │     [ 📄 증권 올리기 ]  ← 단일 CTA │  ← /customer/create
   └─────────────────────────────────┘
```

### 6.2 빈 상태(empty state) — 전부 동일 CTA로 수렴

| 화면 | 빈 상태 | CTA | 목적지 |
|---|---|---|---|
| 대시보드 `/home` | 고객 0 | `[증권 올리기]` | `/customer/create` |
| 고객목록 `/customer` | 고객 0 | `[증권 올리기]` | `/customer/create` |
| 액션큐 | 할일 0 | `[첫 고객 등록]` | `/customer/create` |
| 캘린더 | 일정 0 | 점선 일러스트 (CTA 보조) | — |

**FE 계약**: empty 상태는 6화면 공통 컴포넌트 `<ColdStartCard cta target/>`로 단일화. 콜드스타트 CTA는 **물리적으로 1개 목적지**(`/customer/create`)로만 — 첫 행동을 흐리는 분기 금지.

### 6.3 온보딩 진행 게이트 (재진입 보장)

```
onboarding_completed_at IS NULL
   → 로그인 시 항상 /onboarding 로 라우팅 (중단 후 재진입 보장)
   → STEP 1(약관) → STEP 2(위촉 자기신고) → STEP 3(첫 고객 — skip 허용)
   → STEP 2 완료 시점에 onboarding_completed_at 기록 (STEP 3는 skip 가능)
```

- **STEP 3는 skip 허용** — 첫 고객 등록을 강제하면 마찰. skip해도 대시보드 빈 상태가 동일 CTA로 계속 유도(§6.2). "강제 아닌 수렴" 전략.
- **온보딩 완료 판정**: STEP 2(위촉 자기신고)까지만 필수. `onboarding_completed_at` 기록 = 약관+위촉 완료.

### 6.4 콜드스타트 계측 (북극선 연결)

```
가입 → 온보딩완료 → [첫 고객 등록] → [첫 증권 detect = ocr_upload] → analysis_complete
                                          ↑                              ↑
                                   활성화 1차 신호              활성화 완성(북극선 입구)
```

- 활성화 깔때기: `signup → onboarding_complete → first_customer → first_ocr_upload → first_analysis_complete`.
- `ocr_upload` / `analysis_complete`는 `NorthStarEvent` 6종 중 2종(§5 / 북극성 정본). 콜드스타트 성공 = `first_analysis_complete` 1건.
- **(추정)** 콜드스타트 전환율 목표·집계는 PMF admin 깔때기(`dev/02` analytics)와 교차. 본 문서는 *이벤트 발화 지점*만 못박고 목표 수치는 베타 실측 후.

---

## 7. 화면 명세 (FE)

### 7.1 라우트

| 라우트 | 화면 | 렌더 | 가드 |
|---|---|---|---|
| `/login` | 카카오 로그인 | client | 비인증만 |
| `/auth/kakao/callback` | OAuth 콜백 | client (sessionStorage 가드) | — |
| `/onboarding` | 약관/위촉/첫고객 3-step | client | 인증 + `onboarding_completed_at IS NULL` |
| `/home` | 대시보드 (콜드스타트 빈상태) | RSC SSR | 인증 + 온보딩완료 |

### 7.2 온보딩 컴포넌트 트리

```
<OnboardingShell>  (진행바 1/2/3, 뒤로/건너뛰기)
 ├ <StepTerms/>        STEP1  약관 동의 (필수 2 + 선택 1 체크박스)
 │    └ 필수 미동의 → [다음] 비활성
 ├ <StepAttest/>       STEP2  위촉 자기신고 (affiliation/agent_type/license_self_declared)
 │    └ license_self_declared 미체크 → §97 기능 게이트 경고(차단 아님, 고지)
 └ <StepColdStart/>    STEP3  첫 고객 등록 유도 ([증권 올리기] or [나중에])
      └ skip → /home (빈상태 동일 CTA로 계속 유도)
```

### 7.3 로그인 화면 상태 5종

| 상태 | 렌더 |
|---|---|
| 기본 | 카카오 버튼 1개 (브랜드 가이드 색) |
| 진행중 | 버튼 disabled + 스피너 |
| 콜백 처리중 | `/callback` 전체화면 로딩 (sessionStorage 가드 중) |
| 에러(invalid_grant) | "다시 시도해 주세요" + 재시도 (1회용 code 중복 — §1.1) |
| 휴면복구 | "계정이 복구되었습니다" 토스트 후 `/home` |

---

## 8. API 계약 (인증·온보딩)

| Path | Method | Auth | 용도 |
|---|---|---|---|
| `/api/v1/rest-auth/kakao_login/` | POST | AllowAny | 카카오 OAuth → Token + `{is_new, onboarding_required}` (♻ + 응답 확장) |
| `/api/v1/accounts/logout/` | POST | Token | 토큰 폐기 (추정: foliio 패턴 확인) |
| `/api/v1/accounts/profile/` | GET | Token | 내 프로필 + 온보딩 상태 + 멤버십 |
| `/api/v1/accounts/onboarding/` | PATCH | Token | 약관/위촉 저장 → `onboarding_completed_at` 기록 |
| `/api/v1/accounts/profile/attest/` | PATCH | Token | 위촉 자기신고 (affiliation/agent_type/license_self_declared) |

**`kakao_login` 응답 확장 (foliio ♻ + 인파 net-new)**
```json
{
  "token": "9a8b7c…",
  "is_new": true,
  "onboarding_required": true,
  "profile": {
    "onboarding_completed_at": null,
    "agent_type": null,
    "license_self_declared": false,
    "membership": { "name": "플러스", "is_unlimited": true }
  }
}
```

> **갭**: `kakao_login` 응답에 `is_new`/`onboarding_required` 추가는 foliio 응답 스키마 확장 — BE `KakaoLoginView` 리턴 페이로드 수정 필요(로직 무변경, 응답 필드만 추가). `logout` 엔드포인트 존재 여부 foliio 확인 후 ♻ 또는 net-new.

---

## 9. 갭 · 미결 (Sprint0 게이트 / blocking 표시)

| # | 갭 | 영향 | 게이트 |
|---|---|---|---|
| 1 | **멀티테넌시 단일 강제점** `OwnedQuerySetMixin`/`IsOwner`가 dev 문서에 미명시 | 1곳 누락 = 타설계사 고객 유출 | ★Sprint0 blocking |
| 2 | **`ref_code` 발급 체계** (생성·유일성·위변조) 미설계 | 북극성 귀속 정확도 근간 | ★Sprint0 (Day1 스키마만 동결) |
| 3 | 위촉 자기신고 vs 자격 API 연동 — 베타 self-attestation 확정, 정식 미정 | §97 기능 게이트 입력 | 베타 self-attest로 우회 |
| 4 | `is_new`/`onboarding_required` 응답 확장 — BE `KakaoLoginView` 페이로드 수정 | 온보딩 라우팅 분기 | BE 응답 필드 추가(로직 무변경) |
| 5 | `logout` 엔드포인트 foliio 존재 여부 미확인 | 세션 종료 동선 | foliio 확인 후 ♻/net-new |
| 6 | 인파 카카오 콘솔 신규 키·Redirect URI 발급 — 운영작업, 책임자·기한 미지정 | OAuth 동작 전제 | 대표 승인 + 담당 지정 |
| 7 | SET_NULL 유령행 admin 재배정 동선 — foliio 필터 재활용 가정(추정), 인파 미검증 | 탈퇴 후 고객 비가시 | `dev/02` admin 영역 교차 |
| 8 | 토큰 만료/리프레시 정책 — 베타 무기한(추정), 정식 재검토 | 세션 보안 | 정식 출시 전 |
| 9 | 마케팅 동의 철회 동선 — 정보주체 권리(열람·철회) 미확정 | 개인정보 컴플라이언스 | 정식 출시 전 |
| 10 | 온보딩 STEP3 skip 후 재유도 전환율 목표 — 베타 실측 후 | 콜드스타트 KPI | PMF admin 교차 |

---

## 10. 수용 기준 (Definition of Done)

- [ ] 카카오 로그인 → Token 발급 → `is_new` 분기 → 온보딩/대시보드 라우팅 동작 (시크릿 창 검증 — ngsw 캐시 함정)
- [ ] 인파 전용 카카오 키 발급 + Redirect URI canonical 1개 등록 (대표 승인)
- [ ] `OwnedQuerySetMixin` + `IsOwner` 적용 → "설계사 A가 B 고객 조회 = 404" 회귀테스트 전 소유 모델 통과
- [ ] 화이트리스트 2개(admin/share_token) 외 `request.user` 없는 접근 0건 (코드리뷰 + grep 검증)
- [ ] `is_dormant` 미들웨어 게이트 부재 확인 + 휴면 재로그인 자동복구 동작
- [ ] 동의 2종 분리 검증: 온보딩 약관 ≠ 고객 국외이전 동의 (detect 412 게이트 별도 발화)
- [ ] `onboarding_completed_at IS NULL` → `/onboarding` 강제 라우팅 (중단 재진입 보장)
- [ ] 콜드스타트: 빈 상태 6화면 전부 단일 CTA(`/customer/create`)로 수렴
- [ ] `ref_code` Day1 스키마(`unique` 컬럼) 마이그레이션 포함 (발급 로직 Sprint0)
- [ ] `ConsentLog` 6요건 스키마 동결 + 고객 동의 감사 추적 가능