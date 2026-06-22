import { Card } from "@/components/ui";
import { compareMock } from "@/lib/mock";

const nf = new Intl.NumberFormat("ko-KR");
function amt(v: number): string {
  if (v === 0) return "없음";
  if (v >= 100_000_000) return `${nf.format(Math.round((v / 100_000_000) * 10) / 10)}억`;
  if (v >= 10_000) return `${nf.format(Math.round(v / 10_000))}만원`;
  return `${nf.format(v)}원`;
}

const DEC: Record<string, { label: string; cls: string }> = {
  SWITCH: { label: "갈아타기 권장", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  KEEP: { label: "유지 권장", cls: "bg-blue-50 text-blue-700 border-blue-200" },
  NEUTRAL: { label: "중립", cls: "bg-surface2 text-ink3 border-line" },
};

export default function DemoCompare() {
  const c = compareMock;
  const dec = DEC[c.verdict.decision];

  return (
    <div>
      <h1 className="text-[22px] font-extrabold text-ink">갈아타기 비교 — {c.customerName}님</h1>
      <p className="mt-1 text-[13px] text-ink3">기존 증권과 제안 증권의 담보·보험료를 나란히 비교합니다.</p>

      {/* 요약 2열 */}
      <div className="mt-4 grid sm:grid-cols-2 gap-3">
        <Card className="p-4">
          <div className="text-[12px] font-semibold text-ink3">기존</div>
          <div className="text-[15px] font-bold text-ink mt-0.5">{c.current.product}</div>
          <div className="mt-2 text-[13px] text-ink2">월 보험료 <b className="text-ink">{amt(c.current.monthly)}</b> · 총 납입 {amt(c.current.total)}</div>
        </Card>
        <Card className="p-4">
          <div className="text-[12px] font-semibold text-brand">제안</div>
          <div className="text-[15px] font-bold text-ink mt-0.5">{c.proposed.product}</div>
          <div className="mt-2 text-[13px] text-ink2">월 보험료 <b className="text-brand">{amt(c.proposed.monthly)}</b> · 총 납입 {amt(c.proposed.total)}</div>
        </Card>
      </div>

      {/* 담보 비교표 */}
      <Card className="mt-3 overflow-hidden">
        <div className="grid grid-cols-[1.4fr_1fr_1fr_1fr] text-[12px] font-semibold text-ink3 bg-surface2 px-4 py-2.5">
          <div>담보</div>
          <div className="text-right">기존</div>
          <div className="text-right">제안</div>
          <div className="text-right">증감</div>
        </div>
        <div className="divide-y divide-line">
          {c.rows.map((r) => {
            const d = r.proposed - r.current;
            return (
              <div key={r.coverage} className="grid grid-cols-[1.4fr_1fr_1fr_1fr] px-4 py-2.5 text-[13px] items-center">
                <div className="text-ink">{r.coverage}</div>
                <div className="text-right text-ink2 tnum">{amt(r.current)}</div>
                <div className="text-right text-ink font-semibold tnum">{amt(r.proposed)}</div>
                <div className={`text-right tnum font-semibold ${d > 0 ? "text-emerald-600" : d < 0 ? "text-rose-600" : "text-ink3"}`}>
                  {d > 0 ? "▲ " : d < 0 ? "▼ " : "– "}
                  {d !== 0 ? amt(Math.abs(d)) : ""}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* 판정 (설계사 내부 전용) */}
      <Card className="mt-3 p-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-[12px] font-bold rounded-full border px-2.5 py-0.5 ${dec.cls}`}>{dec.label}</span>
          <span className="text-[12px] text-ink3">설계사 내부 판단 근거 · 고객 노출 금지 (§97)</span>
        </div>
        <p className="mt-2 text-[13px] text-ink2 leading-5">{c.verdict.reason}</p>
        <div className="mt-2 text-[13px] text-ink2">1년 추정 순이득 <b className="text-emerald-600">+{amt(c.verdict.netBenefitYear)}</b></div>
      </Card>

      {/* 유의사항 */}
      <Card className="mt-3 p-4">
        <div className="text-[13px] font-bold text-ink mb-2">갈아타기 유의사항</div>
        <div className="space-y-2">
          {c.warnings.map((w) => (
            <div key={w.label} className="flex gap-2 text-[13px]">
              <span className="text-amber-600 shrink-0">⚠️</span>
              <div><b className="text-ink">{w.label}</b> <span className="text-ink2">{w.detail}</span></div>
            </div>
          ))}
        </div>
      </Card>

      <p className="px-1 py-5 text-[12px] leading-5 text-muted">{c.disclaimer}</p>
    </div>
  );
}
