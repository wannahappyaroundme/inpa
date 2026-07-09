import React from "react";
import { InpaMark } from "./inpa-logo";

// 공개 토큰 페이지(/s·/b·/c) 공용 로딩 스켈레톤 프리미티브 (프리런치 리뷰 #14).
// ⚠️ 라이트 고정 화면 전용 — dark: 클래스 추가 금지. 기존 토큰(bg-surface2/bg-surface/border-line/
//    shadow-card/bg-line/bg-accent-tint)만 사용, 신규 색상 없음. 30~60초 웨이크 화면이 아니라
//    웜패스 도착 후 2~5초 잔여 대기용 형태 일치 스켈레톤이다(패널이 kill한 범위는 건드리지 않음).

/** 형태만 표시하는 회색 펄스 바. w/h는 tailwind 폭·높이 클래스. */
export function SkeletonBar({
  w = "w-full",
  h = "h-4",
  className = "",
}: {
  w?: string;
  h?: string;
  className?: string;
}) {
  return <div className={`${w} ${h} rounded-lg bg-line ${className}`} />;
}

/** 실제 <Card>(rounded-2xl bg-surface border border-line shadow-card)와 같은 셸의 스켈레톤 래퍼. */
export function SkeletonCard({
  className = "",
  children,
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={`rounded-2xl bg-surface border border-line shadow-card ${className}`}>
      {children}
    </div>
  );
}

/** 목록 한 줄(담보 행·빈 시간 슬롯 행 등) 전체 너비 블록. */
export function SkeletonRow({
  h = "h-12",
  className = "",
}: {
  h?: string;
  className?: string;
}) {
  return <div className={`w-full ${h} rounded-xl bg-line ${className}`} />;
}

/**
 * 공개 토큰 페이지 공통 로딩 셸 — 헤더(accent-tint) + 작은 InpaMark(live, 은은하게) +
 * (옵션) 절제된 로딩 캡션 + children(페이지별 스켈레톤 모양).
 * ★ /d의 analyzing 화면(InpaMark live intense, 대형)과는 다른 절제 수준 — 여기선 작고 조용하게만.
 */
export function TokenLoadingShell({
  children,
  mark = true,
  caption,
  headerLabel = "인파",
}: {
  children: React.ReactNode;
  mark?: boolean;
  caption?: string;
  headerLabel?: string;
}) {
  return (
    <div className="mx-auto w-full max-w-md min-h-dvh flex flex-col bg-surface2">
      <header className="px-5 pt-5 pb-3 bg-accent-tint flex items-center gap-1.5">
        {mark && <InpaMark size={18} live />}
        <span className="text-[13px] font-bold text-brand">{headerLabel}</span>
      </header>
      <main className="flex-1 px-5 pb-10">
        {caption && (
          <p className="pt-4 text-center text-[12px] text-ink3">{caption}</p>
        )}
        <div className={`animate-pulse space-y-3 ${caption ? "mt-4" : "pt-6"}`}>
          {children}
        </div>
      </main>
    </div>
  );
}
