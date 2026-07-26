"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  dismissBillingNotice,
  leaseBillingNotice,
  markBillingNoticeRendered,
  tokenStore,
  type BillingNotice,
} from "@/lib/api";

const DEVICE_KEY = "inpa_billing_notice_device";

function deviceId(): string {
  const existing = window.localStorage.getItem(DEVICE_KEY);
  if (existing) return existing;
  const created = window.crypto.randomUUID();
  window.localStorage.setItem(DEVICE_KEY, created);
  return created;
}

export function FreeTransitionNotice() {
  const [notice, setNotice] = useState<BillingNotice | null>(null);
  const noticeDevice = useRef<string | null>(null);

  useEffect(() => {
    if (!tokenStore.get()) return;
    const currentDevice = deviceId();
    noticeDevice.current = currentDevice;
    leaseBillingNotice(currentDevice)
      .then((result) => setNotice(result.notice))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!notice || !noticeDevice.current) return;
    markBillingNoticeRendered(notice.id, noticeDevice.current)
      .catch(() => undefined);
  }, [notice]);

  if (!notice) return null;

  async function close() {
    const noticeId = notice?.id;
    setNotice(null);
    if (noticeId) {
      await dismissBillingNotice(noticeId).catch(() => undefined);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[90] flex items-end justify-center bg-black/35 p-3 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="billing-transition-title"
    >
      <div className="w-full max-w-md rounded-3xl bg-surface p-5 shadow-2xl sm:p-6">
        <p className="text-[12px] font-bold text-brand">이용 상태 안내</p>
        <h2
          id="billing-transition-title"
          className="mt-1 text-[20px] font-extrabold text-ink"
        >
          {notice.title}
        </h2>
        <p className="mt-3 text-[14px] leading-6 text-ink2">{notice.body}</p>
        {notice.existing_data_available && (
          <p className="mt-3 rounded-xl bg-success-tint px-3 py-2 text-[13px] font-semibold leading-5 text-success">
            기존 고객과 메모, 상담 요약은 그대로 보관돼요.
          </p>
        )}
        <div className="mt-5 grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={close}
            aria-label="안내 닫기"
            className="rounded-xl border border-line px-4 py-3 text-[14px] font-bold text-ink2"
          >
            나중에
          </button>
          <Link
            href={notice.action_path}
            onClick={close}
            className="rounded-xl bg-brand px-4 py-3 text-center text-[14px] font-bold text-white"
          >
            {notice.action_label}
          </Link>
        </div>
      </div>
    </div>
  );
}
