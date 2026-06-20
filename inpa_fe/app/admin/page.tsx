"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useAdminGuard } from "@/lib/useAdminGuard";
import { adminGetStats, type AdminDashboardStats } from "@/lib/adminApi";
import { Card } from "@/components/ui";

function fmt(n: number): string {
  return new Intl.NumberFormat("ko-KR").format(n);
}

export default function AdminDashboardPage() {
  const ready = useAdminGuard();
  const [stats, setStats] = useState<AdminDashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    setLoading(true);
    adminGetStats()
      .then((s) => { setStats(s); setError(null); })
      .catch(() => setError("통계를 불러오지 못했어요."))
      .finally(() => setLoading(false));
  }, [ready]);

  if (!ready) return null;

  const todayCards = [
    { label: "신규 가입 설계사", value: stats?.today_new_users, unit: "명" },
    { label: "신규 판촉물 주문", value: stats?.today_new_orders, unit: "건" },
    { label: "미처리 문의",      value: stats?.open_inquiries,   unit: "건" },
    { label: "신규 신고",        value: stats?.pending_reports,  unit: "건" },
  ];

  const totalCards = [
    { label: "전체 설계사",  value: stats?.total_users,     unit: "명" },
    { label: "전체 고객(읽기 전용)", value: stats?.total_customers, unit: "명" },
  ];

  const dist = stats?.plan_distribution ?? {};
  const distTotal = Object.values(dist).reduce((a, b) => a + b, 0);

  const alerts = [
    {
      count: stats?.pending_orders ?? 0,
      label: "판촉물 주문",
      suffix: "건 대기 중",
      href: "/admin/orders",
      linkLabel: "주문 처리",
    },
    {
      count: stats?.open_inquiries ?? 0,
      label: "1:1 문의",
      suffix: "건 미응답",
      href: "/admin/inquiries",
      linkLabel: "문의 보기",
    },
    {
      count: stats?.pending_reports ?? 0,
      label: "신고",
      suffix: "건 검토 대기",
      href: "/admin/board",
      linkLabel: "신고 처리",
    },
    {
      count: stats?.unresolved_unmatched ?? 0,
      label: "정규화 매핑",
      suffix: "건 대기",
      href: "/admin/normalization",
      linkLabel: "매핑 큐",
    },
  ];

  return (
    <div className="p-6">
      <h1 className="text-[22px] font-extrabold text-ink mb-6">대시보드</h1>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700 flex items-center justify-between">
          <span>{error}</span>
          <button
            onClick={() => {
              setLoading(true);
              adminGetStats()
                .then((s) => { setStats(s); setError(null); })
                .catch(() => setError("통계를 불러오지 못했어요."))
                .finally(() => setLoading(false));
            }}
            className="ml-3 font-semibold underline shrink-0"
          >
            재시도
          </button>
        </div>
      )}

      {loading && (
        <div className="text-[14px] text-ink3">불러오는 중...</div>
      )}

      {!loading && stats && (
        <>
          {/* 오늘 현황 */}
          <section className="mb-6">
            <h2 className="text-[14px] font-bold text-ink3 mb-3">오늘 현황</h2>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {todayCards.map((c) => (
                <Card key={c.label} className="px-4 py-3.5">
                  <div className="text-[12px] text-ink3">{c.label}</div>
                  <div className="mt-1 flex items-baseline gap-1">
                    <span className="text-[26px] font-extrabold tnum text-ink">
                      {c.value !== undefined ? fmt(c.value) : "—"}
                    </span>
                    <span className="text-[13px] text-ink3">{c.unit}</span>
                  </div>
                </Card>
              ))}
            </div>
          </section>

          {/* 누적 지표 */}
          <section className="mb-6">
            <h2 className="text-[14px] font-bold text-ink3 mb-3">누적 지표</h2>
            <div className="grid grid-cols-2 gap-3">
              {totalCards.map((c) => (
                <Card key={c.label} className="px-4 py-3.5">
                  <div className="text-[12px] text-ink3">{c.label}</div>
                  <div className="mt-1 flex items-baseline gap-1">
                    <span className="text-[26px] font-extrabold tnum text-ink">
                      {c.value !== undefined ? fmt(c.value) : "—"}
                    </span>
                    <span className="text-[13px] text-ink3">{c.unit}</span>
                  </div>
                </Card>
              ))}
            </div>
          </section>

          {/* 요금제 분포 */}
          <section className="mb-6">
            <h2 className="text-[14px] font-bold text-ink3 mb-3">요금제 분포</h2>
            <Card className="p-4">
              {distTotal === 0 ? (
                <p className="text-[13px] text-ink3">데이터 없음</p>
              ) : (
                <div className="space-y-2">
                  {Object.entries(dist).map(([plan, count]) => {
                    const pct = distTotal > 0 ? Math.round((count / distTotal) * 100) : 0;
                    return (
                      <div key={plan}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[13px] font-semibold text-ink">{plan}</span>
                          <span className="text-[13px] tnum text-ink3">
                            {fmt(count)}명 ({pct}%)
                          </span>
                        </div>
                        <div className="h-2 rounded-full bg-surface2 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-brand"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
          </section>

          {/* 미처리 항목 빠른 접근 */}
          <section>
            <h2 className="text-[14px] font-bold text-ink3 mb-3">미처리 항목</h2>
            <Card className="divide-y divide-line">
              {alerts.map((a) => (
                <div key={a.href} className="flex items-center justify-between px-4 py-3.5">
                  <div className="flex items-center gap-2">
                    {a.count > 0 && (
                      <span className="w-2 h-2 rounded-full bg-warning shrink-0" />
                    )}
                    <span className="text-[14px] text-ink">
                      {a.label}{" "}
                      <span className="font-bold tnum text-ink">{fmt(a.count)}</span>
                      {a.suffix}
                    </span>
                  </div>
                  <Link
                    href={a.href}
                    className="text-[13px] font-semibold text-brand hover:underline"
                  >
                    {a.linkLabel} →
                  </Link>
                </div>
              ))}
            </Card>
          </section>
        </>
      )}
    </div>
  );
}
