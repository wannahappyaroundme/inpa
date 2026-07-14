"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { useAdminGuard } from "@/lib/useAdminGuard";
import { adminListUsers, type AdminUserListItem } from "@/lib/adminApi";
import { type PaginatedResult } from "@/lib/api";
import { Card } from "@/components/ui";

function fmt(d: string): string {
  return new Date(d).toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function statusBadge(u: AdminUserListItem) {
  if (u.will_delete_at) return <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-neg-soft text-neg-ink">탈퇴 예정</span>;
  if (u.is_dormant)     return <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-surface2 text-ink3">휴면</span>;
  return <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-pos-soft text-pos-ink">활성</span>;
}

function UsersContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const ready = useAdminGuard();

  const [data, setData] = useState<PaginatedResult<AdminUserListItem> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const page = Number(searchParams.get("page") ?? "1");
  const q = searchParams.get("q") ?? "";
  const plan = searchParams.get("plan") ?? "";

  const [searchInput, setSearchInput] = useState(q);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminListUsers({ page, q: q || undefined, plan: plan || undefined });
      setData(res);
    } catch {
      setError("설계사 목록을 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }, [page, q, plan]);

  useEffect(() => { if (ready) fetch(); }, [ready, fetch]);

  function goSearch() {
    const qs = new URLSearchParams();
    if (searchInput) qs.set("q", searchInput);
    if (plan) qs.set("plan", plan);
    qs.set("page", "1");
    router.push(`/admin/users?${qs.toString()}`);
  }

  if (!ready) return null;

  return (
    <div>
      <h1 className="text-[22px] font-extrabold text-ink mb-6">설계사 관리</h1>

      {/* 검색 */}
      <div className="flex gap-2 mb-4">
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") goSearch(); }}
          placeholder="이름·이메일 검색"
          className="flex-1 rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
        />
        <button
          onClick={goSearch}
          className="rounded-xl bg-brand text-white text-[13px] font-bold px-5 py-2.5"
        >
          검색
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger-ink">{error}</div>
      )}

      {loading && <div className="text-[14px] text-ink3">불러오는 중...</div>}

      {!loading && data && (
        <>
          <div className="text-[13px] text-ink3 mb-3 tnum">전체 {new Intl.NumberFormat("ko-KR").format(data.count)}명</div>
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="border-b border-line text-ink3">
                    <th className="text-left px-4 py-3 font-semibold">이메일</th>
                    <th className="text-left px-4 py-3 font-semibold">소속</th>
                    <th className="text-left px-4 py-3 font-semibold">요금제</th>
                    <th className="text-left px-4 py-3 font-semibold">가입일</th>
                    <th className="text-left px-4 py-3 font-semibold">상태</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.results.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-ink3">
                        결과가 없어요.
                      </td>
                    </tr>
                  )}
                  {data.results.map((u) => (
                    <tr key={u.id} className="hover:bg-surface2 transition">
                      <td className="px-4 py-3 text-ink font-medium">{u.email}</td>
                      <td className="px-4 py-3 text-ink3">{u.affiliation ?? "미입력"}</td>
                      <td className="px-4 py-3 text-ink">{u.plan_display}</td>
                      <td className="px-4 py-3 text-ink3 tnum">{fmt(u.date_joined)}</td>
                      <td className="px-4 py-3">{statusBadge(u)}</td>
                      <td className="px-4 py-3">
                        <Link
                          href={`/admin/users/${u.id}`}
                          className="text-brand font-semibold hover:underline whitespace-nowrap"
                        >
                          상세 →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* 페이지네이션 */}
          <div className="flex items-center justify-center gap-3 mt-4">
            {data.previous && (
              <Link
                href={`/admin/users?page=${page - 1}${q ? `&q=${q}` : ""}`}
                className="text-[13px] font-semibold text-brand hover:underline"
              >
                ← 이전
              </Link>
            )}
            <span className="text-[13px] text-ink3 tnum">페이지 {page}</span>
            {data.next && (
              <Link
                href={`/admin/users?page=${page + 1}${q ? `&q=${q}` : ""}`}
                className="text-[13px] font-semibold text-brand hover:underline"
              >
                다음 →
              </Link>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default function AdminUsersPage() {
  return (
    <Suspense fallback={null}>
      <UsersContent />
    </Suspense>
  );
}
