"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { tokenStore } from "@/lib/api";
import { adminLogin } from "@/lib/adminApi";

function AdminLoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const denied = searchParams.get("denied") === "1";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await adminLogin({ email, password });
      tokenStore.set(res.token);
      router.replace("/admin");
    } catch {
      setError("이메일 또는 비밀번호를 확인하세요. 관리자 계정만 로그인할 수 있습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-dvh flex items-center justify-center bg-surface2 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="text-[22px] font-extrabold text-brand-ink mb-1">인파 Admin</div>
          <div className="text-[13px] text-ink3">관리자 전용 로그인</div>
        </div>

        {denied && (
          <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">
            관리자 권한이 없는 계정입니다.
          </div>
        )}

        <form onSubmit={handleSubmit} className="bg-surface rounded-2xl border border-line shadow-sm p-6 space-y-4">
          <div>
            <label className="block text-[13px] font-semibold text-ink mb-1.5">이메일</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              placeholder="admin@inpa.kr"
              className="w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>
          <div>
            <label className="block text-[13px] font-semibold text-ink mb-1.5">비밀번호</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>

          {error && (
            <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-xl bg-brand text-white text-[14px] font-bold py-3 disabled:opacity-50 transition hover:opacity-90"
          >
            {loading ? "로그인 중..." : "관리자 로그인"}
          </button>
        </form>

        <p className="mt-4 text-center text-[12px] text-ink3">
          설계사 로그인은{" "}
          <a href="/login" className="text-brand font-semibold">
            이쪽
          </a>
        </p>
      </div>
    </div>
  );
}

export default function AdminLoginPage() {
  return (
    <Suspense fallback={null}>
      <AdminLoginForm />
    </Suspense>
  );
}
