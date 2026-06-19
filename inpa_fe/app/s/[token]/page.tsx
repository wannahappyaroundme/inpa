import { shareMock as m } from "@/lib/mock";
import { Card, DisclaimerFooter } from "@/components/ui";

// A · 고객 공유뷰 (삼쩜삼형). 고객이 share_token 링크로 봄.
// ⚠️ 인파는 보험을 중개·권유하지 않음 → '납입 현황(사실)'과 '보유 담보(사실)'만. 판정 라벨 없음.
export default function SharePage() {
  return (
    <div className="mx-auto w-full max-w-md min-h-dvh flex flex-col bg-surface2">
      {/* 설계사 브랜딩 미니 헤더 */}
      <header className="px-5 pt-5 pb-3 bg-accent-tint">
        <div className="text-[13px] font-semibold text-brand">{m.plannerName}</div>
      </header>

      <main className="flex-1 px-5 pb-6">
        {/* 납입 현황 히어로 */}
        <section className="pt-6 pb-1">
          <p className="text-[15px] text-ink3">
            {m.customerName}님 · {m.product}
          </p>
          <h1 className="mt-2 text-[26px] leading-9 font-extrabold text-ink">
            만기까지 앞으로
            <br />
            <span className="text-accent">{m.remainingText}</span> 더 내면 끝이에요
          </h1>
          <p className="mt-1.5 text-[13px] text-ink3">{m.expiryText}</p>

          {/* 납입률 */}
          <div className="mt-5">
            <div className="flex justify-between text-[12px] text-ink3 mb-1.5">
              <span>납입률</span>
              <span className="font-bold text-ink2 tnum">{m.payProgress}%</span>
            </div>
            <div className="h-2.5 rounded-full bg-line overflow-hidden">
              <div className="h-full rounded-full bg-accent" style={{ width: `${m.payProgress}%` }} />
            </div>
            <div className="mt-2 flex justify-between text-[12px]">
              <span className="text-ink3">낸 보험료 <b className="text-ink2 tnum">{m.paidText}</b></span>
              <span className="text-ink3">남은 보험료 <b className="text-ink2 tnum">{m.remainingText}</b></span>
            </div>
          </div>
        </section>

        {/* KPI 카드 3 (사실) */}
        <section className="mt-5 grid grid-cols-3 gap-2.5">
          {[
            { label: "월 보험료", value: m.monthly },
            { label: "낸 보험료", value: m.paidText },
            { label: "남은 보험료", value: m.remainingText, accent: true },
          ].map((k) => (
            <Card key={k.label} className="px-3 py-3.5 text-center">
              <div className="text-[11px] text-ink3">{k.label}</div>
              <div className={`mt-1 text-[15px] font-extrabold tnum ${k.accent ? "text-accent" : "text-ink"}`}>{k.value}</div>
            </Card>
          ))}
        </section>

        {/* 보유 담보 (사실만 — 판정 없음) */}
        <section className="mt-5">
          <h2 className="text-[13px] font-semibold text-ink3 mb-2">지금 보장받는 담보</h2>
          <Card className="divide-y divide-line">
            {m.coverages.map((c) => (
              <div key={c.name} className="flex items-center gap-3 px-4 py-3">
                <div className="flex-1 min-w-0 text-[15px] font-semibold text-ink">{c.name}</div>
                <div className="text-[14px] font-bold text-ink tnum shrink-0">{c.amountText}</div>
              </div>
            ))}
          </Card>
        </section>

        {/* 설계사 배너 — 판단/권유는 설계사 몫 */}
        <section className="mt-4">
          <div className="flex items-center gap-3 rounded-2xl bg-accent-tint px-4 py-3.5">
            <div className="flex-1">
              <div className="text-[15px] font-bold text-ink">내 보장, 이대로 괜찮은지 궁금하다면</div>
              <div className="text-[13px] font-semibold text-brand">담당 설계사와 확인하기 ›</div>
            </div>
            <div className="w-9 h-9 rounded-full bg-brand/10 flex items-center justify-center text-[18px]">💬</div>
          </div>
        </section>

        <DisclaimerFooter />
      </main>

      {/* 하단 고정 CTA */}
      <div
        className="sticky bottom-0 z-20 bg-surface/95 backdrop-blur border-t border-line px-4 pt-3"
        style={{ paddingBottom: "max(14px, env(safe-area-inset-bottom))" }}
      >
        <button className="w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 active:scale-[0.99] transition">
          담당 설계사에게 물어보기
        </button>
      </div>
    </div>
  );
}
