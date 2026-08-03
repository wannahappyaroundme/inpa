"use client";

import { useState, type FormEvent } from "react";

import { computeInsuranceAge } from "@/lib/insurance-age";
import { trackPublicResourceUse } from "@/lib/public-resource-events";

function currentKstDate(): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

export function InsuranceAgeCalculator() {
  const [birthDate, setBirthDate] = useState("");
  const [asOf, setAsOf] = useState(currentKstDate);
  const [result, setResult] = useState<number | null>(null);
  const [attempted, setAttempted] = useState(false);

  function calculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAttempted(true);
    const nextResult = computeInsuranceAge(birthDate, asOf);
    setResult(nextResult);
    if (nextResult !== null) {
      trackPublicResourceUse("insurance_age", "calculate", "tool");
    }
  }

  function reset() {
    setBirthDate("");
    setAsOf(currentKstDate());
    setResult(null);
    setAttempted(false);
  }

  return (
    <section className="rounded-3xl border border-line bg-surface p-5 shadow-card sm:p-8" aria-labelledby="insurance-age-calculator-title">
      <div className="max-w-2xl">
        <p className="text-[12px] font-extrabold tracking-[0.14em] text-brand">바로 계산하기</p>
        <h2 id="insurance-age-calculator-title" className="mt-2 text-[26px] font-black text-brand-ink sm:text-[30px]">보험나이 계산</h2>
      </div>

      <form onSubmit={calculate} noValidate className="mt-7">
        <div className="grid gap-5 sm:grid-cols-2">
          <label className="block text-[13px] font-bold text-ink2">
            생년월일
            <input
              type="date"
              value={birthDate}
              max={asOf || undefined}
              onChange={(event) => setBirthDate(event.target.value)}
              className="mt-2 min-h-[48px] w-full rounded-xl border border-line bg-white px-3 text-[15px] text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
          </label>
          <label className="block text-[13px] font-bold text-ink2">
            기준일
            <input
              type="date"
              value={asOf}
              onChange={(event) => setAsOf(event.target.value)}
              className="mt-2 min-h-[48px] w-full rounded-xl border border-line bg-white px-3 text-[15px] text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
          </label>
        </div>

        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <button type="submit" className="min-h-[50px] rounded-xl bg-brand px-6 py-3 text-[14px] font-black text-white transition hover:opacity-90">
            보험나이 계산하기
          </button>
          <button type="button" onClick={reset} className="min-h-[50px] rounded-xl border border-line bg-white px-6 py-3 text-[14px] font-bold text-ink2 transition hover:border-brand hover:text-brand">
            입력 초기화
          </button>
        </div>
      </form>

      <div className="mt-7 min-h-[150px] rounded-2xl bg-canvas p-5 sm:p-6" aria-live="polite">
        {!attempted ? (
          <div>
            <p className="text-[16px] font-extrabold text-brand-ink">생년월일과 기준일을 입력하면 바로 확인할 수 있어요.</p>
            <p className="mt-2 text-[13px] leading-6 text-ink3">기준일은 오늘로 채워져 있으며 원하는 날짜로 바꿀 수 있습니다.</p>
          </div>
        ) : result === null ? (
          <div role="alert">
            <p className="text-[16px] font-extrabold text-brand-ink">날짜를 확인하면 바로 계산할 수 있어요.</p>
            <p className="mt-2 text-[13px] leading-6 text-ink3">생년월일은 기준일과 같거나 이전 날짜로 입력해 주세요.</p>
          </div>
        ) : (
          <div>
            <p className="text-[13px] font-bold text-ink3">계산 결과</p>
            <p className="mt-1 text-[42px] font-black tracking-tight text-brand-ink">{result}세</p>
            <p className="mt-3 text-[13px] leading-6 text-ink3">
              만나이를 기준으로 마지막 생일부터 6개월이 지났으면 한 살을 더해 계산했습니다.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
