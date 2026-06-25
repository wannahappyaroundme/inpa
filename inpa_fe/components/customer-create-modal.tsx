"use client";

// 고객 등록 모달 — 이름만 필수, 나머지 선택. createCustomer 실 API 연결.
// booking-modal.tsx 와 동일한 시트형 모달 패턴.

import { useState, useCallback } from "react";
import { createCustomer, ApiError, type CustomerDetail } from "@/lib/api";
import { AVATAR_PALETTE, CustomerAvatar } from "@/components/ui";

export function CustomerCreateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (c: CustomerDetail) => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [gender, setGender] = useState<"" | "1" | "2">("");
  const [birth, setBirth] = useState("");
  const [memo, setMemo] = useState("");
  const [color, setColor] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async () => {
    if (!name.trim()) {
      setError("이름을 입력해 주세요.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const c = await createCustomer({
        name: name.trim(),
        gender: gender || undefined,
        birth_day: birth || undefined,
        mobile_phone_number: phone.trim() || undefined,
        memo: memo.trim() || undefined,
        color: color || undefined,
      });
      onCreated(c);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "등록 중 오류가 발생했어요. 다시 시도해 주세요."
      );
    } finally {
      setSaving(false);
    }
  }, [name, gender, birth, phone, memo, color, onCreated]);

  const inputCls =
    "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand transition";

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="customer-create-title"
    >
      <div className="w-full sm:max-w-md bg-surface rounded-t-3xl sm:rounded-2xl px-6 pt-6 pb-8 shadow-xl">
        <h2 id="customer-create-title" className="text-[18px] font-extrabold text-ink">
          고객 등록
        </h2>
        <p className="mt-2 text-[13px] text-ink3 leading-5">
          이름만 입력해도 등록돼요. 나머지는 나중에 채워도 됩니다.
        </p>

        {error && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
            {error}
          </div>
        )}

        <div className="mt-5 flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">이름 *</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="예) 김보장"
              autoFocus
              className={inputCls}
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">연락처</span>
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="010-1234-5678"
              inputMode="tel"
              className={inputCls}
            />
          </label>

          <div className="flex gap-3">
            <div className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">성별</span>
              <div className="flex gap-1.5">
                {([["1", "남"], ["2", "여"]] as const).map(([v, label]) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setGender((g) => (g === v ? "" : v))}
                    className={`w-12 rounded-xl border py-2.5 text-[14px] font-semibold transition ${
                      gender === v
                        ? "border-brand bg-accent-tint text-brand"
                        : "border-line text-ink3"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <label className="flex flex-col gap-1 flex-1">
              <span className="text-[12px] font-semibold text-ink3">생년월일</span>
              <input
                type="date"
                value={birth}
                onChange={(e) => setBirth(e.target.value)}
                className={inputCls}
              />
            </label>
          </div>

          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">메모</span>
            <textarea
              value={memo}
              onChange={(e) => setMemo(e.target.value)}
              rows={2}
              placeholder="상담 내용·특이사항 (선택)"
              className={inputCls}
            />
          </label>

          {/* 아바타 색상 — 분류용(선택). 미선택 = 인파 로고 디폴트 */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-semibold text-ink3">아바타 색상 (선택 — 분류용)</span>
            <div className="flex items-center gap-2 flex-wrap">
              <CustomerAvatar name={name || "?"} color={color || null} size={34} />
              <button
                type="button"
                onClick={() => setColor("")}
                className={`h-7 px-2 rounded-full border text-[10px] font-semibold ${color === "" ? "border-brand text-brand" : "border-line text-ink3"}`}
                title="기본(인파 로고)"
              >
                로고
              </button>
              {AVATAR_PALETTE.map((hex) => (
                <button
                  key={hex}
                  type="button"
                  onClick={() => setColor(hex)}
                  aria-label={`색상 ${hex}`}
                  className={`w-7 h-7 rounded-full border-2 ${color === hex ? "border-brand" : "border-transparent"}`}
                  style={{ backgroundColor: hex }}
                />
              ))}
            </div>
          </div>
        </div>

        <div className="mt-6 flex flex-col gap-2.5">
          <button
            onClick={submit}
            disabled={saving}
            className="w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 disabled:opacity-60 transition"
          >
            {saving ? "등록 중…" : "등록하기"}
          </button>
          <button
            onClick={onClose}
            disabled={saving}
            className="w-full rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 py-3 disabled:opacity-60 transition"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
