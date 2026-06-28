"use client";

import Link from "next/link";
import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { verifyEmail, resendVerification, ApiError } from "@/lib/api";

type VerifyState = "pending" | "success" | "error";

function VerifyEmailContent() {
  const params = useSearchParams();
  const [state, setState] = useState<VerifyState>("pending");
  const [errorMsg, setErrorMsg] = useState<string>("");
  // 인증 메일 재발송(만료·무효 링크 복구 동선)
  const [resendEmail, setResendEmail] = useState("");
  const [resending, setResending] = useState(false);
  const [resendMsg, setResendMsg] = useState("");

  useEffect(() => {
    const token = params.get("token");

    if (!token) {
      setState("error");
      setErrorMsg("인증 링크가 올바르지 않습니다. 이메일에서 링크를 다시 클릭해 주세요.");
      return;
    }

    verifyEmail(token)
      .then(() => {
        setState("success");
      })
      .catch((err) => {
        setState("error");
        if (err instanceof ApiError) {
          switch (err.code) {
            case "INVALID_OR_EXPIRED_TOKEN":
            case "400":
              setErrorMsg("인증 링크가 만료되었거나 이미 사용되었습니다. 다시 가입하거나 재발송을 요청하세요.");
              break;
            default:
              setErrorMsg(err.message || "이메일 인증 중 오류가 발생했습니다.");
          }
        } else {
          setErrorMsg("네트워크 오류가 발생했습니다. 잠시 후 다시 시도하세요.");
        }
      });
  }, [params]);

  const handleResend = async () => {
    if (!resendEmail.trim() || resending) return;
    setResending(true);
    setResendMsg("");
    try {
      await resendVerification(resendEmail.trim());
      setResendMsg("입력하신 주소가 미인증 계정이면 인증 메일을 다시 보냈어요. 메일함을 확인해 주세요.");
    } catch {
      setResendMsg("재발송 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.");
    }
    setResending(false);
  };

  if (state === "pending") {
    return (
      <div className="flex flex-col items-center gap-4 text-center">
        <span className="inline-block w-10 h-10 border-4 border-[var(--brand)] border-t-transparent rounded-full animate-spin" />
        <p className="text-[14px] text-[var(--ink-3)]">이메일 인증 처리 중...</p>
      </div>
    );
  }

  if (state === "success") {
    return (
      <div className="flex flex-col items-center gap-4 text-center">
        <div className="w-14 h-14 rounded-full bg-success-tint flex items-center justify-center text-success text-[28px]">
          ✓
        </div>
        <h1 className="text-[20px] font-extrabold text-[var(--ink)]">이메일 인증 완료!</h1>
        <p className="text-[13px] text-[var(--ink-3)]">
          이제 로그인하여 인파를 사용하실 수 있습니다.
        </p>
        <Link
          href="/login?verified=true"
          className="mt-2 w-full py-3 rounded-xl bg-[var(--brand)] text-white font-bold text-[15px] text-center hover:opacity-90 transition min-h-[48px] flex items-center justify-center"
        >
          로그인하기
        </Link>
      </div>
    );
  }

  // error
  return (
    <div className="flex flex-col items-center gap-4 text-center">
      <div className="w-14 h-14 rounded-full bg-danger-tint flex items-center justify-center text-danger text-[28px]">
        ✕
      </div>
      <h1 className="text-[20px] font-extrabold text-[var(--ink)]">인증 실패</h1>
      <p className="text-[13px] text-[var(--ink-3)] leading-relaxed">{errorMsg}</p>
      <div className="flex flex-col gap-2 w-full mt-2">
        <Link
          href="/login"
          className="w-full py-3 rounded-xl bg-[var(--brand)] text-white font-bold text-[15px] text-center hover:opacity-90 transition min-h-[48px] flex items-center justify-center"
        >
          로그인 페이지로
        </Link>
        <Link
          href="/register"
          className="w-full py-3 rounded-xl border border-[var(--line)] text-[var(--ink-2)] font-semibold text-[14px] text-center hover:bg-[var(--surface-2)] transition min-h-[48px] flex items-center justify-center"
        >
          다시 가입하기
        </Link>
      </div>
      <div className="w-full mt-3 pt-3 border-t border-[var(--line)] text-left">
        <p className="text-[12px] text-[var(--ink-3)] mb-2">
          인증 메일을 다시 받으시려면 가입한 이메일을 입력하세요.
        </p>
        <div className="flex gap-2">
          <input
            type="email"
            value={resendEmail}
            onChange={(e) => setResendEmail(e.target.value)}
            placeholder="you@example.com"
            className="flex-1 min-w-0 rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-[13px] text-[var(--ink)] outline-none focus:border-[var(--brand)]"
          />
          <button
            type="button"
            onClick={handleResend}
            disabled={resending || !resendEmail.trim()}
            className="shrink-0 rounded-xl bg-[var(--brand)] text-white text-[13px] font-bold px-3 py-2 disabled:opacity-50"
          >
            {resending ? "발송 중" : "재발송"}
          </button>
        </div>
        {resendMsg && <p className="mt-2 text-[12px] text-[var(--ink-2)]">{resendMsg}</p>}
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <div className="min-h-dvh bg-[var(--surface-2)] flex items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-2xl bg-[var(--surface)] border border-[var(--line)] shadow-card p-8">
        <Suspense
          fallback={
            <div className="flex flex-col items-center gap-4 text-center">
              <span className="inline-block w-10 h-10 border-4 border-[var(--brand)] border-t-transparent rounded-full animate-spin" />
              <p className="text-[14px] text-[var(--ink-3)]">로딩 중...</p>
            </div>
          }
        >
          <VerifyEmailContent />
        </Suspense>
      </div>
    </div>
  );
}
