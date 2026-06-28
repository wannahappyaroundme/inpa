"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { CustomerAvatar, stalenessLevel } from "@/components/ui";
import { SelfDiagnosisShare } from "@/components/self-diagnosis-share";
import { InfoDot } from "@/components/info-dot";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  listCustomers,
  updateCustomer,
  SALES_STAGES,
  type CustomerListItem,
  type SalesStage,
  type CustomerWritePayload,
} from "@/lib/api";
import { CustomerCreateModal } from "@/components/customer-create-modal";

// 고객 관리(CRM) — 영업 4단계(DB·TA·FA·청약) 칸반/리스트. 방치 색상경보·즐겨찾기·보험나이.

// ── 방치 경보 → 카드 테두리(ring, 배경 X — PM 06.24) ──
function ringCls(level: "red" | "amber" | null): string {
  if (level === "red") return "ring-2 ring-cnone";
  if (level === "amber") return "ring-2 ring-short";
  return "";
}

function genderLabel(g: string | null): string {
  const s = g == null ? "" : String(g);
  if (s === "1" || s === "M") return "남";
  if (s === "2" || s === "F") return "여";
  return "";
}

// ── 경과일 계산 헬퍼 ──
function daysSince(dateStr: string | null | undefined): number {
  if (!dateStr) return Infinity;
  const diff = Date.now() - new Date(dateStr).getTime();
  return Math.floor(diff / 86_400_000);
}

function elapsedLabel(lastContacted: string | null | undefined, createdAt: string): string {
  const d = daysSince(lastContacted ?? createdAt);
  if (d <= 0) return "오늘";
  return `${d}일전`;
}

// ── 영업단계 배지 ──
const STAGE_BADGE: Record<string, { label: string; cls: string }> = {
  db:       { label: "DB",   cls: "bg-surface2 text-ink3 border-line" },
  contact:  { label: "TA",   cls: "bg-blue-50 text-blue-700 border-blue-200" },
  meeting:  { label: "FA",   cls: "bg-violet-50 text-violet-700 border-violet-200" },
  contract: { label: "청약", cls: "bg-success-tint text-success-ink border-enough/30" },
};

// ── ⋯ 드롭다운 메뉴 ──
function DotMenu({
  c,
  onToggle,
  onContacted,
}: {
  c: CustomerListItem;
  onToggle: (id: number, payload: Partial<CustomerWritePayload>, optimistic: Partial<CustomerListItem>) => void;
  onContacted: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        aria-label="더보기 메뉴"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className="text-[16px] text-ink3 hover:text-ink px-1.5 py-0.5 rounded-lg hover:bg-surface2 leading-none"
      >
        ⋯
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-20 bg-surface border border-line rounded-xl shadow-lg py-1 min-w-[130px] text-[13px]"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onToggle(c.id, { is_pinned: !c.is_pinned }, { is_pinned: !c.is_pinned }); setOpen(false); }}
            className="w-full text-left px-4 py-2 hover:bg-surface2 flex items-center gap-2"
          >
            {c.is_pinned ? "📌 고정 해제" : "📍 상단고정"}
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onToggle(c.id, { is_favorite: !c.is_favorite }, { is_favorite: !c.is_favorite }); setOpen(false); }}
            className="w-full text-left px-4 py-2 hover:bg-surface2 flex items-center gap-2"
          >
            {c.is_favorite ? "★ 즐겨찾기 해제" : "☆ 즐겨찾기"}
          </button>
          <hr className="my-1 border-line" />
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onContacted(c.id); setOpen(false); }}
            className="w-full text-left px-4 py-2 hover:bg-surface2 text-brand"
          >
            방금 연락함
          </button>
        </div>
      )}
    </div>
  );
}

export default function CustomersPage() {
  const ready = useAuthGuard();
  const router = useRouter();

  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [view, setView] = useState<"kanban" | "list">("kanban");
  const [dragId, setDragId] = useState<number | null>(null);
  const [moving, setMoving] = useState<Set<number>>(new Set());
  const [showContract, setShowContract] = useState(false);

  const fetchCustomers = useCallback(async (q: string) => {
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
  }, []);

  useEffect(() => {
    if (!ready) return;
    fetchCustomers("");
  }, [ready, fetchCustomers]);

  useEffect(() => {
    if (!ready) return;
    const id = setTimeout(() => fetchCustomers(search), 300);
    return () => clearTimeout(id);
  }, [search, ready, fetchCustomers]);

  // 칸반 단계 이동 — 드래그/select 공용. 낙관적 업데이트 후 실패 시 롤백.
  const moveCustomer = useCallback(async (id: number, to: SalesStage) => {
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
  }, []);

  // 즐겨찾기·상단고정 등 부분 패치 — 낙관적 업데이트 후 실패 시 재조회로 복구.
  const patchCustomer = useCallback(
    async (id: number, payload: Partial<CustomerWritePayload>, optimistic: Partial<CustomerListItem>) => {
      setCustomers((prev) => prev.map((c) => (c.id === id ? { ...c, ...optimistic } : c)));
      try {
        await updateCustomer(id, payload);
      } catch {
        setError("저장에 실패했어요. 잠시 후 다시 시도하세요.");
        fetchCustomers(search);
      }
    },
    [fetchCustomers, search]
  );

  // "연락함" — last_contacted_at 갱신(방치 경보 리셋)
  const markContacted = useCallback(
    (id: number) => {
      const now = new Date().toISOString();
      patchCustomer(id, { last_contacted_at: now }, { last_contacted_at: now });
    },
    [patchCustomer]
  );

  // 정렬: 상단고정 > 즐겨찾기 > 방치(red>amber) > 최근 등록
  const sortCustomers = useCallback((list: CustomerListItem[]) => {
    const rank = (c: CustomerListItem) => {
      const lvl = (c.sales_stage === "contract" ? null : stalenessLevel(c.last_contacted_at, c.created_at));
      return lvl === "red" ? 2 : lvl === "amber" ? 1 : 0;
    };
    return [...list].sort((a, b) => {
      if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
      if (a.is_favorite !== b.is_favorite) return a.is_favorite ? -1 : 1;
      const r = rank(b) - rank(a);
      if (r) return r;
      return b.created_at.localeCompare(a.created_at);
    });
  }, []);

  const sorted = useMemo(() => sortCustomers(customers), [customers, sortCustomers]);

  if (!ready) return null;

  return (
    <div className="min-h-dvh">
      <AppNav active="customers" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        {/* ── 제목 + 범례 + 버튼 ── */}
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-x-4 gap-y-1 flex-wrap">
            <h1 className="text-[22px] font-extrabold text-ink">
              고객 <span className="text-ink3 tnum">{loading ? "..." : totalCount}</span>
            </h1>
            {/* 방치 경보 범례 — 제목 옆 인라인 */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink3 pt-1">
              <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-[4px] border-2 border-short" />3일+</span>
              <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-[4px] border-2 border-cnone" />7일+</span>
              <span className="text-muted">테두리 = 연락 끊긴 기간</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
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

        <div className="mt-4">
          <SelfDiagnosisShare />
        </div>

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-danger-tint border border-cnone/30 text-[13px] text-danger-ink">{error}</div>
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
        {view === "list" && customers.length > 0 && (
          <div className="mt-4 grid sm:grid-cols-2 gap-3">
            {sorted.map((c) => {
              const lvl = (c.sales_stage === "contract" ? null : stalenessLevel(c.last_contacted_at, c.created_at));
              return (
                <div
                  key={c.id}
                  className={`rounded-2xl bg-surface border border-line shadow-sm p-3.5 cursor-pointer hover:shadow-md transition ${ringCls(lvl)}`}
                  onClick={() => router.push(`/customer/${c.id}`)}
                >
                  <div className="flex items-start gap-3">
                    <CustomerAvatar label={c.avatar_label} color={c.color} size={40} />
                    <div className="flex-1 min-w-0">
                      {/* top row */}
                      <div className="flex items-center gap-1.5">
                        <span className="text-[15px] font-bold text-ink truncate">{c.name}</span>
                        {genderLabel(c.gender) || c.job_risk_grade ? (
                          <span className="text-[11px] text-ink3 shrink-0">
                            {[genderLabel(c.gender), c.job_risk_grade ? `${c.job_risk_grade}급` : ""].filter(Boolean).join("·")}
                          </span>
                        ) : null}
                        <div className="ml-auto shrink-0">
                          <DotMenu c={c} onToggle={patchCustomer} onContacted={markContacted} />
                        </div>
                      </div>
                      {/* bottom row */}
                      <div className="mt-1 flex items-center gap-2 flex-wrap">
                        <span className="text-[12px] text-ink3">{c.mobile_phone_number ?? "연락처 없음"}</span>
                        {(() => {
                          const sb = STAGE_BADGE[c.sales_stage];
                          return sb ? (
                            <span className={`text-[10px] font-semibold rounded-full px-2 py-0.5 border ${sb.cls}`}>{sb.label}</span>
                          ) : null;
                        })()}
                        <span className="text-[11px] text-ink3">{elapsedLabel(c.last_contacted_at, c.created_at)}</span>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* ── 칸반 보기 (영업 4단계: DB·TA·FA·청약) ── */}
        {view === "kanban" && customers.length > 0 && (
          <>
            <div className="mt-3 flex items-center justify-end">
              <button
                type="button"
                onClick={() => setShowContract((v) => !v)}
                className="text-[12px] font-semibold text-ink3 border border-line rounded-lg px-3 py-1.5 hover:bg-surface2"
              >
                {showContract ? "청약 숨기기" : "청약 더보기"}
              </button>
            </div>
            <div className="mt-2 flex gap-3 overflow-x-auto pb-2 snap-x">
              {SALES_STAGES.map((stage) => {
                if (stage.key === "contract" && !showContract) return null;
                const col = sorted.filter((c) => c.sales_stage === stage.key);
                return (
                  <div
                    key={stage.key}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => {
                      if (dragId != null) moveCustomer(dragId, stage.key);
                      setDragId(null);
                    }}
                    className="rounded-2xl bg-surface2 border border-line p-2.5 min-h-[120px] w-[78vw] shrink-0 sm:w-auto sm:flex-1 sm:min-w-0 snap-start"
                  >
                    <div className="flex items-center justify-between px-1 pb-2">
                      <span className="inline-flex items-center gap-1 text-[13px] font-bold text-ink">
                        <span className="text-ink3 tnum mr-0.5">{stage.short}</span>
                        {stage.label}
                        <InfoDot text={stage.desc} />
                      </span>
                      <span className="text-[12px] text-ink3 tnum">{col.length}</span>
                    </div>
                    <div className="space-y-2">
                      {col.map((c) => {
                        const lvl = (c.sales_stage === "contract" ? null : stalenessLevel(c.last_contacted_at, c.created_at));
                        return (
                          <div
                            key={c.id}
                            draggable
                            onDragStart={() => setDragId(c.id)}
                            onDragEnd={() => setDragId(null)}
                            className={`rounded-xl bg-surface border border-line p-3 cursor-grab active:cursor-grabbing ${ringCls(lvl)} ${moving.has(c.id) ? "opacity-50" : ""}`}
                            onClick={() => router.push(`/customer/${c.id}`)}
                          >
                            <div className="flex items-start gap-2">
                              <CustomerAvatar label={c.avatar_label} color={c.color} size={32} />
                              <div className="flex-1 min-w-0">
                                {/* top row */}
                                <div className="flex items-center gap-1">
                                  <span className="text-[13px] font-bold text-ink truncate">{c.name}</span>
                                  {(genderLabel(c.gender) || c.job_risk_grade) && (
                                    <span className="text-[10px] text-ink3 shrink-0">
                                      {[genderLabel(c.gender), c.job_risk_grade ? `${c.job_risk_grade}급` : ""].filter(Boolean).join("·")}
                                    </span>
                                  )}
                                  <div className="ml-auto shrink-0">
                                    <DotMenu c={c} onToggle={patchCustomer} onContacted={markContacted} />
                                  </div>
                                </div>
                                {/* bottom row */}
                                <div className="mt-1 flex items-center gap-1.5 flex-wrap">
                                  <span className="text-[11px] text-ink3 truncate">{c.mobile_phone_number ?? ""}</span>
                                  {(() => {
                                    const sb = STAGE_BADGE[c.sales_stage];
                                    return sb ? (
                                      <span className={`text-[9px] font-semibold rounded-full px-1.5 py-0.5 border ${sb.cls}`}>{sb.label}</span>
                                    ) : null;
                                  })()}
                                  <span className="text-[10px] text-ink3">{elapsedLabel(c.last_contacted_at, c.created_at)}</span>
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
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
