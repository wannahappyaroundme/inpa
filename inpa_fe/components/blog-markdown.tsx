// 인파 노트 본문 마크다운 렌더러 — 공개 상세(app/blog/[slug], 서버)와 어드민 에디터
// 미리보기(app/admin/blog, 클라이언트)가 '같은 컴포넌트'를 쓴다(렌더 단일 소스 = 미리보기 = 실제).
//
// ★ 보안: react-markdown 기본값(rehype-raw 미사용) → 원본 HTML 주입 차단(XSS 안전).
//   remark-gfm 로 표·체크리스트·취소선만 확장한다.
// ★ 테마: 토큰 유틸(text-ink/…)만 사용 → 서비스(라이트 고정)와 어드민(.theme-system 다크)
//   두 문맥에서 자동으로 올바른 색이 된다. dark: 변형을 쓰지 않는다(§6 테마 가드레일 준수).
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

const components: Components = {
  h1: ({ children }) => (
    <h1 className="mt-8 mb-3 text-[24px] font-extrabold text-ink leading-snug tracking-tight">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-9 mb-3 text-[20px] font-bold text-ink leading-snug border-l-4 border-brand pl-3">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-7 mb-2 text-[17px] font-bold text-ink leading-snug">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="mt-5 mb-2 text-[15px] font-bold text-ink2">{children}</h4>
  ),
  p: ({ children }) => (
    <p className="my-4 text-[15px] leading-8 text-ink2">{children}</p>
  ),
  a: ({ children, href }) => {
    const external = !!href && /^https?:\/\//.test(href);
    return (
      <a
        href={href}
        className="text-brand font-medium underline underline-offset-2 hover:opacity-80 transition break-words"
        {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      >
        {children}
      </a>
    );
  },
  strong: ({ children }) => <strong className="font-bold text-ink">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => (
    <ul className="my-4 pl-5 list-disc marker:text-brand space-y-1.5 text-[15px] leading-7 text-ink2">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="my-4 pl-5 list-decimal marker:text-ink3 space-y-1.5 text-[15px] leading-7 text-ink2">{children}</ol>
  ),
  li: ({ children }) => <li className="pl-1">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="my-5 rounded-r-xl border-l-4 border-brand bg-accent-tint px-4 py-2.5 text-[15px] leading-7 text-ink2">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-8 border-t border-line" />,
  img: ({ src, alt }) =>
    // eslint-disable-next-line @next/next/no-img-element
    typeof src === "string" ? (
      <img src={src} alt={alt ?? ""} className="my-5 rounded-xl max-w-full h-auto border border-line" loading="lazy" />
    ) : null,
  code: ({ children, className }) => {
    // 인라인 코드(className 없음) vs 코드블록(언어 클래스 있음, pre 안에서 렌더).
    const isBlock = !!className;
    if (isBlock) {
      return <code className={`${className ?? ""} text-[13px] leading-6`}>{children}</code>;
    }
    return (
      <code className="rounded-md bg-surface2 border border-line px-1.5 py-0.5 text-[13px] font-mono text-ink">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="my-5 overflow-x-auto rounded-xl bg-surface2 border border-line p-4 text-ink font-mono">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="my-5 overflow-x-auto rounded-xl border border-line">
      <table className="w-full border-collapse text-[14px] text-ink2">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-surface2">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b border-line px-3 py-2 text-left font-bold text-ink whitespace-nowrap">{children}</th>
  ),
  td: ({ children }) => <td className="border-b border-line px-3 py-2 align-top">{children}</td>,
};

export function BlogMarkdown({ body }: { body: string }) {
  return (
    <div className="blog-body">
      <Markdown remarkPlugins={[remarkGfm]} components={components}>
        {body}
      </Markdown>
    </div>
  );
}
