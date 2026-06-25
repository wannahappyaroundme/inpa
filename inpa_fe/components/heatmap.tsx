"use client";

// ════════════════════════════════════════════════════════════════════════════
// 담보 한눈표(히트맵) — 공유 렌더 컴포넌트 (/analysis 와 /customer/[id] 분석 탭 공유)
//
// 정직성 레드라인:
//  - 상태 판정은 BE 권위(FE는 status 문자열 → CSS클래스 매핑만). FE 재판정 금지.
//  - neutral 모드: '기준 미설정 — 중립 표시'. 충족/부족 단정 금지.
//  - 부족/적정/넉넉 단정은 mode='graded' 일 때만.
// ════════════════════════════════════════════════════════════════════════════

import { useState, type ReactNode } from "react";
import type { HeatmapResponse, HeatmapDetail, HeatmapStatus } from "@/lib/api";

// ── 색·패턴 매핑 (BE status → Tailwind 유틸만, inline hex 금지) ─────────────
function cellClasses(status: HeatmapStatus, graded: boolean): string {
  // 색맹 이중인코딩: 채움/좌4px바/점선 패턴 동반 (aria-label은 각 셀에)
  if (!graded) {
    return status === "neutral"
      ? "bg-surface2 border border-dashed border-line text-ink3"
      : status === "shortage"
      ? "bg-amber-50 border-l-4 border-l-short border border-line text-ink"
      : status === "adequate"
      ? "bg-surface2 border border-line text-ink2"
      : "bg-surface2 border border-line text-ink2"; // over
  }
  switch (status) {
    case "neutral":
      return "bg-surface2 border border-dashed border-line text-ink3";
    case "shortage":
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
    case "neutral":
      return "—";
    case "shortage":
      return "부족";
    case "adequate":
      return "적정";
    case "over":
      return "넉넉";
  }
}

function statusAriaLabel(
  name: string,
  status: HeatmapStatus,
  mode: "neutral" | "graded"
): string {
  if (mode === "neutral") return `${name}: 중립(기준 미설정)`;
  switch (status) {
    case "neutral":
      return `${name}: 중립`;
    case "shortage":
      return `${name}: 부족`;
    case "adequate":
      return `${name}: 적정`;
    case "over":
      return `${name}: 넉넉`;
  }
}

// ── 금액 포매터 ────────────────────────────────
const krw = new Intl.NumberFormat("ko-KR");
export function fmtAmount(val: number | null): string {
  if (val === null || val === 0) return "—";
  if (val >= 100_000_000) return `${krw.format(val / 100_000_000)}억`;
  if (val >= 10_000) return `${krw.format(val / 10_000)}만`;
  return `${krw.format(val)}원`;
}
export function fmtWon(val: number | null): string {
  if (val === null) return "—";
  return `${krw.format(val)}원`;
}

// ── 필터 타입 ──────────────────────────────────
export type FilterKey = "all" | "shortage" | "adequate" | "over" | "neutral";

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
          <span className="tnum opacity-80">{fmtAmount(detail.held_amount)}</span>
          {mode !== "neutral" && label !== "—" && (
            <span className="opacity-60">· {label}</span>
          )}
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
  const filteredTree = heatmap.tree
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
    .filter((cat) => cat.sub_categories.length > 0);

  return (
    <div>
      {/* BE 판정 모드 안내 (PM 06.24 — graded 가 왜 켜졌는지 명확화) */}
      <div className="mb-3 text-[12px] leading-5">
        {heatmap.mode === "graded" ? (
          <span className="inline-block rounded-lg bg-indigo-50 border border-indigo-200 px-2.5 py-1 text-indigo-700">
            ✓ 내 기준 {heatmap.baseline_count}개 적용 중 — 부족·적정·넉넉은 <b className="font-semibold">설정한 기준</b>에 따른 결과예요.
          </span>
        ) : (
          <span className="inline-block rounded-lg bg-surface2 border border-line px-2.5 py-1 text-ink3">
            기준 미설정(중립) — 보유 0만 표시하고 부족·충분은 단정하지 않아요. <b className="font-semibold text-ink2">설정 › 기준선</b>에서 기준을 추가하면 판정이 켜져요.
          </span>
        )}
      </div>

      {/* 뷰 세그먼트 + 필터 칩 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-xl bg-line p-1 text-[13px] font-semibold">
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
              onClick={() => onFilterChange(key)}
            >
              {label}
            </FilterChip>
          ))}
        </div>
      </div>

      {/* 그리드 */}
      <div className="mt-5">
        {filteredTree.length === 0 ? (
          <div className="py-8 text-center text-[14px] text-ink3">
            해당 조건의 담보가 없어요.
          </div>
        ) : (
          <div className="space-y-6">
            {filteredTree.map((cat) => (
              <div key={cat.category_id}>
                <div className="mb-2 flex items-center gap-2">
                  <h2 className="text-[14px] font-bold text-ink">{cat.name}</h2>
                  <span className="text-[11px] text-ink3 bg-surface2 border border-line rounded-full px-2 py-0.5">
                    {cat.insurance_type}
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

        {/* 범례 */}
        {graded && (
          <div className="mt-6 flex flex-wrap gap-x-5 gap-y-2 text-[12px] text-ink3">
            <LegendItem
              label="넉넉"
              chip="bg-blue-50 border border-blue-200 text-over"
              pattern="진한 채움"
            />
            <LegendItem
              label="적정"
              chip="bg-indigo-50 border border-indigo-200 text-enough"
              pattern="옅은 채움"
            />
            <LegendItem
              label="부족"
              chip="bg-amber-50 border-l-4 border-l-short border border-amber-200 text-ink"
              pattern="왼쪽 띠"
            />
            <LegendItem
              label="중립"
              chip="bg-surface2 border border-dashed border-line text-ink3"
              pattern="점선"
            />
          </div>
        )}
      </div>
    </div>
  );
}
