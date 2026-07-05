"use client";

// ════════════════════════════════════════════════════════════════════════════
// 담보 한눈표(히트맵) — 공유 렌더 컴포넌트 (/analysis 와 /customer/[id] 분석 탭 공유)
//
// 정직성 레드라인:
//  - 상태 판정은 BE 권위(FE는 status 문자열 → CSS클래스 매핑만). FE 재판정 금지.
//  - 기준 미설정(mode='neutral')이면 부족/적정/넉넉을 아예 표시하지 않는다(색·라벨 없음).
//    '중립'이라고 적는 대신, 기준을 정하라는 안내(CTA)로 유도 — PM 06.29.
//  - 신호등 색: 넉넉=초록 / 적정=노랑 / 부족=빨강 (PM 06.29).
// ════════════════════════════════════════════════════════════════════════════

import { useState, type ReactNode } from "react";
import Link from "next/link";
import type { HeatmapResponse, HeatmapDetail, HeatmapStatus } from "@/lib/api";

// ── 색 매핑 (BE status → Tailwind 신호등) ─────────────
// 기준 미설정(neutral 모드)이면 판정색을 칠하지 않고 담백한 기본 셀로 둔다.
function cellClasses(status: HeatmapStatus, mode: "neutral" | "graded"): string {
  if (mode === "neutral") return "bg-surface2 border border-line text-ink2";
  switch (status) {
    case "shortage": // 부족 = 빨강
      return "bg-rose-50 border border-rose-200 border-l-4 border-l-cnone text-rose-700 font-semibold";
    case "adequate": // 적정 = 노랑
      return "bg-amber-50 border border-amber-200 text-amber-800 font-semibold";
    case "over": // 넉넉 = 초록
      return "bg-emerald-50 border border-emerald-200 text-emerald-700 font-semibold";
    case "neutral":
      return "bg-surface2 border border-line text-ink2";
  }
}

function statusLabel(status: HeatmapStatus, mode: "neutral" | "graded"): string {
  if (mode === "neutral") return "";
  switch (status) {
    case "shortage":
      return "부족";
    case "adequate":
      return "적정";
    case "over":
      return "넉넉";
    case "neutral":
      return "";
  }
}

function statusAriaLabel(
  name: string,
  status: HeatmapStatus,
  mode: "neutral" | "graded"
): string {
  if (mode === "neutral") return `${name}: 보유 여부만 표시(기준 미설정)`;
  switch (status) {
    case "shortage":
      return `${name}: 부족`;
    case "adequate":
      return `${name}: 적정`;
    case "over":
      return `${name}: 넉넉`;
    case "neutral":
      return name;
  }
}

// ── 금액 포매터 ────────────────────────────────
const krw = new Intl.NumberFormat("ko-KR");
export function fmtAmount(val: number | null): string {
  if (val === null || val === 0) return "-";
  if (val >= 100_000_000) return `${krw.format(val / 100_000_000)}억`;
  if (val >= 10_000) return `${krw.format(val / 10_000)}만`;
  return `${krw.format(val)}원`;
}
export function fmtWon(val: number | null): string {
  if (val === null) return "-";
  return `${krw.format(val)}원`;
}

// ── 필터 타입 (중립 제거 — PM 06.29) ──────────────────────────────────
export type FilterKey = "all" | "shortage" | "adequate" | "over";

// ── HeatCell ──────────────────────────────────────────────────────────────
export function HeatCell({
  detail,
  mode,
  graded,
}: {
  detail: HeatmapDetail;
  mode: "neutral" | "graded";
  graded: boolean;
}) {
  const cls = cellClasses(detail.status, mode);
  const label = statusLabel(detail.status, mode);
  const aria = statusAriaLabel(detail.name, detail.status, mode);

  return (
    <div
      className={`rounded-lg px-3 py-2 text-[13px] transition ${cls}`}
      aria-label={aria}
      title={aria}
    >
      <div className="font-semibold leading-4">{detail.name}</div>
      {graded && (
        <div className="mt-1 flex items-center gap-1.5 text-[11px]">
          <span className="tnum opacity-80">{fmtAmount(detail.held_amount)}</span>
          {label && <span className="opacity-70">· {label}</span>}
        </div>
      )}
    </div>
  );
}

// ── FilterChip ────────────────────────────────────────────────────────────
export function FilterChip({
  active,
  onClick,
  children,
  title,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
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

// ── KpiCard ───────────────────────────────────────────────────────────────
export function KpiCard({
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
      <div className={`mt-1 text-[18px] font-extrabold tnum ${valueClass}`}>
        {value}
      </div>
    </div>
  );
}

// ── LegendItem ────────────────────────────────────────────────────────────
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

// ── HeatmapGrid ── 트리 → 카테고리/서브카테고리/셀 그리드 + 필터 + 범례 ─────
export function HeatmapGrid({
  heatmap,
  graded,
  onGradedChange,
  filter,
  onFilterChange,
}: {
  heatmap: HeatmapResponse;
  graded: boolean;
  onGradedChange: (g: boolean) => void;
  filter: FilterKey;
  onFilterChange: (f: FilterKey) => void;
}) {
  // 보장 있는 것만 보기 토글(내부 상태) — held_amount>0 인 담보만. 기본 false(전체).
  const [coverageOnly, setCoverageOnly] = useState(false);
  // 기준 미설정 상태에서 넉넉/적정/부족을 누르면 '먼저 기준을 설정' 안내를 띄운다(PM 07.01).
  const [gateNotice, setGateNotice] = useState(false);

  const filteredTree = heatmap.tree
    .map((cat) => ({
      ...cat,
      sub_categories: cat.sub_categories
        .map((sub) => ({
          ...sub,
          details: sub.details.filter((d) => {
            const statusOk = filter === "all" ? true : d.status === filter;
            const heldOk = coverageOnly ? (d.held_amount ?? 0) > 0 : true;
            return statusOk && heldOk;
          }),
        }))
        .filter((sub) => sub.details.length > 0),
    }))
    .filter((cat) => cat.sub_categories.length > 0);

  // 카테고리별 '보유 담보 수'(held_amount>0) — 배지에 표시(보장 내역과 일치, 필터 무관 전체 기준).
  const heldByCat = new Map<number, number>();
  for (const cat of heatmap.tree) {
    let n = 0;
    for (const sub of cat.sub_categories)
      for (const d of sub.details) if ((d.held_amount ?? 0) > 0) n++;
    heldByCat.set(cat.category_id, n);
  }
  // 제로 상태 구분 — 보험은 등록됐는데 읽힌 담보가 0개(스캔이 담보를 못 읽었거나 매칭 0).
  // '보험 0건' 빈 상태(호출부에서 처리)와 다른 케이스라 별도 안내를 띄운다. 판정어 없음.
  const totalHeld = Array.from(heldByCat.values()).reduce((s, n) => s + n, 0);
  const noHeldCoverage = heatmap.insurance_count > 0 && totalHeld === 0;

  return (
    <div>
      {/* BE 판정 모드 안내 — 기준 있으면 적용중, 없으면 기준 설정으로 유도(PM 06.29: '중립' 표기 제거) */}
      <div className="mb-3 text-[12px] leading-5">
        {heatmap.mode === "graded" ? (
          <span className="inline-block rounded-lg bg-emerald-50 border border-emerald-200 px-2.5 py-1 text-emerald-800">
            ✓ 내 기준 {heatmap.baseline_count}개 적용 중. 넉넉·적정·부족은 <b className="font-semibold">설정한 기준</b>에 따른 결과예요.
          </span>
        ) : (
          <Link
            href="/settings/baseline"
            className="flex items-center justify-between gap-2 rounded-xl bg-surface2 border border-line px-3.5 py-2.5 hover:border-brand transition"
          >
            <span className="text-ink2">
              기준을 정하면 <b className="text-ink">넉넉·적정·부족</b>을 색으로 한눈에 볼 수 있어요. (지금은 보유 내역만 표시돼요)
            </span>
            <span className="shrink-0 text-[12px] font-semibold text-brand whitespace-nowrap">기준 설정하기 ›</span>
          </Link>
        )}
      </div>

      {/* 담보 0개 안내 — 보험은 있는데 읽힌 담보가 없을 때(보험 0건 빈 상태와 구분) */}
      {noHeldCoverage && (
        <div className="mb-3 rounded-xl border border-line bg-surface2 px-3.5 py-2.5 text-[12px] text-ink2">
          등록된 보험에서 담보를 아직 읽지 못했어요. 증권을 다시 올리거나 직접 입력으로 채울 수 있어요.
        </div>
      )}

      {/* 뷰 세그먼트 + 보유 토글 + 상태 필터 칩 — 모바일 1줄(가로스크롤), 데스크탑 2단 */}
      <div className="flex flex-nowrap items-center gap-2 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible sm:pb-0">
        {/* 1단: 간략/상세 세그먼트 */}
        <div className="inline-flex shrink-0 rounded-xl bg-line p-1 text-[13px] font-semibold">
          <button
            onClick={() => onGradedChange(false)}
            className={`px-3 py-1.5 rounded-lg transition ${
              !graded ? "bg-surface text-ink shadow-sm" : "text-ink3"
            }`}
          >
            간략
          </button>
          <button
            onClick={() => onGradedChange(true)}
            className={`px-3 py-1.5 rounded-lg transition ${
              graded ? "bg-surface text-ink shadow-sm" : "text-ink3"
            }`}
          >
            상세
          </button>
        </div>

        {/* 1단: 보장 있는 것만 보기 토글(한 개) — 끄면 빈 칸까지 전체 */}
        <button
          onClick={() => setCoverageOnly((v) => !v)}
          aria-pressed={coverageOnly}
          title={coverageOnly ? "빈 칸까지 전체 보기" : "보장 있는 담보만 보기"}
          className={`shrink-0 inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-[12px] font-semibold border transition ${
            coverageOnly
              ? "bg-brand text-white border-brand"
              : "bg-surface text-ink2 border-line hover:border-brand"
          }`}
        >
          <span aria-hidden>{coverageOnly ? "✓" : "◰"}</span>
          보장 있는 것만
        </button>

        {/* 데스크탑에서만 줄바꿈 → 상태 필터를 2단(아래 줄)으로 */}
        <div className="hidden sm:block sm:basis-full" aria-hidden />

        {/* 2단: 상태 필터 칩 */}
        <div className="flex shrink-0 gap-2">
          {(
            [
              { key: "all", label: "전체" },
              { key: "over", label: "넉넉" },
              { key: "adequate", label: "적정" },
              { key: "shortage", label: "부족" },
            ] as { key: FilterKey; label: string }[]
          ).map(({ key, label }) => (
            <FilterChip
              key={key}
              active={filter === key}
              title={heatmap.mode !== "graded" && key !== "all" ? "보장 기준을 먼저 설정해 주세요." : undefined}
              onClick={() => {
                // 기준 미설정이면 넉넉/적정/부족은 판정이 없으므로 필터 대신 기준 설정으로 유도.
                if (heatmap.mode !== "graded" && key !== "all") { setGateNotice(true); return; }
                setGateNotice(false);
                onFilterChange(key);
              }}
            >
              {label}
            </FilterChip>
          ))}
        </div>
      </div>

      {/* 기준 미설정 상태에서 판정 필터를 누른 경우 — 기준 설정으로 유도(부정어 없이 다음 단계로) */}
      {gateNotice && heatmap.mode !== "graded" && (
        <div className="mt-3 flex items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-[12px]">
          <span className="text-amber-800">보장 기준을 먼저 설정해 주세요. 그러면 넉넉·적정·부족을 색으로 볼 수 있어요.</span>
          <Link href="/settings/baseline" className="shrink-0 font-semibold text-brand whitespace-nowrap">기준 설정하기 ›</Link>
        </div>
      )}

      {/* 그리드 */}
      <div className="mt-5">
        {filteredTree.length === 0 ? (
          <div className="py-8 text-center text-[14px] text-ink3">
            해당 조건의 담보가 없어요.
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 gap-x-6 gap-y-6">
            {filteredTree.map((cat) => (
              <div key={cat.category_id}>
                <div className="mb-2 flex items-center gap-2">
                  <h2 className="text-[14px] font-bold text-ink">{cat.name}</h2>
                  <span className="text-[11px] text-ink3 bg-surface2 border border-line rounded-full px-2 py-0.5">
                    보유 {heldByCat.get(cat.category_id) ?? 0}개
                  </span>
                </div>

                <div className="space-y-3">
                  {cat.sub_categories.map((sub) => (
                    <div
                      key={sub.sub_category_id}
                      className="flex items-start gap-2"
                    >
                      <div className="w-20 sm:w-24 shrink-0 pt-2 text-[12px] font-semibold text-ink2 leading-4">
                        {sub.name}
                      </div>
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

        {/* 범례 — 신호등 3색(중립 제거, PM 06.29). 기준 적용 모드에서만 노출. */}
        {graded && heatmap.mode === "graded" && (
          <div className="mt-6 flex flex-wrap gap-x-5 gap-y-2 text-[12px] text-ink3">
            <LegendItem
              label="넉넉"
              chip="bg-emerald-50 border border-emerald-200"
              pattern="초록"
            />
            <LegendItem
              label="적정"
              chip="bg-amber-50 border border-amber-200"
              pattern="노랑"
            />
            <LegendItem
              label="부족"
              chip="bg-rose-50 border-l-4 border-l-cnone border border-rose-200"
              pattern="빨강"
            />
          </div>
        )}
      </div>
    </div>
  );
}
