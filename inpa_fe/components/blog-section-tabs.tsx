import Link from "next/link";

const BLOG_SECTIONS = [
  { key: "blog", href: "/blog", label: "인파 블로그" },
  { key: "resources", href: "/blog/resources", label: "무료 자료" },
] as const;

export type BlogSection = (typeof BLOG_SECTIONS)[number]["key"];

export function BlogSectionTabs({ activeSection }: { activeSection: BlogSection }) {
  return (
    <nav
      aria-label="인파 블로그 메뉴"
      className="mt-8 grid w-full max-w-sm grid-cols-2 rounded-2xl border border-line bg-surface2 p-1.5"
    >
      {BLOG_SECTIONS.map((section) => {
        const active = activeSection === section.key;
        return (
          <Link
            key={section.key}
            href={section.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-[44px] items-center justify-center rounded-xl px-4 py-2 text-[14px] font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
              active
                ? "bg-brand text-white shadow-sm"
                : "text-ink2 hover:bg-surface hover:text-brand-ink"
            }`}
          >
            {section.label}
          </Link>
        );
      })}
    </nav>
  );
}
