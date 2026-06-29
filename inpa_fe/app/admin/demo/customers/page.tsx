import { Card } from "@/components/ui";
import { customers } from "@/lib/mock";

export default function DemoCustomers() {
  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-[22px] font-extrabold text-ink">
          고객 <span className="text-ink3 tnum">{customers.length}</span>
        </h1>
        <span className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5 opacity-70">+ 고객 등록</span>
      </div>

      <div className="mt-4 w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-muted">
        이름·연락처 검색
      </div>

      <div className="mt-4 grid sm:grid-cols-2 gap-3">
        {customers.map((c) => (
          <Card key={c.id} className="p-4 flex items-center gap-3">
            <div className="w-11 h-11 rounded-full flex items-center justify-center text-[16px] font-bold shrink-0 text-brand bg-accent-tint">
              {c.name[0]}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[16px] font-bold text-ink">{c.name}</span>
                <span className="text-[12px] text-ink3">{c.age}세 · {c.gender}</span>
                {c.expirySoon && (
                  <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-neg-soft text-danger">만기 임박</span>
                )}
              </div>
              <div className="text-[12px] text-ink3 mt-0.5">
                계약 {c.policies}건 · 월 {c.premium} · {c.lastContact}
              </div>
            </div>
            <span className="text-[12px] font-semibold text-brand shrink-0">분석 ›</span>
          </Card>
        ))}
      </div>
    </div>
  );
}
