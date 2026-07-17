"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, useEffect, Suspense } from "react";
import { login, resendVerification, tokenStore, ApiError } from "@/lib/api";
import {
  consumeAuthReturn,
  processAuthReturnSearch,
} from "@/lib/auth-return";
import { GoogleSignInButton } from "@/components/google-signin-button";

// ─── Small Logo ───────────────────────────────────────────────────────────────

function Logo() {
  return (
    <svg viewBox="0 0 48 48" width="36" height="36" aria-label="인파" role="img">
      <path d="M16.5 41 V15.5 H25 A7 7 0 0 1 25 29.5 H16.5" fill="none" stroke="#1E40C4" strokeWidth="7.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
    </svg>
  );
}

// ─── Inner form (uses useSearchParams) ───────────────────────────────────────

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verifiedBanner, setVerifiedBanner] = useState(false);
  const [resetBanner, setResetBanner] = useState(false);
  const [expiredBanner, setExpiredBanner] = useState(false);
  // 미인증 로그인 시 재발송 버튼(2026-07-07: 버튼 부재로 미인증 계정이 메일을 다시 못 받던 문제)
  const [showResend, setShowResend] = useState(false);
  const [resendState, setResendState] = useState<"idle" | "sending" | "sent">("idle");

  async function handleResend() {
    if (!email || resendState === "sending") return;
    setResendState("sending");
    try {
      await resendVerification(email);
    } catch {
      /* 항상 동일 안내(계정 존재 비노출) — 실패해도 아래 문구 유지 */
    }
    setResendState("sent");
  }

  useEffect(() => {
    if (params.get("verified") === "true") setVerifiedBanner(true);
    if (params.get("reset") === "done") setResetBanner(true);
    if (params.get("session") === "expired") setExpiredBanner(true);
    processAuthReturnSearch(window.location.search);
    // Redirect if already logged in
    if (tokenStore.get()) router.replace(consumeAuthReturn() ?? "/home");
  }, [params, router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setShowResend(false);
    setLoading(true);

    try {
      const res = await login({ email, password });
      tokenStore.set(res.token);
      processAuthReturnSearch(window.location.search);
      if (!res.onboarding_completed) {
        router.replace("/onboarding");
      } else {
        router.replace(consumeAuthReturn() ?? "/home");
      }
    } catch (err) {
      if (err instanceof ApiError) {
        switch (err.code) {
          case "EMAIL_NOT_VERIFIED":
            setError("이메일 인증 후 로그인하세요. 받은편지함에서 인증 링크를 확인하세요.");
            setShowResend(true);
            setResendState("idle");
            break;
          case "INVALID_CREDENTIALS":
            setError("이메일 또는 비밀번호가 올바르지 않습니다.");
            break;
          case "ACCOUNT_LOCKED":
          case "LOCKED":
            setError("비밀번호를 5회 틀려 10분간 잠겼습니다. 잠시 후 다시 시도하세요.");
            break;
          default:
            setError(err.message || "로그인 중 오류가 발생했습니다.");
        }
      } else {
        setError("네트워크 오류가 발생했습니다. 잠시 후 다시 시도하세요.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-dvh bg-surface2 flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center gap-2 mb-8">
          <Link href="/" className="flex items-center gap-2">
            <Logo />
            <span className="font-extrabold text-[20px] text-[var(--brand-ink)]">인파</span>
          </Link>
          <p className="text-[13px] text-ink3">보험설계사의 AI 영업 파트너</p>
        </div>

        {/* Banners */}
        {verifiedBanner && (
          <div className="mb-4 p-3 rounded-xl bg-success-tint border border-line text-[13px] text-success">
            이메일 인증이 완료되었습니다. 로그인하세요.
          </div>
        )}
        {resetBanner && (
          <div className="mb-4 p-3 rounded-xl bg-success-tint border border-line text-[13px] text-success">
            비밀번호가 변경되었습니다. 새 비밀번호로 로그인하세요.
          </div>
        )}
        {expiredBanner && (
          <div className="mb-4 p-3 rounded-xl bg-surface2 border border-line text-[13px] text-ink2">
            로그인 정보가 만료되어 로그아웃되었어요. 다시 로그인해주세요.
          </div>
        )}

        {/* Form card */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl bg-surface border border-line shadow-card p-6 flex flex-col gap-4"
        >
          <h1 className="text-[18px] font-extrabold text-ink">로그인</h1>

          {error && (
            <div className="p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger">
              {error}
              {showResend && (
                <div className="mt-2">
                  {resendState === "sent" ? (
                    <p className="text-[12px] text-ink2">
                      인증 메일을 다시 보냈어요. 받은편지함과 스팸함을 확인해 주세요.
                    </p>
                  ) : (
                    <button
                      type="button"
                      onClick={handleResend}
                      disabled={resendState === "sending"}
                      className="rounded-lg border border-line bg-surface px-3 py-1.5 text-[12px] font-semibold text-ink2 transition hover:bg-surface2 disabled:opacity-50"
                    >
                      {resendState === "sending" ? "보내는 중..." : "인증 메일 다시 받기"}
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          <label className="flex flex-col gap-1">
            <span className="text-[13px] font-semibold text-ink2">이메일</span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-xl border border-line px-4 py-3 text-[14px] text-ink bg-surface focus:outline-none focus:ring-2 focus:ring-[var(--brand)] min-h-[48px]"
              placeholder="agent@example.com"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[13px] font-semibold text-ink2">비밀번호</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-xl border border-line px-4 py-3 text-[14px] text-ink bg-surface focus:outline-none focus:ring-2 focus:ring-[var(--brand)] min-h-[48px]"
              placeholder="비밀번호"
            />
          </label>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-xl bg-brand text-white font-bold text-[15px] min-h-[48px] disabled:opacity-60 hover:opacity-90 transition flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                로그인 중...
              </>
            ) : (
              "로그인"
            )}
          </button>

          <div className="flex items-center justify-between text-[13px] text-ink3">
            <Link href="/forgot-password" className="hover:text-brand transition">
              비밀번호를 잊으셨나요?
            </Link>
            <Link href="/register" className="text-brand font-semibold hover:underline">
              회원가입
            </Link>
          </div>
        </form>

        {/* 구글 로그인(병행) — 클라이언트 ID 설정 시에만 노출 */}
        {process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID && (
          <div className="mt-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex-1 h-px bg-line" />
              <span className="text-[12px] text-ink3">또는</span>
              <div className="flex-1 h-px bg-line" />
            </div>
            <GoogleSignInButton />
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-surface2" />}>
      <LoginForm />
    </Suspense>
  );
}
