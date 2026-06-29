import { Card } from "@/components/ui";
import { shareMock } from "@/lib/mock";

export default function DemoShare() {
  const s = shareMock;
  return (
    <div className="max-w-md mx-auto">
      <Card className="p-5 rounded-2xl shadow-card">
        <div className="text-[12px] text-ink3">{s.plannerName}</div>
        <h1 className="text-[20px] font-extrabold text-ink mt-1">{s.customerName}님 보장 현황</h1>
        <div className="text-[13px] text-ink2 mt-1">{s.product}</div>
        <div className="mt-2 text-[12px] text-ink3">{s.expiryText}</div>

        <div className="mt-4 rounded-xl bg-surface2 p-3">
          <div className="flex justify-between text-[13px]">
            <span className="text-ink3">월 보험료</span>
            <b className="text-ink">{s.monthly}</b>
          </div>
          <div className="flex justify-between text-[13px] mt-1.5">
            <span className="text-ink3">납입</span>
            <span className="text-ink2">{s.paidText} / 잔여 {s.remainingText}</span>
          </div>
          <div className="mt-2 h-2 rounded-full bg-line overflow-hidden">
            <div className="h-full bg-brand rounded-full" style={{ width: `${s.payProgress}%` }} />
          </div>
          <div className="text-[11px] text-ink3 mt-1 text-right">{s.payProgress}% 납입</div>
        </div>

        <div className="mt-4 text-[13px] font-bold text-ink">보장 내용</div>
        <div className="mt-1 divide-y divide-line">
          {s.coverages.map((c) => (
            <div key={c.name} className="flex justify-between py-2 text-[13px]">
              <span className="text-ink2">{c.name}</span>
              <b className="text-ink">{c.amountText}</b>
            </div>
          ))}
        </div>
      </Card>
      <p className="px-2 py-4 text-[12px] leading-5 text-muted">
        이 자료는 가입하신 증권 정보를 정리한 거예요. 보장이 충분한지 등 판단은 담당 설계사에게 확인하세요.
      </p>
    </div>
  );
}
