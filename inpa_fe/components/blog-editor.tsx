"use client";

// 인파 노트 에디터 — /admin/blog/new 와 /admin/blog/[id]/edit 가 공유한다.
// ★ 미리보기는 공개 페이지와 '같은 렌더러'(BlogMarkdown) + .theme-light 로 실제 라이트 화면과
//   동일하게 보여준다(렌더 단일 소스). 초안 비공개 미리보기 = 이 실시간 미리보기 패널.
//   공개 URL(/blog/<slug>)은 서버 렌더가 토큰 없이 조회하므로 '게시된' 글에서만 새 탭으로 연다.
import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  adminGetBlogPost,
  adminCreateBlogPost,
  adminUpdateBlogPost,
  uploadBlogCover,
  type BlogWritePayload,
  type CopyWarning,
} from "@/lib/adminApi";
import { BLOG_CATEGORIES, type BlogCategory } from "@/lib/api";
import { BlogMarkdown } from "@/components/blog-markdown";

const EXCERPT_MAX = 200;
const SEO_TITLE_MAX = 60;
const SEO_DESC_MAX = 160;

const FIELD_LABEL: Record<CopyWarning["field"], string> = {
  title: "제목",
  body: "본문",
  excerpt: "요약",
};
const ISSUE_LABEL: Record<CopyWarning["issue"], string> = {
  em_dash: "긴 줄표 기호(쉼표·마침표·괄호로 바꾸기)",
  advice_word: "권유 표현(사실 서술로)",
};

/** 제목 → 슬러그(공백 → -, 한글·영문·숫자·하이픈 유지). PM 이 직접 수정 가능. */
function slugify(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^\p{L}\p{N}-]/gu, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

const inputCls =
  "w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink outline-none focus:border-brand";

export function BlogEditor({ postId: initialPostId }: { postId?: number }) {
  const router = useRouter();

  const [postId, setPostId] = useState<number | undefined>(initialPostId);
  const [loading, setLoading] = useState<boolean>(!!initialPostId);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 필드
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [category, setCategory] = useState<BlogCategory>("sales");
  const [tags, setTags] = useState("");
  const [excerpt, setExcerpt] = useState("");
  const [seoTitle, setSeoTitle] = useState("");
  const [seoDescription, setSeoDescription] = useState("");
  const [isNoindex, setIsNoindex] = useState(false);
  const [body, setBody] = useState("");
  const [seoOpen, setSeoOpen] = useState(false);

  // 커버
  const [coverImage, setCoverImage] = useState<string | null>(null); // 저장된 R2 URL
  const [coverFile, setCoverFile] = useState<File | null>(null); // 신규 글: 저장 전 대기 파일
  const [coverPreview, setCoverPreview] = useState<string | null>(null); // objectURL(대기 미리보기)
  const [coverCleared, setCoverCleared] = useState(false); // 수정 중 커버를 명시적으로 지웠나(→ PATCH 에 cover_image:null 전송)
  const [coverUploading, setCoverUploading] = useState(false);

  // 저장 상태
  const [published, setPublished] = useState(false);
  const [initialSlug, setInitialSlug] = useState("");
  const [initialPublished, setInitialPublished] = useState(false);
  const [saving, setSaving] = useState(false);
  const [warnings, setWarnings] = useState<CopyWarning[]>([]);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const bodyRef = useRef<HTMLTextAreaElement>(null);

  // ── 기존 글 로드(edit 모드) ─────────────────────────────────
  useEffect(() => {
    if (!initialPostId) return;
    let cancelled = false;
    (async () => {
      try {
        const p = await adminGetBlogPost(initialPostId);
        if (cancelled) return;
        setTitle(p.title);
        setSlug(p.slug);
        setInitialSlug(p.slug);
        setSlugTouched(true); // 로드된 슬러그는 제목 변경으로 자동 덮어쓰지 않는다.
        setCategory(p.category);
        setTags(p.tags);
        setExcerpt(p.excerpt);
        setSeoTitle(p.seo_title);
        setSeoDescription(p.seo_description);
        setIsNoindex(p.is_noindex);
        setBody(p.body);
        setCoverImage(p.cover_image);
        setPublished(p.is_published);
        setInitialPublished(p.is_published);
        if (p.seo_title || p.seo_description || p.is_noindex) setSeoOpen(true);
      } catch {
        if (!cancelled) setLoadError("글을 불러오지 못했어요.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialPostId]);

  // ── 제목 → 슬러그 자동(신규·미수정 시에만) ───────────────────
  function onTitleChange(v: string) {
    setTitle(v);
    if (!postId && !slugTouched) setSlug(slugify(v));
  }

  // ── 본문 마크다운 툴바 ──────────────────────────────────────
  const wrapInline = useCallback(
    (before: string, after: string, placeholder: string) => {
      const ta = bodyRef.current;
      if (!ta) return;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const selected = body.slice(start, end) || placeholder;
      const next = body.slice(0, start) + before + selected + after + body.slice(end);
      setBody(next);
      requestAnimationFrame(() => {
        ta.focus();
        const pos = start + before.length;
        ta.setSelectionRange(pos, pos + selected.length);
      });
    },
    [body]
  );

  const insertBlock = useCallback(
    (snippet: string) => {
      const ta = bodyRef.current;
      if (!ta) {
        setBody((b) => (b ? b + "\n\n" + snippet : snippet));
        return;
      }
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const beforeText = body.slice(0, start);
      const afterText = body.slice(end);
      const lead = beforeText === "" || beforeText.endsWith("\n\n") ? "" : beforeText.endsWith("\n") ? "\n" : "\n\n";
      const trail = afterText === "" || afterText.startsWith("\n") ? "" : "\n";
      const insert = lead + snippet + trail;
      const next = beforeText + insert + afterText;
      setBody(next);
      requestAnimationFrame(() => {
        ta.focus();
        const pos = start + insert.length;
        ta.setSelectionRange(pos, pos);
      });
    },
    [body]
  );

  const TOOLS: { label: string; title: string; run: () => void }[] = [
    { label: "H2", title: "소제목", run: () => insertBlock("## 소제목") },
    { label: "H3", title: "작은 소제목", run: () => insertBlock("### 작은 소제목") },
    { label: "굵게", title: "굵게", run: () => wrapInline("**", "**", "굵게") },
    { label: "기울임", title: "기울임", run: () => wrapInline("_", "_", "기울임") },
    { label: "링크", title: "링크", run: () => wrapInline("[", "](https://)", "링크 텍스트") },
    { label: "목록", title: "목록", run: () => insertBlock("- 항목 1\n- 항목 2\n- 항목 3") },
    { label: "인용", title: "인용", run: () => insertBlock("> 인용문") },
    { label: "이미지", title: "이미지", run: () => insertBlock("![설명](이미지 주소)") },
  ];

  // ── 커버 선택 ───────────────────────────────────────────────
  async function onCoverPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // 같은 파일 재선택 허용
    if (!file) return;
    if (postId) {
      // 이미 글이 존재 → 즉시 R2 업로드하고 저장된 URL 확보(미리보기 = 실제 저장본)
      setCoverUploading(true);
      setSaveError(null);
      try {
        const updated = await uploadBlogCover(postId, file);
        setCoverImage(updated.cover_image);
        setCoverFile(null);
        setCoverPreview(null);
        setCoverCleared(false);
      } catch {
        setSaveError("커버 이미지를 올리지 못했어요. 잠시 후 다시 시도해 주세요.");
      } finally {
        setCoverUploading(false);
      }
    } else {
      // 신규 글 → 저장(생성) 시 함께 업로드. 그 전엔 로컬 미리보기.
      setCoverFile(file);
      setCoverPreview((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return URL.createObjectURL(file);
      });
    }
  }

  function clearCover() {
    setCoverImage(null);
    setCoverFile(null);
    setCoverCleared(true); // 저장 시 cover_image:null 을 명시 전송해 R2 커버를 실제로 제거
    setCoverPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
  }

  // objectURL 정리
  useEffect(() => {
    return () => {
      if (coverPreview) URL.revokeObjectURL(coverPreview);
    };
  }, [coverPreview]);

  const shownCover = coverPreview ?? coverImage;

  // ── 저장 ────────────────────────────────────────────────────
  async function doSave(targetPublished: boolean) {
    if (!title.trim() || !body.trim()) {
      setSaveError("제목과 본문을 채워 주세요.");
      return;
    }
    if (targetPublished && !confirm("이 글을 공개할까요? 공개하면 블로그 목록과 검색에 노출돼요.")) return;
    if (postId && initialPublished && !targetPublished) {
      if (!confirm("게시를 내리면 공개 화면에서 숨겨져요. 계속할까요?")) return;
    }

    setSaving(true);
    setSaveError(null);
    setSavedMsg(null);
    setWarnings([]);

    const payload: BlogWritePayload = {
      title: title.trim(),
      body,
      excerpt: excerpt.trim(),
      category,
      tags: tags.trim(),
      is_published: targetPublished,
      seo_title: seoTitle.trim(),
      seo_description: seoDescription.trim(),
      is_noindex: isNoindex,
    };
    // 슬러그는 값이 있을 때만 보낸다(비우면 BE 가 제목에서 자동 생성).
    if (slug.trim()) payload.slug = slug.trim();
    // 수정 중 커버를 지웠으면 명시적으로 null 전송 — 부분 PATCH 라 누락 시 기존 커버가 그대로 남는다(D1).
    if (postId && coverCleared) payload.cover_image = null;

    try {
      if (postId) {
        const res = await adminUpdateBlogPost(postId, payload);
        setPublished(res.is_published);
        setInitialPublished(res.is_published);
        setInitialSlug(res.slug);
        setSlug(res.slug);
        setCoverImage(res.cover_image);
        setCoverCleared(false);
        setWarnings(res.warnings ?? []);
        setSavedMsg(res.is_published ? "저장하고 게시했어요." : "임시저장했어요.");
      } else {
        const res = await adminCreateBlogPost(payload, coverFile);
        setPostId(res.id);
        setPublished(res.is_published);
        setInitialPublished(res.is_published);
        setInitialSlug(res.slug);
        setSlug(res.slug);
        setSlugTouched(true);
        setCoverImage(res.cover_image);
        setCoverFile(null);
        setCoverPreview((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return null;
        });
        setWarnings(res.warnings ?? []);
        setSavedMsg(res.is_published ? "새 글을 게시했어요." : "새 글을 임시저장했어요.");
        // 리마운트 없이 주소만 편집 URL 로 바꿔 새로고침 대비(내비게이션 아님 = 상태 보존).
        window.history.replaceState(null, "", `/admin/blog/${res.id}/edit`);
      }
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "저장에 실패했어요.");
    } finally {
      setSaving(false);
    }
  }

  const slugChangeWarn = !!postId && initialPublished && slug.trim() !== initialSlug;

  if (loading) {
    return <div className="p-6 text-[14px] text-ink3">불러오는 중...</div>;
  }
  if (loadError) {
    return (
      <div className="p-6">
        <div className="rounded-xl border border-line bg-danger-tint p-4 text-[13px] text-danger-ink">{loadError}</div>
        <button onClick={() => router.push("/admin/blog")} className="mt-4 text-[13px] font-semibold text-brand hover:underline">
          ← 목록으로
        </button>
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* 상단 바 */}
      <div className="mb-5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push("/admin/blog")}
            className="text-[13px] font-semibold text-ink3 hover:text-ink"
          >
            ← 목록
          </button>
          <h1 className="text-[18px] font-extrabold text-ink">{postId ? "글 수정" : "새 글"}</h1>
          {published && (
            <span className="rounded-full bg-success-tint px-2 py-0.5 text-[11px] font-bold text-success-ink">게시됨</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {postId && published && (
            <a
              href={`/blog/${slug}`}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 hover:border-brand"
            >
              새 탭에서 보기
            </a>
          )}
          {published ? (
            <>
              <button
                onClick={() => doSave(false)}
                disabled={saving}
                className="rounded-xl border border-line bg-surface px-4 py-2 text-[13px] font-semibold text-ink2 hover:border-brand disabled:opacity-50"
              >
                게시 내리기
              </button>
              <button
                onClick={() => doSave(true)}
                disabled={saving}
                className="rounded-xl bg-brand px-4 py-2 text-[13px] font-bold text-white disabled:opacity-50"
              >
                {saving ? "저장 중..." : "수정 저장"}
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => doSave(false)}
                disabled={saving}
                className="rounded-xl border border-line bg-surface px-4 py-2 text-[13px] font-semibold text-ink2 hover:border-brand disabled:opacity-50"
              >
                임시저장
              </button>
              <button
                onClick={() => doSave(true)}
                disabled={saving}
                className="rounded-xl bg-brand px-4 py-2 text-[13px] font-bold text-white disabled:opacity-50"
              >
                {saving ? "저장 중..." : "게시하기"}
              </button>
            </>
          )}
        </div>
      </div>

      {/* 저장 결과 / 경고 */}
      {savedMsg && (
        <div className="mb-3 rounded-xl border border-line bg-success-tint px-4 py-2.5 text-[13px] font-semibold text-success-ink">
          {savedMsg}
        </div>
      )}
      {saveError && (
        <div className="mb-3 rounded-xl border border-line bg-danger-tint px-4 py-2.5 text-[13px] text-danger-ink">
          {saveError}
        </div>
      )}
      {warnings.length > 0 && (
        <div className="mb-3 rounded-xl border border-warning-ink/30 bg-warning-tint px-4 py-3 text-[13px] text-warning-ink">
          <p className="font-bold">고객 대면 문구 주의 (저장은 됐어요)</p>
          <ul className="mt-1.5 space-y-1">
            {warnings.map((w, i) => (
              <li key={i}>
                {FIELD_LABEL[w.field]}에 &lsquo;{w.match}&rsquo; · {ISSUE_LABEL[w.issue]}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 메타 필드 */}
      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-[12px] font-semibold text-ink3">제목</label>
          <input
            value={title}
            onChange={(e) => onTitleChange(e.target.value)}
            placeholder="검색되는 제목을 써 주세요"
            className={`${inputCls} text-[16px] font-semibold`}
          />
        </div>

        <div>
          <label className="mb-1 block text-[12px] font-semibold text-ink3">주소(슬러그)</label>
          <div className="flex items-center gap-2">
            <span className="text-[13px] text-ink3">/blog/</span>
            <input
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value);
                setSlugTouched(true);
              }}
              placeholder="자동으로 만들어져요"
              className={`${inputCls} flex-1`}
            />
          </div>
          {slugChangeWarn && (
            <p className="mt-1 text-[12px] text-warning-ink">
              발행 후 슬러그를 바꾸면 기존 링크가 깨져요. 꼭 필요할 때만 바꿔 주세요.
            </p>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-[12px] font-semibold text-ink3">카테고리</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as BlogCategory)}
              className={inputCls}
            >
              {BLOG_CATEGORIES.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[12px] font-semibold text-ink3">태그 (쉼표로 구분)</label>
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="예: 신입설계사, 보장분석"
              className={inputCls}
            />
          </div>
        </div>

        {/* 커버 */}
        <div>
          <label className="mb-1 block text-[12px] font-semibold text-ink3">커버 이미지 (선택)</label>
          <div className="flex items-start gap-4">
            <div className="h-24 w-40 shrink-0 overflow-hidden rounded-xl border border-line bg-surface2">
              {shownCover ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={shownCover} alt="커버 미리보기" className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-[12px] text-ink3">
                  미리보기
                </div>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <label className="w-fit cursor-pointer rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 hover:border-brand">
                {coverUploading ? "올리는 중..." : shownCover ? "다른 이미지로 바꾸기" : "이미지 올리기"}
                <input type="file" accept="image/*" onChange={onCoverPick} className="hidden" disabled={coverUploading} />
              </label>
              {shownCover && (
                <button onClick={clearCover} className="w-fit text-[12px] font-semibold text-danger hover:underline">
                  커버 지우기
                </button>
              )}
              {!postId && coverFile && (
                <p className="text-[11px] text-ink3">저장하면 함께 올라가요.</p>
              )}
            </div>
          </div>
        </div>

        {/* 요약 */}
        <div>
          <div className="mb-1 flex items-center justify-between">
            <label className="text-[12px] font-semibold text-ink3">요약 (목록·검색 미리보기)</label>
            <span className={`text-[11px] ${excerpt.length > EXCERPT_MAX ? "text-danger" : "text-ink3"}`}>
              {excerpt.length}/{EXCERPT_MAX}
            </span>
          </div>
          <textarea
            value={excerpt}
            onChange={(e) => setExcerpt(e.target.value)}
            maxLength={EXCERPT_MAX}
            rows={2}
            placeholder="한두 문장으로 이 글이 무엇을 돕는지 적어 주세요"
            className={`${inputCls} resize-none`}
          />
        </div>

        {/* SEO 접기 */}
        <div className="rounded-xl border border-line">
          <button
            onClick={() => setSeoOpen((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-[13px] font-semibold text-ink2"
          >
            <span>SEO 설정 (선택)</span>
            <span className="text-ink3">{seoOpen ? "접기 ▲" : "펼치기 ▼"}</span>
          </button>
          {seoOpen && (
            <div className="space-y-4 border-t border-line px-4 py-4">
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="text-[12px] font-semibold text-ink3">검색 제목 (비우면 제목 사용)</label>
                  <span className="text-[11px] text-ink3">{seoTitle.length}/{SEO_TITLE_MAX}</span>
                </div>
                <input
                  value={seoTitle}
                  onChange={(e) => setSeoTitle(e.target.value)}
                  maxLength={SEO_TITLE_MAX}
                  className={inputCls}
                />
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="text-[12px] font-semibold text-ink3">검색 설명 (비우면 요약 사용)</label>
                  <span className="text-[11px] text-ink3">{seoDescription.length}/{SEO_DESC_MAX}</span>
                </div>
                <textarea
                  value={seoDescription}
                  onChange={(e) => setSeoDescription(e.target.value)}
                  maxLength={SEO_DESC_MAX}
                  rows={2}
                  className={`${inputCls} resize-none`}
                />
              </div>
              <label className="flex items-center gap-2 text-[13px] text-ink2">
                <input type="checkbox" checked={isNoindex} onChange={(e) => setIsNoindex(e.target.checked)} />
                검색에 숨기기 (색인 제외)
              </label>
            </div>
          )}
        </div>
      </div>

      {/* 본문 에디터 + 실시간 미리보기 */}
      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 에디터 */}
        <div className="flex flex-col rounded-xl border border-line bg-surface">
          <div className="flex flex-wrap gap-1 border-b border-line px-2 py-2">
            {TOOLS.map((t) => (
              <button
                key={t.label}
                type="button"
                title={t.title}
                onClick={t.run}
                className="rounded-lg px-2.5 py-1 text-[12px] font-semibold text-ink2 hover:bg-surface2"
              >
                {t.label}
              </button>
            ))}
          </div>
          <textarea
            ref={bodyRef}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="마크다운으로 본문을 작성하세요. 위 버튼으로 소제목·목록·표를 넣을 수 있어요."
            className="min-h-[480px] w-full resize-y rounded-b-xl bg-surface px-4 py-3 text-[14px] leading-7 text-ink outline-none font-mono"
          />
        </div>

        {/* 미리보기 — 공개 페이지와 같은 렌더러 + 라이트(실제 화면과 동일) */}
        <div className="flex flex-col rounded-xl border border-line">
          <div className="border-b border-line px-4 py-2 text-[12px] font-semibold text-ink3">미리보기 (비공개)</div>
          <div className="theme-light min-h-[480px] overflow-y-auto rounded-b-xl px-5 py-5">
            {title && <h1 className="mb-3 text-[24px] font-extrabold leading-tight text-brand-ink">{title}</h1>}
            {excerpt && <p className="mb-4 text-[15px] font-medium leading-8 text-ink2">{excerpt}</p>}
            {body.trim() ? (
              <BlogMarkdown body={body} />
            ) : (
              <p className="text-[14px] text-ink3">본문을 입력하면 여기에 미리보기가 보여요.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
