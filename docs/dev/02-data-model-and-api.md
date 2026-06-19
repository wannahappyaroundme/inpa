# 인파(Inpa) — 데이터 모델 & API 설계 (통합 정본)

> 본 문서는 인파(Inpa)의 백엔드 데이터 모델(DB 스키마)과 주요 API 계약(요청/응답)을 **단일 정합 스키마**로 정의한다.
> 병렬 작업 스트림(공통척추·account·legal-consent·core-product·notifications·boards·판촉물·billing·admin·devops)이 각자 제출한 데이터모델 델타를 한 명세로 직렬 통합한 결과물이다.
> 설계 원칙은 변하지 않는다: **foliio 실코드를 직접 정독한 위에 재배치(추측이 아니라 검증된 자산 위의 포팅)** 한다.
> 검증 참조: `weapon/customers/models.py:76` Customer · `weapon/customers/calculate.py:245` calculate_total_analysis · `weapon/core/ocr/claude_parser.py:430/700` claude_parse/_add_coverage · `weapon/membership/credit.py:123` _check_and_consume · `weapon/insurances/models.py:53` AnalysisDetail. (vendoring 시 `weapon` → `inpa` 네임스페이스 리네임.)
> 정량 수치 중 베타 실측 전 가설은 모두 **(추정)** 라벨을 단다.

---

## 0. 가장 중요한 규칙 — 데이터 가시성 / 멀티테넌시 매트릭스

인파의 테넌트는 **설계사 1인**이다. 아래 표가 모든 엔티티의 스코프를 결정한다. 데이터모델·API 권한·화면 접근에 **일관 적용**한다.

| 스코프 | 의미 | 강제 수단 | owner FK |
|---|---|---|---|
| **공유** | 인증된 모든 설계사가 봄 | owner FK 없음. 인증만 요구 | 없음 |
| **비공개** | 작성자 + 관리자만 | owner FK + `OwnedQuerySetMixin` + `IsOwner`, 관리자 bypass | 있음 (CASCADE) |
| **소유자 전용** | 본인만 (관리자 bypass 운영 조회) | owner FK + `OwnedQuerySetMixin` + `IsOwner` | 있음 |
| **소유자 + 관리자** | 본인은 본인 것, 관리자는 전체 | owner FK + `OwnedQuerySetMixin`, 관리자 전체 우회 | 있음 |
| **공개읽기 + 관리자쓰기** | 비로그인 포함 읽기, 관리자만 쓰기 | 읽기 무인증, 쓰기 admin 게이트 | 없음 |

**스코프 배정 결과 (단일 진실원천):**

| 영역 | 엔티티 | 스코프 |
|---|---|---|
| 인증/계정 | `User`, `Profile`, `Token` | 소유자 전용 (본인 + 관리자 운영) |
| 게시판 SNS | `Post`, `Comment`, `PostLike`, `PostAttachment` | **공유** |
| 신고 | `Report` | 신고자 본인 조회 + 관리자 처리 |
| 공지/FAQ | `Notice`, `Faq` | **공유** (공개읽기 + 관리자쓰기) |
| 1:1 문의 | `Inquiry`, `InquiryReply` | **비공개** (본인 + 관리자) |
| 판촉물 카탈로그 | `PromotionSample`, `PromotionSampleImage` | **공유** (읽기) + 관리자쓰기 |
| 판촉물 주문 | `PromotionOrder`, `PromotionOrderStatusLog` | **소유자 + 관리자** |
| 고객/가족/병력 | `Customer`, `FamilyMember`, `CustomerMedicalHistory`, `CustomerTag` | 소유자 전용 |
| 동의 | `ConsentLog` | 소유자 전용 (`customer__owner` 경유) |
| 약관 버전 | `PolicyVersion` | 공개읽기 + 관리자쓰기 |
| 보험/계산 | `CustomerInsurance`, `CustomerInsuranceDetail` | 소유자 전용 (`customer__owner` 경유) |
| 담보 분류 트리 | `AnalysisCategory/SubCategory/Detail`, `ChartDetail`, `JobRiskCode` | 공유 (전역 표준 마스터) |
| 정규화 사전 | `NormalizationDict`, `UnmatchedLog` | 공유 (전역) + 관리자 검수 |
| 설계사 기준 | `planner_baseline` | 소유자 전용 |
| 캘린더/태스크 | `CalendarEvent`, `Task`, `WorkNote`, `ContactLog` | 소유자 전용 |
| 알림 | `Notification`, `ReminderRule` | 소유자 전용 |
| 북극성 계측 | `NorthStarEvent` | 관리자 전용 + 본인 sender 이벤트 |
| 요금제/사용량 | `Plan` (공개읽기) · `Subscription`, `UsageMeter` (소유자+관리자) | 혼합 (아래 §9) |
| 운영 로그 | `EmailLog`, `ClaudeApiLog` | 관리자 전용 (owner FK 없음) |

> **레드라인:** '공유' 5개 군(게시판·공지·FAQ·판촉물 카탈로그·담보표준)을 제외한 **모든 것은 owner 스코프**다. `request.user` 없는 데이터 접근은 코드리뷰 reject. 화이트리스트 예외 2개만: ① 관리자 bypass ② 공유뷰 `share_token`(비인증 고객 열람).

---

## 1. 한 장 요약 (투자자/디자이너용)

인파의 데이터 설계 한 문장: **"foliio가 이미 검증한 8케이스 보험료 엔진·증권 OCR·공유링크 모델을 그대로 가져오고, 그 위에 ① 병력 국외이전 동의를 물리적으로 강제하는 게이트(ConsentLog/consent_overseas_at), ② 쓸수록 두꺼워지는 보험사별 담보명 정규화 사전(NormalizationDict), ③ 설계사가 소유하는 보장 기준선(planner_baseline) — 단 세 개의 신규 자산 — 을 얹는다."**

```
   [재활용 ♻ 90% — weapon→inpa 리네임]      [신규 ✦ 10%]
 ┌────────────────────┐        ┌──────────────────────────────┐
 │ Customer (owner FK) │        │ consent_overseas_at (1필드)    │ ← AI 기능 물리 게이트
 │ CustomerInsurance   │        │ ConsentLog / PolicyVersion     │ ← 법무 감사추적
 │ AnalysisDetail 4계층 │  ─┐    │ NormalizationDict / UnmatchedLog│ ← 데이터 복리 해자
 │ calculate.py 8케이스 │   ├──► │ planner_baseline (준법 통제점)  │ ← 설계사 소유 기준
 │ share_token 공유뷰   │  ─┘    │ NorthStarEvent (귀속 계측)      │
 │ credit.py 크레딧     │        │ heatmap neutral/graded 모드     │
 └────────────────────┘        └──────────────────────────────┘
```

★ **준법 통제점 = planner_baseline.** `baseline_source == null`이면 분석 결과를 "부족/충분"으로 단정하지 않고 **neutral 강제**. 인파는 중개·권유하지 않으며, 보장 기준은 설계사가 소유한다.

---

## 2. 인증·계정 모델 (소유자 전용 — 이메일/비밀번호 전용)

> **카카오 OAuth 전면 제거 확정.** 흐름: 회원가입 → 이메일 인증 → 로그인 → 비밀번호 찾기(이메일 토큰 재설정). 가입 폼에 약관 동의 통합 수집.
> 상세 흐름·화면은 `dev/11-auth-onboarding.md`, 동의 법무는 `dev/16-legal-and-consent.md` 정본.

### 2.1 User (소유자 전용 — 본인 + 관리자 운영)

Django 기본 User를 그대로 쓰되 `email`을 로그인 식별자로 사용한다.

| 필드 | 타입 | 용도 |
|---|---|---|
| `id` | PK | |
| `email` | EmailField (unique) | **로그인 식별자** |
| `password` | str | PBKDF2 해시 (Django 기본) |
| `is_active` | bool | 이메일 인증 완료 전 `False`, 인증 시 `True` |
| `is_staff` | bool | Django admin 접근 |
| `date_joined` | DateTimeField (auto) | 가입 시각 |

관계: `Profile` OneToOne, `Token` OneToOne, `Customer.owner` 1:N, 그 외 owner 스코프 엔티티의 owner FK 대상.

> **인증/약관/휴면 상태 필드는 User가 아니라 `Profile`에 둔다** (Django User 비대화 방지, foliio 패턴 일치). devops 델타가 제안한 User 직속 인증필드(`is_email_verified`, `terms_agreed_at`, `email_verification_token_hash` 등)는 **Profile로 흡수 통합**한다 — 충돌 해소.

### 2.2 Profile (소유자 전용 — 본인 + 관리자) — 정본

`accounts/models.py`. User OneToOne. 인증 상태·약관 동의·위촉 자기신고·계정 상태(휴면)를 모두 담는다. legal-consent 델타(`dev/16` §5.4)를 정본으로 채택하고 다른 스트림 델타의 필드를 합집합 흡수했다.

```python
class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='profile')

    # ── 인증 (이메일/비밀번호 전용) ─────────────────────────
    email_verified_at     = models.DateTimeField(null=True)   # 이메일 인증 완료 시각 (User.is_active와 1:1)
    last_password_changed = models.DateTimeField(null=True)   # 비밀번호 변경 이력

    # ── 약관 동의 (가입 폼 통합 수집) ───────────────────────
    tos_agreed_at         = models.DateTimeField(null=True)   # 서비스 이용약관 (필수)
    tos_doc_version       = models.CharField(max_length=30, default='')   # 동의한 버전
    pp_agreed_at          = models.DateTimeField(null=True)   # 개인정보처리방침 (필수)
    pp_doc_version        = models.CharField(max_length=30, default='')
    marketing_agreed_at   = models.DateTimeField(null=True)   # 마케팅 수신 (선택, null=미동의)
    marketing_revoked_at  = models.DateTimeField(null=True)   # 마케팅 철회

    # ── 위촉 자기신고 · 온보딩 ──────────────────────────────
    affiliation           = models.CharField(max_length=100, null=True)   # 소속 원수사/GA
    agent_type            = models.SmallIntegerField(null=True)  # 1=생명/2=손해/3=교차
    license_self_declared = models.BooleanField(default=False)   # 위촉 자기신고
    license_no            = models.CharField(max_length=50, null=True)  # 검증 hook 대비
    career_years          = models.IntegerField(null=True)
    onboarding_completed_at = models.DateTimeField(null=True)    # null이면 /onboarding 강제 라우팅

    # ── 계정 상태 (휴면) ────────────────────────────────────
    is_admin              = models.BooleanField(default=False)   # 관리자 bypass 게이트
    is_dormant            = models.BooleanField(default=False)   # ★ 미들웨어 게이트 금지 — 재로그인 시 자동복구
    dormant_at            = models.DateTimeField(null=True)
    dormancy_warning_sent_at = models.DateTimeField(null=True)
    will_delete_at        = models.DateTimeField(null=True)

    # ── 북극성 귀속 ────────────────────────────────────────
    ref_code              = models.CharField(max_length=20, unique=True, null=True)  # Day1 컬럼, 발급 로직 Sprint0
```

> **레드라인:** `is_dormant`를 미들웨어/permission에서 차단하면 영구 락아웃. 복구는 로그인 API에서만. `agent_type`은 **1=생명/2=손해/3=교차** SmallInt로 통일 — auth 델타의 `life/nonlife/both` 문자열 enum은 표기상 별칭일 뿐, DB는 SmallInt.

### 2.3 이메일 인증 토큰 / 비밀번호 재설정 토큰

**별도 모델 없이 Django `PasswordResetTokenGenerator` 상속**을 정본으로 채택한다 (공통척추 델타). account/devops 델타가 제안한 별도 `EmailVerificationToken`/`PasswordResetToken` 모델은 **stateless 토큰 생성기로 대체** — 토큰 테이블 운영 부담 제거, foliio 패턴 일치.

| 토큰 | 구현 | TTL | 무효화 |
|---|---|---|---|
| 이메일 인증 | `PasswordResetTokenGenerator` 상속, pk 임베드 | `EMAIL_VERIFY_TOKEN_TTL_HOURS=24` (settings) | `is_active=True` 전환 시 자동 무효 |
| 비밀번호 재설정 | `PasswordResetTokenGenerator` 상속, pk 임베드 | `PASSWORD_RESET_TOKEN_TTL_HOURS=1` (settings) | 비밀번호 변경(해시 변경)으로 1회용 자동 보장 |

> `dev/11`은 서술상 `EmailVerificationToken`(UUID4 DB저장)을 언급하나, 통합 정본은 **생성기 상속 방식**으로 확정한다. 운영 단순성·1회용 자동보장이 결정 근거. (openGaps에 표기 — `dev/11` 서술과 동기화 필요.)

### 2.4 Token (DRF authtoken — 소유자 전용)

| 필드 | 타입 | 용도 |
|---|---|---|
| `key` | str(40) | 인증 토큰 |
| `user` | OneToOne User | |
| `created` | DateTimeField | |

로그인 성공 시 발급, 로그아웃 시 삭제. 베타 무기한, 정식 출시 전 만료 정책 재검토.

---

## 3. 고객 도메인 모델 (소유자 전용)

> foliio `weapon/customers/models.py` 재활용 + 인파 owner 스코프·동의 게이트·태그·공유 계측 추가.

### 3.1 Customer (◑ — owner FK + 신규 필드)

foliio `Customer`(`customers/models.py:76`)는 필요 필드를 이미 거의 다 보유한다. 인파는 **owner 스코프 + 동의 게이트 + 공유 계측 필드**를 추가한다.

**재활용 필드 (♻ 무변경):** `name`, `mobile_phone_number`, `birth_day`, `gender`(1남/2여 null), `job_code`(FK JobRiskCode SET_NULL), `share_token`(UUID unique), `share_expires_at`, `user_view_at`, `is_agree_term`, `color`, `memo`.

**신규/변경 필드 (✦):**

```python
class Customer(models.Model):
    # ── owner 스코프 (멀티테넌시 핵심) ──────────────────────
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='customers')   # ★ OwnedQuerySetMixin + IsOwner

    # ── 병력 = 민감정보 = AI 분석 게이트 ────────────────────
    consent_overseas_at = models.DateTimeField(null=True, blank=True, default=None)
    #   null = 미동의 → detect API 호출 전 확인, null이면 412 게이트

    # ── 공유/알림 계측 ─────────────────────────────────────
    share_sent_at  = models.DateTimeField(null=True)  # share_unread 알림 트리거용 발송 시각
    # share_expires_at(♻ 기존) = 공유 만료/회수 정책 hook

    tags = models.ManyToManyField('CustomerTag', blank=True, related_name='customers')
```

관계: `CustomerTag` M2M, `FamilyMember` 1:N, `CustomerMedicalHistory` 1:N(병력 민감정보), `CustomerInsurance` 1:N, `ConsentLog` 1:N(역관계 `consent_logs`).

> **설계 레드라인:** `is_agree_term`(일반 동의) 하나로 국외이전까지 덮지 않는다. 병력은 민감정보, Claude API는 미국(Anthropic, Inc.)으로 나간다. `consent_overseas_at`(스냅샷) + `ConsentLog`(불변 로그) 2층 분리가 detect 출시 게이트. **(법무 선결 — 1탭 vs 별도 동의서 확정.)**

### 3.2 CustomerTag (소유자 전용)

| 필드 | 타입 | 비고 |
|---|---|---|
| `id` | PK | |
| `owner` | FK User | ★ owner 스코프 |
| `label` | CharField | |
| `color` | CharField | |

`UNIQUE(owner, label)` — 설계사별 태그 네임스페이스 분리. Customer M2M.

### 3.3 FamilyMember (소유자 전용 — `customer__owner` 경유)

| 필드 | 타입 |
|---|---|
| `id` | PK |
| `customer` | FK Customer (CASCADE) |
| `relation` | str (관계) |
| `name` / `birth_day` / `gender` / `memo` | null 허용 |
| `created_at` / `updated_at` | DateTimeField |

owner 스코프는 `customer.owner`로 도출(직접 owner FK 없음, 부모 경유 강제).

### 3.4 CustomerMedicalHistory (소유자 전용 — `customer__owner` 경유, ♻)

foliio 무변경. **병력 = 민감정보 = 국외이전 동의 대상.** `ConsentLog(scope=overseas_medical)` + `Customer.consent_overseas_at`로 보호.

---

## 4. 동의·약관 모델 (법무 게이트)

> 정본은 `dev/16-legal-and-consent.md` §5. 기존 02 문서의 구버전 ConsentLog(`consent_type` SmallInt)는 **legal-consent 정본(`scope` CharField + `purpose`/`revoke_ip`)으로 대체**한다 — 충돌 해소.

### 4.1 ConsentLog (소유자 전용 — `customer__owner` 경유, append-only)

`consent_overseas_at`은 "지금 동의 상태인가"의 스냅샷, `ConsentLog`는 "언제·어떤 버전·누가·어디서"의 불변 감사 로그. 둘 다 필요.

```python
class ConsentLog(models.Model):
    SCOPE_CHOICES = (
        ('overseas_medical',  '병력 국외이전 (Claude API, 미국)'),
        ('medical_sensitive', '민감정보(병력) 처리'),
        ('marketing',         '마케팅 수신'),
    )
    customer    = models.ForeignKey('customers.Customer', on_delete=models.CASCADE,
                                    related_name='consent_logs')
    scope       = models.CharField(max_length=50, choices=SCOPE_CHOICES)
    purpose     = models.CharField(max_length=200, default='')  # 처리 목적 텍스트
    doc_version = models.CharField(max_length=30)               # "OVERSEAS-v1.0-20260619" → PolicyVersion.version 참조
    agreed_at   = models.DateTimeField(auto_now_add=True)       # 불변
    ip          = models.GenericIPAddressField(null=True)
    revoked_at  = models.DateTimeField(null=True, blank=True)   # null = 유효, 값=철회
    revoke_ip   = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'consent_log'
        ordering = ['-agreed_at']
        indexes = [models.Index(fields=['customer', 'scope'])]
```

> **append-only 원칙:** INSERT만 허용. UPDATE·DELETE 금지(감사 무결성). 철회는 `revoked_at` 기록(삭제 아님). 6요건 완비: 누가(`customer`)·언제(`agreed_at`)·무엇(`purpose`)·버전(`doc_version`)·어디서(`ip`)·철회(`revoked_at`).

### 4.2 PolicyVersion (공개읽기 + 관리자쓰기 — 독립 테이블)

약관 버전 식별의 단일 출처. `ConsentLog.doc_version`이 이 `version` 값을 참조.

```python
class PolicyVersion(models.Model):
    POLICY_TYPE = (('tos', '서비스 이용약관'), ('pp', '개인정보처리방침'), ('overseas', '병력 국외이전 동의서'))
    policy_type        = models.CharField(max_length=20, choices=POLICY_TYPE)
    version            = models.CharField(max_length=30, unique=True)  # "TOS-v1.0-20260619"
    content_hash       = models.CharField(max_length=64)              # SHA-256 (내용 변경 감지)
    effective_at       = models.DateTimeField()
    requires_reconsent = models.BooleanField(default=False)           # True = major 개정 → 재동의
    created_at         = models.DateTimeField(auto_now_add=True)
```

---

## 5. 담보 분류 트리 + 정규화 사전 (공유 전역 마스터)

> 전역 표준 — owner FK 없음. 모든 설계사가 같은 틀을 본다. 관리자만 시드·검수.

### 5.1 담보 분류 트리 (♻ 4계층 + 시드 100+)

foliio 4계층 관계형 모델(`insurances/models.py:12~85`) **모델 무변경, 시드만 30 → 100+ 확장**.

```
AnalysisCategory      (대분류 15+)   insurance_type(1생명/2손해)
   └─ AnalysisSubCategory (중분류)
        └─ AnalysisDetail (세부담보 leaf 100+)   chart_based_amount ← 기준선 hook
             └─ ChartDetail (차트 표시 단위)
```

부속: `JobRiskCode`(직업 위험등급, ♻), `ChartDetail`(차트 기준 금액, ♻). 전체 정의는 `dev/06-coverage-taxonomy-reference.md` §2·§3 정본.

> `AnalysisDetail.chart_based_amount`는 **표준 보장 기준선의 물리적 저장 위치**다. 단, 인파의 히트맵 판정 기준선은 §6의 `planner_baseline`(설계사 소유)이 **상위 권위**다 — 준법 통제점이 코드/시드가 아니라 설계사에게 있다는 원칙.

### 5.2 NormalizationDict (✦ 신규 — 데이터 복리 해자)

보험사별 담보명 → 표준 담보(`AnalysisDetail`) 정규화 사전. `_add_coverage` 매칭 단계에 끼운다.

```python
class NormalizationDict(models.Model):
    SOURCE = ((1, 'seed'), (2, 'ocr_learned'), (3, 'admin_verified'))
    std_detail  = models.ForeignKey('AnalysisDetail', on_delete=models.CASCADE, related_name='aliases')
    company     = models.SmallIntegerField()                       # 보험사 코드
    raw_name    = models.CharField(max_length=120, db_index=True)  # "암진단급부금"
    source      = models.SmallIntegerField(choices=SOURCE, default=1)
    confidence  = models.SmallIntegerField(default=100)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    hit_count   = models.IntegerField(default=0)                   # ★ 매칭마다 ++ (데이터 복리)
    created_at  = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['company', 'raw_name'], name='uniq_norm_company_rawname')]
        indexes = [models.Index(fields=['raw_name'])]
```

### 5.3 UnmatchedLog (✦ 신규 — 학습 플라이휠)

```python
class UnmatchedLog(models.Model):
    company    = models.SmallIntegerField()
    raw_name   = models.CharField(max_length=120, db_index=True)
    occurrence = models.IntegerField(default=1)
    sample_ctx = models.CharField(max_length=300, default='')
    resolved   = models.BooleanField(default=False)   # admin 매핑 완료 여부
    created_at = models.DateTimeField(auto_now_add=True)
```

루프: OCR `raw_name` → `NormalizationDict.get` → 매칭 O면 `hit_count++` / 매칭 X면 `UnmatchedLog` 적재 → admin 1탭 매핑 → `NormalizationDict` 영구 추가(source=admin_verified) → 다음 OCR부터 자동 매칭(복리).

> **운영 미결:** 자동승격 임계(동일 raw_name 5회+ → `ocr_learned` 자동) 허용 여부. 자동매핑 오류 = 비교안내서 거짓 = §97 위반 리스크. 베타까지 **`admin_verified`만 매칭에 사용**(보수적 기본값).

---

## 6. 설계사 기준선 (소유자 전용 — ★ 준법 통제점)

> `planner_baseline` = 설계사가 소유하는 보장 기준. 인파는 중개·권유하지 않으며, "부족/충분" 판정 권위는 설계사에게 있다.

```python
class planner_baseline(models.Model):   # 표기상 소문자, 실 클래스명 PlannerBaseline
    owner          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)  # ★ owner 스코프
    coverage_key   = models.CharField(db_index=True)   # 표준 담보 키
    product_group  = models.SmallIntegerField()        # 1=생명/2=손해 등
    age_band       = models.CharField()                # 나이대 밴드
    gender         = models.SmallIntegerField(null=True)
    recommend_min  = models.DecimalField(null=True)
    recommend_max  = models.DecimalField(null=True)
    unit           = models.SmallIntegerField()        # 금액 단위
    source         = models.CharField(null=True)       # planner | preset:<id> | null
    preset_origin  = models.CharField(null=True)
    is_active      = models.BooleanField(default=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['owner', 'coverage_key', 'product_group', 'age_band', 'gender'],
            name='uniq_baseline_scope')]
```

> ★ **neutral 강제 규칙:** 히트맵·분석에서 해당 `coverage_key`의 `planner_baseline`이 없거나 `source==null`이면 그 담보는 **부족/충분으로 단정 금지 → neutral**(보유여부 0원만 회색 표기). 상세는 `dev/10-planner-criteria.md`.

---

## 7. 보험·계산 모델 (소유자 전용 — ♻ 8케이스 엔진 무변경)

`CustomerInsurance`(`insurances/models.py:194`) + `CustomerInsuranceDetail` + `calculate.py`는 **한 줄도 건드리지 않는다.** foliio 8케이스 골든테스트(`test_premium_calculation_8cases.py`)를 회귀 가드로 그대로 가져온다. owner 스코프는 `customer__owner` 경유.

| 필드 | 값 | 인파 용도 |
|---|---|---|
| `portfolio_type` | 0=템플릿/1=기존가입/2=제안 | 갈아타기 비교 좌(1)·우(2) 분기 |
| `insurance_type` | 1=생명/2=손해 | 생손보 분리 계산 |
| `monthly_{premiums,assurance,renewal,non_renewal,earned}_premium` | — | 비용요약 표 |
| `case_list` → `CustomerInsuranceDetail` | `calculate()` (numpy_financial.fv) | 케이스별 미래가치 |

> **음수 guard 보존:** `monthly_non_renewal_premium = max(0, assurance − renewal)` (foliio 2026-05-29 fix). 8케이스 변경 시 골든테스트 재실행 원칙 인파에도 동일.

---

## 8. 업무·일정·접점 모델 (소유자 전용)

> core-product 스트림. 모두 owner FK + `OwnedQuerySetMixin` + `IsOwner`. **공유뷰 물리 부재**(설계사 사적 업무 데이터).

### 8.1 CalendarEvent

| 필드 | 비고 |
|---|---|
| `owner` FK User | ★ 스코프 |
| `customer_id` (nullable) | 고객 연결 |
| `event_type` | expiry / birthday / consult / task |
| `source_type` | auto / manual |
| `title`, `date`(KST), `time`(null), `all_day` | |
| `linked_task_id`(null) | Task 1:1 optional |
| `origin_ref` JSON, `memo` | |
| `created_at`, `updated_at` | |

### 8.2 Task

`owner` FK · `customer_id`(null) · `title` · `due_date` · `done` · `done_at` · `snoozed_until` · `priority` · `created_at`/`updated_at`. CalendarEvent 1:1 optional(`linked_task_id`).

### 8.3 WorkNote

`owner` FK · `customer_id`(null) · `body` · `pinned` · `created_at`/`updated_at`. Customer N:1 optional.

### 8.4 ContactLog

`owner` FK · `customer_id`(required) · `channel`(call/sms/kakao/meet/email) · `direction`(outbound/inbound) · `outcome`(connected/no_answer/scheduled/declined) · `summary` · `occurred_at` · `next_action_task_id`(null) · `created_at`. Customer N:1, Task optional(next_action).

---

## 9. 알림·리마인더 모델 (소유자 전용)

> notifications 스트림. owner FK + `OwnedQuerySetMixin` + `IsOwner`, 관리자 bypass.

### 9.1 Notification

| 필드 | 비고 |
|---|---|
| `owner_id` FK User | ★ 스코프 |
| `notif_type` | expiry_soon / birthday_soon / consult_reminder / task_due / share_unread |
| `title`, `body`, `target_date`(date) | |
| `customer_id` FK (nullable), `calendar_event_id` FK (nullable) | |
| `is_read`(default False), `sent_email`(default False) | |
| `created_at` | |

> foliio `Notification` 재활용 + 인파 신규 type. cron `watchdog`(만기·갱신·생일 일배치) → 액션큐.

### 9.2 ReminderRule

`owner_id` FK · `rule_type`(Notification.notif_type와 1:1) · `days_before`(0~90) · `enabled`(default True) · `email_enabled`(default False) · `updated_at`.

> `Customer.share_sent_at`(§3.1)이 `share_unread` 트리거 입력.

---

## 10. 게시판·커뮤니티 모델

> boards 스트림. **게시판 SNS·공지·FAQ = 공유**(owner FK 없음), **1:1 문의 = 비공개**(owner FK), **신고 = 신고자+관리자**.
> 충돌 해소: admin 델타의 `Announcement`/`FAQ`/`BoardReport`는 boards 델타의 `Notice`/`Faq`/`Report`와 **동일 개념 중복** → boards 명칭을 정본으로 채택, 관리자 콘솔(`dev/19`)은 같은 테이블을 관리한다.

### 10.1 Post (공유)

`id` · `author` FK(User SET_NULL) · `title`(200) · `body` · `is_hidden` · `is_deleted` · `view_count` · `like_count`(캐시) · `comment_count`(캐시) · `pinned` · `category`(30 null) · `created_at`/`updated_at`.
가시성: 인증 설계사 전원 읽기/작성, **본인만** 수정/삭제, 관리자 전체 수정/삭제/숨김. 관계: Post →< Comment / PostLike / PostAttachment / Report.

### 10.2 Comment (공유)

`id` · `post` FK(CASCADE) · `author` FK(User SET_NULL) · `parent` FK(self null, 1단계 대댓글) · `body` · `is_hidden` · `is_deleted` · `created_at`/`updated_at`.

### 10.3 PostLike (공유)

`post` FK(CASCADE) · `user` FK(CASCADE) · `created_at` · `UNIQUE(post, user)`. 본인 생성/취소, 카운트 전체 노출.

### 10.4 PostAttachment (공유)

`post` FK(CASCADE) · `uploader` FK(User SET_NULL) · `file_url`(500) · `file_name`(255) · `file_size` · `mime_type`(100) · `created_at`. 본인 글에만 업로드, 관리자 삭제.

### 10.5 Report (신고자 본인 조회 + 관리자 처리)

`id` · `reporter` FK(User SET_NULL) · `content_type`(post|comment) · `object_id` · `reason`(30) · `detail`(null) · `status`(pending|resolved|dismissed) · `resolved_by` FK(User null) · `resolved_at`(null) · `created_at` · `UNIQUE(reporter, content_type, object_id)`.

### 10.6 Notice (공유 — 공개읽기 + 관리자쓰기)

`id` · `author` FK(User SET_NULL admin) · `title`(200) · `body` · `is_pinned` · `is_published` · `published_at`(null) · `created_at`/`updated_at`.

### 10.7 Faq (공유 — 공개읽기 + 관리자쓰기)

`id` · `author` FK(User SET_NULL admin) · `category`(50) · `question`(300) · `answer` · `order` · `is_published` · `created_at`/`updated_at`.

### 10.8 Inquiry (비공개 — 소유자 + 관리자)

`id` · `owner` FK(User CASCADE) · `category`(30) · `title`(200) · `body` · `status`(open|answered|closed) · `created_at`/`updated_at`.
가시성: 본인만 읽기/작성, 관리자 전체 읽기/답변. `OwnedQuerySetMixin` + `IsOwner`. 관계: Inquiry →< InquiryReply.

### 10.9 InquiryReply (Inquiry 소유자 읽기 + 관리자 작성)

`id` · `inquiry` FK(CASCADE) · `author` FK(User SET_NULL) · `body` · `created_at`/`updated_at`.

---

## 11. 판촉물 모델

> 판촉물 스트림. **카탈로그 = 공유**(읽기) + 관리자쓰기, **주문 = 소유자 + 관리자**.

### 11.1 PromotionSample (공유 — 읽기 / 관리자 쓰기)

`id` · `name`(100) · `category`(30) · `description` · `is_available`(default True) · `form_fields`(JSON — 동적 폼 필드 정의 배열) · `sort_order` · `created_at`/`updated_at`. 관계: PromotionSampleImage(1:N, related_name=images).

### 11.2 PromotionSampleImage (공유 — PromotionSample 종속)

`id` · `sample` FK(CASCADE) · `image_url`(S3) · `is_primary` · `sort_order`.

### 11.3 PromotionOrder (소유자 + 관리자)

`id` · `owner` FK(User SET_NULL — 소유 설계사) · `sample` FK(SET_NULL) · `form_response`(JSON — 키=form_fields[].key) · `status`(pending/reviewing/producing/shipped/done/cancelled 상태머신) · `admin_note`(설계사에게도 노출) · `tracking_number` · `carrier` · `created_at`/`updated_at`. `OwnedQuerySetMixin` 적용. 관계: PromotionOrderStatusLog(1:N, related_name=status_logs).

> admin 델타의 `PromotionOrder`(items JSON·delivery_address·status 1-6)는 **판촉물 스트림 정본으로 통합** — `form_response` JSON이 items/배송지를 모두 흡수, status는 문자열 상태머신으로 통일. 중복 제거.

### 11.4 PromotionOrderStatusLog (소유자 본인 주문 로그 + 관리자)

`id` · `order` FK(CASCADE) · `to_status` · `changed_by` FK(User SET_NULL — 관리자) · `changed_at`(auto_now_add) · `note`.

---

## 12. 요금제·사용량 모델

> billing 스트림. **Plan = 공개읽기 / 관리자쓰기**, **Subscription·UsageMeter = 소유자 + 관리자**.

### 12.1 Plan (공개읽기 / 관리자쓰기)

`code`(unique: free|plus) · `display_name` · `price_krw` · `limit_ocr_detect`(null=무제한) · `limit_ai_compare`(null) · `limit_ai_analysis`(null) · `limit_ai_message`(null) · `is_active` · `created_at`/`updated_at`. Plan 1 ← N Subscription.

### 12.2 Subscription (소유자 + 관리자)

`user` OneToOne(User) · `plan` FK(Plan) · `status`(active|cancelled|expired|trial) · `started_at` · `expires_at`(null=무기한) · `cancelled_at` · `pg_subscription_id`(MVP 미사용 hook). `OwnedQuerySetMixin` + `IsOwner`.

### 12.3 UsageMeter (소유자 본인 사용량 + 관리자 전체)

`user` FK(User) · `action`(ocr_detect|ai_compare|ai_analysis|ai_message) · `year_month`(YYYY-MM, 월별 lazy reset) · `count` · `updated_at` · `UNIQUE(user, action, year_month)`.

> foliio `credit.py:_check_and_consume`의 `kind`에 `ai_credit`를 더한 것의 영속화. 베타 `FREE_TIER_UNLIMITED=True`로 전부 우회, 정식 출시 시 `False` flip. `limit=null`은 **무제한 sentinel**(`is_unlimited`로 판별, `remaining==0` 아님).

---

## 13. 북극성 계측 모델

### 13.1 NorthStarEvent (관리자 전용 + 본인 sender 이벤트)

```python
class NorthStarEvent(models.Model):
    id          = models.BigAutoField(primary_key=True)
    event_type  = models.SmallIntegerField()   # 1~6 (아래 이벤트 스펙)
    share_token = models.UUIDField(null=True)
    sender_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    ref_code    = models.CharField(null=True)
    channel     = models.CharField()
    viewer_fp   = models.CharField(null=True)   # 열람자 핑거프린트(비인증)
    meta        = models.JSONField(default=dict)
    created_at  = models.DateTimeField(auto_now_add=True)   # UTC
```

이벤트(`event_type` 1~6): `ocr_upload / analysis_complete / share_link_create / share_clipboard_copy / share_view / referral_attributed`.

> 귀속 계측은 **사후 복원 불가** → 첫 배포 전 이벤트 스펙 확정 필수. 계측 인프라 Day1, 캠페인 활성화 Phase2.

---

## 14. 운영 로그 모델 (관리자 전용 — owner FK 없음, 내부 운영용)

> devops 스트림. 설계사 접근 불가. 관리자 콘솔(`dev/19`)·비용 대시보드 입력.

### 14.1 EmailLog (관리자 전용)

`id` · `recipient` · `email_type`(verification|password_reset|expiry_notify) · `sent_at` · `resend_message_id`(null) · `status`(sent|bounced|failed). 이메일 발송 감사 로그.

### 14.2 ClaudeApiLog (관리자 전용)

`id` · `purpose`(ocr_parse|compare_guide|message_gen 등) · `model` · `input_tokens` · `output_tokens` · `cache_read_input_tokens`(default 0) · `customer_id` FK(null) · `created_at`. Claude API 호출당 비용 로깅, 월 예산 캡 집계. **설계사 본인 조회 불가**, 관리자 전체 조회.

---

## 15. 주요 API 계약

엔드포인트 출처: `insurances/views.py:detect` + `customers/views.py:analysis/compare` 재활용 + 신규 heatmap/guardrail/message. base path `/api/v1/`. 인증·온보딩 API는 `dev/11`, 게시판/판촉물/관리자 API는 각 도메인 정본 참조.

### 15.0 핵심 API 지도

| Method · Path | 출처 | credit | 게이트 |
|---|---|---|---|
| `POST /accounts/register/` | ✦ | — | 약관 동의 통합 수집 → User(is_active=False) + 인증메일 |
| `GET /accounts/verify-email/?token=` | ✦ | — | is_active=True (TTL 24h) |
| `POST /accounts/login/` | ✦ | — | 비밀번호 검증 + is_dormant 복구 + Token 발급 |
| `POST /accounts/password-reset/request/` | ✦ | — | 무조건 200 (이메일 노출 방지) |
| `POST /accounts/password-reset/confirm/` | ✦ | — | 토큰 1회용(TTL 1h) |
| `POST /insurance/detect/` | foliio | `ai_credit` | **국외이전 미동의 412** |
| `POST /insurance/detect_batch/` | ✦ | N×`ai_credit` | 동의 412 / 부분실패 허용 |
| `GET /customer/:id/analysis/` | foliio | — | 본인/공유토큰 |
| `GET /customer/:id/heatmap/` | ✦ | — | **planner_baseline 없으면 neutral 강제** |
| `GET /customer/:id/compare/` | foliio + ◑ | — | **§97 6항목 미완 시 발행 하드블록** |
| `POST /ai/message/` | ✦ | `ai_credit` | 클립보드만 (자동발송 X) |
| `POST /ai/guardrail_check/` | ✦ | — | 보험업법 룰셋 판정 |
| `GET /customer/:id/share/analysis/?token=&ref=` | foliio | — | **열람 이벤트 계측 (북극성)** |

---

### 15.1 `POST /insurance/detect/` — 증권 업로드 → OCR (국외이전 게이트)

증권 PDF 업로드 → 텍스트 추출 → Claude 파싱 → **정규화 사전 결합** → 표준담보 매핑.
파이프라인: `extract_text_from_pdf`(pdfplumber→PyMuPDF 폴백, 암호화 `authenticate`) → 한화 fast-path → `claude_parse`(`claude_parser.py:430`) → regex fallback.

**게이트 (진입 시점):**
```python
if customer.consent_overseas_at is None:
    return Response(status=412, data={
        "reason": "CONSENT_OVERSEAS_REQUIRED",
        "consent_url": f"/check/{customer.share_token}",
    })
```

**Response 200** (정규화 적용):
```json
{
  "insurance_company": "삼성생명", "product_name": "삼성생명 종합보장보험", "insurance_type": 1,
  "coverages": [
    { "raw_name": "암진단급부금", "std_detail_id": 41, "std_detail_name": "일반암진단비",
      "match_source": "admin_verified", "assurance_amount": 30000000,
      "monthly_premium": 12000, "payment_type": 1, "warranty_type": 2 }
  ],
  "unmatched": [ { "raw_name": "특정고도질병진단비", "logged": true } ]
}
```

체크리스트: 매칭 담보는 `std_detail_id`+`match_source` 동반 / 미매칭은 `unmatched[]`+`UnmatchedLog` 적재 / OCR 추출률 ≥ 85% / `ai_credit` 차감(베타 우회).

---

### 15.2 `POST /insurance/detect_batch/` — 다건 일괄 OCR (M1)

N장 일괄 큐잉, **부분 실패 허용**. 야간 배치는 Claude Batches API(50% 할인).

**Response 207** (Multi-Status):
```json
{
  "succeeded": [ { "file": "a.pdf", "insurance_id": 501, "coverages": 12 } ],
  "partial_failed": [
    { "file": "b.pdf", "reason": "PDF_ENCRYPTED_NO_PASSWORD" },
    { "file": "c.pdf", "reason": "OCR_LOW_CONFIDENCE", "extracted": 3 }
  ]
}
```
원칙: 한 장 실패가 전체를 죽이지 않는다(`partial_failed[]`).

---

### 15.3 `GET /customer/:id/analysis/` — 분석 집계 (♻ 무변경)

`calculate_total_analysis(birth_day, case_list, chart_list, insurance_list)`(`calculate.py:245`) 출력을 **그대로** 반환. BE 무변경. `non_renewal_old_list`/`renewal_old_list`는 **항상 10칸 고정**, 연속 보장구간 도출은 **FE에서**.

---

### 15.4 `GET /customer/:id/heatmap/` — 담보 한눈표 3색 (M3) ★ neutral 통제점

15+ 카테고리 × 세부담보 그리드를 충분/부족/없음 3색으로. 실제 보장액 vs `planner_baseline`(설계사 소유) 비교.

**Response 200**:
```json
{
  "baseline_source": null,
  "mode": "neutral",
  "categories": [
    { "category": "진단비-암", "details": [
        { "detail": "일반암진단비", "actual_amount": 30000000, "std_baseline": 50000000, "status": "short" },
        { "detail": "고액암진단비", "actual_amount": 0, "std_baseline": 30000000, "status": "none" }
    ] }
  ]
}
```

**status 판정 (★ planner_baseline 게이트):**
```python
def heatmap_status(actual, baseline, baseline_source):
    if baseline_source is None:                  # planner_baseline 없음/source==null
        return "none" if actual == 0 else "neutral"   # 보유여부만 회색, 부족/충분 단정 금지
    if actual == 0:                  return "none"     # 🔴 없음
    if actual < baseline * 0.7:      return "short"    # 🟡 부족
    return "enough"                                    # 🟢 충분
```

> ★ **중립 모드 = 준법 안전장치.** `planner_baseline`(설계사가 직접 소유·설정한 기준)이 없으면 `enough/short` 판정 보류, `none`(0원 보유여부)만 회색 중립. 인파는 기준을 제시하지 않는다 — 설계사가 소유한다. 상세 `dev/10`.

---

### 15.5 `GET /customer/:id/compare/` — 갈아타기 비교안내서 (§97)

foliio 기존가입(`portfolio_type=1`) vs 제안(`portfolio_type=2`) 매트릭스 + **§97 비교안내 정확요건**.

**Response 200**:
```json
{
  "existing": { "monthly_premiums": 152000, "case_list": [] },
  "proposal": { "monthly_premiums": 138000, "case_list": [] },
  "switch_warnings": [
    { "type": "cancellation_loss", "label": "해지환급금 손실", "amount": 1200000 },
    { "type": "exemption_reset", "label": "면책기간 리셋", "detail": "암 90일 재적용" },
    { "type": "rate_change", "label": "예정이율 하락", "from": 2.5, "to": 1.8 },
    { "type": "renewal_conversion", "label": "비갱신→갱신 전환" }
  ],
  "compliance_checklist": { "items_required": 6, "items_completed": 4, "publishable": false },
  "disclaimer": "AI 초안 · 최종책임 설계사"
}
```

> **§97 하드블록:** `publishable == false`면 발행 불가(필수 6항목 누락률 0% 강제). 불리점 자동 경고 상시 노출. **"심의완료/안전 배지" 절대 금지**, 면책 카피만(`disclaimer` 고정).

---

### 15.6 `POST /ai/message/` — AI 카톡 메시지 (M6, 클립보드만)

목적 enum 칩 → Claude 생성 → `ai_guardrail` 후처리 → **클립보드 복사만**.

**Request**: `{ "customer_id": 123, "purpose": "renewal", "tone": "friendly" }`
`purpose ∈ {needs, renewal, birthday, gap, referral, remind}`

**Response 200**:
```json
{ "message": "○○님, 가입하신 암보험 만기가 D-30 남았어요...",
  "guardrail": { "passed": true, "flags": [] },
  "delivery": "clipboard" }
```

> 정직성 레드라인: `delivery`는 항상 `clipboard`. 원탭 자동발송 사칭 금지(카카오 불가). 신뢰 KPI는 `share_view`(서버 측정).

---

### 15.7 `POST /ai/guardrail_check/` — 보험업법 룰셋 판정 (M5)

foliio `content_filter.py`(PII 정규식) 재사용 → `ai_guardrail.py` 보험업법 룰셋 신규.

**Response 200**:
```json
{ "passed": false, "flags": [
  { "rule": "guarantee_return", "match": "수익 보장", "severity": "block" },
  { "rule": "absolute_term", "match": "무조건", "severity": "warn" }
]}
```
룰: 단정표현 / 수익보장 / 비교과장. `severity=block`이면 출력 차단.

---

### 15.8 `GET /customer/:id/share/analysis/?token=&ref=` — 공유 열람 + 계측

foliio 공유뷰(글로벌헤더 숨김) 재활용 + **북극성 열람 이벤트 + 리퍼럴 귀속**.
동작: 공개 열람(`share_token` 검증, 인증 불필요) / `share_view` 이벤트 적재(`NorthStarEvent`) / `?ref=` 존재 시 `referral_attributed` 귀속(`Profile.ref_code`).

---

## 16. 크레딧 / 한도 집행 (UsageMeter + credit.py)

foliio `credit.py:_check_and_consume(user, kind)`는 `kind ∈ {customer, insurance, promotion}`을 지원. 인파는 **`ai_credit`(AI 호출 차감)을 추가**한다.

| 동작 | credit kind | 무료(free) | Plus(plus) |
|---|---|---|---|
| 증권 OCR 등록 | `insurance` / `ocr_detect` | 허용(제한) | 허용 |
| 분석/히트맵 조회 | — (무차감) | 허용 | 허용 |
| 비교안내서 생성 | `ai_credit` / `ai_compare` | 1건 체험 | 복수 |
| AI 메시지 생성 | `ai_credit` / `ai_message` | ✗ | 허용 |

**402 응답 shape:**
```json
{ "detail": "이번 달 AI 한도(N건)를 모두 사용했어요.", "code": "credit_exhausted",
  "kind": "ai", "membership": "free", "limit": 1, "used": 1 }
```
→ FE는 `UpgradeGuideModal`. 베타 `FREE_TIER_UNLIMITED=True` 우회. 한도 숫자는 **베타 90일 실측 후 토큰화** (전부 **(추정)** 유지).

---

## 17. 마이그레이션 & 시드 순서

```bash
# 1. 모델 마이그레이션 (로컬: settings.local)
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py makemigrations
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py migrate

# 2. 담보 트리 + 정규화 사전 시드 (30 → 100+)
python manage.py seed_taxonomy

# 3. 요금제 시드 (free/plus) + 약관 3종 PolicyVersion 시드
python manage.py loadinitialplans
python manage.py seed_policy_versions   # TOS/PP/OVERSEAS 초기 버전
```

체크리스트 — 데이터 모델 PR 완료 정의:
- [ ] `User.email` unique 로그인 + `Profile` 인증/약관/휴면/위촉 필드 마이그레이션
- [ ] 토큰 생성기(이메일인증 24h / 비번재설정 1h) 동작 — 별도 토큰 테이블 없음
- [ ] `Customer.owner` FK + `OwnedQuerySetMixin`/`IsOwner` 강제 (타 설계사 데이터 403)
- [ ] `consent_overseas_at` 마이그레이션 + detect 412 게이트 동작
- [ ] `ConsentLog` 6요건 + append-only + `PolicyVersion` 3종 시드
- [ ] `NormalizationDict` UNIQUE(company, raw_name) + `hit_count` 증가 / `UnmatchedLog` → admin 매핑 루프
- [ ] `planner_baseline` 없을 때 heatmap `neutral` 강제 단위테스트
- [ ] `seed_taxonomy` 100+ 담보 적재(`AnalysisDetail.count() ≥ 100`)
- [ ] foliio 8케이스 골든테스트 회귀 통과
- [ ] 공유 엔티티(Post/Comment/Notice/Faq/PromotionSample) owner FK 부재 + 인증 읽기 검증
- [ ] 소유자+관리자 엔티티(PromotionOrder/Subscription/UsageMeter) 관리자 전체 우회 검증

---

## 18. 미결 항목 (법무·운영 게이트 + 통합 시 정한 기본값)

| ID | 항목 | 막는 것 | 기본 가정(이번 통합에서 확정) |
|---|---|---|---|
| **Q1** | planner_baseline / 표준 기준선 출처·권위 | heatmap `graded` 모드 | `planner_baseline` 없으면 `neutral`(none만), 설계사 소유 원칙 |
| **Q2** | 국외이전 동의 1탭 vs 별도 동의서 | **detect API 전체** | 별도 필드(`consent_overseas_at`)+ConsentLog 분리 |
| **Q3** | §97 비교안내 6항목 법적 확정 | compare 발행 하드블록 | 6항목 미완 시 `publishable=false` |
| **Q4** | 셀프진단 제3자 동의 충분성 | `consent_type=selfdiag` 동선 | share_token 만료·회수 정책 동반 |
| 운영 | 정규화 사전 자동승격 임계 | `ocr_learned` 자동매칭 | 베타까지 `admin_verified`만 사용 |
| 가격 | `ai_credit` 무료 한도 숫자 | 전환율 레버 | 베타 90일 실측 후 토큰화 (추정 유지) |
| 토큰 | 이메일/비번 토큰 구현체 | `dev/11` 서술 동기화 | 생성기 상속 채택(별도 테이블 없음) — `dev/11`의 `EmailVerificationToken` 서술 동기화 필요 |
| 명칭 | admin 델타 `Announcement/FAQ/PromotionOrder` 중복 | 표준 명칭 | boards/판촉물 명칭(`Notice/Faq/PromotionOrder`) 정본, admin은 동일 테이블 관리 |
| 클래스명 | `planner_baseline` 표기 | ORM 클래스 규약 | 실 클래스 `PlannerBaseline`, db_table=`planner_baseline` |

> **fallback 원칙:** 컴플라이언스 게이트가 막히면 중립 기능부터 선출시 — OCR(M1) → 히트맵 `neutral`(M3) → 정규화(M2). 비교안내서·메시지는 §97·동의 확정 후 오픈.

---

*본 문서는 인파(Inpa) 개발 정본 `dev/02-data-model-and-api.md`(병렬 스트림 델타 직렬 통합판). 아키텍처는 `dev/01`, 포팅 지점은 `dev/03`, 빌드 순서는 `dev/04`, 인증/온보딩 `dev/11`, 법무/동의 `dev/16`, 기준선 `dev/10`, 게시판 `dev/17`, 관리자 `dev/19`, 알림 `dev/22`, 판촉물 `dev/21`, 요금제 `dev/23` 참조.*
