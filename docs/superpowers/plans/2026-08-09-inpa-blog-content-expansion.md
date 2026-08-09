# 인파 블로그 신규 5편과 발행일 재배치 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 블로그 20편의 공개 날짜를 영업일에 재배치하고, 새로운 실무 관점의 예약 글 5편과 고품질 이미지 15개를 안전하게 추가한다.

**Architecture:** Django 공개 블로그 조회 조건을 공통 함수에서 `is_published=true AND published_at<=now`로 제한해 예약 글을 닫는다. 기존 `refresh_blog_content`를 v2로 확장하되 기존 20편은 발행 시각만 수정하고, 신규 5편만 전체 필드를 생성한다. 저장소 원고의 `publication_plan_at`을 일정 SSOT로 사용하고 기존 snapshot·transaction·marker·restore 보호 장치를 유지한다.

**Tech Stack:** Django 5.2 + DRF + SQLite/PostgreSQL, Next.js 16 + React 19 + TypeScript, Markdown + JSON metadata, WebP, Sharp, Vitest, Django TestCase.

## Global Constraints

- Work only in `/Users/kyungsbook/Desktop/inpa/.worktrees/blog-content-expansion` on `codex/blog-content-expansion`.
- Preserve all existing 20 post content fields, admin edits, authors, legal review state, view counts, and upload paths; only the 17 public rows receive new `published_at` values.
- Keep slugs 07, 08, 10 unpublished with `published_at=null` and `review_gate=legal`.
- Public author remains the server-owned `인파 담당자` value and structured-data Organization.
- New five posts publish at the exact KST times in the approved design and are 404 before that time.
- User-facing Korean follows easy-word, positive-framing, honesty, and no em dash rules.
- No external image hotlinks, real customer data, carrier/product logos, generated readable text, or unverifiable performance claims.
- Existing image manifest and blog-release guards remain authoritative.
- Production deployment occurs only through merged `master`; Render applies the versioned release from its existing start command.

---

## File map

- Modify `inpa_be/inpa/boards/views.py`: one public-visibility QuerySet boundary used by list, detail, related, sitemap, and view-count eligibility.
- Modify `inpa_be/inpa/boards/tests.py`: reservation-boundary regressions.
- Modify `inpa_be/inpa/boards/blog_release.py`: v2 item sets, `publication_plan_at`, schedule validation, date-only updates for the existing 20, full creation for the new 5.
- Modify `inpa_be/inpa/boards/test_blog_release.py`: 20-existing/5-new fixtures, schedule validation, preservation, idempotency, snapshot, restore.
- Modify `docs/blog-content/01-*.md` through `20-*.md`: add only `publication_plan_at` metadata.
- Create `docs/blog-content/21-*.md` through `25-*.md`: complete new articles and metadata.
- Modify `docs/blog-content/README.md`: 25-post catalog, public/draft/scheduled states, new restore command.
- Create five directories under `inpa_fe/public/blog-assets/{new-slug}/`: `cover.webp`, one diagram, one product capture per article.
- Modify `inpa_fe/public/blog-assets/manifest.json`: 15 exact asset records.
- Modify `inpa_fe/scripts/check-blog-release.mjs`: require `publication_plan_at`, exactly 25 posts, and exactly 25 covers.
- Modify `inpa_fe/scripts/check-blog-release.test.mjs`: cover 25-post package and invalid publication schedules.
- Modify `README.md` and `AGENTS.md` only after implementation is merged and deployed, per repository policy.

---

### Task 1: 예약 시각 전 공개 차단

**Files:**
- Modify: `inpa_be/inpa/boards/tests.py`
- Modify: `inpa_be/inpa/boards/views.py`

**Interfaces:**
- Produces: `_public_blog_posts(at=None) -> QuerySet[BlogPost]`.
- Consumers: public list, public detail lookup, related posts, sitemap, view-count increment path.

- [ ] **Step 1: Write failing public-boundary tests**

Add tests that create `past`, `future`, and `published_at=None` posts with `is_published=True`. Assert the anonymous list and sitemap contain only `past`; future detail returns 404; future retrieval does not increment `view_count`; admin detail still returns 200; with `mock.patch('inpa.boards.views.timezone.now', return_value=scheduled_at)`, the future row becomes visible exactly at its timestamp.

```python
def test_future_published_post_is_hidden_everywhere_until_schedule(self):
    now = timezone.now()
    future = _make_blog(
        title='예약 글', slug='scheduled-post',
        published_at=now + timedelta(hours=1),
    )
    self.assertNotIn(
        future.slug,
        [row['slug'] for row in self.anon.get('/api/v1/board/blog/').json()['results']],
    )
    self.assertEqual(self.anon.get('/api/v1/board/blog/scheduled-post/').status_code, 404)
    self.assertNotIn(
        future.slug,
        [row['slug'] for row in self.anon.get('/api/v1/board/blog/sitemap/').json()],
    )
```

- [ ] **Step 2: Run the focused tests and verify red**

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards.tests.BlogPublicReadTests
```

Expected: future rows are visible and the new assertions fail.

- [ ] **Step 3: Implement the single public visibility boundary**

In `views.py`, import Django timezone and filter before legal-review validation:

```python
def _public_blog_posts(*, at=None):
    visible_at = at or timezone.now()
    qs = BlogPost.objects.select_related('author').filter(
        is_published=True,
        published_at__isnull=False,
        published_at__lte=visible_at,
    )
    protected = qs.filter(
        Q(legal_review_required=True) | Q(review_gate=BlogPost.REVIEW_GATE_LEGAL)
    )
    stale_ids = [post.pk for post in protected if not post.has_current_legal_review()]
    return qs.exclude(pk__in=stale_ids)
```

Keep admin queries unchanged. Public view-count eligibility is guaranteed because anonymous detail resolves through this QuerySet.

- [ ] **Step 4: Run focused and board suites**

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards.tests.BlogPublicReadTests
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards
```

Expected: all pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add inpa_be/inpa/boards/views.py inpa_be/inpa/boards/tests.py
git commit -m "feat(블로그): 예약 시각 전 공개 차단"
```

---

### Task 2: 블로그 릴리스 v2와 날짜 보존 정책

**Files:**
- Modify: `inpa_be/inpa/boards/blog_release.py`
- Modify: `inpa_be/inpa/boards/test_blog_release.py`

**Interfaces:**
- Extends `BlogReleaseItem.publication_plan_at: datetime`.
- Produces `RELEASE_VERSION='2026-08-blog-expansion-v2'`, 20 exact existing slugs, five exact created slugs.
- `apply_release()` updates existing public posts with `published_at=item.publication_plan_at`, preserves the three protected drafts, and fully creates the five new rows.

- [ ] **Step 1: Upgrade release fixtures and write failing parser tests**

Change the fixture to exact 25 slugs, add `publication_plan_at` to every metadata block, seed all 20 existing posts, and expect five creations. Add failures for missing field, naive datetime, non-KST offset, weekend date, 2026-07-17, duplicate timestamp, non-monotonic order, public `is_published=true` with invalid plan, and protected draft schedule being written to DB.

Use exact ISO values such as:

```python
'publication_plan_at': '2026-07-01T09:20:00+09:00'
```

- [ ] **Step 2: Write failing preservation and apply tests**

Assert:

```python
before = _serialize_public_fields(existing_post)
result = apply_release(items=items, digest=digest, backup_path=backup_path)
existing_post.refresh_from_db()
self.assertEqual(existing_post.title, before['title'])
self.assertEqual(existing_post.body, before['body'])
self.assertEqual(existing_post.author_id, original_author_id)
self.assertEqual(existing_post.view_count, original_view_count)
self.assertEqual(existing_post.published_at, planned_datetime)
self.assertEqual(result, {'created': 5, 'updated': 17})
```

For safety slugs, assert every field including `published_at` and legal-review data remains unchanged. Keep marker retry, digest conflict, atomic failure, before/after snapshot, restore, and reapply-after-restore tests.

- [ ] **Step 3: Run release tests and verify red**

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards.test_blog_release
```

Expected: old exact-20 and metadata assumptions fail.

- [ ] **Step 4: Implement strict v2 schedule parsing and validation**

Add `publication_plan_at` to `_META_FIELDS` and `BlogReleaseItem`. Parse with `parse_datetime`; require an aware `+09:00` value with seconds and no microseconds. Validate:

- exact 25 slugs
- exact planned timestamps from the approved schedule
- no Saturday, Sunday, or 2026-07-17
- one or two items per calendar date
- all timestamps unique
- file-number order 01 through 25 is chronological
- safety slugs remain `is_published=false`, `review_gate=legal`

Keep the exact schedule in one immutable map keyed by slug so validation and apply cannot drift.

- [ ] **Step 5: Implement date-only updates for the existing 20**

Split apply behavior explicitly:

```python
if item.slug in RELEASE_EXISTING_SLUGS:
    if item.slug in SAFETY_SLUGS:
        applied_posts.append(post)
        continue
    post.published_at = item.publication_plan_at
    post.save(update_fields=['published_at', 'updated_at'])
    updated += 1
else:
    values = _release_values(item)
    post = BlogPost(
        slug=item.slug,
        author=admin,
        published_at=item.publication_plan_at,
        **values,
    )
    post.save()
    created += 1
```

Do not call `_release_values()` for an existing row. Require all 20 existing slugs and reject any pre-existing new slug. Update snapshot item counts and created-slug counts to 25 and 5.

- [ ] **Step 6: Run release tests and command dry-run**

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa.boards.test_blog_release
/tmp/inpa-blog-expansion-venv/bin/python manage.py refresh_blog_content
```

Expected: tests pass and dry-run reports v2, 25 targets, 20 existing, 5 new.

- [ ] **Step 7: Commit Task 2**

```bash
git add inpa_be/inpa/boards/blog_release.py inpa_be/inpa/boards/test_blog_release.py
git commit -m "feat(블로그): 25편 발행 일정 릴리스 v2"
```

---

### Task 3: 기존 일정, 신규 원고 5편, 이미지 15개

**Files:**
- Modify: `docs/blog-content/01-*.md` through `20-*.md`
- Create: `docs/blog-content/21-sales-보험설계사-주간-계획표-고객-단계별-다음-행동.md`
- Create: `docs/blog-content/22-sales-보험설계사-소개-카드-고객-확인사항.md`
- Create: `docs/blog-content/23-story-보험설계사-월말-복기-영업-숫자.md`
- Create: `docs/blog-content/24-sales-보험설계사-고객-연간-일정-관리법.md`
- Create: `docs/blog-content/25-story-보험설계사-팀장-일대일-질문.md`
- Modify: `docs/blog-content/README.md`
- Create: `inpa_fe/public/blog-assets/{five-new-slugs}/cover.webp`
- Create: one hashed diagram WebP and one hashed product-capture WebP in each new slug directory.
- Modify: `inpa_fe/public/blog-assets/manifest.json`
- Modify: `inpa_fe/scripts/check-blog-release.mjs`
- Modify: `inpa_fe/scripts/check-blog-release.test.mjs`

**Interfaces:**
- Consumes: exact schedule map and metadata parser from Task 2.
- Produces: complete 25-item repository release package and 61 declared WebP assets.

- [ ] **Step 1: Add only `publication_plan_at` to existing 20 metadata blocks**

Use the exact schedule in the design. Do not alter titles, body, source URLs, tags, images, or legal status.

- [ ] **Step 2: Research and write article 21**

Write the weekly plan article with a five-day routine, a synthetic planner example, a four-column checklist, and links to the existing customer-management and consultation-preparation resources. Avoid guaranteed activity counts.

- [ ] **Step 3: Research and write article 22**

Write the introduction-card article with five factual fields, weak/strong sentence examples, prohibited exaggeration examples phrased as warnings, and a final copy checklist. Link to the public introduction-card feature without implying customer consent from merely opening it.

- [ ] **Step 4: Research and write article 23**

Write the month-end review article around five counts and explicitly distinguish a current funnel snapshot from cohort conversion. Use a fictional month and do not present the numbers as industry benchmarks.

- [ ] **Step 5: Research and write article 24**

Write the annual schedule article with data minimization, neutral calendar labels, birthday/month-day handling, renewal and maturity sources, and a 12-month setup checklist. Do not put illness or family details in example calendar titles.

- [ ] **Step 6: Research and write article 25**

Write the manager 1:1 article with six questions, a fictional team-member conversation, activity/performance sharing boundaries, and a follow-up note template. Avoid fabricated retention claims and coercive language.

- [ ] **Step 7: Generate five editorial still-life covers**

Use the imagegen skill once per distinct scene or in a controlled batch. Prompts must require 16:9 editorial photography, Korean professional context without text, no people, no hands, no logos, natural daylight, believable wear, asymmetrical composition, restrained blue/green accents, and a different material palette per article. Inspect every source image before conversion.

- [ ] **Step 8: Create five diagrams from the approved information structures**

Use repo-native SVG/HTML and existing Inpa tokens, then convert to 1600×900 WebP with Sharp. Use text only in these deterministic diagrams, not generated covers. Add an equivalent HTML table or list in the article body.

- [ ] **Step 9: Capture five actual product screens with synthetic data**

Use the capture account and current product routes. Hide browser chrome, keep 16:9 framing, use no real data, and ensure each screen represents a currently public feature. If a required product surface cannot be safely captured, replace it with a second original diagram and mark `source_type=original-diagram`.

- [ ] **Step 10: Add manifest records and strengthen the asset guard**

For each asset record exact `path`, `role`, `source_type`, `license`, `created_at=2026-08-09`, `used_by`, `pii_reviewed=true`, `rights_reviewed=true`, `width=1600`, `height=900`, `alt`, and `caption`. Covers use `alt=""`; inline images use 20-60 character Korean alt text. Change the guard and its fixture from 20 to 25 posts/covers and require an ISO `publication_plan_at` on every source.

- [ ] **Step 11: Update catalog and run complete content and asset validation**

```bash
cd inpa_fe
node scripts/check-blog-release.mjs
node scripts/check-copy.js
npm run test:blog-lint
```

Expected: exactly 25 posts, 25 covers, 61 declared assets, zero content, asset, or copy findings.

- [ ] **Step 12: Inspect all 15 new images at original detail**

Reject and remake images with fake characters, broken geometry, repeated composition, over-smoothed surfaces, clipped objects, or illegible deterministic text.

- [ ] **Step 13: Commit Task 3**

```bash
git add docs/blog-content inpa_fe/public/blog-assets inpa_fe/scripts/check-blog-release.mjs inpa_fe/scripts/check-blog-release.test.mjs
git commit -m "feat(블로그): 설계사 실무 콘텐츠와 시각 자료 추가"
```

---

### Task 4: 전체 검증, 리뷰, 문서, PR 병합과 운영 확인

**Files:**
- Modify after deploy: `README.md`
- Modify after deploy: `AGENTS.md`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: merged and production-verified release with rollback evidence.

- [ ] **Step 1: Run full backend verification**

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py check
/tmp/inpa-blog-expansion-venv/bin/python manage.py makemigrations --check --dry-run
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa
```

Expected: check clean, no missing migrations, all tests pass.

- [ ] **Step 2: Run full frontend verification**

```bash
cd inpa_fe
npm run lint:copy
npm run lint:blog
npm run test:blog-lint
npm run test:copy-lint
npm run test:run
npx tsc --noEmit --incremental false
NEXT_PUBLIC_API_BASE=http://localhost:8000/api/v1 npm run build
```

Expected: all commands pass, 25 content sources and 61 declared blog assets if 15 new assets are added to the existing 46.

- [ ] **Step 3: Run local release rehearsal**

On a disposable SQLite test DB, establish the v1-equivalent 20 existing rows, apply v2, then query:

- 20 pre-existing rows still exist with unchanged bodies and authors
- 17 historical public dates match the map
- 3 legal drafts remain unpublished with null dates
- 5 new rows have future KST dates
- public API hides all five before their times
- restore removes the new five and restores previous dates

- [ ] **Step 4: Perform adversarial review**

Review correctness, legal/compliance copy, privacy, release rollback, SEO leakage, image rights, mobile readability, and reservation boundaries. Fix all confirmed Critical and Important findings; record rejected findings with evidence.

- [ ] **Step 5: Rebase on latest master and rerun affected gates**

```bash
git fetch origin master
git rebase origin/master
```

Stage only files owned by this feature. Rerun backend boards/release tests and frontend blog/copy guards after conflict resolution.

- [ ] **Step 6: Push and open a ready PR**

```bash
git push -u origin codex/blog-content-expansion
gh pr create --base master --head codex/blog-content-expansion --title "feat(블로그): 신규 5편과 발행 일정 확장" --body-file /tmp/inpa-blog-content-expansion-pr.md
```

Wait for every GitHub Actions and deploy-preview check. Do not merge on a failing or pending required check.

- [ ] **Step 7: Merge and verify production**

Merge the PR, wait for Vercel and Render, then verify:

- `/healthz/` 200
- public API has exactly 17 historical posts on 2026-08-09
- the five future slugs return 404 before their timestamps
- sitemap excludes future and legal-draft slugs
- all existing visible dates match the approved KST schedule
- new cover and inline image URLs return 200 `image/webp`

- [ ] **Step 8: Update the two audience docs after live verification**

Update `README.md` in plain Korean and `AGENTS.md` in dense English with the merged commit, CI run, production release version, 20 historical schedule, five scheduled posts, asset counts, rollback command, and verification results. Commit, push, merge the docs closeout PR, then confirm both deploys remain healthy.

- [ ] **Step 9: Final completion report**

Report exactly:

```text
Changed: [content, images, schedule, visibility]
Verified by: [commands, CI run, production URLs]
Result: [counts and actual responses]
Unverified: [future time-bound posts not yet reached, if any]
```
