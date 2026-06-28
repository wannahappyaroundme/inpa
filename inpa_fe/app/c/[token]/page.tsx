"use client";

// 고객 본인 동의 (공개·비로그인) — 다항목(개인정보·마케팅·국외이전) P3c.
// ★ 명시 체크박스 + 버튼(사전체크·자동제출 금지). 필수 항목 모두 체크해야 제출 가능.

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { Card } from "@/components/ui";
import {
  getConsentDisclosure,
  submitConsent,
  ApiError,
  type ConsentDisclosure,
} from "@/lib/api";

export default function CustomerConsentPage() {
  const params = useParams();
  const token = typeof params?.token === "string" ? params.token : "";

  const [disclosure, setDisclosure] = useState<ConsentDisclosure | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    getConsentDisclosure(token)
      .then((d) => {
        if (cancelled) return;
        setDisclosure(d);
        if (d.all_required_done) setDone(true);
        // 이미 동의한 항목은 체크 표시(비활성)
        setChecked(Object.fromEntries(d.items.filter((i) => i.already).map((i) => [i.scope, true])));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadError(
          e instanceof ApiError ? e.message
            : "링크를 열 수 없어요. 담당 설계사에게 새 링크를 요청해 주세요."
        );
      });
    return () => { cancelled = true; };
  }, [token]);

  const requiredOk =
    !!disclosure &&
    disclosure.items.filter((i) => i.required).every((i) => checked[i.scope] || i.already);

  const submit = useCallback(async () => {
    if (!disclosure) return;
    setSubmitting(true);
    setSubmitError(null);
    const agreed = disclosure.items.filter((i) => checked[i.scope]).map((i) => i.scope);
    try {
      await submitConsent(token, agreed);
      setDone(true);
    } catch (e: unknown) {
      setSubmitError(
        e instanceof ApiError ? e.message : "동의 처리에 실패했어요. 잠시 후 다시 시도해 주세요."
      );
    } finally {
      setSubmitting(false);
    }
  }, [token, disclosure, checked]);

  if (loadError) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 flex items-center justify-center px-5">
        <Card className="px-6 py-8 text-center">
          <div className="text-[15px] font-bold text-ink">링크를 열 수 없어요</div>
          <p className="mt-2 text-[13px] text-ink3 leading-5">{loadError}</p>
        </Card>
      </div>
    );
  }

  if (done) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
        <header className="px-5 pt-5 pb-3 bg-accent-tint">
          <div className="text-[13px] font-bold text-brand">⌃ 인파 동의</div>
        </header>
        <main className="px-5 pb-10 flex flex-col items-center text-center">
          <div className="mt-16 text-[40px]">✅</div>
          <h1 className="mt-4 text-[20px] font-extrabold text-ink">동의가 완료됐어요</h1>
          <p className="mt-2 text-[14px] text-ink3 leading-6">
            담당 설계사가 이어서 도와드릴 거예요. 이 창은 닫으셔도 됩니다.
          </p>
        </main>
      </div>
    );
  }

  if (!disclosure) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 flex items-center justify-center">
        <div className="text-[13px] text-ink3">불러오는 중…</div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
      <header className="px-5 pt-5 pb-3 bg-accent-tint">
        <div className="text-[13px] font-bold text-brand">⌃ 인파 동의</div>
      </header>
      <main className="px-5 pb-10">
        <h1 className="pt-6 text-[22px] font-extrabold text-ink leading-8">동의 요청</h1>
        <p className="mt-2 text-[14px] text-ink3 leading-6">
          {disclosure.customer.name_masked}님, 담당 설계사
          {disclosure.planner.affiliation ? ` (${disclosure.planner.affiliation})` : ""}가
          아래 내용에 <b>본인 동의</b>를 요청했어요.
        </p>

        <div className="mt-5 space-y-3">
          {disclosure.items.map((item) => (
            <Card key={item.scope} className="px-4 py-4">
              <label className="flex items-start gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!checked[item.scope]}
                  disabled={item.already}
                  onChange={(e) =>
                    setChecked((p) => ({ ...p, [item.scope]: e.target.checked }))
                  }
                  className="mt-0.5"
                />
                <span className="text-[13px] text-ink2 leading-5">
                  <b>{item.required ? "(필수) " : "(선택) "}</b>
                  {item.title}
                  {item.already ? " — 이미 동의함" : ""}
                </span>
              </label>
              <ul className="mt-2.5 ml-7 space-y-1 text-[12px] text-ink3 leading-5">
                {item.lines.map((l, i) => (<li key={`${item.scope}-${i}`}>{l}</li>))}
              </ul>
              <p className="mt-2 ml-7 text-[11px] text-muted leading-5">{item.notice}</p>
            </Card>
          ))}
        </div>

        <p className="mt-3 text-[12px] text-muted leading-5">{disclosure.disclaimer}</p>

        {submitError && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
            {submitError}
          </div>
        )}

        <button
          onClick={submit}
          disabled={!requiredOk || submitting}
          className="mt-4 w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 disabled:opacity-50 active:scale-[0.99] transition"
        >
          {submitting ? "처리 중…" : "동의합니다"}
        </button>
        <p className="mt-3 text-[11px] text-ink3 leading-5 text-center">
          인파는 보험을 중개·권유하지 않습니다.
        </p>
      </main>
    </div>
  );
}
