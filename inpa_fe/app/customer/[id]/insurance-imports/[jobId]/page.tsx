"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { AppNav } from "@/components/app-nav";
import {
  InsuranceReviewWorkspace,
  parseInsuranceReviewRouteParams,
} from "@/components/insurance-review-workspace";
import { useAuthGuard } from "@/lib/useAuthGuard";

export default function InsuranceImportReviewPage() {
  const ready = useAuthGuard();
  const params = useParams<{ id: string; jobId: string }>();
  const route = parseInsuranceReviewRouteParams(params);

  if (!ready) {
    return (
      <div className="min-h-dvh">
        <AppNav active="customers" />
        <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6">
          <div className="h-24 animate-pulse rounded-2xl bg-line" aria-label="증권 확인 화면 불러오는 중" />
        </main>
      </div>
    );
  }

  if (!route) {
    return (
      <div className="min-h-dvh">
        <AppNav active="customers" />
        <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6">
          <section role="alert" className="rounded-2xl border border-line bg-surface p-6 shadow-card">
            <h1 className="text-xl font-bold text-ink">증권 확인 화면을 다시 선택해 주세요</h1>
            <p className="mt-2 text-sm leading-6 text-ink2">고객 목록에서 확인할 증권을 선택하면 이어서 볼 수 있어요.</p>
            <Link href="/customers" className="mt-4 inline-flex rounded-xl bg-brand px-4 py-2.5 text-sm font-bold text-white">고객 목록으로 이동</Link>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-dvh bg-canvas">
      <AppNav active="customers" />
      <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6">
        <InsuranceReviewWorkspace
          key={`${route.customerId}:${route.jobId}`}
          customerId={route.customerId}
          jobId={route.jobId}
        />
      </main>
    </div>
  );
}
