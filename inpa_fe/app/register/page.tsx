"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { register, getInviteInfo, tokenStore, ApiError, type InviteInfo } from "@/lib/api";
import {
  consumeAuthReturn,
  peekAuthReturn,
  processAuthReturnSearch,
} from "@/lib/auth-return";
import { readCapturedUtm } from "@/lib/useUtmCapture";
import { GoogleSignInButton } from "@/components/google-signin-button";

function Logo() {
  return (
    <svg viewBox="0 0 48 48" width="36" height="36" aria-label="인파" role="img">
      <path d="M16.5 41 V15.5 H25 A7 7 0 0 1 25 29.5 H16.5" fill="none" stroke="#1E40C4" strokeWidth="7.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
    </svg>
  );
}

export default function RegisterPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [affiliation, setAffiliation] = useState("");
  const [title, setTitle] = useState("");
  const [licenseNo, setLicenseNo] = useState("");
  const [tosAgreed, setTosAgreed] = useState(false);
  const [ppAgreed, setPpAgreed] = useState(false);
  const [marketingAgreed, setMarketingAgreed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [authReturnPath, setAuthReturnPath] = useState<string | null>(null);
  // 팀 초대(#24) — ?invite= 토큰. 무효/만료면 칩 없이 일반 가입(가입을 막지 않는다).
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [inviteInfo, setInviteInfo] = useState<InviteInfo | null>(null);

  useEffect(() => {
    setAuthReturnPath(processAuthReturnSearch(window.location.search));
    if (tokenStore.get()) router.replace(consumeAuthReturn() ?? "/home");
  }, [router]);

  // ?invite= 읽기 — useSearchParams Suspense 회피(클라이언트 전용 읽기, /customers 패턴).
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("invite");
    if (!token) return;
    setInviteToken(token);
    getInviteInfo(token)
      .then(setInviteInfo)
      .catch(() => setInviteInfo(null)); // 무효/만료 → 칩 미표시, 정상 가입
  }, []);

  function validate(): string | null {
    if (password.length < 8) return "비밀번호는 8자 이상이어야 합니다.";
    if (password !== passwordConfirm) return "비밀번호가 일치하지 않습니다.";
    if (licenseNo && !/^[A-Za-z0-9-]{4,20}$/.test(licenseNo)) return "정상적인 설계사 번호를 확인해 주세요.";
    if (!tosAgreed) return "이용약관에 동의해야 합니다.";
    if (!ppAgreed) return "개인정보처리방침에 동의해야 합니다.";
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const validationErr = validate();
    if (validationErr) { setError(validationErr); return; }

    setLoading(true);
    try {
      const utm = readCapturedUtm(); // 첫터치 sessionStorage + 현재 URL 쿼리(#16)
      await register({
        email,
        password,
        password_confirm: passwordConfirm,
        tos_agreed: tosAgreed,
        pp_agreed: ppAgreed,
        marketing_agreed: marketingAgreed,
        affiliation: affiliation.trim() || undefined,
        title: title.trim() || undefined,
        license_no: licenseNo || undefined,
        invite_token: inviteToken || undefined,
        utm_source: utm.utm_source || undefined,
        utm_medium: utm.utm_medium || undefined,
        utm_campaign: utm.utm_campaign || undefined,
      });
      setAuthReturnPath(peekAuthReturn());
      setSuccess(true);
    } catch (err) {
      if (err instanceof ApiError) {
        switch (err.code) {
          case "EMAIL_ALREADY_EXISTS":
            setError("이미 가입된 이메일입니다. 로그인 페이지로 이동하세요.");
            break;
          default:
            setError(err.message || "회원가입 중 오류가 발생했습니다.");
        }
      } else {
        setError("네트워크 오류가 발생했습니다. 잠시 후 다시 시도하세요.");
      }
    } finally {
      setLoading(false);
    }
  }

  const allAgreed = tosAgreed && ppAgreed && marketingAgreed;
  function agreeAll() {
    const next = !allAgreed;
    setTosAgreed(next);
    setPpAgreed(next);
    setMarketingAgreed(next);
  }

  if (success) {
    return (
      <div className="min-h-dvh bg-[var(--surface-2)] flex items-center justify-center px-4">
        <div className="w-full max-w-sm rounded-2xl bg-[var(--surface)] border border-[var(--line)] shadow-card p-8 flex flex-col items-center gap-4 text-center">
          <div className="w-12 h-12 rounded-full bg-success-tint flex items-center justify-center text-success text-[24px]">✓</div>
          <h2 className="text-[18px] font-extrabold text-[var(--ink)]">이메일을 확인하세요</h2>
          <p className="text-[13px] text-[var(--ink-3)] leading-relaxed">
            <strong className="text-[var(--ink)]">{email}</strong>로 인증 링크를 발송했습니다.
            이메일을 확인하고 링크를 클릭하면 가입이 완료됩니다.
          </p>
          <Link
            href={authReturnPath ? `/login?next=${authReturnPath}` : "/login"}
            className="mt-2 w-full py-3 rounded-xl bg-[var(--brand)] text-white font-bold text-[15px] text-center hover:opacity-90 transition"
          >
            로그인 페이지로
          </Link>
        </div>
      </div>
    );
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
          <p className="text-[13px] text-[var(--ink-3)]">보험설계사의 AI 영업 파트너</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] shadow-card p-6 flex flex-col gap-4"
        >
          <h1 className="text-[18px] font-extrabold text-[var(--ink)]">회원가입</h1>

          {/* 팀 초대 칩 — 유효한 초대일 때만. 팀 연결만 되고 성과 공유는 본인이 설정에서 선택. */}
          {inviteInfo && (
            <div className="flex items-center gap-2 rounded-xl bg-accent-tint border border-brand/30 px-3 py-2.5">
              <span className="w-6 h-6 rounded-full bg-brand text-white grid place-items-center text-[12px] font-bold shrink-0">
                {inviteInfo.manager_name[0]}
              </span>
              <span className="text-[13px] text-[var(--ink-2)]">
                <b className="text-[var(--ink)]">
                  {inviteInfo.affiliation ? `${inviteInfo.affiliation} ` : ""}{inviteInfo.manager_name}님
                </b>의 팀 초대로 가입 중
              </span>
            </div>
          )}

          {error && (
            <div className="p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger">
              {error}
            </div>
          )}

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

          <label className="flex flex-col gap-1">
            <span className="text-[13px] font-semibold text-[var(--ink-2)]">비밀번호</span>
            <input
              type="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-xl border border-[var(--line)] px-4 py-3 text-[14px] text-[var(--ink)] bg-[var(--surface)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)] min-h-[48px]"
              placeholder="8자 이상, 영문+숫자"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[13px] font-semibold text-[var(--ink-2)]">비밀번호 확인</span>
            <input
              type="password"
              autoComplete="new-password"
              required
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              className="w-full rounded-xl border border-[var(--line)] px-4 py-3 text-[14px] text-[var(--ink)] bg-[var(--surface)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)] min-h-[48px]"
              placeholder="비밀번호 재입력"
            />
          </label>

          {/* 설계사 정보(선택) — 소속/직책/설계사 번호 */}
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-[13px] font-semibold text-[var(--ink-2)]">소속 <span className="font-normal text-[var(--ink-3)]">(선택)</span></span>
              <input
                value={affiliation}
                onChange={(e) => setAffiliation(e.target.value)}
                className="w-full rounded-xl border border-[var(--line)] px-4 py-3 text-[14px] text-[var(--ink)] bg-[var(--surface)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)] min-h-[48px]"
                placeholder="예: 메리츠화재 강남지점"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[13px] font-semibold text-[var(--ink-2)]">직책 <span className="font-normal text-[var(--ink-3)]">(선택)</span></span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full rounded-xl border border-[var(--line)] px-4 py-3 text-[14px] text-[var(--ink)] bg-[var(--surface)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)] min-h-[48px]"
                placeholder="예: FC, 팀장"
              />
            </label>
          </div>

          <label className="flex flex-col gap-1">
            <span className="text-[13px] font-semibold text-[var(--ink-2)]">설계사 번호 <span className="font-normal text-[var(--ink-3)]">(선택)</span></span>
            <input
              value={licenseNo}
              onChange={(e) => setLicenseNo(e.target.value.replace(/[^A-Za-z0-9-]/g, "").slice(0, 20))}
              className="w-full rounded-xl border border-[var(--line)] px-4 py-3 text-[14px] text-[var(--ink)] bg-[var(--surface)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)] min-h-[48px]"
              placeholder="설계사 번호 입력"
            />
            {licenseNo.length > 0 && (
              <span className={`text-[12px] ${/^[A-Za-z0-9-]{4,20}$/.test(licenseNo) ? "text-success" : "text-[var(--ink-3)]"}`}>
                {/^[A-Za-z0-9-]{4,20}$/.test(licenseNo) ? "✓ 확인됐어요" : "정상적인 설계사 번호를 확인해 주세요"}
              </span>
            )}
          </label>

          {/* Terms */}
          <div className="flex flex-col gap-2 pt-1 border-t border-[var(--line)]">
            <p className="text-[12px] font-semibold text-[var(--ink-2)]">약관 동의</p>

            <button
              type="button"
              onClick={agreeAll}
              className={`w-full rounded-xl border py-2.5 text-[13px] font-bold transition ${
                allAgreed ? "border-brand bg-brand text-white" : "border-brand/40 bg-accent-tint text-brand"
              }`}
            >
              {allAgreed ? "전체 동의 완료" : "전체 동의하기"}
            </button>

            <label className="flex items-center gap-3 cursor-pointer min-h-[44px]">
              <input
                type="checkbox"
                checked={tosAgreed}
                onChange={(e) => setTosAgreed(e.target.checked)}
                className="w-4 h-4 accent-[var(--brand)]"
              />
              <span className="text-[13px] text-[var(--ink-2)]">
                <span className="font-semibold text-[var(--danger)]">[필수]</span>{" "}
                <Link href="/legal/terms" target="_blank" className="underline hover:text-[var(--brand)]">이용약관</Link>에 동의합니다.
              </span>
            </label>

            <label className="flex items-center gap-3 cursor-pointer min-h-[44px]">
              <input
                type="checkbox"
                checked={ppAgreed}
                onChange={(e) => setPpAgreed(e.target.checked)}
                className="w-4 h-4 accent-[var(--brand)]"
              />
              <span className="text-[13px] text-[var(--ink-2)]">
                <span className="font-semibold text-[var(--danger)]">[필수]</span>{" "}
                <Link href="/legal/privacy" target="_blank" className="underline hover:text-[var(--brand)]">개인정보처리방침</Link>에 동의합니다.
              </span>
            </label>

            <label className="flex items-center gap-3 cursor-pointer min-h-[44px]">
              <input
                type="checkbox"
                checked={marketingAgreed}
                onChange={(e) => setMarketingAgreed(e.target.checked)}
                className="w-4 h-4 accent-[var(--brand)]"
              />
              <span className="text-[13px] text-[var(--ink-2)]">
                <span className="text-[var(--ink-3)]">[선택]</span>{" "}
                마케팅 정보 수신에 동의합니다.
              </span>
            </label>

            {/* 동의 분리 안내 — 고객 국외이전 동의는 별개임을 명시 */}
            <p className="text-[11px] text-[var(--muted)] leading-relaxed">
              고객 보험증권의 AI 분석 시 고객 개인정보 국외이전 동의는 분석 화면에서 별도 수집됩니다.
              위 약관은 설계사님 본인의 서비스 약관입니다.
            </p>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-xl bg-[var(--brand)] text-white font-bold text-[15px] min-h-[48px] disabled:opacity-60 hover:opacity-90 transition flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                가입 중...
              </>
            ) : (
              "가입하기"
            )}
          </button>

          <p className="text-center text-[13px] text-[var(--ink-3)]">
            이미 계정이 있으신가요?{" "}
            <Link href="/login" className="text-[var(--brand)] font-semibold hover:underline">
              로그인
            </Link>
          </p>
        </form>

        {/* 구글로 시작(병행) — 클라이언트 ID 설정 시에만 노출 */}
        {process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID && (
          <div className="mt-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex-1 h-px bg-[var(--line)]" />
              <span className="text-[12px] text-[var(--ink-3)]">또는</span>
              <div className="flex-1 h-px bg-[var(--line)]" />
            </div>
            <GoogleSignInButton />
          </div>
        )}
      </div>
    </div>
  );
}
