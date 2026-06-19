# 법무·동의 설계 (Legal & Consent)

> 인파(Inpa) 개발 정본 · `docs/dev/16-legal-and-consent.md`
> 상위 정본: `dev/09`(컴플라이언스 절대원칙) · `dev/14`(카피 룰) · `dev/11`(인증·온보딩)
> 본 문서 위상: 이용약관·개인정보처리방침 초안 + 동의 분류·저장·흐름·버전관리를 **단일 정본**으로 정의한다.
> 작성: CPO=CTO 보수적 자체처리. 외부 법무자문 없음. 유료 정식출시 전 반드시 법무 재검토.
> 날짜: 2026-06-19

---

## 0. 한 줄 원칙 & dev/09·14와의 정렬

**인파는 보험을 중개·권유하지 않는다. 인파는 도구다.** 이 전제가 법무 설계 전체를 결정한다.

| dev/09 원칙 | 법무 설계 반영 |
|---|---|
| 판정·권유 금지 | 약관 "인파는 보장 적정성을 판정하지 않습니다" 명문화 |
| 인파는 도구, 설계사가 판단 주체 | 서비스 이용 조건 = 유효한 보험모집 자격 보유자 |
| AI 생성물 면책 ("AI 초안·최종책임 설계사") | 개인정보처리방침 AI 처리 항목에 동일 면책 고정 |
| 원탭 자동발송 없음 | 약관 제공 방식 조항에 "클립보드/앱 이동"까지만 명시 |
| graded/§97 기능 법무 선결 | 각 기능 게이트를 약관 "서비스 제공 범위"로 연동 |

---

## 1. 약관 구조 & 버전 관리

### 1.1 문서 목록

인파가 운영하는 법무 문서는 **3종**이다.

| ID | 문서명 | 대상 | 위치 |
|---|---|---|---|
| `TOS-v1` | 서비스 이용약관 | 설계사(서비스 이용자) | `/legal/terms` |
| `PP-v1` | 개인정보처리방침 | 설계사 + 고객(정보주체) | `/legal/privacy` |
| `OVERSEAS-v1` | 병력 국외이전 동의서 | 고객(정보주체) — 설계사가 대리 수집 | 분석 기능 진입 시 팝업/화면 |

> 세 문서의 버전은 **독립 관리**한다. 이용약관 개정이 개인정보처리방침을 자동 개정하지 않는다.

### 1.2 버전 규칙

```
형식: <문서ID>-v<major>.<minor>-<YYYYMMDD>
예시: TOS-v1.0-20260619

major: 정보주체 권리·수집 범위·국외이전 목적지 변경 → 재동의 필요
minor: 문구 정정·연락처 변경 → 공지 후 30일 경과 시 자동 적용
```

- 개정 시 `PolicyVersion` 테이블에 신규 행 추가(하단 §5.3).
- 재동의 필요 개정(major): 다음 로그인 시 재동의 레이어 노출. 미동의 = 서비스 이용 중단.
- 약관 개정 이력은 `/legal/terms/history`에 공개 보관(삭제 금지).

---

## 2. 서비스 이용약관 (TOS-v1) 초안

> 이 초안은 한국 전자상거래법·약관규제법·개인정보보호법을 참고해 작성했다.
> 보수적 자체처리 기준이며 유료 정식출시 전 법무 전문가 검토 필수.

---

### 제1조 목적

이 약관은 인파(이하 "인파" 또는 "서비스")를 운영하는 **[법인명 미확정]** (이하 "회사")이 제공하는 보험설계사용 AI 영업지원 웹 애플리케이션 서비스의 이용에 관한 조건과 절차를 규정함을 목적으로 합니다.

> **개발 갭:** 법인명, 대표자명, 사업자등록번호, 연락처(이메일·전화)가 확정되지 않았습니다. 정식출시 전 반드시 기재해야 합니다. → openGaps 참고.

### 제2조 이용자 자격 및 가입

1. 서비스는 **유효한 보험모집 자격을 보유한 보험설계사(원수사·GA 위촉직 포함)** 를 대상으로 합니다.
2. 이용자는 가입 시 본인이 유효한 보험모집 자격(생명보험·손해보험·제3보험)을 보유하고 있음을 자기신고(self-attestation)로 확인합니다.
3. 자격 미보유자가 허위 신고 후 이용한 경우, 이로 인한 법적·민사적 책임은 이용자 본인에게 있습니다.
4. 가입은 **이메일·비밀번호** 방식으로만 진행합니다. 가입 완료 전 이메일 인증이 필요합니다.

### 제3조 서비스 제공 범위 및 제한

1. 회사는 다음 기능을 제공합니다:
   - 고객 정보 및 보험증권 등록·관리
   - 보험증권 OCR 분석 및 담보 정규화
   - 담보 현황 시각화(히트맵)
   - 보장 현황 공유(고객 열람 링크)
   - 커뮤니티(게시판·공지)·판촉물 관리
2. **회사는 보험 중개·권유 행위를 하지 않습니다.** 보장 적정성의 판단·권유는 라이선스를 보유한 이용자(설계사)의 책임입니다.
3. AI가 생성한 분석·문구는 **보조 초안**입니다. 최종 판단과 고객 전달 책임은 이용자에게 있으며, 서비스 이용 화면에 이를 명시합니다.
4. 다음 기능은 추가 법무 검토 완료 후 활성화됩니다 (현재 비활성):
   - 보험 비교안내서 자동생성(보험업법 §97 관련)
   - AI 기반 고객 문자 자동 초안 생성

### 제4조 이용자 의무

1. 이용자는 고객으로부터 **개인정보처리 동의 및 병력(민감정보)의 국외이전 동의**를 직접 수집한 후 서비스에 입력해야 합니다.
2. 이용자는 고객 정보를 보험업 관련 업무 외 목적으로 사용하지 않습니다.
3. 이용자는 서비스를 통해 생성된 자료(공유링크·문구 등)를 고객에게 전달할 때 최종 내용을 직접 확인합니다.
4. 계정과 비밀번호는 이용자 본인이 관리하며, 제3자에게 양도·공유할 수 없습니다.

### 제5조 서비스 이용 중단·해지

1. 이용자는 언제든지 서비스 탈퇴를 신청할 수 있습니다.
2. 탈퇴 처리 시 이용자 계정은 익명화됩니다. 단, 관계 법령에 따라 일정 기간 보관이 필요한 정보는 별도 보관 후 파기합니다.
3. 회사는 다음 사유 발생 시 이용을 중단할 수 있습니다:
   - 자격 허위 신고 사실이 확인된 경우
   - 서비스를 이용해 고객에게 무자격 모집·부당권유 행위를 한 경우
   - 타 이용자 데이터에 무단 접근을 시도한 경우

### 제6조 요금제 및 크레딧

1. 서비스는 프리미엄(Freemium) 방식으로 제공됩니다. 무료 플랜은 월 사용량 제한이 있으며, 유료 플랜은 제한이 확장됩니다.
2. 유료 플랜 결제는 별도 결제 약관에 따릅니다.
3. 미사용 크레딧은 다음 달로 이월되지 않습니다. **(추정 — 정식출시 전 확정 필요)**

### 제7조 면책

1. 회사는 이용자가 서비스를 통해 고객에게 제공한 정보·문구의 정확성·적합성에 대해 책임지지 않습니다.
2. 회사는 AI 분석 결과의 정확성을 보장하지 않으며, 이용자가 AI 결과를 검토·수정 없이 사용해 발생한 손해에 대해 책임지지 않습니다.
3. 보험업법 위반(부당권유·무자격 모집)으로 인한 민사·형사 책임은 이용자 본인에게 있습니다.

### 제8조 약관 변경

1. 회사는 약관을 변경할 경우 변경 내용과 시행일을 서비스 내 공지사항에 7일 전부터 게시합니다.
2. 이용자의 권리를 제한하거나 의무를 가중하는 중요 변경의 경우 30일 전 공지합니다.
3. 이용자가 시행일까지 거부 의사를 표명하지 않으면 변경 약관에 동의한 것으로 간주합니다.

---

## 3. 개인정보처리방침 (PP-v1) 초안

> 한국 개인정보보호법(PIPA) 및 정보통신망법 기준. 보수적 자체처리.

---

### 제1조 수집하는 개인정보

**가. 설계사(이용자) 정보**

| 항목 | 수집 방법 | 보유 기간 |
|---|---|---|
| 이메일 주소 | 회원가입 | 탈퇴 후 30일 |
| 비밀번호(암호화) | 회원가입 | 탈퇴 후 즉시 파기 |
| 소속(원수사/GA명) | 온보딩 | 탈퇴 후 30일 |
| 모집 자격 자기신고 여부 | 온보딩 | 탈퇴 후 30일 |
| 서비스 이용 기록 | 자동 수집 | 1년 |
| IP 주소(동의 기록용) | 동의 시 자동 수집 | 동의 철회 후 5년 |

**나. 고객 정보 (설계사가 입력, 설계사가 정보제공자)**

| 항목 | 민감정보 여부 | 이용 목적 |
|---|---|---|
| 고객명 | 아니오 | 담보 분석·공유 |
| 생년·성별·연락처 | 아니오 | 담보 계산·연락 |
| 직업위험등급 | 아니오 | 손해보험 분석 |
| 병력(질병명·진단 이력) | **예 — 민감정보** | Claude AI API 분석(국외이전 포함) |

> **병력(민감정보)**: 개인정보보호법 제23조에 따라 병력은 민감정보입니다. 수집·처리 시 별도 명시적 동의가 필요하며, Claude API(Anthropic Inc., 미국)로 전송되는 국외이전에 대한 동의도 별도로 받아야 합니다. → §4 상세.

### 제2조 개인정보 처리 목적

1. **설계사 서비스 제공**: 계정 관리, 고객 데이터 분석, 담보 시각화
2. **AI 분석**: 보험증권 OCR, 담보 정규화, 히트맵 생성 (Claude API 이용)
3. **서비스 개선**: 담보명 정규화 사전 학습(익명화된 매핑 데이터 활용)
4. **공지·고객지원**: 공지사항 발송, 1:1 문의 응대

> **인파는 고객 정보를 마케팅·제3자 제공에 사용하지 않습니다.**

### 제3조 개인정보 보유 및 파기

| 정보 유형 | 보유 기간 | 파기 방법 |
|---|---|---|
| 설계사 계정 | 탈퇴 후 30일 | DB 익명화 |
| 고객 개인정보(병력 제외) | 설계사 탈퇴 후 30일 | DB 삭제 |
| 병력(민감정보) | 동의 철회 또는 설계사 탈퇴 후 즉시 | DB 삭제 + 로그 파기 |
| 동의 기록(ConsentLog) | **5년** (개정된 정보주체 권리 분쟁 대비) | 보관 후 파기 |
| 이용 로그 | 1년 | 자동 삭제 |
| 결제 기록 | 5년 (전자상거래법 §6) | 별도 보관 |

### 제4조 민감정보(병력) 및 국외이전

#### 4.1 처리 근거

고객의 병력은 개인정보보호법 제23조의 **민감정보**입니다. 인파는 다음 요건을 충족한 경우에만 병력을 처리합니다:

1. 고객의 **별도 명시적 동의** 수집 (설계사가 서비스 내 동의서 화면을 통해 직접 수집)
2. 동의 내용에 처리 목적·항목·보유기간 명시

#### 4.2 국외이전

병력을 포함한 보험증권 분석 정보는 **Claude API(Anthropic Inc., 미국 소재)** 에 전송됩니다.

| 항목 | 내용 |
|---|---|
| 수신자 | Anthropic, Inc. |
| 소재 국가 | 미국 (United States) |
| 전송 목적 | 보험증권 OCR 및 담보 분석 AI 처리 |
| 전송 항목 | 증권 텍스트(병력 포함 가능) |
| 보유 기간 | Anthropic 처리 완료 즉시 (응답 후 저장 없음 — 추정: Anthropic API 정책 기준) |

> **Anthropic 데이터 보호 정책**: [https://www.anthropic.com/legal/privacy](https://www.anthropic.com/legal/privacy) — 인파는 API 설정에서 `do not use for training` 옵션을 적용합니다. **(추정: Anthropic API 기본 정책 확인 필요. openGaps 참고.)**

#### 4.3 동의 게이트 (코드 강제)

```
고객 분석 기능 진입 요청
  ↓
Customer.consent_overseas_at IS NULL?
  → YES: 412 CONSENT_OVERSEAS_REQUIRED 반환
          → FE: 국외이전 동의서 화면 표시
          → 동의 완료: ConsentLog 기록 + consent_overseas_at 갱신
          → 재진입
  → NO:  분석 진행
```

병력 국외이전 동의 없이는 AI 분석 기능이 **물리적으로 차단**됩니다.

### 제5조 개인정보처리 수탁자

| 수탁자 | 위탁 업무 | 보유·이용 기간 |
|---|---|---|
| Anthropic, Inc. (미국) | AI 텍스트 분석(병력 포함 가능) | API 요청·응답 완료 즉시 |
| AWS / 클라우드 인프라 **(미확정)** | 서버·DB 호스팅 | 계약 기간 |

> **개발 갭:** 호스팅 인프라(AWS, Cloudflare Pages 등)가 확정되지 않았습니다. 정식출시 전 수탁자 목록에 추가 필요.

### 제6조 정보주체 권리

설계사 및 고객은 다음 권리를 행사할 수 있습니다:

| 권리 | 행사 방법 | 처리 기한 |
|---|---|---|
| 열람 | 이메일 신청 (helpdesk 주소 미확정) | 10일 이내 |
| 정정 | 서비스 내 직접 수정 또는 이메일 신청 | 10일 이내 |
| 삭제(잊혀질 권리) | 이메일 신청 | 10일 이내 |
| 처리정지 | 이메일 신청 | 10일 이내 |
| 동의철회 | 서비스 내 "동의철회" 기능 또는 이메일 신청 | 즉시 처리 |

> 동의 철회 시 관련 기능(AI 분석)은 즉시 중단됩니다. 이미 처리된 데이터는 법령 허용 범위 내에서 삭제 처리합니다.

### 제7조 개인정보 보호책임자

```
개인정보 보호책임자: [대표자명 미확정]
연락처: [이메일 미확정]
처리 부서: 운영팀
```

> **개발 갭:** 개인정보 보호책임자(CPO) 지정 및 연락처 확정 필요. 정식출시 전 게시 의무.

---

## 4. 동의 분류 & 수집 흐름

### 4.1 동의 3종 — 주체·시점·분리 원칙

인파에서 수집하는 동의는 **성격이 다른 3가지**다. 이를 섞으면 법적 무효가 될 수 있다.

| 동의 ID | 명칭 | 정보주체 | 수집 시점 | 저장 위치 | 필수/선택 |
|---|---|---|---|---|---|
| `CONSENT_TOS` | 서비스 이용약관 동의 | 설계사 | 회원가입 | `Profile.tos_agreed_at` | **필수** |
| `CONSENT_PP` | 개인정보처리방침 동의 | 설계사 | 회원가입 | `Profile.pp_agreed_at` | **필수** |
| `CONSENT_MARKETING` | 마케팅 수신 동의 | 설계사 | 회원가입(선택) | `Profile.marketing_agreed_at` | 선택 |
| `CONSENT_OVERSEAS` | 병력 국외이전 동의 | **고객** | 분석 기능 진입 직전 | `Customer.consent_overseas_at` + `ConsentLog` | **필수(기능 게이트)** |

**레드라인**: `CONSENT_TOS`/`CONSENT_PP`(설계사 본인 약관)와 `CONSENT_OVERSEAS`(고객 병력 이전)를 **같은 화면이나 같은 체크박스로 묶지 않는다.** 법적 주체가 다르며 목적이 다르다.

### 4.2 가입 폼 통합 동의 화면 흐름

```
[가입 화면 /register]
  ├─ 이메일 입력
  ├─ 비밀번호 입력 (8자 이상, 영문+숫자+특수문자)
  ├─ 비밀번호 확인
  └─ 약관 동의 블록
       ├─ [전체 동의] 체크박스 (선택 포함)
       ├─ [필수] 서비스 이용약관 동의  [내용 보기 →]
       ├─ [필수] 개인정보처리방침 동의  [내용 보기 →]
       └─ [선택] 마케팅 정보 수신 동의 (이메일·앱 알림)
  └─ [가입하기] 버튼 (필수 미동의 → 비활성)
```

**가입 완료 → 이메일 인증 안내 화면 → 이메일 인증 링크 클릭 → 로그인 허용**

> 가입 폼에서 마케팅 동의는 선택이며, 미체크도 가입 가능. 이후 설정에서 언제든 변경 가능.

### 4.3 이메일 인증 흐름

```
가입 폼 제출
  ↓
BE: User 생성(is_active=False) + 인증 토큰 발급 + 인증 이메일 발송
  ↓
이용자: 이메일 수신 → 인증 링크 클릭
  ↓
BE: GET /api/v1/accounts/verify-email/?token=<token>
  → 토큰 검증(만료: 24시간) **(합리적 기본값)**
  → is_active=True + EmailVerificationLog 기록
  ↓
FE: /login 리다이렉트 + "이메일 인증 완료" 토스트
```

토큰 재발송: `/resend-verification/` (로그인 미완 상태에서 이메일로 신청).

### 4.4 로그인 흐름

```
[로그인 화면 /login]
  ├─ 이메일 입력
  ├─ 비밀번호 입력
  └─ [로그인] 버튼
       ↓
BE: POST /api/v1/auth/login/ { email, password }
  → is_active=False? → 403 "이메일 인증을 완료해주세요" + 재발송 링크
  → 비밀번호 불일치? → 401 "이메일 또는 비밀번호가 올바르지 않습니다" (구체적 오류 노출 금지)
  → 정상: { token, user_id, onboarding_required }
       ↓
FE: onboarding_required? → /onboarding : /home
```

로그인 실패 5회 초과 시 계정 잠금 10분. **(합리적 기본값 — 정식출시 전 정책 확정)**

### 4.5 비밀번호 재설정 흐름

```
[비밀번호 찾기 /forgot-password]
  └─ 이메일 입력 → [재설정 링크 받기]
       ↓
BE: POST /api/v1/auth/password-reset/
  → 해당 이메일 계정 존재 여부와 무관하게 "메일을 발송했습니다" 응답
    (이메일 존재 여부 노출 방지)
  → 계정 있으면: PasswordResetToken 발급(만료: 1시간) + 재설정 이메일 발송
       ↓
이용자: 이메일 수신 → 재설정 링크 클릭
  → /reset-password?token=<token>
       ↓
BE: POST /api/v1/auth/password-reset/confirm/
  → 토큰 검증 + 새 비밀번호 저장(PBKDF2, Django 기본) + 토큰 무효화
       ↓
FE: /login 리다이렉트 + "비밀번호가 변경되었습니다" 토스트
```

---

## 5. ConsentLog — 동의 6요건 모델

### 5.1 법적 요건 매핑

개인정보보호법상 동의는 **6가지 정보**를 동의서에 포함하고 수집·기록해야 한다.

| 요건 | PIPA 조항 | ConsentLog 필드 |
|---|---|---|
| 누가 (정보주체 식별) | §22 | `customer` FK |
| 언제 (동의 시점) | §22 | `agreed_at` (auto_now_add, 불변) |
| 무엇을 (처리 항목·범위) | §22①1 | `scope` (예: "병력·진단명·투약이력") |
| 왜 (처리 목적) | §22①2 | `purpose` (예: "AI 담보 분석") |
| 어느 버전 동의서 | 개정 추적 | `doc_version` (예: "OVERSEAS-v1.0-20260619") |
| 철회 가능성 | §37 | `revoked_at` (null=유효, not null=철회됨) |
| 어디서 (동의 출처) | 감사추적 | `ip` |

### 5.2 ConsentLog 모델 (정본)

```python
class ConsentLog(models.Model):
    """고객 동의 감사 로그 — 6요건 완비. 수정 금지(append-only)."""

    SCOPE_CHOICES = (
        ('overseas_medical', '병력 국외이전 (Claude API, 미국)'),
        ('medical_sensitive', '민감정보(병력) 처리'),
        ('marketing', '마케팅 수신'),
    )

    customer     = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='consent_logs'
    )
    scope        = models.CharField(max_length=50, choices=SCOPE_CHOICES)
    purpose      = models.CharField(max_length=200, default='')  # 처리 목적 텍스트
    doc_version  = models.CharField(max_length=30)              # "OVERSEAS-v1.0-20260619"
    agreed_at    = models.DateTimeField(auto_now_add=True)       # 불변 (수정 금지)
    ip           = models.GenericIPAddressField(null=True)
    revoked_at   = models.DateTimeField(null=True, blank=True)   # null = 유효
    revoke_ip    = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'consent_log'
        ordering = ['-agreed_at']
        # append-only 보장: 수정 방지는 django-simple-history 또는 DB 트리거로 보완
        indexes = [
            models.Index(fields=['customer', 'scope']),
        ]
```

> **append-only 원칙**: ConsentLog는 INSERT만 허용. UPDATE·DELETE 금지(감사 무결성). 철회는 `revoked_at` 필드로 기록(레코드 삭제 아님).

### 5.3 PolicyVersion 모델 (약관 버전 추적)

```python
class PolicyVersion(models.Model):
    """약관 버전 이력 — 동의서 버전 식별의 단일 출처."""

    POLICY_TYPE = (
        ('tos', '서비스 이용약관'),
        ('pp', '개인정보처리방침'),
        ('overseas', '병력 국외이전 동의서'),
    )

    policy_type  = models.CharField(max_length=20, choices=POLICY_TYPE)
    version      = models.CharField(max_length=30, unique=True)  # "TOS-v1.0-20260619"
    content_hash = models.CharField(max_length=64)  # SHA-256 (내용 변경 감지)
    effective_at = models.DateTimeField()            # 시행일
    requires_reconsent = models.BooleanField(default=False)  # True = major 개정
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'policy_version'
        ordering = ['-effective_at']
```

### 5.4 Profile 동의 필드 확장 (설계사 약관)

```python
# accounts/models.py Profile — 인파 net-new 동의 필드
class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, ...)

    # ── 인증 (이메일/비밀번호 전용) ────────────────────
    email_verified_at     = models.DateTimeField(null=True)  # 이메일 인증 완료 시각
    last_password_changed = models.DateTimeField(null=True)  # 비밀번호 변경 이력

    # ── 설계사 약관 동의 ─────────────────────────────
    tos_agreed_at         = models.DateTimeField(null=True)  # 서비스 이용약관
    tos_doc_version       = models.CharField(max_length=30, default='')  # 동의한 버전
    pp_agreed_at          = models.DateTimeField(null=True)  # 개인정보처리방침
    pp_doc_version        = models.CharField(max_length=30, default='')
    marketing_agreed_at   = models.DateTimeField(null=True)  # 마케팅 동의 (선택)
    marketing_revoked_at  = models.DateTimeField(null=True)  # 마케팅 철회

    # ── 위촉·온보딩 ──────────────────────────────────
    affiliation           = models.CharField(max_length=100, null=True)
    agent_type            = models.SmallIntegerField(null=True)  # 1=생명/2=손해/3=교차
    license_self_declared = models.BooleanField(default=False)
    license_no            = models.CharField(max_length=50, null=True)
    career_years          = models.IntegerField(null=True)
    onboarding_completed_at = models.DateTimeField(null=True)

    # ── 계정 상태 ───────────────────────────────────
    is_admin              = models.BooleanField(default=False)
    is_dormant            = models.BooleanField(default=False)
    dormant_at            = models.DateTimeField(null=True)
    will_delete_at        = models.DateTimeField(null=True)
    ref_code              = models.CharField(max_length=20, unique=True, null=True)
```

---

## 6. 병력 국외이전 동의서 (OVERSEAS-v1) 화면 & 문구

### 6.1 동의서 전문 (표준 문구)

> 이 동의서는 고객이 직접 읽고 동의합니다. 설계사가 대신 체크하는 방식은 **법적 유효성 없음** — 반드시 고객 본인이 확인하는 UX 흐름 필요.

---

**[병력 등 민감정보의 국외이전 동의서]**

**인파(Inpa)** 를 통한 보험 담보 분석 서비스 이용과 관련하여, 귀하의 병력 정보가 국외로 이전될 수 있음을 안내드립니다.

**처리 항목**: 귀하의 병력, 진단명, 투약 이력, 보험증권에 기재된 건강 관련 정보

**처리 목적**: 보험 담보 현황 분석 (인공지능 OCR 및 담보 정규화)

**이전 국가**: 미국 (United States)

**이전받는 자**: Anthropic, Inc. (Claude AI API 제공자)
**연락처**: [privacy@anthropic.com](mailto:privacy@anthropic.com) / [https://www.anthropic.com](https://www.anthropic.com)

**이전 항목**: 보험증권 텍스트(병력 포함 가능)

**보유 기간**: API 처리 완료 직후 (Anthropic은 API 응답 후 요청 내용을 학습에 사용하지 않습니다)

**동의 거부 권리**: 귀하는 이 동의를 거부할 수 있습니다. 단, 동의 거부 시 인공지능 기반 보험 담보 분석 서비스를 이용할 수 없습니다.

귀하는 언제든지 담당 보험설계사 또는 인파 고객센터(이메일: [미확정])에 동의 철회를 요청할 수 있습니다.

---

[ ] **위 내용을 읽었으며, 병력 등 민감정보의 미국 이전에 동의합니다.**

---

### 6.2 동의 화면 흐름 (UX)

```
[고객 공유뷰에서 분석 진입 or 설계사가 분석 시작]
  ↓
BE: consent_overseas_at IS NULL?
  → YES: 412 반환
       ↓
FE: 모달 또는 별도 화면
  ┌─────────────────────────────────────────────┐
  │ 분석을 위해 동의가 필요합니다               │
  │                                             │
  │ [동의서 전문 스크롤 영역 — §6.1 전문]        │
  │                                             │
  │ [ ] 병력 국외이전에 동의합니다              │
  │                                             │
  │ [동의하고 계속하기]  [취소]                 │
  │                                             │
  │ ※ 동의 거부 시 AI 분석을 이용할 수 없습니다 │
  └─────────────────────────────────────────────┘
  → [동의하고 계속하기] 클릭
       ↓
BE: POST /api/v1/customers/{id}/consent/overseas/
  body: { doc_version: "OVERSEAS-v1.0-20260619" }
  → Customer.consent_overseas_at = now()
  → ConsentLog 생성 (scope='overseas_medical', doc_version, ip, agreed_at)
  → 200 OK
       ↓
FE: 분석 재시작
```

> **설계사가 대신 동의할 수 없다.** 설계사 전용 분석 화면(설계사가 업로드)과 고객 공유뷰 분석의 동의 주체가 다를 수 있음 — 설계사 화면에서는 "고객에게 동의서를 직접 확인받으셨습니까?" 확인 체크박스를 경유하는 설계 검토 필요. **(openGaps 참고)**

### 6.3 동의 철회 흐름

```
설계사: 고객 상세 페이지 → [동의 관리] → [국외이전 동의 철회]
  ↓
BE: POST /api/v1/customers/{id}/consent/overseas/revoke/
  → ConsentLog.revoked_at = now() + revoke_ip 기록
  → Customer.consent_overseas_at = None
  → 200 OK
  ↓
이후 분석 기능 진입 → 412 게이트 재발동
```

---

## 7. 인증 시스템 — 이메일/비밀번호 전용

> **확정 결정**: 카카오 OAuth 전면 제거. 이메일/비밀번호만 사용. `dev/11`의 카카오 OAuth 내용은 이 문서로 대체됨.

### 7.1 인증 스택

| 항목 | 결정 | 근거 |
|---|---|---|
| 인증 방식 | 이메일/비밀번호 | 카카오 OAuth 제거 — 카카오 콘솔 의존성·개인정보 위탁 최소화 |
| 토큰 방식 | DRF Token (foliio ♻) | 심플하고 검증됨. 베타는 무기한 |
| 비밀번호 해시 | PBKDF2 (Django 기본) | Django 기본값 사용 |
| 이메일 인증 | 가입 후 24시간 유효 토큰 | is_active=False 게이트 |
| 비밀번호 찾기 | 이메일 링크 (1시간 유효 토큰) | PasswordResetToken 모델 |
| 로그인 실패 잠금 | 5회 실패 → 10분 잠금 | 합리적 기본값 |

### 7.2 API 계약 (인증)

| Path | Method | Auth | 용도 |
|---|---|---|---|
| `/api/v1/auth/register/` | POST | AllowAny | 회원가입 (이메일+비밀번호+약관동의) |
| `/api/v1/auth/verify-email/` | GET | AllowAny | 이메일 인증 링크 처리 (`?token=`) |
| `/api/v1/auth/resend-verification/` | POST | AllowAny | 인증 이메일 재발송 |
| `/api/v1/auth/login/` | POST | AllowAny | 로그인 → Token 발급 |
| `/api/v1/auth/logout/` | POST | Token | 로그아웃 (Token 삭제) |
| `/api/v1/auth/password-reset/` | POST | AllowAny | 비밀번호 재설정 이메일 발송 |
| `/api/v1/auth/password-reset/confirm/` | POST | AllowAny | 새 비밀번호 설정 |
| `/api/v1/accounts/profile/` | GET/PATCH | Token | 내 프로필 조회·수정 |
| `/api/v1/accounts/onboarding/` | PATCH | Token | 약관/위촉 완료 기록 |
| `/api/v1/customers/{id}/consent/overseas/` | POST | Token (IsOwner) | 국외이전 동의 수집 |
| `/api/v1/customers/{id}/consent/overseas/revoke/` | POST | Token (IsOwner) | 국외이전 동의 철회 |

**register 요청/응답 예시:**

```json
// POST /api/v1/auth/register/
// Request:
{
  "email": "agent@example.com",
  "password": "Secure123!",
  "password_confirm": "Secure123!",
  "tos_agreed": true,
  "pp_agreed": true,
  "marketing_agreed": false,
  "tos_doc_version": "TOS-v1.0-20260619",
  "pp_doc_version": "PP-v1.0-20260619"
}

// Response 201:
{
  "message": "가입이 완료되었습니다. 이메일을 확인해 인증을 완료해주세요.",
  "email": "agent@example.com"
}
```

**login 응답 예시:**

```json
// Response 200:
{
  "token": "9a8b7c...",
  "user_id": 42,
  "onboarding_required": true,
  "profile": {
    "email_verified": true,
    "onboarding_completed_at": null,
    "agent_type": null,
    "license_self_declared": false
  }
}
```

---

## 8. 권한 & 가시성 — 멀티테넌시 동의 레이어

동의 관련 데이터의 접근 권한은 전체 가시성 매트릭스에 따라 **소유자 전용** 원칙을 적용한다.

| 데이터 | 소유자(설계사) | 관리자(admin) | 고객 | 공개 |
|---|---|---|---|---|
| `ConsentLog` | 본인 고객의 것만 읽기 | 전체 읽기 | 직접 접근 없음 (설계사 경유) | 불가 |
| `Customer.consent_overseas_at` | 본인 고객만 읽기/쓰기 | 전체 읽기 | 직접 접근 없음 | 불가 |
| `Profile.tos_agreed_at` | 본인만 | 전체 읽기 | 해당 없음 | 불가 |
| `PolicyVersion` | 읽기(버전 확인) | 읽기/쓰기 | 읽기(공개페이지) | 읽기(`/legal/*`) |

> `ConsentLog`는 설계사가 **생성·조회**만 가능. 삭제 불가(append-only). 철회는 별도 `revoke` API로만.

---

## 9. 관리자 페이지 (Admin) 동의 관련 기능

관리자 페이지는 다음 동의 관련 기능을 제공한다:

| 기능 | 설명 |
|---|---|
| 전체 ConsentLog 조회 | 날짜·설계사·고객별 필터 |
| 동의 미수집 고객 현황 | `consent_overseas_at IS NULL` + AI 분석 시도 횟수 |
| PolicyVersion 등록·관리 | 약관 버전 추가, 재동의 플래그 설정 |
| 이메일 인증 미완료 계정 목록 | `is_active=False` 계정 재발송 |
| 마케팅 동의 통계 | 선택 동의 현황 집계 |

---

## 10. 컴플라이언스 체크리스트 — 베타 게이트

개발 착수 전 또는 베타 오픈 전 완료해야 할 법무 선결 항목.

### 10.1 착수 전 필수 (코드 작성 불가 게이트)

| # | 항목 | 상태 | 담당 |
|---|---|---|---|
| G1 | 법인명·대표자·사업자등록번호 확정 | 미완 | 대표 |
| G2 | 개인정보 보호책임자(CPO) 지정 및 연락처 | 미완 | 대표 |
| G3 | 국외이전 동의서 전문(§6.1) 대표 승인 | 미완 | 대표 |
| G4 | Anthropic API 데이터 처리 정책 확인 (학습 사용 여부) | 미완 | 개발 |
| G5 | 호스팅 인프라(수탁자) 확정 | 미완 | 개발 |

### 10.2 베타 오픈 전 필수

| # | 항목 | 상태 | 담당 |
|---|---|---|---|
| B1 | 이용약관 본문 법무 검토 (자체처리 한계 인지) | 미완 | 법무자문 |
| B2 | 개인정보처리방침 법무 검토 | 미완 | 법무자문 |
| B3 | 정보통신망법상 개인정보처리방침 공개 페이지(`/legal/privacy`) 게시 | 미완 | 개발 |
| B4 | 이용약관 공개 페이지(`/legal/terms`) 게시 | 미완 | 개발 |
| B5 | 동의서 ConsentLog 6요건 적재 실제 동작 검증 | 미완 | QA |
| B6 | 마케팅 동의 철회 동선(`marketing_revoked_at`) 구현·검증 | 미완 | 개발 |
| B7 | 정보주체 권리 행사 이메일 연락처 공개 | 미완 | 운영 |

### 10.3 정식출시 전 필수 (베타 이후)

| # | 항목 | 상태 |
|---|---|---|
| P1 | 설계사 자기신고 vs 자격 API 연동 재결정 | 미완 |
| P2 | 병력·진단서 Claude API 전송 범위 법무 확인 (개정 PIPA 국외이전 기준) | 미완 |
| P3 | 개인정보영향평가(PIA) 필요 여부 검토 (처리 건수·민감정보 기준) | 미완 |
| P4 | 이용자 10만 초과 시 개인정보보호위원회 신고 의무 확인 | 미완 |

---

## 11. 수용 기준 (Definition of Done)

- [ ] 회원가입 폼: 이메일·비밀번호·약관 동의(필수 2 + 선택 1) — 필수 미동의 시 [가입하기] 비활성
- [ ] 가입 완료 → 이메일 인증 이메일 발송 → 링크 클릭 → `is_active=True` → 로그인 허용
- [ ] 로그인: 이메일+비밀번호 → Token 발급 → `onboarding_required` 분기 라우팅
- [ ] 비밀번호 찾기: 이메일 발송 → 링크 클릭 → 새 비밀번호 설정 → 로그인
- [ ] `ConsentLog` 6요건 필드 전부 실제 DB 적재 확인 (INSERT 후 SELECT)
- [ ] `consent_overseas_at IS NULL` → AI 분석 API 412 반환 → FE 동의서 화면 표시
- [ ] 국외이전 동의 수집 → `ConsentLog` 자동 생성 → 분석 재진입 가능
- [ ] 동의 철회 → `revoked_at` 기록 → `consent_overseas_at = None` → 분석 412 재발동
- [ ] 마케팅 동의 선택 체크 여부와 무관하게 가입 완료 가능
- [ ] 마케팅 동의 철회 → `marketing_revoked_at` 기록 → 마케팅 이메일 발송 중단
- [ ] `PolicyVersion` 테이블에 초기 3종 버전 시드 데이터 삽입 완료
- [ ] `/legal/terms`, `/legal/privacy` 공개 페이지 렌더링 (비인증 접근 허용)
- [ ] 관리자 페이지: ConsentLog 전체 조회 + 동의 미수집 고객 필터 동작
- [ ] 카카오 OAuth 관련 코드·환경변수·라우트가 존재하지 않음 (grep 검증)

---

## 12. 미결 과제 (openGaps)

| # | 항목 | 리스크 | 우선순위 |
|---|---|---|---|
| O1 | 법인명·대표자·사업자등록번호 확정 | 약관 본문 게시 불가 | 착수 전 필수 |
| O2 | Anthropic API 데이터 보유·학습 정책 최신 버전 확인 | 국외이전 동의서 정확성 | 착수 전 필수 |
| O3 | 설계사가 고객 동의를 대리 수집하는 경우 법적 유효성 확인 | 동의 무효 리스크 | 베타 전 |
| O4 | 로그인 실패 잠금 정책(횟수·시간) 확정 | 보안 vs UX 트레이드오프 | 베타 전 |
| O5 | 토큰 만료·리프레시 정책 — 베타 무기한 → 정식출시 전 재검토 | 세션 보안 | 정식출시 전 |
| O6 | 호스팅 인프라(AWS·Cloudflare 등) 확정 → 수탁자 목록 업데이트 | 개인정보처리방침 미완 | 베타 전 |
| O7 | 병력 외 민감정보(진단서 이미지 등) 처리 범위 명확화 | 동의서 범위 누락 | 베타 전 |
| O8 | 마케팅 수신 채널(이메일만 vs 앱푸시 포함) 확정 | 동의 항목 정확성 | 베타 전 |
