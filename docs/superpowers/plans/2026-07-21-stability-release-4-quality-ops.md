# Release 4 품질 게이트·운영 정합·계측 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 베타에서도 실제 기능 사용량을 측정하고, 전체 백엔드 테스트를 외부 Git worktree 찌꺼기와 무관하게 통과시키며, 예외·404·검색 색인·키보드 복구 화면을 제품 수준으로 갖추고, 코드의 인프라 선언과 실제 Render 상태를 검증 가능한 한 장으로 맞춘다.

**Architecture:** 사용량 측정과 quota enforcement를 분리해 unlimited 모드에서도 UsageMeter를 증가시킨다. 보험 평가 명령은 Git porcelain record를 파싱해 실제 존재하는 worktree만 보안 경계로 사용하고, 존재하지 않는 `prunable` record만 무시한다. Next 16의 현재 `unstable_retry` 계약으로 root error boundaries를 추가하고 proxy에서 내부 경로의 `X-Robots-Tag`를 중앙 적용한다. 인프라와 의존성은 읽기 전용 현황 대조 후 안전한 변경만 한다.

**Tech Stack:** Django 5.2/PostgreSQL, Next.js 16.2.9/React 19, Vitest, Git CLI, npm audit, Render/Vercel.

## 2026-08-18 검증 결과 (아래 원문은 그대로 유지)

**이 릴리스 범위는 거의 전부 해소됐다.** 2026-08-18 세션에서 코드 대조 + 테스트 실행으로 확인했다.

해소:
- **베타 계측** (PR #174, 머지 `4b067b4`): `billing/credit.py::_consume`의 early return을 제거해 '차단은 없지만 계측은 하는' 계약으로 바꿨다. 무제한 모드에서도 `UsageMeter`가 증가하고, 반환 dict의 `limit`/`remaining`은 계속 `None`(호출자 계약 유지), `count`/`year_month`만 실제값이다. **핵심: 무제한일 때 `resolve_effective_plan`을 호출하지 않는다.** Free Plan 미시드 환경에서 RuntimeError로 계측이 죽는 것을 막기 위함이다. `GET /billing/usage/`는 무제한 시 한도·잔여를 null로 내리되 `_build_usage_response(hide_limits_when_unlimited=)`로 분리해 관리자 경로는 명목 한도를 유지한다. 환불 대칭성은 `import_services`의 `credit_consumed`/`credit_year_month`로 이미 확보돼 추가 코드가 없었다. 마이그레이션 0. 검증: BE 2,585 OK/39 skip, billing+admin_console+consultations 548 OK.
- **전역 오류 경계** (PR #173, 머지 `52cf912`): FE 루트 `error.tsx`/`global-error.tsx`/`not-found.tsx` 신설. `global-error`는 전역 CSS가 적용되지 않아 인라인 스타일을 쓰고, 두 경계 모두 현행 Next 16 계약대로 `unstable_retry ?? reset`을 사용한다. Playwright로 실렌더 확인.
- 평가 명령 hermetic 실행: `extraction_eval.py`가 존재하지 않는 `prunable` record만 무시하도록 이미 처리됨.
- Render Blueprint 정합: 2026-07-22 `4251bdb`로 이미 처리됨.
- `docs/dev/20-devops-and-deploy.md`의 Render Free 플랜 표기: 2026-08-18에 Starter 운영 상태로 정정 완료 (같은 파일의 2026-07-22 전환 기록과 일치).

잔존:
- `analysis/models.py`의 `INSURANCE_TYPE` choices에 실손(3)이 없다.

아래 원문은 당시 구현 계획 기록으로 보존한다. 전체 잔존 목록은 `docs/superpowers/specs/2026-07-21-comprehensive-stability-upgrade.md` §0 참고.

## Global Constraints

- 승인 설계는 `docs/superpowers/specs/2026-07-21-comprehensive-stability-upgrade.md`의 Release 4다.
- `FREE_TIER_UNLIMITED=True`는 차단만 우회한다. 사용량 측정은 계속한다.
- 평가 데이터가 실제 live worktree 내부에 있으면 계속 `E_DATASET_PATH`로 거부한다.
- 존재하지 않는 path를 무시할 수 있는 유일한 경우는 같은 porcelain record에 `prunable` marker가 있는 경우다.
- root error UI는 error message·stack·digest를 사용자에게 노출하지 않는다.
- Next.js 구현 전 현재 설치본 `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md`를 다시 읽고 `unstable_retry`를 사용한다.
- 공개 마케팅 페이지만 색인 허용한다. 고객 token·인증 서비스·관리자·API는 noindex/no-follow다.
- `npm audit fix --force`, Next.js downgrade, major 버전 일괄 업데이트를 금지한다.
- Render actual service 조회는 읽기 전용이다. plan·instance·env·deploy 변경은 별도 PM 승인 없이는 하지 않는다.
- Production deploy 전 전체 테스트·build·migration order·rollback을 다시 확인한다.
- README와 AGENTS는 구현·병합·배포가 모두 끝난 뒤에만 갱신한다.
- 아래 커밋 단계는 PM이 별도로 요청한 경우에만 수행한다.

---

### Task 1: 베타 사용량 측정과 quota 차단을 분리

**Files:**

- Modify: `inpa_be/inpa/billing/credit.py`
- Modify: `inpa_be/inpa/billing/tests.py`
- Modify: `inpa_be/inpa/billing/views.py` only if response mapping assumes count 0
- Modify: `inpa_fe/lib/api.ts` only if the existing type rejects measured unlimited values

- [ ] **Step 1: unlimited 측정 테스트를 RED로 바꾼다.**

기존 `FreeTierUnlimitedSwitchTests`의 `count=0` 기대를 실제 측정 계약으로 교체한다.

```python
@override_settings(FREE_TIER_UNLIMITED=True)
def test_unlimited_mode_counts_without_enforcing(self):
    for _ in range(25):
        result = check_and_consume(self.user, 'ocr')
    self.assertEqual(result['count'], 25)
    self.assertIsNone(result['limit'])
    self.assertIsNone(result['remaining'])
    self.assertEqual(result['year_month'], UsageMeter.current_month())
    self.assertEqual(UsageMeter.objects.get(
        user=self.user, action='ocr',
        year_month=UsageMeter.current_month()).count, 25)
```

추가 테스트:

```python
def test_unlimited_bulk_counts_all_rows(self): ...
def test_unlimited_never_raises_when_measured_count_exceeds_plan_limit(self): ...
def test_zero_bulk_still_creates_no_meter(self): ...
def test_enforcement_off_to_on_uses_existing_measured_count(self): ...
```

마지막 테스트는 unlimited에서 10건 측정 후 switch를 False로 바꾸면 11번째 요청이 차단되는지 확인한다. 운영에서 switch 변경 전에 measured usage를 어떻게 해석할지 PM이 볼 수 있게 한다.

- [ ] **Step 2: 현재 무차감 구현의 RED를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.billing.tests.FreeTierUnlimitedSwitchTests inpa.billing.tests.BulkCustomerQuotaTests -v 2`

Expected: early return 때문에 meter가 없어 실패.

- [ ] **Step 3: enforcement flag와 measurement 경로를 분리한다.**

```python
enforce_limit = not free_tier_unlimited()
plan = resolve_effective_plan(user)
actual_limit = plan.get_limit(kind)
display_limit = actual_limit if enforce_limit else None

with transaction.atomic():
    meter, _ = UsageMeter.objects.select_for_update().get_or_create(...)
    if enforce_limit and actual_limit is not None and meter.count + n > actual_limit:
        raise LimitExceeded(...)
    meter.count += n
    meter.save(update_fields=['count', 'updated_at'])
```

반환의 `limit`·`remaining`은 unlimited에서 계속 None이지만 `count`와 `year_month`는 실제 receipt다. docstring의 `무차감` 표현을 `차단 없이 측정`으로 바꾼다.

- [ ] **Step 4: RuntimeConfig DB 우선 계약을 유지한다.**

`@override_settings`만 바꿔도 이미 singleton row가 있으면 DB 값이 우선하는 기존 동작을 건드리지 않는다. 테스트 setUp에서 RuntimeConfig 상태를 명시해 환경 의존성을 없앤다.

- [ ] **Step 5: billing 전체 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.billing -v 2`

Expected: unlimited 25건 측정, 402는 0건, enforcement ON 회귀 PASS.

---

### Task 2: 보험 평가 명령을 stale prunable worktree와 무관하게 만들기

**Files:**

- Modify: `inpa_be/inpa/insurances/extraction_eval.py`
- Modify: `inpa_be/inpa/insurances/test_extraction_eval.py`

- [ ] **Step 1: porcelain record parser 테스트를 작성한다.**

```python
PORCELAIN = """worktree /repo
HEAD abc
branch refs/heads/main

worktree /private/tmp/deleted
HEAD def
detached
prunable gitdir file points to non-existent location
"""

def test_missing_prunable_worktree_is_ignored(self): ...
def test_missing_live_worktree_still_fails_closed(self): ...
def test_existing_prunable_path_is_still_a_protected_root(self): ...
def test_empty_or_malformed_porcelain_fails_closed(self): ...
```

- [ ] **Step 2: 실제로 실패했던 command 테스트를 환경 독립적으로 고정한다.**

`test_command_prints_aggregate_only_without_private_values`가 실제 머신의 worktree 목록에 기대지 않도록 subprocess output 또는 `_discover_git_worktree_roots`를 테스트 fixture로 mock한다. 별도 integration 테스트에서 parser와 discovery 결합을 검증한다.

- [ ] **Step 3: 현재 RED를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_extraction_eval.ExtractionOrchestrationTests.test_command_prints_aggregate_only_without_private_values -v 2`

Expected before fix: 로컬 Git 목록에 삭제된 prunable path가 있으면 `E_DATASET_PATH`.

- [ ] **Step 4: blank-line 단위 record parser를 구현한다.**

```python
@dataclass(frozen=True)
class WorktreeRecord:
    path: Path
    prunable: bool


def _parse_worktree_porcelain(output: str) -> tuple[WorktreeRecord, ...]:
    records = []
    for block in output.strip().split('\n\n'):
        lines = block.splitlines()
        worktree = next((line[9:] for line in lines
                         if line.startswith('worktree ')), None)
        if not worktree:
            raise EvalContractError('E_DATASET_PATH')
        records.append(WorktreeRecord(
            path=Path(worktree),
            prunable=any(line == 'prunable' or line.startswith('prunable ')
                         for line in lines),
        ))
    if not records:
        raise EvalContractError('E_DATASET_PATH')
    return tuple(records)
```

- [ ] **Step 5: 존재·prunable 규칙을 fail-closed로 적용한다.**

```python
for record in _parse_worktree_porcelain(output):
    try:
        roots.append(record.path.resolve(strict=True))
    except OSError:
        if record.prunable:
            continue
        raise EvalContractError('E_DATASET_PATH') from None
if not roots:
    raise EvalContractError('E_DATASET_PATH')
```

실재하는 prunable path는 roots에 포함한다. dataset path 자체의 strict 검증과 worktree 포함 거부는 변경하지 않는다.

- [ ] **Step 6: 단일 실패·평가 전체·insurances 앱 테스트를 실행한다.**

```bash
cd inpa_be
python manage.py test \
  inpa.insurances.test_extraction_eval.ExtractionOrchestrationTests.test_command_prints_aggregate_only_without_private_values \
  -v 2
python manage.py test inpa.insurances.test_extraction_eval -v 2
```

Expected: 삭제된 prunable record가 있어도 PASS, live missing·dataset-in-worktree 테스트는 계속 `E_DATASET_PATH`.

---

### Task 3: Next 16 root 오류·404·키보드 복구·내부 noindex 추가

**Files:**

- Create: `inpa_fe/app/error.tsx`
- Create: `inpa_fe/app/global-error.tsx`
- Create: `inpa_fe/app/not-found.tsx`
- Create: `inpa_fe/components/app-error-state.tsx`
- Modify: `inpa_fe/app/layout.tsx`
- Modify: `inpa_fe/app/globals.css`
- Modify: `inpa_fe/proxy.ts`
- Modify: `inpa_fe/app/robots.ts`
- Create: `inpa_fe/lib/route-indexing.ts`
- Create: `inpa_fe/components/__tests__/app-errors-and-indexing.test.tsx`
- Modify: `inpa_fe/components/__tests__/sitemap.test.tsx`

- [ ] **Step 1: 설치된 Next 16 문서를 다시 읽는다.**

Read:

```text
inpa_fe/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md
inpa_fe/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/not-found.md
inpa_fe/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md
```

확인할 계약: error boundary는 Client Component, prop은 `error`와 `unstable_retry`, global-error는 자체 `<html><body>` 필요.

- [ ] **Step 2: 오류·404 컴포넌트 테스트를 RED로 작성한다.**

```ts
it("retries a recoverable app error with unstable_retry", async () => ...);
it("does not render server error text or digest", () => ...);
it("global error owns html and body", () => ...);
it("not found offers home and login paths", () => ...);
```

사용자 문구는 `화면을 불러오는 중 문제가 생겼어요`, `다시 불러오기`, `홈으로 이동`처럼 다음 행동 중심으로 쓴다.

- [ ] **Step 3: 내부 경로 noindex matrix 테스트를 작성한다.**

`shouldNoIndex(pathname)`가 다음에 true인지 확인한다.

```text
/home /customers /customer/1 /analysis /schedule /sales /manager
/settings/account /notifications /promotion /boards/inquiry /admin
/s/token /b/token /c/token /d/ref /p/ref /r/token /api/anything
```

다음은 false다.

```text
/ /story /blog /blog/post /faq /data-policy
```

- [ ] **Step 4: 공통 오류 상태를 구현한다.**

`AppErrorState`는 title, message, retry, homeHref만 받는다. `error.tsx`와 `global-error.tsx`는 `useEffect`에서 `console.error`를 호출하지 않는다. Sentry instrumentation이 이미 예외를 수집하므로 PII가 포함될 수 있는 client error를 중복 출력하지 않는다.

```tsx
"use client";

export default function Error({ unstable_retry }: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return <AppErrorState onRetry={unstable_retry} />;
}
```

- [ ] **Step 5: skip link와 전역 focus-visible을 추가한다.**

RootLayout의 body 첫 interactive 요소로 `본문 바로가기` 링크를 넣고 children wrapper에 `id="main-content" tabIndex={-1}`를 둔다. CSS는 화면 밖 skip link가 focus 시 보이게 하고 button, link, input, select, textarea의 `:focus-visible` outline을 보장한다. `prefers-reduced-motion: reduce`에서 animation duration을 줄인다.

- [ ] **Step 6: proxy에서 noindex header를 중앙 적용한다.**

기존 new.inpa.kr redirect를 먼저 유지한다. redirect가 없는 www/preview 요청은 `NextResponse.next()`를 만들고 internal path이면 다음 header를 추가한다.

```ts
response.headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
```

`route-indexing.ts`의 prefix 목록은 `robots.ts` DISALLOW와 공유한다. `/s/`가 `/schedule`을 오탐하지 않도록 slash 경계를 테스트한다.

- [ ] **Step 7: 오류·색인·기존 host routing 테스트를 통과시킨다.**

Run:

```bash
cd inpa_fe
npm test -- --run components/__tests__/app-errors-and-indexing.test.tsx components/__tests__/sitemap.test.tsx
npm run test:landing
npm run build
```

Expected: 공식 공개 페이지 색인 유지, token·service·admin은 header noindex, host redirect 회귀 0.

---

### Task 4: Render 실제 상태와 Blueprint 선언을 읽기 전용으로 대조

**Files:**

- Modify: `render.yaml` only after actual state is verified
- Modify after deployed: `docs/dev/25-deploy-guide.md`
- Modify after deployed: `README.md`
- Modify after deployed: `AGENTS.md`

- [ ] **Step 1: 변경 없이 현재 Git 선언을 기록한다.**

현재 확인 대상:

```text
web inpa-be: render.yaml plan=free
keyvalue inpa-insurance-queue: starter
worker inpa-insurance-worker: standard
cron inpa-insurance-source-cleanup: starter
```

비밀 환경변수의 값은 읽거나 출력하지 않는다. 존재 여부와 서비스 연결 이름만 확인한다.

- [ ] **Step 2: Render 대시보드에서 실제 resource를 읽기 전용으로 확인한다.**

정확한 클릭 경로:

1. Render Dashboard에서 `inpa-be` 선택
2. `Settings` 선택
3. `Instance Type`의 현재 plan 이름 기록
4. `Events` 또는 `Deploys`에서 현재 commit이 AGENTS의 live commit과 같은지 기록
5. `inpa-insurance-worker`, `inpa-insurance-queue`, `inpa-insurance-source-cleanup`도 같은 방식으로 plan과 상태 기록

Expected: 서비스명·region·plan·현재 commit의 대조표가 완성된다. 변경 버튼은 누르지 않는다.

- [ ] **Step 3: actual과 desired가 다르면 코드 쪽만 최소 수정한다.**

- 실제 web이 Starter이고 승인된 desired도 Starter면 `render.yaml`의 web `plan: starter`로 수정한다.
- 실제 web이 free면 코드 변경을 하지 않고 AGENTS의 Starter 서술을 불일치로 기록한다.
- 실제 plan이 둘 중 어느 것도 아니거나 비용이 바뀌는 선택이 필요하면 작업을 멈추고 PM 결정 요청.

이 단계에서 Blueprint sync, plan 변경, redeploy는 하지 않는다.

- [ ] **Step 4: 시작·worker·cron 명령의 정합을 확인한다.**

Release 3 결과를 포함해 web migration/seed 순서, worker queue, hourly cleanup+calendar drain이 실제 서비스 command와 맞는지 대조한다. 실제 command 변경은 Production 승인 이후에만 한다.

- [ ] **Step 5: rollback 정보를 적는다.**

Release 보고에 다음을 남긴다.

- 이전 정상 Render deploy commit
- Vercel 이전 정상 deployment
- booking migration `0004`, `0005`의 backward 영향
- 새 gate 기본값 False
- worker queue 추가 전 command

비밀값과 DB URL은 기록하지 않는다.

---

### Task 5: 의존성 취약점은 상위 호환 범위에서만 정리

**Files:**

- Modify only if safe: `inpa_fe/package-lock.json`
- Modify only if required and compatible: `inpa_fe/package.json`
- Modify only for a confirmed runtime advisory: `inpa_be/requirements.txt`

- [ ] **Step 1: 변경 전 정확한 dependency tree와 감사 결과를 저장하지 않고 화면에만 확인한다.**

Run:

```bash
cd inpa_fe
npm ls postcss next @tailwindcss/postcss tailwindcss
npm audit --json
npm audit --omit=dev --json
npm outdated --json
```

민감정보가 없지만 audit JSON을 새 파일로 commit하지 않는다. 결과는 package, severity, direct/transitive, fixed version만 Release 보고에 요약한다.

- [ ] **Step 2: 안전한 수정 가능 여부를 결정한다.**

허용:

- 현재 semver range 안의 patch/minor lockfile refresh
- Next 16.2.x 유지 또는 공식 호환 상위 patch
- Tailwind 4 유지

금지:

- `npm audit fix --force`
- Next 16에서 구버전 major로 downgrade
- React 19 downgrade
- 취약점과 무관한 major 일괄 변경

- [ ] **Step 3: 안전한 lockfile 갱신이 가능할 때만 적용한다.**

먼저 `npm update postcss --package-lock-only`의 diff를 확인한다. Next/Tailwind major가 바뀌거나 peer conflict가 생기면 즉시 원복하고 변경 없음으로 기록한다. 원복은 해당 명령이 만든 lockfile hunk만 되돌리며 사용자 변경을 덮지 않는다.

- [ ] **Step 4: Python runtime 의존성을 감사한다.**

기존 audit tool 환경을 사용해 `inpa_be/requirements.txt`만 검사한다. 임시 audit venv의 pip/setuptools 경고는 제품 runtime advisory와 분리한다. 실제 runtime advisory가 있을 때만 공식 package changelog와 Django 호환성을 확인한 뒤 patch를 계획한다.

- [ ] **Step 5: 변경이 있으면 전체 설치·테스트·build를 재실행한다.**

```bash
cd inpa_fe
npm ci
npm test -- --run
npm run lint:copy
npm run build
```

Expected: lockfile 재현 설치 성공. 안전한 수정 경로가 없으면 취약점 수와 이유를 `Unverified/accepted risk`로 명시하고 억지 수정하지 않는다.

---

### Task 6: 전체 회귀·런타임·접근성·보안 검증

**Files:**

- No product file changes
- Review: Release 1~4 전체 변경 파일

- [ ] **Step 1: Backend 전체 suite를 깨끗하게 실행한다.**

```bash
cd inpa_be
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test inpa -v 2
```

Expected: 기존 1,676 이후 실패했던 eval command 포함 전체 PASS. skip 수는 이유와 함께 기록한다.

- [ ] **Step 2: PostgreSQL 전용 경쟁 테스트를 실행한다.**

```bash
DATABASE_URL="$INPA_TEST_DATABASE_URL" \
DJANGO_SETTINGS_MODULE=config.settings.test_postgres \
  python manage.py test \
  inpa.booking.test_postgres_concurrency \
  inpa.insurances.test_import_concurrency \
  -v 2
```

환경변수는 실제 실행 환경의 승인된 비밀 주입 방식을 사용한다. 명령 출력에 연결 문자열을 노출하지 않는다.

- [ ] **Step 3: Frontend 전체 gate를 실행한다.**

```bash
cd ../inpa_fe
npm ci
npm test -- --run
npm run test:unit
npm run test:landing
npm run lint:copy
npm run build
```

Expected: unit·routing·copy·Next build 전부 PASS.

- [ ] **Step 4: local runtime API를 실제 호출한다.**

synthetic fixture로 다음 흐름을 확인한다.

1. 로그인
2. 고객 생성
3. gate closed heatmap 조회
4. 소개카드 invalid/valid 전화번호 제출
5. snapshot 공유 발급·조회·철회
6. 예약 pending·accept·cancel
7. calendar outbox worker fake adapter 실행
8. unlimited usage meter 증가 확인

각 API의 status, code, DB row count를 기록한다.

- [ ] **Step 5: 브라우저 matrix를 확인한다.**

Viewport 320px, 390px, 768px, 1440px에서 다음을 확인한다.

- `/analysis`, `/customers`, `/schedule`, `/settings/meetings`
- `/s`, `/b`, `/c`, `/d`, `/p` synthetic token
- root error fallback과 unmatched 404
- keyboard-only skip link, focus ring, dialog 닫기, retry
- offline/Slow 3G 복구
- console error와 horizontal overflow 0

- [ ] **Step 6: HTTP header를 확인한다.**

```bash
curl -I http://localhost:3000/home
curl -I http://localhost:3000/s/synthetic-token
curl -I http://localhost:3000/story
```

Expected: 내부·token 경로는 `X-Robots-Tag: noindex, nofollow, noarchive`, `/story`는 해당 header 없음.

- [ ] **Step 7: 보안·개인정보 검토를 수행한다.**

검토 대상:

- owner scope와 public token 권위
- 동의 receipt 선커밋
- outbox log/exception/admin PII
- secret diff와 `.env` 추적 여부
- HTML error에 stack/digest 미노출
- dependency downgrade·force fix 없음

gitleaks를 기존 CI와 같은 방식으로 실행할 수 있으면 실행하고 결과를 기록한다.

- [ ] **Step 8: 독립 adversarial review를 수행하고 발견 사항을 닫는다.**

관점은 correctness, security/privacy, UX/accessibility, insurance/compliance, operations/cost다. Critical/Important 0이 될 때까지 수정·재검증한다. 기각 항목은 코드 근거와 함께 기록한다.

---

### Task 7: Preview·Production 승인 경계와 문서 마감

**Files:**

- Modify after implemented + merged + deployed: `README.md`
- Modify after implemented + merged + deployed: `AGENTS.md`
- Modify after deployed if Render actual changed: `docs/dev/25-deploy-guide.md`

- [ ] **Step 1: 변경 범위와 user-owned diff를 분리한다.**

```bash
git status --short
git diff --check
git diff --stat
git diff --name-only
```

랜딩, boards seed/tests, Manager 요금제 파일과 이번 계획 전부터 있던 `.Codex/failures.md` 변경을 stage하지 않는다.

- [ ] **Step 2: PM이 커밋을 요청한 경우에만 작은 Conventional Commit으로 나눈다.**

권장 경계:

```text
fix(분석): 기준선 판정 계약과 안전 게이트 적용
fix(동의): 셀프진단 동의 증적 선커밋
fix(공유): 스냅샷 공개 권위와 사실성 강화
fix(화면): 오류 상태와 KST 요청 경합 수정
fix(예약): 상태기계와 캘린더 outbox 추가
fix(계측): 베타 사용량 측정 유지
test(평가): prunable worktree 독립성 보강
feat(품질): 전역 오류 복구와 내부 noindex 추가
```

공유 작업트리에서는 각 커밋의 파일만 명시적으로 `git add`한다.

- [ ] **Step 3: Preview 배포 전 rollback을 확인한다.**

- FE: 이전 Vercel deployment ID
- BE: 이전 Render deploy commit
- DB: booking 0005 -> 0004 -> 0003 순서의 down 가능성, outbox 데이터 영향
- gate: 두 신규 gate False
- worker: 이전 queue command

- [ ] **Step 4: Preview 배포도 PM 요청 범위 안에서만 수행한다.**

Preview에서 smoke를 반복하고 실제 URL·응답·화면을 기록한다. Production database, actual customer, actual policy PDF는 사용하지 않는다.

- [ ] **Step 5: Production은 별도 명시 승인을 받기 전 멈춘다.**

승인 요청에 반드시 포함할 것:

- 변경 요약과 위험 감소
- 전체 테스트 수·skip·build route 수
- migration 2개와 실행 순서
- Render worker/cron command 변화
- gate 기본값 False
- 예상 rollback
- 남은 dependency advisory 또는 미검증 Google 실계정 항목

- [ ] **Step 6: Production 승인 후 배포·실제 URL 검증·5분 관찰을 수행한다.**

승인된 경우에만 merge/auto-deploy를 진행한다. 배포 뒤 `/healthz/`, 주요 API, `www.inpa.kr` 공개·인증 화면을 확인하고 Sentry/Render logs에서 새 오류와 expected event flatline을 5분 관찰한다.

- [ ] **Step 7: 구현·병합·배포 완료 후 두 대상 문서를 갱신한다.**

`README.md`에는 PM이 이해할 수 있는 한국어 서비스 변화와 운영 상태를 쓴다. `AGENTS.md`에는 gate, 상태기계, outbox, KST, 공유 권위, 검증 수치, 실제 Render plan을 dense English로 반영하고 stale 설명을 제거한다.

- [ ] **Step 8: 최종 완료 보고를 작성한다.**

```text
Changed: [Release 1~4 실제 완료 범위]
Verified by: [BE/FE/PostgreSQL/API/browser/Preview/Production]
Result: [pass 수, route 수, HTTP 결과, 운영 상태]
Unverified: [없음 또는 명확한 잔여와 이유]
```
