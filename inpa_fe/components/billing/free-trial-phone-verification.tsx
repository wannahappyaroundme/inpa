"use client";

import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  requestFreeTrialPhoneVerification,
  submitManualBenefitReview,
  verifyFreeTrialPhone,
  type ManualBenefitReview,
} from "@/lib/api";

type VerificationStep = "phone" | "sending" | "code" | "verifying" | "retrying" | "manual-review" | "submitted";
export type CouponRetryResult =
  | { state: "complete" }
  | { state: "manual-review" }
  | { state: "recoverable-error"; message: string };

const REVIEW_STATUS_LABEL: Record<ManualBenefitReview["status"], string> = {
  pending: "접수",
  approved: "승인",
  rejected: "반려",
  consumed: "지급 완료",
};

function secondsText(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function FreeTrialPhoneVerification({
  initialStep = "phone",
  initialSubmittedReview = null,
  onVerified,
  onBack,
  onSubmitted,
  onRefresh,
}: {
  initialStep?: "phone" | "manual-review";
  initialSubmittedReview?: ManualBenefitReview | null;
  onVerified: () => Promise<CouponRetryResult>;
  onBack: () => void;
  onSubmitted?: (review: ManualBenefitReview) => void;
  onRefresh?: () => Promise<void>;
}) {
  const [step, setStep] = useState<VerificationStep>(initialSubmittedReview ? "submitted" : initialStep);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [phoneMasked, setPhoneMasked] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [resendAt, setResendAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);
  const [contactEmail, setContactEmail] = useState("");
  const [reason, setReason] = useState("");
  const [submittedReview, setSubmittedReview] = useState<ManualBenefitReview | null>(initialSubmittedReview);
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [reviewRefreshing, setReviewRefreshing] = useState(false);
  const phoneRef = useRef<HTMLInputElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const operationRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      operationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if ((step !== "code" && step !== "verifying") || (!expiresAt && !resendAt)) return;
    const intervalId = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(intervalId);
  }, [expiresAt, resendAt, step]);

  useEffect(() => {
    const frameId = window.requestAnimationFrame(() => {
      if (step === "phone") phoneRef.current?.focus();
      if (step === "code") codeRef.current?.focus();
      if (step === "manual-review") emailRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [step]);

  const expirySeconds = expiresAt ? Math.max(0, Math.ceil((expiresAt - now) / 1000)) : 0;
  const resendSeconds = resendAt ? Math.max(0, Math.ceil((resendAt - now) / 1000)) : 0;
  const canResend = (step === "code" || step === "verifying") && resendSeconds === 0;

  async function sendCode() {
    if (!phone.trim() || step === "sending" || step === "retrying") return;
    const operation = operationRef.current + 1;
    operationRef.current = operation;
    setStep("sending");
    setError(null);
    try {
      const result = await requestFreeTrialPhoneVerification(phone);
      if (!mountedRef.current || operation !== operationRef.current) return;
      const startedAt = Date.now();
      setChallengeId(result.challenge_id);
      setPhoneMasked(result.phone_masked);
      setCode("");
      setNow(startedAt);
      setExpiresAt(startedAt + result.expires_in_seconds * 1000);
      setResendAt(startedAt + 60_000);
      setStep("code");
    } catch (caught) {
      if (!mountedRef.current || operation !== operationRef.current) return;
      setStep("phone");
      setError(errorMessage(caught, "인증번호를 다시 보내 주세요."));
    }
  }

  async function verifyCode() {
    if (!challengeId || code.length !== 6 || step !== "code") return;
    const operation = operationRef.current + 1;
    operationRef.current = operation;
    setStep("verifying");
    setError(null);
    try {
      await verifyFreeTrialPhone({ challenge_id: challengeId, phone, code });
      if (!mountedRef.current || operation !== operationRef.current) return;
      setStep("retrying");
      const next = await onVerified();
      if (!mountedRef.current || operation !== operationRef.current) return;
      if (next.state === "manual-review") setStep("manual-review");
      if (next.state === "recoverable-error") {
        setStep("code");
        setError(next.message);
      }
    } catch (caught) {
      if (!mountedRef.current || operation !== operationRef.current) return;
      setStep("code");
      setError(errorMessage(caught, "인증번호를 다시 확인해 주세요."));
      codeRef.current?.focus();
    }
  }

  async function submitReview() {
    if (!contactEmail.trim() || !reason.trim() || step === "submitted" || reviewSubmitting) return;
    const operation = operationRef.current + 1;
    operationRef.current = operation;
    setError(null);
    setReviewSubmitting(true);
    try {
      const review = await submitManualBenefitReview({
        contact_email: contactEmail.trim(),
        reason: reason.trim(),
      });
      if (!mountedRef.current || operation !== operationRef.current) return;
      setSubmittedReview(review);
      onSubmitted?.(review);
      setStep("submitted");
    } catch (caught) {
      if (!mountedRef.current || operation !== operationRef.current) return;
      setError(errorMessage(caught, "확인 요청을 다시 보내 주세요."));
    } finally {
      if (mountedRef.current && operation === operationRef.current) setReviewSubmitting(false);
    }
  }

  async function refreshReview() {
    if (!onRefresh || reviewRefreshing) return;
    setReviewRefreshing(true);
    try {
      await onRefresh();
    } finally {
      if (mountedRef.current) setReviewRefreshing(false);
    }
  }

  return (
    <section className="mt-4 rounded-2xl border border-brand/20 bg-brand-soft p-4" aria-labelledby="free-trial-phone-title">
      <h3 id="free-trial-phone-title" className="text-[15px] font-extrabold text-ink">무료 혜택 확인</h3>
      {error && <p role="alert" className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-[13px] leading-5 text-danger-ink">{error}</p>}

      {(step === "phone" || (step === "sending" && !challengeId)) && (
        <div className="mt-3">
          <label htmlFor="free-trial-phone" className="text-[13px] font-semibold text-ink2">휴대전화 번호</label>
          <input
            ref={phoneRef}
            id="free-trial-phone"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            disabled={step === "sending"}
            inputMode="tel"
            autoComplete="tel"
            placeholder="010-1234-5678"
            className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink outline-none focus:border-brand"
          />
          <button type="button" disabled={!phone.trim() || step === "sending"} onClick={() => void sendCode()} className="mt-3 min-h-11 w-full rounded-xl bg-brand px-4 text-[14px] font-bold text-white disabled:opacity-50">
            {step === "sending" ? "인증번호 보내는 중..." : "인증번호 보내기"}
          </button>
        </div>
      )}

      {(step === "code" || step === "verifying" || step === "retrying" || (step === "sending" && Boolean(challengeId))) && (
        <div className="mt-3">
          <p role="status" aria-live="polite" className="text-[13px] leading-5 text-ink2">{phoneMasked}로 인증번호를 보냈어요.</p>
          {step === "retrying" ? (
            <p role="status" aria-live="polite" className="mt-3 text-[13px] font-semibold text-brand">쿠폰을 다시 확인하고 있어요.</p>
          ) : step === "sending" ? (
            <p role="status" aria-live="polite" className="mt-3 text-[13px] font-semibold text-ink2">인증번호를 다시 보내고 있어요.</p>
          ) : (
            <>
              <label htmlFor="free-trial-code" className="mt-3 block text-[13px] font-semibold text-ink2">인증번호</label>
              <input
                ref={codeRef}
                id="free-trial-code"
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[16px] tracking-[0.25em] text-ink outline-none focus:border-brand"
              />
              <p className="mt-2 text-[12px] text-ink3">남은 시간 {secondsText(expirySeconds)}</p>
              <button type="button" disabled={step === "verifying" || code.length !== 6 || expirySeconds === 0} onClick={() => void verifyCode()} className="mt-3 min-h-11 w-full rounded-xl bg-brand px-4 text-[14px] font-bold text-white disabled:opacity-50">
                {step === "verifying" ? "인증 확인 중..." : "인증 확인"}
              </button>
              <button type="button" disabled={!canResend} onClick={() => void sendCode()} className="mt-2 min-h-11 w-full rounded-xl border border-line bg-surface px-4 text-[13px] font-semibold text-ink2 disabled:opacity-50">
                {canResend ? "인증번호 다시 보내기" : `재전송 ${secondsText(resendSeconds)}`}
              </button>
            </>
          )}
        </div>
      )}

      {step === "manual-review" && (
        <div className="mt-3">
          <p className="text-[13px] leading-5 text-ink2">확인이 필요한 번호예요. 이메일과 간단한 사유를 남기면 확인 후 안내해 드릴게요.</p>
          <label htmlFor="benefit-review-email" className="mt-3 block text-[13px] font-semibold text-ink2">연락 이메일</label>
          <input ref={emailRef} id="benefit-review-email" value={contactEmail} onChange={(event) => setContactEmail(event.target.value)} type="email" autoComplete="email" className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink outline-none focus:border-brand" />
          <label htmlFor="benefit-review-reason" className="mt-3 block text-[13px] font-semibold text-ink2">확인 사유</label>
          <textarea id="benefit-review-reason" value={reason} onChange={(event) => setReason(event.target.value)} rows={3} className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink outline-none focus:border-brand" />
          <button type="button" disabled={!contactEmail.trim() || !reason.trim() || reviewSubmitting} onClick={() => void submitReview()} className="mt-3 min-h-11 w-full rounded-xl bg-brand px-4 text-[14px] font-bold text-white disabled:opacity-50">{reviewSubmitting ? "확인 요청 보내는 중..." : "확인 요청 보내기"}</button>
        </div>
      )}

      {step === "submitted" && submittedReview && (
        <div className="mt-3" role="status" aria-live="polite">
          <p className="text-[13px] font-semibold leading-5 text-success-ink">
            {submittedReview.created
              ? "확인 요청을 접수했어요. 처리 결과는 이 화면에서 다시 확인할 수 있어요."
              : "이전에 남긴 확인 요청의 현재 상태예요."}
          </p>
          <p className="mt-2 text-[13px] text-ink2">현재 상태: {REVIEW_STATUS_LABEL[submittedReview.status]}</p>
          {onRefresh && (
            <button type="button" disabled={reviewRefreshing} onClick={() => void refreshReview()} className="mt-3 min-h-11 text-[13px] font-semibold text-ink2 underline underline-offset-4 disabled:opacity-50">
              {reviewRefreshing ? "처리 상태 확인 중..." : "처리 상태 다시 확인"}
            </button>
          )}
        </div>
      )}

      <button type="button" disabled={step === "sending" || step === "verifying" || step === "retrying"} onClick={onBack} className="mt-4 min-h-11 text-[13px] font-semibold text-ink2 underline underline-offset-4 disabled:opacity-50">쿠폰 코드 다시 입력</button>
    </section>
  );
}
