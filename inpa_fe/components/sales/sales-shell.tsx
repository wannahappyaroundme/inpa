"use client";

import {
  CalendarDays,
  ChevronRight,
  MessageSquareText,
  Phone,
  UserPlus,
  Users,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { AppNav } from "@/components/app-nav";
import { RecruitingWorkspace } from "@/components/recruiting/recruiting-shell";
import { Card } from "@/components/ui";
import { getProfile } from "@/lib/api";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  buildRecruitingSalesHref,
  resolveSalesTab,
  type SalesTab,
} from "./sales-view-model";

const SALES_TABS: Array<{ key: SalesTab; label: string; description: string; icon: LucideIcon }> = [
  {
    key: "customers",
    label: "고객 영업",
    description: "보험 가입 고객의 연락과 상담",
    icon: Users,
  },
  {
    key: "recruiting",
    label: "설계사 영업",
    description: "후배 설계사의 영입과 정착",
    icon: UserPlus,
  },
];

const CUSTOMER_ACTIONS: Array<{
  href: string;
  title: string;
  description: string;
  action: string;
  icon: LucideIcon;
}> = [
  {
    href: "/customers",
    title: "고객 흐름 관리",
    description: "DB, TA, FA, 청약 단계별로 고객과 다음 행동을 확인해요.",
    action: "고객 보기",
    icon: Users,
  },
  {
    href: "/call-list",
    title: "오늘 연락할 고객",
    description: "생일, 만기, 연락 공백을 기준으로 먼저 연락할 고객을 모아 봐요.",
    action: "연락 순서 보기",
    icon: Phone,
  },
  {
    href: "/scripts",
    title: "상담 화법 준비",
    description: "상황에 맞는 질문과 설명 흐름을 골라 상담 전에 정리해요.",
    action: "화법 고르기",
    icon: MessageSquareText,
  },
  {
    href: "/schedule",
    title: "다음 약속 관리",
    description: "고객 미팅과 후속 일정을 한곳에서 이어서 관리해요.",
    action: "일정 보기",
    icon: CalendarDays,
  },
];

export function SalesLoading() {
  return (
    <div role="status" aria-live="polite" className="mx-auto min-h-dvh max-w-[1440px] space-y-4 px-4 py-6 sm:px-6 sm:py-8">
      <span className="sr-only">영업 화면을 불러오는 중이에요.</span>
      <div aria-hidden="true" className="h-8 w-20 animate-pulse rounded-lg bg-line" />
      <div aria-hidden="true" className="h-16 w-full animate-pulse rounded-2xl bg-line" />
      <div aria-hidden="true" className="grid gap-3 sm:grid-cols-2">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className="h-44 animate-pulse rounded-2xl bg-surface2" />
        ))}
      </div>
    </div>
  );
}

function CustomerSalesWorkspace() {
  return (
    <section aria-labelledby="customer-sales-title">
      <div className="rounded-3xl border border-[#cfdbff] bg-[linear-gradient(135deg,#f8faff_0%,#eef3ff_100%)] px-5 py-6 sm:px-7 sm:py-8">
        <p className="text-[12px] font-bold text-brand">보험 가입 고객 영업</p>
        <h2 id="customer-sales-title" className="mt-1 text-[22px] font-extrabold tracking-tight text-brand-ink sm:text-[26px]">
          고객과의 다음 행동을 바로 이어가세요
        </h2>
        <p className="mt-2 max-w-2xl break-keep text-[13px] leading-6 text-ink3 sm:text-[14px]">
          고객 등록부터 연락, 상담 준비, 다음 약속까지 기존 인파 기능을 영업 흐름에 맞춰 모았습니다.
        </p>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        {CUSTOMER_ACTIONS.map((item) => {
          const Icon = item.icon;
          return (
            <Card key={item.href} className="group p-5 transition hover:-translate-y-0.5 hover:border-brand/30 hover:shadow-md">
              <Link href={item.href} className="block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-4">
                <span className="flex size-11 items-center justify-center rounded-2xl bg-brand-soft text-brand">
                  <Icon size={20} strokeWidth={2} aria-hidden />
                </span>
                <h3 className="mt-4 text-[16px] font-extrabold text-ink">{item.title}</h3>
                <p className="mt-1 min-h-10 break-keep text-[12px] leading-5 text-ink3">{item.description}</p>
                <span className="mt-4 inline-flex items-center gap-1 text-[13px] font-bold text-brand">
                  {item.action}
                  <ChevronRight size={15} aria-hidden className="transition group-hover:translate-x-0.5" />
                </span>
              </Link>
            </Card>
          );
        })}
      </div>
    </section>
  );
}

function SalesAccessError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="min-h-dvh overflow-x-clip">
      <AppNav active="sales" />
      <main className="mx-auto max-w-[720px] px-4 py-12 sm:px-6 sm:py-16">
        <Card className="p-6 text-center sm:p-8">
          <h1 className="text-[20px] font-extrabold text-ink">영업 화면을 다시 연결해 주세요</h1>
          <p className="mt-2 break-keep text-[13px] leading-6 text-ink3">
            연결을 확인하고 다시 불러오면 고객 영업과 설계사 영업을 이어갈 수 있어요.
          </p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-5 inline-flex min-h-11 items-center justify-center rounded-xl bg-brand px-5 text-[13px] font-bold text-white transition active:scale-[0.98]"
          >
            다시 불러오기
          </button>
        </Card>
      </main>
    </div>
  );
}

export function SalesShell() {
  const ready = useAuthGuard({ requireOnboarding: true });
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  const [recruitingEnabled, setRecruitingEnabled] = useState<boolean | null>(null);
  const [profileLoadFailed, setProfileLoadFailed] = useState(false);
  const profileRequestId = useRef(0);
  const tabRefs = useRef<Partial<Record<SalesTab, HTMLAnchorElement | null>>>({});

  const loadRecruitingAccess = useCallback(() => {
    const requestId = profileRequestId.current + 1;
    profileRequestId.current = requestId;
    setRecruitingEnabled(null);
    setProfileLoadFailed(false);
    getProfile()
      .then((profile) => {
        if (profileRequestId.current === requestId) {
          setRecruitingEnabled(profile.recruiting_enabled);
        }
      })
      .catch(() => {
        if (profileRequestId.current === requestId) {
          setProfileLoadFailed(true);
        }
      });
  }, []);

  useEffect(() => {
    if (!ready) return undefined;
    loadRecruitingAccess();
    return () => {
      profileRequestId.current += 1;
    };
  }, [loadRecruitingAccess, ready]);

  const tab = resolveSalesTab(rawTab, recruitingEnabled === true);

  useEffect(() => {
    if (!ready || recruitingEnabled === null) return;
    if (rawTab !== tab) {
      router.replace(`/sales?tab=${tab}`, { scroll: false });
    }
  }, [rawTab, ready, recruitingEnabled, router, tab]);

  if (profileLoadFailed) return <SalesAccessError onRetry={loadRecruitingAccess} />;
  if (!ready || recruitingEnabled === null) return <SalesLoading />;

  const visibleTabs = recruitingEnabled
    ? SALES_TABS
    : SALES_TABS.filter((item) => item.key === "customers");

  const handleTabKeyDown = (event: KeyboardEvent<HTMLAnchorElement>) => {
    const currentTab = event.currentTarget.dataset.salesTab as SalesTab | undefined;
    if (!currentTab) return;

    const currentIndex = visibleTabs.findIndex((item) => item.key === currentTab);
    const lastIndex = visibleTabs.length - 1;
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = currentIndex === lastIndex ? 0 : currentIndex + 1;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = currentIndex === 0 ? lastIndex : currentIndex - 1;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = lastIndex;
    const handledKeys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"];
    if (!handledKeys.includes(event.key)) return;
    event.preventDefault();
    if (nextIndex === currentIndex) return;

    const nextTab = visibleTabs[nextIndex].key;
    tabRefs.current[nextTab]?.focus();
    router.push(`/sales?tab=${nextTab}`, { scroll: false });
  };

  return (
    <div className="min-h-dvh overflow-x-clip">
      <AppNav active="sales" />
      <main className="mx-auto min-w-0 max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8">
        <div>
          <p className="text-[12px] font-bold text-brand">두 가지 영업, 서로 섞이지 않게</p>
          <h1 className="mt-1 text-[24px] font-extrabold tracking-tight text-ink sm:text-[28px]">영업</h1>
          <p className="mt-2 text-[13px] leading-5 text-ink3">
            보험 가입 고객과 함께할 설계사를 각각의 흐름으로 관리하세요.
          </p>
        </div>

        <nav role="tablist" aria-label="영업 종류" className="mt-5 grid gap-2 rounded-2xl border border-line bg-surface p-1.5 shadow-card sm:grid-cols-2">
          {visibleTabs.map((item) => {
            const Icon = item.icon;
            const active = item.key === tab;
            return (
              <Link
                key={item.key}
                href={`/sales?tab=${item.key}`}
                ref={(element) => { tabRefs.current[item.key] = element; }}
                data-sales-tab={item.key}
                id={`sales-tab-${item.key}`}
                role="tab"
                aria-selected={active}
                aria-controls={`sales-panel-${item.key}`}
                tabIndex={active ? 0 : -1}
                onKeyDown={handleTabKeyDown}
                className={`flex min-h-16 items-center gap-3 rounded-xl px-4 py-3 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
                  active ? "bg-brand text-white" : "text-ink2 hover:bg-surface2"
                }`}
              >
                <Icon size={20} strokeWidth={2} aria-hidden />
                <span>
                  <span className="block text-[14px] font-extrabold">{item.label}</span>
                  <span className={`mt-0.5 block text-[11px] ${active ? "text-white/80" : "text-ink3"}`}>
                    {item.description}
                  </span>
                </span>
              </Link>
            );
          })}
        </nav>

        {visibleTabs.map((item) => {
          const active = item.key === tab;
          return (
            <div
              key={item.key}
              id={`sales-panel-${item.key}`}
              role="tabpanel"
              aria-labelledby={`sales-tab-${item.key}`}
              hidden={!active}
              tabIndex={active ? 0 : -1}
              className="mt-5 min-w-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-4"
            >
              {active && item.key === "customers" && <CustomerSalesWorkspace />}
              {active && item.key === "recruiting" && (
                <RecruitingWorkspace
                  queryKey="view"
                  hrefForTab={buildRecruitingSalesHref}
                  showHeading={false}
                />
              )}
            </div>
          );
        })}
      </main>
    </div>
  );
}
