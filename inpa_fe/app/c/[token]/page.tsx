"use client";

// 고객 본인 국외이전 동의 (공개·비로그인) — P3c.
// 설계사가 만든 동의 요청 링크(/c/<token>)를 고객이 본인 기기에서 연다.
// ★ 명시 체크박스 + 버튼(사전체크·자동제출 금지 — 정직성 레드라인). 동의해야 분석 잠금 해제.

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
  const [checked, setChecked] = useState(false);
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
        if (d.already_consented) setDone(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadError(
          e instanceof ApiError
            ? e.message
            : "링크를 열 수 없어요. 담당 설계사에게 새 링크를 요청해 주세요."
        );
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const submit = useCallback(async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      await submitConsent(token);
      setDone(true);
    } catch (e: unknown) {
      setSubmitError(
        e instanceof ApiError ? e.message : "동의 처리에 실패했어요. 잠시 후 다시 시도해 주세요."
      );
    } finally {
      setSubmitting(false);
    }
  }, [token]);

  // ── 만료/위조 링크 ──
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

  // ── 동의 완료 ──
  if (done) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
        <header className="px-5 pt-5 pb-3 bg-accent-tint">
          <div className="text-[13px] font-bold text-brand">⌃ 인파 보장 분석 동의</div>
        </header>
        <main className="px-5 pb-10 flex flex-col items-center text-center">
          <div className="mt-16 text-[40px]">✅</div>
          <h1 className="mt-4 text-[20px] font-extrabold text-ink">동의가 완료됐어요</h1>
          <p className="mt-2 text-[14px] text-ink3 leading-6">
            담당 설계사가 증권을 분석해 보장 현황을 정리해 드릴 거예요. 이 창은 닫으셔도 됩니다.
          </p>
        </main>
      </div>
    );
  }

  // ── 로딩 ──
  if (!disclosure) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 flex items-center justify-center">
        <div className="text-[13px] text-ink3">불러오는 중…</div>
      </div>
    );
  }

  // ── 동의 입력 ──
  return (
    <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
      <header className="px-5 pt-5 pb-3 bg-accent-tint">
        <div className="text-[13px] font-bold text-brand">⌃ 인파 보장 분석 동의</div>
      </header>
      <main className="px-5 pb-10">
        <h1 className="pt-6 text-[22px] font-extrabold text-ink leading-8">
          보험 정보 국외이전 동의
        </h1>
        <p className="mt-2 text-[14px] text-ink3 leading-6">
          {disclosure.customer.name_masked}님, 담당 설계사
          {disclosure.planner.affiliation ? ` (${disclosure.planner.affiliation})` : ""}가
          증권을 분석하려면 아래 국외이전에 <b>본인 동의</b>가 필요해요.
        </p>

        {/* 고지 */}
        <Card className="mt-5 px-4 py-4">
          <div className="text-[13px] font-semibold text-ink">{disclosure.scope_text}</div>
          <p className="mt-2 text-[13px] text-ink2 leading-6">{disclosure.purpose_text}</p>
          <ul className="mt-3 space-y-1 text-[12px] text-ink3 leading-5">
            <li>이전 국가·수탁자: 미국 Anthropic(Claude API)</li>
            <li>이전 항목: 증권의 보험정보(담보·보험료 등)</li>
            <li>보유 기간: 처리 후 즉시 삭제</li>
          </ul>
        </Card>

        {/* 명시 동의 체크박스 (사전체크 금지) */}
        <Card className="mt-3 px-4 py-4">
          <label className="flex items-start gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => setChecked(e.target.checked)}
              className="mt-0.5"
            />
            <span className="text-[13px] text-ink2 leading-5">
              <b>(필수)</b> 위 내용을 확인했으며, 보험정보가 Claude API(미국, Anthropic)로{" "}
              <b>국외이전</b>되는 데 동의합니다.
            </span>
          </label>
        </Card>

        <p className="mt-3 text-[12px] text-muted leading-5">{disclosure.disclaimer}</p>

        {submitError && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
            {submitError}
          </div>
        )}

        <button
          onClick={submit}
          disabled={!checked || submitting}
          className="mt-4 w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 disabled:opacity-50 active:scale-[0.99] transition"
        >
          {submitting ? "처리 중…" : "동의합니다"}
        </button>
        <p className="mt-3 text-[11px] text-ink3 leading-5 text-center">
          인파는 보험을 중개·권유하지 않습니다. 분석 결과는 AI 초안이며 최종 책임은 담당 설계사에게 있습니다.
        </p>
      </main>
    </div>
  );
}
