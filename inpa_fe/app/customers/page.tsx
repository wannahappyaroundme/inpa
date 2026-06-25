"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card, CustomerAvatar, stalenessLevel } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  listCustomers,
  updateCustomer,
  SALES_STAGES,
  type CustomerListItem,
  type SalesStage,
  type MarketingConsent,
  type CustomerWritePayload,
} from "@/lib/api";
import { CustomerCreateModal } from "@/components/customer-create-modal";

// 고객 관리(CRM) — 영업 4단계(DB·TA·FA·청약) 칸반/리스트. 방치 색상경보·즐겨찾기·보험나이.

// ── 직업 위험등급 배지 (1/2/3급만 표시, 9=기타·null=미표시) ──
function riskBadge(grade: number | null): { label: string; cls: string } | null {
  switch (grade) {
    case 1: return { label: "위험 1급", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" };
    case 2: return { label: "위험 2급", cls: "bg-amber-50 text-amber-700 border-amber-200" };
    case 3: return { label: "위험 3급", cls: "bg-rose-50 text-rose-700 border-rose-200" };
    default: return null;
  }
}

// ── 마케팅 동의 배지 ('none'·'revoked' = 비동의) ──
function consentBadge(c: MarketingConsent): { label: string; cls: string } {
  if (c === "agreed") return { label: "마케팅 동의", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" };
  return { label: "마케팅 비동의", cls: "bg-surface2 text-ink3 border-line" };
}

// ── 방치 경보 → 카드 테두리(ring, 배경 X — PM 06.24) ──
function ringCls(level: "red" | "amber" | null): string {
  if (level === "red") return "ring-2 ring-rose-400";
  if (level === "amber") return "ring-2 ring-amber-400";
  return "";
}

function genderLabel(g: string | null): string {
  const s = g == null ? "" : String(g);
  if (s === "1" || s === "M") return "남";
  if (s === "2" || s === "F") return "여";
  return "";
}

// 보험나이 표기 (없으면 —)
function ageLabel(age: number | null): string {
  return age == null ? "—" : `${age}세`;
}

// ── ? 툴팁(클릭 토글) — 단계 설명 ──
function InfoDot({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        onBlur={() => setOpen(false)}
        aria-label="단계 설명"
        className="w-4 h-4 rounded-full border border-line text-[10px] font-bold text-ink3 leading-none flex items-center justify-center hover:bg-surface2"
      >
        ?
      </button>
      {open && (
        <span className="absolute left-0 top-5 z-30 w-56 rounded-lg border border-line bg-surface px-3 py-2 text-[11px] leading-4 text-ink2 shadow-lg">
          {text}
        </span>
      )}
    </span>
  );
}

// ── 즐겨찾기/고정 토글 버튼 ──
function FavPinButtons({
  c,
  onToggle,
}: {
  c: CustomerListItem;
  onToggle: (id: number, payload: Partial<CustomerWritePayload>, optimistic: Partial<CustomerListItem>) => void;
}) {
  return (
    <div className="flex items-center gap-0.5">
      <button
        type="button"
        aria-label={c.is_pinned ? "상단고정 해제" : "상단고정"}
        aria-pressed={c.is_pinned}
        onClick={(e) => { e.stopPropagation(); onToggle(c.id, { is_pinned: !c.is_pinned }, { is_pinned: !c.is_pinned }); }}
        className={`text-[13px] leading-none px-1 ${c.is_pinned ? "text-brand" : "text-muted hover:text-ink3"}`}
      >
        {c.is_pinned ? "📌" : "📍"}
      </button>
      <button
        type="button"
        aria-label={c.is_favorite ? "즐겨찾기 해제" : "즐겨찾기"}
        aria-pressed={c.is_favorite}
        onClick={(e) => { e.stopPropagation(); onToggle(c.id, { is_favorite: !c.is_favorite }, { is_favorite: !c.is_favorite }); }}
        className={`text-[13px] leading-none px-1 ${c.is_favorite ? "text-amber-500" : "text-muted hover:text-ink3"}`}
      >
        {c.is_favorite ? "★" : "☆"}
      </button>
    </div>
  );
}

// ── 작은 배지 묶음(위험등급·마케팅) ──
function MetaBadges({ c }: { c: CustomerListItem }) {
  const risk = riskBadge(c.job_risk_grade);
  const consent = consentBadge(c.marketing_consent);
  return (
    <>
      {risk && (
        <span className={`text-[10px] font-semibold rounded-full px-1.5 py-0.5 border ${risk.cls}`}>{risk.label}</span>
      )}
      <span className={`text-[10px] font-semibold rounded-full px-1.5 py-0.5 border ${consent.cls}`}>{consent.label}</span>
    </>
  );
}

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
      const lvl = stalenessLevel(c.last_contacted_at, c.created_at);
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
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-[22px] font-extrabold text-ink">
            고객 <span className="text-ink3 tnum">{loading ? "..." : totalCount}</span>
          </h1>
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

        {/* 방치 경보 범례 */}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink3">
          <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-[4px] border-2 border-amber-400" />3일+ 미연락</span>
          <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-[4px] border-2 border-rose-400" />7일+ 미연락</span>
          <span className="text-muted">테두리 = 방치 정도 · ★ 즐겨찾기 · 📌 상단고정</span>
        </div>

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">{error}</div>
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
              const lvl = stalenessLevel(c.last_contacted_at, c.created_at);
              return (
                <Card key={c.id} className={`p-4 flex items-center gap-3 ${ringCls(lvl)}`}>
                  <CustomerAvatar name={c.name} color={c.color} size={44} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[16px] font-bold text-ink">{c.name}</span>
                      <span className="text-[12px] text-ink3">
                        {[ageLabel(c.insurance_age), genderLabel(c.gender)].filter(Boolean).join(" · ")}
                      </span>
                      <MetaBadges c={c} />
                      {c.tags.slice(0, 2).map((tag) => (
                        <span
                          key={tag.id}
                          className="text-[11px] font-semibold rounded-full px-2 py-0.5"
                          style={{ backgroundColor: tag.color ? `${tag.color}20` : undefined, color: tag.color ?? undefined }}
                        >
                          {tag.label}
                        </span>
                      ))}
                    </div>
                    <div className="text-[12px] text-ink3 mt-0.5">
                      {c.mobile_phone_number ?? "연락처 없음"}
                      {c.family_count > 0 && <span> · 가족 {c.family_count}명</span>}
                      {lvl && <span className={lvl === "red" ? "text-rose-600" : "text-amber-600"}> · 미연락 경보</span>}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1.5 shrink-0">
                    <FavPinButtons c={c} onToggle={patchCustomer} />
                    <button
                      onClick={() => markContacted(c.id)}
                      className="text-[11px] font-semibold text-ink3 border border-line rounded-lg px-2 py-0.5 hover:bg-surface2"
                    >
                      연락함
                    </button>
                    <Link href={`/customer/${c.id}?tab=analysis`} className="text-[12px] font-semibold text-brand">
                      분석 ›
                    </Link>
                  </div>
                </Card>
              );
            })}
          </div>
        )}

        {/* ── 칸반 보기 (영업 4단계: DB·TA·FA·청약) ── */}
        {view === "kanban" && customers.length > 0 && (
          <>
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {SALES_STAGES.map((stage) => {
                const col = sorted.filter((c) => c.sales_stage === stage.key);
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
                      <span className="inline-flex items-center gap-1 text-[13px] font-bold text-ink">
                        <span className="text-ink3 tnum mr-0.5">{stage.short}</span>
                        {stage.label}
                        <InfoDot text={stage.desc} />
                      </span>
                      <span className="text-[12px] text-ink3 tnum">{col.length}</span>
                    </div>
                    <div className="space-y-2">
                      {col.map((c) => {
                        const lvl = stalenessLevel(c.last_contacted_at, c.created_at);
                        return (
                          <div
                            key={c.id}
                            draggable
                            onDragStart={() => setDragId(c.id)}
                            onDragEnd={() => setDragId(null)}
                            className={`rounded-xl bg-surface border border-line p-3 cursor-grab active:cursor-grabbing ${ringCls(lvl)} ${
                              moving.has(c.id) ? "opacity-50" : ""
                            }`}
                          >
                            <div className="flex items-center gap-2">
                              <CustomerAvatar name={c.name} color={c.color} size={32} />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-1">
                                  <span className="text-[14px] font-bold text-ink truncate">{c.name}</span>
                                </div>
                                <div className="text-[11px] text-ink3 truncate">
                                  {[ageLabel(c.insurance_age), genderLabel(c.gender), c.mobile_phone_number]
                                    .filter(Boolean)
                                    .join(" · ")}
                                </div>
                              </div>
                              <FavPinButtons c={c} onToggle={patchCustomer} />
                            </div>
                            <div className="mt-1.5 flex gap-1 flex-wrap">
                              <MetaBadges c={c} />
                              {c.tags.slice(0, 1).map((tag) => (
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
                            <div className="mt-2 flex items-center justify-between gap-2">
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
                              <div className="flex items-center gap-2 shrink-0">
                                <button
                                  onClick={() => markContacted(c.id)}
                                  className="text-[11px] font-semibold text-ink3 border border-line rounded-lg px-2 py-1 hover:bg-surface2"
                                >
                                  연락함
                                </button>
                                <Link href={`/customer/${c.id}?tab=analysis`} className="text-[12px] font-semibold text-brand">
                                  분석 ›
                                </Link>
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
