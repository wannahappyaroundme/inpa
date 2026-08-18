# 내부 시연 계정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 운영 서비스에 `test@inpa.kr` 전용 시연 계정과 풍부한 합성 자료를 만들되, 실제 사용자·공용 게시판·운영 지표·외부 유료/발송 기능과 완전히 분리한다.

**Architecture:** `Profile.is_showcase`와 서버 설정 이메일을 함께 확인하는 중앙 판별 함수를 만든다. 전용 `seed_showcase` 명령은 기존 표준 담보 자료를 읽기 전용으로 재사용하며, 시연 계정 소유 행만 한 트랜잭션에서 결정론적으로 재생성한다. 외부 작동은 중앙 권한 클래스로 차단하고, 운영 지표는 중앙 QuerySet 조건으로 제외한다.

**Tech Stack:** Django 5.2, Django REST Framework, PostgreSQL/SQLite, Django management command, Django TestCase/APIClient, Next.js 16 브라우저 검증

## Global Constraints

- 제품 코드 작업은 최신 `origin/master`에서 분기한 격리 worktree `codex/internal-showcase-account`에서 수행한다. 현재 작업 폴더의 기존 수정·미추적 파일은 건드리거나 스테이징하지 않는다.
- 사용자 확정 비밀번호는 채팅과 Render 비밀 설정에만 존재한다. 소스, 문서, 테스트 fixture, 명령 출력, 커밋 기록에는 실제 값을 쓰지 않는다.
- `seed_showcase`는 외부 AI, 이메일, Google, 파일 저장소, 결제, 판촉물 시스템을 호출하지 않는다.
- 공용 `Notice`, `Faq`, `BlogPost`, `Post`, `Plan`, 표준 담보 트리, 정규화 사전, 호환 카탈로그는 생성·수정·삭제하지 않는다.
- 기존 `[표준]` 호환 카탈로그는 조회만 하고, 고객별 `analysis_detail_override`만 연결한다. 전역 M2M은 변경하지 않는다.
- 운영 서버 반영은 PR CI 통과 후 PM의 별도 명시적 승인을 받아야 한다.
- 각 구현 단계는 실패 테스트 작성 → 실패 확인 → 최소 구현 → 통과 확인 순서로 진행한다.

---

## Task 0: 격리 작업공간과 기준선 고정

**Files:**

- Read: `/Users/kyungsbook/Desktop/inpa/AGENTS.md`
- Read: `/Users/kyungsbook/Desktop/inpa/inpa_fe/AGENTS.md`
- Read: `/Users/kyungsbook/Desktop/inpa/.Codex/failures.md`
- Verify only: current Git worktree

**Steps:**

- [ ] `superpowers:using-git-worktrees`를 읽고 최신 `origin/master` 기준 격리 worktree와 `codex/internal-showcase-account` 브랜치를 만든다.
- [ ] `git status --short`와 `git log --oneline -10`을 기록해 기존 작업과 분리됐음을 확인한다.
- [ ] 백엔드 기준선을 실행한다.

```bash
cd inpa_be
python manage.py check
python manage.py test inpa.accounts inpa.admin_console inpa.notifications inpa.promotion inpa.billing
```

- [ ] 프런트엔드는 변경하지 않을 계획이지만 회귀 기준으로 현재 빌드를 한 번 기록한다.

```bash
cd inpa_fe
npm run build
```

- [ ] 실패가 있으면 새 작업으로 덮지 않고 기준선 실패로 기록해 PM에게 알린다.

---

## Task 1: 시연 계정 표식과 중앙 판별 함수

**Files:**

- Modify: `inpa_be/inpa/accounts/models.py:38-80`
- Create: `inpa_be/inpa/accounts/migrations/0016_profile_is_showcase.py`
- Create: `inpa_be/inpa/core/internal_accounts.py`
- Modify: `inpa_be/inpa/core/permissions.py`
- Modify: `inpa_be/config/settings/base.py:184`
- Modify: `inpa_be/.env.example`
- Modify: `render.yaml`
- Test: `inpa_be/inpa/accounts/tests.py`

**Public interfaces:**

```python
def is_showcase_user(user) -> bool:
    """Profile.is_showcase=True AND email equals SHOWCASE_ACCOUNT_EMAIL."""

def internal_user_q(relation: str = "") -> models.Q:
    """@inpa.local OR verified showcase account, with optional FK prefix."""

class ShowcaseActionRestricted(APIException):
    status_code = 403
    default_detail = {
        "code": "SHOWCASE_ACTION_RESTRICTED",
        "detail": "등록된 자료를 활용해 주요 기능을 확인할 수 있어요.",
    }

def block_showcase_external_action(user) -> None:
    """Raise ShowcaseActionRestricted for the verified showcase account."""

class BlocksShowcaseExternalActions(BasePermission):
    """Call block_showcase_external_action() from DRF permission evaluation."""
```

**Steps:**

- [ ] `Profile` 생성 시 기본값이 `False`이고 API 응답에 새 내부 필드가 노출되지 않는 테스트를 먼저 작성한다.
- [ ] 이메일만 일치하거나 플래그만 켜진 계정은 시연 계정으로 인정하지 않고, 두 조건이 모두 맞을 때만 인정하는 테스트를 작성한다.
- [ ] `internal_user_q()`가 기존 `@inpa.local` 계정과 정확한 시연 계정만 잡는 테스트를 작성한다.
- [ ] 테스트가 `FieldError`/import error로 실패하는 것을 확인한다.

```bash
cd inpa_be
python manage.py test inpa.accounts.tests.ShowcaseAccountClassificationTests
```

- [ ] `Profile.is_showcase = models.BooleanField(default=False, db_index=True)`와 migration을 추가한다.
- [ ] `SHOWCASE_ACCOUNT_EMAIL`, `SHOWCASE_ACCOUNT_PASSWORD`를 빈 기본값의 서버 설정으로 추가한다. `render.yaml`에는 두 값을 `sync: false`로 선언한다.
- [ ] `is_showcase_user()`는 설정 이메일이 비어 있으면 항상 `False`를 반환하고, 프로필 미생성/익명 사용자도 안전하게 처리한다.
- [ ] `internal_user_q(relation)`는 `relation="sender"` → `sender__email...`, `sender__profile__is_showcase...` 형식으로 조합하되 설정 이메일이 비어 있으면 `@inpa.local` 조건만 반환한다.
- [ ] 외부 작동 차단 권한 클래스를 추가한다. 읽기 전용 API에는 붙이지 않는다.
- [ ] migration 적용과 테스트 통과를 확인한다.

```bash
python manage.py makemigrations --check
python manage.py migrate
python manage.py test inpa.accounts.tests.ShowcaseAccountClassificationTests
```

- [ ] 커밋 권한이 승인된 실행 방식이면 이 단계만 커밋한다.

```bash
git add inpa_be/inpa/accounts/models.py \
  inpa_be/inpa/accounts/migrations/0016_profile_is_showcase.py \
  inpa_be/inpa/core/internal_accounts.py \
  inpa_be/inpa/core/permissions.py \
  inpa_be/config/settings/base.py inpa_be/.env.example render.yaml \
  inpa_be/inpa/accounts/tests.py
git commit -m "security(시연): 전용 계정 식별과 외부작동 가드 추가"
```

---

## Task 2: 운영 통계에서 시연 계정 중앙 제외

**Files:**

- Modify: `inpa_be/inpa/admin_console/views.py:1239-1270`
- Modify: `inpa_be/inpa/admin_console/views.py:1470-1480`
- Modify: `inpa_be/inpa/admin_console/views.py:1690-1705`
- Modify: `inpa_be/inpa/admin_console/views.py:1936-1970`
- Modify: `inpa_be/inpa/notifications/jobs.py:381-395`
- Test: `inpa_be/inpa/admin_console/tests.py:1080-1210`
- Test: `inpa_be/inpa/admin_console/tests.py:1790-1850`
- Test: `inpa_be/inpa/notifications/tests.py:1020-1045`

**Steps:**

- [ ] 사용량, 보험 검토 작업, Claude 비용, 활성화 전환, 가입·인증 장애 감시 각각에 일반 사용자와 시연 사용자를 함께 넣는 실패 테스트를 작성한다.
- [ ] 시연 계정 활동이 분자·분모·합계에 모두 포함되지 않고 일반 사용자는 그대로 집계되는지 수치로 단언한다.
- [ ] 기존 하드코딩 `@inpa.local` 조건 때문에 새 시연 계정이 집계되는 실패를 확인한다.

```bash
cd inpa_be
python manage.py test \
  inpa.admin_console.tests.AdminUsageShowcaseExclusionTests \
  inpa.admin_console.tests.ActivationFunnelShowcaseExclusionTests \
  inpa.notifications.tests.SignupFlatlineShowcaseExclusionTests
```

- [ ] 모든 제외 조건을 `internal_user_q()`로 교체한다. FK 관계별 prefix는 `sender`, `owner`, `user`, 빈 문자열을 정확히 사용한다.
- [ ] `/admin/usage`의 고객·증권·공유 합계와 구독/쿠폰 요약도 동일 중앙 조건을 거치는지 전체 함수 범위를 재검토하고 누락된 queryset을 같은 방식으로 보완한다.
- [ ] 기존 `@inpa.local` 제외 테스트와 새 시연 제외 테스트를 함께 통과시킨다.

```bash
python manage.py test inpa.admin_console inpa.notifications
```

- [ ] 커밋 권한이 승인된 실행 방식이면 이 단계만 커밋한다.

```bash
git add inpa_be/inpa/admin_console/views.py inpa_be/inpa/admin_console/tests.py \
  inpa_be/inpa/notifications/jobs.py inpa_be/inpa/notifications/tests.py
git commit -m "fix(통계): 시연 계정을 운영 지표에서 제외"
```

---

## Task 3: 비용·발송·공개 확산 경로 차단

**Files:**

- Modify: `inpa_be/inpa/accounts/views.py:159-170`
- Modify: `inpa_be/inpa/accounts/views.py:221-375`
- Modify: `inpa_be/inpa/accounts/views.py:385-510`
- Modify: `inpa_be/inpa/customers/views.py:74-160`
- Modify: `inpa_be/inpa/insurances/views.py:360-530`
- Modify: `inpa_be/inpa/insurances/import_views.py:148-190`
- Modify: `inpa_be/inpa/promotion/views.py:123-158`
- Modify: `inpa_be/inpa/promotion/views.py:200-245`
- Modify: `inpa_be/inpa/billing/views.py:163-190`
- Modify: `inpa_be/inpa/recruiting/views.py:265-350`
- Test: `inpa_be/inpa/accounts/tests.py`
- Test: `inpa_be/inpa/accounts/test_google.py`
- Test: `inpa_be/inpa/customers/tests.py`
- Test: `inpa_be/inpa/insurances/tests.py`
- Test: `inpa_be/inpa/insurances/test_import_api.py`
- Test: `inpa_be/inpa/promotion/tests.py`
- Test: `inpa_be/inpa/billing/tests.py`
- Test: `inpa_be/inpa/recruiting/tests/test_api.py`

**Protected write paths:**

- 이메일 재발송·비밀번호 재설정 메일, 비밀번호 재설정 확정·변경
- Google 로그인 연결, Google Calendar 연결·콜백
- 계정 탈퇴
- 프로필 사진과 고객 명함 파일 업로드
- 기존 OCR과 검토형 증권 업로드
- 전자자료 요청과 판촉물 주문
- 쿠폰 사용
- 공개 설계사 모집 페이지·캠페인 생성/활성화/복사 기록

**Allowed paths:**

- 로그인, 로그아웃, 프로필·요금제·준비된 분석 읽기
- 고객 단계·상태·메모·태그 수정
- 직접 입력한 고객/증권/일정의 계정 내부 CRUD
- 준비된 공유 링크와 예약 링크 읽기
- 기존 시연 계정 소유 주문/이력의 읽기

**Steps:**

- [ ] 각 보호 경로에서 외부 함수(`send_mail`, Google token exchange, Claude parser/task enqueue, 파일 storage save, `check_and_consume`, 주문/쿠폰 서비스)가 호출되지 않는 실패 테스트를 mock으로 작성한다.
- [ ] 차단 응답은 HTTP 403, `code=SHOWCASE_ACTION_RESTRICTED`, 긍정 안내 문구로 통일한다.
- [ ] `PasswordResetView`와 `ResendVerificationView`는 계정 존재 여부를 노출하지 않도록 기존 200 응답을 유지하면서 발송만 건너뛴다. 나머지 인증된 외부 작동은 403을 반환한다.
- [ ] 일반 사용자에 대해서는 같은 mock이 정확히 한 번 호출되고 기존 응답이 유지되는 쌍대 테스트를 작성한다.
- [ ] 실패 테스트를 앱별로 확인한다.

```bash
cd inpa_be
python manage.py test \
  inpa.accounts.tests.ShowcaseExternalActionTests \
  inpa.accounts.test_google.ShowcaseGoogleActionTests \
  inpa.customers.tests.ShowcaseUploadTests \
  inpa.insurances.tests.ShowcaseOcrTests \
  inpa.insurances.test_import_api.ShowcaseImportTests \
  inpa.promotion.tests.ShowcasePromotionTests \
  inpa.billing.tests.ShowcaseCouponTests \
  inpa.recruiting.tests.test_api.ShowcasePublicCampaignTests
```

- [ ] 인증된 API에는 `BlocksShowcaseExternalActions`를 가장 앞의 부작용 직전에 적용한다. 읽기와 내부 CRUD가 함께 있는 APIView는 클래스 전체가 아니라 해당 write method 시작에서 공용 helper로 판별한다.
- [ ] 공개 비밀번호 재설정/재발송은 이메일 조회 뒤 `is_showcase_user()`일 때 발송 함수를 호출하지 않는다.
- [ ] Google 로그인은 검증된 Google 이메일이 기존 시연 계정과 일치할 경우 계정 연결·토큰 갱신 전에 403으로 중단한다.
- [ ] 모집 페이지는 새 공개 토큰 생성·활성화만 차단하고 `/sales`의 고객 영업 읽기/내부 고객 기능은 유지한다.
- [ ] 전체 관련 앱 테스트를 통과시킨다.

```bash
python manage.py test inpa.accounts inpa.customers inpa.insurances \
  inpa.promotion inpa.billing inpa.recruiting
```

- [ ] 커밋 권한이 승인된 실행 방식이면 이 단계만 커밋한다.

```bash
git add inpa_be/inpa/accounts/views.py inpa_be/inpa/accounts/tests.py \
  inpa_be/inpa/accounts/test_google.py inpa_be/inpa/customers/views.py \
  inpa_be/inpa/customers/tests.py inpa_be/inpa/insurances/views.py \
  inpa_be/inpa/insurances/import_views.py inpa_be/inpa/insurances/tests.py \
  inpa_be/inpa/insurances/test_import_api.py inpa_be/inpa/promotion/views.py \
  inpa_be/inpa/promotion/tests.py inpa_be/inpa/billing/views.py \
  inpa_be/inpa/billing/tests.py inpa_be/inpa/recruiting/views.py \
  inpa_be/inpa/recruiting/tests/test_api.py
git commit -m "security(시연): 외부 비용과 발송 경로 차단"
```

---

## Task 4: 합성 자료 명세를 순수 데이터로 고정

**Files:**

- Create: `inpa_be/inpa/analysis/showcase_data.py`
- Create: `inpa_be/inpa/analysis/test_showcase_data.py`

**Required constants and validation:**

```python
CUSTOMER_COUNT = 50
INSURANCE_COUNT = 80
ANCHOR_CUSTOMER_COUNT = 8
MIN_COVERAGE_COUNT = 160
STAGE_COUNTS = {"db": 14, "contact": 12, "meeting": 12, "contract": 12}
STATUS_COUNTS = {"active": 42, "hold": 4, "dormant": 3, "closed": 1}

def validate_showcase_specs() -> None:
    """Raise CommandError before DB writes when counts/names/date rules disagree."""
```

**Steps:**

- [ ] 50명의 이름·생년월일·성별·직업·전화·유입·단계·상태·태그·메모 조합을 테스트로 먼저 정의한다.
- [ ] 전화는 모두 `010-1XXX-XXXX` 형식이며 중복이 없고, 이메일·주소·주민번호가 고객 자료에 없는지 검사한다.
- [ ] 실제 보험사 상호나 실적처럼 보이는 표현 없이 합성 회사/일반 상품 유형만 사용하는 금칙어 테스트를 만든다.
- [ ] 8명의 핵심 고객은 2~4개 증권, 고객별 12~25개 담보, 전체 160개 이상이라는 구조 검사를 만든다.
- [ ] 고객 50명 전체에 증권 80건이 정확히 배분되고 최근 6개월 월별 흐름이 감소하지 않도록 검사한다.
- [ ] 렌더 가능 문자열 전체에서 `[DEMO]`, `[촬영]`, `데모`, `테스트`, `촬영용`, `sample`, `dummy`가 0건인지 검사한다. 내부 상수명과 주석은 검사 대상에서 제외한다.
- [ ] 실패 확인 후 immutable tuple/dataclass 기반 명세를 작성하고 import 시 `validate_showcase_specs()`를 통과시킨다.

```bash
cd inpa_be
python manage.py test inpa.analysis.test_showcase_data
```

- [ ] 커밋 권한이 승인된 실행 방식이면 이 단계만 커밋한다.

```bash
git add inpa_be/inpa/analysis/showcase_data.py \
  inpa_be/inpa/analysis/test_showcase_data.py
git commit -m "feat(시연): 자연스러운 합성 고객과 증권 명세 추가"
```

---

## Task 5: 원자적 생성·초기화·삭제 명령

**Files:**

- Create: `inpa_be/inpa/analysis/management/commands/seed_showcase.py`
- Create: `inpa_be/inpa/analysis/test_showcase_seed.py`
- Read only: `inpa_be/inpa/analysis/management/commands/seed_capture.py`
- Read only: `inpa_be/inpa/analysis/management/commands/seed_normalization.py`
- Read only: `inpa_be/inpa/insurances/import_services.py`

**Command contract:**

```bash
python manage.py seed_showcase --apply
python manage.py seed_showcase --purge --apply
```

**Safety contract:**

```python
@transaction.atomic
def handle(...):
    # create: exact configured email absent OR exact email + is_showcase + non-admin
    # reset/purge: exact configured email + is_showcase + non-admin + --apply
    # password is read only from settings and never printed
```

**Steps:**

- [ ] `--apply` 누락, 이메일/비밀번호 설정 누락, 같은 이메일의 일반 계정 존재, 관리자/직원/슈퍼유저 계정 충돌이 모두 DB 변경 0건으로 실패하는 테스트를 작성한다.
- [ ] 빈 DB에서 실행하면 아래 정확한 결과가 생성되는 통합 테스트를 작성한다.

  - 프로필 1, 관리자 권한 0, 이메일 인증/첫 설정 완료
  - 활성 내부 Super 구독 1, 자동 결제/다음 결제일 없음
  - 고객 50, 증권 80, 핵심 고객 8, 상세 담보 160 이상
  - 단계 DB/TA/FA/청약 = 14/12/12/12
  - 상태 진행중/보류/휴면/종료 = 42/4/3/1
  - 최근 6개월 `MonthlyGoal` 6
  - 이번 달 `ScheduleItem` 30, 오늘 3
  - 평일 `WorkHour` 5
  - `Meeting` 대기 2, 확정 3
  - `Notification` 12, 읽음/안 읽음 혼합
  - 공유 가능한 핵심 고객 2

- [ ] 실행 전후 공용 테이블과 연결을 fingerprint로 비교하는 테스트를 작성한다.

  - `Post`, `Notice`, `Faq`, `BlogPost`, `Plan`, `PromotionSample`
  - `AnalysisCategory`, `AnalysisSubCategory`, `AnalysisDetail`
  - `InsuranceCategory`, `InsuranceSubCategory`, `InsuranceDetail`
  - `InsuranceDetail.analysis_detail` 전역 M2M through table

- [ ] 두 번째 실행에서 첫 실행의 시연 소유 행을 안전 가드로만 지운 뒤 동일 개수·동일 자연키·상대 날짜 상태가 만들어지는 멱등 테스트를 작성한다.
- [ ] 생성 중 강제 예외를 주입해 사용자까지 포함한 모든 시연 행이 롤백되는 테스트를 작성한다.
- [ ] `--purge --apply`가 정확한 계정만 지우고 공용 fingerprint를 보존하며, 플래그를 끈 뒤에는 삭제를 거부하는 테스트를 작성한다.
- [ ] 실패를 확인한다.

```bash
cd inpa_be
python manage.py test inpa.analysis.test_showcase_seed
```

- [ ] 명령 시작 시 `validate_showcase_specs()`와 필요한 표준 담보 exact-name 목록을 검증해 누락을 한 번에 출력한다.
- [ ] 계정은 `select_for_update()`로 잠그고, 초기화/삭제 네 조건을 공통 `_assert_safe_target()`에서 강제한다.
- [ ] 프로필은 박도윤, 한빛금융서비스, 팀장으로 만들고 `is_showcase=True`, 인증/온보딩/둘러보기 완료 상태를 설정한다.
- [ ] `Plan(code="super")`는 조회만 하며 없으면 생성하지 않고 실패한다. `Subscription`은 내부 비결제 상태로 만든다.
- [ ] 날짜는 서비스 시간대의 실행일을 기준으로 월 경계를 계산한다. `auto_now_add` 역산은 `QuerySet.update()`로 처리해 모델 hook과 모순되지 않게 한다.
- [ ] 핵심 고객의 담보는 `[표준]` 분석 상세와 호환 `InsuranceDetail`을 정확한 이름으로 조회하고 `analysis_detail_override`만 설정한다.
- [ ] 증권/담보 계산은 기존 모델 계산 함수를 호출해 대시보드·히트맵·비교가 같은 원자료를 사용하게 한다.
- [ ] 공유 고객 2명은 기존 UUID·만료 규칙과 현재 동의 버전을 사용하고, 예약 링크는 기존 토큰 생성 함수를 재사용한다.
- [ ] 명령 출력에는 생성 개수, 대표 고객 ID, 안전한 공개 경로만 출력한다. 비밀번호·토큰 원문·고객 전화는 출력하지 않는다.
- [ ] 테스트를 통과시킨다.

```bash
python manage.py test inpa.analysis.test_showcase_seed
python manage.py test inpa.analysis
```

- [ ] 커밋 권한이 승인된 실행 방식이면 이 단계만 커밋한다.

```bash
git add inpa_be/inpa/analysis/management/commands/seed_showcase.py \
  inpa_be/inpa/analysis/test_showcase_seed.py
git commit -m "feat(시연): 전용 계정 초기화 명령 추가"
```

---

## Task 6: API 소유 격리와 실제 흐름 통합 검증

**Files:**

- Modify: `inpa_be/inpa/analysis/test_showcase_seed.py`
- Modify only if a verified defect exists: owner-scoped views/serializers involved in the failing test

**Steps:**

- [ ] 시연 계정 로그인 성공, 일반 계정 로그인 실패가 아니라 각자 정상 인증됨을 확인한다.
- [ ] 일반 사용자가 시연 고객·증권·일정·알림 ID를 직접 넣어 GET/PATCH/DELETE하면 404인지 확인한다.
- [ ] 시연 계정이 일반 사용자 행을 같은 방식으로 요청해도 404인지 확인한다.
- [ ] 관리자는 기존 정책대로 관리 목적 조회가 가능하지만 시연 계정이 관리자 API에는 접근할 수 없는지 확인한다.
- [ ] 핵심 API를 실제 APIClient로 호출한다.

  - 홈 대시보드와 최근 6개월 목표
  - 고객 단계별/목록 count 50
  - 핵심 고객 상세, 증권, 보장 한눈표
  - 증권 A/증권 B 비교
  - 일정 30, 예약 요청 5, 알림 12
  - 공개 공유 GET 2건, 공개 예약 GET 1건

- [ ] 허용된 고객 단계 이동·메모 수정·태그 추가·일정 추가가 성공하고, 다음 `seed_showcase --apply`에서 원래 상태로 복구되는지 확인한다.
- [ ] 공유/예약 공개 응답에 이메일, 실제 설정 값, 내부 표식, 다른 고객 정보가 없는지 검사한다.

```bash
cd inpa_be
python manage.py test inpa.analysis.test_showcase_seed.ShowcaseApiIntegrationTests
```

- [ ] 실제 결함을 고친 경우 해당 파일과 회귀 테스트만 별도 커밋하고, 결함이 없으면 테스트 추가 커밋만 만든다.

```bash
git add inpa_be/inpa/analysis/test_showcase_seed.py
git commit -m "test(시연): 소유 격리와 주요 화면 API 검증"
```

---

## Task 7: 전체 자동 검증과 독립 리뷰

**Files:**

- Review: all files changed by Tasks 1-6

**Steps:**

- [ ] 시연 데이터 금칙 문자열과 비밀 설정 형태를 검사한다. 사용자 확정 비밀번호가 저장소에 0건이어야 한다.

```bash
git diff --check
rg -n "\\[DEMO\\]|\\[촬영\\]|데모|촬영용|sample|dummy" \
  inpa_be/inpa/analysis/showcase_data.py
rg -n "SHOWCASE_ACCOUNT_(EMAIL|PASSWORD)" \
  inpa_be/config/settings/base.py inpa_be/.env.example render.yaml \
  inpa_be/inpa/analysis/management/commands/seed_showcase.py
```

- [ ] 위 검색 결과를 사람이 검토해 이메일은 서버 설정 참조만, 비밀번호는 빈 기본값/설정 참조만 존재하는지 확인하고 gitleaks를 실행한다.

```bash
gitleaks detect --source . --no-banner
```

- [ ] migration과 Django 설정을 검사한다.

```bash
cd inpa_be
python manage.py makemigrations --check
python manage.py migrate
python manage.py check --deploy
```

- [ ] 전체 백엔드 테스트를 실행한다.

```bash
python manage.py test inpa
```

- [ ] 프런트 변경이 없어도 실제 계약 회귀를 위해 빌드한다.

```bash
cd ../inpa_fe
npm run build
```

- [ ] `superpowers:requesting-code-review`로 정확성, 보안, 소유 격리, 운영 통계, 개인정보, UX 관점 독립 리뷰를 받고 Critical/Important를 모두 해소한다.
- [ ] `superpowers:verification-before-completion`으로 최신 출력만 근거로 완료 여부를 판단한다.
- [ ] 사용자 비밀번호를 넣지 않은 임시 로컬 설정으로 `seed_showcase --apply`를 실제 실행하고 DB SELECT/API count를 확인한 뒤 `--purge --apply`로 제거한다.

---

## Task 8: 브라우저 시각 검증

**Files:**

- No source changes expected
- QA artifacts only in a temporary directory, never committed

**Steps:**

- [ ] 로컬 서버를 실행하고 브라우저 스킬로 시연 계정 로그인부터 검증한다.
- [ ] 데스크톱과 모바일에서 아래 화면을 확인한다.

  - 홈 대시보드
  - `/customers` 단계별·목록
  - 핵심 고객 8명의 상세·보장 한눈표
  - 여러 증권 비교
  - `/schedule`
  - 알림
  - 공개 `/s/<token>`
  - 공개 `/b/<token>`

- [ ] 빈 상태, 잘린 카드, 중복 이름, 날짜 모순, 부자연스러운 메모, 내부 표식이 있으면 데이터 명세를 고치고 Task 4-7 검증을 다시 수행한다.
- [ ] Network 패널 또는 서버 mock 기록으로 외부 AI·이메일·Google·파일 저장·주문·쿠폰 호출이 0건임을 재확인한다.

---

## Task 9: PR과 운영 배포 전 승인 지점

**Files:**

- Git metadata only

**Steps:**

- [ ] `git fetch origin` 후 `origin/master..HEAD`와 `git diff --stat origin/master...HEAD`를 확인한다.
- [ ] 계획 범위 파일만 커밋됐고 다른 세션의 파일이 섞이지 않았는지 확인한다.
- [ ] 승인된 경우 브랜치를 push하고 draft PR을 만든다.
- [ ] GitHub Actions의 백엔드 테스트, 프런트 빌드, gitleaks가 모두 통과할 때까지 확인한다.
- [ ] PM에게 아래 실제 결과를 보고하고 **운영 merge/deploy 명시 승인**을 요청한다.

  - 변경 파일과 기능 요약
  - 전체 테스트/빌드 수치
  - Critical/Important 리뷰 결과
  - DB migration 영향과 rollback
  - 시연 자료 정확한 개수
  - 공용 자료 fingerprint 불변 결과
  - 미검증 항목

- [ ] 승인 전에는 PR을 merge하지 않고 Render 운영 설정도 변경하지 않는다.

---

## Task 10: 운영 반영, 계정 생성, 사후 검증

**Prerequisite:** PM의 별도 운영 배포 승인.

**Rollback:**

```bash
python manage.py seed_showcase --purge --apply
```

필요 시 Render의 이전 이미지로 되돌리고 migration은 additive Boolean 필드이므로 우선 남겨도 기존 서비스 동작에 영향이 없다.

**Steps:**

- [ ] Render 운영 비밀 설정에 `SHOWCASE_ACCOUNT_EMAIL`과 `SHOWCASE_ACCOUNT_PASSWORD`를 입력한다. 값은 출력·스크린샷·로그에 남기지 않는다.
- [ ] 승인된 PR을 merge해 Render 자동 배포를 시작한다.
- [ ] Render 배포가 Live이고 `/healthz/`가 200인지 확인한다.
- [ ] 운영 DB migration `0016_profile_is_showcase` 적용 여부를 SELECT로 확인한다.
- [ ] 생성 전 대상 계정 부재와 공용 테이블 fingerprint/count를 기록한다.
- [ ] Render Web Shell에서 `python manage.py seed_showcase --apply`를 한 번 실행한다.
- [ ] 계정과 수량을 SELECT로 확인한다. 명령을 두 번째 실행해 같은 최종 상태인지 확인한다.
- [ ] 실제 운영 로그인 API와 브라우저에서 ID `test@inpa.kr` 및 별도 전달된 비밀번호로 로그인한다.
- [ ] Task 8의 주요 화면을 운영 데스크톱/모바일에서 재검증한다.
- [ ] 시연 계정으로 차단된 외부 작동을 호출해 403 또는 존재 비노출 200을 확인하고, 외부 side effect가 0건인지 서버 기록으로 확인한다.
- [ ] 별도 일반 계정으로 시연 고객 ID 접근이 404인지 확인한다.
- [ ] 공지·FAQ·블로그·요금제 공개 API와 전역 표준 fingerprint가 생성 전과 동일한지 확인한다.
- [ ] 실제 사용자 운영 지표 화면에서 시연 계정 활동이 제외되는지 확인한다.
- [ ] 오류가 있으면 즉시 `seed_showcase --purge --apply` 후 이전 Render 이미지로 rollback한다.

---

## Task 11: 배포 후 문서와 인수인계

**Files:**

- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify if needed: `CHANGELOG.md`

**Steps:**

- [ ] 기능이 merge되고 운영 검증까지 끝난 뒤에만 PM용 `README.md`와 agent SSOT `AGENTS.md`를 갱신한다.
- [ ] README에는 운영자가 알아야 할 초기화/삭제 방법과 외부 작동 제한만 쉬운 한국어로 기록하고, 비밀번호는 기록하지 않는다.
- [ ] AGENTS에는 `is_showcase`, 중앙 통계 제외, 외부 작동 차단, seed/purge 명령과 운영 검증 결과를 밀도 높게 기록한다.
- [ ] 문서 변경만 별도 Conventional Commit으로 만들고 CI/자동 배포 상태를 확인한다.
- [ ] 최종 보고는 아래 형식을 지킨다.

```text
Changed: [시연 계정, 합성 자료, 격리·차단, 초기화 명령]
Verified by: [전체 테스트, 빌드, 운영 API/브라우저, DB fingerprint]
Result: [실제 수량과 주요 응답]
Unverified: [없으면 없음]
```
