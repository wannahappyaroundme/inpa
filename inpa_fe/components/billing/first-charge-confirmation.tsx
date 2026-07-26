"use client";

import { useState } from "react";
import {
  ApiError,
  reconfirmFirstCharge,
  type BillingStatus,
} from "@/lib/api";
import { formatCalendarDate, formatWon } from "./date-format";

export function FirstChargeConfirmation({
  status,
  onUpdated,
}: {
  status: BillingStatus;
  onUpdated: () => Promise<void>;
}) {
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (status.state !== "trial") return null;

  async function confirmCharge() {
    setBusy(true);
    setMessage(null);
    try {
      await reconfirmFirstCharge();
      setMessage("첫 결제 내용을 확인했어요.");
      await onUpdated();
    } catch (error) {
      setMessage(
        error instanceof ApiError
          ? error.message
          : "결제 내용을 다시 확인해 주세요.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-2xl border border-brand/25 bg-brand-soft p-5">
      <p className="text-[12px] font-bold text-brand">첫 결제 확인</p>
      <h2 className="mt-1 text-[17px] font-extrabold text-ink">
        {formatCalendarDate(status.access_through)}까지 무료
      </h2>
      <p className="mt-2 text-[14px] font-semibold text-ink2">
        {formatCalendarDate(status.next_charge_date)} {formatWon(status.amount_krw)} 결제 예정
      </p>
      {status.card_label && (
        <p className="mt-1 text-[13px] text-ink3">{status.card_label}</p>
      )}

      {status.reconfirmation_required ? (
        <>
          <label className="mt-4 flex cursor-pointer items-start gap-2.5 rounded-xl bg-surface p-3 text-[13px] leading-5 text-ink2">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(event) => setAccepted(event.target.checked)}
              aria-label="첫 결제 내용을 확인했어요"
              className="mt-1 h-4 w-4 accent-[var(--brand)]"
            />
            <span>
              표시된 날짜, 금액, 카드를 확인했어요. 결제가 완료되면 한 달 이용 기간이 이어집니다.
            </span>
          </label>
          <button
            type="button"
            disabled={!accepted || busy}
            onClick={confirmCharge}
            className="mt-3 w-full rounded-xl bg-brand px-4 py-3 text-[14px] font-bold text-white disabled:opacity-50"
          >
            {busy ? "확인 저장 중..." : "첫 결제 확인하기"}
          </button>
        </>
      ) : (
        <p className="mt-4 rounded-xl bg-surface px-3 py-2 text-[13px] leading-5 text-ink2">
          {status.reconfirmation_opens_on
            ? `${formatCalendarDate(status.reconfirmation_opens_on)}부터 첫 결제 내용을 확인할 수 있어요.`
            : "첫 결제 확인을 마쳤어요."}
        </p>
      )}
      {message && (
        <p className="mt-3 text-[13px] text-ink2" role="status">
          {message}
        </p>
      )}
    </section>
  );
}
