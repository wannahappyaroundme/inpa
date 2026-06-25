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

/** 세로 막대 — 월별 추이 등. CSS 높이로 그려 반응형·라벨 가독성 확보. 마지막 막대 강조(이번달). */
export function BarChart({
  data,
  highlightLast = true,
  format = (n) => KO.format(n),
  className = "",
}: {
  data: BarPoint[];
  highlightLast?: boolean;
  format?: (n: number) => string;
  className?: string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const lastIdx = data.length - 1;
  const aria = data.map((d) => `${d.label} ${format(d.value)}`).join(", ");
  return (
    <div className={className} role="img" aria-label={aria}>
      <div className="flex items-end gap-1.5">
        {data.map((d, i) => {
          const hot = highlightLast && i === lastIdx;
          const pct = Math.round((d.value / max) * 100);
          return (
            <div key={i} className="flex-1 flex flex-col items-center">
              {hot && (
                <span className="mb-1 text-[10px] font-semibold text-brand tnum whitespace-nowrap">
                  {format(d.value)}
                </span>
              )}
              <div className="h-24 w-full flex items-end">
                <div
                  className="w-full rounded-t-md transition-all"
                  style={{
                    height: `${Math.max(pct, 4)}%`,
                    background: hot ? "var(--brand)" : "var(--accent-tint)",
                  }}
                />
              </div>
              <span className={`mt-1 text-[10px] ${hot ? "text-brand font-semibold" : "text-ink3"}`}>
                {d.label}
              </span>
            </div>
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
