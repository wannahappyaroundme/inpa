"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { listCustomers, type CustomerListItem } from "@/lib/api";
import { CustomerCreateModal } from "@/components/customer-create-modal";

// 고객 관리(CRM). 목록·검색·만기배지. 실 API 연결. 데스크톱 2열 반응형.
export default function CustomersPage() {
  const ready = useAuthGuard();

  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const fetchCustomers = useCallback(
    async (q: string) => {
      setLoading(true);
      setError(null);
      try {
        const res = await listCustomers({ search: q || undefined });
        setCustomers(res.results);
        setTotalCount(res.count);
      } catch {
        setError("고객 목록을 불러오지 못했어요. 잠시 후 다시 시도하세요.");
        setCustomers([]);
        setTotalCount(0);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    if (!ready) return;
    fetchCustomers("");
  }, [ready, fetchCustomers]);

  // 검색: 300ms 디바운스
  useEffect(() => {
    if (!ready) return;
    const id = setTimeout(() => fetchCustomers(search), 300);
    return () => clearTimeout(id);
  }, [search, ready, fetchCustomers]);

  if (!ready) return null;

  // 나이 계산 (birth_day: "YYYY-MM-DD")
  function calcAge(birthDay: string | null): string {
    if (!birthDay) return "—";
    const birth = new Date(birthDay);
    const today = new Date();
    let age = today.getFullYear() - birth.getFullYear();
    const m = today.getMonth() - birth.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--;
    return `${age}세`;
  }

  // 성별 한글 표기
  function genderLabel(g: string | null): string {
    if (g === "M") return "남";
    if (g === "F") return "여";
    return "";
  }

  // 만기 임박 여부: consent_overseas_at이 있고 공유 만료일이 30일 이내인 경우
  // (BE share_expires_at 없는 List 시리얼라이저이므로 tags 중 만기 태그로 graceful 처리)
  // → 현재 List 응답에는 만기 정보가 없으므로 배지를 표시하지 않는 게 안전함.
  // 향후 BE가 days_until_expiry 등 필드를 추가하면 여기에 연결.

  return (
    <div className="min-h-dvh">
      <AppNav active="customers" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <div className="flex items-center justify-between">
          <h1 className="text-[22px] font-extrabold text-ink">
            고객{" "}
            <span className="text-ink3 tnum">
              {loading ? "..." : totalCount}
            </span>
          </h1>
          <button
            onClick={() => setShowCreate(true)}
            className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5 active:scale-[0.98] transition"
          >
            + 고객 등록
          </button>
        </div>

        <div className="mt-4">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="이름·연락처 검색"
            className="w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
          />
        </div>

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">
            {error}
          </div>
        )}

        {loading && !customers.length && (
          <div className="mt-8 text-center text-[14px] text-ink3">불러오는 중...</div>
        )}

        {!loading && !error && customers.length === 0 && (
          <div className="mt-8 text-center text-[14px] text-ink3">
            {search ? "검색 결과가 없어요." : "등록된 고객이 없어요. 첫 고객을 등록해 보세요."}
          </div>
        )}

        <div className="mt-4 grid sm:grid-cols-2 gap-3">
          {customers.map((c) => (
            <Card key={c.id} className="p-4 flex items-center gap-3">
              {/* 아바타 */}
              <div
                className="w-11 h-11 rounded-full flex items-center justify-center text-[16px] font-bold shrink-0 text-brand"
                style={{ backgroundColor: c.color ?? "var(--accent-tint)" }}
              >
                {c.name[0]}
              </div>

              {/* 정보 */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[16px] font-bold text-ink">{c.name}</span>
                  <span className="text-[12px] text-ink3">
                    {[calcAge(c.birth_day), genderLabel(c.gender)]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                  {/* 태그 배지 */}
                  {c.tags.slice(0, 2).map((tag) => (
                    <span
                      key={tag.id}
                      className="text-[11px] font-semibold rounded-full px-2 py-0.5"
                      style={{
                        backgroundColor: tag.color ? `${tag.color}20` : undefined,
                        color: tag.color ?? undefined,
                      }}
                    >
                      {tag.label}
                    </span>
                  ))}
                </div>
                <div className="text-[12px] text-ink3 mt-0.5">
                  {c.mobile_phone_number ?? "연락처 없음"}
                  {c.family_count > 0 && (
                    <span> · 가족 {c.family_count}명</span>
                  )}
                </div>
              </div>

              {/* 고객 상세(분석 탭) 링크 — 한 동선 IA */}
              <Link
                href={`/customer/${c.id}?tab=analysis`}
                className="text-[12px] font-semibold text-brand shrink-0"
              >
                분석 ›
              </Link>
            </Card>
          ))}
        </div>
      </main>

      {showCreate && (
        <CustomerCreateModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            fetchCustomers(search);
          }}
        />
      )}
    </div>
  );
}
