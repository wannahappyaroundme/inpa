"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { listCustomers, updateCustomer, SALES_STAGES, type CustomerListItem, type SalesStage } from "@/lib/api";
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
  const [view, setView] = useState<"kanban" | "list">("kanban");
  const [dragId, setDragId] = useState<number | null>(null);
  const [moving, setMoving] = useState<Set<number>>(new Set());

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

  // 칸반 단계 이동 — 드래그/단계 select 공용. 낙관적 업데이트 후 실패 시 롤백.
  const moveCustomer = useCallback(
    async (id: number, to: SalesStage) => {
      let prevStage: SalesStage | undefined;
      setCustomers((prev) =>
        prev.map((c) => {
          if (c.id !== id) return c;
          prevStage = c.sales_stage;
          return { ...c, sales_stage: to };
        })
      );
      if (prevStage === undefined || prevStage === to) return;
      setMoving((m) => new Set(m).add(id));
      setError(null);
      try {
        await updateCustomer(id, { sales_stage: to });
      } catch {
        const back = prevStage;
        setCustomers((prev) => prev.map((c) => (c.id === id ? { ...c, sales_stage: back! } : c)));
        setError("단계 이동에 실패했어요. 잠시 후 다시 시도하세요.");
      } finally {
        setMoving((m) => {
          const n = new Set(m);
          n.delete(id);
          return n;
        });
      }
    },
    []
  );

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
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-[22px] font-extrabold text-ink">
            고객{" "}
            <span className="text-ink3 tnum">
              {loading ? "..." : totalCount}
            </span>
          </h1>
          <div className="flex items-center gap-2">
            {/* 보기 전환: 칸반(영업단계) / 리스트 */}
            <div className="inline-flex rounded-xl border border-line bg-surface2 p-0.5 text-[12px] font-semibold">
              {(["kanban", "list"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`px-3 py-1.5 rounded-[10px] transition ${
                    view === v ? "bg-surface text-brand shadow-sm" : "text-ink3"
                  }`}
                >
                  {v === "kanban" ? "칸반" : "리스트"}
                </button>
              ))}
            </div>
            <button
              onClick={() => setShowCreate(true)}
              className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5 active:scale-[0.98] transition"
            >
              + 고객 등록
            </button>
          </div>
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

        {/* ── 리스트 보기 ── */}
        {view === "list" && (
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
        )}

        {/* ── 칸반 보기 (영업 4단계) ── 데스크탑=드래그, 모바일=단계 select 폴백 ── */}
        {view === "kanban" && customers.length > 0 && (
          <>
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {SALES_STAGES.map((stage) => {
                const col = customers.filter((c) => c.sales_stage === stage.key);
                return (
                  <div
                    key={stage.key}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => {
                      if (dragId != null) moveCustomer(dragId, stage.key);
                      setDragId(null);
                    }}
                    className="rounded-2xl bg-surface2 border border-line p-2.5 min-h-[120px]"
                  >
                    <div className="flex items-center justify-between px-1 pb-2">
                      <span className="text-[13px] font-bold text-ink">
                        <span className="text-ink3 tnum mr-1">{stage.short}</span>
                        {stage.label}
                      </span>
                      <span className="text-[12px] text-ink3 tnum">{col.length}</span>
                    </div>
                    <div className="space-y-2">
                      {col.map((c) => (
                        <div
                          key={c.id}
                          draggable
                          onDragStart={() => setDragId(c.id)}
                          onDragEnd={() => setDragId(null)}
                          className={`rounded-xl bg-surface border border-line p-3 cursor-grab active:cursor-grabbing ${
                            moving.has(c.id) ? "opacity-50" : ""
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <div
                              className="w-8 h-8 rounded-full flex items-center justify-center text-[13px] font-bold shrink-0 text-brand"
                              style={{ backgroundColor: c.color ?? "var(--accent-tint)" }}
                            >
                              {c.name[0]}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="text-[14px] font-bold text-ink truncate">{c.name}</div>
                              <div className="text-[11px] text-ink3 truncate">
                                {[calcAge(c.birth_day), genderLabel(c.gender), c.mobile_phone_number]
                                  .filter(Boolean)
                                  .join(" · ")}
                              </div>
                            </div>
                          </div>
                          {c.tags.length > 0 && (
                            <div className="mt-1.5 flex gap-1 flex-wrap">
                              {c.tags.slice(0, 2).map((tag) => (
                                <span
                                  key={tag.id}
                                  className="text-[10px] font-semibold rounded-full px-1.5 py-0.5"
                                  style={{
                                    backgroundColor: tag.color ? `${tag.color}20` : "var(--surface-2)",
                                    color: tag.color ?? "var(--ink-3)",
                                  }}
                                >
                                  {tag.label}
                                </span>
                              ))}
                            </div>
                          )}
                          <div className="mt-2 flex items-center justify-between gap-2">
                            {/* 모바일·접근성 폴백: 드래그 없이 단계 이동 */}
                            <select
                              value={c.sales_stage}
                              onChange={(e) => moveCustomer(c.id, e.target.value as SalesStage)}
                              aria-label={`${c.name} 영업단계 이동`}
                              className="text-[11px] rounded-lg border border-line bg-surface px-1.5 py-1 text-ink2"
                            >
                              {SALES_STAGES.map((s) => (
                                <option key={s.key} value={s.key}>
                                  {s.label}
                                </option>
                              ))}
                            </select>
                            <Link
                              href={`/customer/${c.id}?tab=analysis`}
                              className="text-[12px] font-semibold text-brand shrink-0"
                            >
                              분석 ›
                            </Link>
                          </div>
                        </div>
                      ))}
                      {col.length === 0 && (
                        <div className="px-1 py-5 text-center text-[11px] text-ink3">여기로 끌어다 놓기</div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            {totalCount > customers.length && (
              <p className="mt-3 text-[12px] text-ink3 text-center">
                전체 {totalCount}명 중 {customers.length}명 표시 중 — 검색으로 좁혀서 이동하세요.
              </p>
            )}
          </>
        )}
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
