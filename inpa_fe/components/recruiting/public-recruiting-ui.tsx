import Link from "next/link";
import type { ReactNode } from "react";

import type { RecruitingPlanner } from "../../lib/api";

export function PublicRecruitingFrame({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh overflow-x-hidden bg-surface2 text-ink">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex min-h-16 w-full max-w-3xl items-center px-4 sm:px-6">
          <Link
            href="/"
            className="inline-flex min-h-11 items-center rounded-xl text-[18px] font-extrabold text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            인파
          </Link>
          <span className="ml-2 text-[12px] font-semibold text-ink3">보험설계사 동료 지원</span>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6 sm:py-10">
        {children}
      </main>
    </div>
  );
}

export function PublicPlannerCard({ planner }: { planner: RecruitingPlanner }) {
  const subtitle = [planner.affiliation, planner.title].filter(Boolean).join(" · ");
  return (
    <section className="rounded-3xl border border-line bg-surface p-5 shadow-card sm:p-7">
      <div className="flex min-w-0 items-center gap-4">
        <div className="grid h-16 w-16 shrink-0 place-items-center overflow-hidden rounded-2xl bg-brand-soft text-[22px] font-extrabold text-brand">
          {planner.profile_image ? (
            <img src={planner.profile_image} alt="" className="h-full w-full object-cover" />
          ) : (
            <span aria-hidden="true">{planner.display_name.trim().slice(0, 1) || "인"}</span>
          )}
        </div>
        <div className="min-w-0">
          <p className="break-words text-[19px] font-extrabold text-ink">
            {planner.display_name}
          </p>
          {subtitle && <p className="mt-1 break-words text-[13px] text-ink3">{subtitle}</p>}
        </div>
      </div>
    </section>
  );
}

export function PublicRecruitingLoading({ label = "지원 화면을 불러오는 중이에요." }: { label?: string }) {
  return (
    <PublicRecruitingFrame>
      <div role="status" aria-live="polite" className="space-y-4">
        <span className="sr-only">{label}</span>
        <div aria-hidden="true" className="h-28 animate-pulse rounded-3xl border border-line bg-surface" />
        <div aria-hidden="true" className="h-24 animate-pulse rounded-3xl border border-line bg-surface" />
        <div aria-hidden="true" className="h-80 animate-pulse rounded-3xl border border-line bg-surface" />
      </div>
    </PublicRecruitingFrame>
  );
}

export function PublicRecruitingNotice({
  title,
  description,
  action,
  role,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  role?: "alert" | "status";
}) {
  return (
    <PublicRecruitingFrame>
      <section
        role={role}
        className="rounded-3xl border border-line bg-surface px-5 py-10 text-center shadow-card sm:px-8"
      >
        <h1 className="break-words text-[20px] font-extrabold text-ink">{title}</h1>
        <p className="mt-3 break-words text-[14px] leading-6 text-ink3">{description}</p>
        {action && <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row">{action}</div>}
      </section>
    </PublicRecruitingFrame>
  );
}

export const PUBLIC_PRIMARY_BUTTON =
  "inline-flex min-h-12 items-center justify-center rounded-2xl bg-brand px-5 py-3 text-[14px] font-bold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2";

export const PUBLIC_SECONDARY_BUTTON =
  "inline-flex min-h-12 items-center justify-center rounded-2xl border border-line bg-surface px-5 py-3 text-[14px] font-bold text-ink2 transition hover:bg-surface2 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2";
