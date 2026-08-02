# Inpa Blog Content Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 블로그 13편을 정확하고 읽기 쉬운 실무 글로 교정하고 신규 7편, 고유 커버 20개, 본문 시각 자료, `인파 담당자` 바이라인, 관련 글과 운영 안전장치를 구현해 운영에 배포한다.

**Architecture:** Django의 기존 `BlogPost`에 공개 정적 커버 경로와 release marker만 additive로 추가하고, 공개 API는 정적 커버를 우선하며 같은 카테고리 관련 글 3개를 제공한다. 원고는 `docs/blog-content`의 JSON 메타 블록이 있는 Markdown release package로 관리하고 수동 전용 `refresh_blog_content` 명령이 검증·백업·transaction·버전 마커를 담당한다. Next.js는 repo-owned `/blog-assets/`와 manifest를 사용해 이미지 크기·캡션·대체 설명을 고정하며, 20편 프리뷰 검수 후 저위험 17편만 공개하고 법무 검토 전 안심 가이드 3편은 비공개로 둔다.

**Tech Stack:** Django 5.2 LTS, DRF, PostgreSQL/SQLite, Next.js 16.2.9 App Router, React 19.2, TypeScript, Tailwind v4, react-markdown, remark-gfm, Next Image, Vitest, Pillow, Vercel Analytics, Cloudflare R2 legacy cover fallback.

## Global Constraints

- Start from `origin/master` in an isolated `codex/blog-content-enrichment` worktree; do not include the dirty shared tree or its ahead commit.
- Preserve existing Korean slugs and original `published_at` for 13 posts.
- Public author is always `인파 담당자`; internal `BlogPost.author` and admin email remain audit data.
- `BlogPosting.author` references Inpa `Organization`, never a fabricated `Person`.
- Produce 20 preview-complete posts; publish 17 low-risk posts, and keep slugs 07, 08, 10 unpublished until a real lawyer review record exists.
- Every post has a unique 1600×900 WebP cover. Inline visuals average 1–2 and exist only when they improve understanding.
- Generated imagery may show objects and spaces only. No generated people, faces, hands, legible text, insurer logos, policy documents, or fake Korean.
- Product captures use synthetic capture data only. No PII, notifications, QR codes, real policy files, carrier names, or closed features.
- No external image hotlinks. Blog bodies may reference only `/blog-assets/` paths present in the manifest.
- No unsupported claims, recommendation/verdict language, hardcoded model ids, secrets, em dash, negative user-facing copy, or unavailable feature claims.
- All insurance/legal facts use official primary sources and a recorded `checked_at` date.
- Production deployment was explicitly requested on 2026-08-03; still run the exact commit/data/publication preflight before the irreversible merge and database apply.
- Update `README.md` and `AGENTS.md` only after the feature is merged, deployed, and production-verified.

---

## File Map

### Backend contracts

- Modify `inpa_be/inpa/boards/models.py`: `cover_asset_path`, `BlogContentRelease`.
- Create `inpa_be/inpa/boards/migrations/0004_blogpost_cover_asset_path_blogcontentrelease.py`: additive schema.
- Modify `inpa_be/inpa/boards/serializers.py`: fixed public author, static-cover preference, related item serializer.
- Modify `inpa_be/inpa/boards/views.py`: deterministic related-post selection.
- Modify `inpa_be/inpa/boards/admin.py`: expose static cover and release markers to admins.
- Modify `inpa_be/inpa/boards/tests.py`: public contract regressions.

### Release package and command

- Create `inpa_be/inpa/boards/blog_release.py`: parse and validate Markdown metadata, manifest, copy, image, count, review gates.
- Create `inpa_be/inpa/boards/management/commands/refresh_blog_content.py`: dry-run, backup, atomic apply, release marker.
- Create `inpa_be/inpa/boards/test_blog_release.py`: parser, validation, idempotency, rollback, admin-edit preservation.
- Modify `docs/blog-content/01-*.md` through `13-*.md`: corrected release sources.
- Create `docs/blog-content/14-*.md` through `20-*.md`: new release sources.
- Modify `docs/blog-content/README.md` and `docs/blog-content/00-brand-voice-guide.md`: 20-post catalog and current image/byline rules.

### Frontend presentation

- Create `inpa_fe/lib/blog-assets.ts`: typed manifest lookup and absolute public URL normalization.
- Create `inpa_fe/components/blog-image.tsx`: static optimized cover/content image and legacy fallback.
- Create `inpa_fe/components/blog-analytics.tsx`: page-view and CTA events with allowlisted UTM fields.
- Create `inpa_fe/components/__tests__/blog-public.test.tsx`: image, author, readability, related-card, analytics tests.
- Modify `inpa_fe/components/blog-markdown.tsx`: figure/caption renderer and improved reading rhythm.
- Modify `inpa_fe/components/structured-data.tsx`: organization author and absolute image URL.
- Modify `inpa_fe/app/blog/page.tsx`: unique covers, date-first cards, responsive image sizing.
- Modify `inpa_fe/app/blog/[slug]/page.tsx`: answer-first layout, byline, modified date, related posts, tracked CTA.
- Modify `inpa_fe/lib/api.ts`: relative/legacy cover contract and `related_posts`.
- Modify `inpa_fe/lib/adminApi.ts`: `cover_asset_path` readback.

### Visual assets

- Create `inpa_fe/public/blog-assets/manifest.json`: rights, PII, dimensions, alt, caption, usage.
- Create one directory under `inpa_fe/public/blog-assets/` for each of the exact 20 slugs listed in the approved design, containing that post's `cover.webp` and declared inline WebP assets.
- Create `inpa_fe/scripts/check-blog-release.mjs`: manifest/file/size/path/duplicate-cover/copy checks used locally and in CI.
- Modify `inpa_fe/package.json`: `lint:blog` script.
- Modify `.github/workflows/ci.yml`: run `npm run lint:blog` after copy lint.

### Post-deploy documentation

- Modify `README.md`: Korean PM-facing release summary and operating rule.
- Modify `AGENTS.md`: current-state changelog, blog architecture, command, publication gate.

---

### Task 0: Create isolated execution worktree and capture baselines

**Files:**
- No product files changed.

**Interfaces:**
- Consumes: `origin/master`, approved design spec and this plan from the shared tree.
- Produces: `/tmp/inpa-blog-content-enrichment`, branch `codex/blog-content-enrichment`, baseline logs.

- [ ] **Step 1: Verify the shared tree will not be used for implementation**

Run:

```bash
git status --short --branch
git log --oneline -10
git rev-parse --show-toplevel
```

Expected: the shared tree shows unrelated modified/untracked files and remains untouched.

- [ ] **Step 2: Refresh remote refs and create the isolated branch/worktree**

Run after invoking `superpowers:using-git-worktrees`:

```bash
git fetch origin
git worktree add -b codex/blog-content-enrichment /tmp/inpa-blog-content-enrichment origin/master
```

Expected: a clean worktree on `codex/blog-content-enrichment` based only on `origin/master`.

- [ ] **Step 3: Recreate the approved spec and plan in the isolated worktree**

Use `apply_patch` to add:

```text
docs/superpowers/specs/2026-08-03-inpa-blog-content-enrichment-design.md
docs/superpowers/plans/2026-08-03-inpa-blog-content-enrichment.md
```

Expected: byte-for-byte content equality with the approved documents in the shared tree.

- [ ] **Step 4: Capture current gates before edits**

Run:

```bash
cd inpa_be && python manage.py check
cd ../inpa_fe && npm run lint:copy
cd .. && git status --short --branch
```

Expected: backend check and copy lint pass; git status contains only the two approved docs.

- [ ] **Step 5: Commit the planning artifacts**

```bash
git add docs/superpowers/specs/2026-08-03-inpa-blog-content-enrichment-design.md docs/superpowers/plans/2026-08-03-inpa-blog-content-enrichment.md
git commit -m "docs(블로그): 콘텐츠 품질 보강 설계와 구현 계획"
```

Expected: one docs-only commit.

---

### Task 1: Add stable public author, static cover, and related-post API contracts

**Files:**
- Modify: `inpa_be/inpa/boards/models.py`
- Create: `inpa_be/inpa/boards/migrations/0004_blogpost_cover_asset_path_blogcontentrelease.py`
- Modify: `inpa_be/inpa/boards/serializers.py`
- Modify: `inpa_be/inpa/boards/views.py`
- Modify: `inpa_be/inpa/boards/admin.py`
- Test: `inpa_be/inpa/boards/tests.py`

**Interfaces:**
- Consumes: existing `BlogPost`, `BlogPostListSerializer`, `BlogPostDetailSerializer`.
- Produces: `BLOG_PUBLIC_AUTHOR`, `BlogPost.cover_asset_path`, `BlogContentRelease`, `BlogRelatedSerializer`, `related_posts`.

- [ ] **Step 1: Write failing API contract tests**

Add these behaviors to `BlogPublicReadTests`:

```python
def test_public_author_is_inpa_manager_not_login_email(self):
    author, _ = _make_planner('private-editor@example.com')
    _make_blog(title='작성자 글', author=author)
    row = self.anon.get('/api/v1/board/blog/').json()['results'][0]
    self.assertEqual(row['author_name'], '인파 담당자')
    self.assertNotIn('private-editor', str(row))

def test_static_cover_path_precedes_legacy_upload(self):
    _make_blog(title='정적 커버', cover_asset_path='/blog-assets/정적-커버/cover.webp')
    row = self.anon.get('/api/v1/board/blog/').json()['results'][0]
    self.assertEqual(row['cover_image'], '/blog-assets/정적-커버/cover.webp')

def test_related_posts_prefer_same_category_and_exclude_drafts_and_self(self):
    current = _make_blog(title='현재', slug='current', category='coverage')
    same = _make_blog(title='같은 분류', slug='same', category='coverage')
    other = _make_blog(title='다른 분류', slug='other', category='sales')
    _make_blog(title='초안', slug='draft-related', category='coverage', is_published=False)
    data = self.anon.get('/api/v1/board/blog/current/').json()
    self.assertEqual(data['related_posts'][0]['id'], same.id)
    self.assertNotIn(current.id, [row['id'] for row in data['related_posts']])
    self.assertNotIn('draft-related', [row['slug'] for row in data['related_posts']])
    self.assertIn(other.id, [row['id'] for row in data['related_posts']])
```

- [ ] **Step 2: Run the targeted tests and confirm RED**

Run:

```bash
cd inpa_be
python manage.py test inpa.boards.tests.BlogPublicReadTests
```

Expected: failures for missing field/constant and missing `related_posts`.

- [ ] **Step 3: Add the additive model contract**

Add to `BlogPost`:

```python
cover_asset_path = models.CharField(
    '공개 정적 커버 경로', max_length=300, blank=True, default='',
)
```

Add after `BlogPost`:

```python
class BlogContentRelease(models.Model):
    version = models.CharField(max_length=80, unique=True)
    digest = models.CharField(max_length=64)
    item_count = models.PositiveSmallIntegerField()
    applied_at = models.DateTimeField(auto_now_add=True)
    reverted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'board_blog_content_release'
        ordering = ['-applied_at']
```

Generate migration `0004_blogpost_cover_asset_path_blogcontentrelease.py` and register the static cover field and release marker model in Django admin.

- [ ] **Step 4: Implement the public serialization boundary**

In `serializers.py` define:

```python
BLOG_PUBLIC_AUTHOR = '인파 담당자'

def _blog_cover_url(obj, request):
    if obj.cover_asset_path:
        return obj.cover_asset_path
    if not obj.cover_image:
        return None
    url = obj.cover_image.url
    return request.build_absolute_uri(url) if request else url
```

Declare `cover_image = serializers.SerializerMethodField()` and return the helper in public list/detail serializers. Return `BLOG_PUBLIC_AUTHOR` from the three blog `get_author_name` methods. Keep `author_email` internal in the admin serializer.

Add `BlogRelatedSerializer` with only `id`, `title`, `slug`, `excerpt`, `cover_image`, `category`, `category_label`, and `published_at`.

- [ ] **Step 5: Implement deterministic related-post selection**

In `BlogPostViewSet.retrieve`, compute at most three rows:

```python
published = BlogPost.objects.filter(is_published=True).exclude(pk=post.pk)
same_category = list(published.filter(category=post.category)[:3])
missing = 3 - len(same_category)
others = list(published.exclude(category=post.category)[:missing]) if missing else []
data = BlogPostDetailSerializer(post, context={'request': request}).data
data['related_posts'] = BlogRelatedSerializer(
    same_category + others, many=True, context={'request': request}
).data
return Response(data)
```

Use model ordering for stable newest-first selection and never return drafts to public readers.

- [ ] **Step 6: Run tests and schema checks GREEN**

```bash
cd inpa_be
python manage.py test inpa.boards.tests.BlogPublicReadTests inpa.boards.tests.BlogAdminCrudTests
python manage.py makemigrations --check
python manage.py check
```

Expected: all pass and no uncreated migration.

- [ ] **Step 7: Commit Task 1**

```bash
git add inpa_be/inpa/boards/models.py inpa_be/inpa/boards/migrations/0004_blogpost_cover_asset_path_blogcontentrelease.py inpa_be/inpa/boards/serializers.py inpa_be/inpa/boards/views.py inpa_be/inpa/boards/admin.py inpa_be/inpa/boards/tests.py
git commit -m "feat(블로그): 공개 저자와 관련 글 계약 정리"
```

---

### Task 2: Build the owned image manifest and accessible renderers

**Files:**
- Create: `inpa_fe/public/blog-assets/manifest.json`
- Create: `inpa_fe/lib/blog-assets.ts`
- Create: `inpa_fe/components/blog-image.tsx`
- Modify: `inpa_fe/components/blog-markdown.tsx`
- Modify: `inpa_fe/components/structured-data.tsx`
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/lib/adminApi.ts`
- Test: `inpa_fe/components/__tests__/blog-public.test.tsx`

**Interfaces:**
- Consumes: public API `cover_image`, manifest records.
- Produces: `BlogAssetRecord`, `getBlogAsset`, `absoluteSiteUrl`, `BlogCoverImage`, `BlogContentImage`, `BlogDetail.related_posts`.

- [ ] **Step 1: Add the initial typed manifest**

Create `manifest.json` with an empty array:

```json
[]
```

Create `lib/blog-assets.ts`:

```ts
import manifestJson from "@/public/blog-assets/manifest.json";

export type BlogAssetRole = "cover" | "inline" | "diagram" | "product-screen";
export interface BlogAssetRecord {
  path: string;
  role: BlogAssetRole;
  source_type: "generated-object" | "product-capture" | "original-diagram" | "licensed-photo";
  license: "project-owned" | "generated-for-inpa" | "commercial-license";
  created_at: string;
  used_by: string[];
  pii_reviewed: boolean;
  rights_reviewed: boolean;
  width: number;
  height: number;
  alt: string;
  caption: string;
}

const records = manifestJson as BlogAssetRecord[];
const byPath = new Map(records.map((record) => [record.path, record]));
export const getBlogAsset = (path: string) => byPath.get(path);
export const absoluteSiteUrl = (path: string) => {
  if (/^https?:\/\//.test(path)) return path;
  const site = process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.inpa.kr";
  return `${site}${path.startsWith("/") ? path : `/${path}`}`;
};
```

- [ ] **Step 2: Write failing component and structured-data tests**

Create Vitest cases that assert:

```tsx
expect(blogPosting({
  title: "보험나이 계산법",
  slug: "보험나이-계산법-6개월-예시",
  cover_image: "/blog-assets/보험나이-계산법-6개월-예시/cover.webp",
}).author).toEqual({ "@id": "https://www.inpa.kr/#organization" });

expect(blogPosting({
  title: "보험나이 계산법",
  slug: "보험나이-계산법-6개월-예시",
  cover_image: "/blog-assets/보험나이-계산법-6개월-예시/cover.webp",
}).image).toBe("https://www.inpa.kr/blog-assets/보험나이-계산법-6개월-예시/cover.webp");
```

Also render `BlogCoverImage` with a local path and assert its image has explicit dimensions, empty decorative alt, and `sizes`. Render `BlogMarkdown` with a manifest-backed image and assert a `<figure>` and caption appear.

- [ ] **Step 3: Run the test and confirm RED**

```bash
cd inpa_fe
npx vitest run components/__tests__/blog-public.test.tsx
```

Expected: missing components and current Person author behavior fail.

- [ ] **Step 4: Implement local optimized and legacy image rendering**

`BlogCoverImage` behavior:

- local `/blog-assets/` path with manifest record: Next Image, `fill`, `sizes`, `object-cover`, decorative `alt=""`.
- legacy absolute URL: current `<img>` compatibility path with lazy loading.
- missing URL or error state: iP mark and category label fallback.

`BlogContentImage` behavior:

- require a manifest record for `/blog-assets/`.
- use Next Image with manifest width/height and `sizes="(max-width: 768px) 100vw, 680px"`.
- render `<figcaption>` when `caption` is non-empty.
- return no image for an unowned/external URL; the release validator prevents publication.

- [ ] **Step 5: Replace the markdown image renderer and improve typography**

In `blog-markdown.tsx`, render `BlogContentImage` from the `img` component. Set paragraph font to 17px on service pages, line-height near 1.8, reduce repeated H2 border weight, and keep tables as accessible HTML with horizontal overflow.

- [ ] **Step 6: Fix organization author and image URL normalization**

In `structured-data.tsx`, change blog author to:

```ts
author: { "@id": `${SITE_URL}/#organization` },
image: absoluteSiteUrl(post.cover_image || "/opengraph-image.jpg"),
```

Update the comment so it no longer promises a real-person byline.

Extend frontend types:

```ts
export interface BlogRelatedPost extends Omit<BlogListItem, "tags" | "author_name" | "view_count"> {}
export interface BlogDetail { related_posts: BlogRelatedPost[]; }
```

Update `BlogAdmin` with `cover_asset_path: string` readback.

- [ ] **Step 7: Run the focused tests and build**

```bash
cd inpa_fe
npx vitest run components/__tests__/blog-public.test.tsx
npm run build
```

Expected: tests and Next build pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add inpa_fe/public/blog-assets/manifest.json inpa_fe/lib/blog-assets.ts inpa_fe/components/blog-image.tsx inpa_fe/components/blog-markdown.tsx inpa_fe/components/structured-data.tsx inpa_fe/lib/api.ts inpa_fe/lib/adminApi.ts inpa_fe/components/__tests__/blog-public.test.tsx
git commit -m "feat(블로그): 소유 이미지와 조직 작성자 렌더링"
```

---

### Task 3: Make list/detail reading flow and analytics production-quality

**Files:**
- Create: `inpa_fe/components/blog-analytics.tsx`
- Modify: `inpa_fe/app/blog/page.tsx`
- Modify: `inpa_fe/app/blog/[slug]/page.tsx`
- Test: `inpa_fe/components/__tests__/blog-public.test.tsx`

**Interfaces:**
- Consumes: `BlogCoverImage`, `BlogDetail.related_posts`, Vercel `track`.
- Produces: `BlogAnalytics`, `TrackedBlogCta`, answer-first page, related cards.

- [ ] **Step 1: Write failing analytics and presentation tests**

Mock `@vercel/analytics` and assert:

```tsx
render(<BlogAnalytics slug="보험나이-계산법-6개월-예시" category="coverage" />);
expect(track).toHaveBeenCalledWith("blog_view", expect.objectContaining({
  slug: "보험나이-계산법-6개월-예시",
  category: "coverage",
}));
```

Render `TrackedBlogCta`, click once, and assert one `blog_cta_click` with only `slug`, `category`, `destination`, `referrer_class`, and allowlisted `utm_source`, `utm_medium`, `utm_campaign`.

Add source assertions for the public pages: list cards do not render the repeated author; detail renders `인파 담당자`, published/modified dates, three related cards, and one official disclaimer.

- [ ] **Step 2: Run focused tests RED**

```bash
cd inpa_fe
npx vitest run components/__tests__/blog-public.test.tsx
```

Expected: missing analytics and old layout assertions fail.

- [ ] **Step 3: Implement safe analytics**

`blog-analytics.tsx` is a Client Component. Define:

```ts
type BlogAnalyticsProps = { slug: string; category: BlogCategory };
type TrackedBlogCtaProps = BlogAnalyticsProps & {
  href: string;
  children: React.ReactNode;
  className?: string;
};
```

`classifyReferrer` returns only `direct`, `search`, `social`, or `other`. `readAllowedUtm` reads only `utm_source`, `utm_medium`, and `utm_campaign`, truncates each to 80 characters, and sends no URL, search text, or user identifier. Analytics failures are caught and never block navigation.

- [ ] **Step 4: Update the list page**

Keep the current 3-column/page-size-12 layout. Replace the cover `<img>`/fallback branch with `BlogCoverImage`, keep title and excerpt at two lines, and show date without repeating `인파 담당자` on every card.

- [ ] **Step 5: Update the detail page**

Order content as category, title, iP avatar/byline + first publication + modified date, excerpt answer box, cover, body, tags, single disclaimer, related posts, tracked CTA. Remove the duplicate disclaimer from source bodies in Task 6/7, not by string replacement at render time.

Related cards use the API-provided three rows and never issue another API request.

- [ ] **Step 6: Run tests, copy lint, and build GREEN**

```bash
cd inpa_fe
npx vitest run components/__tests__/blog-public.test.tsx
npm run lint:copy
npm run build
```

Expected: pass with all blog routes built.

- [ ] **Step 7: Commit Task 3**

```bash
git add inpa_fe/components/blog-analytics.tsx inpa_fe/app/blog/page.tsx 'inpa_fe/app/blog/[slug]/page.tsx' inpa_fe/components/__tests__/blog-public.test.tsx
git commit -m "feat(블로그): 모바일 읽기 흐름과 관련 글 개선"
```

---

### Task 4: Build the validated, versioned content release command

**Files:**
- Create: `inpa_be/inpa/boards/blog_release.py`
- Create: `inpa_be/inpa/boards/management/commands/refresh_blog_content.py`
- Create: `inpa_be/inpa/boards/test_blog_release.py`

**Interfaces:**
- Consumes: 20 Markdown sources, `manifest.json`, `scan_blog_content`, `BlogContentRelease`.
- Produces: `BlogReleaseItem`, `load_release`, `validate_release`, `apply_release`, `restore_release`, management command.

- [ ] **Step 1: Define exact release-source format in a failing parser test**

Each source starts with this exact block:

```markdown
<!-- blog-meta
{"slug":"보험나이-계산법-6개월-예시","category":"coverage","excerpt":"보험나이를 계산할 때 확인할 기준을 예시로 정리합니다.","tags":["보험나이","설계사실무"],"seo_title":"보험나이 계산법, 생일 전후 6개월 예시","seo_description":"보험나이 계산 순서와 생일 전후 6개월 경계를 예시로 확인합니다.","cover_asset_path":"/blog-assets/보험나이-계산법-6개월-예시/cover.webp","is_published":true,"review_gate":"none","legal_review":null,"sources":[{"title":"보험업법","url":"https://www.law.go.kr/법령/보험업법","checked_at":"2026-08-03"}]}
-->
# 보험나이 계산법, 생일 전후 6개월 예시로 보기

<!-- blog-body -->

## 보험나이는 어떻게 계산하나요?
본문입니다.
```

`BlogReleaseItem` fields are exact strings/list/bool plus `title` and `body` parsed from H1/body marker. `review_gate` is exactly `none` or `legal`. `legal_review` is null unless a real review has occurred; a valid record has non-empty `reviewer`, ISO `reviewed_at`, and `reference` fields. Posts 07, 08, and 10 ship with `review_gate: "legal"`, `legal_review: null`, and `is_published: false`.

- [ ] **Step 2: Write validator failure tests**

Test rejection of:

- not exactly 20 items;
- duplicate slug;
- missing/duplicate cover path;
- cover/body image missing in manifest or on disk;
- external body image URL;
- `pii_reviewed`/`rights_reviewed` false;
- missing source/checked date;
- any `scan_blog_content` warning;
- safety slugs `보험-갈아타기-비교`, `비교안내서-한눈에-보는-비교표`, `보험-갈아타기-설계사-순서` with `is_published=true` and no valid `legal_review` record;
- published article with body disclaimer duplicated from the template;
- any body asset not listing the article slug in `used_by`.

- [ ] **Step 3: Run parser/validator tests RED**

```bash
cd inpa_be
python manage.py test inpa.boards.test_blog_release.BlogReleaseParserTests
```

Expected: module missing.

- [ ] **Step 4: Implement parser and validator**

Use only Python standard library `json`, `hashlib`, `pathlib`, `re`, and dataclasses. Do not add YAML dependencies. `load_release(content_dir, manifest_path)` returns sorted `BlogReleaseItem` records and a SHA-256 digest over normalized source bytes and manifest bytes.

`validate_release` returns a list of human-readable errors; command exits non-zero when any exist.

- [ ] **Step 5: Write apply/idempotency/rollback tests**

Cover these cases:

```python
@override_settings(...)
def test_apply_updates_by_slug_preserves_published_at_and_writes_marker(self): ...

def test_same_release_version_is_noop_and_preserves_later_admin_edit(self): ...

def test_apply_requires_backup_path(self): ...

def test_failure_rolls_back_posts_and_release_marker(self): ...

def test_backup_contains_public_content_only_and_no_author_email(self): ...

def test_restore_rejects_posts_edited_after_release(self): ...

def test_restore_recovers_existing_posts_and_unpublishes_new_posts(self): ...
```

- [ ] **Step 6: Implement atomic apply**

Expose:

```python
RELEASE_VERSION = "2026-08-blog-enrichment-v1"

def apply_release(*, items, digest, backup_path: Path) -> dict[str, int]:
    ...
```

Behavior:

1. If marker version exists with the same digest, return zero changes.
2. If marker version exists with another digest, abort.
3. Write a temporary backup, fsync, then atomically rename to `backup_path` before DB writes.
4. Inside `transaction.atomic`, update existing posts by slug and create seven new rows.
5. Preserve existing `published_at`; stamp new published posts only.
6. Preserve internal author on existing rows; assign the first admin to new rows if present, otherwise null.
7. Create `BlogContentRelease` only after all 20 writes succeed.
8. Write the after snapshot beside the requested backup as `2026-08-blog-enrichment-v1-after.json`.

- [ ] **Step 7: Implement guarded restore behavior**

Expose `restore_release(*, snapshot_path: Path, confirm_version: str)`. It must:

1. require the exact confirmation string `2026-08-blog-enrichment-v1`;
2. validate the backup schema and digest before any DB write;
3. require an active marker with the same version and digest;
4. abort when any target post has `updated_at` later than `applied_at`, so a later admin edit is never overwritten;
5. inside one transaction restore the prior 13 public fields, keep internal authors unchanged, set the seven release-created slugs to `is_published=False` rather than deleting rows, and stamp `reverted_at`;
6. print counts and slugs only, never bodies or email addresses.

- [ ] **Step 8: Implement the command interface**

```text
python manage.py refresh_blog_content
python manage.py refresh_blog_content --apply --backup-out outputs/blog-release/2026-08-blog-enrichment-v1-before.json
python manage.py refresh_blog_content --restore-from outputs/blog-release/2026-08-blog-enrichment-v1-before.json --confirm-version 2026-08-blog-enrichment-v1
```

Default is dry-run. `--apply` without `--backup-out` exits before DB or file changes. `--restore-from` is mutually exclusive with `--apply` and requires the exact `--confirm-version`. Output contains counts and slugs only, never raw bodies or author email.

- [ ] **Step 9: Run release tests GREEN and commit**

```bash
cd inpa_be
python manage.py test inpa.boards.test_blog_release
python manage.py check
```

```bash
git add inpa_be/inpa/boards/blog_release.py inpa_be/inpa/boards/management/commands/refresh_blog_content.py inpa_be/inpa/boards/test_blog_release.py
git commit -m "feat(블로그): 검증 가능한 콘텐츠 릴리스 명령 추가"
```

---

### Task 5: Audit official sources and rewrite the existing 13 posts

**Files:**
- Modify: `docs/blog-content/01-*.md` through `13-*.md`
- Modify: `docs/blog-content/00-brand-voice-guide.md`

**Interfaces:**
- Consumes: approved design section 5, official primary sources, exact metadata format from Task 4.
- Produces: 13 machine-validated corrected release sources.

- [ ] **Step 1: Build the official-source evidence table before prose edits**

Use only current official primary sources. At minimum verify:

- Insurance Business Act Articles 97 and 98 and Enforcement Decree Article 46 at `law.go.kr`;
- Financial Services Commission 5th-generation indemnity insurance announcement and duplicate-indemnity guidance at `fsc.go.kr`;
- KISA latest spam-prevention guide at `kisa.or.kr`;
- Financial Supervisory Service and life/non-life association official terminology pages.

Record exact title, direct URL, publication/effective date, and `checked_at: 2026-08-03` in each affected post metadata. Do not cite search-result pages.

- [ ] **Step 2: Convert all 13 sources to the Task 4 metadata format**

Keep each existing slug and set `cover_asset_path` to `/blog-assets/` + that unchanged slug + `/cover.webp`. Set:

```json
{"is_published": false}
```

for the three safety slugs. All other existing posts are true.

- [ ] **Step 3: Rewrite posts 01–06**

Implement the exact corrections in design section 5. Remove unsupported rates/timing, distinguish policy terms from normalized names, avoid recommendation language, and add one useful checklist/table/message block per post.

- [ ] **Step 4: Rewrite posts 07–10**

Keep 07/08/10 draft-gated. Use neutral `증권 A`/`증권 B`, official verification paths, and no implication that Inpa publishes a customer comparison guide. Keep post 09 clearly marked as a composite/fictional workflow and remove time-saving claims.

- [ ] **Step 5: Rewrite posts 11–13**

Separate fixed-benefit and indemnity duplication, avoid `중복=낭비`, and update indemnity content to official 2026-08 information. Make uncertainty and contract-specific differences explicit without sprinkling disclaimers.

- [ ] **Step 6: Remove body-level duplicate disclaimer and add related links**

Each body contains no template disclaimer sentence. Add two contextual internal links using the exact slugs from the approved 20-post catalog and one CTA that points only to a currently public Inpa feature.

- [ ] **Step 7: Run the release validator**

The manifest is incomplete until Task 8, so first run content-only tests in `BlogReleaseParserTests`, then run copy checks:

```bash
cd inpa_be
python manage.py test inpa.boards.test_blog_release.BlogReleaseParserTests
cd ../inpa_fe
npm run lint:copy
```

Expected: metadata and copy pass; full asset validation remains intentionally pending Task 8.

- [ ] **Step 8: Commit the existing-post corrections**

```bash
git add docs/blog-content/00-brand-voice-guide.md docs/blog-content/01-*.md docs/blog-content/02-*.md docs/blog-content/03-*.md docs/blog-content/04-*.md docs/blog-content/05-*.md docs/blog-content/06-*.md docs/blog-content/07-*.md docs/blog-content/08-*.md docs/blog-content/09-*.md docs/blog-content/10-*.md docs/blog-content/11-*.md docs/blog-content/12-*.md docs/blog-content/13-*.md
git commit -m "docs(블로그): 기존 13편 사실과 출처 교정"
```

---

### Task 6: Write the seven new planner-practical posts

**Files:**
- Create: `docs/blog-content/14-sales-보험-증권-요청-문자-안내.md`
- Create: `docs/blog-content/15-sales-보험-상담-준비-체크리스트.md`
- Create: `docs/blog-content/16-sales-보험-상담-후-기록-다음-연락.md`
- Create: `docs/blog-content/17-sales-상담-예약-전날-당일-안내.md`
- Create: `docs/blog-content/18-sales-보험설계사-고객관리표-필수-항목.md`
- Create: `docs/blog-content/19-coverage-보험나이-계산법-6개월-예시.md`
- Create: `docs/blog-content/20-coverage-보험-직업급수-확인-순서.md`
- Modify: `docs/blog-content/README.md`

**Interfaces:**
- Consumes: metadata/parser contract, product facts, public features.
- Produces: 7 publishable low-risk records and a 20-post catalog.

- [ ] **Step 1: Write posts 14–15**

Post 14 covers customer consent, what information to avoid exposing, approved transfer method, and a message used only after an existing customer relationship. Post 15 produces a consultation-prep checklist linked to current analysis features. Neither promises speed or results.

- [ ] **Step 2: Write posts 16–18**

Post 16 covers notes and next actions without raw medical details. Post 17 provides confirmation/change wording without `노쇼 방지` claims. Post 18 provides seven minimal fields and explicitly excludes resident numbers, medical detail, and unnecessary free text.

- [ ] **Step 3: Write posts 19–20**

Post 19 mirrors `compute_insurance_age` and tests boundary examples against the backend function. Post 20 explains why the class must be checked per company and links the current Inpa job search without claiming one universal class.

- [ ] **Step 4: Give every new post a distinct result**

Use: direct answer, 3–5 steps, synthetic example, common mistake, saveable checklist, one product connection. Keep 1,500–2,500 Korean characters excluding metadata and source list.

- [ ] **Step 5: Update the content catalog and run parser tests**

```bash
cd inpa_be
python manage.py test inpa.boards.test_blog_release.BlogReleaseParserTests
```

Expected: exactly 20 unique slugs, 17 published and 3 safety drafts.

- [ ] **Step 6: Commit the new posts**

```bash
git add docs/blog-content/README.md docs/blog-content/14-*.md docs/blog-content/15-*.md docs/blog-content/16-*.md docs/blog-content/17-*.md docs/blog-content/18-*.md docs/blog-content/19-*.md docs/blog-content/20-*.md
git commit -m "docs(블로그): 설계사 실무 글 7편 추가"
```

---

### Task 7: Produce and validate the editorial visual library

**Files:**
- Create: one `inpa_fe/public/blog-assets/{exact-approved-slug}/` directory for each of the 20 approved slugs, with declared WebP files only.
- Populate: `inpa_fe/public/blog-assets/manifest.json`
- Create: `inpa_fe/scripts/check-blog-release.mjs`
- Modify: `inpa_fe/package.json`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: final 20 bodies, capture dataset, `imagegen` built-in output, design tokens.
- Produces: 20 unique covers, shared/unique inline visuals, complete manifest, `npm run lint:blog`.

- [ ] **Step 1: Lock the 20-cover source map before generation**

Use this map:

| Post | Cover source |
|---|---|
| 01 | natural editorial desk/networking objects |
| 02 | real booking screen crop |
| 03 | synthetic text-free policy stack |
| 04 | real premium split screen crop |
| 05 | original three-area coverage diagram |
| 06 | real normalization screen crop |
| 07 | real neutral A/B comparison crop |
| 08 | original neutral two-document diagram |
| 09 | natural early-morning work desk |
| 10 | original four-step neutral review diagram |
| 11 | natural blank checklist/document scene |
| 12 | natural household planning desk |
| 13 | original medical-expense flow diagram |
| 14 | natural secure document sleeve scene |
| 15 | real analysis screen crop distinct from 03 |
| 16 | real customer-stage screen crop |
| 17 | natural calendar/appointment desk scene |
| 18 | real customer-list screen crop |
| 19 | original six-month calendar diagram |
| 20 | real job-search screen crop |

No two covers may have the same source crop or perceptual hash.

- [ ] **Step 2: Generate the seven natural object/space originals with imagegen**

Use the built-in ImageGen tool in `photorealistic-natural` mode, one call per final source. Shared constraints for every prompt:

```text
Asset type: Korean business editorial blog cover, 16:9 landscape
Style: natural editorial photography, believable real-world wear, soft window light, restrained color, documentary still life
Composition: central 70% safe area, no text overlay, no brand mark
Constraints: no people, no faces, no hands, no readable text, no Korean characters, no insurer logo, no policy document, no QR, no watermark, no glossy corporate stock-photo look, no purple gradient, no impossible object geometry
```

Distinct subjects are: networking desk, text-free blank paper stack with magnifier, early-morning work desk, blank checklist documents, household planning desk, secure document sleeve, and calendar appointment desk. Inspect every output at original detail and regenerate any asset with warped objects, fake text, excessive cleanliness, or repeated composition.

- [ ] **Step 3: Capture the eight real product-source covers and reusable inline screens**

Use the existing `seed_capture` synthetic account. Capture current public functionality only: booking, analysis, premium split, normalization, A/B comparison, customer stage, customer list, job search. Hide feedback controls and verify there is no PII, real phone number, carrier/product name, system marker, notification text, or closed feature.

- [ ] **Step 4: Build five original diagram covers and the required inline diagrams**

Create deterministic HTML/SVG diagrams using active tokens from `app/globals.css`, then render to WebP. Diagrams include labels only when the final Korean text is authored in code, never generated in a bitmap model. Every diagram also has equivalent HTML explanation in the body.

- [ ] **Step 5: Build inline visual set and reuse only when semantically identical**

Create the 20-post inline plan from design section 5/6. Reuse these real screens where accurate: booking for 02/17, analysis for 03/06/15, neutral comparison for 07/08/10, customer-stage/list for 01/16/18. All other inline visuals are unique diagrams. Do not repeat the cover image inside the same body.

- [ ] **Step 6: Optimize and strip metadata**

Use Pillow to convert every committed raster asset to WebP, strip EXIF/GPS, keep long edge ≤1600, cover at exactly 1600×900, and enforce the design size budgets.

- [ ] **Step 7: Populate the manifest**

For every asset record exact path, role, source type, license, creation date, used-by slugs, PII and rights review booleans, intrinsic width/height, alt, and caption. Decorative covers use `alt=""`; information assets use 20–60 Korean characters.

- [ ] **Step 8: Write the failing blog asset lint tests**

`check-blog-release.mjs` exits non-zero for missing files, undeclared files, external paths, duplicate covers, wrong 16:9 size, false review booleans, missing dimensions, information image without alt, or files over budget.

- [ ] **Step 9: Add the CI gate and run it GREEN**

Add to `package.json`:

```json
"lint:blog": "node scripts/check-blog-release.mjs"
```

Add `npm run lint:blog` after `npm run lint:copy` in the frontend CI job.

Run:

```bash
cd inpa_fe
npm run lint:blog
npm run lint:copy
npm run build
```

- [ ] **Step 10: Run the backend full release validator**

```bash
cd inpa_be
python manage.py refresh_blog_content
```

Expected: 20 valid records, 17 public, 3 safety drafts, zero validation errors.

- [ ] **Step 11: Commit Task 7**

```bash
git add inpa_fe/public/blog-assets inpa_fe/scripts/check-blog-release.mjs inpa_fe/package.json .github/workflows/ci.yml
git commit -m "feat(블로그): 고유 커버와 본문 시각 자료 추가"
```

---

### Task 8: Apply locally and perform full visual/content verification

**Files:**
- Runtime outputs only under `outputs/blog-release/` (untracked).

**Interfaces:**
- Consumes: Tasks 1–7 complete.
- Produces: migrated local DB, 20-post preview evidence, findings fixed before review.

- [ ] **Step 1: Apply migrations and dry-run**

```bash
cd inpa_be
python manage.py migrate
python manage.py refresh_blog_content
```

Expected: schema applied, dry-run lists 13 updates and 7 creates.

- [ ] **Step 2: Apply the release locally**

```bash
python manage.py refresh_blog_content --apply --backup-out ../outputs/blog-release/2026-08-blog-enrichment-v1-before.json
```

Expected: 20 records, 17 published, 3 safety drafts, release marker present.

- [ ] **Step 3: Verify database state directly**

```bash
python manage.py shell -c "from inpa.boards.blog_release import load_release; from inpa.boards.models import BlogPost,BlogContentRelease; items,_=load_release(); slugs=[x.slug for x in items]; print(BlogPost.objects.filter(slug__in=slugs).count(), BlogPost.objects.filter(slug__in=slugs,is_published=True).count(), BlogContentRelease.objects.values_list('version','item_count','reverted_at'))"
```

Expected: exactly 20 release posts, exactly 17 of those release posts public, marker `2026-08-blog-enrichment-v1` with item_count 20 and null `reverted_at`.

- [ ] **Step 4: Run focused and full automated gates**

```bash
cd inpa_be
python manage.py test inpa.boards
python manage.py test inpa
python manage.py check
cd ../inpa_fe
npm run test:run
npm run lint:copy
npm run lint:blog
npm run build
```

Expected: all pass. Do not report success from build/typecheck alone.

- [ ] **Step 5: Run local backend and frontend**

```bash
cd inpa_be && python manage.py runserver 127.0.0.1:8000
cd ../inpa_fe && NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api/v1 npm run dev
```

- [ ] **Step 6: Browser-verify desktop and mobile**

Use the Browser skill. Check `/blog`, page 2, every category, all 20 admin-preview/detail states, 17 public details, and 3 draft visibility. At desktop and mobile verify unique covers, answer-first layout, author, modified date, captions, tables, related cards, CTA, no horizontal overflow, no broken asset, no duplicate disclaimer, no PII, and no generated artifact.

- [ ] **Step 7: Verify API runtime with curl**

```bash
curl -fsS http://127.0.0.1:8000/api/v1/board/blog/?page_size=20
curl -fsS http://127.0.0.1:8000/api/v1/board/blog/보험나이-계산법-6개월-예시/
```

Expected: author `인파 담당자`, relative static cover, three related posts, no draft safety slugs in public list.

- [ ] **Step 8: Fix every confirmed finding and rerun the affected gate**

Do not defer critical/important correctness, privacy, accessibility, or trust findings.

---

### Task 9: Independent review, commit final fixes, and publish PR

**Files:**
- Any files changed by confirmed review fixes only.

**Interfaces:**
- Consumes: verified implementation.
- Produces: review-approved branch, pushed branch, draft PR, green CI.

- [ ] **Step 1: Invoke `superpowers:requesting-code-review`**

Review lenses:

1. content factual accuracy and current product behavior;
2. legal/compliance and neutral comparison language;
3. privacy/image provenance/PII;
4. backend correctness/idempotency/rollback;
5. frontend accessibility/performance/mobile UX;
6. brand authenticity and generated-image artifacts.

- [ ] **Step 2: Fix confirmed findings using TDD**

Each code finding gets a failing regression test before the fix. Each content/image finding gets a validator rule or manifest/body correction and a rerun of the relevant gate.

- [ ] **Step 3: Run final verification from a clean state**

```bash
git status --short
cd inpa_be && python manage.py test inpa && python manage.py check
cd ../inpa_fe && npm run test:run && npm run lint:copy && npm run lint:blog && npm run build
cd .. && git diff --check origin/master...HEAD
```

- [ ] **Step 4: Commit only final owned fixes**

Record the exact review-fix paths in the review log, stage each recorded path explicitly, never use `git add -A` or `git add -u`, and commit with `fix(블로그): 배포 전 다각 검토 findings 반영`. Skip this commit when review produces no changes.

- [ ] **Step 5: Invoke `github:yeet` and publish**

Before push:

```bash
git fetch origin
git log --oneline origin/master..HEAD
git diff --stat origin/master...HEAD
```

Push `codex/blog-content-enrichment` and open a draft PR with scope, tests, publication gate, data command, rollback, and image provenance summary.

- [ ] **Step 6: Wait for GitHub Actions and fix failures**

If any GitHub Action fails, invoke `github:gh-fix-ci`, inspect logs, fix the root cause, rerun local gates, push, and wait again. Required checks: backend, frontend build/lints, gitleaks.

---

### Task 10: Merge, deploy, apply production content, and close documentation

**Files:**
- Modify after production verification: `README.md`, `AGENTS.md`.

**Interfaces:**
- Consumes: green reviewed PR, explicit deployment authorization from 2026-08-03.
- Produces: merged master, Vercel/Render production release, production DB content marker, post-deploy docs.

- [ ] **Step 1: Production preflight immediately before merge**

Confirm exact PR head SHA, all required checks green, migration additive, data backup command, 17/3 publication split, rollback path, production env diff unchanged, and no unrelated commits. If any differs, stop before merge.

- [ ] **Step 2: Merge the reviewed PR**

Use GitHub Flow merge without force push. Vercel and Render auto-deploy from `master`.

- [ ] **Step 3: Wait for both deployments and verify code before data apply**

Check GitHub Actions, Vercel production `/blog`, Render deploy status, and `/healthz/`. Confirm the old content still renders with the new compatible code before running the release command.

- [ ] **Step 4: Run production dry-run in Render Shell**

```bash
python manage.py refresh_blog_content
```

Expected: 13 updates, 7 creates, 17 public, 3 safety drafts, zero validation errors.

- [ ] **Step 5: Run production apply with backup**

```bash
mkdir -p outputs/blog-release
python manage.py refresh_blog_content --apply --backup-out outputs/blog-release/2026-08-blog-enrichment-v1-before.json
```

Download or copy the before/after JSON artifacts from the one-off shell before closing it. They contain public blog content only and no author email.

- [ ] **Step 6: Verify production runtime**

Check:

- `https://www.inpa.kr/blog` shows 17 public articles over two pages;
- seven new slugs return 200;
- the three safety slugs return 404 publicly and remain editable as drafts in admin;
- author is `인파 담당자`;
- covers and inline images load from `www.inpa.kr/blog-assets/`;
- related posts, CTA analytics, OG, JSON-LD, sitemap, and mobile layout work;
- `https://inpa-be.onrender.com/healthz/` returns the expected OK JSON;
- no new Sentry/console errors during a five-minute observation window.

- [ ] **Step 7: Prepare rollback but use it only on a confirmed material issue**

Code rollback: Vercel rollback and Render previous deploy. Data rollback: while the new code is still available, run `python manage.py refresh_blog_content --restore-from outputs/blog-release/2026-08-blog-enrichment-v1-before.json --confirm-version 2026-08-blog-enrichment-v1`; the command must abort if a later admin edit exists. Otherwise preserve snapshots without mutation. Do not delete release assets while any post references them.

- [ ] **Step 8: Update PM and agent docs after production is proven**

Update `README.md` in Korean with the 17-public/3-review-pending release and image/readability improvements. Update `AGENTS.md` with current state, `cover_asset_path`, fixed public author, release command, asset manifest, and marker version.

- [ ] **Step 9: Commit and merge the docs-only closeout**

```bash
git add README.md AGENTS.md
git commit -m "docs: 블로그 콘텐츠 품질 보강 운영 상태 기록"
```

Push a docs-only PR, merge after checks, and confirm the docs commit does not alter production behavior.

- [ ] **Step 10: Final report**

Use the required format:

```text
Changed: [20편 프리뷰, 17편 운영 공개, 이미지·저자·관련 글·가독성·릴리스 안전장치]
Verified by: [backend/frontend tests, build, copy/blog lint, browser, curl, CI, production URLs]
Result: [actual counts, SHA, PR, deploy states, health response]
Unverified: [only the three lawyer-review-gated posts, with reason]
```
