import { InpaMark } from "@/components/inpa-logo";

export default function BlogLoading() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl items-center px-4 py-4 sm:px-6">
          <InpaMark size={28} title="인파 블로그" />
        </div>
      </header>
      <main
        className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14"
        role="status"
        aria-label="블로그 글을 불러오고 있어요"
      >
        <div className="h-10 w-36 animate-pulse rounded-xl bg-surface2" />
        <div className="mt-4 h-5 w-full max-w-xl animate-pulse rounded-lg bg-surface2" />
        <div className="mt-10 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className="overflow-hidden rounded-2xl border border-line bg-surface">
              <div className="aspect-[16/9] animate-pulse bg-accent-tint" />
              <div className="space-y-3 p-5">
                <div className="h-5 w-20 animate-pulse rounded-full bg-surface2" />
                <div className="h-5 w-full animate-pulse rounded-lg bg-surface2" />
                <div className="h-4 w-4/5 animate-pulse rounded-lg bg-surface2" />
              </div>
            </div>
          ))}
        </div>
        <span className="sr-only">글 목록을 준비하고 있어요.</span>
      </main>
    </div>
  );
}
