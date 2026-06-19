"use client";

import { useState, type ReactNode } from "react";
import { heatmapMock, type CovStatus } from "@/lib/mock";
import { DisclaimerFooter } from "@/components/ui";

// 담보 한눈표 (히트맵) — 설계사 전용 도구.
// 충족 표기는 '설계사가 정한 기준' 대비. 인파가 자체 판정하지 않음(기준 출처 = 설계사).
export default function AnalysisPage() {
  const [onlyGap, setOnlyGap] = useState(false);
  const [graded, setGraded] = useState(true);

  const isGap = (s: CovStatus) => s === "short" || s === "none";
  const cats = heatmapMock
    .map((c) => ({ ...c, items: onlyGap ? c.items.filter((i) => isGap(i.status)) : c.items }))
    .filter((c) => c.items.length > 0);

  const total = heatmapMock.reduce((n, c) => n + c.items.length, 0);
  const gaps = heatmapMock.reduce((n, c) => n + c.items.filter((i) => isGap(i.status)).length, 0);

  return (
    <div className="mx-auto w-full max-w-md min-h-dvh flex flex-col">
      <header className="px-5 pt-5 pb-3 bg-surface border-b border-line">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[13px] text-ink3">김보장님 · 설계사 도구</div>
            <h1 className="text-[20px] font-extrabold text-ink">담보 한눈표</h1>
          </div>
          <button className="text-[12px] font-semibold text-brand border border-line rounded-full px-3 py-1.5">
            기준 설정 ›
          </button>
        </div>
        <p className="mt-1.5 text-[12px] text-ink3">
          <b className="text-ink2">설계사가 정한 기준</b> 대비 · 전체 <b className="text-ink2 tnum">{total}</b>개 중{" "}
          <b className="text-cnone tnum">{gaps}</b>개 보강 여지
        </p>
      </header>

      <main className="flex-1 px-5 py-4">
        {/* 필터 칩 */}
        <div className="flex gap-2 overflow-x-auto pb-1">
          <Chip active={!onlyGap} onClick={() => setOnlyGap(false)}>전체</Chip>
          <Chip active={onlyGap} onClick={() => setOnlyGap(true)}>보강 여지만</Chip>
        </div>

        {/* 뷰 세그먼트 */}
        <div className="mt-3 inline-flex rounded-xl bg-line p-1 text-[13px] font-semibold">
          <button onClick={() => setGraded(false)} className={`px-3 py-1.5 rounded-lg transition ${!graded ? "bg-surface text-ink shadow-sm" : "text-ink3"}`}>간략</button>
          <button onClick={() => setGraded(true)} className={`px-3 py-1.5 rounded-lg transition ${graded ? "bg-surface text-ink shadow-sm" : "text-ink3"}`}>상세 · 4단계</button>
        </div>

        {/* 그리드 */}
        <div className="mt-4 space-y-2.5">
          {cats.map((cat) => (
            <div key={cat.category} className="flex items-start gap-2">
              <div className="w-16 shrink-0 pt-1.5 text-[12px] font-semibold text-ink2">{cat.category}</div>
              <div className="flex flex-wrap gap-1.5">
                {cat.items.map((it) => (
                  <span key={it.name} className={`px-2.5 py-1.5 rounded-lg text-[12px] font-medium ${cellClass(it.status, graded)}`}>
                    {it.name}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* 범례 (신호등 + 안내 파랑) */}
        <div className="mt-5 flex flex-wrap gap-x-4 gap-y-2 text-[12px] text-ink3">
          <Legend className="bg-over" label="넉넉" />
          <Legend className="bg-enough" label="적정" />
          <Legend className="bg-short" label="부족" />
          <Legend className="bg-cnone" label="없음" />
        </div>

        <DisclaimerFooter />
      </main>
    </div>
  );
}

function cellClass(status: CovStatus, graded: boolean): string {
  if (!graded) return status === "none" ? "bg-cnone text-white" : "bg-line text-ink2";
  switch (status) {
    case "over": return "bg-over text-white";
    case "enough": return "bg-enough text-white";
    case "short": return "bg-short text-[#3a2a00]";
    case "none": return "bg-cnone text-white";
  }
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} className={`shrink-0 px-3.5 py-1.5 rounded-full text-[13px] font-semibold border transition ${active ? "bg-brand text-white border-brand" : "bg-surface text-ink2 border-line"}`}>
      {children}
    </button>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`w-3 h-3 rounded ${className}`} />
      {label}
    </span>
  );
}
