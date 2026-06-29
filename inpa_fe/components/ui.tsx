import React from "react";
import { ArrowUpRight, ArrowDownRight, type LucideIcon } from "lucide-react";
import type { CovStatus } from "@/lib/mock";
import { InpaMark } from "./inpa-logo";
import { InfoDot } from "./info-dot";

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`rounded-2xl bg-surface border border-line shadow-card ${className}`}>{children}</div>;
}

/** 섹션 제목 — 좌측 굵은 제목 + 우측 액션(예: '칸반 보기 →'). 카드 안 머리줄 공용. */
export function SectionTitle({
  title,
  action,
  className = "",
}: {
  title: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex items-center justify-between gap-2 mb-3 ${className}`}>
      <h3 className="text-[15px] font-bold text-ink">{title}</h3>
      {action}
    </div>
  );
}

// 통계 카드 아이콘 뱃지 톤 — 전부 '우리 4색'(brand/pos=초록/neg=빨강/warn=노랑)의 soft 배경.
export type StatTone = "brand" | "pos" | "neg" | "warn";
const STAT_BADGE: Record<StatTone, string> = {
  brand: "bg-brand-soft text-brand",
  pos: "bg-pos-soft text-pos-ink",
  neg: "bg-neg-soft text-neg",
  warn: "bg-warn-soft text-warn-ink",
};

/** 통계 KPI 카드 — (옵션)컬러 아이콘 뱃지 + 라벨 + 큰 수치(+단위) + 증감률 배지(↑초록/↓빨강).
 *  icon/tone 미지정 시 뱃지 없이 동작(하위호환). 홈 상단 KPI 5개에서 아이콘과 함께 사용. */
export function StatCard({
  label,
  value,
  unit,
  delta,
  accent = false,
  hint,
  icon: Icon,
  tone = "brand",
  className = "",
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  delta?: number | null;     // 전월 대비 %(있으면 배지)
  accent?: boolean;          // 강조(예: 환수 위험 > 0) — 숫자·뱃지를 빨강 톤으로
  hint?: string;             // 라벨 옆 ? 툴팁(용어 풀이 — 쉬운말)
  icon?: LucideIcon;         // 컬러 아이콘 뱃지(lucide). 없으면 뱃지 생략
  tone?: StatTone;           // 뱃지 톤(brand/pos/neg/warn) — 우리 4색 soft
  className?: string;
}) {
  const badgeTone = accent ? "neg" : tone;
  return (
    <Card className={`p-4 flex items-start gap-3 ${className}`}>
      {Icon && (
        <span className={`shrink-0 w-11 h-11 rounded-xl grid place-items-center ${STAT_BADGE[badgeTone]}`} aria-hidden>
          <Icon className="w-[22px] h-[22px]" strokeWidth={2} />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-[12px] font-medium text-ink3">
          <span className="truncate">{label}</span>
          {hint && <InfoDot text={hint} />}
        </div>
        <p className="mt-1 flex items-baseline gap-1">
          <span className={`text-[22px] sm:text-[26px] lg:text-[28px] font-extrabold leading-none tnum tracking-tight ${accent ? "text-danger" : "text-ink"}`}>
            {value}
          </span>
          {unit && <span className="text-[12px] font-medium text-ink3">{unit}</span>}
        </p>
        {delta !== undefined && delta !== null && (
          <span
            className={`mt-1.5 inline-flex items-center gap-0.5 text-[12px] font-semibold tnum ${
              delta > 0 ? "text-pos-ink" : delta < 0 ? "text-neg" : "text-muted"
            }`}
          >
            {delta > 0 ? <ArrowUpRight className="w-3.5 h-3.5" strokeWidth={2.5} /> : delta < 0 ? <ArrowDownRight className="w-3.5 h-3.5" strokeWidth={2.5} /> : null}
            {delta > 0 ? "+" : ""}
            {delta}%
          </span>
        )}
      </div>
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
      이 자료는 입력된 증권 정보를 정리한 참고 자료예요. <b className="font-semibold text-ink3">보장 충분 여부의 판단과
      고객 안내는 설계사님이 직접</b> 해주세요.
    </p>
  );
}

// 고객 아바타 파스텔 팔레트 (무지개 + 회색조, 저채도). Customer.color 에 hex 저장(빈값 = 인파 로고).
export const AVATAR_PALETTE = [
  "#F8D7DD", "#FCE2CF", "#FBF0C9", "#DDEEDC", "#D6EAF1",
  "#DFE1FA", "#ECDDF3", "#E7E9ED", "#D5D8DE",
];

/** 고객 아바타 (PM 06.27):
 *  · 글씨(label) 있으면 → 글씨를 배경색 위에.
 *  · 글씨 없으면 → 인파 로고를 배경색 위에(배경색 없으면 기본 틴트). = 기본 로고 + 뒷배경만 바꾸기.
 *  배경색(color)은 두 경우 모두 적용. 빈값이면 기본 틴트. */
export function CustomerAvatar({
  label,
  color,
  size = 44,
}: {
  label?: string | null;
  color?: string | null;
  size?: number;
}) {
  const text = (label ?? "").trim();
  const bg = color || "var(--accent-tint)";
  if (text) {
    return (
      <div
        className="rounded-full flex items-center justify-center font-bold shrink-0 text-ink2 leading-none"
        style={{ width: size, height: size, backgroundColor: bg, fontSize: Math.round(size * 0.36) }}
      >
        {text.slice(0, 3)}
      </div>
    );
  }
  return (
    <div
      className="rounded-full flex items-center justify-center shrink-0"
      style={{ width: size, height: size, backgroundColor: bg }}
    >
      <InpaMark size={Math.round(size * 0.56)} />
    </div>
  );
}

/** 방치 경보 레벨 — 최종 연락일(없으면 등록일) 기준 7일↑ red / 3일↑ amber / 그 외 null. */
export function stalenessLevel(
  lastContactedAt: string | null,
  createdAt?: string
): "red" | "amber" | null {
  const ref = lastContactedAt || createdAt;
  if (!ref) return null;
  const days = (Date.now() - new Date(ref).getTime()) / 86_400_000;
  if (days >= 7) return "red";
  if (days >= 3) return "amber";
  return null;
}
