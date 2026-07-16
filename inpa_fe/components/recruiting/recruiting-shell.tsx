"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { AppNav } from "@/components/app-nav";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { CampaignPanel } from "./campaign-panel";
import { PageEditor } from "./page-editor";
import { RecruitingLoading } from "./recruiting-states";
import { SettlementPanel } from "./settlement-panel";
import { StatusPanel } from "./status-panel";
import { normalizeRecruitingTab, type RecruitingTab } from "./recruiting-view-model";

const TABS: Array<{ key: RecruitingTab; label: string; hint: string }> = [
  { key: "status", label: "영입 현황", hint: "지원 흐름과 다음 연락" },
  { key: "page", label: "나의 영입 페이지", hint: "지원자가 보는 소개" },
  { key: "campaign", label: "캠페인 링크", hint: "개인 소개 링크" },
  { key: "settlement", label: "정착 지원", hint: "합류 뒤 확인 일정" },
];

export function RecruitingShell() {
  const ready = useAuthGuard({ requireOnboarding: true });
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  const tab = normalizeRecruitingTab(rawTab);

  useEffect(() => {
    if (rawTab !== tab) router.replace(`/recruiting?tab=${tab}`, { scroll: false });
  }, [rawTab, router, tab]);

  if (!ready) return <RecruitingLoading fullPage />;

  return (
    <div className="min-h-dvh overflow-x-clip">
      <AppNav />
      <main className="mx-auto min-w-0 max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-[12px] font-bold text-brand">함께 오래 성장할 동료 찾기</p>
            <h1 className="mt-1 text-[24px] font-extrabold tracking-tight text-ink sm:text-[28px]">
              설계사 영입
            </h1>
            <p className="mt-2 text-[13px] leading-5 text-ink3">
              보험가입 고객과 별도로 관리됩니다.
            </p>
          </div>
        </div>

        <nav
          aria-label="설계사 영입 메뉴"
          className="scrollbar-none mt-5 flex max-w-full gap-2 overflow-x-auto rounded-2xl border border-line bg-surface p-1.5 shadow-card"
        >
          {TABS.map((item) => {
            const active = item.key === tab;
            return (
              <Link
                key={item.key}
                href={`/recruiting?tab=${item.key}`}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-11 min-w-[132px] flex-1 flex-col justify-center rounded-xl px-3 py-2 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
                  active
                    ? "bg-brand text-white"
                    : "bg-surface text-ink2 hover:bg-surface2"
                }`}
              >
                <span className="text-[13px] font-bold">{item.label}</span>
                <span className={`mt-0.5 text-[10px] ${active ? "text-white/80" : "text-ink3"}`}>
                  {item.hint}
                </span>
              </Link>
            );
          })}
        </nav>

        <section className="mt-5 min-w-0" aria-label={TABS.find((item) => item.key === tab)?.label}>
          {tab === "status" && <StatusPanel />}
          {tab === "page" && <PageEditor />}
          {tab === "campaign" && <CampaignPanel onMoveToPage={() => router.replace("/recruiting?tab=page")} />}
          {tab === "settlement" && <SettlementPanel />}
        </section>
      </main>
    </div>
  );
}
