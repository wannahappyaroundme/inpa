"use client";

import { useCallback, useEffect, useState } from "react";
import { Card } from "@/components/ui";
import {
  adminCreateBillingCoupon,
  adminGetBillingOverview,
  adminListBillingCoupons,
  adminQueueBillingReconciliation,
  adminQueueBillingTokenRevocation,
  adminUpdateBillingCoupon,
  adminUpdateBillingSettings,
  type AdminBillingCoupon,
  type AdminBillingOverview,
  type AdminBillingSettings,
} from "@/lib/adminApi";
import { ApiError } from "@/lib/api";
import { useAdminGuard } from "@/lib/useAdminGuard";

function CountCard({
  label,
  value,
  note,
}: {
  label: string;
  value: number;
  note: string;
}) {
  return (
    <Card className="p-4">
      <p className="text-[12px] font-semibold text-ink3">{label}</p>
      <p className="mt-2 text-[26px] font-extrabold text-ink">
        {value.toLocaleString("ko-KR")}
      </p>
      <p className="mt-1 text-[11px] leading-5 text-ink3">{note}</p>
    </Card>
  );
}

function dateText(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).format(new Date(value));
}

const ORDER_LABEL: Record<string, string> = {
  created: "생성",
  submitted: "승인 요청",
  approved: "승인",
  declined: "승인 거절",
  unknown: "미확정",
  canceled: "취소",
  refunded: "환불",
};

export default function AdminBillingPage() {
  const ready = useAdminGuard();
  const [overview, setOverview] = useState<AdminBillingOverview | null>(null);
  const [coupons, setCoupons] = useState<AdminBillingCoupon[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [durationMonths, setDurationMonths] = useState<1 | 2 | 3>(1);
  const [redeemBy, setRedeemBy] = useState("");
  const [maxRedemptions, setMaxRedemptions] = useState(1);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextOverview, nextCoupons] = await Promise.all([
        adminGetBillingOverview(),
        adminListBillingCoupons(),
      ]);
      setOverview(nextOverview);
      setCoupons(nextCoupons);
    } catch {
      setError("결제 운영 상태를 다시 불러와 주세요.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (ready) void load();
  }, [load, ready]);

  async function createCoupon(event: React.FormEvent) {
    event.preventDefault();
    if (!redeemBy || maxRedemptions < 1 || busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const created = await adminCreateBillingCoupon(
        {
          plan_code: "plus",
          duration_months: durationMonths,
          redeem_by: new Date(redeemBy).toISOString(),
          max_redemptions: maxRedemptions,
          note: note.trim(),
        },
        crypto.randomUUID(),
      );
      setCoupons((current) => [
        created,
        ...current.filter((item) => item.id !== created.id),
      ]);
      setRedeemBy("");
      setMaxRedemptions(1);
      setNote("");
      setMessage(`${created.code} 쿠폰을 발행했어요.`);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "쿠폰 정보를 확인한 뒤 다시 발행해 주세요.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function toggleCoupon(coupon: AdminBillingCoupon) {
    setBusy(true);
    setError(null);
    try {
      const updated = await adminUpdateBillingCoupon(
        coupon.id,
        { is_active: !coupon.is_active },
        crypto.randomUUID(),
      );
      setCoupons((current) => current.map(
        (item) => item.id === updated.id ? updated : item,
      ));
      setMessage(
        updated.is_active
          ? `${updated.code} 사용을 다시 열었어요.`
          : `${updated.code} 신규 사용을 멈췄어요.`,
      );
    } catch {
      setError("쿠폰 상태를 다시 확인해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  async function updateSetting(
    field: keyof AdminBillingSettings,
    value: boolean,
  ) {
    if (!overview || busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await adminUpdateBillingSettings({
        [field]: value,
      });
      setOverview((current) => current ? {
        ...current,
        environment: result.environment,
        settings: result.settings,
      } : current);
      setMessage("결제 운영 설정을 저장했어요.");
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "결제 운영 설정을 다시 확인해 주세요.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function reconcile(orderId: number) {
    setBusy(true);
    setError(null);
    try {
      await adminQueueBillingReconciliation(
        orderId, crypto.randomUUID());
      setMessage("미확정 결제 조회를 요청했어요.");
      await load();
    } catch {
      setError("결제 상태를 다시 확인한 뒤 조회해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  async function revokeToken(tokenId: number) {
    setBusy(true);
    setError(null);
    try {
      await adminQueueBillingTokenRevocation(
        tokenId, crypto.randomUUID());
      setMessage("결제키 폐기를 요청했어요.");
      await load();
    } catch {
      setError("결제키 상태를 다시 확인해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return null;
  if (loading && !overview) {
    return (
      <div className="max-w-6xl" aria-label="결제 운영 상태 불러오는 중">
        <div className="h-8 w-48 animate-pulse rounded-lg bg-line" />
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((item) => (
            <div key={item} className="h-28 animate-pulse rounded-2xl bg-line" />
          ))}
        </div>
      </div>
    );
  }
  if (!overview) {
    return (
      <div className="max-w-xl rounded-2xl bg-surface p-6">
        <h1 className="text-[22px] font-extrabold text-ink">결제·쿠폰 운영</h1>
        <p role="alert" className="mt-3 text-[13px] text-ink2">{error}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-4 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white"
        >
          운영 상태 다시 불러오기
        </button>
      </div>
    );
  }

  const envReady = (
    overview.environment.card_registration_env
    && overview.environment.recurring_charge_env
    && overview.environment.reconciliation_env
    && overview.environment.provider_credentials_ready
  );
  const unknownOrders = overview.recent_orders.filter(
    (order) => order.status === "unknown",
  );
  const pendingTokens = overview.recent_agreements.filter(
    (agreement) => agreement.payment_token_status === "revocation_pending",
  );

  return (
    <div className="max-w-6xl">
      <div>
        <h1 className="text-[22px] font-extrabold text-ink">결제·쿠폰 운영</h1>
        <p className="mt-2 text-[13px] leading-6 text-ink3">
          카드 원문과 결제키는 표시하지 않고, 쿠폰과 처리 상태만 관리합니다.
        </p>
      </div>

      {!envReady && (
        <p className="mt-4 rounded-2xl bg-surface p-4 text-[13px] leading-6 text-ink2">
          서버 환경 설정을 마치면 운영 스위치를 켤 수 있어요. 설정을 마치기 전에는 카드 등록과 자동결제가 시작되지 않습니다.
        </p>
      )}
      {message && (
        <p aria-live="polite" className="mt-4 text-[13px] text-success-ink">
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-4 text-[13px] text-danger-ink">
          {error}
        </p>
      )}

      <section className="mt-6" aria-labelledby="billing-status-title">
        <h2 id="billing-status-title" className="text-[16px] font-extrabold text-ink">
          운영 현황
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <CountCard label="무료 이용 중" value={overview.status.trial_count} note="쿠폰 무료 기간을 이용하는 설계사" />
          <CountCard label="정기 이용 중" value={overview.status.active_count} note="월 결제가 확정된 설계사" />
          <CountCard label="미확정 결제" value={overview.status.unknown_order_count} note="재결제 없이 조회만 진행하는 건" />
          <CountCard label="결제키 폐기 대기" value={overview.status.revocation_pending_token_count} note="공급자 확인을 기다리는 건" />
          <CountCard label="쿠폰 점유 중" value={overview.status.held_coupon_claim_count} note="카드 등록을 진행하는 15분 점유" />
        </div>
      </section>

      <section className="mt-8 rounded-2xl bg-surface p-5" aria-labelledby="billing-switch-title">
        <h2 id="billing-switch-title" className="text-[16px] font-extrabold text-ink">
          운영 스위치
        </h2>
        <p className="mt-1 text-[12px] leading-5 text-ink3">
          환경 설정과 운영 스위치가 모두 맞을 때만 사용자 기능이 열립니다.
        </p>
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {([
            ["billing_card_registration_enabled", "카드 등록형 쿠폰"],
            ["billing_reconciliation_enabled", "결제 조회·취소"],
            ["billing_recurring_charge_enabled", "월 정기결제"],
            ["free_tier_unlimited", "무료 무제한"],
          ] as const).map(([field, label]) => {
            const active = overview.settings[field];
            return (
              <div key={field} className="flex items-center justify-between gap-3 rounded-xl border border-line p-3">
                <div>
                  <p className="text-[13px] font-bold text-ink">{label}</p>
                  <p className="mt-0.5 text-[11px] text-ink3">
                    {active ? "켜짐" : "꺼짐"}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void updateSetting(field, !active)}
                  className={`min-h-10 rounded-xl px-4 text-[12px] font-bold ${
                    active
                      ? "bg-brand text-white"
                      : "border border-line text-ink2"
                  } disabled:opacity-50`}
                >
                  {active ? "끄기" : "켜기"}
                </button>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mt-8" aria-labelledby="coupon-create-title">
        <h2 id="coupon-create-title" className="text-[16px] font-extrabold text-ink">
          쿠폰 발행
        </h2>
        <form onSubmit={createCoupon} className="mt-3 grid gap-3 rounded-2xl bg-surface p-5 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-[12px] font-semibold text-ink2">
            무료 이용 개월
            <select
              aria-label="무료 이용 개월"
              value={durationMonths}
              onChange={(event) => setDurationMonths(Number(event.target.value) as 1 | 2 | 3)}
              className="mt-1 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px]"
            >
              <option value={1}>1개월</option>
              <option value={2}>2개월</option>
              <option value={3}>3개월</option>
            </select>
          </label>
          <label className="text-[12px] font-semibold text-ink2">
            쿠폰 사용 기한
            <input
              type="datetime-local"
              aria-label="쿠폰 사용 기한"
              value={redeemBy}
              onChange={(event) => setRedeemBy(event.target.value)}
              className="mt-1 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px]"
            />
          </label>
          <label className="text-[12px] font-semibold text-ink2">
            최대 사용 인원
            <input
              type="number"
              min={1}
              max={100000}
              aria-label="최대 사용 인원"
              value={maxRedemptions}
              onChange={(event) => setMaxRedemptions(Number(event.target.value))}
              className="mt-1 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px]"
            />
          </label>
          <label className="text-[12px] font-semibold text-ink2">
            운영 메모
            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={200}
              placeholder="예: 8월 설명회"
              className="mt-1 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px]"
            />
          </label>
          <button
            type="submit"
            disabled={busy || !redeemBy || maxRedemptions < 1}
            className="min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white disabled:opacity-50 sm:col-span-2 lg:col-span-4"
          >
            {busy ? "처리 중..." : "쿠폰 발행"}
          </button>
        </form>
      </section>

      <section className="mt-8" aria-labelledby="coupon-list-title">
        <h2 id="coupon-list-title" className="text-[16px] font-extrabold text-ink">
          발행한 쿠폰
        </h2>
        {coupons.length === 0 ? (
          <div className="mt-3 rounded-2xl bg-surface p-6 text-[13px] text-ink3">
            첫 쿠폰을 발행하면 코드와 사용 현황이 여기에 표시됩니다.
          </div>
        ) : (
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            {coupons.map((coupon) => (
              <Card key={coupon.id} className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-mono text-[15px] font-extrabold text-ink">{coupon.code}</p>
                    <p className="mt-1 text-[12px] text-ink3">
                      {coupon.duration_months}개월 · {coupon.redeemed_count}/{coupon.max_redemptions}명 사용
                    </p>
                  </div>
                  <span className={`rounded-full px-2 py-1 text-[11px] font-bold ${
                    coupon.is_active
                      ? "bg-success-tint text-success-ink"
                      : "bg-surface2 text-ink3"
                  }`}>
                    {coupon.is_active ? "사용 가능" : "신규 사용 멈춤"}
                  </span>
                </div>
                <p className="mt-3 text-[12px] text-ink2">
                  사용 기한 {dateText(coupon.redeem_by)}
                </p>
                {coupon.note && <p className="mt-1 text-[12px] text-ink3">{coupon.note}</p>}
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void navigator.clipboard.writeText(coupon.code)}
                    className="rounded-lg border border-line px-3 py-2 text-[12px] font-bold text-ink2"
                  >
                    코드 복사
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void toggleCoupon(coupon)}
                    className="rounded-lg border border-line px-3 py-2 text-[12px] font-bold text-ink2 disabled:opacity-50"
                  >
                    {coupon.is_active ? "신규 사용 멈추기" : "다시 사용 열기"}
                  </button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section className="mt-8" aria-labelledby="billing-queue-title">
        <h2 id="billing-queue-title" className="text-[16px] font-extrabold text-ink">
          처리 대기열
        </h2>
        {unknownOrders.length === 0 && pendingTokens.length === 0 ? (
          <div className="mt-3 rounded-2xl bg-surface p-6 text-[13px] text-ink3">
            지금 확인할 미확정 결제나 결제키 폐기 건이 없습니다.
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            {unknownOrders.map((order) => (
              <Card key={`order-${order.id}`} className="p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-[13px] font-bold text-ink">{order.user_email}</p>
                    <p className="mt-1 text-[12px] text-ink3">
                      {ORDER_LABEL[order.status] ?? order.status} · {order.amount_krw.toLocaleString("ko-KR")}원 · 결제일 {dateText(order.due_date)}
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void reconcile(order.id)}
                    className="min-h-10 rounded-xl bg-brand px-4 text-[12px] font-bold text-white disabled:opacity-50"
                  >
                    상태 조회
                  </button>
                </div>
              </Card>
            ))}
            {pendingTokens.map((agreement) => (
              <Card key={`token-${agreement.id}`} className="p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-[13px] font-bold text-ink">{agreement.user_email}</p>
                    <p className="mt-1 text-[12px] text-ink3">
                      {agreement.card_label ?? "등록 카드"} · 결제키 폐기 확인 대기
                    </p>
                  </div>
                  {agreement.payment_token_id && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void revokeToken(agreement.payment_token_id!)}
                      className="min-h-10 rounded-xl border border-line px-4 text-[12px] font-bold text-ink2 disabled:opacity-50"
                    >
                      폐기 다시 확인
                    </button>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
