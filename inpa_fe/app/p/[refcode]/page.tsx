"use client";

// 내 소개 카드(공개·비로그인) — 설계사가 카톡·문자·QR로 뿌리는 디지털 명함.
// 이름·소속·직책·한줄소개 + '무료 보장점검'(→/d) + '상담 신청'(→ 설계사 db 리드 자동 생성).
// ★ 고객 대면: 혜택 + 다음 행동만. 법·심사 용어 없음.

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { Card } from "@/components/ui";
import { getIntroductionCard, submitIntroLead, ApiError, type IntroCardResponse } from "@/lib/api";

const MOBILE_PHONE_PATTERN = /^01[0-9]{8,9}$/;
type LoadState = "loading" | "ready" | "not-found" | "retryable";
type FormError = { field: "name" | "phone" | "consent" | "form"; message: string };

export default function IntroCardPage() {
  const params = useParams();
  const refcode = typeof params?.refcode === "string" ? params.refcode : "";

  const [card, setCard] = useState<IntroCardResponse | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<FormError | null>(null);

  const loadCard = useCallback(async () => {
    setCard(null);
    setLoadState("loading");
    if (!refcode) {
      setLoadState("not-found");
      return;
    }
    try {
      setCard(await getIntroductionCard(refcode));
      setLoadState("ready");
    } catch (e) {
      setLoadState(e instanceof ApiError && e.status === 404 ? "not-found" : "retryable");
    }
  }, [refcode]);

  useEffect(() => {
    void loadCard();
  }, [loadCard]);

  const submit = useCallback(async () => {
    if (!name.trim()) {
      setError({ field: "name", message: "이름을 입력해 주세요." });
      return;
    }
    if (!MOBILE_PHONE_PATTERN.test(phone.replace(/\D/g, ""))) {
      setError({ field: "phone", message: "올바른 휴대폰 번호를 입력해 주세요." });
      return;
    }
    if (!agreed) {
      setError({ field: "consent", message: "개인정보 수집·연락 동의에 체크해 주세요." });
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await submitIntroLead(refcode, { name: name.trim(), phone: phone.trim(), agreed: true });
      setSubmitted(true);
    } catch (e) {
      const field = e instanceof ApiError && e.code === "INVALID_PHONE"
        ? "phone"
        : e instanceof ApiError && e.code === "NAME_REQUIRED"
          ? "name"
          : e instanceof ApiError && e.code === "CONSENT_REQUIRED"
            ? "consent"
            : "form";
      setError({
        field,
        message: e instanceof ApiError ? e.message : "신청에 실패했어요. 잠시 후 다시 시도해 주세요.",
      });
      setSubmitting(false);
    }
  }, [refcode, name, phone, agreed]);

  if (loadState === "loading") {
    return <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 grid place-items-center text-[14px] text-ink3">불러오는 중...</div>;
  }
  if (loadState === "not-found") {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 grid place-items-center px-6 text-center">
        <p className="text-[15px] font-semibold text-ink2">유효하지 않은 링크예요.</p>
      </div>
    );
  }
  if (loadState === "retryable" || !card) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 flex flex-col items-center justify-center px-6 text-center">
        <h1 className="text-[20px] font-extrabold text-ink">잠시 연결이 원활하지 않아요</h1>
        <p className="mt-2 text-[14px] text-ink3 leading-6">다시 시도하면 소개 내용을 확인할 수 있어요.</p>
        <button
          type="button"
          onClick={loadCard}
          className="mt-5 rounded-xl bg-brand px-5 py-3 text-[14px] font-bold text-white"
        >
          다시 불러오기
        </button>
      </div>
    );
  }

  const p = card.planner;
  const sub = [p.affiliation, p.title].filter(Boolean).join(" · ");

  return (
    <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
      <header className="px-5 pt-5 pb-3 bg-accent-tint">
        <div className="text-[13px] font-bold text-brand">⌃ 인파</div>
      </header>
      <main className="px-5 pb-10">
        {/* 소개 카드 */}
        <Card className="mt-5 p-5 text-center">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-brand-soft text-brand grid place-items-center text-[24px] font-extrabold">
            {p.name.slice(0, 1)}
          </div>
          <div className="mt-3 text-[20px] font-extrabold text-ink">{p.name}</div>
          {sub && <div className="mt-0.5 text-[13px] text-ink3">{sub}</div>}
          {p.intro_text && <p className="mt-3 text-[14px] text-ink2 leading-6">{p.intro_text}</p>}
        </Card>

        {/* CTA 1 — 무료 보장점검(셀프진단) */}
        <a
          href={card.self_diagnosis_url}
          className="mt-4 block rounded-2xl bg-brand text-white text-center text-[16px] font-bold py-4 hover:opacity-90 transition"
        >
          내 보험 무료로 점검받기
        </a>
        <p className="mt-1.5 text-center text-[12px] text-ink3">지금 내 상황에 맞는 보장인지 1분 만에 확인해보세요. 증권 파일(PDF)만 있으면 돼요.</p>

        {/* CTA 2 — 상담 신청(리드 생성) */}
        {submitted ? (
          <Card className="mt-5 p-5 text-center">
            <div className="text-[16px] font-bold text-ink">신청이 접수됐어요 🙌</div>
            <p className="mt-1 text-[13px] text-ink3">상담 내용을 확인한 뒤 연락드려요</p>
          </Card>
        ) : (
          <Card className="mt-5 p-5">
            <div className="text-[15px] font-bold text-ink">상담 신청하기</div>
            <p className="mt-1 text-[12px] text-ink3 leading-5">상담 내용을 확인한 뒤 연락드릴 수 있도록 휴대폰 번호를 남겨 주세요.</p>
            <label htmlFor="intro-card-name" className="mt-3 block text-[12px] font-medium text-ink2">
              이름
            </label>
            <input
              id="intro-card-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (error) setError(null);
              }}
              placeholder="이름"
              aria-invalid={error?.field === "name"}
              aria-describedby={error?.field === "name" ? "intro-card-name-error" : undefined}
              className="mt-1 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
            />
            {error?.field === "name" && <div id="intro-card-name-error" role="alert" className="mt-2 text-[12px] text-cnone">{error.message}</div>}
            <label htmlFor="intro-card-phone" className="mt-3 block text-[12px] font-medium text-ink2">
              연락받을 휴대폰 번호
            </label>
            <input
              id="intro-card-phone"
              value={phone}
              onChange={(e) => {
                setPhone(e.target.value);
                if (error) setError(null);
              }}
              type="tel"
              autoComplete="tel"
              placeholder="예: 010-1234-5678"
              inputMode="tel"
              aria-invalid={error?.field === "phone"}
              aria-describedby={error?.field === "phone" ? "intro-card-phone-error" : undefined}
              className="mt-1 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
            />
            {error?.field === "phone" && <div id="intro-card-phone-error" role="alert" className="mt-2 text-[12px] text-cnone">{error.message}</div>}
            <label htmlFor="intro-card-consent" className="mt-3 flex items-start gap-2 text-[12px] text-ink3 leading-5">
              <input
                id="intro-card-consent"
                type="checkbox"
                checked={agreed}
                onChange={(e) => {
                  setAgreed(e.target.checked);
                  if (error) setError(null);
                }}
                aria-invalid={error?.field === "consent"}
                aria-describedby={error?.field === "consent" ? "intro-card-consent-error" : undefined}
                className="mt-0.5"
              />
              <span>개인정보(이름·연락처)를 상담 목적으로 수집·이용하고 담당 설계사에게 전달하는 데 동의해요.</span>
            </label>
            {error?.field === "consent" && <div id="intro-card-consent-error" role="alert" className="mt-2 text-[12px] text-cnone">{error.message}</div>}
            {error?.field === "form" && <div id="intro-card-form-error" role="alert" className="mt-2 text-[12px] text-cnone">{error.message}</div>}
            <button
              type="button"
              onClick={submit}
              disabled={submitting}
              className="mt-3 w-full rounded-2xl bg-ink text-white text-[15px] font-bold py-3.5 disabled:opacity-50 hover:opacity-90 transition"
            >
              {submitting ? "신청 중..." : "상담 신청"}
            </button>
          </Card>
        )}

        <p className="mt-6 text-center text-[11px] text-muted leading-5">
          인파는 보험을 중개·권유하지 않는 분석·정리 도구입니다.
        </p>
      </main>
    </div>
  );
}
