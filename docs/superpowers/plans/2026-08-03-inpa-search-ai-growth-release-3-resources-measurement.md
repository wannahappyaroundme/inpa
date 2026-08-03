# Inpa Search and AI Growth Release 3: Resources and Measurement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Use spreadsheets:Spreadsheets when validating the downloadable CSV contract, superpowers:test-driven-development before product code, and superpowers:verification-before-completion before every success claim.

**Goal:** 개인정보를 서버로 보내지 않는 공개 실무 도구 3개를 제공하고, 검색·AI 유입이 가입 후 7일 안의 첫 분석과 첫 공유로 이어지는지 관리자 화면에서 확인한다.

**Architecture:** 보험나이 계산은 백엔드와 같은 순수 함수를 공용 모듈로 추출하고 계산기 입력은 브라우저 메모리에만 둔다. 고객 관리표는 헤더만 있는 UTF-8 CSV를 브라우저에서 생성하며, 상담 체크리스트는 브라우저 안 체크와 인쇄만 제공한다. 기존 UTM first-touch에 raw referrer 대신 allowlist source·channel을 보완하고, 기존 Profile UTM과 활성화 timestamp를 사용해 DB migration 없이 search/ai/direct/other 채널 퍼널을 반환한다.

**Tech Stack:** Next.js 16.2.9, React 19.2, TypeScript, Vitest, Vercel custom events, Django 5.2/DRF, existing `Profile.utm_*` and `AdminActivationFunnelView`.

## 공개 URL

- `/tools/insurance-age`: 기준일과 생년월일로 보험나이를 계산한다. 입력·결과를 저장하거나 전송하지 않는다.
- `/resources/customer-management-sheet`: 비어 있는 고객 관리 CSV를 내려받는다. 샘플 실명·전화번호는 넣지 않는다.
- `/resources/consultation-checklist`: 첫 상담 전·중·후 체크리스트를 화면에서 체크하고 인쇄한다. 체크 상태를 저장하지 않는다.

## 획득 채널 계약

| channel | 허용 source 예시 | 판정 근거 |
|---|---|---|
| `search` | `google_organic`, `naver_organic`, `bing_organic`, `daum_organic` | 명시 UTM이 없고 allowlist 검색 referrer인 경우 |
| `ai` | `chatgpt`, `chatgpt.com`, `perplexity`, `gemini`, `claude`, `copilot` | 명시 UTM 또는 allowlist AI referrer인 경우 |
| `direct` | `direct` | UTM·인식 가능한 referrer가 모두 없는 경우 |
| `other` | 기존 안전한 UTM source, `other_referral` | 위 세 그룹 외의 allowlist/sanitized source |

- 명시 `utm_source/medium/campaign`이 referrer 추정보다 우선한다.
- full referrer URL, path, query, hostname 원문은 저장하지 않는다.
- 기존 60자 `[A-Za-z0-9._-]` validation과 first-touch semantics를 유지한다.
- 과거 데이터는 source 매핑으로 분류하고 덮어쓰지 않는다.

## 파일 지도

- Create `inpa_fe/lib/insurance-age.ts`, `lib/insurance-age.test.ts`: 날짜 검증·보험나이 순수 함수.
- Create `inpa_fe/lib/acquisition.ts`, `lib/acquisition.test.ts`: safe source/channel 판정.
- Create `inpa_fe/lib/public-resource-events.ts`: enum-only Vercel events.
- Create `inpa_fe/components/search-hub-analytics.tsx`: 공개 허브 view·CTA enum event.
- Create `inpa_fe/components/insurance-age-calculator.tsx`.
- Create `inpa_fe/components/customer-management-sheet.tsx`.
- Create `inpa_fe/components/consultation-checklist.tsx`.
- Create `inpa_fe/components/__tests__/public-resources.test.tsx`.
- Create `inpa_fe/app/tools/insurance-age/page.tsx`.
- Create `inpa_fe/app/resources/customer-management-sheet/page.tsx`.
- Create `inpa_fe/app/resources/consultation-checklist/page.tsx`.
- Modify `inpa_fe/app/customer/[id]/page.tsx`: 공용 보험나이 함수 사용.
- Modify `inpa_fe/lib/useUtmCapture.ts`, `lib/api.ts`, `app/register/page.tsx`: safe acquisition first-touch 전달.
- Modify `inpa_fe/components/search-hub-page.tsx`: page key·cluster·CTA event 연결.
- Modify `inpa_be/inpa/admin_console/views.py`, `tests.py`: 채널별 퍼널 응답.
- Modify `inpa_fe/lib/adminApi.ts`, `app/admin/activation-funnel/page.tsx`: 채널 표와 7일 활성화 표시.
- Modify `inpa_fe/lib/search-policy.ts`, `app/sitemap.ts`, 관련 테스트: 공개 3개 추가.
- Create `docs/seo/ai-recommendation-audit.md`: 30개 질문, 엔진별 결과, 인용 URL, 날짜.

### Task 0: Release 2 운영 기준에서 격리 브랜치를 만든다

- [ ] **Step 1: 최신 master와 Release 2 운영 SHA를 확인한다**

```bash
git fetch origin
git log -1 --oneline origin/master
```

- [ ] **Step 2: 격리 worktree를 만든다**

```bash
git worktree add -b codex/inpa-search-ai-resources-measurement /tmp/inpa-search-ai-resources-measurement origin/master
```

- [ ] **Step 3: 전체 기준선을 실행한다**

```bash
cd /tmp/inpa-search-ai-resources-measurement/inpa_be
python manage.py check
python manage.py test inpa.admin_console.tests.AdminActivationFunnelTest
cd ../inpa_fe
npm run test:run
npm run lint:copy
npm run build
```

### Task 1: 보험나이 공용 계산을 골든 테스트로 고정한다

**Interface:**

```ts
export function computeInsuranceAge(birthDate: string, asOf: string | Date): number | null;
```

- [ ] **Step 1: 백엔드 규칙을 읽고 골든 케이스를 쓴다**

`inpa_be/inpa/customers/models.py::compute_insurance_age`를 기준으로 직전 생일 5개월 29일, 정확히 6개월, 윤년 2월 29일, 미래 생일, invalid date, 오늘 생일을 포함한다. 같은 날짜로 Python 결과와 TypeScript expected를 대조한다.

- [ ] **Step 2: RED를 확인한다**

```bash
npm run test:run -- lib/insurance-age.test.ts
```

- [ ] **Step 3: timezone에 흔들리지 않는 순수 함수를 구현한다**

`YYYY-MM-DD`를 숫자로 검증하고 UTC timestamp 차이가 아닌 달력 연·월·일 비교로 계산한다. 잘못된 날짜와 미래 날짜는 `null`이다.

- [ ] **Step 4: 고객 상세의 중복 함수를 제거하고 공용 함수를 사용한다**

기존 UI 결과가 같도록 현재 KST 날짜를 `YYYY-MM-DD`로 전달한다. normalized render diff 또는 동일 fixture assertion으로 변경 전후 값을 증명한다.

- [ ] **Step 5: FE와 BE 골든 테스트를 통과시킨다**

```bash
npm run test:run -- lib/insurance-age.test.ts
cd ../inpa_be
python manage.py test inpa.customers
```

- [ ] **Step 6: 계산 공용화만 커밋한다**

```bash
git add inpa_fe/lib/insurance-age.ts inpa_fe/lib/insurance-age.test.ts 'inpa_fe/app/customer/[id]/page.tsx'
git commit -m "refactor(고객): 보험나이 계산을 공용 골든 함수로 통합"
```

### Task 2: 공개 도구·자료 3개의 무저장 UX를 구현한다

- [ ] **Step 1: 실패하는 공개 자원 테스트를 쓴다**

다음을 검사한다.

- 보험나이 계산기는 생년월일·기준일, 계산 전 안내, invalid 안내, 결과·계산 기준, 초기화 버튼이 있다.
- 고객 관리표 CSV는 UTF-8 BOM과 `고객명,연락처,영업 단계,진행 상태,마지막 연락일,다음 행동,메모` 헤더만 포함하고 샘플 개인정보가 없다.
- 상담 체크리스트는 준비·상담·후속 3구간, 브라우저 체크, 전체 초기화, 인쇄가 있고 localStorage/sessionStorage/fetch를 호출하지 않는다.
- resource event payload는 `resource`, `action`, `page_kind` enum만 허용하고 입력값·생년월일·체크 상태를 받지 않는다.

- [ ] **Step 2: RED를 확인한다**

```bash
npm run test:run -- components/__tests__/public-resources.test.tsx
```

- [ ] **Step 3: 세 client component와 enum-only event helper를 구현한다**

계산기 state는 memory-only다. CSV는 click 시 Blob URL을 만들고 즉시 revoke한다. checklist는 React state와 `window.print()`만 쓴다. 세 페이지 모두 “입력 내용은 이 화면에서만 계산되며 저장되지 않아요”처럼 사실인 개인정보 안내를 한 곳에 둔다.

- [ ] **Step 4: 정적 공개 route와 metadata를 구현한다**

각 페이지는 `PublicSiteShell`, 고유 canonical/OG/index metadata, Breadcrumb/WebPage JSON-LD, 관련 solution/guide, `/register` CTA를 제공한다. empty·error·mobile·print 상태까지 완성한다.

- [ ] **Step 5: CSV를 spreadsheet skill로 검증한다**

`spreadsheets:Spreadsheets`를 사용해 생성된 CSV가 Excel과 Google Sheets에서 한글 헤더 7열, 데이터 0행으로 열리는지 확인한다. CSV formula injection이 일어날 사용자 셀 자체가 없음을 확인한다.

- [ ] **Step 6: 테스트·copy lint·browser QA를 통과시킨다**

```bash
npm run test:run -- components/__tests__/public-resources.test.tsx lib/insurance-age.test.ts
npm run lint:copy
```

390×844와 1440×900에서 calculator invalid/result, CSV download, checklist check/reset/print preview를 검수한다.

- [ ] **Step 7: 공개 자원만 커밋한다**

```bash
git add inpa_fe/lib/public-resource-events.ts inpa_fe/components/insurance-age-calculator.tsx inpa_fe/components/customer-management-sheet.tsx inpa_fe/components/consultation-checklist.tsx inpa_fe/components/__tests__/public-resources.test.tsx inpa_fe/app/tools/insurance-age/page.tsx inpa_fe/app/resources/customer-management-sheet/page.tsx inpa_fe/app/resources/consultation-checklist/page.tsx
git commit -m "feat(자료): 무저장 보험나이 도구와 실무 자료 공개"
```

### Task 3: safe first-touch 검색·AI 유입을 캡처한다

**Interfaces:**

```ts
export type AcquisitionChannel = "search" | "ai" | "direct" | "other";
export interface SafeAcquisition { utm_source?: string; utm_medium?: string; utm_campaign?: string }
export function inferSafeAcquisition(search: string, referrer: string): SafeAcquisition;
export function classifyAcquisitionSource(source: string): AcquisitionChannel;
```

- [ ] **Step 1: 명시 UTM 우선과 referrer allowlist 실패 테스트를 쓴다**

Google, Naver, Bing, Daum, ChatGPT, Perplexity, Gemini, Claude, Copilot, unknown host, malformed URL, empty referrer, explicit UTM override를 검사한다. 기존 운영 source인 `google`, `naver`, OpenAI referral 표준인 `chatgpt.com`도 각각 search·AI로 분류한다. 반환값과 serialized storage에 raw path/query가 없어야 한다.

- [ ] **Step 2: RED를 확인한다**

```bash
npm run test:run -- lib/acquisition.test.ts
```

- [ ] **Step 3: pure classifier를 구현한다**

hostname은 exact 또는 dot-boundary suffix만 허용한다. substring 매칭은 `notgoogle.com` 오분류 때문에 금지한다. unknown referrer는 `other_referral`, no referrer는 저장하지 않아 backend에서 direct로 집계되게 한다.

- [ ] **Step 4: 기존 UTM first-touch에 안전하게 연결한다**

`useUtmCapture`는 명시 UTM이 있으면 그대로 첫 저장하고, 없을 때만 safe inferred source/medium을 저장한다. `readCapturedUtm`과 register payload 계약은 유지한다. 저장·가입 오류가 주 흐름을 막지 않는 기존 catch 원칙을 유지한다.

- [ ] **Step 5: 테스트를 GREEN으로 만들고 커밋한다**

```bash
npm run test:run -- lib/acquisition.test.ts
git add inpa_fe/lib/acquisition.ts inpa_fe/lib/acquisition.test.ts inpa_fe/lib/useUtmCapture.ts inpa_fe/lib/api.ts inpa_fe/app/register/page.tsx
git commit -m "feat(유입): 검색·AI 첫 방문을 안전한 채널로 분류"
```

### Task 4: 관리자 활성화 퍼널을 channel 기준으로 확장한다

**Backend response additive contract:**

```json
{
  "acquisition_channels": [
    {"channel":"search","label":"검색","signups":0,"verified":0,"first_customer":0,"first_analysis":0,"first_share":0,"activated":0,"activation_rate":null},
    {"channel":"ai","label":"AI 답변","signups":0,"verified":0,"first_customer":0,"first_analysis":0,"first_share":0,"activated":0,"activation_rate":null},
    {"channel":"direct","label":"직접 유입","signups":0,"verified":0,"first_customer":0,"first_analysis":0,"first_share":0,"activated":0,"activation_rate":null},
    {"channel":"other","label":"기타","signups":0,"verified":0,"first_customer":0,"first_analysis":0,"first_share":0,"activated":0,"activation_rate":null}
  ]
}
```

- [ ] **Step 1: backend 실패 테스트를 쓴다**

source fixture `google_organic`, `naver_organic`, `chatgpt`, `perplexity`, empty, `newsletter`를 만들고 4 channel의 signup·verified·first_customer·first_analysis·first_share·activated·rate와 각 단계 총합 보존을 검증한다. 기존 `utm_sources` 응답도 그대로여야 한다.

- [ ] **Step 2: backend RED를 확인한다**

```bash
cd inpa_be
python manage.py test inpa.admin_console.tests.AdminActivationFunnelTest
```

- [ ] **Step 3: backend source mapper와 고정 순서 집계를 구현한다**

raw referrer 없이 `profile__utm_source`만 분류한다. constant map은 accounts나 analytics가 아니라 `admin_console`의 집계 helper에 두며, unknown은 other다. 신규 DB field나 migration은 만들지 않는다.

- [ ] **Step 4: backend 테스트를 GREEN으로 만든다**

```bash
python manage.py test inpa.admin_console.tests.AdminActivationFunnelTest
```

- [ ] **Step 5: frontend 실패 테스트와 UI를 구현한다**

`AdminActivationFunnelResponse`에 typed `acquisition_channels`를 추가하고 기존 source 표 위에 검색·AI·직접·기타 표를 렌더한다. 각 행은 가입, 인증, 첫 고객, 첫 분석, 첫 공유, 7일 활성화, 활성화율을 보여준다. loading, error, 0명 empty, null rate `-`를 유지한다. 화면 문구는 7일 내 첫 분석+첫 공유 정의를 그대로 설명한다.

- [ ] **Step 6: FE 테스트와 양쪽 전체 게이트를 통과시킨다**

```bash
cd inpa_fe
npm run test:run
npm run lint:copy
npm run build
cd ../inpa_be
python manage.py check
python manage.py test inpa
```

- [ ] **Step 7: 퍼널 확장만 커밋한다**

```bash
git add inpa_be/inpa/admin_console/views.py inpa_be/inpa/admin_console/tests.py inpa_fe/lib/adminApi.ts inpa_fe/app/admin/activation-funnel/page.tsx
git commit -m "feat(분석): 검색·AI 유입의 7일 활성화 분해 추가"
```

### Task 5: 공개 허브·자료 event와 sitemap을 연결한다

- [ ] **Step 1: enum event의 실패 테스트를 쓴다**

`search_landing_view`는 `page_key`, `cluster`만, `search_landing_cta_click`은 `page_key`, `cta_type`, `destination`만, `public_resource_use`는 `resource`, `action`, `page_kind`만 전송해야 한다. arbitrary key, URL, referrer, query, 생년월일, 체크 상태가 payload에 들어가면 테스트가 실패해야 한다.

- [ ] **Step 2: 허브 view·CTA와 자료 action을 연결한다**

`SearchHubAnalytics`는 mount 시 한 번만 view event를 보내고, 템플릿 CTA click은 destination enum으로 기록한다. public resource helper는 계산 완료, CSV 다운로드, checklist 인쇄만 기록한다. analytics 오류는 화면 동작을 막지 않는다.

- [ ] **Step 3: event 테스트를 GREEN으로 만든다**

```bash
cd inpa_fe
npm run test:run -- components/__tests__/search-hubs.test.tsx components/__tests__/public-resources.test.tsx
```

- [ ] **Step 4: event 연결만 커밋한다**

```bash
git add inpa_fe/lib/public-resource-events.ts inpa_fe/components/search-hub-analytics.tsx inpa_fe/components/search-hub-page.tsx inpa_fe/components/insurance-age-calculator.tsx inpa_fe/components/customer-management-sheet.tsx inpa_fe/components/consultation-checklist.tsx inpa_fe/components/__tests__/search-hubs.test.tsx inpa_fe/components/__tests__/public-resources.test.tsx
git commit -m "feat(분석): 공개 허브와 실무 자료의 enum 사용 이벤트 추가"
```

### Task 6: sitemap 연결, 30질문 기준선, 독립 리뷰를 완료한다

- [ ] **Step 1: sitemap·내부 링크 실패 테스트를 쓴다**

새 3개 URL이 sitemap과 solution/guide 관련 링크에 있고 private/token/legal URL은 여전히 없는지 검사한다.

- [ ] **Step 2: allowlist와 sitemap을 확장한다**

새 페이지 3개를 `search-policy.ts`에 추가하고 랜딩 discovery strip 또는 관련 guide에서 각 페이지로 최소 두 개의 내부 링크를 만든다.

- [ ] **Step 3: 전체 테스트·build를 다시 실행한다**

```bash
cd inpa_fe
npm run test:run
npm run lint:copy
npm run build
cd ../inpa_be
python manage.py check
python manage.py test inpa
cd ..
git diff --check
```

- [ ] **Step 4: 30개 AI 질문 감사표를 만든다**

`docs/seo/ai-recommendation-audit.md`에 고객관리 8, 증권정리 8, 상담·후속관리 7, 사실 비교 7개 질문을 고정한다. 각 행은 날짜, 엔진, 인파 언급 여부, 정확성, 인용 URL, 다음 개선으로 구성한다. 브라우저에서 접근 가능한 ChatGPT·Perplexity·Gemini·Claude 중 실제 결과만 기록하고 로그인/지역 제한은 `미확인`으로 명시한다. 자체 답변을 외부 엔진 결과처럼 기록하지 않는다.

- [ ] **Step 5: 독립 adversarial review를 수행한다**

`superpowers:requesting-code-review`로 날짜 계산, CSV 안전성, 무저장 주장, source spoofing, 퍼널 수학, 개인정보, 접근성, 검색 품질을 검토한다. Critical/Important 0까지 수정한다.

- [ ] **Step 6: 최종 기능 커밋을 만든다**

```bash
git add inpa_fe/lib/search-policy.ts inpa_fe/app/sitemap.ts inpa_fe/components/public-discovery-strip.tsx inpa_fe/components/__tests__/search-policy.test.tsx inpa_fe/components/__tests__/sitemap.test.tsx docs/seo/ai-recommendation-audit.md
git commit -m "feat(검색): 공개 도구 발견 경로와 AI 기준선 추가"
```

### Task 7: PR, 운영 배포, 검색 도구 감사, 문서 마감

- [ ] **Step 1: 최신 master diff와 rollback 지점을 확인한다**

`git fetch origin`, `git log origin/master..HEAD`, `git diff --name-only origin/master...HEAD`를 확인한다. schema migration이 없고 각 커밋이 독립 revert 가능한지 확인한다.

- [ ] **Step 2: PR·CI·병합·운영 배포를 완료한다**

`github:yeet`로 `feat(검색): 공개 실무 도구와 검색·AI 활성화 측정` PR을 만든다. CI 전체 성공 후 병합하고 Vercel/Render가 merge SHA를 배포했는지 확인한다.

- [ ] **Step 3: 실제 운영 흐름을 검증한다**

세 공개 URL 200·metadata·mobile, 보험나이 골든 입력, CSV download, checklist print를 확인한다. synthetic query `?utm_source=chatgpt`로 새 테스트 계정을 만들 수 있는 운영용 계정 정책이 없으므로 운영 DB를 오염시키지 않는다. 대신 Preview/local E2E로 등록 payload와 admin grouping을 검증하고 운영에서는 API schema와 기존 실제 행만 read-only 확인한다.

- [ ] **Step 4: Google·네이버 상태를 감사한다**

기존 등록 화면에서 `/sitemap.xml` 성공, 새 10개 URL 발견 여부, crawl/index 오류를 확인한다. 실제 오류가 있거나 새 sitemap을 아직 가져오지 않은 경우에만 재제출/검사 요청을 한다. 무차별 URL 검사 요청은 하지 않는다.

- [ ] **Step 5: 5분 관찰과 실제 URL smoke test를 완료한다**

Vercel function/build 오류, Sentry 새 오류, Render health, sitemap 10개 URL, private/token/legal 미포함을 60초 이하 간격으로 확인한다.

- [ ] **Step 6: 운영 상태 문서를 갱신한다**

운영 검증 후에만 `README.md`에 PM용 검색 성장 구조·확인 위치를, `AGENTS.md`에 route/content/search-policy/telemetry/acquisition 계약과 배포 SHA를 추가한다. 문서 전용 commit/PR을 병합한다.

- [ ] **Step 7: 최종 보고를 남긴다**

세 릴리스의 PR, merge SHA, CI, Vercel, Render, 10개 공개 URL, sitemap, 검색도구 상태, 30질문 결과, 7일 활성화 화면, Unverified를 네 줄 형식과 함께 보고한다.
