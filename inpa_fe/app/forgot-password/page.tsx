"use client";

import Link from "next/link";
import { useState } from "react";
import { requestPasswordReset, ApiError } from "@/lib/api";

function Logo() {
  return (
    <svg viewBox="0 0 48 48" width="36" height="36" aria-label="인파" role="img">
      <path d="M16.5 41 V15.5 H25 A7 7 0 0 1 25 29.5 H16.5" fill="none" stroke="#1E40C4" strokeWidth="7.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
    </svg>
  );
}

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await requestPasswordReset({ email });
      setSent(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message || "요청 중 오류가 발생했습니다.");
      } else {
        setError("네트워크 오류가 발생했습니다. 잠시 후 다시 시도하세요.");
      }
    } finally {
      setLoading(false);
    }
  }

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
          {sent ? (
            <>
              <div className="flex flex-col items-center gap-3 text-center py-4">
                <div className="w-12 h-12 rounded-full bg-success-tint flex items-center justify-center text-success text-[22px]">✓</div>
                <h1 className="text-[18px] font-extrabold text-[var(--ink)]">이메일을 확인하세요</h1>
                <p className="text-[13px] text-[var(--ink-3)] leading-relaxed">
                  <strong className="text-[var(--ink)]">{email}</strong>로
                  재설정 링크를 발송했습니다. 1시간 내에 클릭하세요.
                </p>
              </div>
              <Link
                href="/login"
                className="w-full py-3 rounded-xl border border-[var(--line)] text-[var(--ink-2)] font-semibold text-[14px] text-center hover:bg-[var(--surface-2)] transition min-h-[48px] flex items-center justify-center"
              >
                로그인 페이지로
              </Link>
            </>
          ) : (
            <>
              <h1 className="text-[18px] font-extrabold text-[var(--ink)]">비밀번호 찾기</h1>
              <p className="text-[13px] text-[var(--ink-3)]">
                가입한 이메일을 입력하면 재설정 링크를 보내드립니다.
              </p>

              {error && (
                <div className="p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                <label className="flex flex-col gap-1">
                  <span className="text-[13px] font-semibold text-[var(--ink-2)]">이메일</span>
                  <input
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full rounded-xl border border-[var(--line)] px-4 py-3 text-[14px] text-[var(--ink)] bg-[var(--surface)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)] min-h-[48px]"
                    placeholder="agent@example.com"
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
                      발송 중...
                    </>
                  ) : (
                    "재설정 링크 받기"
                  )}
                </button>
              </form>

              <Link
                href="/login"
                className="text-center text-[13px] text-[var(--brand)] font-semibold hover:underline"
              >
                로그인으로 돌아가기
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
