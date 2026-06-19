import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { customers } from "@/lib/mock";

// 고객 관리(CRM). 목록·검색·등록. 데스크톱 2열 반응형.
export default function CustomersPage() {
  return (
    <div className="min-h-dvh">
      <AppNav active="customers" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <div className="flex items-center justify-between">
          <h1 className="text-[22px] font-extrabold text-ink">
            고객 <span className="text-ink3 tnum">{customers.length}</span>
          </h1>
          <button className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5">+ 고객 등록</button>
        </div>

        <div className="mt-4">
          <input
            placeholder="이름·연락처 검색"
            className="w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
          />
        </div>

        <div className="mt-4 grid sm:grid-cols-2 gap-3">
          {customers.map((c) => (
            <Card key={c.id} className="p-4 flex items-center gap-3">
              <div className="w-11 h-11 rounded-full bg-accent-tint text-brand flex items-center justify-center text-[16px] font-bold shrink-0">
                {c.name[0]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[16px] font-bold text-ink">{c.name}</span>
                  <span className="text-[12px] text-ink3">{c.age}세 · {c.gender}</span>
                  {c.expirySoon && (
                    <span className="text-[11px] font-semibold text-cnone bg-cnone/10 rounded-full px-2 py-0.5">만기 임박</span>
                  )}
                </div>
                <div className="text-[12px] text-ink3 mt-0.5">
                  보험 {c.policies}건 · 월 {c.premium} · {c.lastContact} 연락
                </div>
              </div>
              <Link href="/analysis" className="text-[12px] font-semibold text-brand shrink-0">분석 ›</Link>
            </Card>
          ))}
        </div>
      </main>
    </div>
  );
}
