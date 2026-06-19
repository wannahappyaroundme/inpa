# 인증 & 온보딩 (Auth & Onboarding)

> 인파(Inpa) 개발 정본 · `docs/dev/11-auth-onboarding.md`
> **이메일/비밀번호 전용 인증.** 카카오 OAuth 없음.
> 흐름: 회원가입 → 이메일 인증 → 로그인 → 비밀번호 찾기/재설정 → 마이페이지 → 콜드스타트 온보딩.
> 상위 정본: `dev/02`(모델·API) · `dev/07`(API 계약) · `dev/09`(컴플라이언스). 본 문서는 그 위에 인증/온보딩 레이어를 얹는다.

---

## 0. 한눈에 — 이 문서가 잠그는 것

| # | 영역 | 핵심 결정 |
|---|---|---|
| 1 | 인증 방식 | 이메일/비밀번호 전용. 카카오 OAuth 제거. |
| 2 | 가입 흐름 | 이메일 인증 → 약관 동의(통합) → 위촉 자기신고 → 대시보드 |
| 3 | 세션 | DRF Token. 베타 무기한, 정식 출시 전 만료 정책 재검토 |
| 4 | 비밀번호 찾기 | 이메일 토큰 재설정. 24시간 만료 1회용 링크 |
| 5 | 권한·멀티테넌시 | `OwnedQuerySetMixin` + `IsOwner` 단일 강제점. 예외 2개(admin/share_token) |
| 6 | 동의 분리 | 설계사 약관(가입) ≠ 고객 국외이전 동의(detect 412 게이트) |
| 7 | 콜드스타트 | 첫 고객 등록 유도 = 활성화 북극선, 빈 상태 전부 단일 CTA |

**레드라인 3개 (절대 어기지 말 것)**

1. **멀티테넌시 단일 강제점** — `request.user` 없는 데이터 접근은 코드리뷰 reject. 화이트리스트 2개(admin / 공유뷰 share_token) 외 예외 없음.
2. **동의 2종 분리** — 가입 약관 = 설계사 본인 서비스약관. `consent_overseas_at`은 *고객별*. 가입 UX가 이 둘을 섞으면 안 됨.
3. **`is_dormant` 게이트 미들웨어 금지** — 미들웨어/permission에서 휴면을 차단하면 영구 락아웃. 복구는 로그인 API에서만.

---

## 1. 인증 파이프라인 — 이메일/비밀번호

### 1.1 전체 인증 흐름 (ASCII)

```
[설계사]                        [inpa_fe]                    [inpa_be]
   │                               │                             │
   │  (A) 회원가입                  │                             │
   │──────────────────────────────>│                             │
   │                               │ POST /accounts/register/    │
   │                               │  {email, password,          │
   │                               │   terms_agreed,             │
   │                               │   privacy_agreed,           │
   │                               │   marketing_agreed(선택)}    │
   │                               │───────────────────────────>│
   │                               │                   User 생성(비활성)
   │                               │                   이메일 인증 메일 발송
   │                               │  {message: "이메일 확인"}   │
   │                               │<───────────────────────────│
   │  이메일 수신 → 링크 클릭        │                             │
   │──────────────────────────────>│                             │
   │                               │ GET /accounts/verify-email/ │
   │                               │  ?token=<uuid>              │
   │                               │───────────────────────────>│
   │                               │              User.is_active=True
   │                               │  /login?verified=true       │
   │                               │<───────────────────────────│
   │                               │                             │
   │  (B) 로그인                    │                             │
   │──────────────────────────────>│                             │
   │                               │ POST /accounts/login/       │
   │                               │  {email, password}          │
   │                               │───────────────────────────>│
   │                               │             비밀번호 검증
   │                               │             is_active 확인
   │                               │             is_dormant 복구(if True)
   │                               │  {token, onboarding_required}
   │                               │<───────────────────────────│
   │                               │ onboarding_required?        │
   │                               │  → /onboarding : /home      │
```

### 1.2 비밀번호 찾기 흐름 (ASCII)

```
[설계사]                        [inpa_fe]                    [inpa_be]
   │  이메일 입력                   │                             │
   │──────────────────────────────>│                             │
   │                               │ POST /accounts/             │
   │                               │   password-reset/request/   │
   │                               │  {email}                    │
   │                               │───────────────────────────>│
   │                               │        해당 이메일 존재 여부
   │                               │        무조건 200 (이메일 노출 방지)
   │                               │        링크 발송 (존재할 경우만)
   │                               │  {message: "이메일 확인"}   │
   │                               │<───────────────────────────│
   │  이메일 수신 → 링크 클릭        │                             │
   │──────────────────────────────>│                             │
   │                               │ GET /reset-password         │
   │                               │  ?token=<uuid>              │
   │                               │  → 토큰 유효 여부 확인       │
   │                               │───────────────────────────>│
   │                               │  {valid: true/false}        │
   │                               │<───────────────────────────│
   │  새 비밀번호 입력               │                             │
   │──────────────────────────────>│                             │
   │                               │ POST /accounts/             │
   │                               │   password-reset/confirm/   │
   │                               │  {token, new_password,      │
   │                               │   new_password_confirm}     │
   │                               │───────────────────────────>│
   │                               │    토큰 검증 + 비밀번호 변경
   │                               │    토큰 즉시 무효화(1회용)
   │                               │  {message: "변경 완료"}     │
   │                               │<───────────────────────────│
   │                               │ /login?reset=done           │
```

---

## 2. 회원가입 & 위촉확인

### 2.1 가입 = "이메일 + 약관 + 이메일 인증 + 위촉 자기신고"

인파의 가입자는 **보험설계사(원수사·GA 위촉직 개인사업자)**다. 가입은 3단계지만 체감은 "이메일+비밀번호 입력 → 약관 체크 → 이메일 확인 → 위촉정보 입력".

```
[가입 폼]  이메일 + 비밀번호 + 약관 동의 통합
   └→ [BE] 이메일 인증 메일 발송 + User 생성(is_active=False)
        └→ [이메일] 인증 링크 클릭 → is_active=True
             └→ /login?verified=true (이메일 인증 완료 알림)
                  └→ 로그인 성공 → onboarding_required=true
                       ├ STEP 1  위촉 자기신고 (소속/자격/경력)
                       └ STEP 2  첫 고객 등록 유도 (콜드스타트 — §6)
```

**약관 동의는 가입 폼에 통합** — 가입 폼의 체크박스로 일괄 처리. 별도 온보딩 스텝 없음. 이메일 인증 완료 후 곧장 위촉 자기신고로 진입.

### 2.2 이메일 인증 정책

| 항목 | 정책 |
|---|---|
| 인증 토큰 | UUID4, DB 저장(`EmailVerificationToken`) |
| 만료 | 24시간 |
| 링크 형식 | `https://inpa.도메인/auth/verify-email?token=<uuid>` |
| 이중 클릭 가드 | 토큰 1회 사용 후 즉시 `used_at` 기록, 재사용 시 410 Gone |
| 미인증 재발송 | `/accounts/resend-verification/` (쿨다운 60초) |
| 미인증 로그인 | 403 `EMAIL_NOT_VERIFIED` + 재발송 버튼 안내 |

### 2.3 위촉확인 — "자기신고" 모델 (베타 정책)

**핵심 결정: 베타는 위촉 자격을 자동검증하지 않는다. 자기신고(self-attestation)로 받는다.** 보험설계사 자격 API(생·손보협회 e-클린보험 등) 연동은 외부 인증·비용·법무 검토가 필요 — 베타 범위 밖. 자기신고 + 체크박스 면책으로 컴플라이언스 라인을 지킨다.

| 필드 | 타입 | 필수 | 용도 |
|---|---|---|---|
| `affiliation` | str | ✓ | 소속(원수사/GA명) — 자유입력 |
| `agent_type` | enum(life/nonlife/both) | ✓ | 생명/손해/교차 — §97 비교안내 게이트 입력 |
| `license_self_declared` | bool | ✓ | "본인은 유효한 보험모집 자격을 보유하고 있음" 자기신고 체크 |
| `career_years` | int | – | 경력연차 (성과카드/온보딩 카피 개인화) |
| `license_no` | str | – | 자격번호 (선택 입력 — 추후 검증 hook 대비 컬럼만 확보) |

**왜 자기신고로 충분한가**: 인파는 보험을 중개·권유하지 않는다(`dev/09`). 판단·권유 주체는 라이선스 있는 설계사 본인. 인파는 *도구*다. 단 §97 비교안내서/발굴 기능은 위촉 자격이 전제이므로 `license_self_declared=false`면 **해당 기능 진입 차단**(분석/공유는 허용).

### 2.4 `User` & `Profile` 모델 (인파 기준)

```
User (Django 내장)
  email          CharField(unique)   ← 로그인 ID
  password       (bcrypt, Django 기본)
  is_active      bool default=False  ← 이메일 인증 전 비활성
  date_joined    datetime

Profile (OneToOne User)
  ── 계정 상태 ─────────────────────────────
  is_admin                bool default=False
  is_dormant              bool default=False    # 미들웨어 게이트 금지!
  dormant_at              datetime(null)
  dormancy_warning_sent_at datetime(null)
  will_delete_at          datetime(null)
  ── 약관 동의 (가입 시 통합) ─────────────────
  terms_agreed_at         datetime             # 서비스 이용약관
  privacy_agreed_at       datetime             # 개인정보 처리방침
  marketing_agreed_at     datetime(null)       # 선택 마케팅 동의
  ── 위촉·온보딩 ──────────────────────────────
  affiliation             str(null)
  agent_type              enum(1=life/2=nonlife/3=both, null)
  license_self_declared   bool default=False
  license_no              str(null)
  career_years            int(null)
  onboarding_completed_at datetime(null)       # null=온보딩 미완 → 재진입
  ref_code                str(unique, null)    # Day1 컬럼만, 발급 로직 Sprint0

EmailVerificationToken
  user        FK User
  token       UUIDField(unique)
  created_at  datetime
  used_at     datetime(null)
  expires_at  datetime                         # created_at + 24h

PasswordResetToken
  user        FK User
  token       UUIDField(unique)
  created_at  datetime
  used_at     datetime(null)
  expires_at  datetime                         # created_at + 24h
```

---

## 3. 권한 · 세션

### 3.1 세션 모델

- **DRF Token** 사용. 로그인 성공 → `{ token }` 발급 → FE가 `Authorization: Token <…>` 헤더로 모든 API 인증.
- **만료 정책**: 베타는 무기한(설계사 도구 — 매일 진입, 잦은 재로그인은 마찰). 정식 출시 전 만료/리프레시 정책 재검토.
- **로그아웃**: `POST /accounts/logout/` → BE Token 삭제 + FE 로컬스토리지 폐기.
- **비밀번호 변경**: 변경 완료 시 기존 Token 전부 무효화(보안 강제 재로그인).

### 3.2 권한 레이어 (3단)

```
Layer 1  인증 여부      IsAuthenticated (DRF default)
Layer 2  소유권         IsOwner (request.user == obj.owner)  ★멀티테넌시 핵심
Layer 3  기능 게이트     license_self_declared / 멤버십 tier / consent_overseas_at
```

| 화이트리스트(인증 우회) | permission | 근거 |
|---|---|---|
| 회원가입 | `AllowAny` | 가입 진입점 |
| 이메일 인증 | `AllowAny` | 링크 클릭 = 비인증 상태 |
| 로그인 | `AllowAny` | 인증 진입점 |
| 비밀번호 찾기/재설정 | `AllowAny` | 비인증 접근 필요 |
| 멤버십 목록 | `AllowAny` | 가격표 공개 |
| 공유뷰(분석/비교) | `AllowAny` + `share_token` | 고객 열람 |

### 3.3 멀티테넌시 — 설계사별 데이터 격리 (★ 가장 중요)

**테넌트 = 설계사 1인.** 격리는 **row-level: 모든 쿼리에 `filter(owner=request.user)`.**

```python
# 계약 (구현 코드 아님 — 구조)
class OwnedQuerySetMixin:
    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.profile.is_admin:   # 화이트리스트 ①
            return qs                              #   admin bypass
        return qs.filter(owner=self.request.user) # 그 외 전부 강제 user 필터

class IsOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user or request.user.profile.is_admin
```

**적용 규칙 (절대원칙)**
- 모든 설계사 소유 ViewSet(`Customer`, `CustomerInsurance`, `Task`, `Schedule`, `ActivityLog`, `Suggest` 등)은 `OwnedQuerySetMixin` 상속 강제.
- `request.user` 없는 데이터 접근 = 코드리뷰 reject.
- 회귀테스트 Day1: "설계사 A가 설계사 B 고객 조회 → 404" 테스트를 소유 모델 전부에 작성.

**화이트리스트 예외 2개만**

| # | 경로 | 메커니즘 | 주의 |
|---|---|---|---|
| ① | admin | `Profile.is_admin` bypass | 관리 목적만. 일반 설계사에 부여 금지 |
| ② | 공유뷰 | `AllowAny` + `share_token` | 노출범위 = 납입현황 '사실'만(`dev/09`) |

**가시성 매트릭스 (전체)**

| 데이터 | 가시성 | 격리 메커니즘 |
|---|---|---|
| 게시판 SNS 피드(글·댓글·좋아요) | 모든 설계사(공유) | owner FK 없음 |
| 공지사항 | 모든 설계사 읽기, 관리자 작성 | owner FK 없음 |
| FAQ | 모든 설계사 읽기, 관리자 작성 | owner FK 없음 |
| 판촉물 샘플 카탈로그 | 모든 설계사 읽기 | owner FK 없음 |
| 1:1 문의 | 작성자 + 관리자 | owner FK |
| 고객 정보·동의·보험 정보·보험 분석·비교 | 소유자 전용 | `OwnedQuerySetMixin` + `IsOwner` |
| 캘린더·KPI/대시보드·알림/리마인더 | 소유자 전용 | `OwnedQuerySetMixin` + `IsOwner` |
| 설계사 기준(`planner_baseline`) | 소유자 전용 | `OwnedQuerySetMixin` + `IsOwner` |
| 판촉물 주문 | 설계사=본인 주문, 관리자=전체 | owner FK + admin bypass |
| 요금제·사용량 | 설계사=본인, 관리자=전체 | owner FK + admin bypass |

### 3.4 휴면/탈퇴

- 휴면 시스템(`process_dormancy`: +150d 경고 / +180d 휴면 / dormant+180d 삭제) — foliio 로직 포팅.
- **레드라인 재확인**: `is_dormant`를 미들웨어/permission에서 차단하지 말 것. 로그인 API(`/accounts/login/`)가 `is_dormant=True` 상태 확인 후 자동으로 `is_dormant=False` + `dormant_at=None` 복구. admin(`is_admin=True`)은 휴면 처리 제외.
- 탈퇴: foliio `withdraw/` 익명화 패턴 포팅(no-undo). 탈퇴 설계사의 `Customer.user`가 `SET_NULL` → "소유자 없는 유령행" 발생 → admin "owner=NULL 고객" 필터 + 재배정 액션 필수.

---

## 4. 동의 분리

### 4.1 동의 2종 — 절대 분리 (컴플라이언스 게이트)

| | 설계사 약관 (가입 시) | 고객 국외이전 동의 (detect 게이트) |
|---|---|---|
| 주체 | 설계사 본인 | 설계사가 받아온 *고객*의 동의 |
| 시점 | 가입 폼 체크박스 (통합) | 증권 detect **직전** (412 게이트) |
| 저장 | `Profile` 약관 동의 타임스탬프 | `Customer.consent_overseas_at` + `ConsentLog` |
| 범위 | 서비스/개인정보/마케팅(선택) | 민감정보(병력) 국외이전(Claude API US) |
| 게이트 | 가입 통과 조건 | `consent_overseas_at is None → 412 CONSENT_OVERSEAS_REQUIRED` |

**UX 레드라인**: 설계사가 가입 시 약관에 동의했다고 *고객* 국외이전 동의가 받아진 게 아니다. 고객 동의는 **고객별·detect별**로 별도 수집(`dev/07` detect 6단계 ①번 게이트). UI에서 이 두 동의를 같은 화면에서 처리하거나 혼동을 줄 수 있는 표현 금지.

### 4.2 `ConsentLog` — 고객 국외이전 동의 감사추적

```
ConsentLog  (고객별 동의 감사로그 — 6요건)
  customer FK        # 누가(고객)
  consented_at       # 언제
  scope              # 무엇을 (overseas_transfer / medical_sensitive)
  doc_version        # 어느 약관 버전
  ip                 # 어디서
  revoked_at (null)  # 철회 시점 (철회권 보장)
```

설계사 약관 동의(가입)는 `Profile` 타임스탬프 필드로 충분 — 별도 `ConsentLog` 미사용.

---

## 5. 콜드스타트 온보딩 — 첫 고객 등록 유도

### 5.1 활성화 정의 = "첫 고객 등록 + 첫 증권 업로드"

인파의 활성화(activation) 북극선은 **첫 고객 1명 등록 → 첫 증권 detect**다. 가입만 하고 빈 대시보드를 보면 이탈한다. 온보딩 STEP 2 + 모든 빈 상태(empty state)를 **단일 CTA로 수렴**시킨다.

```
가입 직후 대시보드 (고객 0)
   ┌─────────────────────────────────┐
   │  환영합니다, OO 설계사님          │
   │                                 │
   │  아직 등록된 고객이 없어요         │
   │  증권을 올리면 분석이 시작됩니다    │
   │                                 │
   │     [ 증권 올리기 ]  ← 단일 CTA   │  ← /customer/create
   └─────────────────────────────────┘
```

### 5.2 빈 상태(empty state) — 전부 동일 CTA로 수렴

| 화면 | 빈 상태 | CTA | 목적지 |
|---|---|---|---|
| 대시보드 `/home` | 고객 0 | `[증권 올리기]` | `/customer/create` |
| 고객목록 `/customer` | 고객 0 | `[증권 올리기]` | `/customer/create` |
| 액션큐 | 할일 0 | `[첫 고객 등록]` | `/customer/create` |
| 캘린더 | 일정 0 | 점선 일러스트 (CTA 보조) | — |

**FE 계약**: empty 상태는 6화면 공통 컴포넌트 `<ColdStartCard cta target/>` 로 단일화. 콜드스타트 CTA는 물리적으로 1개 목적지(`/customer/create`)로만 — 첫 행동을 흐리는 분기 금지.

### 5.3 온보딩 진행 게이트 (재진입 보장)

```
onboarding_completed_at IS NULL
   → 로그인 시 항상 /onboarding 으로 라우팅 (중단 후 재진입 보장)
   → STEP 1(위촉 자기신고) → STEP 2(첫 고객 — skip 허용)
   → STEP 1 완료 시점에 onboarding_completed_at 기록
```

- **STEP 2는 skip 허용** — 첫 고객 등록을 강제하면 마찰. skip해도 대시보드 빈 상태가 동일 CTA로 계속 유도. "강제 아닌 수렴" 전략.
- **온보딩 완료 판정**: STEP 1(위촉 자기신고)만 필수. `onboarding_completed_at` 기록 = 위촉 완료.

### 5.4 활성화 깔때기 계측

```
signup → email_verified → login → onboarding_complete
       → first_customer → first_ocr_upload → first_analysis_complete
```

- `ocr_upload` / `analysis_complete`는 `NorthStarEvent` 6종 중 2종. 콜드스타트 성공 = `first_analysis_complete` 1건.

---

## 6. 화면 명세 (FE)

### 6.1 라우트

| 라우트 | 화면 | 렌더 | 가드 |
|---|---|---|---|
| `/register` | 회원가입 폼 | client | 비인증만 |
| `/auth/verify-email` | 이메일 인증 처리 | client | — (비인증 접근 가능) |
| `/login` | 로그인 폼 | client | 비인증만 |
| `/forgot-password` | 비밀번호 찾기 이메일 입력 | client | 비인증만 |
| `/reset-password` | 새 비밀번호 입력 | client | — (토큰 파라미터로 접근) |
| `/onboarding` | 위촉 자기신고 + 첫 고객 유도 2-step | client | 인증 + `onboarding_completed_at IS NULL` |
| `/home` | 대시보드 (콜드스타트 빈상태) | RSC SSR | 인증 + 온보딩완료 |
| `/settings/profile` | 마이페이지 (비번 변경·탈퇴·휴면) | client | 인증 |

### 6.2 온보딩 컴포넌트 트리

```
<OnboardingShell>  (진행바 1/2, 뒤로/건너뛰기)
 ├ <StepAttest/>       STEP1  위촉 자기신고 (affiliation/agent_type/license_self_declared)
 │    └ license_self_declared 미체크 → §97 기능 게이트 경고(차단 아님, 고지)
 └ <StepColdStart/>    STEP2  첫 고객 등록 유도 ([증권 올리기] or [나중에])
      └ skip → /home (빈상태 동일 CTA로 계속 유도)
```

### 6.3 로그인 화면 상태 6종

| 상태 | 렌더 |
|---|---|
| 기본 | 이메일·비밀번호 입력 + [로그인] 버튼 |
| 진행중 | 버튼 disabled + 스피너 |
| 이메일 미인증 | 403 → "이메일 인증 후 로그인하세요" + [인증 메일 재발송] 버튼 |
| 비밀번호 오류 | 401 → "이메일 또는 비밀번호가 올바르지 않습니다" (계정 존재 여부 노출 금지) |
| 이메일 인증 완료 직후 | `/login?verified=true` → "이메일 인증이 완료되었습니다. 로그인하세요" 배너 |
| 휴면 자동복구 | 로그인 성공 후 "계정이 복구되었습니다" 토스트 + `/onboarding` or `/home` |

### 6.4 마이페이지(설정) — `/settings/profile`

| 기능 | UX |
|---|---|
| 비밀번호 변경 | 현재 비밀번호 확인 → 새 비밀번호 × 2 입력 → 변경 완료 시 기존 토큰 전부 무효화 + 재로그인 유도 |
| 마케팅 동의 철회 | 토글 → `Profile.marketing_agreed_at = None` |
| 회원 탈퇴 | 경고 모달(no-undo) → 비밀번호 재확인 → 익명화 처리 |
| 휴면 전환 | — (자동 처리, 설계사 직접 전환 없음) |

---

## 7. API 계약 (인증·온보딩)

### 7.1 엔드포인트 목록

| Path | Method | Auth | 용도 |
|---|---|---|---|
| `/api/v1/accounts/register/` | POST | AllowAny | 회원가입 → 이메일 인증 메일 발송 |
| `/api/v1/accounts/verify-email/` | GET | AllowAny | 이메일 인증 토큰 처리 |
| `/api/v1/accounts/resend-verification/` | POST | AllowAny | 이메일 인증 메일 재발송 (쿨다운 60초) |
| `/api/v1/accounts/login/` | POST | AllowAny | 로그인 → DRF Token + onboarding_required |
| `/api/v1/accounts/logout/` | POST | Token | 로그아웃 → Token 삭제 |
| `/api/v1/accounts/profile/` | GET | Token | 내 프로필 + 온보딩 상태 + 멤버십 |
| `/api/v1/accounts/onboarding/attest/` | PATCH | Token | 위촉 자기신고 저장 → onboarding_completed_at 기록 |
| `/api/v1/accounts/password/change/` | POST | Token | 비밀번호 변경 → 기존 토큰 전부 무효화 |
| `/api/v1/accounts/password-reset/request/` | POST | AllowAny | 비밀번호 재설정 메일 발송 요청 |
| `/api/v1/accounts/password-reset/confirm/` | POST | AllowAny | 새 비밀번호 저장 (토큰 1회용) |
| `/api/v1/accounts/withdraw/` | DELETE | Token | 회원 탈퇴 (익명화) |

### 7.2 주요 요청/응답 계약

**POST `/api/v1/accounts/register/`**
```json
// 요청
{
  "email": "agent@example.com",
  "password": "password123!",
  "password_confirm": "password123!",
  "terms_agreed": true,
  "privacy_agreed": true,
  "marketing_agreed": false
}

// 응답 201
{
  "message": "이메일로 인증 링크를 발송했습니다. 확인 후 로그인하세요."
}

// 오류 400 — 이미 가입된 이메일
{
  "error": "EMAIL_ALREADY_EXISTS"
}
```

**POST `/api/v1/accounts/login/`**
```json
// 요청
{
  "email": "agent@example.com",
  "password": "password123!"
}

// 응답 200
{
  "token": "9a8b7c...",
  "onboarding_required": true,
  "dormancy_recovered": false,
  "profile": {
    "email": "agent@example.com",
    "onboarding_completed_at": null,
    "agent_type": null,
    "license_self_declared": false,
    "membership": { "name": "베타", "is_unlimited": true }
  }
}

// 오류 401 — 이메일/비밀번호 불일치
{ "error": "INVALID_CREDENTIALS" }

// 오류 403 — 이메일 미인증
{ "error": "EMAIL_NOT_VERIFIED" }
```

**PATCH `/api/v1/accounts/onboarding/attest/`**
```json
// 요청
{
  "affiliation": "삼성생명",
  "agent_type": "life",
  "license_self_declared": true,
  "career_years": 3,
  "license_no": "2021-xxxxx"
}

// 응답 200
{
  "onboarding_completed_at": "2026-06-19T10:00:00Z"
}
```

**POST `/api/v1/accounts/password-reset/request/`**
```json
// 요청
{ "email": "agent@example.com" }

// 응답 200 — 항상 200 (이메일 존재 여부 노출 금지)
{ "message": "해당 이메일로 재설정 링크를 발송했습니다." }
```

**POST `/api/v1/accounts/password-reset/confirm/`**
```json
// 요청
{
  "token": "uuid-token",
  "new_password": "newpass123!",
  "new_password_confirm": "newpass123!"
}

// 응답 200
{ "message": "비밀번호가 변경되었습니다. 다시 로그인하세요." }

// 오류 400 — 만료 또는 이미 사용된 토큰
{ "error": "INVALID_OR_EXPIRED_TOKEN" }
```

### 7.3 비밀번호 정책

- 최소 8자, 영문+숫자 조합 강제.
- Django 내장 `AUTH_PASSWORD_VALIDATORS` 활용(길이·공통패턴·숫자전용 차단).
- bcrypt 해시(Django 기본 PBKDF2 또는 `django-bcrypt`로 교체 — 합리적 기본값: PBKDF2 그대로 사용, 교체는 Sprint0에서 재검토).

---

## 8. 컴플라이언스 · 면책

- **정직성 레드라인**: "심의완료/안전/보장확정" 배지 금지. AI 생성물엔 "AI 초안·최종책임 설계사" 면책 고정.
- **원탭 자동발송 없음**: 클립보드 복사/카톡 열기까지만.
- **병력(민감정보) 국외이전**: Claude API 호출 전 `consent_overseas_at` 확인 → null이면 412 반환. 이 게이트는 detect API에만 적용(가입/로그인과 무관).
- **`baseline_source == null` 시 neutral 강제**: 분석 결과를 부족/충분으로 단정하지 않음. 설계사가 기준(`planner_baseline`)을 설정하지 않았으면 히트맵 상태 = neutral.
- **마케팅 동의 선택**: 가입 시 선택(opt-in). 철회는 마이페이지에서 언제든 가능.

---

## 9. 갭 · 미결 (Sprint0 게이트)

| # | 갭 | 영향 | 게이트 |
|---|---|---|---|
| 1 | **`OwnedQuerySetMixin`/`IsOwner`** 전체 ViewSet 적용 목록 미확정 | 1곳 누락 = 타설계사 고객 유출 | ★Sprint0 blocking |
| 2 | **`ref_code` 발급 체계** (생성 알고리즘·유일성·위변조 방지) 미설계 | 북극성 귀속 정확도 근간 | Day1 스키마만 동결, 발급 로직 Sprint0 |
| 3 | **이메일 발송 인프라** — Django 이메일 백엔드(SMTP/SendGrid/SES) 미선정 | 가입·비밀번호 재설정 동작 전제 | Sprint0 선택 필요 |
| 4 | **비밀번호 해시 알고리즘** — PBKDF2 vs bcrypt 최종 선택 미확정 | 보안 강도 | Sprint0 재검토 (합리적 기본값: PBKDF2) |
| 5 | **토큰 만료/리프레시 정책** — 베타 무기한, 정식 미정 | 세션 보안 | 정식 출시 전 재검토 |
| 6 | **SET_NULL 유령행 admin 재배정** 동선 미명세 | 탈퇴 후 고객 비가시 | `dev/02` admin 영역 교차 |
| 7 | **마케팅 동의 철회 감사추적** — `Profile.marketing_agreed_at=null`만으로 충분한지, 별도 로그 필요한지 미확정 | 개인정보 컴플라이언스 | 정식 출시 전 확정 |
| 8 | **위촉 자격 API 연동** — 베타 self-attestation 확정, 정식 재검토 | §97 기능 게이트 | 정식 출시 전 재검토 |
| 9 | **콜드스타트 전환율 목표** — 베타 실측 후 확정 | KPI 기준 | PMF admin 교차 |

---

## 10. 수용 기준 (Definition of Done)

- [ ] 회원가입 → 이메일 인증 메일 수신 → 링크 클릭 → `is_active=True` 전환 확인 (curl 또는 실 클라이언트)
- [ ] 이메일 미인증 상태 로그인 시도 → 403 `EMAIL_NOT_VERIFIED` 응답 + 재발송 버튼 동작
- [ ] 로그인 성공 → Token 발급 → `onboarding_required` 분기 → 온보딩/대시보드 라우팅 동작
- [ ] `OwnedQuerySetMixin` + `IsOwner` 적용 → "설계사 A가 B 고객 조회 = 404" 회귀테스트 전 소유 모델 통과
- [ ] 화이트리스트 2개(admin/share_token) 외 `request.user` 없는 접근 0건 (코드리뷰 + grep 검증)
- [ ] `is_dormant` 미들웨어 게이트 부재 확인 + 휴면 자동복구는 로그인 API에서만 처리
- [ ] 동의 2종 분리: 가입 약관 ≠ 고객 국외이전 동의 (detect 412 게이트 별도 발화)
- [ ] 비밀번호 찾기 이메일 → 24시간 만료 1회용 링크 → 재설정 완료 → 기존 Token 무효화
- [ ] 비밀번호 변경 완료 시 기존 Token 전부 무효화 + 재로그인 강제 확인
- [ ] `onboarding_completed_at IS NULL` → `/onboarding` 강제 라우팅 (중단 재진입 보장)
- [ ] 콜드스타트: 빈 상태 6화면 전부 단일 CTA(`/customer/create`)로 수렴
- [ ] `ref_code` Day1 스키마(`unique` 컬럼) 마이그레이션 포함 (발급 로직 Sprint0)
- [ ] `ConsentLog` 6요건 스키마 동결 + 고객 동의 감사 추적 가능
- [ ] `baseline_source=null` → 히트맵 status=neutral 강제 확인 (부족/충분 단정 없음)
