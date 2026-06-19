"use client";

import { useState, useEffect, useCallback, Suspense, type ReactNode } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { DisclaimerFooter } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  getHeatmap,
  listCustomers,
  type HeatmapResponse,
  type HeatmapDetail,
  type HeatmapStatus,
  type CustomerListItem,
} from "@/lib/api";

// ──────────────────────────────────────────────
// 담보 한눈표 (히트맵) — 설계사 전용 도구.
// 상태 판정은 BE 권위(FE는 status 문자열 → CSS클래스 매핑만).
// neutral 모드: '기준 미설정 — 중립 표시'. 충족/부족 단정 금지.
// ──────────────────────────────────────────────

// ── 색·패턴 매핑 (BE status → Tailwind 유틸만, inline hex 금지) ─────────────
function cellClasses(status: HeatmapStatus, graded: boolean): string {
  // 색맹 이중인코딩: 채움/좌4px바/점선 패턴 동반 (aria-label은 각 셀에)
  if (!graded) {
    // 간략 모드: 없는 것만 강조, 나머지 흐리게
    return status === "neutral"
      ? "bg-surface2 border border-dashed border-line text-ink3"
      : status === "shortage"
      ? "bg-amber-50 border-l-4 border-l-short border border-line text-ink"
      : status === "adequate"
      ? "bg-surface2 border border-line text-ink2"
      : /* over */
        "bg-surface2 border border-line text-ink2";
  }
  // 상세(4단계) 모드
  switch (status) {
    case "neutral":
      return "bg-surface2 border border-dashed border-line text-ink3";
    case "shortage":
      // 좌4px 액센트바 + amber 틴트 (amber ≠ danger/red)
      return "bg-amber-50 border-l-4 border-l-short border border-amber-200 text-ink font-medium";
    case "adequate":
      return "bg-indigo-50 border border-indigo-200 text-enough font-medium";
    case "over":
      return "bg-blue-50 border border-blue-200 text-over font-medium";
  }
}

function statusLabel(status: HeatmapStatus, mode: "neutral" | "graded"): string {
  if (mode === "neutral") return "—";
  switch (status) {
    case "neutral":  return "—";
    case "shortage": return "부족";
    case "adequate": return "적정";
    case "over":     return "넉넉";
  }
}

function statusAriaLabel(name: string, status: HeatmapStatus, mode: "neutral" | "graded"): string {
  if (mode === "neutral") return `${name}: 중립(기준 미설정)`;
  switch (status) {
    case "neutral":  return `${name}: 중립`;
    case "shortage": return `${name}: 부족`;
    case "adequate": return `${name}: 적정`;
    case "over":     return `${name}: 넉넉`;
  }
}

// ── 금액 포매터 ────────────────────────────────
const krw = new Intl.NumberFormat("ko-KR");
function fmtAmount(val: number | null): string {
  if (val === null || val === 0) return "—";
  if (val >= 100_000_000) return `${krw.format(val / 100_000_000)}억`;
  if (val >= 10_000) return `${krw.format(val / 10_000)}만`;
  return `${krw.format(val)}원`;
}
function fmtWon(val: number | null): string {
  if (val === null) return "—";
  return `${krw.format(val)}원`;
}

// ── 필터 타입 ──────────────────────────────────
type FilterKey = "all" | "shortage" | "adequate" | "over" | "neutral";

// ── 최상위: Suspense 래핑 (useSearchParams 요건) ──
export default function AnalysisPage() {
  return (
    <Suspense fallback={<AnalysisPageSkeleton />}>
      <AnalysisPageInner />
    </Suspense>
  );
}

function AnalysisPageSkeleton() {
  return (
    <div className="min-h-dvh">
      <AppNav active="analysis" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <div className="h-8 w-40 rounded-xl bg-line animate-pulse" />
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 rounded-2xl bg-line animate-pulse" />
          ))}
        </div>
        <div className="mt-8 space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-start gap-3">
              <div className="w-20 h-6 rounded bg-line animate-pulse shrink-0" />
              <div className="flex gap-2 flex-wrap">
                {Array.from({ length: 4 }).map((_, j) => (
                  <div key={j} className="w-24 h-9 rounded-lg bg-line animate-pulse" />
                ))}
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

// ── 실제 구현 컴포넌트 ────────────────────────
function AnalysisPageInner() {
  const ready = useAuthGuard();
  const searchParams = useSearchParams();
  const router = useRouter();

  // 고객 목록 (드롭다운용)
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [customersLoading, setCustomersLoading] = useState(false);

  // 선택된 고객 ID
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // 히트맵 데이터
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null);
  const [heatmapLoading, setHeatmapLoading] = useState(false);
  const [heatmapError, setHeatmapError] = useState<string | null>(null);

  // UI 상태
  const [graded, setGraded] = useState(true);
  const [filter, setFilter] = useState<FilterKey>("all");

  // ── 고객 목록 로드 ──────────────────────────
  useEffect(() => {
    if (!ready) return;
    setCustomersLoading(true);
    listCustomers({ page: 1 })
      .then((res) => {
        setCustomers(res.results);
        // ?customer=<id> 쿼리 우선, 없으면 첫 고객 선택
        const qid = searchParams.get("customer");
        if (qid) {
          setSelectedId(Number(qid));
        } else if (res.results.length > 0) {
          setSelectedId(res.results[0].id);
        }
      })
      .catch(() => {
        setCustomers([]);
      })
      .finally(() => setCustomersLoading(false));
  }, [ready, searchParams]);

  // ── 히트맵 로드 ────────────────────────────
  const fetchHeatmap = useCallback(async (id: number) => {
    setHeatmapLoading(true);
    setHeatmapError(null);
    setHeatmap(null);
    try {
      const data = await getHeatmap(id);
      setHeatmap(data);
    } catch (e: unknown) {
      const msg =
        e instanceof Error ? e.message : "분석 데이터를 불러오지 못했어요.";
      setHeatmapError(msg);
    } finally {
      setHeatmapLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId !== null) {
      fetchHeatmap(selectedId);
    }
  }, [selectedId, fetchHeatmap]);

  // 고객 변경 시 URL 쿼리도 업데이트
  function handleCustomerChange(id: number) {
    setSelectedId(id);
    router.replace(`/analysis?customer=${id}`);
  }

  if (!ready) return null;

  // 선택된 고객 정보
  const selectedCustomer = customers.find((c) => c.id === selectedId);

  // ── 담보 필터링 (tree 순회) ──────────────────
  const filteredTree = heatmap
    ? heatmap.tree
        .map((cat) => ({
          ...cat,
          sub_categories: cat.sub_categories
            .map((sub) => ({
              ...sub,
              details: sub.details.filter((d) =>
                filter === "all" ? true : d.status === filter
              ),
            }))
            .filter((sub) => sub.details.length > 0),
        }))
        .filter((cat) => cat.sub_categories.length > 0)
    : [];

  return (
    <div className="min-h-dvh">
      <AppNav active="analysis" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">

        {/* ── 헤더 ── */}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-[13px] text-ink3">담보 한눈표 · 설계사 도구</div>
            <h1 className="text-[22px] font-extrabold text-ink">보장 분석</h1>
          </div>
          {/* 고객 드롭다운 */}
          {customersLoading ? (
            <div className="h-9 w-40 rounded-xl bg-line animate-pulse" />
          ) : customers.length > 0 ? (
            <select
              value={selectedId ?? ""}
              onChange={(e) => handleCustomerChange(Number(e.target.value))}
              className="rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-brand"
            >
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-[13px] text-ink3">고객 없음</span>
          )}
        </div>

        {/* ── neutral 모드 안내 배너 ── */}
        {heatmap?.mode === "neutral" && (
          <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-line bg-surface2 px-4 py-3">
            <span className="mt-0.5 text-[16px]" aria-hidden>ⓘ</span>
            <p className="text-[13px] text-ink2 leading-5">
              <b className="font-semibold text-ink">기준 미설정 — 중립 표시</b>
              <br />
              보장 기준선이 설정되지 않아 보유 여부만 표시해요.
              기준을 설정하면 부족·적정·넉넉을 구분할 수 있어요.
            </p>
            <button className="ml-auto shrink-0 text-[12px] font-semibold text-brand whitespace-nowrap">
              기준 설정 ›
            </button>
          </div>
        )}

        {/* ── summary KPI ── */}
        {heatmap && (
          <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <KpiCard label="월 보험료" value={fmtWon(heatmap.summary.monthly_premiums)} />
            <KpiCard label="총 납입 보험료" value={fmtWon(heatmap.summary.total_premiums)} />
            <KpiCard label="보험 건수" value={`${heatmap.insurance_count}건`} />
            <KpiCard
              label="분석 모드"
              value={heatmap.mode === "neutral" ? "중립" : "기준 적용"}
              valueClass={heatmap.mode === "neutral" ? "text-ink3" : "text-enough"}
            />
          </div>
        )}

        {/* ── 뷰 세그먼트 + 필터 칩 ── */}
        {heatmap && (
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <div className="inline-flex rounded-xl bg-line p-1 text-[13px] font-semibold">
              <button
                onClick={() => setGraded(false)}
                className={`px-3 py-1.5 rounded-lg transition ${!graded ? "bg-surface text-ink shadow-sm" : "text-ink3"}`}
              >
                간략
              </button>
              <button
                onClick={() => setGraded(true)}
                className={`px-3 py-1.5 rounded-lg transition ${graded ? "bg-surface text-ink shadow-sm" : "text-ink3"}`}
              >
                상세·4단계
              </button>
            </div>

            <div className="flex gap-2 overflow-x-auto">
              {(
                [
                  { key: "all", label: "전체" },
                  { key: "shortage", label: "부족" },
                  { key: "adequate", label: "적정" },
                  { key: "over", label: "넉넉" },
                  { key: "neutral", label: "중립" },
                ] as { key: FilterKey; label: string }[]
              ).map(({ key, label }) => (
                <FilterChip
                  key={key}
                  active={filter === key}
                  onClick={() => setFilter(key)}
                >
                  {label}
                </FilterChip>
              ))}
            </div>
          </div>
        )}

        {/* ── 로딩 상태 ── */}
        {heatmapLoading && (
          <div className="mt-8 space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-start gap-3">
                <div className="w-16 h-6 rounded bg-line animate-pulse shrink-0" />
                <div className="flex gap-2 flex-wrap">
                  {Array.from({ length: 4 }).map((_, j) => (
                    <div key={j} className="w-20 h-8 rounded-lg bg-line animate-pulse" />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── 에러 상태 ── */}
        {heatmapError && !heatmapLoading && (
          <div className="mt-6 rounded-xl border border-line bg-surface2 px-4 py-8 text-center">
            <p className="text-[14px] text-ink3">{heatmapError}</p>
            {selectedId !== null && (
              <button
                onClick={() => fetchHeatmap(selectedId)}
                className="mt-3 text-[13px] font-semibold text-brand"
              >
                다시 시도
              </button>
            )}
          </div>
        )}

        {/* ── 빈 상태 (보험 없음) ── */}
        {!heatmapLoading && !heatmapError && heatmap && heatmap.insurance_count === 0 && (
          <div className="mt-6 rounded-xl border border-dashed border-line px-4 py-12 text-center">
            <p className="text-[15px] font-semibold text-ink2">증권이 아직 없어요</p>
            <p className="mt-1 text-[13px] text-ink3">증권을 등록하면 보장 공백이 보여요.</p>
            <button className="mt-4 rounded-xl bg-brand text-white text-[13px] font-bold px-5 py-2.5">
              증권 등록
            </button>
          </div>
        )}

        {/* ── 고객 없음 상태 ── */}
        {!customersLoading && customers.length === 0 && (
          <div className="mt-8 text-center text-[14px] text-ink3">
            등록된 고객이 없어요.{" "}
            <a href="/customers" className="font-semibold text-brand">
              고객 등록 →
            </a>
          </div>
        )}

        {/* ── 히트맵 그리드 ── */}
        {!heatmapLoading && !heatmapError && heatmap && heatmap.insurance_count > 0 && (
          <div className="mt-5">
            {/* 고객 이름 + 분석 일시 */}
            {selectedCustomer && (
              <p className="mb-3 text-[13px] text-ink3">
                <b className="text-ink2">{selectedCustomer.name}</b>님의 보장 한눈표
                {heatmap.mode === "neutral" && (
                  <span className="ml-2 inline-flex items-center rounded-full bg-surface2 border border-line px-2 py-0.5 text-[11px] font-semibold text-ink3">
                    기준 미설정 · 중립
                  </span>
                )}
              </p>
            )}

            {filteredTree.length === 0 ? (
              <div className="py-8 text-center text-[14px] text-ink3">
                해당 조건의 담보가 없어요.
              </div>
            ) : (
              <div className="space-y-6">
                {filteredTree.map((cat) => (
                  <div key={cat.category_id}>
                    {/* 카테고리 헤더 */}
                    <div className="mb-2 flex items-center gap-2">
                      <h2 className="text-[14px] font-bold text-ink">{cat.name}</h2>
                      <span className="text-[11px] text-ink3 bg-surface2 border border-line rounded-full px-2 py-0.5">
                        {cat.insurance_type}
                      </span>
                    </div>

                    <div className="space-y-3">
                      {cat.sub_categories.map((sub) => (
                        <div key={sub.sub_category_id} className="flex items-start gap-2">
                          {/* 서브카테고리 라벨 */}
                          <div className="w-20 sm:w-24 shrink-0 pt-2 text-[12px] font-semibold text-ink2 leading-4">
                            {sub.name}
                          </div>

                          {/* 담보 셀 그리드 */}
                          <div className="flex flex-wrap gap-1.5">
                            {sub.details.map((detail) => (
                              <HeatCell
                                key={detail.detail_id}
                                detail={detail}
                                mode={heatmap.mode}
                                graded={graded}
                              />
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* 범례 */}
            {graded && (
              <div className="mt-6 flex flex-wrap gap-x-5 gap-y-2 text-[12px] text-ink3">
                {/* 이중 인코딩: 색 + 패턴 텍스트 */}
                <LegendItem
                  label="넉넉"
                  chip="bg-blue-50 border border-blue-200 text-over"
                  pattern="채움"
                />
                <LegendItem
                  label="적정"
                  chip="bg-indigo-50 border border-indigo-200 text-enough"
                  pattern="채움"
                />
                <LegendItem
                  label="부족"
                  chip="bg-amber-50 border-l-4 border-l-short border border-amber-200 text-ink"
                  pattern="좌4px바"
                />
                <LegendItem
                  label="중립"
                  chip="bg-surface2 border border-dashed border-line text-ink3"
                  pattern="점선"
                />
              </div>
            )}
          </div>
        )}

        <DisclaimerFooter />
      </main>
    </div>
  );
}

// ── HeatCell ────────────────────────────────────────────────────────────────

function HeatCell({
  detail,
  mode,
  graded,
}: {
  detail: HeatmapDetail;
  mode: "neutral" | "graded";
  graded: boolean;
}) {
  const cls = cellClasses(detail.status, graded);
  const label = statusLabel(detail.status, mode);
  const aria = statusAriaLabel(detail.name, detail.status, mode);

  return (
    <div
      className={`rounded-lg px-2.5 py-1.5 text-[12px] transition ${cls}`}
      aria-label={aria}
      title={aria}
    >
      <div className="font-medium leading-4">{detail.name}</div>
      {graded && (
        <div className="mt-0.5 flex items-center gap-1.5 text-[11px]">
          <span className="tnum opacity-80">
            {fmtAmount(detail.held_amount)}
          </span>
          {mode !== "neutral" && label !== "—" && (
            <span className="opacity-60">· {label}</span>
          )}
        </div>
      )}
    </div>
  );
}

// ── 서브 컴포넌트들 ──────────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  valueClass = "text-ink",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-2xl bg-surface border border-line shadow-sm px-4 py-3.5">
      <div className="text-[12px] text-ink3">{label}</div>
      <div className={`mt-1 text-[18px] font-extrabold tnum ${valueClass}`}>{value}</div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`shrink-0 px-3 py-1.5 rounded-full text-[12px] font-semibold border transition ${
        active
          ? "bg-brand text-white border-brand"
          : "bg-surface text-ink2 border-line hover:border-brand"
      }`}
    >
      {children}
    </button>
  );
}

function LegendItem({
  label,
  chip,
  pattern,
}: {
  label: string;
  chip: string;
  pattern: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-flex items-center justify-center w-5 h-5 rounded text-[9px] ${chip}`}
        aria-hidden
      />
      {label}
      <span className="text-[10px] text-muted">({pattern})</span>
    </span>
  );
}
