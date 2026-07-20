"use client";

// 보험료 갱신/비갱신/적립 분리 — 표·절대수치만(판정·색·등급 없음). 사실 정리.
import { fmtWon } from "@/components/heatmap";
import type { CompareSide, HeatmapSummary, InsuranceFee } from "@/lib/api";

function Row({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-line last:border-0">
      <span className="text-[13px] text-ink2">{label}</span>
      <span className="text-[14px] font-semibold text-ink tnum">{value == null ? "-" : fmtWon(value)}</span>
    </div>
  );
}

function SummaryTable({ title, renewal, nonRenewal, earned, total }: {
  title: string; renewal: number | null; nonRenewal: number | null; earned: number | null; total: number | null;
}) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-[13px] font-bold text-ink mb-1.5">{title}</div>
      <Row label="갱신형 (갱신 시 달라질 수 있어요)" value={renewal} />
      <Row label="비갱신형 (만기까지 고정)" value={nonRenewal} />
      <Row label="적립" value={earned} />
      <div className="flex items-center justify-between pt-2 mt-1 border-t border-line">
        <span className="text-[13px] font-bold text-ink">합계</span>
        <span className="text-[15px] font-extrabold text-ink tnum">{total == null ? "-" : fmtWon(total)}</span>
      </div>
    </div>
  );
}

function DataCheckNotice({ summary }: { summary: HeatmapSummary }) {
  const mp = summary.monthly_premiums ?? 0;
  const r = summary.monthly_renewal_premium ?? 0;
  const nr = summary.monthly_non_renewal_premium ?? 0;
  const e = summary.monthly_earned_premium ?? 0;
  const gap = mp - r - nr - e;
  const overage = Math.max(0, -gap);
  const unclassified = gap > 1000 && gap > mp * 0.05 ? gap : 0;
  if (overage <= 0 && unclassified <= 0) return null;
  const msg = overage > 0
    ? `등록된 담보 보험료 합이 월 보험료보다 큽니다. 등록된 숫자를 확인해 주세요. (차이 ${fmtWon(overage)})`
    : `월 보험료 중 일부가 갱신·비갱신·적립으로 분류되지 않았어요(직접 입력 보험 포함 가능). 등록된 숫자를 확인해 주세요. (${fmtWon(unclassified)})`;
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-[12px] text-amber-800 leading-5">
      {msg}
    </div>
  );
}

function CoverageFeeList({ insurances }: { insurances: InsuranceFee[] }) {
  const withCases = insurances.filter((i) => i.case_fees.length > 0);
  const manual = insurances.filter((i) => i.case_fees.length === 0);
  return (
    <div className="space-y-3">
      {withCases.map((ins) => (
        <div key={ins.id} className="rounded-xl border border-line bg-surface">
          <div className="flex items-center justify-between px-4 py-2 border-b border-line">
            <span className="text-[13px] font-bold text-ink">{ins.name ?? "보험"}</span>
            <span className="text-[12px] text-ink3">월 {ins.monthly_premiums == null ? "-" : fmtWon(ins.monthly_premiums)}</span>
          </div>
          <div className="px-4 py-1.5">
            <div className="flex items-center text-[11px] text-ink3 py-1 border-b border-line">
              <span className="flex-1">담보</span>
              <span className="w-16 text-right">구분</span>
              <span className="w-24 text-right">월 보험료</span>
            </div>
            {ins.case_fees.map((c, i) => (
              <div key={i} className="flex items-center text-[13px] text-ink2 py-1.5 border-b border-line last:border-0">
                <span className="flex-1">{c.detail_name}</span>
                <span className="w-16 text-right text-[12px] text-ink3">{c.is_renewal ? "갱신형" : "비갱신형"}</span>
                <span className="w-24 text-right font-semibold text-ink tnum">{c.premium == null ? "-" : fmtWon(c.premium)}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
      {manual.map((ins) => (
        <div key={ins.id} className="rounded-xl border border-line bg-surface2 px-4 py-2.5 flex items-center justify-between">
          <span className="text-[13px] text-ink2">{ins.name ?? "보험"} · 직접 입력(담보 내역 없음)</span>
          <span className="text-[12px] text-ink3">월 {ins.monthly_premiums == null ? "-" : fmtWon(ins.monthly_premiums)}</span>
        </div>
      ))}
    </div>
  );
}

export function PremiumSplitSection({ summary, insurances }: { summary: HeatmapSummary; insurances: InsuranceFee[] }) {
  return (
    <section className="mt-6 space-y-3">
      <h3 className="text-[15px] font-bold text-ink">보험료 (갱신/비갱신)</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <SummaryTable title="월 보험료" renewal={summary.monthly_renewal_premium}
          nonRenewal={summary.monthly_non_renewal_premium} earned={summary.monthly_earned_premium}
          total={summary.monthly_premiums} />
        <SummaryTable title="총 보험료" renewal={summary.total_renewal_premium}
          nonRenewal={summary.total_non_renewal_premium} earned={summary.total_earned_premium}
          total={summary.total_premiums} />
      </div>
      <DataCheckNotice summary={summary} />
      <h4 className="text-[14px] font-bold text-ink pt-1">담보별 요금</h4>
      <CoverageFeeList insurances={insurances} />
    </section>
  );
}

// ── 비교분석용 갱신/비갱신 요약·증감 표 — 절대금액만, 판정 없음 ────────────────

function DeltaCell({ cur, prop }: { cur: number | null; prop: number | null }) {
  if (cur == null || prop == null) return <span className="text-ink3">-</span>;
  const d = prop - cur;
  const sign = d > 0 ? "+" : d < 0 ? "-" : "";
  return <span className="tnum text-ink2">{sign}{fmtWon(Math.abs(d))}</span>;
}

function CompareRow({ label, cur, prop }: { label: string; cur: number | null; prop: number | null }) {
  return (
    <div className="grid grid-cols-4 items-center text-[13px] py-1.5 border-b border-line last:border-0">
      <span className="text-ink2">{label}</span>
      <span className="text-right font-semibold text-ink tnum">{cur == null ? "-" : fmtWon(cur)}</span>
      <span className="text-right font-semibold text-ink tnum">{prop == null ? "-" : fmtWon(prop)}</span>
      <span className="text-right"><DeltaCell cur={cur} prop={prop} /></span>
    </div>
  );
}

export function ComparePremiumSplit({ current, proposed, labelA = "증권 A", labelB = "증권 B" }: { current: CompareSide; proposed: CompareSide; labelA?: string; labelB?: string }) {
  return (
    <section className="mt-5 rounded-xl border border-line bg-surface px-4 py-3">
      <h4 className="text-[14px] font-bold text-ink mb-2">보험료 비교 (갱신/비갱신)</h4>
      <div className="grid grid-cols-4 text-[11px] text-ink3 pb-1 border-b border-line">
        <span></span><span className="text-right">{labelA}</span><span className="text-right">{labelB}</span><span className="text-right">증감</span>
      </div>
      <div className="text-[12px] font-bold text-ink3 pt-2">월 보험료</div>
      <CompareRow label="갱신형" cur={current.monthly_renewal_premium} prop={proposed.monthly_renewal_premium} />
      <CompareRow label="비갱신형" cur={current.monthly_non_renewal_premium} prop={proposed.monthly_non_renewal_premium} />
      <CompareRow label="적립" cur={current.monthly_earned_premium} prop={proposed.monthly_earned_premium} />
      <CompareRow label="합계" cur={current.monthly_premiums} prop={proposed.monthly_premiums} />
      <div className="text-[12px] font-bold text-ink3 pt-3">총 보험료</div>
      <CompareRow label="갱신형" cur={current.total_renewal_premium} prop={proposed.total_renewal_premium} />
      <CompareRow label="비갱신형" cur={current.total_non_renewal_premium} prop={proposed.total_non_renewal_premium} />
      <CompareRow label="적립" cur={current.total_earned_premium} prop={proposed.total_earned_premium} />
      <CompareRow label="합계" cur={current.total_premiums} prop={proposed.total_premiums} />
    </section>
  );
}
