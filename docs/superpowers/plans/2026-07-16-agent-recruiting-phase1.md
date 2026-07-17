# 설계사 영입 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkboxes so progress can be tracked. Before implementation, use `superpowers:using-git-worktrees`; before completion, use `superpowers:verification-before-completion` and `superpowers:requesting-code-review`.

**Goal:** 경력 보험설계사를 관계형 링크로 영입하고, 실제 팀 합류 뒤 1·4·8·13주 정착을 돕는 독립 기능을 출시한다. 보험가입자인 고객 데이터와는 모델·API·검색·통계·화면을 완전히 분리하고, 첫 실제 팀원 합류 시 별도 결제 없이 `Manager` 역할을 자동 활성화한다.

**Architecture:** Django에 독립 앱 `inpa.recruiting`을 추가해 영입 페이지, 출처 링크, 지원자, 동의, 활동 이력, 정착 체크, 영입 전용 분석 이벤트를 소유한다. 기존 `accounts`에는 팀 관계를 만드는 단일 서비스와 Manager 역할 시각만 추가하고, 기존 일반 팀 초대 토큰은 그대로 유지한다. 기존 `billing`은 Plus·legacy Manager·Super가 같은 팀 기능 권한을 갖도록 능력값만 정렬하며, 승격 시 구독 행은 절대 수정하지 않는다. Next.js에는 인증 화면 `/recruiting`, 공개 지원 페이지 `/r/[token]`, 본인 관리 페이지 `/r/manage/[token]`, 최종 합류 페이지 `/recruiting/join/[token]`을 새로 둔다.

**Tech Stack:** Django 4.2 · DRF · PostgreSQL/SQLite · Django signed tokens · Next.js 16 App Router · React 19 · TypeScript · Tailwind v4 · 기존 `lib/api.ts`/`lib/adminApi.ts` 단일 API 게이트 · Django unittest · 브라우저 실동작 검증.

**Approved design:** [`docs/superpowers/specs/2026-07-16-agent-recruiting-design.md`](/Users/kyungsbook/Desktop/inpa/docs/superpowers/specs/2026-07-16-agent-recruiting-design.md)

## Global Constraints

- **고객 절대 분리:** `RecruitingCandidate`에서 `Customer`로 향하는 FK·OneToOne·M2M·범용 객체 연결을 만들지 않는다. 이름·전화번호가 같아도 고객으로 합치거나 복사하지 않는다.
- **고객 코드 무변경:** 아래 경로는 이 기능 구현 커밋에서 수정하지 않는다.
  - `inpa_be/inpa/customers/**`
  - `inpa_fe/app/customers/**`
  - `inpa_fe/app/customer/**`
  - 기존 공개 고객 경로 `/s`, `/d`, `/c`, `/b`, `/p`
- **기존 초대 호환:** `inpa_be/inpa/accounts/invite.py`의 `TEAM_INVITE_SALT`, 토큰 내용, 7일 유효기간과 기존 `/manager/invite-*` API 계약을 바꾸지 않는다. 영입 합류 토큰은 별도 salt와 payload를 사용한다.
- **구독 불변:** 자동 승격은 `Subscription.plan`, `status`, `starts_at`, `expires_at`, 쿠폰, 사용량을 수정하지 않는다. Plus와 Manager의 판매가는 모두 19,900원(VAT 별도)으로 보이되, 신규 구매 UI에는 Plus 하나만 제공하고 기존 Manager 구독은 계속 유효하게 유지한다.
- **수동 단계 이동 금지:** `team_join`은 지원자 카드에서 고를 수 없다. 실제 계정이 지원자 전용 합류 링크를 수락해 `Profile.manager`가 연결될 때만 서버가 기록한다.
- **Manager 역할 유지:** 팀원이 나중에 0명이 되어도 `manager_promoted_at`은 지우지 않는다. Plus가 만료되어도 역할·영입 데이터는 보존하고, Plus 재개 시 팀 도구 권한만 다시 열린다.
- **공유 동의 불변:** 팀 연결 시 `Profile.manager_share_level`을 채우거나 바꾸지 않는다. 기존 팀 KPI 공유 동의 절차가 그대로 권한의 근거다.
- **PII 최소화:** 영입 이벤트·알림·서버 로그에는 지원자 이름·전화번호·자유 입력 내용을 담지 않는다. 운영자 목록은 연락처를 가린 값만 반환한다.
- **보수적 공개:** `RECRUITING_ENABLED`는 기본 `False`다. preview에서만 먼저 열고, 켜진 경우에만 메뉴·인증 API·공개 링크가 함께 동작한다. 꺼진 상태의 직접 API 접근은 404다.
- **후보 본인 선택 증명:** 전화번호 일치만으로 기존 신청의 리더를 바꾸거나 연락을 중단할 수 없다. 이전 신청 때 받은 `manage_token`을 함께 제시한 후보만 기존 리더 유지·새 리더 변경을 선택할 수 있다.
- **첫 출시의 공개 범위:** 네 탭은 모두 실제로 동작한다. `캠페인 링크` 탭은 관계형 기본 링크의 켜기·끄기·재발급·방문/지원 수 확인까지 제공한다. Threads·TikTok·Instagram·사람인·잡코리아별 링크 생성과 인파 자체 광고 유입은 Phase 2 별도 승인 계획에서 같은 `RecruitingCampaign` 구조를 확장한다.
- **실행 환경:** 현재 작업 폴더의 랜딩 관련 미완료 변경을 건드리지 않는다. 구현은 최신 깨끗한 기준점에서 별도 worktree로 시작한다. 가격 화면 작업은 현재 랜딩 변경이 커밋된 기준점을 확보한 뒤 가장 마지막 독립 커밋으로 수행한다.
- **품질:** 로딩·빈 상태·오류·모바일·키보드 조작·중복 제출·만료 토큰·탈퇴 요청을 첫 출시에 포함한다. 사용자 화면에는 `리드`, `파이프라인`, `퍼널`, `컴플라이언스`, `승격 조건` 같은 내부 용어를 쓰지 않는다.
- **배포:** preview까지 검증한다. 프로덕션 merge/deploy는 PM의 별도 명시 승인 뒤에만 한다.

## 변경 경계 지도

| 구분 | 경로 | 허용 변경 |
|---|---|---|
| 신규 BE 소유 영역 | `inpa_be/inpa/recruiting/**` | 모델·서비스·공개/인증/운영자 API·테스트 전체 |
| BE 필수 접점 | `config/settings/base.py`, `config/urls.py` | 앱·URL·throttle·보존기간 설정 |
| 팀 관계 접점 | `accounts/models.py`, 신규 `accounts/team.py`, `accounts/serializers.py`, `accounts/views.py`, `accounts/urls.py` | 승격 시각, 공통 팀 연결 서비스, 승격 확인 API, 기존 초대 생성 경로의 서비스 사용 |
| 요금 접점 | `billing/credit.py`, `billing/management/commands/seed_billing.py`, 관련 테스트 | Plus·legacy Manager·Super의 팀 기능 권한 일치 |
| 알림/일일 작업 접점 | `notifications/models.py`, `notifications/views.py`, `notifications/jobs.py`, 관련 테스트 | 영입 알림 유형·읽지 않은 수·정착 알림·보존 정리 |
| 신규 FE 소유 영역 | `app/recruiting/**`, `app/r/**`, `components/recruiting/**` | 인증/공개/합류/정착 UI |
| FE 필수 접점 | `lib/api.ts`, `lib/adminApi.ts`, 신규 `lib/auth-return.ts`, `components/app-nav.tsx`, `components/bottom-nav.tsx`, `app/home/page.tsx`, `app/notifications/page.tsx`, `app/manager/page.tsx` | 타입·API·메뉴·알림·기존 초대 UI의 연결 변경 |
| 운영자 FE | `app/admin/recruiting/page.tsx`, `app/admin/layout.tsx` | 영입 현황·문구·정리 운영 |
| 가격 접점, 마지막 | `components/brand-story-sections.tsx`, `components/upgrade-modal.tsx`, 필요 시 `components/landing-sections.tsx` | Plus 단일 구매, Manager 자동 활성화 설명 |
| 절대 비접점 | 고객·보험·분석·예약·일정의 모델과 집계 | 수정 금지 |

## 고정 API 계약

### 인증 설계사 API

| Method | URL | 용도 |
|---|---|---|
| `GET` | `/api/v1/recruiting/summary/` | 내 단계별 수, 다음 연락, 정착 요약 |
| `GET/PATCH` | `/api/v1/recruiting/page/` | 내 영입 페이지 문구·게시 상태 |
| `GET` | `/api/v1/recruiting/templates/` | 운영자가 관리하는 지원/FAQ 문구 |
| `GET/PATCH` | `/api/v1/recruiting/campaign/` | 관계형 기본 링크, 활성화·재발급·성과 |
| `POST` | `/api/v1/recruiting/campaign/copied/` | 개인 링크 복사를 PII 없이 기록 |
| `GET` | `/api/v1/recruiting/candidates/` | 내 지원자 목록, 후보의 자발적 신청만 생성 |
| `GET/PATCH` | `/api/v1/recruiting/candidates/{id}/` | 내 지원자 상세·허용 단계/다음 행동 수정 |
| `POST` | `/api/v1/recruiting/candidates/{id}/team-invite/` | 실제 합류용 서명 링크 발급 |
| `GET/PATCH` | `/api/v1/recruiting/settlements/` | 1·4·8·13주 정착 확인 |
| `GET` | `/api/v1/recruiting/team-summary/` | 관리자가 보는 팀원의 영입 집계, 개인 상세 없음 |
| `POST` | `/api/v1/auth/manager-promotion/ack/` | 최초 Manager 안내 확인 |

### 공개/로그인 경계 API

| Method | URL | 용도 |
|---|---|---|
| `GET/POST` | `/api/v1/r/{campaign_uuid}/` | 공개 영입 페이지 조회·지원 |
| `GET/POST` | `/api/v1/r/manage/{manage_uuid}/` | 지원자가 자신의 요청 확인·연락 중단/삭제 요청 |
| `POST` | `/api/v1/r/choice/{signed_token}/` | 기존 본인 관리 링크를 확인한 후보의 리더 유지·변경 선택 |
| `GET` | `/api/v1/recruiting/join/{signed_token}/` | 합류할 리더의 공개 가능 정보만 확인 |
| `POST` | `/api/v1/recruiting/join/{signed_token}/accept/` | 로그인 계정의 최종 리더 선택·팀 합류 |

### 운영자 API

| Method | URL | 용도 |
|---|---|---|
| `GET` | `/api/v1/admin/recruiting/summary/` | 방문·지원·합류·정착·승격 집계 |
| `GET` | `/api/v1/admin/recruiting/candidates/` | 가린 연락처의 보존/정리 대상 목록 |
| `POST` | `/api/v1/admin/recruiting/candidates/{id}/purge/` | 즉시 비식별 또는 삭제 |
| `GET/POST/PATCH` | `/api/v1/admin/recruiting/templates/` | 지원 문구·FAQ 관리 |
| `GET` | `/api/v1/admin/recruiting/promotions/` | Manager 자동 활성화 이력 |
| `GET` | `/api/v1/admin/recruiting/audit/` | PII 없는 담당 변경·연락 중단·삭제 감사 이력 |

## 데이터 계약

### `RecruitingCandidate.stage`

```text
new          새 지원
contact      연락
conversation 대화·면담
preparing    위촉 준비
team_join    팀 합류, 서버 전용
recontact    다시 연락
ended        종료
```

허용 전이는 아래 하나의 서비스에서만 판정한다.

```python
ALLOWED_STAGE_TRANSITIONS = {
    "new": {"contact", "recontact", "ended"},
    "contact": {"conversation", "recontact", "ended"},
    "conversation": {"preparing", "recontact", "ended"},
    "preparing": {"conversation", "recontact", "ended"},
    "recontact": {"contact", "ended"},
    "team_join": {"ended"},
    "ended": {"recontact"},
}
```

`team_join`은 이 표를 거치지 않고 `accept_team_join()` 내부에서만 설정한다.

### 정착 주차

| 주차 | 기준일 | 설계사 화면 질문 |
|---|---:|---|
| 1주 | 합류일 + 7일 | 첫 주에 막힌 일이 있었나요? |
| 4주 | 합류일 + 28일 | 혼자 해결하기 어려운 일이 있나요? |
| 8주 | 합류일 + 56일 | 활동 흐름이 자리를 잡았나요? |
| 13주 | 합류일 + 91일 | 다음 3개월 목표를 같이 정했나요? |

상태는 `active`(계속 활동), `support_needed`(도움 필요), `stopped`(활동 중단) 세 가지다. 막힘과 다음 지원은 자유 입력이 아닌 선택형 enum으로 저장해 PII·민감정보가 쌓이지 않게 한다.

---

## Task 0: 깨끗한 실행 기준점과 회귀 잠금 만들기

**Files:**
- Read: `/Users/kyungsbook/Desktop/inpa/AGENTS.md`
- Read: `/Users/kyungsbook/Desktop/inpa/inpa_fe/AGENTS.md`
- Read: `inpa_fe/node_modules/next/dist/docs/01-app/01-getting-started/04-linking-and-navigating.md`
- Read: `inpa_fe/node_modules/next/dist/docs/01-app/01-getting-started/10-error-handling.md`
- Read: `inpa_fe/node_modules/next/dist/docs/01-app/01-getting-started/14-metadata-and-og-images.md`
- Read: `inpa_fe/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/loading.md`
- Read: `inpa_fe/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md`
- Create: implementation worktree through `superpowers:using-git-worktrees`

- [ ] **Step 0.1: 현재 변경을 기록하고 건드리지 않을 파일을 고정한다.**

Run in the original workspace:

```bash
git status --short
git log --oneline -10
git diff --name-only
git ls-files --others --exclude-standard
```

Expected: 현재 랜딩 관련 수정·미추적 파일이 보이며, 구현 에이전트는 이를 stage·restore·stash하지 않는다.

- [ ] **Step 0.2: 별도 worktree를 만든다.**

`superpowers:using-git-worktrees` 지침에 따라 `codex/agent-recruiting-phase1` 브랜치를 만들고, 현재 랜딩 변경이 포함된 최신 깨끗한 commit을 기준으로 사용한다. 원래 폴더가 dirty인 상태에서 직접 구현하지 않는다.

- [ ] **Step 0.3: 기준 회귀 검사를 실행한다.**

```bash
cd inpa_be
python manage.py check
python manage.py test inpa.accounts inpa.billing inpa.notifications inpa.customers
cd ../inpa_fe
npm run lint:copy
npm run build
```

Expected: 구현 전 기존 기준점이 모두 통과한다. 실패가 있으면 새 기능과 분리해 원인을 기록하고, 기준 실패를 새 기능 커밋에 섞지 않는다.

- [ ] **Step 0.4: 고객 영역 해시를 저장한다.**

```bash
git rev-parse HEAD > /tmp/inpa-recruiting-base.txt
git diff --exit-code HEAD -- inpa_be/inpa/customers inpa_fe/app/customers inpa_fe/app/customer
```

Expected: 두 번째 명령 출력 없음, exit 0.

**Commit:** 없음. 이 Task는 안전 기준만 만든다.

---

## Task 1: 독립 `recruiting` 앱과 스키마를 TDD로 추가하기

**Files:**
- Create: `inpa_be/inpa/recruiting/__init__.py`
- Create: `inpa_be/inpa/recruiting/apps.py`
- Create: `inpa_be/inpa/recruiting/models.py`
- Create: `inpa_be/inpa/recruiting/admin.py`
- Create: `inpa_be/inpa/recruiting/consent_texts.py`
- Create: `inpa_be/inpa/recruiting/migrations/0001_initial.py`
- Create: `inpa_be/inpa/recruiting/migrations/0002_seed_copy_templates.py`
- Create: `inpa_be/inpa/recruiting/tests/__init__.py`
- Create: `inpa_be/inpa/recruiting/tests/test_models.py`
- Modify: `inpa_be/config/settings/base.py`

- [ ] **Step 1.1: 실패하는 모델 격리 테스트를 작성한다.**

`test_models.py`에서 다음을 증명한다.

```python
from django.db.models.fields.related import RelatedField
from django.test import TestCase

from inpa.recruiting.models import RecruitingCandidate


class RecruitingModelIsolationTests(TestCase):
    def test_candidate_has_no_customer_relation(self):
        related_models = {
            field.related_model._meta.label_lower
            for field in RecruitingCandidate._meta.get_fields()
            if isinstance(field, RelatedField) and field.related_model
        }
        self.assertNotIn("customers.customer", related_models)
```

Run:

```bash
cd inpa_be
python manage.py test inpa.recruiting.tests.test_models
```

Expected: `ModuleNotFoundError` 또는 모델 없음으로 실패.

- [ ] **Step 1.2: 아래 모델을 additive migration으로 구현한다.**

`RecruitingCopyTemplate`

```python
class Kind(models.TextChoices):
    HEADLINE = "headline", "첫 문장"
    SUPPORT = "support", "정착 지원"
    FAQ = "faq", "자주 묻는 질문"
    SHARE = "share", "공유 문구"

code = models.SlugField(max_length=60, unique=True)
kind = models.CharField(max_length=20, choices=Kind.choices)
title = models.CharField(max_length=80)
body = models.CharField(max_length=300)
is_active = models.BooleanField(default=True)
sort_order = models.PositiveSmallIntegerField(default=0)
created_at = models.DateTimeField(auto_now_add=True)
updated_at = models.DateTimeField(auto_now=True)
```

`RecruitingPage`

```python
owner = models.OneToOneField(
    settings.AUTH_USER_MODEL,
    on_delete=models.CASCADE,
    related_name="recruiting_page",
)
headline_template = models.ForeignKey(
    RecruitingCopyTemplate,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="headline_pages",
)
activity_region = models.CharField(max_length=60, blank=True)
is_published = models.BooleanField(default=False)
templates = models.ManyToManyField(RecruitingCopyTemplate, blank=True)
created_at = models.DateTimeField(auto_now_add=True)
updated_at = models.DateTimeField(auto_now=True)
```

`RecruitingCampaign`

```python
class Channel(models.TextChoices):
    RELATIONSHIP = "relationship", "개인 소개"
    THREADS = "threads", "Threads"
    TIKTOK = "tiktok", "TikTok"
    INSTAGRAM = "instagram", "Instagram"
    SARAMIN = "saramin", "사람인"
    JOBKOREA = "jobkorea", "잡코리아"
    INPA_CONTENT = "inpa_content", "인파 콘텐츠"

page = models.ForeignKey(RecruitingPage, on_delete=models.CASCADE, related_name="campaigns")
name = models.CharField(max_length=60)
channel = models.CharField(max_length=20, choices=Channel.choices)
public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
is_active = models.BooleanField(default=True)
created_at = models.DateTimeField(auto_now_add=True)
updated_at = models.DateTimeField(auto_now=True)

class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=("page", "channel"),
            condition=models.Q(channel="relationship", is_active=True),
            name="uniq_recruiting_relationship_campaign",
        )
    ]
```

`RecruitingCandidate`

```python
owner = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.CASCADE,
    related_name="recruiting_candidates",
)
campaign = models.ForeignKey(
    RecruitingCampaign,
    on_delete=models.SET_NULL,
    null=True,
    related_name="candidates",
)
name = models.CharField(max_length=30)
phone = models.CharField(max_length=20, db_index=True)  # 저장 전 숫자형 정규화
career_band = models.CharField(max_length=20, choices=CareerBand.choices)
current_affiliation = models.CharField(max_length=100, blank=True)
region = models.CharField(max_length=60)
contact_window = models.CharField(max_length=20, choices=ContactWindow.choices)
submission_key = models.UUIDField(default=uuid.uuid4, db_index=True, editable=False)
audit_ref = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
identity_ref = models.UUIDField(default=uuid.uuid4, db_index=True, editable=False)
selection_status = models.CharField(
    max_length=20,
    choices=SelectionStatus.choices,
    default=SelectionStatus.ACTIVE,
)
stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.NEW)
next_action = models.CharField(max_length=30, choices=NextAction.choices, blank=True)
next_action_at = models.DateTimeField(null=True, blank=True)
last_contacted_at = models.DateTimeField(null=True, blank=True)
joined_user = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="accepted_recruiting_candidates",
)
joined_at = models.DateTimeField(null=True, blank=True)
ended_at = models.DateTimeField(null=True, blank=True)
retention_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
contact_opt_out_at = models.DateTimeField(null=True, blank=True)
manage_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
created_at = models.DateTimeField(auto_now_add=True)
updated_at = models.DateTimeField(auto_now=True)

class Meta:
    indexes = [
        models.Index(fields=("owner", "stage", "next_action_at")),
        models.Index(fields=("owner", "phone")),
    ]
    constraints = [
        models.UniqueConstraint(
            fields=("campaign", "submission_key"),
            name="uniq_recruiting_campaign_submission",
        )
    ]
```

`CareerBand`는 `under_1`, `1_3`, `3_5`, `5_10`, `10_plus`; `ContactWindow`는 `morning`, `afternoon`, `evening`, `anytime`; `NextAction`은 `call`, `message`, `meeting`, `follow_up`, `none`으로 고정한다. `SelectionStatus`는 `pending`, `active`, `replaced`, `declined`이며, 설계사 API에는 `active` 지원자만 나타난다.

`RecruitingConsentLog`

```python
candidate = models.ForeignKey(RecruitingCandidate, on_delete=models.CASCADE, related_name="consents")
scope = models.CharField(max_length=30, default="recruiting_contact")
doc_version = models.CharField(max_length=30)
agreed_at = models.DateTimeField(auto_now_add=True)
revoked_at = models.DateTimeField(null=True, blank=True)
ip_address = models.GenericIPAddressField(null=True, blank=True)
```

`RecruitingActivity`

```python
candidate = models.ForeignKey(
    RecruitingCandidate,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="activities",
)
candidate_ref = models.UUIDField(db_index=True, editable=False)
actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
event_type = models.CharField(max_length=30, choices=EventType.choices)
from_stage = models.CharField(max_length=20, blank=True)
to_stage = models.CharField(max_length=20, blank=True)
created_at = models.DateTimeField(auto_now_add=True)
```

`SettlementCheck`

```python
candidate = models.ForeignKey(RecruitingCandidate, on_delete=models.CASCADE, related_name="settlement_checks")
week = models.PositiveSmallIntegerField(choices=((1, "1주"), (4, "4주"), (8, "8주"), (13, "13주")))
due_on = models.DateField(db_index=True)
state = models.CharField(max_length=20, choices=State.choices, default=State.ACTIVE)
blocker = models.CharField(max_length=30, choices=Blocker.choices, blank=True)
next_support = models.CharField(max_length=30, choices=NextSupport.choices, blank=True)
completed_at = models.DateTimeField(null=True, blank=True)
created_at = models.DateTimeField(auto_now_add=True)
updated_at = models.DateTimeField(auto_now=True)

class Meta:
    constraints = [
        models.UniqueConstraint(fields=("candidate", "week"), name="uniq_candidate_settlement_week")
    ]
```

`Blocker`는 `customer_prospecting`, `consultation_prep`, `product_understanding`, `work_tools`, `time_management`, `organization_adjustment`, `personal`, `none`; `NextSupport`는 `consultation_prep`, `training`, `activity_plan`, `tool_help`, `leader_meeting`, `schedule_only`, `close`로 고정한다. 화면 라벨은 승인 설계의 `고객 발굴`, `상담 준비`, `상품 이해`, `업무 도구`, `시간 관리`, `조직 적응`, `개인 사정`, `해당 없음`과 1:1로 연결한다.

`RecruitingEvent`

```python
owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recruiting_events")
campaign = models.ForeignKey(RecruitingCampaign, on_delete=models.SET_NULL, null=True, blank=True)
candidate = models.ForeignKey(RecruitingCandidate, on_delete=models.SET_NULL, null=True, blank=True)
event_type = models.CharField(max_length=40, choices=EventType.choices, db_index=True)
channel = models.CharField(max_length=20, choices=RecruitingCampaign.Channel.choices, blank=True)
metadata = models.JSONField(default=dict, blank=True)  # enum/count/id만 허용
created_at = models.DateTimeField(auto_now_add=True, db_index=True)
```

`EventType`은 `page_published`, `link_copied`, `page_view`, `application_submitted`, `first_contact`, `conversation_started`, `preparing_started`, `team_join`, `settlement_completed`, `manager_promoted`로 고정한다. 기존 고객 `NorthStarEvent` 이름을 재사용하지 않는다.

`metadata` serializer/service는 허용 키 `source`, `week`, `state`, `previous_stage`만 받도록 한다. 이름·전화·소속·지역 문자열은 거부한다.

`RecruitingActivity`는 분쟁·권한 감사 기록이라 상태 변경 transaction 안에서 `candidate_ref=candidate.audit_ref`와 함께 필수로 저장한다. 후보가 삭제되면 FK만 null이 되고 무작위 ref·actor·enum 단계·시각은 남는다. 이름·전화·owner 변경 상대는 넣지 않는다. `RecruitingEvent`는 분석용이므로 `transaction.on_commit()`의 best-effort 함수로 생성하고, 실패해도 지원·단계·합류·정착 본 동작을 실패시키지 않는다.

- [ ] **Step 1.3: 동의 문구를 한 파일에서 버전 관리한다.**

`consent_texts.py`:

```python
RECRUITING_CONSENT_VERSION = "2026-07-16-v1"
RECRUITING_CONTACT_CONSENT = (
    "영입 상담을 위해 이름, 연락처, 경력, 현재 소속, 활동 지역, 연락 가능 시간을 "
    "제공하며 담당 설계사가 연락하는 데 동의합니다. 팀에 합류하지 않고 상담이 끝난 정보는 "
    "종료일 또는 마지막 활동일 중 늦은 날부터 180일 뒤 정리됩니다. 신청 관리 화면에서 언제든 "
    "연락 중단과 정보 정리를 요청할 수 있습니다."
)
```

문구의 수집 목적·보유기간이 실질적으로 바뀌면 버전을 함께 올리고, 이전 동의를 새 지원에 재사용하지 않는다.

- [ ] **Step 1.4: 기본 문구를 자연키 data migration으로 넣는다.**

`0002_seed_copy_templates.py`는 `code`로 `update_or_create`하지 않고 `get_or_create(code=code, defaults=defaults)`를 사용해 운영자 수정이 배포 때 덮이지 않게 한다. 기본 세트:

```python
DEFAULTS = (
    ("headline-long-growth", "headline", "함께 오래 성장하기", "함께 오래 일할 동료를 찾고 있어요.", 10),
    ("support-first-week", "support", "첫 주 동행", "첫 주에는 고객 만남과 업무 흐름을 함께 정리해요.", 10),
    ("support-field", "support", "현장 지원", "혼자 막히는 순간이 없도록 필요한 자리에서 같이 움직여요.", 20),
    ("support-growth", "support", "13주 성장 점검", "1·4·8·13주에 활동 흐름을 확인하고 다음 목표를 같이 정해요.", 30),
    ("faq-contract", "faq", "위촉 전에도 이야기할 수 있나요?", "현재 소속과 일정에 맞춰 부담 없이 먼저 대화할 수 있어요.", 10),
    ("faq-data", "faq", "남긴 정보는 어디에 쓰이나요?", "영입 상담 연락과 일정 조율에만 사용해요.", 20),
    ("share-known", "share", "아는 설계사에게", "지금보다 오래 성장할 수 있는 환경을 함께 이야기해보고 싶어 링크를 보냅니다.", 10),
)
```

- [ ] **Step 1.5: 모델 테스트를 보강하고 통과시킨다.**

테스트 항목:

- 관계형 기본 캠페인은 페이지당 하나만 생성 가능
- 같은 `submission_key` 재시도는 같은 지원자와 같은 성공 응답으로 idempotent
- 같은 전화번호라도 새 `submission_key`면 별도 지원 행이며, 기존 `manage_token`이 있을 때만 리더 선택 흐름으로 연결
- 다른 설계사는 같은 전화번호를 별도 보유 가능하고 서로의 상세를 볼 수 없음
- 유효한 기존 manage token으로 이어진 신청만 같은 비공개 `identity_ref`를 공유하고, 전화번호 일치만으로 identity를 합치지 않음
- 영입 데이터가 있는 User 탈퇴가 `PROTECT` 오류 없이 기존 계정 삭제 흐름대로 완료
- 정착 주차는 지원자별 중복 불가
- `RecruitingEvent.metadata` 허용 키 외 값 거부
- 모든 PII 모델은 `__str__`에서 이름·전화번호를 출력하지 않고 `candidate:{pk}` 형식만 반환
- 후보 삭제 뒤 `RecruitingActivity.candidate`는 null, 무작위 `candidate_ref`와 enum 감사 이력은 유지

Run:

```bash
cd inpa_be
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py test inpa.recruiting.tests.test_models
```

Expected: 새 migration 없음, migration 적용 성공, 테스트 통과.

- [ ] **Step 1.6: 이 Task만 커밋한다.**

```bash
git add inpa_be/inpa/recruiting inpa_be/config/settings/base.py
git commit -m "feat(recruiting): add isolated recruiting domain models"
```

---

## Task 2: 지원자 단계·공개 지원·연락 중단 서비스를 TDD로 구현하기

**Files:**
- Create: `inpa_be/inpa/recruiting/services.py`
- Create: `inpa_be/inpa/recruiting/serializers.py`
- Create: `inpa_be/inpa/recruiting/views.py`
- Create: `inpa_be/inpa/recruiting/public_views.py`
- Create: `inpa_be/inpa/recruiting/tokens.py` (후보 리더 선택 token만 먼저 구현)
- Create: `inpa_be/inpa/recruiting/urls.py`
- Create: `inpa_be/inpa/recruiting/tests/test_services.py`
- Create: `inpa_be/inpa/recruiting/tests/test_api.py`
- Create: `inpa_be/inpa/recruiting/tests/test_public_api.py`
- Modify: `inpa_be/config/urls.py`
- Modify: `inpa_be/config/settings/base.py`

- [ ] **Step 2.1: 실패하는 서비스 테스트를 작성한다.**

반드시 포함할 사례:

recruiting API test class는 기본 `@override_settings(RECRUITING_ENABLED=True)`로 실행하고, feature-off 한 건만 `False`로 다시 덮는다.

- `test_same_campaign_and_submission_key_is_idempotent`
- `test_same_owner_phone_with_new_submission_key_is_separate`
- `test_same_phone_under_another_owner_creates_separate_candidate`
- `test_phone_match_alone_cannot_change_or_stop_an_existing_application`
- `test_valid_prior_manage_token_offers_keep_or_switch_choice`
- `test_keep_choice_closes_only_the_new_pending_application`
- `test_switch_choice_closes_old_and_activates_new_without_revealing_new_leader`
- `test_owner_cannot_read_another_owners_candidate`
- `test_admin_does_not_bypass_candidate_service_view`
- `test_planner_cannot_create_candidate_without_public_consent_flow`
- `test_manual_patch_cannot_set_team_join`
- `test_replaced_or_opted_out_candidate_cannot_be_reactivated_by_previous_owner`
- `test_stage_change_writes_structured_activity`
- `test_public_duplicate_submit_returns_same_success_shape`
- `test_public_response_never_reveals_existing_owner_or_candidate`
- `test_public_failures_and_duplicate_paths_do_not_log_name_or_phone`
- `test_manage_token_can_stop_contact_and_scrub_pii`
- `test_joined_candidate_manage_token_cannot_unlink_authenticated_team_relation`
- `test_expired_or_disabled_campaign_has_positive_next_action_copy`
- `test_recruiting_endpoints_return_404_when_feature_is_disabled`

Run:

```bash
cd inpa_be
python manage.py test inpa.recruiting.tests.test_services inpa.recruiting.tests.test_public_api
```

Expected: 구현 전 실패.

- [ ] **Step 2.2: 전화번호 정규화와 단계 변경을 단일 서비스로 만든다.**

`services.py` 핵심 계약:

```python
import re
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("82"):
        digits = "0" + digits[2:]
    if len(digits) not in (10, 11):
        raise ValidationError("연락 가능한 휴대전화 번호를 확인해주세요.")
    return digits


@transaction.atomic
def transition_candidate(*, candidate, actor, to_stage, next_action="", next_action_at=None):
    locked = type(candidate).objects.select_for_update().get(pk=candidate.pk)
    if locked.selection_status != locked.SelectionStatus.ACTIVE or locked.contact_opt_out_at:
        raise ValidationError("현재 담당 중인 지원자만 다음 단계를 이어갈 수 있어요.")
    if to_stage == locked.Stage.TEAM_JOIN:
        raise ValidationError("팀 합류는 합류 링크를 수락하면 자동으로 기록돼요.")
    if to_stage not in ALLOWED_STAGE_TRANSITIONS[locked.stage]:
        raise ValidationError("현재 단계에서 선택할 수 있는 다음 흐름을 확인해주세요.")
    previous = locked.stage
    locked.stage = to_stage
    locked.next_action = next_action
    locked.next_action_at = next_action_at
    if to_stage == locked.Stage.CONTACT:
        locked.last_contacted_at = timezone.now()
    if to_stage == locked.Stage.ENDED:
        locked.ended_at = timezone.now()
        anchor = max(locked.ended_at, locked.last_contacted_at or locked.ended_at)
        locked.retention_expires_at = anchor + timedelta(days=settings.RECRUITING_RETENTION_DAYS)
    locked.save(update_fields=[
        "stage", "next_action", "next_action_at", "last_contacted_at",
        "ended_at", "retention_expires_at", "updated_at",
    ])
    RecruitingActivity.objects.create(
        candidate=locked,
        candidate_ref=locked.audit_ref,
        actor=actor,
        event_type=RecruitingActivity.EventType.STAGE_CHANGED,
        from_stage=previous,
        to_stage=to_stage,
    )
    return locked
```

`create_candidate_submission()`은 `(campaign, submission_key)`만 idempotency 기준으로 사용한다. 전화번호만 같다는 이유로 기존 행이나 `manage_token`을 반환하지 않는다. 후보가 새 submission key로 같은 owner에게 다시 신청하면 자동 병합하지 않고, owner의 자기 목록에서만 “같은 연락처 신청이 있어요” 표시를 제공한다.

새 active 신청은 `next_action=call`, `next_action_at=timezone.now()+timedelta(hours=24)`로 시작해 첫 연락 누락을 바로 잡는다. pending 선택 행은 다음 행동 알림 대상에서 제외하고, `switch_to_new`로 active가 되는 순간부터 24시간을 새로 계산한다.

공개 폼이 보내는 `prior_manage_token`이 유효하고, 정규화 전화번호가 그 기존 지원자와 일치할 때만 다음 분기를 허용한다.

- 같은 owner: 기존 행을 유지하고 동일 manage URL을 반환, 새 중복 행은 만들지 않음
- 다른 owner: 새 행은 기존 행의 비공개 `identity_ref`를 이어받고 `selection_status=pending`으로 생성한 뒤, 두 candidate id가 든 10분짜리 signed `choice_token` 반환
- `keep_current`: 새 pending 행을 `declined + ended`로 변경하고 system-stamped 보관 만료일 설정, 기존 행 유지
- `switch_to_new`: 기존 active 행을 `replaced + ended`로 바꾸고 이름·전화·소속·지역을 즉시 비식별하며 system-stamped 보관 만료일 설정, 새 행을 `active`로 변경한 뒤 새 owner에게만 알림
- prior token이 없거나 틀리면 다른 owner 중복 여부를 절대 알리지 않고 새 독립 신청으로 처리. 최종 팀 합류 때 다시 명시 확인

`choice_token`에는 candidate id 두 개와 version만 넣고 이름·전화·owner id·manage token은 넣지 않는다. 이 token은 `prior_manage_token` 검증을 통과한 요청에서만 발급한다. POST 때 두 행의 정규화 전화번호가 여전히 같고 old가 active, new가 pending인지 다시 확인한다.

`tokens.py`의 후보 선택 상수는 아래로 고정한다.

```python
RECRUITING_CHOICE_SALT = "inpa-recruiting-leader-choice"
RECRUITING_CHOICE_MAX_AGE_SECONDS = 60 * 10


def make_leader_choice_token(*, old_candidate_id, new_candidate_id):
    return signing.dumps(
        {"old_candidate_id": old_candidate_id, "new_candidate_id": new_candidate_id, "v": 1},
        salt=RECRUITING_CHOICE_SALT,
        compress=True,
    )
```

해석은 같은 salt와 max age를 쓰고, 두 candidate 행을 `select_for_update()`로 잠근 뒤 선택을 적용한다.

- [ ] **Step 2.3: 설계사 전용 API를 owner-only로 만든다.**

`RecruitingCandidateViewSet.get_queryset()`은 관리자 우회가 있는 `OwnedQuerySetMixin`을 사용하지 않고 아래처럼 강제한다.

```python
def get_queryset(self):
    return (
        RecruitingCandidate.objects
        .filter(owner=self.request.user, selection_status__in=("active", "replaced"))
        .select_related("campaign", "joined_user")
        .prefetch_related("settlement_checks")
        .order_by("stage", "next_action_at", "-created_at")
    )
```

후보 생성은 공개 동의 제출 service만 가능하다. 인증된 ViewSet의 collection POST는 405로 막아, 설계사가 동의 없이 연락처를 직접 쌓지 못하게 한다. list query는 `q`, `stage`, `campaign`, `due`, `career_band`만 허용하고, `q`는 owner 범위의 이름·전화에만 적용한다. `replaced` 행은 “후보가 다른 담당자를 선택해 대화가 종료되었어요”라는 generic 종료 카드로만 직렬화하고 원래 PII는 반환하지 않는다. PATCH 허용 필드는 `name`, `phone`, `career_band`, `current_affiliation`, `region`, `contact_window`, `next_action`, `next_action_at`이며, `stage`는 별도 `transition` action에서만 받는다. `team_join`, `selection_status`, `joined_user`, `joined_at`, `retention_expires_at`, `manage_token`은 항상 read-only/비노출이다.

- [ ] **Step 2.4: 영입 페이지·기본 캠페인을 자동 보장한다.**

`get_or_create_recruiting_page(user)`가 페이지를 만들고 `RecruitingCampaign.objects.get_or_create(page=page, channel="relationship", is_active=True, defaults={"name": "개인 소개"})`로 현재 활성 관계형 캠페인을 보장한다. 기본 `headline` template도 연결한다. 사용자 프로필 이름·사진·소속·직책은 응답 시 `Profile`에서 읽고 `RecruitingPage`에 복제 저장하지 않는다. Page PATCH는 `headline_template_id`, `activity_region`, 활성 template id 목록, `is_published`만 받는다. serializer는 headline id가 `kind=headline`, 선택 문구가 `kind in {support, faq}`, 모두 `is_active=True`인지 검증한다. 자유 수익·수수료 홍보 문구 입력란은 만들지 않는다.

관계형 캠페인 API의 재발급은 기존 캠페인 token을 바꾸지 않고 기존 행을 `is_active=False`로 만든 뒤 새 관계형 캠페인을 생성한다. 단, partial unique constraint와 충돌하지 않도록 같은 transaction에서 순서대로 처리한다. 이전 링크는 즉시 “새 링크를 받아보세요” 안내만 반환하고 지원을 받지 않는다.

- [ ] **Step 2.5: 공개 지원 API를 안전하게 구현한다.**

설정:

```python
RECRUITING_ENABLED = env.bool("RECRUITING_ENABLED", default=False)
RECRUITING_RETENTION_DAYS = env.int("RECRUITING_RETENTION_DAYS", default=180)
RECRUITING_TOMBSTONE_DAYS = env.int("RECRUITING_TOMBSTONE_DAYS", default=30)

REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update({
    "recruiting_public": "120/hour",
    "recruiting_apply": "10/hour",
    "recruiting_apply_campaign": "30/day",
    "recruiting_join": "20/hour",
})
```

모든 recruiting service/public/join endpoint는 공통 permission/mixin에서 `RECRUITING_ENABLED`를 검사해 꺼져 있으면 404를 반환한다. 운영자 template·정리 API는 rollout 준비를 위해 flag가 꺼져 있어도 관리자에게만 열어둔다.

`GET /r/{token}/` 응답은 공개 설계사 프로필, 선택된 headline·지원 문구·FAQ, 실제 활동 지역만 반환한다. 개인 이메일·전화·팀원 수·수수료 정보는 반환하지 않는다. `is_published=False` 또는 캠페인 비활성은 404 대신 같은 공개 형태의 다음 행동 메시지를 반환하되, HTTP 410과 `code="recruiting_link_renewed"`를 사용한다.

`POST` 입력:

```json
{
  "name": "홍길동",
  "phone": "010-1234-5678",
  "career_band": "5_10",
  "current_affiliation": "선택 입력",
  "region": "서울",
  "contact_window": "evening",
  "submission_key": "11111111-1111-4111-8111-111111111111",
  "prior_manage_token": "선택 입력, 이전 신청을 가진 브라우저만 전송",
  "agreed": true
}
```

같은 `submission_key` 재시도는 같은 성공 응답을 반환한다.

```json
{
  "submitted": true,
  "message": "지원 내용을 잘 받았어요. 담당 설계사가 선택한 시간대에 연락드릴게요.",
  "manage_url": "/r/manage/00000000-0000-0000-0000-000000000000"
}
```

유효한 이전 본인 관리 token으로 다른 리더에 신청하면 HTTP 200으로 아래 선택 상태를 반환한다. 이전 리더 정보는 token을 가진 후보에게만 보이고, 양쪽 리더에게는 선택 완료 전 새 행이 보이지 않는다.

```json
{
  "submitted": false,
  "choice_required": true,
  "current_leader": {"display_name": "김리더", "affiliation": "현재 공개 소속"},
  "new_leader": {"display_name": "이리더", "affiliation": "새 공개 소속"},
  "choice_token": "signed-value"
}
```

`POST /r/choice/{choice_token}/`은 `{ "choice": "keep_current" }` 또는 `{ "choice": "switch_to_new" }`만 받는다. 선택 완료 응답은 선택된 신청의 새 `manage_url`과 generic 완료 메시지만 반환한다. 선택 전에는 어떤 리더에게도 pending 지원자 상세나 알림을 보내지 않는다.

페이지별 30건/일 상한은 Django DB cache 키 `recruiting-apply:{campaign_id}:{KST-date}`로 별도 확인한다. cache 장애는 제출 자체를 깨지 않게 격리하고, 예외 종류만 log한다.

- [ ] **Step 2.6: 연락 중단과 삭제 요청을 즉시 반영한다.**

`POST /r/manage/{manage_token}/`에 `{ "action": "stop_contact" }`만 받는다. `selection_status=active`, `joined_user is null`, `stage != team_join`인 해당 행만 조작할 수 있고, 다른 후보 행이나 같은 전화번호 행에는 영향이 없다. 이미 팀에 합류한 행은 팀 관계를 바꾸지 않고 HTTP 409 `team_account_management_required`와 “인파 계정에서 연결 상태를 확인하고, 정보 정리는 문의함에서 요청할 수 있어요”를 반환한다. transaction 안에서:

1. `contact_opt_out_at=now`, `stage=ended`, `ended_at=now`, `retention_expires_at=now+30일` 설정
2. 동의 행을 즉시 삭제
3. `name="정리 요청"`, `phone=""`, `current_affiliation=""`, `region=""`으로 즉시 비식별
4. 아직 연결되지 않은 `joined_user`는 null 유지
5. PII 없는 `contact_stopped` activity/event 기록

응답은 `{ "contact_stopped": true, "message": "연락을 멈췄어요. 남은 정보도 정리 절차에 따라 처리됩니다." }`로 고정한다. PII 없는 tombstone이 정리되기 전 30일 동안 재요청은 같은 성공 응답을 내는 idempotent 동작이다.

- [ ] **Step 2.7: API 테스트를 통과시킨다.**

```bash
cd inpa_be
python manage.py test \
  inpa.recruiting.tests.test_services \
  inpa.recruiting.tests.test_api \
  inpa.recruiting.tests.test_public_api
```

Expected: 모든 owner 격리·중복·캡·비식별 테스트 통과.

- [ ] **Step 2.8: 커밋한다.**

```bash
git add inpa_be/inpa/recruiting inpa_be/config/settings/base.py inpa_be/config/urls.py
git commit -m "feat(recruiting): add candidate and public application flow"
```

---

## Task 3: 공통 팀 연결 서비스와 sticky Manager 역할을 TDD로 추가하기

**Files:**
- Create: `inpa_be/inpa/accounts/team.py`
- Create: `inpa_be/inpa/accounts/migrations/0014_profile_manager_promotion.py`
- Create: `inpa_be/inpa/accounts/test_team_service.py`
- Modify: `inpa_be/inpa/accounts/models.py`
- Modify: `inpa_be/inpa/accounts/serializers.py`
- Modify: `inpa_be/inpa/accounts/views.py`
- Modify: `inpa_be/inpa/accounts/urls.py`
- Test: `inpa_be/inpa/accounts/tests.py`
- Test: `inpa_be/inpa/accounts/test_google.py`

- [ ] **Step 3.1: 실패하는 팀 관계·승격 테스트를 작성한다.**

필수 사례:

- `test_first_real_team_link_stamps_manager_promotion_once`
- `test_removing_last_agent_does_not_remove_manager_role`
- `test_team_link_never_changes_manager_share_level`
- `test_team_link_never_updates_subscription_or_usage`
- `test_self_management_is_rejected`
- `test_switching_manager_requires_explicit_confirmation`
- `test_confirmed_switch_updates_only_profile_manager`
- `test_legacy_manager_subscription_counts_as_manager_role`
- `test_legacy_manager_first_team_link_is_marked_seen_without_new_promotion_notice`
- `test_profile_exposes_recruiting_feature_flag_read_only`
- `test_existing_generic_invite_token_still_resolves`
- `test_generic_invite_registration_uses_team_service`
- `test_generic_invite_signup_succeeds_when_free_plan_seed_is_temporarily_missing`

구독 불변 테스트는 호출 전후 `Subscription`의 `plan_id/status/starts_at/expires_at`과 `UsageMeter` 행을 직렬화해 완전 동일함을 비교한다.

- [ ] **Step 3.2: Profile에 역할 시각 두 개만 추가한다.**

```python
manager_promoted_at = models.DateTimeField(null=True, blank=True)
manager_promotion_seen_at = models.DateTimeField(null=True, blank=True)
```

data migration 규칙:

- `managed_agents`가 1명 이상인 manager Profile: 가장 이른 팀원 `date_joined`를 두 필드 모두에 기록
- 기존 유효 `manager` 요금제지만 팀원이 0명인 사용자: `Subscription.starts_at`을 두 필드 모두에 기록. 이미 Manager로 구매한 사람에게 신규 승격 안내를 다시 띄우지 않음
- 과거 사용자는 축하 안내가 다시 뜨지 않게 `seen_at=promoted_at`

이 RunPython migration은 `accounts.Profile`, `accounts.User`, `billing.Subscription`의 historical model만 사용하고, dependency에 `("billing", "0010_plan_price_annual_krw_and_more")`를 명시한다. 유효 상태는 `active/trial`이고 `expires_at is null 또는 현재보다 뒤`인 행만 대상으로 한다.

- [ ] **Step 3.3: 팀 연결을 한 서비스로 고정한다.**

`accounts/team.py`:

```python
from dataclasses import dataclass
from django.db import transaction
from django.utils import timezone


class TeamSwitchConfirmationRequired(Exception):
    pass


@dataclass(frozen=True)
class TeamLinkResult:
    manager_id: int
    promoted_now: bool
    switched: bool


@transaction.atomic
def link_agent_to_manager(*, agent, manager, confirm_switch=False) -> TeamLinkResult:
    if agent.pk == manager.pk:
        raise ValueError("self_management")

    agent_profile = Profile.objects.select_for_update().get(user=agent)
    manager_profile = Profile.objects.select_for_update().get(user=manager)
    previous_manager_id = agent_profile.manager_id

    if previous_manager_id and previous_manager_id != manager.pk and not confirm_switch:
        raise TeamSwitchConfirmationRequired

    switched = bool(previous_manager_id and previous_manager_id != manager.pk)
    if agent_profile.manager_id != manager.pk:
        agent_profile.manager = manager
        agent_profile.save(update_fields=["manager"])

    from inpa.billing.credit import resolve_effective_plan
    needs_promotion_stamp = manager_profile.manager_promoted_at is None
    try:
        legacy_manager = resolve_effective_plan(manager).code == "manager"
    except RuntimeError:  # free Plan seed가 없는 초기/테스트 환경
        legacy_manager = False
    promoted_now = needs_promotion_stamp and not legacy_manager
    if needs_promotion_stamp:
        manager_profile.manager_promoted_at = timezone.now()
        if legacy_manager:
            manager_profile.manager_promotion_seen_at = manager_profile.manager_promoted_at
        manager_profile.save(update_fields=[
            "manager_promoted_at", "manager_promotion_seen_at",
        ])

    return TeamLinkResult(
        manager_id=manager.pk,
        promoted_now=promoted_now,
        switched=switched,
    )
```

이 함수는 기존 Manager 구매자의 안내 재노출을 막기 위해 effective plan code만 읽는다. `Subscription`·`UsageMeter`의 생성·수정·삭제는 하지 않아야 하며, 테스트가 전후 완전 동일을 보장한다. 알림은 호출자 또는 `transaction.on_commit()` 콜백으로 생성한다.

- [ ] **Step 3.4: 역할 판정과 최초 안내 확인 API를 추가한다.**

```python
def profile_has_manager_role(profile) -> bool:
    if profile.manager_promoted_at is not None:
        return True
    from inpa.billing.credit import resolve_effective_plan
    try:
        return resolve_effective_plan(profile.user).code == "manager"
    except RuntimeError:
        return False
```

`ProfileSerializer` read-only 출력:

```json
{
  "is_manager": true,
  "manager_promoted_at": "2026-07-16T02:30:00Z",
  "manager_promotion_seen_at": null,
  "managed_agents_count": 1,
  "recruiting_enabled": true
}
```

`recruiting_enabled`는 `settings.RECRUITING_ENABLED`의 read-only 값이다. FE 메뉴와 홈 빠른 실행은 이 값이 true일 때만 노출한다. `POST /auth/manager-promotion/ack/`는 `manager_promoted_at`이 있을 때만 `seen_at`을 최초 기록한다. 반복 호출은 동일 성공이며, Manager 역할을 지우지 않는다.

- [ ] **Step 3.5: 기존 일반 초대 등록만 공통 서비스로 연결한다.**

`RegisterSerializer.create()`에서 기존 `invite_token` 해석 방식과 잘못된 토큰 무시 정책은 그대로 둔다. Profile 생성 뒤 manager가 유효할 때 `link_agent_to_manager(agent=user, manager=manager)`를 호출해 승격 시각만 함께 찍는다. 신규 영입 토큰은 이 serializer 필드에 추가하지 않는다. 영입 합류는 로그인 후 전용 accept API에서 처리해 인증 흐름을 덜 건드린다.

- [ ] **Step 3.6: 기존 account 전체 회귀를 통과시킨다.**

```bash
cd inpa_be
python manage.py test inpa.accounts.test_team_service
python manage.py test inpa.accounts
```

Expected: 신규 테스트와 기존 회원가입·이메일 인증·Google·일반 초대 테스트 전부 통과.

- [ ] **Step 3.7: 커밋한다.**

```bash
git add inpa_be/inpa/accounts
git commit -m "feat(accounts): activate manager role on first team link"
```

---

## Task 4: 지원자 전용 합류 토큰과 정착 일정 생성을 TDD로 구현하기

**Files:**
- Modify: `inpa_be/inpa/recruiting/tokens.py` (기존 후보 선택 salt와 별도 합류 salt 추가)
- Create: `inpa_be/inpa/recruiting/join_views.py`
- Create: `inpa_be/inpa/recruiting/tests/test_join.py`
- Modify: `inpa_be/inpa/recruiting/services.py`
- Modify: `inpa_be/inpa/recruiting/views.py`
- Modify: `inpa_be/inpa/recruiting/urls.py`

- [ ] **Step 4.1: 실패하는 합류 테스트를 작성한다.**

필수 사례:

- `test_invite_token_has_separate_salt_and_candidate_owner_payload`
- `test_expired_join_token_returns_410_without_identity_details`
- `test_anonymous_accept_returns_401`
- `test_accepting_sets_profile_manager_and_candidate_joined`
- `test_accepting_creates_exactly_four_settlement_checks`
- `test_repeated_accept_is_idempotent`
- `test_manual_candidate_stage_patch_still_cannot_join`
- `test_switch_requires_confirmation_and_confirm_switch_succeeds`
- `test_accept_never_changes_subscription_or_share_level`
- `test_previous_accepted_candidate_record_closes_without_revealing_new_leader`
- `test_previous_leaders_unfinished_settlement_checks_stop_after_switch`
- `test_accept_closes_other_active_rows_only_when_manage_proof_linked_the_identity`
- `test_same_phone_without_manage_proof_is_not_closed_by_another_accounts_accept`
- `test_support_needed_requires_blocker_and_next_support`
- `test_stopped_settlement_closes_future_unfinished_checks`

- [ ] **Step 4.2: 기존 초대와 완전히 다른 signed token을 만든다.**

`tokens.py`:

```python
from django.core import signing

RECRUITING_JOIN_SALT = "inpa-recruiting-team-invite"
RECRUITING_JOIN_MAX_AGE_SECONDS = 60 * 60 * 24 * 14


def make_recruiting_join_token(candidate):
    return signing.dumps(
        {"candidate_id": candidate.pk, "owner_id": candidate.owner_id, "v": 1},
        salt=RECRUITING_JOIN_SALT,
        compress=True,
    )


def read_recruiting_join_token(token):
    return signing.loads(
        token,
        salt=RECRUITING_JOIN_SALT,
        max_age=RECRUITING_JOIN_MAX_AGE_SECONDS,
    )
```

해석 뒤 반드시 DB의 `candidate.owner_id == payload.owner_id`, `selection_status == active`, `contact_opt_out_at is null`, `stage != ended`를 재검증한다. 토큰에는 이름·전화번호를 넣지 않는다. 후보 리더 선택 token과 합류 token은 salt·유효기간·해석 함수가 서로 달라 교차 사용이 실패해야 한다.

- [ ] **Step 4.3: 공개 info와 로그인 accept 응답을 분리한다.**

GET info는 리더의 공개 프로필 `display_name`, `affiliation`, `title`, `profile_image`, 선택된 headline만 반환한다. 지원자의 이름·연락처·다른 지원 이력은 반환하지 않는다.

POST accept:

```json
{ "confirm_switch": false }
```

다른 manager가 이미 있으면:

```json
{
  "code": "team_switch_confirmation_required",
  "message": "현재 연결된 리더가 있어요. 이 리더로 변경할지 한 번 더 확인해주세요."
}
```

HTTP 409. 두 번째 요청 `{ "confirm_switch": true }`에서만 변경한다.

- [ ] **Step 4.4: 합류 완료를 한 transaction에서 처리한다.**

```python
SETTLEMENT_DAYS = {1: 7, 4: 28, 8: 56, 13: 91}


@transaction.atomic
def accept_team_join(*, candidate, agent, confirm_switch=False):
    locked_group = list(
        RecruitingCandidate.objects.select_for_update()
        .filter(Q(identity_ref=candidate.identity_ref) | Q(joined_user=agent))
        .order_by("pk")
    )
    locked = next(row for row in locked_group if row.pk == candidate.pk)
    if locked.joined_user_id == agent.pk and locked.stage == locked.Stage.TEAM_JOIN:
        return locked, False
    if locked.selection_status != locked.SelectionStatus.ACTIVE:
        raise ValueError("inactive_candidate_selection")

    team_result = link_agent_to_manager(
        agent=agent,
        manager=locked.owner,
        confirm_switch=confirm_switch,
    )
    now = timezone.now()
    joined_date = timezone.localdate()
    locked.joined_user = agent
    locked.joined_at = now
    locked.stage = locked.Stage.TEAM_JOIN
    locked.name = "팀 합류 설계사"
    locked.phone = ""
    locked.current_affiliation = ""
    locked.region = ""
    locked.next_action = ""
    locked.next_action_at = None
    locked.save(update_fields=[
        "joined_user", "joined_at", "stage", "name", "phone", "current_affiliation",
        "region", "next_action", "next_action_at", "updated_at",
    ])
    locked.consents.filter(revoked_at__isnull=True).update(revoked_at=now)
    for week, days in SETTLEMENT_DAYS.items():
        SettlementCheck.objects.get_or_create(
            candidate=locked,
            week=week,
            defaults={"due_on": joined_date + timedelta(days=days)},
        )
    previous_rows = [
        row for row in locked_group
        if row.pk != locked.pk and row.stage != RecruitingCandidate.Stage.ENDED
    ]
    for previous in previous_rows:
        previous.selection_status = RecruitingCandidate.SelectionStatus.REPLACED
        previous.stage = RecruitingCandidate.Stage.ENDED
        previous.ended_at = now
        previous.name = "담당자 변경"
        previous.phone = ""
        previous.current_affiliation = ""
        previous.region = ""
        previous.save(update_fields=[
            "selection_status", "stage", "ended_at", "name", "phone",
            "current_affiliation", "region", "updated_at",
        ])
        previous.settlement_checks.filter(completed_at__isnull=True).update(
            state=SettlementCheck.State.STOPPED,
            next_support=SettlementCheck.NextSupport.CLOSE,
            completed_at=now,
        )
    return locked, team_result.promoted_now
```

이 service는 `django.db.models.Q`를 import한다. 같은 identity/agent 관련 후보 행을 PK 오름차순으로 먼저 모두 잠가, 두 합류 링크의 동시 수락도 deadlock·이중 최종 리더 없이 직렬 처리한다. 마지막 loop에서 각 행에 PII 없는 `leader_changed` activity를 모아 `bulk_create`한다. 새 리더 id/이름은 이전 owner의 응답이나 activity metadata에 남기지 않는다. `identity_ref`는 serializer·event·알림·운영자 화면에 노출하지 않는다.

- [ ] **Step 4.5: 정착 확인 저장 규칙을 서비스로 고정한다.**

`complete_settlement_check(*, check, owner, state, blocker, next_support)`는 candidate owner만 호출한다. `support_needed`이면 blocker가 `none/blank`가 아니고 next_support가 필수다. 다른 상태는 blocker/next_support 조합을 serializer에서 정규화한다. 저장 시 `completed_at=now`와 PII 없는 `settlement_completed` event를 기록한다.

`state=stopped`이면 같은 candidate의 현재 주차 이후 미완료 check를 transaction 안에서 `stopped + next_support=close + completed_at=now`로 함께 닫아 이후 알림이 생기지 않게 한다. 다시 활동을 시작하면 owner가 필요한 미래 주차를 개별 `active`로 되돌릴 수 있지만, 이미 지난 완료 기록의 날짜와 activity는 삭제하지 않는다.

- [ ] **Step 4.6: 합류 링크 발급 권한을 잠근다.**

`POST candidates/{id}/team-invite/`는 owner 본인만 호출 가능하고, 연락 중단·종료·이미 다른 계정과 합류한 지원자는 새 링크를 발급하지 않는다. 응답은 절대 URL 대신 FE가 조립할 수 있는 상대 경로와 만료일만 반환한다.

```json
{
  "join_path": "/recruiting/join/<signed-token>",
  "expires_at": "2026-07-30T00:00:00+09:00"
}
```

- [ ] **Step 4.7: 테스트를 통과시킨다.**

```bash
cd inpa_be
python manage.py test inpa.recruiting.tests.test_join
python manage.py test inpa.accounts inpa.recruiting
```

- [ ] **Step 4.8: 커밋한다.**

```bash
git add inpa_be/inpa/recruiting
git commit -m "feat(recruiting): add explicit team join and settlement schedule"
```

---

## Task 5: 영입 알림·정착 리마인드·180일 정리를 기존 일일 작업에 안전하게 연결하기

**Files:**
- Create: `inpa_be/inpa/recruiting/jobs.py`
- Create: `inpa_be/inpa/recruiting/tests/test_jobs.py`
- Modify: `inpa_be/inpa/recruiting/services.py`
- Modify: `inpa_be/inpa/notifications/models.py`
- Modify: `inpa_be/inpa/notifications/views.py`
- Modify: `inpa_be/inpa/notifications/jobs.py`
- Modify: `inpa_be/inpa/accounts/team.py`
- Create: `inpa_be/inpa/notifications/migrations/0011_notification_recruiting_types_and_dedupe.py`
- Test: `inpa_be/inpa/notifications/tests.py` 또는 현행 테스트 구조

- [ ] **Step 5.1: 실패하는 알림·정리 테스트를 작성한다.**

- `test_new_application_notifies_owner_without_candidate_pii`
- `test_pending_leader_choice_does_not_notify_either_owner_until_selected`
- `test_due_follow_up_notification_is_idempotent_per_day`
- `test_settlement_due_notification_is_idempotent_per_week`
- `test_unread_counts_include_recruiting_bucket`
- `test_opted_out_candidate_is_never_reminded`
- `test_expired_ended_unjoined_candidate_is_deleted`
- `test_active_candidate_is_not_deleted_only_because_it_is_older_than_180_days`
- `test_joined_candidate_keeps_non_pii_history_after_retention`
- `test_recruiting_job_failure_does_not_stop_other_daily_producers`
- `test_feature_off_skips_reminders_but_still_runs_retention_cleanup`

- [ ] **Step 5.2: 알림 유형과 버킷을 추가한다.**

```python
RECRUITING_APPLICATION = "recruiting_application", "새 영입 지원"
RECRUITING_FOLLOWUP = "recruiting_followup", "영입 다음 연락"
RECRUITING_SETTLEMENT = "recruiting_settlement", "정착 확인"
MANAGER_PROMOTED = "manager_promoted", "Manager 활성화"

RECRUITING_NOTIF_TYPES = {
    NotifType.RECRUITING_APPLICATION,
    NotifType.RECRUITING_FOLLOWUP,
    NotifType.RECRUITING_SETTLEMENT,
    NotifType.MANAGER_PROMOTED,
}
```

알림 제목/본문에는 이름을 넣지 않는다.

```text
새 영입 지원이 도착했어요 / 가능한 시간대를 확인하고 첫 연락을 준비해보세요.
다음 연락 시간이 되었어요 / 영입 현황에서 오늘 이어갈 대화를 확인해보세요.
정착 확인 주차가 되었어요 / 함께 일하는 설계사의 현재 흐름을 짧게 확인해보세요.
Manager 기능이 열렸어요 / 첫 팀원이 합류해 팀 관리 흐름을 시작할 수 있어요.
```

읽지 않은 수 응답에 `recruiting` 숫자를 더하되, 기존 키와 의미는 바꾸지 않는다.

새 지원 알림은 candidate가 `selection_status=active`가 되는 transaction의 on-commit에서 `dedupe_key="recruiting:application:{candidate.audit_ref}"`로 한 번만 만든다. pending 선택 행에는 만들지 않는다.

`accounts/team.py`는 `promoted_now=True`일 때 `transaction.on_commit()`으로 `MANAGER_PROMOTED` 알림을 한 번 만든다. `dedupe_key="manager-promoted:{manager_id}"`로 일반 초대와 영입 합류가 동시에 재시도되어도 한 건만 생성한다. 알림 실패는 이미 저장된 팀 관계와 승격을 되돌리지 않고 exception class만 기록한다.

- [ ] **Step 5.3: 일일 producer와 cleanup을 구현한다.**

`produce_recruiting_reminders(run_date=None)`는 `run_date or timezone.localdate()`를 사용한다.

- `RECRUITING_ENABLED=False`면 reminder producer는 0건으로 끝내되, 개인정보 정리 cleanup은 flag와 무관하게 계속 실행
- `next_action_at`이 오늘 이전이고 연락 중단이 없는 지원자: owner별 1일 1개 follow-up 알림
- `SettlementCheck.due_on <= today`, 미완료: candidate/week별 1개 정착 알림
- idempotency는 Notification에 `dedupe_key = models.CharField(max_length=120, null=True, blank=True, unique=True)`를 additive로 추가하고 `recruiting:followup:{owner}:{date}`, `recruiting:settlement:{check_id}`로 보장한다. 기존 알림 생성은 null이라 영향 없음

`cleanup_expired_recruiting_candidates()`:

- 연락 중단 요청은 제출 즉시 PII·동의 삭제와 행동 목록 제외. cleanup은 `contact_opt_out_at is not null` AND `name="정리 요청"` AND 전화·소속·지역이 비어 있음 AND `retention_expires_at <= now`를 함께 확인해 30일짜리 후보 tombstone을 완전 삭제. Activity는 candidate FK만 null이 되고 PII 없는 감사 ref·enum·시각은 유지
- 일반 미합류 종료 후보는 `joined_user is null` AND `stage=ended` AND `ended_at is not null` AND `retention_expires_at <= now` 네 조건을 모두 만족할 때만 완전 삭제
- `retention_expires_at`은 종료 service가 `종료일`과 system-stamped `last_contacted_at/최종 RecruitingActivity.created_at` 중 늦은 날 + 180일로 계산
- 진행 중 후보는 생성 후 180일이 지났다는 이유만으로 삭제하지 않음
- 팀 합류 후보는 합류 transaction에서 이미 전화·이전 소속·지역·후보용 이름을 비식별하고, `joined_user`, 합류일, 정착 결과 enum을 계속 보관
- 삭제 뒤 `RecruitingEvent.candidate`는 SET_NULL이라 PII 없는 집계만 남음
- 정리 기준은 system-stamped 날짜만 사용하며, 자유 수정 필드를 삭제 조건으로 쓰지 않음

- [ ] **Step 5.4: 기존 daily runner에 독립 producer로 연결한다.**

`notifications/jobs.py`의 `PRODUCERS`에 영입 producer를 하나 추가하고 기존 per-producer 예외 격리를 그대로 사용한다. cleanup도 기존 정리 함수들과 별도 try/except 구간으로 연결한다. 원시 예외 메시지나 후보자 내용을 로그하지 않고 producer name과 exception class만 남긴다.

- [ ] **Step 5.5: 테스트를 통과시킨다.**

```bash
cd inpa_be
python manage.py test inpa.recruiting.tests.test_jobs inpa.notifications
python manage.py test inpa.recruiting
```

- [ ] **Step 5.6: 커밋한다.**

```bash
git add inpa_be/inpa/recruiting inpa_be/inpa/notifications inpa_be/inpa/accounts/team.py
git commit -m "feat(recruiting): add private reminders and retention cleanup"
```

---

## Task 6: Plus와 legacy Manager의 팀 권한을 같은 값으로 맞추기

**Files:**
- Modify: `inpa_be/inpa/billing/credit.py`
- Modify: `inpa_be/inpa/billing/management/commands/seed_billing.py`
- Create: `inpa_be/inpa/billing/migrations/0011_plus_team_capability.py`
- Modify: `inpa_be/inpa/billing/tests.py` 또는 현행 테스트 파일
- Modify: `inpa_be/inpa/accounts/manager.py`의 오류 문구만, 응답 계약 유지

- [ ] **Step 6.1: 실패하는 요금 호환 테스트를 작성한다.**

- `test_plus_can_use_team`
- `test_legacy_manager_can_still_use_team`
- `test_super_can_use_team`
- `test_free_cannot_use_team_when_gate_enabled`
- `test_promotion_does_not_switch_plus_subscription_to_manager`
- `test_plus_expiry_keeps_manager_role_but_closes_paid_team_tools`
- `test_plus_restart_restores_team_tools_without_data_change`

- [ ] **Step 6.2: seed의 능력값을 정렬한다.**

생성 기본값과 운영 중 행 보정 정책을 분리한다.

- `free.can_use_team=False`
- `plus.can_use_team=True`
- `manager.can_use_team=True` (legacy 보존)
- `super.can_use_team=True`

현재 `seed_billing`이 `get_or_create`로 운영자 수정을 보존하므로, 기존 Plus 행을 자동 수정하려면 별도 명시 migration이 필요하다. 이 기능에서는 additive data migration `inpa_be/inpa/billing/migrations/0011_plus_team_capability.py`로 `code="plus"`만 `can_use_team=True`로 한 번 보정하고, seed defaults도 같은 값으로 바꾼다. 가격·quota·다른 능력값은 건드리지 않는다.

- [ ] **Step 6.3: 기존 gate 계약을 유지한다.**

`user_can_use_team()`은 기존 effective subscription·만료 판정을 재사용하고 `plan.can_use_team`만 본다. `manager_plan_required` 오류 code는 FE 호환을 위해 유지하되, 사용자 문구만 다음처럼 바꾼다.

```text
Plus를 시작하면 팀 관리 기능을 계속 사용할 수 있어요.
```

beta의 `MANAGER_PLAN_GATE_ENABLED=False` 동작은 그대로 유지한다.

- [ ] **Step 6.4: 테스트를 통과시킨다.**

```bash
cd inpa_be
python manage.py test inpa.billing inpa.accounts.test_team_service
```

- [ ] **Step 6.5: 커밋한다.**

```bash
git add inpa_be/inpa/billing inpa_be/inpa/accounts/manager.py
git commit -m "feat(billing): align plus and manager team access"
```

---

## Task 7: 영입 집계와 비식별 운영자 API를 구현하기

**Files:**
- Create: `inpa_be/inpa/recruiting/analytics.py`
- Create: `inpa_be/inpa/recruiting/admin_views.py`
- Create: `inpa_be/inpa/recruiting/admin_urls.py`
- Create: `inpa_be/inpa/recruiting/tests/test_analytics.py`
- Create: `inpa_be/inpa/recruiting/tests/test_admin_api.py`
- Modify: `inpa_be/inpa/recruiting/views.py`
- Modify: `inpa_be/config/urls.py`

- [ ] **Step 7.1: 실패하는 집계·운영자 테스트를 작성한다.**

- `test_personal_summary_uses_only_owner_candidates`
- `test_team_summary_returns_counts_not_candidate_details`
- `test_team_summary_requires_actual_managed_agent_relation`
- `test_team_summary_excludes_agents_without_manager_share_consent`
- `test_admin_candidate_list_masks_name_and_phone`
- `test_admin_template_crud_requires_is_admin`
- `test_admin_purge_removes_pii_and_records_enum_audit`
- `test_admin_audit_survives_candidate_deletion_without_pii`
- `test_admin_promotion_history_shows_original_plan_code_and_current_role`
- `test_recruiting_events_reject_pii_metadata`
- `test_customer_funnel_metrics_are_unchanged`

- [ ] **Step 7.2: 영입 현황의 계산 기준을 고정한다.**

`summary`:

```json
{
  "stage_counts": {
    "new": 0,
    "contact": 0,
    "conversation": 0,
    "preparing": 0,
    "team_join": 0,
    "recontact": 0,
    "ended": 0
  },
  "due_today": 0,
  "overdue": 0,
  "joined_this_month": 0,
  "settlement_due": 0
}
```

`this month`는 반드시 `timezone.localdate()` 기준으로 계산한다. 고객 dashboard·NorthStarEvent를 import하거나 수정하지 않는다.

개인/팀/운영 지표의 지원·단계·합류 수는 `selection_status=active`만 센다. `pending`, `replaced`, `declined`는 후보 선택 분쟁 감사에는 남지만 전환율 분모·분자에 넣지 않는다.

`team-summary`는 `Profile.manager=request.user`이면서 기존 `manager_share_level in {activity, full}`에 본인이 동의한 설계사만 aggregate한다. 동의가 `none`인 팀원은 이름·숫자 모두 제외하고 `not_shared_count`만 반환해 “팀원이 활동 공유를 선택하면 함께 볼 수 있어요”라고 안내한다. `MANAGER_PLAN_GATE_ENABLED=True`일 때는 기존 `user_can_use_team()`을 그대로 적용하고, 닫힌 경우에도 데이터는 삭제하지 않는다. beta의 gate off 동작은 기존 Manager 현황과 동일하게 유지한다.

```json
{
  "team_totals": {
    "active_recruiting": 4,
    "joined_this_month": 1,
    "settlement_due": 2
  },
  "not_shared_count": 1,
  "members": [
    {
      "user_id": 12,
      "display_name": "김설계",
      "active_recruiting": 2,
      "joined_this_month": 1,
      "settlement_due": 1
    }
  ]
}
```

Manager는 팀원의 지원자 이름·전화번호·현재 소속·지역을 볼 수 없다. 각 팀원은 자신의 상세만 본다.

- [ ] **Step 7.3: 운영자 API를 새 앱 안에 둔다.**

`IsAdmin`을 사용하고 기존 거대 `admin_console/views.py`에 영입 로직을 추가하지 않는다.

운영자 지원자 목록:

```json
{
  "id": 41,
  "name_masked": "홍*동",
  "phone_masked": "***-****-5678",
  "stage": "contact",
  "created_at": "2026-07-16T10:00:00+09:00",
  "retention_expires_at": "2027-01-12T10:00:00+09:00",
  "contact_opted_out": false
}
```

운영자 summary에는 `recruiting_enabled`, `retention_days`, `tombstone_days` read-only 값을 포함해 현재 rollout·정리 정책을 개발자 없이 확인할 수 있게 한다. 변경은 env 배포 승인 절차로만 한다.

templates CRUD는 `code`를 생성 뒤 변경하지 못하게 하고 title/body/is_active/sort_order만 수정한다. purge는 연락 중단 서비스와 동일 비식별 함수를 재사용하고, 사유 enum `user_request`, `retention`, `admin_correction` 중 하나만 받는다.

Manager 활성화 이력은 `manager_promoted_at`, 현재 팀원 수, 현재 `is_manager`, effective plan code와 원래 `Subscription.plan.code`를 구분해 반환한다. 기존 Manager 구독을 Plus로 바꾸거나 데이터 수정 동작은 제공하지 않는다.

감사 API는 `candidate_ref`, `event_type`, `from_stage`, `to_stage`, `actor_id`, `created_at`만 반환한다. 후보 이름·전화·소속·새 리더 정보와 자유 metadata는 반환하지 않는다.

- [ ] **Step 7.4: Django admin을 등록한다.**

지원자 admin의 list display에는 id·stage·campaign·created_at·retention_expires_at만 노출한다. 이름·전화·현재 소속은 `list_display`, `search_fields`, `list_filter`에 넣지 않는다. 동의·activity·event는 read-only로 등록한다.

- [ ] **Step 7.5: 테스트를 통과시킨다.**

```bash
cd inpa_be
python manage.py test \
  inpa.recruiting.tests.test_analytics \
  inpa.recruiting.tests.test_admin_api
python manage.py test inpa.admin_console inpa.analytics inpa.dashboard
```

Expected: 영입 집계 통과, 기존 고객/활성화/dashboard 집계 회귀 없음.

- [ ] **Step 7.6: 커밋한다.**

```bash
git add inpa_be/inpa/recruiting inpa_be/config/urls.py
git commit -m "feat(recruiting): add isolated metrics and admin operations"
```

---

## Task 8: FE 타입·인증 복귀 경로·공통 상태를 먼저 만들기

**Files:**
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/lib/adminApi.ts`
- Create: `inpa_fe/lib/auth-return.ts`
- Create: `inpa_fe/components/recruiting/recruiting-states.tsx`
- Modify: `inpa_fe/app/login/page.tsx`
- Modify: `inpa_fe/app/register/page.tsx`
- Modify: `inpa_fe/components/google-signin-button.tsx`
- Modify: `inpa_fe/app/onboarding/page.tsx`

- [ ] **Step 8.1: Next 16 공식 로컬 문서를 읽고 현재 auth 흐름을 다시 추적한다.**

Task 0의 Next 문서와 login/register/Google/onboarding의 모든 redirect 위치를 읽어 아래 두 흐름을 종이에 기록한다.

```text
일반 로그인 → 기존 그대로 /home
합류 링크 → 로그인/가입/Google → 온보딩 필요 시 /onboarding → 원래 합류 링크 → 수락
```

- [ ] **Step 8.2: `lib/api.ts`에 정확한 타입과 함수만 추가한다.**

타입:

```typescript
export type RecruitingStage =
  | "new"
  | "contact"
  | "conversation"
  | "preparing"
  | "team_join"
  | "recontact"
  | "ended";

export type RecruitingCareerBand = "under_1" | "1_3" | "3_5" | "5_10" | "10_plus";
export type RecruitingContactWindow = "morning" | "afternoon" | "evening" | "anytime";
export type RecruitingNextAction = "call" | "message" | "meeting" | "follow_up" | "none";
export type RecruitingSelectionStatus = "active" | "replaced";
export type SettlementState = "active" | "support_needed" | "stopped";
export type SettlementBlocker =
  | "customer_prospecting"
  | "consultation_prep"
  | "product_understanding"
  | "work_tools"
  | "time_management"
  | "organization_adjustment"
  | "personal"
  | "none";
export type SettlementNextSupport =
  | "consultation_prep"
  | "training"
  | "activity_plan"
  | "tool_help"
  | "leader_meeting"
  | "schedule_only"
  | "close";

export interface RecruitingTemplate {
  id: number;
  code: string;
  kind: "headline" | "support" | "faq" | "share";
  title: string;
  body: string;
  sort_order: number;
}

export interface RecruitingCandidate {
  id: number;
  name: string;
  phone: string;
  career_band: RecruitingCareerBand;
  current_affiliation: string;
  region: string;
  contact_window: RecruitingContactWindow;
  selection_status: RecruitingSelectionStatus;
  stage: RecruitingStage;
  next_action: RecruitingNextAction | "";
  next_action_at: string | null;
  last_contacted_at: string | null;
  joined_agent: { id: number; display_name: string; profile_image: string | null } | null;
  joined_at: string | null;
  ended_at: string | null;
  campaign: { id: number; name: string; channel: "relationship" } | null;
  created_at: string;
}

export interface RecruitingSummary {
  stage_counts: Record<RecruitingStage, number>;
  due_today: number;
  overdue: number;
  joined_this_month: number;
  settlement_due: number;
}

export interface RecruitingPageConfig {
  display_name: string;
  affiliation: string;
  title: string;
  profile_image: string | null;
  activity_region: string;
  is_published: boolean;
  headline_template: RecruitingTemplate;
  selected_templates: RecruitingTemplate[];
}

export interface RecruitingCampaignSummary {
  id: number;
  name: string;
  channel: "relationship";
  public_path: string;
  is_active: boolean;
  visits: number;
  applications: number;
  joins: number;
}

export interface SettlementCheck {
  id: number;
  candidate_id: number;
  joined_agent_name: string;
  week: 1 | 4 | 8 | 13;
  due_on: string;
  state: SettlementState;
  blocker: SettlementBlocker | "";
  next_support: SettlementNextSupport | "";
  completed_at: string | null;
}

export interface PublicRecruitingPage {
  display_name: string;
  affiliation: string;
  title: string;
  profile_image: string | null;
  activity_region: string;
  headline: string;
  support_items: RecruitingTemplate[];
  faq_items: RecruitingTemplate[];
  consent_version: string;
  consent_text: string;
}

export interface RecruitingJoinInfo {
  display_name: string;
  affiliation: string;
  title: string;
  profile_image: string | null;
  headline: string;
  expires_at: string;
}

export type PublicApplicationResult =
  | { submitted: true; message: string; manage_url: string }
  | {
      submitted: false;
      choice_required: true;
      current_leader: { display_name: string; affiliation: string };
      new_leader: { display_name: string; affiliation: string };
      choice_token: string;
    };
```

함수는 고정 API 계약의 전부를 `api.ts` 한곳에 넣는다. 일반 `fetch` 직접 호출을 페이지에 만들지 않는다. 관리자 함수는 `adminApi.ts`만 사용한다.

- [ ] **Step 8.3: 허용 목록 기반 auth return helper를 구현한다.**

`auth-return.ts`:

```typescript
const KEY = "inpa_auth_return";
const TTL_MS = 24 * 60 * 60 * 1000;
const ALLOWED_PREFIXES = ["/recruiting/join/"] as const;

export function isSafeAuthReturn(path: string): boolean {
  return (
    path.startsWith("/") &&
    !path.startsWith("//") &&
    !path.includes("://") &&
    ALLOWED_PREFIXES.some((prefix) => path.startsWith(prefix))
  );
}

type StoredAuthReturn = { path: string; expiresAt: number };

function clearAuthReturn(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(KEY);
}

function readAuthReturn(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw) as StoredAuthReturn;
    if (
      typeof stored.path !== "string" ||
      typeof stored.expiresAt !== "number" ||
      stored.expiresAt <= Date.now() ||
      !isSafeAuthReturn(stored.path)
    ) {
      clearAuthReturn();
      return null;
    }
    return stored.path;
  } catch {
    clearAuthReturn();
    return null;
  }
}

export function rememberAuthReturn(path: string): void {
  if (typeof window === "undefined" || !isSafeAuthReturn(path)) return;
  const value: StoredAuthReturn = { path, expiresAt: Date.now() + TTL_MS };
  window.localStorage.setItem(KEY, JSON.stringify(value));
}

export function peekAuthReturn(): string | null {
  return readAuthReturn();
}

export function consumeAuthReturn(): string | null {
  const path = readAuthReturn();
  clearAuthReturn();
  return path;
}
```

`localStorage`를 사용해 이메일 인증이 새 탭에서 열려도 같은 브라우저에서 복귀 경로가 유지되게 한다. URL query의 `next`도 반드시 `isSafeAuthReturn()`을 통과한 뒤에만 저장한다.

- [ ] **Step 8.4: 기존 auth redirect를 좁게 수정한다.**

- 정상 로그인 성공 + onboarding 완료: `consumeAuthReturn() ?? "/home"`
- onboarding 미완료: return path를 소비하지 않고 `/onboarding`
- onboarding 완료 버튼: `consumeAuthReturn() ?? "/home"`
- Google login도 동일 helper 사용
- 가입 성공 화면의 로그인 링크는 안전한 `next`가 있으면 유지
- `/\evil.com`, `https://evil.com`, `//evil.com`은 모두 `/home`으로 귀결

- [ ] **Step 8.5: 공통 로딩·빈 상태·오류 컴포넌트를 만든다.**

`RecruitingLoading`, `RecruitingEmpty`, `RecruitingError` 세 컴포넌트를 만들고, 오류는 “다시 불러오기” 동작을 반드시 제공한다. 빈 상태 문구:

```text
아직 영입 대화가 없어요.
아는 설계사 한 분에게 내 영입 링크를 먼저 보내보세요.
```

- [ ] **Step 8.6: build로 타입 계약을 확인한다.**

```bash
cd inpa_fe
npm run build
```

Expected: 신규 타입·auth helper·기존 auth 화면 typecheck 통과.

- [ ] **Step 8.7: 커밋한다.**

```bash
git add inpa_fe/lib inpa_fe/app/login inpa_fe/app/register inpa_fe/app/onboarding inpa_fe/components/google-signin-button.tsx inpa_fe/components/recruiting
git commit -m "feat(recruiting): add frontend contracts and safe auth return"
```

---

## Task 9: 인증된 `설계사 영입` 네 탭을 완성하기

**Files:**
- Create: `inpa_fe/app/recruiting/page.tsx`
- Create: `inpa_fe/app/recruiting/loading.tsx`
- Create: `inpa_fe/app/recruiting/error.tsx`
- Create: `inpa_fe/components/recruiting/recruiting-dashboard.tsx`
- Create: `inpa_fe/components/recruiting/candidate-board.tsx`
- Create: `inpa_fe/components/recruiting/candidate-card.tsx`
- Create: `inpa_fe/components/recruiting/recruiting-page-editor.tsx`
- Create: `inpa_fe/components/recruiting/campaign-link-panel.tsx`
- Create: `inpa_fe/components/recruiting/recruiting-qr.tsx`
- Create: `inpa_fe/components/recruiting/settlement-panel.tsx`
- Create: `inpa_fe/components/recruiting/team-recruiting-summary.tsx`
- Modify: `inpa_fe/package.json`
- Modify: `inpa_fe/package-lock.json`

- [ ] **Step 9.1: 페이지 상태 모델을 URL query로 고정한다.**

```text
/recruiting?tab=status
/recruiting?tab=page
/recruiting?tab=campaign
/recruiting?tab=settlement
```

잘못된 tab은 `status`로 정규화한다. 탭 이동은 브라우저 뒤로가기와 공유 URL이 동작해야 한다.

- [ ] **Step 9.2: `영입 현황` 탭을 완성한다.**

데스크톱은 `단계별`과 `목록` 전환을 모두 제공한다. 단계별은 7단계 가로 보드, 목록은 이름·단계·출처·경력·다음 확인일 기준 정렬과 검색·필터를 제공한다. 모바일은 다음 행동일이 빠른 세로 카드가 기본이고 단계 선택 칩을 제공한다. 카드는 이름·경력·현재 소속·지역·연락 가능 시간·다음 행동·기한만 표시한다. 전화번호는 상세 열기 안에서만 보인다.

`team_join` 행은 후보 PII를 비운 뒤이므로 이름·프로필은 `joined_user.profile`에서 읽고, 이전 소속·지원 당시 전화번호는 다시 노출하지 않는다.

카드 이동은 낙관적 UI를 쓰지 않는다. 서버 성공 뒤 이동하며, 실패하면 원래 위치 유지 + 상단 오류 배너. `팀 합류` 열은 읽기 전용이고 드롭 대상이 아니다.

상세 빠른 행동은 `전화하기`(`tel:`), `문자 작성`(`sms:`), `다음 행동 변경`, `단계 변경` 네 개다. 문자 내용은 초안만 열고 자동 발송하지 않는다. 일정 기능과 후보 FK를 새로 만들지 않으며, 일정이 필요하면 `/schedule`을 별도 탭으로 여는 일반 바로가기만 제공한다.

지원자 직접 등록은 제공하지 않는다. 빈 화면의 유일한 생성 행동은 동의가 포함된 개인 영입 링크 복사다. 화면 첫 안내에 “보험가입 고객과 별도로 관리됩니다”를 한 번만 표시하며, 고객 선택·고객 검색·고객 id 입력은 없다.

- [ ] **Step 9.3: `나의 영입 페이지` 탭을 완성한다.**

- Profile에서 가져온 사진·이름·소속·직책은 미리보기만, 수정 CTA는 `/profile`
- 운영자가 승인한 첫 문장 중 1개 선택, 실제 활동 지역 60자 카운터
- 운영자 활성 문구를 최대 3개 선택
- 자유 수익·수수료·정착지원금 홍보 입력란 없음
- 공개/비공개 토글
- 저장 성공 toast와 저장 실패 inline error
- 오른쪽 또는 모바일 아래에 공개 페이지 실제 미리보기

- [ ] **Step 9.4: `캠페인 링크` 탭을 실제 기능으로 완성한다.**

Phase 1에서는 관계형 기본 링크 한 개를 제공한다.

- 링크 복사, 성공한 clipboard 동작 뒤 `campaign/copied/`를 best-effort 호출하며 실패해도 복사 성공을 되돌리지 않음
- 추천 공유 문구 복사
- QR 표시·PNG 저장
- 링크 활성/중지
- 링크 재발급, 확인 modal에서 “기존 링크는 새 지원을 받지 않아요” 설명
- 누적 방문·지원·합류 수
- 공개 페이지가 꺼져 있으면 “페이지를 공개하면 링크로 지원을 받을 수 있어요” CTA

Threads·TikTok·Instagram·채용 사이트 선택 UI는 이 출시에서 노출하지 않는다. 데이터 enum만 준비되어 있고 Phase 2 승인 뒤 생성 기능을 연다.

QR은 새 의존성 `qrcode`와 타입 `@types/qrcode`를 사용해 브라우저에서만 생성한다. `npm install qrcode && npm install -D @types/qrcode`로 lockfile을 갱신하고, QR 안에는 공개 URL 외 개인정보를 넣지 않는다. 저장 파일명은 `inpa-recruiting-qr.png`로 고정한다.

- [ ] **Step 9.5: `정착 지원` 탭을 완성한다.**

- 예정·오늘·지난 확인을 구분
- 1·4·8·13주 질문과 상태 선택
- `도움 필요`일 때 blocker와 next_support 필수
- 저장 뒤 완료 시각 표시, 재수정 가능
- 활동 중단 시 이후 미완료 주차를 `stopped`로 일괄 정리할지 확인 modal
- 관리자이면 하단에 팀원별 상세가 아닌 Task 7의 aggregate 카드만 추가

- [ ] **Step 9.6: 접근성과 모바일 상태를 확인한다.**

- 모든 탭/button/modal에 focus-visible
- 단계 색만으로 의미 전달하지 않고 label 병기
- 320px에서 가로 overflow 없음
- touch target 최소 44px
- loading skeleton이 최종 card 크기와 유사
- 지원자 0명, 정착 0명, 네트워크 오류, 401 세션 만료 상태 포함

- [ ] **Step 9.7: build와 copy lint를 통과시킨다.**

```bash
cd inpa_fe
npm run lint:copy
npm run build
```

- [ ] **Step 9.8: 커밋한다.**

```bash
git add inpa_fe/app/recruiting inpa_fe/components/recruiting inpa_fe/package.json inpa_fe/package-lock.json
git commit -m "feat(recruiting): build planner recruiting workspace"
```

---

## Task 10: 공개 지원·본인 관리·최종 합류 화면을 완성하기

**Files:**
- Create: `inpa_fe/app/r/[token]/page.tsx`
- Create: `inpa_fe/app/r/[token]/layout.tsx`
- Create: `inpa_fe/app/r/[token]/loading.tsx`
- Create: `inpa_fe/app/r/[token]/error.tsx`
- Create: `inpa_fe/app/r/manage/[token]/page.tsx`
- Create: `inpa_fe/app/r/manage/[token]/layout.tsx`
- Create: `inpa_fe/app/recruiting/join/[token]/page.tsx`
- Create: `inpa_fe/app/recruiting/join/[token]/layout.tsx`
- Create: `inpa_fe/app/recruiting/join/[token]/loading.tsx`
- Create: `inpa_fe/components/recruiting/public-application-form.tsx`
- Create: `inpa_fe/components/recruiting/join-confirmation.tsx`
- Modify: `inpa_fe/app/robots.ts`
- Reuse: `inpa_fe/lib/public-og.ts`

- [ ] **Step 10.1: 공개 페이지 metadata와 noindex를 구현한다.**

`/r/[token]` layout은 기존 `lib/public-og.ts` builder를 사용해 nested layout에서 OG 이미지가 사라지지 않게 한다. token·지원자 이름을 title/description에 넣지 않는다. `/r/[token]`, `/r/manage/[token]`, `/recruiting/join/[token]` 모두 layout/page metadata에서 `robots: { index: false, follow: false }`; `app/robots.ts`에서도 `/r/`, `/recruiting/join/`을 disallow한다.

- [ ] **Step 10.2: 공개 지원 페이지를 완성한다.**

화면 순서:

1. 리더 프로필 + “함께 오래 일할 동료를 찾고 있어요”
2. 지원 환경/정착 지원 3개
3. 이름·전화번호·경력·현재 소속(선택)·지역·연락 시간
4. 동의 전문 펼침 + 필수 체크
5. `먼저 이야기 나눠보기`

폼을 처음 열 때 `crypto.randomUUID()`로 `submission_key`를 만들고 성공 응답 전까지 같은 값을 재사용한다. 중복 제출·double click은 submit lock으로 막고, 네트워크 재시도도 같은 key를 보내 같은 결과를 받는다. 성공 뒤 form을 숨긴다. 410 링크는 “이 링크를 보내주신 설계사에게 새 링크를 받아보세요”로 안내한다.

성공 시 받은 manage token은 `inpa_recruiting_manage`에 저장한다. 다른 영입 링크에서 다시 신청할 때 이 token을 `prior_manage_token`으로 보낸다. 서버가 `choice_required`를 반환하면 현재 리더 유지·새 리더 선택 두 카드를 보여주고, 후보의 버튼 클릭 전에는 어느 리더에게도 새 신청 알림이 가지 않는다. localStorage token만으로 기존 이름·전화·신청 내용은 읽을 수 없다. 연락 중단 또는 token 만료 시 저장값을 지운다.

- [ ] **Step 10.3: 지원자 본인 관리 화면을 완성한다.**

manage token으로 지원 일시·리더 공개 이름·현재 연락 상태만 보여준다. 저장된 전화번호·현재 소속을 다시 화면에 출력하지 않는다. `연락 그만 받기` 버튼은 확인 modal 뒤 API를 호출하고, 성공하면 localStorage token도 지운다. 성공 화면에는 다시 활성화 버튼을 제공하지 않는다.

이미 팀 합류한 token이면 `연락 그만 받기` 대신 “계정에서 연결 상태 확인하기”와 “문의 남기기”를 보여준다. 공개 token만으로 인증된 `Profile.manager`를 끊거나 계정을 삭제하지 않는다.

- [ ] **Step 10.4: 합류 전 로그인 복귀를 구현한다.**

합류 페이지 진입 즉시 안전 경로를 `rememberAuthReturn()`에 저장한다.

- 비로그인: 리더 정보 + `로그인하고 합류하기`, `처음이라면 가입하기`
- 로그인 + onboarding 미완료: `/onboarding`으로 이동, 복귀 경로 유지
- 로그인 완료: 현재 연결 상태와 최종 확인 버튼
- 다른 리더 연결: 409 메시지 뒤 두 번째 확인 modal에서만 `confirm_switch=true`
- 성공: “팀 연결이 완료됐어요. 이제 인파에서 함께 일할 흐름을 이어갈 수 있어요.” + `/home`

- [ ] **Step 10.5: 브라우저에서 세 인증 흐름을 검증한다.**

로컬 서버를 띄운 뒤 브라우저로:

1. 기존 사용자 로그인 → 기존처럼 `/home`
2. 비로그인 합류 링크 → 로그인 → 합류 링크 복귀 → 수락
3. 신규 가입 → 이메일 인증 → 로그인 → 온보딩 → 합류 링크 복귀 → 수락
4. Google 로그인 → 온보딩 필요/불필요 두 경우 복귀
5. `next=https://example.com`, `next=//example.com` → 항상 `/home`

- [ ] **Step 10.6: build와 copy lint를 통과시킨다.**

```bash
cd inpa_fe
npm run lint:copy
npm run build
```

- [ ] **Step 10.7: 커밋한다.**

```bash
git add inpa_fe/app/r inpa_fe/app/recruiting/join inpa_fe/components/recruiting inpa_fe/app/robots.ts
git commit -m "feat(recruiting): add public application and team join pages"
```

---

## Task 11: 메뉴·알림·홈·기존 관리자 화면을 최소 접점으로 연결하기

**Files:**
- Modify: `inpa_fe/components/app-nav.tsx`
- Modify: `inpa_fe/components/bottom-nav.tsx`
- Modify: `inpa_fe/app/home/page.tsx`
- Modify: `inpa_fe/app/notifications/page.tsx`
- Modify: `inpa_fe/app/manager/page.tsx`
- Create: `inpa_fe/components/recruiting/manager-promotion-modal.tsx`

- [ ] **Step 11.1: `설계사 영입`을 고객과 다른 메뉴로 추가한다.**

desktop sidebar에는 `설계사 영입`을 1급 메뉴로 추가한다. mobile bottom 5개 구조는 유지하고 `더보기` 안에 넣는다. 고객 메뉴의 label·route·badge는 바꾸지 않는다. 읽지 않은 영입 알림 수는 영입 메뉴에만 표시한다.

`profile.recruiting_enabled=false`면 sidebar·더보기·홈 빠른 실행을 모두 숨긴다. 직접 URL은 BE 404를 다음 행동 안내로 바꾸고 고객 화면으로 보내지 않는다.

frontend의 `isManager` 판정은 `managed_agents_count > 0`에서 API의 `profile.is_manager`로 바꿔 팀원이 0명이 되어도 역할이 유지되게 한다. 기존 manager 화면 자체의 권한 응답은 바꾸지 않는다.

- [ ] **Step 11.2: 홈 빠른 실행을 6개 균형으로 정리한다.**

`설계사 영입` 빠른 실행을 `/recruiting`으로 추가하고, desktop 6열·tablet 3열·mobile 2열로 정렬한다. 고객 등록·분석·일정 등 기존 링크 순서와 동작은 유지한다.

- [ ] **Step 11.3: 알림 action route를 유형별로 연결한다.**

application/followup 알림은 `/recruiting?tab=status`, settlement 알림은 `/recruiting?tab=settlement`, Manager 활성화 알림은 `/manager`로 이동한다. 기존 notification type route는 변경하지 않는다.

- [ ] **Step 11.4: 중복 일반 초대 UI만 새 흐름으로 유도한다.**

`/manager`의 기존 `TeamInviteCard`를 제거하거나 숨기고 다음 CTA 카드로 바꾼다.

```text
함께 일할 설계사 찾기
내 영입 페이지를 보내고, 대화부터 합류 뒤 정착까지 한곳에서 이어가세요.
[설계사 영입 열기]
```

기존 backend `/manager/invite-*`와 이미 발급된 링크는 삭제하지 않는다. URL 회귀 테스트로 계속 동작함을 확인한다.

- [ ] **Step 11.5: 최초 Manager 안내 modal을 조건부로 띄운다.**

조건:

```typescript
profile.is_manager &&
profile.manager_promoted_at !== null &&
profile.manager_promotion_seen_at === null
```

문구:

```text
Manager로 승격되었어요
첫 팀원이 합류해 팀 관리 기능이 열렸습니다. 추가 결제 없이 계속 이용할 수 있어요.
[팀 현황 보기] [다음 설계사 영입하기]
```

`팀 현황 보기`와 `다음 설계사 영입하기`, 닫기 버튼 모두 ack API를 먼저 호출한다. 첫 버튼은 `/manager`, 두 번째는 `/recruiting?tab=page`로 이동한다. `profile.recruiting_enabled=false`인 짧은 rollout 구간에는 두 번째 버튼을 `확인`으로 바꿔 닫기만 한다. 실패하면 modal을 닫지 않고 다시 시도할 수 있게 한다. legacy manager와 migration으로 seen 처리된 기존 사용자는 뜨지 않는다.

- [ ] **Step 11.6: 브라우저 회귀를 확인한다.**

- 일반 설계사: 영입 메뉴 보임, manager 메뉴는 기존 조건 유지
- 첫 팀원 합류 manager: modal 1회, 새로고침 뒤 재노출 없음
- 팀원 0명으로 감소: Manager role/menu 유지
- 알림 badge: 고객/일정 수와 섞이지 않음
- 기존 일반 초대 링크: 신규 가입 연결 성공

- [ ] **Step 11.7: 검증·커밋한다.**

```bash
cd inpa_fe
npm run lint:copy
npm run build
git add inpa_fe/components/app-nav.tsx inpa_fe/components/bottom-nav.tsx inpa_fe/app/home/page.tsx inpa_fe/app/notifications/page.tsx inpa_fe/app/manager/page.tsx inpa_fe/components/recruiting
git commit -m "feat(recruiting): connect navigation notifications and promotion UX"
```

---

## Task 12: 운영자가 개발자 없이 관리할 영입 페이지를 완성하기

**Files:**
- Create: `inpa_fe/app/admin/recruiting/page.tsx`
- Modify: `inpa_fe/app/admin/layout.tsx`
- Modify: `inpa_fe/lib/adminApi.ts`

- [ ] **Step 12.1: 운영자 화면을 네 구역으로 만든다.**

1. 이번 달 방문·지원·합류·정착 완료·Manager 활성화
   - 상단에 현재 기능 상태와 180일/30일 정리 정책을 read-only로 표시
2. 보존/정리 대상, 이름·전화 가림, 즉시 정리 버튼
3. 지원 문구·FAQ CRUD, 순서·활성화
4. Manager 활성화 이력
5. PII 없는 담당 변경·연락 중단·삭제 작업 이력

지원자 상세 연락처를 복원하거나 내려받는 기능은 제공하지 않는다. CSV export도 제외한다.

- [ ] **Step 12.2: 모든 운영 동작에 상태를 제공한다.**

- loading skeleton
- 빈 상태마다 다음 행동
- template 저장 성공/실패
- purge 2단 확인 + 사유 enum 선택
- API 403은 관리자 로그인 안내
- 모바일에서 표를 card로 변환

- [ ] **Step 12.3: 운영자 nav에 `설계사 영입`을 추가한다.**

기존 `/admin/usage`, 문의, 결제 메뉴와 분리된 항목으로 추가한다. customer admin 통계에 합치지 않는다.

- [ ] **Step 12.4: 브라우저 왕복을 검증한다.**

1. template 문구 수정
2. 설계사 page 편집 탭에서 새 문구 확인
3. 공개 페이지에서 선택 문구 확인
4. 지원 제출
5. admin 목록에서 가린 값 확인
6. purge 실행
7. 설계사 상세에서 연락처가 사라지고 연락 알림이 더 생성되지 않음 확인

- [ ] **Step 12.5: 검증·커밋한다.**

```bash
cd inpa_fe
npm run lint:copy
npm run build
git add inpa_fe/app/admin/recruiting inpa_fe/app/admin/layout.tsx inpa_fe/lib/adminApi.ts
git commit -m "feat(admin): add recruiting operations console"
```

---

## Task 13: 가격 화면을 Plus 단일 구매·Manager 자동 활성화로 정렬하기

**Prerequisite:** 현재 `brand-story-sections.tsx`, `landing-sections.tsx`, `cinema-landing.tsx`의 사용자 작업이 깨끗한 commit에 포함된 뒤 시작한다. 이 조건이 충족되지 않으면 해당 파일을 이 feature branch에서 건드리지 않고, 같은 검증을 거치는 별도 후속 커밋으로 수행한다. 사용자 변경을 덮어쓰거나 재포맷하지 않는다.

**Files:**
- Modify: `inpa_fe/components/upgrade-modal.tsx`
- Modify: `inpa_fe/components/brand-story-sections.tsx`
- Modify if the same price copy is directly rendered: `inpa_fe/components/landing-sections.tsx`
- Test: rendered pricing/upgrade browser states

- [ ] **Step 13.1: 현재 가격 렌더 위치와 dirty diff를 다시 확인한다.**

```bash
git status --short
git diff -- inpa_fe/components/brand-story-sections.tsx inpa_fe/components/landing-sections.tsx inpa_fe/components/cinema-landing.tsx
rg -n 'manager|Manager|19,900|플러스|Plus' inpa_fe/components inpa_fe/app
```

Expected: 수정 대상의 현재 문맥을 확인하고, unrelated landing diff가 있으면 먼저 깨끗한 기준점으로 가져온다.

- [ ] **Step 13.2: 신규 구매 선택을 Plus 하나로 통일한다.**

- upgrade reason이 manager 기능이어도 선택 plan code는 `plus`
- legacy `manager` plan code를 API 타입/운영자 화면에서는 삭제하지 않음
- 가격 카드는 하나의 Plus 안에 `Plus for 설계사`와 `Plus for Manager` 두 성장 상태를 나란히 보여주고 둘 다 19,900원(VAT 별도)으로 표시한다. 결제 CTA는 하나이며 `plus`로 연결한다.
- 카드 문구:

```text
Plus
설계사 업무부터 팀 관리까지 같은 가격으로 이어집니다.

Plus for 설계사   월 19,900원, VAT 별도
Plus for Manager  월 19,900원, VAT 별도

첫 팀원이 합류하면 추가 결제 없이 Manager 기능이 자동으로 열려요.
```

기존 Manager 구독자에게 “변경 필요” 또는 “곧 종료” 문구를 보이지 않는다.

- [ ] **Step 13.3: 결제 불변을 브라우저와 API로 확인한다.**

1. Plus 사용자 첫 팀원 합류 전 구독 JSON 저장
2. 팀원 합류
3. 구독 JSON의 plan/status/start/expiry 동일 확인
4. UI role만 Manager로 변경 확인
5. legacy Manager 계정의 기존 기능 접근 확인

- [ ] **Step 13.4: desktop/mobile 시각 검증 후 커밋한다.**

```bash
cd inpa_fe
npm run lint:copy
npm run build
```

브라우저 1440px·390px에서 가격 카드 줄바꿈, CTA, VAT 표기, Manager 설명을 확인한다.

```bash
git add inpa_fe/components/upgrade-modal.tsx inpa_fe/components/brand-story-sections.tsx inpa_fe/components/landing-sections.tsx
git commit -m "feat(pricing): include manager tools in plus"
```

`landing-sections.tsx`가 실제로 수정되지 않았다면 stage 목록에서 제외한다.

---

## Task 14: 전체 회귀·적대 검토·preview 준비

**Files:**
- Modify only after implementation is merged and deployed: `README.md`, `AGENTS.md`
- Create during implementation evidence if existing convention supports it: `docs/dev/` runbook section for recruiting retention/admin

- [ ] **Step 14.1: migration 정합을 확인한다.**

```bash
cd inpa_be
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py check
python manage.py shell -c "from inpa.recruiting.models import RecruitingCandidate; print(RecruitingCandidate._meta.db_table)"
```

Expected: pending migration 없음, system check 0 issues, 테이블명 출력.

- [ ] **Step 14.2: backend 전체 테스트를 실행한다.**

```bash
cd inpa_be
python manage.py test inpa
```

Expected: 전체 통과. 기존 test count보다 신규 영입 테스트만큼 증가.

- [ ] **Step 14.3: frontend 전체 gate를 실행한다.**

```bash
cd inpa_fe
npm run lint:copy
npm run build
```

Expected: 금지 표현·em-dash 0, Next production build 통과.

- [ ] **Step 14.4: 고객 무접점 회귀 잠금을 확인한다.**

```bash
BASE=$(cat /tmp/inpa-recruiting-base.txt)
git diff --exit-code "$BASE" -- inpa_be/inpa/customers inpa_fe/app/customers inpa_fe/app/customer
rg -n "Customer|customer_id|customerId" inpa_be/inpa/recruiting inpa_fe/app/recruiting inpa_fe/app/r inpa_fe/components/recruiting -g '!**/tests/**'
```

Expected:

- 첫 명령 diff 없음
- 두 번째 명령은 모델·타입·API 참조 0. 한국어 UI 문구의 `고객`은 이 영문 식별자 검색에 걸리지 않음
- `tests/test_models.py`의 `customers.customer` 문자열은 의도한 역방향 격리 회귀 테스트라 검색에서 제외

- [ ] **Step 14.5: 데이터·권한 적대 테스트를 수동으로 재현한다.**

| 공격/실수 | 기대 결과 |
|---|---|
| 설계사 A token으로 설계사 B candidate id 조회 | 404 |
| admin이 일반 candidate API로 타인 정보 조회 | 404 |
| 같은 전화번호로 두 리더 페이지 지원 | 각 owner에 별도 행, 상호 정보 노출 없음 |
| `stage=team_join` PATCH | 400, 단계 불변 |
| 만료/변조 join token | 410/400, 내부 id·이름 없음 |
| 다른 리더가 있는 계정의 첫 accept | 409, 관계 불변 |
| confirm accept | 관계 변경, 이전 manager에게 새 리더 정보 없음 |
| 연락 중단 뒤 reminder job | 알림 0 |
| 팀원 0명 | Manager 역할 유지 |
| Plus 만료 | 데이터 유지, paid team gate만 닫힘 |
| Manager 승격 전후 subscription diff | 완전 동일 |
| 악성 auth next URL | `/home` |

- [ ] **Step 14.6: 주요 브라우저 E2E를 수행한다.**

최소 두 계정(리더·경력 설계사)과 관리자 계정으로:

```text
리더 페이지 공개
→ 관계형 링크 복사
→ 비로그인 지원
→ 리더 알림/영입 현황
→ 첫 연락/대화/만남 단계
→ 합류 링크 발급
→ 설계사 로그인/가입 복귀
→ 최종 수락
→ Manager 1회 안내
→ 1·4·8·13주 일정 생성
→ 정착 상태 저장
→ 운영자 집계·가린 연락처·정리
```

1440px, 768px, 390px, 320px에서 확인하고 console error 0을 증거로 남긴다.

- [ ] **Step 14.7: 5관점 코드 리뷰를 수행한다.**

`superpowers:requesting-code-review`로 다음을 별도 확인한다.

1. 정확성: 단계·중복·idempotency·KST 날짜
2. 보안/개인정보: owner 경계·토큰·PII log/event·삭제
3. 기존 기능 회귀: 고객·일반 초대·manager dashboard·billing
4. UX/카피: 고객과 혼동 없음·모바일·오류·빈 상태·쉬운 말
5. 운영: admin CRUD·보존 작업·알림 중복·rollback

확인된 지적은 수정 후 해당 테스트를 다시 실행한다. 기각한 지적은 이유와 증거를 리뷰 기록에 남긴다.

- [ ] **Step 14.8: preview 배포 전 체크리스트를 준비한다.**

- env preview: `RECRUITING_ENABLED=True`, `RECRUITING_RETENTION_DAYS=180`, `RECRUITING_TOMBSTONE_DAYS=30`
- env production default: `RECRUITING_ENABLED=False`; PM 승인·preview 확인 뒤 같은 배포에서 True로 변경
- migration 순서와 rollback: 신규 앱 테이블·additive Profile 필드·notification type/dedupe·Plus capability
- 공개 지원 URL·인증 API·메뉴가 같은 flag를 따르는지 false/true 두 상태 확인
- 실제 preview URL에서 `/r`, join, auth return, admin을 재검증
- rollback 1순위는 `RECRUITING_ENABLED=False`로 메뉴·신규 제출·합류를 즉시 닫는 것. 이미 생긴 데이터 정리 job과 admin은 계속 동작
- 코드 rollback은 이전 배포 commit으로 되돌리되 additive table/field는 남겨 데이터 손실을 피함. destructive down migration은 production rollback에 사용하지 않음
- 프로덕션 merge/deploy는 여기서 멈추고 PM 승인 요청

- [ ] **Step 14.9: merge·production deploy가 실제 완료된 뒤 두 문서를 갱신한다.**

배포 전에는 `README.md`/`AGENTS.md`를 완료 상태로 쓰지 않는다. 배포 후:

- `README.md`: 설계사 영입, 지원자 별도 관리, Manager 자동 활성화, 네 탭을 PM용 쉬운 말로 설명
- `AGENTS.md`: recruiting 앱 모델/API/권한/retention/gotcha, Profile promotion, Plus capability, 공개 token route 추가
- 실제 production URL과 daily job 결과를 확인한 뒤 완료 보고

---

## 승인 설계 추적표

| 승인 결정 | 구현 Task | 기계적 증거 |
|---|---:|---|
| 고객과 지원자 완전 분리 | 1·2·7·14 | FK introspection test, 고객 경로 diff 0, 분리 집계 test |
| 1차 메뉴 `설계사 영입`과 네 탭 | 9·11 | desktop/mobile 브라우저 QA |
| 관계형 개인 링크 우선 | 2·9·10 | 기본 relationship campaign, 공개 지원 E2E |
| 후보가 리더 유지·변경 선택 | 2·10 | manage-token 증명, choice API 권한 test |
| 실제 팀 합류만 `team_join` | 2·4 | manual PATCH 400, accept transaction test |
| 첫 팀원 합류 시 Manager 한 번 활성화 | 3·4·11 | row lock/idempotency/1회 modal test |
| Plus와 Manager 같은 요금, 구독 불변 | 3·6·13 | subscription 전후 완전 diff, 가격 시각 QA |
| 1·4·8·13주 최소 정착 | 4·5·9 | 정확히 4개 생성, due reminder, UI 저장 test |
| 개인정보 최소 수집·연락 중단·180일 삭제 | 1·2·5·12 | PII scrub/delete, active 보존, admin purge test |
| 기존 일반 초대·고객·요금 기록 호환 | 3·6·11·14 | 기존 account/customer/billing 전체 회귀 |
| 공개 채널·인파 광고는 후속 | Phase 2·3 | Phase 1 UI에 외부 채널 생성 없음 |

---

## Phase 2와 Phase 3의 명확한 경계

이 문서의 구현이 아래 release gate를 모두 통과한 뒤 별도 계획·승인으로 시작한다.

### Phase 2: 공개 채널별 캠페인

시작 조건: 관계형 링크 지원 30건 이상 또는 4주 운영, 중복률·첫 연락률·합류율·연락 중단률 확인.

추가 범위:

- Threads·TikTok·Instagram·사람인·잡코리아별 링크 생성
- 채널별 문구 템플릿과 UTM
- 채널별 지원·첫 연락·합류 집계
- 캠페인 중지·복제

기존 `RecruitingCampaign.channel/public_token`을 그대로 쓰며 지원자 스키마는 바꾸지 않는다.

### Phase 3: 인파 공개 콘텐츠·광고에서 리더 연결

시작 조건: Phase 2에서 두 채널 이상 유효 지원이 발생하고, 리더 응답 기준·지원자 최종 선택·배분 공정성 운영 규칙이 문서로 확정됨.

추가 범위:

- 인파 콘텐츠/광고 공개 지원
- 지원자가 리더 후보를 보고 최종 선택
- 리더 응답 시간·일시 중지·배분 상한
- 광고 동의/개인정보 문구 버전 별도 관리

자동 배정은 하지 않는다. 지원자의 최종 선택이 항상 팀 관계 변경의 근거다.

## 완료 정의

이 기능은 다음 네 문장이 실제 테스트·화면·DB로 모두 증명될 때만 완료다.

1. 지원자는 보험가입 고객과 어떤 모델·API·검색·통계에서도 섞이지 않는다.
2. 실제 합류 링크 수락만 팀 관계와 `team_join`을 만든다.
3. 첫 팀원 합류는 Manager 역할만 자동 활성화하고 Plus 구독·가격·기간·사용량을 바꾸지 않는다.
4. 관계형 지원부터 13주 정착까지 설계사·지원자·운영자가 막힘 없이 각자 필요한 화면을 사용할 수 있다.
