import React from "react";
import type { CovStatus } from "@/lib/mock";

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`rounded-2xl bg-surface border border-line shadow-sm ${className}`}>{children}</div>;
}

/** 통계 KPI 카드 — 라벨 + 큰 수치(+단위) + 증감률 배지(+초록/–빨강). 홈 상단·퍼널 셀 공용. */
export function StatCard({
  label,
  value,
  unit,
  delta,
  accent = false,
  className = "",
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  delta?: number | null;     // 전월 대비 %(있으면 배지)
  accent?: boolean;          // 강조(예: 환수 위험 > 0)
  className?: string;
}) {
  return (
    <Card className={`p-3.5 ${className}`}>
      <div className="text-[12px] text-ink3">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={`text-[20px] font-bold leading-none tnum ${accent ? "text-danger" : "text-ink"}`}>
          {value}
        </span>
        {unit && <span className="text-[12px] text-ink3">{unit}</span>}
      </div>
      {delta !== undefined && delta !== null && (
        <div
          className={`mt-1 text-[12px] font-semibold tnum ${
            delta > 0 ? "text-success" : delta < 0 ? "text-danger" : "text-muted"
          }`}
        >
          {delta > 0 ? "+" : ""}
          {delta}%
        </div>
      )}
    </Card>
  );
}

/** 리마인드 카드(환수 레이더) — 색 아이콘 칩 + 큰 카운트. tone = CSS color(var(--danger) 등). */
export function ReminderCard({
  tone,
  icon,
  label,
  count,
  unit = "명",
  className = "",
}: {
  tone: string;
  icon: React.ReactNode;
  label: string;
  count: number;
  unit?: string;
  className?: string;
}) {
  return (
    <Card className={`p-3.5 flex flex-col items-center text-center gap-1.5 ${className}`}>
      <span
        className="w-9 h-9 rounded-full flex items-center justify-center text-white text-[15px]"
        style={{ background: tone }}
        aria-hidden
      >
        {icon}
      </span>
      <span className="text-[12px] text-ink2 leading-tight">{label}</span>
      <span className="text-[20px] font-bold tnum leading-none" style={{ color: tone }}>
        {count}
        <span className="ml-0.5 text-[12px] font-normal text-ink3">{unit}</span>
      </span>
    </Card>
  );
}

// 히트맵(설계사 도구) 전용. 4단계 신호등+파랑. '설계사가 정한 기준' 대비 충족.
export function statusMeta(s: CovStatus): { dot: string; text: string; label: string } {
  switch (s) {
    case "over": return { dot: "bg-over", text: "text-over", label: "넉넉" };
    case "enough": return { dot: "bg-enough", text: "text-enough", label: "적정" };
    case "short": return { dot: "bg-short", text: "text-short", label: "부족" };
    case "none": return { dot: "bg-cnone", text: "text-cnone", label: "없음" };
  }
}

// 정직성 레드라인: 인파는 보장 적정성을 '판정·권유'하지 않음. 판단·권유는 설계사.
export function DisclaimerFooter() {
  return (
    <p className="px-1 py-5 text-[12px] leading-5 text-muted">
      이 자료는 입력된 증권 정보를 정리한 거예요. 보장이 충분한지 등 <b className="font-semibold text-ink3">판단과 권유는
      담당 설계사</b>를 통해 확인하세요. 최종 책임은 설계사에게 있습니다.
    </p>
  );
}
