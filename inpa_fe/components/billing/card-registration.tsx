"use client";

import { useRef, useState } from "react";
import {
  ApiError,
  getCurrentManualBenefitReview,
  preflightRecurringCoupon,
  startCardRegistration,
  type ManualBenefitReview,
  type RecurringCouponPreflight,
} from "@/lib/api";
import { formatCalendarDate, formatWon } from "./date-format";
import { FreeTrialPhoneVerification, type CouponRetryResult } from "./free-trial-phone-verification";

export function CardRegistration() {
  const [code, setCode] = useState("");
  const [preview, setPreview] = useState<RecurringCouponPreflight | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [verificationStep, setVerificationStep] = useState<"phone" | "manual-review" | null>(null);
  const [verificationKey, setVerificationKey] = useState(0);
  const [couponSnapshot, setCouponSnapshot] = useState<string | null>(null);
  const [submittedReview, setSubmittedReview] = useState<ManualBenefitReview | null>(null);
  const couponOperationRef = useRef(0);
  const couponInputRef = useRef<HTMLInputElement>(null);

  async function checkCoupon(
    afterPhoneVerification = false,
    couponCodeOverride?: string,
  ): Promise<CouponRetryResult> {
    const couponCode = afterPhoneVerification
      ? couponSnapshot
      : couponCodeOverride ?? code.trim();
    if (!couponCode) return { state: "complete" };
    const operation = couponOperationRef.current + 1;
    couponOperationRef.current = operation;
    if (!afterPhoneVerification) setCouponSnapshot(couponCode);
    setBusy(true);
    setMessage(null);
    try {
      const nextPreview = await preflightRecurringCoupon(couponCode);
      if (operation !== couponOperationRef.current) return { state: "complete" };
      setPreview(nextPreview);
      setAccepted(false);
      setSubmittedReview(null);
      setVerificationStep(null);
      return { state: "complete" };
    } catch (error) {
      if (operation !== couponOperationRef.current) return { state: "complete" };
      setPreview(null);
      if (!afterPhoneVerification && error instanceof ApiError && error.code === "phone_verification_required") {
        setVerificationStep("phone");
        setVerificationKey((current) => current + 1);
        return { state: "complete" };
      }
      if (error instanceof ApiError && error.code === "manual_benefit_review_required") {
        try {
          const currentReview = await getCurrentManualBenefitReview();
          if (operation !== couponOperationRef.current) return { state: "complete" };
          setSubmittedReview(currentReview);
        } catch (reviewError) {
          if (operation !== couponOperationRef.current) return { state: "complete" };
          const nextMessage = reviewError instanceof ApiError
            ? reviewError.message
            : "처리 상태를 다시 확인해 주세요.";
          setMessage(nextMessage);
          return afterPhoneVerification
            ? { state: "recoverable-error", message: nextMessage }
            : { state: "complete" };
        }
        setVerificationStep("manual-review");
        setVerificationKey((current) => current + 1);
        return { state: "manual-review" };
      }
      const nextMessage = error instanceof ApiError ? error.message : "쿠폰을 다시 확인해 주세요.";
      if (afterPhoneVerification) {
        return { state: "recoverable-error", message: nextMessage };
      }
      setMessage(nextMessage);
      return { state: "complete" };
    } finally {
      if (operation === couponOperationRef.current) setBusy(false);
    }
  }

  async function registerCard() {
    if (!preview || !accepted) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await startCardRegistration(
        preview.claim_id,
        window.innerWidth >= 768 ? "pc" : "mobile",
      );
      window.location.assign(result.auth_page_url);
    } catch (error) {
      setMessage(
        error instanceof ApiError
          ? error.message
          : "카드 등록을 다시 시작해 주세요.",
      );
      setBusy(false);
    }
  }

  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h2 className="text-[16px] font-extrabold text-ink">무료 쿠폰 시작</h2>
      <p className="mt-1 text-[13px] leading-5 text-ink3">
        1~3개월 쿠폰은 카드를 등록한 뒤 사용할 수 있어요. 첫 유료 결제 전에는 날짜와 금액을 한 번 더 확인합니다.
      </p>

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <input
          ref={couponInputRef}
          value={code}
          onChange={(event) => setCode(event.target.value.toUpperCase())}
          placeholder="쿠폰 코드를 입력해 주세요"
          aria-label="쿠폰 코드"
          className="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink outline-none focus:border-brand"
        />
        <button
          type="button"
          disabled={busy || !code.trim()}
          onClick={() => void checkCoupon()}
          className="rounded-xl bg-brand px-4 py-2.5 text-[13px] font-bold text-white disabled:opacity-50"
        >
          {busy && !preview ? "확인 중..." : "쿠폰 확인"}
        </button>
      </div>

      {message && (
        <p role="alert" className="mt-3 rounded-xl bg-surface2 px-3 py-2 text-[13px] leading-5 text-ink2">
          {message}
        </p>
      )}

      {verificationStep && (
        <FreeTrialPhoneVerification
          key={verificationKey}
          initialStep={verificationStep}
          initialSubmittedReview={verificationStep === "manual-review" && submittedReview
            ? { ...submittedReview, created: false }
            : null}
          onVerified={() => checkCoupon(true)}
          onSubmitted={setSubmittedReview}
          onRefresh={() => checkCoupon(false, couponSnapshot ?? undefined).then(() => undefined)}
          onBack={() => {
            couponOperationRef.current += 1;
            setVerificationStep(null);
            setMessage(null);
            couponInputRef.current?.focus();
            requestAnimationFrame(() => couponInputRef.current?.focus());
          }}
        />
      )}

      {preview && (
        <div className="mt-4 rounded-2xl border border-brand/20 bg-brand-soft p-4">
          <p className="text-[15px] font-bold text-brand">
            {preview.plan_display_name} {preview.duration_months}개월 무료
          </p>
          <dl className="mt-3 grid gap-2 text-[13px] text-ink2 sm:grid-cols-2">
            <div>
              <dt className="text-ink3">무료 이용</dt>
              <dd className="font-semibold">
                {formatCalendarDate(preview.access_through)}까지
              </dd>
            </div>
            <div>
              <dt className="text-ink3">첫 결제 예정</dt>
              <dd className="font-semibold">
                {formatCalendarDate(preview.next_charge_date)} {formatWon(preview.amount_krw)}
              </dd>
            </div>
          </dl>
          <label className="mt-4 flex cursor-pointer items-start gap-2.5 text-[13px] leading-5 text-ink2">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(event) => setAccepted(event.target.checked)}
              className="mt-1 h-4 w-4 accent-[var(--brand)]"
            />
            <span>
              무료 이용 날짜와 첫 결제 예정 내용을 확인했어요. 첫 유료 결제 전 별도 확인을 거칩니다.
            </span>
          </label>
          <button
            type="button"
            disabled={busy || !accepted}
            onClick={registerCard}
            className="mt-4 w-full rounded-xl bg-brand px-4 py-3 text-[14px] font-bold text-white disabled:opacity-50"
          >
            {busy ? "카드 등록 여는 중..." : "카드 등록하고 무료로 시작"}
          </button>
        </div>
      )}
    </section>
  );
}
