"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
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
  CUSTOMER_STATUSES,
  type CustomerListItem,
  type SalesStage,
  type CustomerWritePayload,
} from "@/lib/api";
import { CustomerCreateModal } from "@/components/customer-create-modal";

// 고객 관리(CRM) — 영업 4단계(DB·TA·FA·청약) 칸반/리스트. 방치 색상경보·즐겨찾기·보험나이.

// ── 방치(무접촉) 표시 → 카드 왼쪽 옅은 줄(강한 ring 대신 톤다운 — PM 06.29) ──
function staleEdgeCls(level: "red" | "amber" | null): string {
  if (level === "red") return "border-l-[3px] border-l-cnone";
  if (level === "amber") return "border-l-[3px] border-l-short";
  return "";
}

// 방치(무접촉) 레벨 — 진행중 고객만 대상(보류·휴면·종료·청약은 경보 없음 — PM 06.29).
function staleLevelFor(c: CustomerListItem): "red" | "amber" | null {
  if (c.status !== "active" || c.sales_stage === "contract") return null;
  return stalenessLevel(c.last_contacted_at, c.created_at);
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

// ── 고객 상태 배지(진행중은 기본값이라 배지 없음 — 화면을 깔끔히) ──
const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  hold:    { label: "보류", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  dormant: { label: "휴면", cls: "bg-surface2 text-ink3 border-line" },
  closed:  { label: "종료", cls: "bg-rose-50 text-rose-600 border-rose-200" },
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
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const MENU_W = 150;

  // 버튼 위치 기준 fixed 좌표 계산 → 메뉴를 body 포털로 그려 칸반 overflow-x-auto 클리핑 회피
  const openMenu = useCallback(() => {
    const r = btnRef.current?.getBoundingClientRect();
    if (r) setPos({ top: r.bottom + 4, left: Math.max(8, r.right - MENU_W) });
    setOpen(true);
  }, []);

  // 바깥 클릭·ESC·스크롤 시 닫기(여러 메뉴 동시 열림/좌표 어긋남 방지)
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (menuRef.current?.contains(t) || btnRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onScroll = () => setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  const item = "w-full text-left px-4 py-2 hover:bg-surface2 flex items-center gap-2";
  return (
    <div className="relative" onClick={(e) => e.stopPropagation()}>
      <button
        ref={btnRef}
        type="button"
        aria-label="더보기 메뉴"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); open ? setOpen(false) : openMenu(); }}
        className="text-[16px] text-ink3 hover:text-ink px-1.5 py-0.5 rounded-lg hover:bg-surface2 leading-none"
      >
        ⋯
      </button>
      {open && pos && createPortal(
        <div
          ref={menuRef}
          role="menu"
          style={{ position: "fixed", top: pos.top, left: pos.left, width: MENU_W }}
          className="z-50 bg-surface border border-line rounded-xl shadow-lg py-1 text-[13px]"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onToggle(c.id, { is_pinned: !c.is_pinned }, { is_pinned: !c.is_pinned }); setOpen(false); }}
            className={item}
          >
            {c.is_pinned ? "📌 고정 해제" : "📍 상단고정"}
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onToggle(c.id, { is_favorite: !c.is_favorite }, { is_favorite: !c.is_favorite }); setOpen(false); }}
            className={item}
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
          <hr className="my-1 border-line" />
          <div className="px-4 pt-0.5 pb-1 text-[11px] text-ink3">상태</div>
          {CUSTOMER_STATUSES.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={(e) => { e.stopPropagation(); onToggle(c.id, { status: s.key }, { status: s.key }); setOpen(false); }}
              className="w-full text-left px-4 py-1.5 hover:bg-surface2 flex items-center gap-2"
            >
              <span className={c.status === s.key ? "text-brand font-semibold" : "text-ink2"}>{s.label}</span>
              {c.status === s.key && <span className="ml-auto text-brand text-[12px]">✓</span>}
            </button>
          ))}
        </div>,
        document.body
      )}
    </div>
  );
}

// 칸반(단계별) 한 단계에 1차로 보여줄 고객 수 — '더보기'를 누를 때마다 +10씩 펼친다.
const KANBAN_PAGE = 10;

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
  // 단계별 펼침 개수(기본 KANBAN_PAGE, '더보기'로 +KANBAN_PAGE). 단계 key → 노출 개수.
  const [visibleByStage, setVisibleByStage] = useState<Record<string, number>>({});
  // 보류·휴면·종료(정리된 고객) 접기 — '진행중만' 보기 토글.
  const [hideParked, setHideParked] = useState(false);

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
  // 표시 대상 — '진행중만' 토글 시 보류·휴면·종료 숨김.
  const visible = useMemo(
    () => (hideParked ? sorted.filter((c) => c.status === "active") : sorted),
    [sorted, hideParked]
  );

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
            {/* 방치(무접촉) 범례 — 진행중 고객만. 제목 옆 인라인 */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink3 pt-1">
              <span className="inline-flex items-center gap-1"><span className="w-1 h-3.5 rounded-full bg-short" />3일+</span>
              <span className="inline-flex items-center gap-1"><span className="w-1 h-3.5 rounded-full bg-cnone" />7일+</span>
              <span className="text-muted">왼쪽 줄 = 연락 안 한 기간(진행중만)</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setHideParked((v) => !v)}
              aria-pressed={hideParked}
              title="보류·휴면·종료 고객을 접고 진행중만 보기"
              className={`text-[12px] font-semibold rounded-xl border px-3 py-1.5 transition ${hideParked ? "border-brand text-brand bg-accent-tint" : "border-line text-ink3 bg-surface2 hover:bg-surface"}`}
            >
              {hideParked ? "전체 보기" : "진행중만"}
            </button>
            <div className="inline-flex rounded-xl border border-line bg-surface2 p-0.5 text-[12px] font-semibold">
              {(["kanban", "list"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`px-3 py-1.5 rounded-[10px] transition ${
                    view === v ? "bg-surface text-brand shadow-sm" : "text-ink3"
                  }`}
                >
                  {v === "kanban" ? "단계별" : "목록"}
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
            {visible.map((c) => {
              const lvl = staleLevelFor(c);
              return (
                <div
                  key={c.id}
                  className={`rounded-2xl bg-surface border border-line shadow-sm p-3.5 cursor-pointer hover:shadow-md transition ${staleEdgeCls(lvl)} ${c.status !== "active" ? "opacity-60" : ""}`}
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
                        {(() => {
                          const stb = STATUS_BADGE[c.status];
                          return stb ? (
                            <span className={`text-[10px] font-semibold rounded-full px-2 py-0.5 border ${stb.cls}`}>{stb.label}</span>
                          ) : null;
                        })()}
                        <span className={`text-[11px] ${lvl === "red" ? "text-cnone font-semibold" : lvl === "amber" ? "text-short font-semibold" : "text-ink3"}`}>
                          {lvl ? `${daysSince(c.last_contacted_at ?? c.created_at)}일 무접촉` : elapsedLabel(c.last_contacted_at, c.created_at)}
                        </span>
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
                const col = visible.filter((c) => c.sales_stage === stage.key);
                const vis = visibleByStage[stage.key] ?? KANBAN_PAGE;
                const shown = col.slice(0, vis);
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
                      {shown.map((c) => {
                        const lvl = staleLevelFor(c);
                        return (
                          <div
                            key={c.id}
                            draggable
                            onDragStart={() => setDragId(c.id)}
                            onDragEnd={() => setDragId(null)}
                            className={`rounded-xl bg-surface border border-line p-3 cursor-grab active:cursor-grabbing ${staleEdgeCls(lvl)} ${c.status !== "active" ? "opacity-60" : ""} ${moving.has(c.id) ? "opacity-50" : ""}`}
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
                                  {(() => {
                                    const stb = STATUS_BADGE[c.status];
                                    return stb ? (
                                      <span className={`text-[9px] font-semibold rounded-full px-1.5 py-0.5 border ${stb.cls}`}>{stb.label}</span>
                                    ) : null;
                                  })()}
                                  <span className={`text-[10px] ${lvl === "red" ? "text-cnone font-semibold" : lvl === "amber" ? "text-short font-semibold" : "text-ink3"}`}>
                                    {lvl ? `${daysSince(c.last_contacted_at ?? c.created_at)}일 무접촉` : elapsedLabel(c.last_contacted_at, c.created_at)}
                                  </span>
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                      {col.length === 0 && (
                        <div className="px-1 py-5 text-center text-[11px] text-ink3">여기로 끌어다 놓기</div>
                      )}
                      {col.length > shown.length && (
                        <button
                          type="button"
                          onClick={() =>
                            setVisibleByStage((v) => ({ ...v, [stage.key]: (v[stage.key] ?? KANBAN_PAGE) + KANBAN_PAGE }))
                          }
                          className="w-full rounded-xl border border-line bg-surface py-2 text-[12px] font-semibold text-ink3 hover:bg-surface2 transition"
                        >
                          더보기 {col.length - shown.length}명
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            {totalCount > customers.length && (
              <p className="mt-3 text-[12px] text-ink3 text-center">
                전체 {totalCount}명 중 {customers.length}명을 보고 있어요. 이름·연락처로 검색하면 찾는 고객만 볼 수 있어요.
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
