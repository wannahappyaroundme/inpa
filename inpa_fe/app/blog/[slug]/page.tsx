import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import { InpaMark } from "@/components/inpa-logo";
import { BlogMarkdown } from "@/components/blog-markdown";
import { JsonLd, blogPosting, ORGANIZATION } from "@/components/structured-data";
import { getBlogPost, ApiError, type BlogDetail } from "@/lib/api";

// 블로그 상세 — 서버 컴포넌트, 라이트 고정(§6 테마 가드).
// ★ force-dynamic: 요청 시점 렌더 → 빌드가 BE 를 부르지 않고, 조회수(view_count)는 BE 가 매 조회 증가.
export const dynamic = "force-dynamic";

// generateMetadata 와 페이지가 같은 slug 를 두 번 부르지 않도록 요청 범위 메모(React cache).
// 404 는 null 로 흡수(→ notFound), 그 외 오류는 그대로 던진다(일시 장애 = 500, 오탐 404 방지).
// ★ Next 16 은 한글 등 비ASCII 라우트 파라미터를 '인코딩된 상태'로 넘긴다(예: '보험'→'%EB..').
//   getBlogPost 이 다시 encodeURIComponent 하므로 그대로 쓰면 이중 인코딩 → BE 404.
//   여기서 한 번 디코드해 넘긴다(ASCII 슬러그엔 % 가 없어 무해, 잘못된 % 는 원본 유지).
function decodeSlug(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

const loadPost = cache(async (slug: string): Promise<BlogDetail | null> => {
  try {
    return await getBlogPost(decodeSlug(slug));
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
});

function fmtDate(d: string | null): string {
  if (!d) return "";
  // 서버 렌더(Vercel=UTC)에서도 KST 기준 날짜로 — 자정 근처 하루 밀림 방지(store UTC/display KST).
  return new Date(d).toLocaleDateString("ko-KR", {
    year: "numeric", month: "long", day: "numeric", timeZone: "Asia/Seoul",
  });
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const post = await loadPost(slug);
  if (!post) {
    return { title: "찾을 수 없는 글", robots: { index: false, follow: false } };
  }
  const title = post.seo_title || post.title;
  const description = post.seo_description || post.excerpt || "";
  const image = post.cover_image || "/opengraph-image.jpg";
  return {
    title,
    description,
    alternates: { canonical: `/blog/${post.slug}` },
    // is_noindex(안전밸브)면 색인 차단. §7 트랩: openGraph 이미지 명시(부모 파일컨벤션 미상속).
    robots: post.is_noindex ? { index: false, follow: false } : undefined,
    openGraph: {
      type: "article",
      locale: "ko_KR",
      siteName: "인파(Inpa)",
      title,
      description,
      url: `/blog/${post.slug}`,
      images: [{ url: image, width: 1200, height: 630 }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [image],
    },
  };
}

export default async function BlogPostPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const post = await loadPost(slug);
  if (!post) notFound();

  const isSafety = post.category === "safety";

  return (
    <div className="min-h-screen bg-canvas text-ink">
      {/* ★ ORGANIZATION 을 함께 실어야 blogPosting 의 publisher/author @id(#organization)가 해석됨
          (랜딩에만 있으면 상세 페이지에서 dangling → 리치결과 publisher.name/logo 누락). */}
      <JsonLd
        data={[
          ORGANIZATION,
          blogPosting({
            title: post.title,
            slug: post.slug,
            excerpt: post.excerpt,
            seo_description: post.seo_description,
            cover_image: post.cover_image,
            published_at: post.published_at,
            updated_at: post.updated_at,
            author_name: post.author_name,
          }),
        ]}
      />

      {/* 헤더 */}
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4 sm:px-6">
          <Link href="/blog" className="flex items-center gap-2" aria-label="블로그 목록으로">
            <InpaMark size={26} />
            <span className="text-[15px] font-extrabold text-brand-ink">블로그</span>
          </Link>
          <Link
            href="/register"
            className="flex min-h-[44px] items-center rounded-xl bg-brand px-4 py-2 text-[14px] font-semibold text-white transition hover:opacity-90"
          >
            무료로 시작하기
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-14">
        <article>
          {/* 카테고리 + 제목 + 바이라인(E-E-A-T) */}
          <Link
            href={`/blog?category=${post.category}`}
            className="inline-flex rounded-full bg-accent-tint px-3 py-1 text-[12px] font-bold text-brand transition hover:opacity-80"
          >
            {post.category_label}
          </Link>
          <h1 className="mt-4 text-[28px] font-extrabold leading-tight tracking-tight text-brand-ink sm:text-[36px]">
            {post.title}
          </h1>
          <div className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-ink3">
            <span className="font-semibold text-ink2">{post.author_name}</span>
            {post.published_at && (
              <>
                <span aria-hidden>·</span>
                <time dateTime={post.published_at}>{fmtDate(post.published_at)}</time>
              </>
            )}
          </div>

          {/* 커버 */}
          {post.cover_image && (
            <div className="mt-7 overflow-hidden rounded-2xl border border-line">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={post.cover_image} alt="" className="w-full object-cover" />
            </div>
          )}

          {/* 요약(있으면 리드 문단으로) */}
          {post.excerpt && (
            <p className="mt-7 text-[16px] font-medium leading-8 text-ink2">{post.excerpt}</p>
          )}

          {/* 본문 — 공개/어드민 미리보기 공용 렌더러 */}
          <div className="mt-6">
            <BlogMarkdown body={post.body} />
          </div>

          {/* 태그 */}
          {post.tags.length > 0 && (
            <div className="mt-9 flex flex-wrap gap-2">
              {post.tags.map((t) => (
                <span key={t} className="rounded-full bg-surface2 px-2.5 py-1 text-[12px] text-ink3">
                  #{t}
                </span>
              ))}
            </div>
          )}

          {/* 안심 가이드(규정) 글에만 붙는 추가 안내 한 줄 */}
          {isSafety && (
            <p className="mt-8 rounded-xl border border-line bg-surface2 px-4 py-3 text-[12px] leading-6 text-ink3">
              이 글은 일반적인 정보를 정리한 참고 자료예요. 법률 자문이 아니며, 실제 적용은 소속사 컴플라이언스와 금융감독원 안내를 함께 확인해 주세요.
            </p>
          )}

          {/* 정직성 한 줄(§6) */}
          <p className="mt-8 border-t border-line pt-6 text-[12px] leading-6 text-muted">
            인파는 보험을 중개·권유하지 않는 분석·정리 소프트웨어입니다. 보장 판단과 고객 안내는 설계사님의 업무입니다.
          </p>
        </article>

        {/* fit-framing CTA */}
        <div className="mt-10 rounded-2xl border border-line bg-surface p-6 text-center shadow-card sm:p-8">
          <p className="text-[16px] font-bold text-brand-ink">내 영업에 맞을지, 먼저 확인해보세요.</p>
          <p className="mt-1.5 text-[13px] text-ink3">지금은 증권 한 장이면 모든 기능을 무료로 써볼 수 있어요.</p>
          <Link
            href="/register"
            className="mt-5 inline-flex min-h-[50px] items-center justify-center rounded-2xl bg-brand px-7 py-3.5 text-[15px] font-bold text-white transition hover:opacity-90"
          >
            무료로 먼저 확인해보기
          </Link>
        </div>

        {/* 관련 링크 */}
        <nav className="mt-10 flex flex-wrap justify-center gap-x-5 gap-y-2 text-[13px] text-ink3">
          <Link href="/blog" className="transition hover:text-ink">← 블로그 목록</Link>
          <Link href="/faq" className="transition hover:text-ink">자주 묻는 질문</Link>
          <Link href="/" className="transition hover:text-ink">홈</Link>
          <Link href="/legal/terms" className="transition hover:text-ink">이용약관</Link>
          <Link href="/legal/privacy" className="transition hover:text-ink">개인정보처리방침</Link>
        </nav>
      </main>
    </div>
  );
}
