import type { Metadata } from "next";
import Link from "next/link";
import { InpaMark } from "@/components/inpa-logo";
import { listBlogPosts, BLOG_CATEGORIES, type BlogListItem } from "@/lib/api";

// 블로그 목록 — 서버 컴포넌트, 라이트 고정(서비스 페이지 테마 가드 §6).
// ★ force-dynamic: 요청 시점 렌더 → 빌드가 BE 를 부르지 않고(빌드 안정), 새 글이 바로 반영된다.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 12;

const OG_TITLE = "블로그 · 인파(Inpa)";
const OG_DESC =
  "보험설계사를 위한 블로그. 고객 늘리기, 보장분석, 안심 가이드, 설계사 이야기를 쉬운 말로 정리했습니다.";

export const metadata: Metadata = {
  title: "블로그",
  description: OG_DESC,
  alternates: { canonical: "/blog" },
  // §7 트랩: 페이지별 openGraph 정의 시 루트 파일컨벤션 이미지가 상속되지 않으므로 명시 참조.
  openGraph: {
    type: "website",
    locale: "ko_KR",
    siteName: "인파(Inpa)",
    title: OG_TITLE,
    description: OG_DESC,
    url: "/blog",
    images: [{ url: "/opengraph-image.jpg", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: OG_TITLE,
    description: OG_DESC,
    images: ["/opengraph-image.jpg"],
  },
};

function fmtDate(d: string | null): string {
  if (!d) return "";
  // 서버 렌더(Vercel=UTC)에서도 KST 기준 날짜로 — 자정 근처 하루 밀림 방지.
  return new Date(d).toLocaleDateString("ko-KR", {
    year: "numeric", month: "long", day: "numeric", timeZone: "Asia/Seoul",
  });
}

function PostCard({ post }: { post: BlogListItem }) {
  return (
    <Link
      href={`/blog/${post.slug}`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-card transition hover:-translate-y-0.5 hover:shadow-lg"
    >
      {/* 커버 — 이미지가 있으면 사진, 없으면 옅은 브랜드 틴트 + iP 마크(타이포 커버 폴백) */}
      <div className="relative aspect-[16/9] w-full overflow-hidden bg-accent-tint">
        {post.cover_image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={post.cover_image}
            alt=""
            className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2 bg-accent-tint">
            <InpaMark size={34} />
            <span className="text-[12px] font-bold text-brand-ink">{post.category_label}</span>
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col p-5">
        <span className="mb-2 inline-flex w-fit rounded-full bg-accent-tint px-2.5 py-1 text-[11px] font-bold text-brand">
          {post.category_label}
        </span>
        <h2 className="text-[16px] font-bold leading-snug text-ink line-clamp-2 group-hover:text-brand-ink transition">
          {post.title}
        </h2>
        {post.excerpt && (
          <p className="mt-2 text-[13px] leading-6 text-ink3 line-clamp-2">{post.excerpt}</p>
        )}
        <div className="mt-auto pt-4 text-[12px] text-muted">
          {post.author_name}
          {post.published_at && <span> · {fmtDate(post.published_at)}</span>}
        </div>
      </div>
    </Link>
  );
}

export default async function BlogListPage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string; page?: string }>;
}) {
  const sp = await searchParams;
  const activeCategory = sp.category ?? "";
  const page = Math.max(1, Number(sp.page) || 1);

  let posts: BlogListItem[] = [];
  let hasNext = false;
  let hasPrev = page > 1;
  let loadFailed = false;
  try {
    const res = await listBlogPosts({
      category: activeCategory || undefined,
      page,
      pageSize: PAGE_SIZE,
    });
    posts = res.results;
    hasNext = !!res.next;
    hasPrev = !!res.previous;
  } catch {
    loadFailed = true;
  }

  const catQuery = (cat: string) => (cat ? `?category=${cat}` : "");
  const pageHref = (p: number) => {
    const params = new URLSearchParams();
    if (activeCategory) params.set("category", activeCategory);
    if (p > 1) params.set("page", String(p));
    const q = params.toString();
    return q ? `/blog?${q}` : "/blog";
  };

  const tabs = [{ code: "", label: "전체" }, ...BLOG_CATEGORIES];

  return (
    <div className="min-h-screen bg-canvas text-ink">
      {/* 헤더 */}
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2" aria-label="인파 홈으로">
            <InpaMark size={28} />
            <span className="text-[16px] font-extrabold text-brand-ink">블로그</span>
          </Link>
          <Link
            href="/register"
            className="flex min-h-[44px] items-center rounded-xl bg-brand px-4 py-2 text-[14px] font-semibold text-white transition hover:opacity-90"
          >
            무료로 시작하기
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
        <div className="max-w-2xl">
          <h1 className="text-[30px] font-extrabold tracking-tight text-brand-ink sm:text-[38px]">블로그</h1>
          <p className="mt-3 text-[15px] leading-relaxed text-ink3 sm:text-[16px]">
            현장에서 바로 쓰는 영업 팁부터 보장분석, 규정 안심 가이드까지. 설계사님의 하루를 조금 더 가볍게 만드는 이야기를 모았어요.
          </p>
        </div>

        {/* 카테고리 탭 */}
        <nav className="mt-8 flex flex-wrap gap-2" aria-label="카테고리">
          {tabs.map((t) => {
            const active = activeCategory === t.code;
            return (
              <Link
                key={t.code || "all"}
                href={`/blog${catQuery(t.code)}`}
                className={`rounded-full px-3.5 py-2 text-[13px] font-semibold transition ${
                  active
                    ? "bg-brand text-white"
                    : "border border-line bg-surface text-ink2 hover:border-brand hover:text-brand"
                }`}
              >
                {t.label}
              </Link>
            );
          })}
        </nav>

        {/* 목록 */}
        {loadFailed ? (
          <div className="mt-16 rounded-2xl border border-line bg-surface p-10 text-center">
            <p className="text-[15px] font-semibold text-ink">잠시 후 다시 열어봐 주세요.</p>
            <p className="mt-2 text-[13px] text-ink3">글을 불러오는 중에 연결이 잠깐 끊겼어요.</p>
          </div>
        ) : posts.length === 0 ? (
          <div className="mt-16 rounded-2xl border border-line bg-surface p-10 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-accent-tint">
              <InpaMark size={26} />
            </div>
            <p className="text-[15px] font-semibold text-ink">곧 첫 이야기가 올라와요.</p>
            <p className="mt-2 text-[13px] text-ink3">
              현장에 바로 쓰는 글로 찾아뵐게요. 그동안 자주 묻는 질문에서 인파를 먼저 살펴보세요.
            </p>
            <Link
              href="/faq"
              className="mt-5 inline-flex rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] font-semibold text-brand transition hover:border-brand"
            >
              자주 묻는 질문 보기
            </Link>
          </div>
        ) : (
          <>
            <div className="mt-8 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {posts.map((p) => (
                <PostCard key={p.id} post={p} />
              ))}
            </div>

            {(hasPrev || hasNext) && (
              <div className="mt-10 flex items-center justify-center gap-3">
                {hasPrev ? (
                  <Link
                    href={pageHref(page - 1)}
                    className="rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] font-semibold text-ink2 transition hover:border-brand hover:text-brand"
                  >
                    ← 이전
                  </Link>
                ) : (
                  <span className="rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] font-semibold text-muted opacity-50">
                    ← 이전
                  </span>
                )}
                <span className="text-[13px] font-semibold text-ink3">{page}쪽</span>
                {hasNext ? (
                  <Link
                    href={pageHref(page + 1)}
                    className="rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] font-semibold text-ink2 transition hover:border-brand hover:text-brand"
                  >
                    다음 →
                  </Link>
                ) : (
                  <span className="rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] font-semibold text-muted opacity-50">
                    다음 →
                  </span>
                )}
              </div>
            )}
          </>
        )}

        {/* 하단 링크 */}
        <nav className="mt-14 flex flex-wrap justify-center gap-x-5 gap-y-2 text-[13px] text-ink3">
          <Link href="/" className="transition hover:text-ink">홈</Link>
          <Link href="/faq" className="transition hover:text-ink">자주 묻는 질문</Link>
          <Link href="/legal/terms" className="transition hover:text-ink">이용약관</Link>
          <Link href="/legal/privacy" className="transition hover:text-ink">개인정보처리방침</Link>
        </nav>
      </main>
    </div>
  );
}
