"use client";

import { useEffect, useState } from "react";
import { AppNav } from "@/components/app-nav";
import { CardRegistration } from "@/components/billing/card-registration";
import { FirstChargeConfirmation } from "@/components/billing/first-charge-confirmation";
import { formatCalendarDate, formatWon } from "@/components/billing/date-format";
import {
  ApiError,
  cancelBilling,
  getBillingStatus,
  type BillingStatus,
} from "@/lib/api";
import { useAuthGuard } from "@/lib/useAuthGuard";

export default function BillingPage() {
  const ready = useAuthGuard();
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [canceling, setCanceling] = useState(false);

  async function reload() {
    setError(null);
    try {
      setStatus(await getBillingStatus());
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "결제 정보를 다시 불러와 주세요.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!ready) return;
    void reload();
    const registration = new URLSearchParams(
      window.location.search,
    ).get("registration");
    if (registration === "success") {
      setMessage("카드 등록과 무료 이용을 시작했어요.");
    } else if (registration === "check") {
      setMessage("카드 등록 상태를 확인하고 있어요. 잠시 뒤 다시 확인해 주세요.");
    }
  }, [ready]);

  async function confirmCancellation() {
    setCanceling(true);
    setError(null);
    try {
      const result = await cancelBilling();
      setMessage(
        `${formatCalendarDate(result.access_through)}까지 이용할 수 있어요.`,
      );
      setCancelOpen(false);
      await reload();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "결제 상태를 다시 확인해 주세요.",
      );
    } finally {
      setCanceling(false);
    }
  }

  if (!ready) return null;

  const canCancel = status && ["trial", "active", "renewal_processing", "past_due_unknown"].includes(status.state);

  return (
    <div className="min-h-dvh bg-surface2">
      <AppNav active="settings" />
      <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
        <div>
          <p className="text-[12px] font-bold text-brand">설정</p>
          <h1 className="mt-1 text-[24px] font-extrabold text-ink">결제와 쿠폰</h1>
          <p className="mt-2 text-[13px] leading-5 text-ink3">
            무료 이용 날짜, 다음 결제일, 등록한 카드를 한곳에서 확인해요.
          </p>
        </div>

        {message && (
          <div
            className="mt-5 rounded-xl border border-success/20 bg-success-tint px-4 py-3 text-[13px] text-success"
            role="status"
          >
            {message}
          </div>
        )}

        {error && (
          <div className="mt-5 rounded-2xl border border-line bg-surface p-4">
            <p className="text-[13px] leading-5 text-ink2">{error}</p>
            <button
              type="button"
              onClick={reload}
              className="mt-3 rounded-xl bg-brand px-4 py-2 text-[13px] font-bold text-white"
            >
              다시 불러오기
            </button>
          </div>
        )}

        {loading && (
          <div className="mt-5 space-y-3" aria-label="결제 정보 불러오는 중">
            <div className="h-36 animate-pulse rounded-2xl bg-surface" />
            <div className="h-44 animate-pulse rounded-2xl bg-surface" />
          </div>
        )}

        {!loading && status && (
          <div className="mt-5 space-y-4">
            {status.state === "free" && (
              <>
                <section className="rounded-2xl border border-line bg-surface p-5">
                  <p className="text-[12px] font-bold text-brand">현재 요금제</p>
                  <h2 className="mt-1 text-[20px] font-extrabold text-ink">무료</h2>
                  <p className="mt-2 text-[13px] leading-5 text-ink2">
                    기존 고객과 메모, 상담 요약은 그대로 보관돼요. 쿠폰이 있다면 카드 등록 후 Plus를 시작할 수 있어요.
                  </p>
                </section>
                <CardRegistration />
              </>
            )}

            {status.state === "trial" && (
              <FirstChargeConfirmation status={status} onUpdated={reload} />
            )}

            {status.state === "active" && (
              <section className="rounded-2xl border border-line bg-surface p-5">
                <p className="text-[12px] font-bold text-success">이용 중</p>
                <h2 className="mt-1 text-[20px] font-extrabold text-ink">
                  {status.plan_display_name}
                </h2>
                <dl className="mt-4 grid gap-3 text-[13px] sm:grid-cols-2">
                  <div>
                    <dt className="text-ink3">다음 결제</dt>
                    <dd className="mt-1 font-semibold text-ink">
                      {formatCalendarDate(status.next_charge_date)} {formatWon(status.amount_krw)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink3">등록 카드</dt>
                    <dd className="mt-1 font-semibold text-ink">
                      {status.card_label ?? "-"}
                    </dd>
                  </div>
                </dl>
              </section>
            )}

            {status.state === "past_due_unknown" && (
              <section className="rounded-2xl border border-warning/25 bg-warning-tint p-5">
                <p className="text-[12px] font-bold text-warning">결제 확인 중</p>
                <h2 className="mt-1 text-[18px] font-extrabold text-ink">
                  같은 결제를 다시 요청하지 않고 상태를 확인하고 있어요
                </h2>
                <p className="mt-2 text-[13px] leading-5 text-ink2">
                  고객 기록은 그대로 이용할 수 있어요. 확인이 끝나면 이 화면에 바로 반영됩니다.
                </p>
              </section>
            )}

            {status.state === "renewal_processing" && (
              <section className="rounded-2xl border border-line bg-surface p-5">
                <p className="text-[13px] font-semibold text-ink2">
                  결제를 처리하고 있어요. 같은 결제를 다시 누르지 않아도 현재 상태를 자동으로 확인합니다.
                </p>
              </section>
            )}

            {status.state === "canceled" && (
              <section className="rounded-2xl border border-line bg-surface p-5">
                <p className="text-[12px] font-bold text-brand">다음 결제 멈춤</p>
                <h2 className="mt-1 text-[18px] font-extrabold text-ink">
                  {formatCalendarDate(status.access_through)}까지 이용해요
                </h2>
                <p className="mt-2 text-[13px] leading-5 text-ink2">
                  이후 무료 요금제로 전환되어도 기존 고객과 메모, 상담 요약은 그대로 보관돼요.
                </p>
              </section>
            )}

            {canCancel && (
              <section className="rounded-2xl border border-line bg-surface p-5">
                {!cancelOpen ? (
                  <>
                    <h2 className="text-[15px] font-bold text-ink">다음 결제 관리</h2>
                    <p className="mt-1 text-[13px] leading-5 text-ink3">
                      다음 결제를 멈춰도 현재 이용 기간은 끝까지 유지돼요.
                    </p>
                    <button
                      type="button"
                      onClick={() => setCancelOpen(true)}
                      className="mt-3 rounded-xl border border-line px-4 py-2.5 text-[13px] font-bold text-ink2"
                    >
                      다음 결제 멈추기
                    </button>
                  </>
                ) : (
                  <>
                    <h2 className="text-[16px] font-extrabold text-ink">
                      다음 결제를 멈출까요?
                    </h2>
                    <p className="mt-2 text-[13px] leading-5 text-ink2">
                      다음 결제를 멈춰도 {formatCalendarDate(status.access_through)}까지 이용해요.
                    </p>
                    <p className="mt-2 text-[13px] font-semibold leading-5 text-success">
                      기존 고객과 메모, 상담 요약은 그대로 보관돼요.
                    </p>
                    <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                      <button
                        type="button"
                        disabled={canceling}
                        onClick={() => setCancelOpen(false)}
                        className="rounded-xl border border-line px-4 py-2.5 text-[13px] font-bold text-ink2"
                      >
                        계속 이용
                      </button>
                      <button
                        type="button"
                        disabled={canceling}
                        onClick={confirmCancellation}
                        className="rounded-xl bg-ink px-4 py-2.5 text-[13px] font-bold text-white disabled:opacity-50"
                      >
                        {canceling ? "처리 중..." : "다음 결제 멈춤 확인"}
                      </button>
                    </div>
                  </>
                )}
              </section>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
