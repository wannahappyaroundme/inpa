"use client";

import Link from "next/link";
import { useState, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { confirmPasswordReset, ApiError } from "@/lib/api";

function Logo() {
  return (
    <svg viewBox="0 0 48 48" width="36" height="36" aria-label="인파" role="img">
      <path d="M16.5 41 V15.5 H25 A7 7 0 0 1 25 29.5 H16.5" fill="none" stroke="#1E40C4" strokeWidth="7.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
    </svg>
  );
}

function ResetPasswordForm() {
  const params = useSearchParams();
  const router = useRouter();

  const uid = params.get("uid") ?? "";
  const token = params.get("token") ?? "";

  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Missing params
  if (!uid || !token) {
    return (
      <div className="flex flex-col items-center gap-4 text-center py-4">
        <div className="w-12 h-12 rounded-full bg-danger-tint flex items-center justify-center text-danger text-[22px]">✕</div>
        <h1 className="text-[18px] font-extrabold text-[var(--ink)]">잘못된 링크</h1>
        <p className="text-[13px] text-[var(--ink-3)]">
          비밀번호 재설정 링크가 올바르지 않습니다. 이메일에서 링크를 다시 클릭하거나,
          비밀번호 찾기를 다시 요청하세요.
        </p>
        <Link
          href="/forgot-password"
          className="mt-2 w-full py-3 rounded-xl bg-[var(--brand)] text-white font-bold text-[15px] text-center hover:opacity-90 transition min-h-[48px] flex items-center justify-center"
        >
          비밀번호 찾기
        </Link>
      </div>
    );
  }

  function validate(): string | null {
    if (newPassword.length < 8) return "비밀번호는 8자 이상이어야 합니다.";
    if (newPassword !== newPasswordConfirm) return "비밀번호가 일치하지 않습니다.";
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const validationErr = validate();
    if (validationErr) { setError(validationErr); return; }

    setLoading(true);
    try {
      await confirmPasswordReset({
        uid,
        token,
        new_password: newPassword,
        new_password_confirm: newPasswordConfirm,
      });
      router.replace("/login?reset=done");
    } catch (err) {
      if (err instanceof ApiError) {
        switch (err.code) {
          case "INVALID_OR_EXPIRED_TOKEN":
          case "400":
            setError("링크가 만료되었거나 이미 사용되었습니다. 비밀번호 찾기를 다시 요청하세요.");
            break;
          default:
            setError(err.message || "비밀번호 변경 중 오류가 발생했습니다.");
        }
      } else {
        setError("네트워크 오류가 발생했습니다. 잠시 후 다시 시도하세요.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <h1 className="text-[18px] font-extrabold text-[var(--ink)]">새 비밀번호 설정</h1>
      <p className="text-[13px] text-[var(--ink-3)]">
        새 비밀번호를 입력하세요. 변경 후 기존 로그인은 모두 무효화됩니다.
      </p>

      {error && (
        <div className="p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger">
          {error}
          {error.includes("만료") && (
            <div className="mt-2">
              <Link href="/forgot-password" className="underline font-semibold">
                비밀번호 찾기 다시 요청
              </Link>
            </div>
          )}
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1">
          <span className="text-[13px] font-semibold text-[var(--ink-2)]">새 비밀번호</span>
          <input
            type="password"
            autoComplete="new-password"
            required
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="w-full rounded-xl border border-[var(--line)] px-4 py-3 text-[14px] text-[var(--ink)] bg-[var(--surface)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)] min-h-[48px]"
            placeholder="8자 이상, 영문+숫자"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[13px] font-semibold text-[var(--ink-2)]">새 비밀번호 확인</span>
          <input
            type="password"
            autoComplete="new-password"
            required
            value={newPasswordConfirm}
            onChange={(e) => setNewPasswordConfirm(e.target.value)}
            className="w-full rounded-xl border border-[var(--line)] px-4 py-3 text-[14px] text-[var(--ink)] bg-[var(--surface)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)] min-h-[48px]"
            placeholder="비밀번호 재입력"
          />
        </label>

        <button
          type="submit"
          disabled={loading}
          className="w-full py-3 rounded-xl bg-[var(--brand)] text-white font-bold text-[15px] min-h-[48px] disabled:opacity-60 hover:opacity-90 transition flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              변경 중...
            </>
          ) : (
            "비밀번호 변경"
          )}
        </button>
      </form>
    </>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="min-h-dvh bg-[var(--surface-2)] flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center gap-2 mb-8">
          <Link href="/" className="flex items-center gap-2">
            <Logo />
            <span className="font-extrabold text-[20px] text-[var(--brand-ink)]">인파</span>
          </Link>
        </div>

        <div className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] shadow-card p-6 flex flex-col gap-4">
          <Suspense
            fallback={
              <div className="flex items-center justify-center py-8">
                <span className="inline-block w-8 h-8 border-4 border-[var(--brand)] border-t-transparent rounded-full animate-spin" />
              </div>
            }
          >
            <ResetPasswordForm />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
