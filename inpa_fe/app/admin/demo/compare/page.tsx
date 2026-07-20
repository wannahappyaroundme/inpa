import { Card } from "@/components/ui";
import { compareMock } from "@/lib/mock";

const nf = new Intl.NumberFormat("ko-KR");
function amt(v: number): string {
  if (v === 0) return "없음";
  if (v >= 100_000_000) return `${nf.format(Math.round((v / 100_000_000) * 10) / 10)}억`;
  if (v >= 10_000) return `${nf.format(Math.round(v / 10_000))}만원`;
  return `${nf.format(v)}원`;
}

export default function DemoCompare() {
  const c = compareMock;

  return (
    <div>
      <h1 className="text-[22px] font-extrabold text-ink">증권 비교: {c.customerName}님</h1>
      <p className="mt-1 text-[13px] text-ink3">선택한 두 증권의 담보와 보험료를 같은 기준으로 확인합니다.</p>

      {/* 요약 2열 */}
      <div className="mt-4 grid sm:grid-cols-2 gap-3">
        <Card className="p-4">
          <div className="text-[12px] font-semibold text-ink3">증권 A</div>
          <div className="text-[15px] font-bold text-ink mt-0.5">{c.current.product}</div>
          <div className="mt-2 text-[13px] text-ink2">월 보험료 <b className="text-ink">{amt(c.current.monthly)}</b> · 총 납입 {amt(c.current.total)}</div>
        </Card>
        <Card className="p-4">
          <div className="text-[12px] font-semibold text-brand">증권 B</div>
          <div className="text-[15px] font-bold text-ink mt-0.5">{c.proposed.product}</div>
          <div className="mt-2 text-[13px] text-ink2">월 보험료 <b className="text-brand">{amt(c.proposed.monthly)}</b> · 총 납입 {amt(c.proposed.total)}</div>
        </Card>
      </div>

      {/* 담보 비교표 */}
      <Card className="mt-3 overflow-hidden">
        <div className="grid grid-cols-[1.4fr_1fr_1fr_1fr] text-[12px] font-semibold text-ink3 bg-surface2 px-4 py-2.5">
          <div>담보</div>
          <div className="text-right">증권 A</div>
          <div className="text-right">증권 B</div>
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
                <div className={`text-right tnum font-semibold ${d > 0 ? "text-pos" : d < 0 ? "text-neg" : "text-ink3"}`}>
                  {d > 0 ? "▲ " : d < 0 ? "▼ " : "– "}
                  {d !== 0 ? amt(Math.abs(d)) : ""}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      <p className="px-1 py-5 text-[12px] leading-5 text-muted">인파가 등록된 보장 정보를 정리한 참고 자료입니다.</p>
    </div>
  );
}
