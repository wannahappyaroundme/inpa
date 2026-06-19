import React from "react";
import type { CovStatus } from "@/lib/mock";

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`rounded-2xl bg-surface border border-line shadow-sm ${className}`}>{children}</div>;
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
