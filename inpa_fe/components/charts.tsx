// 경량 차트 — 외부 라이브러리 0. 도넛/라인 = SVG, 막대 = CSS 높이(라벨 가독성·반응형 유리).
// 색은 토큰 CSS 변수(var(--brand) 등)를 직접 받는다(라이트 고정 가드레일 준수).
// 접근성: 각 차트 role="img" + aria-label에 핵심 수치를 텍스트로 병기(스크린리더·폴백).
import React from "react";

const KO = new Intl.NumberFormat("ko-KR");

export interface DonutSegment {
  label: string;
  value: number;
  color: string; // CSS color (예: "var(--danger)")
}

/** 도넛(원형) — 보유계약 유지현황·고객 구성 등. 범례는 부모가 segments로 별도 렌더. */
export function DonutChart({
  segments,
  centerValue,
  centerLabel,
  className = "",
}: {
  segments: DonutSegment[];
  centerValue?: string;
  centerLabel?: string;
  className?: string;
}) {
  const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0);
  const R = 50;
  const C = 2 * Math.PI * R;
  const label =
    total > 0
      ? segments.filter((s) => s.value > 0).map((s) => `${s.label} ${s.value}`).join(", ")
      : "데이터 없음";

  let acc = 0;
  return (
    <div className={`relative ${className}`}>
      <svg viewBox="0 0 120 120" className="w-full h-auto" role="img" aria-label={label}>
        {/* 배경 링 */}
        <circle cx="60" cy="60" r={R} fill="none" stroke="var(--line)" strokeWidth="16" />
        {total > 0 &&
          segments.map((s, i) => {
            const frac = Math.max(0, s.value) / total;
            const len = frac * C;
            const seg = (
              <circle
                key={i}
                cx="60"
                cy="60"
                r={R}
                fill="none"
                stroke={s.color}
                strokeWidth="16"
                strokeDasharray={`${len} ${C - len}`}
                strokeDashoffset={-acc}
                transform="rotate(-90 60 60)"
              />
            );
            acc += len;
            return seg;
          })}
      </svg>
      {(centerValue || centerLabel) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
          {centerLabel && <span className="text-[11px] text-ink3">{centerLabel}</span>}
          {centerValue && <span className="text-[15px] font-bold text-ink tnum">{centerValue}</span>}
        </div>
      )}
    </div>
  );
}

export interface BarPoint {
  label: string;
  value: number;
}

/** 세로 막대 — 월별 추이 등. CSS 높이로 그려 반응형·라벨 가독성 확보. 마지막 막대 강조(이번달).
 *  targetLine: 회색 수평 보조선(월별 목표 대표값 — 평균 또는 최신).
 *  averageLine: 파란 수평 보조선(기간 평균).
 */
export function BarChart({
  data,
  highlightLast = true,
  format = (n) => KO.format(n),
  targetLine,
  averageLine,
  className = "",
  heightClass = "h-24",
}: {
  data: BarPoint[];
  highlightLast?: boolean;
  format?: (n: number) => string;
  targetLine?: number;
  averageLine?: number;
  className?: string;
  heightClass?: string;   // 막대 영역 높이(예: 'h-24' 기본 / 'h-44' 더 높게)
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const total = data.reduce((s, d) => s + Math.max(0, d.value), 0);
  const lastIdx = data.length - 1;
  const aria = total > 0 ? data.map((d) => `${d.label} ${format(d.value)}`).join(", ") : "데이터 없음";

  // 전체 0 → 막대를 똑같은 작은 그루터기로 그리면 '데이터 있음'처럼 보임 → 빈상태로 명시
  if (total === 0) {
    return (
      <div className={className} role="img" aria-label={aria}>
        <div className={`${heightClass} flex items-center justify-center text-[12px] text-ink3`}>데이터가 아직 없어요</div>
        <div className="flex gap-1.5 mt-1">
          {data.map((d, i) => (
            <span key={i} className="flex-1 text-center text-[10px] text-ink3">{d.label}</span>
          ))}
        </div>
      </div>
    );
  }

  // 수평 보조선 y 위치 계산 — 막대 영역 h-24(96px), items-end 기준으로 value/max가 100%
  // pct = value/max * 100; y_from_top = (1 - pct/100) * 96px
  const lineY = (value: number) => {
    const clampedPct = Math.min(value / max, 1);  // max 초과 시 상단에 클램프
    return `${(1 - clampedPct) * 100}%`;
  };

  return (
    <div className={className} role="img" aria-label={aria}>
      {/* 막대 영역 — relative 래퍼가 높이 기준(보조선 오버레이 좌표 기준). heightClass='h-full'이면 부모를 채움. */}
      <div className={`relative ${heightClass}`}>
        <div className="flex items-end gap-1.5 h-full">
          {data.map((d, i) => {
            const hot = highlightLast && i === lastIdx;
            const pct = Math.round((d.value / max) * 100);
            return (
              <div key={i} className="relative flex-1 h-full flex items-end">
                <div
                  className="w-full rounded-t-md transition-all relative"
                  style={{
                    height: `${Math.max(pct, 4)}%`,
                    background: hot ? "var(--brand)" : "var(--accent-tint)",
                  }}
                >
                  {hot && d.value > 0 && (
                    <span className="absolute top-1 left-1/2 -translate-x-1/2 text-[9px] font-bold text-white tnum whitespace-nowrap">
                      {format(d.value)}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* 수평 보조선 — 막대 영역(96px)에 정확히 매핑(inset-0, 월 라벨 좌표계 밖) */}
        {(targetLine !== undefined || averageLine !== undefined) && (
          <div className="absolute inset-0 pointer-events-none">
            {targetLine !== undefined && targetLine > 0 && (
              <div
                className="absolute left-0 right-0 flex items-center"
                style={{ top: lineY(targetLine) }}
              >
                <div className="flex-1 border-t border-dashed" style={{ borderColor: "var(--ink3, #9ca3af)" }} />
                <span className="ml-1 text-[9px] font-medium whitespace-nowrap" style={{ color: "var(--ink3, #9ca3af)" }}>
                  목표 {format(targetLine)}
                </span>
              </div>
            )}
            {averageLine !== undefined && averageLine > 0 && (
              <div
                className="absolute left-0 right-0 flex items-center"
                style={{ top: lineY(averageLine) }}
              >
                <div className="flex-1 border-t border-dashed" style={{ borderColor: "var(--accent)" }} />
                <span className="ml-1 text-[9px] font-medium whitespace-nowrap" style={{ color: "var(--accent)" }}>
                  평균 {format(averageLine)}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 월 라벨 — 막대와 분리(보조선 좌표계 밖) */}
      <div className="flex gap-1.5 mt-1">
        {data.map((d, i) => {
          const hot = highlightLast && i === lastIdx;
          return (
            <span key={i} className={`flex-1 text-center text-[10px] ${hot ? "text-brand font-semibold" : "text-ink3"}`}>
              {d.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export interface LineSeries {
  label: string;
  color: string;
  points: number[];
}

/** 라인 비교(기존 vs 제안) — 006. analysis 비교탭 연결은 후순위, 컴포넌트만 선제작. */
export function LineCompareChart({
  series,
  xLabels = [],
  className = "",
}: {
  series: LineSeries[];
  xLabels?: string[];
  className?: string;
}) {
  const W = 100;
  const H = 48;
  const all = series.flatMap((s) => s.points);
  const max = Math.max(1, ...all);
  const n = Math.max(1, ...series.map((s) => s.points.length));
  const x = (i: number) => (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v: number) => H - (v / max) * (H - 6) - 3;
  const aria = series.map((s) => `${s.label}`).join(" 대 ");
  return (
    <div className={className}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label={aria}>
        {series.map((s, si) => (
          <polyline
            key={si}
            fill="none"
            stroke={s.color}
            strokeWidth="1.5"
            strokeLinejoin="round"
            strokeLinecap="round"
            points={s.points.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
          />
        ))}
      </svg>
      {xLabels.length > 0 && (
        <div className="flex justify-between mt-1 text-[10px] text-ink3">
          {xLabels.map((l, i) => (
            <span key={i}>{l}</span>
          ))}
        </div>
      )}
    </div>
  );
}

export interface CompareBarItem {
  label: string;
  current: number;
  proposed: number;
}

/** 기존 vs 제안 그룹 막대 — 담보별 2줄(기존 청록·제안 파랑). 행마다 max로 스케일해 증감을
    한눈에. 정확 수치는 같이 표시 + 아래 비교표. 라인보다 범주형 비교에 적합(006). */
export function CompareBarChart({
  items,
  format = (n) => KO.format(n),
  className = "",
}: {
  items: CompareBarItem[];
  format?: (n: number) => string;
  className?: string;
}) {
  const aria = items
    .map((it) => `${it.label} 증권 A ${format(it.current)} 증권 B ${format(it.proposed)}`)
    .join(", ");
  const Bar = ({ w, color, val }: { w: number; color: string; val: string }) => (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2.5 rounded-full bg-surface2 overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${w}%`, background: color }} />
      </div>
      <span className="w-16 shrink-0 text-right text-[10px] tnum text-ink3">{val}</span>
    </div>
  );
  return (
    <div className={className} role="img" aria-label={aria}>
      <div className="space-y-3">
        {items.map((it, i) => {
          const m = Math.max(1, it.current, it.proposed);
          return (
            <div key={i}>
              <div className="text-[11px] font-medium text-ink2 truncate mb-1">{it.label}</div>
              <div className="space-y-1">
                <Bar w={(it.current / m) * 100} color="var(--existing)" val={format(it.current)} />
                <Bar w={(it.proposed / m) * 100} color="var(--proposal)" val={format(it.proposed)} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
