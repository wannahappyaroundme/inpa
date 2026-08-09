# 인파 내부 오가닉 콘텐츠 12주 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 25편과 겹치지 않는 보험설계사 실무 글 6편과 이미지 18개를 추가하고, 기존 핵심 글 6편의 인파 내부 전환 흐름을 안전하게 개선한다.

**Architecture:** 기존 Markdown 원고, WebP manifest, Django `refresh_blog_content`, 예약 공개 QuerySet, Vercel 계측을 그대로 확장한다. 신규 글은 v3 릴리스에서 미래 KST 시각으로 생성하고, 기존 개선 글은 v2 after snapshot을 기준으로 3방향 병합해 관리자 수정 필드를 보존한다. 별도 콘텐츠 유사도 모듈이 신규 26~31번을 기존 1~25번과 비교하고 기준을 넘으면 프런트 릴리스 검사를 실패시킨다.

**Tech Stack:** Django 5.2 + DRF + SQLite/PostgreSQL, Next.js 16 + React 19 + TypeScript, Markdown + JSON metadata, Node.js 20, Sharp, Vitest, Django TestCase, WebP, Vercel Analytics.

## Global Constraints

- Work only in `/Users/kyungsbook/Desktop/inpa/.worktrees/blog-content-expansion` on `codex/internal-organic-content`.
- New post slugs 26~31 must be distinct from all existing 25 posts and receive an explicit second comparison against recent posts 21~25.
- Do not recreate the weekly stage plan, introduction card, monthly review, annual calendar, or manager 1:1 angles from posts 21~25.
- Public author remains `인파 담당자` in API, rendered UI, and structured data; do not add a public AI-authorship badge.
- AI may draft copy and visuals, but never invent first-hand experience, customers, interviews, statistics, credentials, or product capabilities.
- No external channel publishing, AI admin studio, new database schema, or new admin page.
- Keep slugs 07, 08, 10 unpublished and preserve all legal-review fields.
- Preserve admin edits with a field-level three-way merge against release `2026-08-blog-expansion-v2`; never overwrite a field that differs from the v2 after snapshot.
- New posts publish only at the exact KST times in the approved design and remain 404 before that time.
- User-facing Korean follows easy-word, positive-framing, honesty, and no em dash rules.
- No real customer data, real policies, carrier/product logos, QR codes, generated readable text, or unverifiable performance claims.
- Every new post has one 1600×900 cover, one original diagram, and one product capture; all 18 assets must be byte-distinct.
- Production deployment requires a fresh explicit PM approval after preview verification.

---

## File map

- Create `inpa_fe/scripts/blog-content-distinctness.mjs`: normalize Korean content, compare title/headings/body shingles, and return blocking duplicate findings.
- Modify `inpa_fe/scripts/check-blog-release.mjs`: load title/body, call the distinctness module, protect all existing 25-post assets, require 31 posts/31 covers/79 total assets, and require one product capture for each new post.
- Modify `inpa_fe/scripts/check-blog-release.test.mjs`: duplicate-copy failures, common-word non-failure, recent-post regression, 31-post counts, and asset uniqueness.
- Modify `inpa_be/inpa/boards/blog_release.py`: v3 exact sets, six future schedules, 25-existing/6-created snapshots, and v2-based field-level merge for six approved existing posts.
- Modify `inpa_be/inpa/boards/test_blog_release.py`: v3 parser, three-way merge, admin-edit preservation, idempotency, rollback, and restore tests.
- Create `docs/blog-content/26-*.md` through `31-*.md`: six complete articles and strict metadata.
- Modify `docs/blog-content/01-*.md`, `03-*.md`, `14-*.md`, `15-*.md`, `16-*.md`, `18-*.md`: only the approved title/intro/body/internal-link/CTA fields.
- Modify `docs/blog-content/README.md`: 31-post catalog, new release version, schedules, and restore command.
- Create six directories under `inpa_fe/public/blog-assets/{new-slug}/`: `cover.webp`, one hashed diagram, and one hashed product capture.
- Modify `inpa_fe/public/blog-assets/manifest.json`: add 18 exact asset records without changing existing records.
- Modify `README.md` and `AGENTS.md` only after implementation is merged and deployed, per repository policy.

---

### Task 1: 콘텐츠 중복 차단 게이트

**Files:**
- Create: `inpa_fe/scripts/blog-content-distinctness.mjs`
- Modify: `inpa_fe/scripts/check-blog-release.mjs`
- Test: `inpa_fe/scripts/check-blog-release.test.mjs`

**Interfaces:**
- Produces: `normalizeContentTokens(value: string) -> string[]`.
- Produces: `contentSimilarity(left: ContentPost, right: ContentPost) -> SimilarityResult`.
- Produces: `verifyContentDistinctness(posts: ContentPost[], targetSlugs: Set<string>) -> string[]`.
- `ContentPost` shape: `{ slug: string, filename: string, title: string, body: string, headings: string[] }`.
- Consumers: `validateBlogRelease()` and the standalone distinctness CLI.

- [ ] **Step 1: Write failing duplicate-content tests**

Add fixtures for a recent post and a new post. Verify an exact renamed copy fails, while two articles sharing only `보험설계사`, `보험`, `고객`, `확인`, `방법`, `정리`, `인파` pass.

```js
test("new post copied from a recent post is blocked", () => {
  const recent = post({
    slug: "보험설계사-주간-계획표-고객-단계별-다음-행동",
    title: "보험설계사 주간 계획표, 고객 단계별로 다음 행동 정하기",
    body: "## 월요일에는 빈칸부터 찾습니다\n\n고객마다 다음 행동과 날짜를 남깁니다.",
  });
  const copied = post({
    slug: "보험설계사-새로운-영업-계획",
    title: "보험설계사 영업 계획표, 고객 단계별 다음 행동 정하기",
    body: "## 월요일에는 빈칸부터 찾습니다\n\n고객마다 다음 행동과 날짜를 남깁니다.",
  });
  const errors = verifyContentDistinctness([recent, copied], new Set([copied.slug]));
  assert.ok(errors.some((error) => error.includes("콘텐츠가 겹칩니다")));
});
```

- [ ] **Step 2: Run the focused test and verify red**

Run:

```bash
cd inpa_fe
node --test scripts/check-blog-release.test.mjs
```

Expected: FAIL because `blog-content-distinctness.mjs` and the exported verifier do not exist.

- [ ] **Step 3: Implement normalization and similarity**

Use whitespace-separated Korean/English/digit tokens after punctuation removal. Remove only the approved common-word set. Compare normalized title tokens, exact normalized H2 headings, and five-token body shingles.

```js
const COMMON_TOKENS = new Set([
  "보험설계사", "보험", "고객", "확인", "방법", "정리", "인파",
]);
const TITLE_THRESHOLD = 0.72;
const BODY_CONTAINMENT_THRESHOLD = 0.18;
const MIN_SHARED_TITLE_TOKENS = 3;
const MIN_SHARED_SHINGLES = 15;

export function verifyContentDistinctness(posts, targetSlugs) {
  const errors = [];
  for (const target of posts.filter((post) => targetSlugs.has(post.slug))) {
    for (const existing of posts) {
      if (existing.slug === target.slug) continue;
      const score = contentSimilarity(target, existing);
      if (
        (score.titleJaccard >= TITLE_THRESHOLD
          && score.sharedTitleTokens >= MIN_SHARED_TITLE_TOKENS)
        || score.sharedHeadings >= 2
        || (score.bodyContainment >= BODY_CONTAINMENT_THRESHOLD
          && score.sharedShingles >= MIN_SHARED_SHINGLES)
      ) {
        errors.push(`${target.slug}: ${existing.slug} 콘텐츠가 겹칩니다`);
      }
    }
  }
  return errors;
}
```

The standalone CLI accepts `--content-root`, loads all `blog-meta` Markdown files, prints every pair and score on failure, and exits nonzero.

- [ ] **Step 4: Integrate the gate into the release checker**

Extend `loadPosts()` to retain `source`, parse the H1 title, split the body after `<!-- blog-body -->`, and collect H2 headings. Add exact target slugs:

```js
const DISTINCTNESS_TARGET_SLUGS = new Set([
  "보험설계사-고객관리-프로그램-선택-기준",
  "보험설계사-보장분석-프로그램-확인-항목",
  "보험설계사-고객-자료-파일-정리",
  "보험설계사-휴면-고객-다시-연락",
  "보험설계사-상담-예약-링크",
  "보장분석-결과-고객-공유",
]);
errors.push(...verifyContentDistinctness(posts, DISTINCTNESS_TARGET_SLUGS));
```

- [ ] **Step 5: Add threshold boundary tests and run green**

Cover exact boundary values, fewer than three shared title tokens, one shared H2, 14 shared shingles, and duplicated long content. Confirm the current 25 posts alone produce zero findings.

```bash
cd inpa_fe
node --test scripts/check-blog-release.test.mjs
node scripts/blog-content-distinctness.mjs --content-root ../docs/blog-content
```

Expected: all tests pass; current 25-post corpus reports zero duplicate findings.

- [ ] **Step 6: Commit Task 1**

```bash
git add inpa_fe/scripts/blog-content-distinctness.mjs inpa_fe/scripts/check-blog-release.mjs inpa_fe/scripts/check-blog-release.test.mjs
git commit -m "test(블로그): 최근 콘텐츠 중복 차단"
```

---

### Task 2: 블로그 릴리스 v3와 관리자 수정 보존

**Files:**
- Modify: `inpa_be/inpa/boards/blog_release.py`
- Test: `inpa_be/inpa/boards/test_blog_release.py`

**Interfaces:**
- Produces: `RELEASE_VERSION = '2026-08-internal-organic-v3'`.
- Produces: `BASE_RELEASE_VERSION = '2026-08-blog-expansion-v2'`.
- Produces: 25 exact existing slugs, six exact created slugs, six exact updated slugs.
- Produces: `_merge_approved_fields(post, item, base_fields) -> tuple[list[str], list[str]]` where the first list is changed fields and the second list is preserved admin-edit fields.
- `apply_release()` returns `{created: int, updated: int, preserved_edits: dict[str, list[str]]}`.

- [ ] **Step 1: Upgrade fixtures and write failing 25-existing/6-new tests**

Add the exact new slugs and schedules:

```python
NEW_PUBLICATION_PLAN = {
    '보험설계사-고객관리-프로그램-선택-기준': '2026-08-25T10:20:00+09:00',
    '보험설계사-보장분석-프로그램-확인-항목': '2026-09-08T09:30:00+09:00',
    '보험설계사-고객-자료-파일-정리': '2026-09-22T10:40:00+09:00',
    '보험설계사-휴면-고객-다시-연락': '2026-10-06T09:50:00+09:00',
    '보험설계사-상담-예약-링크': '2026-10-20T10:10:00+09:00',
    '보장분석-결과-고객-공유': '2026-11-03T09:40:00+09:00',
}
UPDATED_EXISTING_SLUGS = {
    '신입-보험설계사-지인-영업-다음-할-일',
    '보험-증권-보는-법-3분-체크리스트',
    '보험-증권-요청-문자-안내',
    '보험-상담-준비-체크리스트',
    '보험-상담-후-기록-다음-연락',
    '보험설계사-고객관리표-필수-항목',
}
```

Create a valid v2 `BlogContentRelease` marker whose `after_snapshot` contains all 25 current rows. Expect six creations and six updated rows when none have admin edits.

- [ ] **Step 2: Write failing field-level preservation tests**

Change one target row's `title` and another target row's `body` after the v2 marker timestamp. Assert v3 preserves only those fields, applies untouched approved fields, preserves author/view count/published_at/cover/legal fields, and reports the conflicts.

```python
result = apply_release(items=items, digest=digest, backup_path=backup_path)
self.assertEqual(result['created'], 6)
self.assertEqual(result['preserved_edits'][edited.slug], ['body'])
edited.refresh_from_db()
self.assertEqual(edited.body, '운영자가 직접 고친 본문')
self.assertEqual(edited.seo_description, desired.seo_description)
```

- [ ] **Step 3: Run release tests and verify red**

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards.test_blog_release
```

Expected: old exact-25 and five-created assumptions fail; three-way merge helpers do not exist.

- [ ] **Step 4: Implement v3 constants and strict package validation**

Require exactly 31 slugs, 25 existing rows, six new rows, and the exact six future schedules. Existing 25 retain their original `publication_plan_at` metadata; v3 never rewrites their `published_at`.

Validate the six new dates are KST-aware, unique, Tuesdays, ordered by file number, and outside the official 2026 holiday ranges in the design. Keep 07, 08, 10 unpublished with `review_gate=legal`.

- [ ] **Step 5: Implement v2 after-snapshot loading and three-way merge**

Read `BlogContentRelease(version=BASE_RELEASE_VERSION)` under the same transaction. Validate its digest, non-reverted state, exact 25 rows, and snapshot digest before using it as the base.

```python
APPROVED_UPDATE_FIELDS = (
    'title', 'body', 'excerpt', 'tags', 'seo_title', 'seo_description',
)

def _merge_approved_fields(post, item, base_fields):
    desired = _release_values(item)
    changed = []
    preserved = []
    for field in APPROVED_UPDATE_FIELDS:
        current = getattr(post, field)
        if current == desired[field]:
            continue
        if current != base_fields[field]:
            preserved.append(field)
            continue
        setattr(post, field, desired[field])
        changed.append(field)
    if changed:
        post.save(update_fields=[*changed, 'updated_at'])
    return changed, preserved
```

Call this helper only for `RELEASE_UPDATED_SLUGS`. Do not call `_release_values()` for the other 19 existing rows. New six rows use `_release_values()` and the exact future `published_at`.

- [ ] **Step 6: Upgrade snapshots, restore, idempotency, and rollback**

The before snapshot contains all 25 existing rows. The after snapshot contains all 31 rows and six `created_slugs`. Restore writes the exact 25 before rows and changes the six created rows to `is_published=false`. Keep same-digest retry a no-op, different-digest retry an error, updated-at race protection, staged after-snapshot recovery, and transaction rollback.

- [ ] **Step 7: Run focused tests and command dry-run**

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards.test_blog_release
/tmp/inpa-blog-expansion-venv/bin/python manage.py refresh_blog_content
```

Expected: tests pass; dry-run reports v3, 31 targets, 25 existing, six new, and six approved update targets.

- [ ] **Step 8: Commit Task 2**

```bash
git add inpa_be/inpa/boards/blog_release.py inpa_be/inpa/boards/test_blog_release.py
git commit -m "feat(블로그): 31편 콘텐츠 릴리스 v3"
```

---

### Task 3: 신규 6편과 기존 6편 원고

**Files:**
- Create: `docs/blog-content/26-sales-보험설계사-고객관리-프로그램-선택-기준.md`
- Create: `docs/blog-content/27-coverage-보험설계사-보장분석-프로그램-확인-항목.md`
- Create: `docs/blog-content/28-sales-보험설계사-고객-자료-파일-정리.md`
- Create: `docs/blog-content/29-sales-보험설계사-휴면-고객-다시-연락.md`
- Create: `docs/blog-content/30-sales-보험설계사-상담-예약-링크.md`
- Create: `docs/blog-content/31-coverage-보장분석-결과-고객-공유.md`
- Modify: `docs/blog-content/01-sales-신입-보험설계사-지인-영업-다음-할-일.md`
- Modify: `docs/blog-content/03-coverage-보험-증권-보는-법-3분-체크리스트.md`
- Modify: `docs/blog-content/14-sales-보험-증권-요청-문자-안내.md`
- Modify: `docs/blog-content/15-sales-보험-상담-준비-체크리스트.md`
- Modify: `docs/blog-content/16-sales-보험-상담-후-기록-다음-연락.md`
- Modify: `docs/blog-content/18-sales-보험설계사-고객관리표-필수-항목.md`
- Modify: `docs/blog-content/README.md`

**Interfaces:**
- Consumes: v3 exact slug/schedule contract from Task 2.
- Consumes: distinctness CLI from Task 1.
- Produces: 31 strict `blog-meta` Markdown sources with six new articles and six approved existing improvements.

- [ ] **Step 1: Freeze and compare the current 25-post inventory**

Run the standalone checker before writing and save the console output in the task notes. Build a review table with each current post's title, primary question, reader result, H2 headings, and image roles. Explicitly mark 21~25 as recent protected angles.

```bash
cd inpa_fe
node scripts/blog-content-distinctness.mjs --content-root ../docs/blog-content
```

Expected: 25 posts, zero duplicate findings.

- [ ] **Step 2: Verify primary sources before drafting**

Open and verify the following direct sources on 2026-08-10; do not rely on search-result snippets.

- 개인정보 보호법 제16조: `https://www.law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1029335669`
- 개인정보 처리방침 작성지침: `https://www.pipc.go.kr/np/cop/bbs/selectBoardArticle.do?bbsId=BS217&mCode=G010030000&nttId=12018`
- 인파 고객관리 솔루션: `https://www.inpa.kr/solutions/customer-management`
- 인파 보장분석 솔루션: `https://www.inpa.kr/solutions/policy-analysis`
- 인파 영업관리 솔루션: `https://www.inpa.kr/solutions/sales-management`
- 인파 첫 상담 가이드: `https://www.inpa.kr/guides/first-consultation`
- 인파 후속 연락 가이드: `https://www.inpa.kr/guides/customer-follow-up`
- 인파 고객관리표: `https://www.inpa.kr/resources/customer-management-sheet`
- 인파 상담 체크리스트: `https://www.inpa.kr/resources/consultation-checklist`

Record only claims directly supported by these sources and each article's `checked_at=2026-08-10`.

- [ ] **Step 3: Draft articles 26~28 with exact outcomes**

Use direct-answer openings and distinct structures:

- 26: seven selection criteria, a two-column `질문/확인할 화면` table, a short self-check, one link to customer-management solution.
- 27: six post-automation checks, a `원문/자동 정리/설계사 재확인` table, no recommendation language, one link to policy-analysis solution.
- 28: filename formula `고객표시이름_자료종류_상담일`, folder depth no more than three, no sensitive data in filenames, deletion-date check, one link to customer-management sheet.

Each body must be 1,800~2,800 Korean characters before Markdown link destinations, include 4~6 H2 headings, one useful table, and one emphasized final action.

- [ ] **Step 4: Run distinctness and rewrite until clean**

```bash
cd inpa_fe
node scripts/blog-content-distinctness.mjs --content-root ../docs/blog-content
```

Expected: 28 posts and zero findings. If a pair fails, rewrite the article angle or structure; do not weaken thresholds or add a pair-specific allowlist.

- [ ] **Step 5: Draft articles 29~31 with exact outcomes**

- 29: verify prior stop request and allowed contact route, split 진행중·보류·휴면·종료, provide three non-pressuring first sentences, and link to follow-up guide.
- 30: explain work hours, buffer, unavailable blocks, customer request, planner accept/decline, and confirmed appointment; distinguish this from post 17's reminder messages.
- 31: explain held amount, configured baseline, 부족·적정·넉넉 only when a baseline exists, questions to leave, and one customer share action; do not recommend products or contract changes.

Keep 30 separate from post 24's annual recurring dates and keep 31 separate from legal-review posts 07, 08, 10.

- [ ] **Step 6: Improve the six approved existing posts**

Preserve each slug, source boundary, existing images, and publication time. Make only these changes:

- 01: direct-answer opening with three post-acquaintance routes and one sales-management link.
- 03: separate original-policy checks from software-assisted rechecks and link policy-analysis solution.
- 14: place minimum-request guidance before message examples and link first-consultation guide.
- 15: connect the checklist to the public downloadable checklist without changing its insurance facts.
- 16: add one-line `담당자/행동/날짜` examples and link follow-up guide.
- 18: state why each field exists and which information should remain blank, then link customer-management sheet.

- [ ] **Step 7: Run content gates and update the catalog**

Update `docs/blog-content/README.md` to 31 posts, list six schedules, mark 07/08/10 as legal-review drafts, and document v3 restore name.

```bash
cd inpa_fe
node scripts/blog-content-distinctness.mjs --content-root ../docs/blog-content
rg -n "—|오늘은.*알아보|실제 고객|성공 보장|무조건" ../docs/blog-content
```

Expected: 31 posts, zero duplicate findings, zero prohibited public-copy findings after manual review of any context matches.

- [ ] **Step 8: Commit Task 3**

```bash
git add docs/blog-content/01-*.md docs/blog-content/03-*.md docs/blog-content/14-*.md docs/blog-content/15-*.md docs/blog-content/16-*.md docs/blog-content/18-*.md docs/blog-content/26-*.md docs/blog-content/27-*.md docs/blog-content/28-*.md docs/blog-content/29-*.md docs/blog-content/30-*.md docs/blog-content/31-*.md docs/blog-content/README.md
git commit -m "feat(블로그): 내부 오가닉 콘텐츠 6편 추가"
```

---

### Task 4: 고품질 이미지 18개와 자산 보호

**Files:**
- Create: `inpa_fe/public/blog-assets/보험설계사-고객관리-프로그램-선택-기준/*`
- Create: `inpa_fe/public/blog-assets/보험설계사-보장분석-프로그램-확인-항목/*`
- Create: `inpa_fe/public/blog-assets/보험설계사-고객-자료-파일-정리/*`
- Create: `inpa_fe/public/blog-assets/보험설계사-휴면-고객-다시-연락/*`
- Create: `inpa_fe/public/blog-assets/보험설계사-상담-예약-링크/*`
- Create: `inpa_fe/public/blog-assets/보장분석-결과-고객-공유/*`
- Modify: `inpa_fe/public/blog-assets/manifest.json`
- Modify: `inpa_fe/scripts/check-blog-release.mjs`
- Test: `inpa_fe/scripts/check-blog-release.test.mjs`

**Interfaces:**
- Consumes: exact six slugs and inline image paths from Task 3.
- Produces: six 1600×900 covers, six 1600×900 diagrams, six product captures, 18 manifest entries, and exact 31-cover/79-asset guards.

- [ ] **Step 1: Add failing 31-post and 79-asset assertions**

Update fixtures to require exactly 31 Markdown sources, 31 cover records, and 79 manifest records. Require exactly one `original-diagram` and one `product-capture` per new slug. Add a test that copies any new inline asset bytes to another path and expects a duplicate-asset failure.

- [ ] **Step 2: Run the blog lint tests and verify red**

```bash
cd inpa_fe
npm run test:blog-lint
```

Expected: FAIL on old 25/61 counts and missing new assets.

- [ ] **Step 3: Generate six natural editorial covers**

Invoke the `imagegen` skill before generating. Make one generation call per cover so lighting and composition do not converge. Every prompt includes `documentary editorial photography, natural Korean office daylight, subtle real wear, no people, no hands, no logos, no readable text, no screen UI, 16:9` plus the article-specific scene:

1. mixed blank index cards and weekly notebook for customer-management software choice
2. blank policy-like sleeves and a tablet with its screen turned away for analysis software checks
3. unnamed document folders with date tabs for customer-file organization
4. an older closed notebook beside one fresh contact card for dormant-customer follow-up
5. separate blank time cards and a small desk clock for booking-link setup
6. two devices facing different directions with a blank explanation card between them for result sharing

Inspect every candidate with `view_image`. Reject repeated desk grain, identical lighting, warped paper, impossible shadows, text-like marks, or an obviously synthetic glossy look. Resize and encode the selected images to 1600×900 WebP under 200KB; strip EXIF, XMP, and ICC metadata.

- [ ] **Step 4: Render six deterministic information diagrams**

Use temporary SVG/HTML sources outside committed asset directories, render Korean text with the existing project font, and encode to 1600×900 WebP under 180KB. The diagrams are:

- selection criteria 7-grid
- original/automatic/recheck six-step flow
- filename/folder/deletion-date flow
- four customer states and recontact decision
- work-hours/request/accept/confirm flow
- five-step customer explanation sequence

The same information must exist as HTML text or a table in each article. Filename format is `{role}-{sha256[:8]}.webp`.

- [ ] **Step 5: Capture six real Inpa screens with synthetic data**

Use the existing `seed_capture` account and routes; never use production or real customer data.

- 26: customer list with status and next-contact cues
- 27: analysis or multiple-policy comparison screen
- 28: customer detail with policy list
- 29: customer list showing active/hold/dormant/closed states
- 30: public booking request screen
- 31: public customer share screen

Crop to 1600×900, verify no readable phone numbers, QR codes, real carrier names, or hidden browser tokens, and encode each under 180KB with a content-hash filename.

- [ ] **Step 6: Extend manifest and immutable-asset guards**

Add exactly 18 records with `created_at=2026-08-10`, accurate role/source type, `pii_reviewed=true`, `rights_reviewed=true`, exact dimensions, used_by, alt, and caption. Add SHA-256 locks for all current 25-post assets so the recent 21~25 images cannot be silently changed. Check byte duplicates for every new asset and perceptual duplicates for all covers.

- [ ] **Step 7: Run asset gates and inspect a safe contact sheet**

```bash
cd inpa_fe
npm run test:blog-lint
npm run lint:blog
```

Expected: 31 posts, 31 covers, 79 assets, zero duplicate content or image findings.

If a contact sheet is useful, write it only to a new `mktemp -d` output path. Validate that the output path is not equal to any source path before running the tool. Never pass a committed asset path as the contact-sheet output; this prevents the prior `montage` overwrite failure.

- [ ] **Step 8: Commit Task 4**

```bash
git add inpa_fe/public/blog-assets inpa_fe/scripts/check-blog-release.mjs inpa_fe/scripts/check-blog-release.test.mjs
git commit -m "feat(블로그): 신규 6편 이미지 자산 추가"
```

---

### Task 5: 릴리스 패키지 통합 검증

**Files:**
- Modify only if a verified failure requires a scoped fix: files already listed in Tasks 1~4.

**Interfaces:**
- Consumes: 31-post v3 release, 79-asset manifest, distinctness gate, and existing public visibility boundary.
- Produces: one fully verified local release candidate.

- [ ] **Step 1: Run backend focused tests**

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py check
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards.test_blog_release
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards.tests.BlogPublicReadTests
```

Expected: all pass; future posts remain excluded before the exact schedule.

- [ ] **Step 2: Run frontend content and unit gates**

```bash
cd inpa_fe
npm run test:blog-lint
npm run lint:blog
npm run test:copy-lint
npm run lint:copy
npm run test:run
```

Expected: all tests and lints pass with zero findings.

- [ ] **Step 3: Run full backend and production build gates**

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa
cd ../inpa_fe
npm run build
```

Expected: Django full suite passes and Next build completes with the public blog routes.

- [ ] **Step 4: Verify release dry-run and v2-to-v3 apply in an isolated test database**

Use the integration fixture to apply v2, make two simulated admin edits, apply v3, and verify: six new rows, unchanged future visibility, two preserved fields, no changed author/view count/published_at, a valid before/after snapshot, same-digest no-op, and successful restore.

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards.test_blog_release.BlogReleaseDatabaseTests
/tmp/inpa-blog-expansion-venv/bin/python manage.py refresh_blog_content
```

Expected: focused integration tests pass; dry-run prints the exact v3 package without mutating the database.

- [ ] **Step 5: Commit only verified scoped fixes**

If verification found a real defect, add only its test and fix, rerun the failed gate, then commit with `fix(블로그): ...`. If no defect exists, do not create an empty commit.

---

### Task 6: 실제 화면·문체·보험 표현 검수

**Files:**
- Modify only confirmed findings in the content/assets/release files from Tasks 1~4.

**Interfaces:**
- Consumes: verified local release candidate.
- Produces: desktop/mobile visual evidence and a zero-important-finding review record.

- [ ] **Step 1: Apply v3 to local synthetic data and expose future posts only locally**

The current worktree SQLite database contains the active v2 marker and 25 synthetic blog rows. Back it up to an explicit `/tmp` path, record the digest, apply v3, then temporarily set only the six new dates to the past.

```bash
cp inpa_be/db.sqlite3 /tmp/inpa-internal-organic-qa-db.sqlite3
shasum -a 256 /tmp/inpa-internal-organic-qa-db.sqlite3
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py shell -c "from inpa.boards.models import BlogContentRelease, BlogPost; assert BlogContentRelease.objects.filter(version='2026-08-blog-expansion-v2', reverted_at__isnull=True).exists(); assert BlogPost.objects.count() >= 25"
/tmp/inpa-blog-expansion-venv/bin/python manage.py refresh_blog_content --apply --backup-out /tmp/inpa-internal-organic-v3-before.json
/tmp/inpa-blog-expansion-venv/bin/python manage.py shell -c "from datetime import timedelta; from django.utils import timezone; from inpa.boards.blog_release import RELEASE_CREATED_SLUGS; from inpa.boards.models import BlogPost; updated=BlogPost.objects.filter(slug__in=RELEASE_CREATED_SLUGS).update(published_at=timezone.now()-timedelta(minutes=1)); assert updated == 6"
```

Never make this mutation in production and never commit `db.sqlite3`.

- [ ] **Step 2: Run backend and frontend servers**

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py runserver 127.0.0.1:8000
```

```bash
cd inpa_fe
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api/v1 npm run dev
```

Expected: API and blog load without console or server errors.

- [ ] **Step 3: Inspect all 12 changed articles at desktop and mobile widths**

Check `/blog`, six new details, and six improved details at 1440×900 and 390×844. Verify Korean line breaks, title wrapping, table horizontal behavior, one primary CTA, related links, image loading, alt behavior, no duplicated cover inside body, no loading/error dead end, and consistent light theme.

- [ ] **Step 4: Run a five-lens adversarial review**

Review each new article for:

1. factual/source accuracy
2. insurance recommendation or contract-change implication
3. privacy and synthetic-data safety
4. overlap with all 25 existing posts, especially 21~25
5. human editorial quality and mobile readability

Record every finding with accept/reject reasoning. Fix all Critical and Important findings, then rerun the relevant focused gate.

- [ ] **Step 5: Verify future visibility again after QA**

Stop both development servers, replace only the worktree SQLite database with the exact backup, and confirm its digest matches the recorded backup.

```bash
cp /tmp/inpa-internal-organic-qa-db.sqlite3 inpa_be/db.sqlite3
shasum -a 256 inpa_be/db.sqlite3 /tmp/inpa-internal-organic-qa-db.sqlite3
```

Then use the Django reservation tests with mocked time to confirm each new URL returns 404 before its schedule, appears exactly at its schedule, and is absent from sitemap before that instant.

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards.tests.BlogPublicReadTests
```

- [ ] **Step 6: Final verification before release handoff**

Invoke `superpowers:verification-before-completion`. Rerun `git diff --check`, focused backend tests, blog lint, copy lint, Next build, and `git status`. Do not report completion from earlier outputs.

---

### Task 7: Preview, approval, merge, production verification, and docs closeout

**Files:**
- Modify after production success: `README.md`
- Modify after production success: `AGENTS.md`

**Interfaces:**
- Consumes: zero-important-finding release candidate.
- Produces: merged production release and PM/dev documentation.

- [ ] **Step 1: Review branch scope before publishing**

```bash
git fetch origin
git status --short --branch
git log --oneline origin/master..HEAD
git diff --stat origin/master...HEAD
```

Expected: only the approved content, assets, release guards, tests, design, and plan are present.

- [ ] **Step 2: Push the branch and open a draft PR**

Push `codex/internal-organic-content`, open a draft PR against `master`, and include exact test results, six schedules, three-way merge behavior, rollback command, and preview checklist. Wait for GitHub Actions and Vercel preview.

- [ ] **Step 3: Verify preview and request production approval**

Check the preview blog list and all 12 changed articles. Because future posts remain hidden on a normal public preview, use the approved local QA evidence or an admin preview path, not a production date change. Present screenshots and the CI summary to the PM.

Stop here and request explicit production approval. Do not merge merely because CI and preview pass.

- [ ] **Step 4: Merge only after explicit PM approval**

Before merge, fetch again and confirm `origin/master` has not introduced overlapping blog changes. Resolve by preserving upstream changes, rerun affected tests, mark the PR ready, and merge normally. Do not force-push another contributor's branch.

- [ ] **Step 5: Verify production**

Confirm:

- `https://www.inpa.kr/blog` returns 200
- six future slugs return 404 before schedule
- six improved articles render their approved new content
- sitemap excludes future slugs
- `https://inpa-be.onrender.com/healthz/` returns the expected JSON
- Render applied `2026-08-internal-organic-v3`
- Vercel and Render show no new errors for five minutes

- [ ] **Step 6: Update PM and agent docs after deployment**

Update `README.md` in Korean with the six topics, schedules, content-only scope, author, verification, and rollback. Update `AGENTS.md` in dense English with release version, exact counts, distinctness gate, three-way merge rule, schedules, and production evidence. Commit as:

```bash
git add README.md AGENTS.md
git commit -m "docs(블로그): 내부 오가닉 콘텐츠 배포 기록"
```

Publish the closeout docs through the normal PR flow and verify the merged files on `master`.
