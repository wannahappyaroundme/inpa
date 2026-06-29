"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useAdminGuard } from "@/lib/useAdminGuard";
import { adminListConsentLogs, type AdminConsentLogItem } from "@/lib/adminApi";
import { type PaginatedResult } from "@/lib/api";
import { Card } from "@/components/ui";

// 동의 로그 — READ-ONLY. 수정·삭제 버튼 없음(감사 무결성).

function fmt(d: string | null): string {
  if (!d) return "-";
  return new Date(d).toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function ConsentLogsContent() {
  const ready = useAdminGuard();
  const searchParams = useSearchParams();
  const router = useRouter();

  const page = Number(searchParams.get("page") ?? "1");

  const [data, setData] = useState<PaginatedResult<AdminConsentLogItem> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminListConsentLogs({ page });
      setData(res);
    } catch {
      setError("동의 로그를 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { if (ready) fetch(); }, [ready, fetch]);

  if (!ready) return null;

  return (
    <div className="p-6">
      <div className="flex items-center gap-3 mb-2">
        <h1 className="text-[22px] font-extrabold text-ink">동의 로그</h1>
        <span className="text-[11px] font-bold rounded-full px-2 py-0.5 bg-surface2 text-ink3">READ-ONLY</span>
      </div>
      <p className="text-[12px] text-ink3 mb-6">감사 무결성 원칙: 수정·삭제 불가. 열람만 허용.</p>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger-ink">{error}</div>
      )}

      {loading && <div className="text-[14px] text-ink3">불러오는 중...</div>}

      {!loading && data && (
        <>
          <div className="text-[12px] text-ink3 mb-2 tnum">전체 {new Intl.NumberFormat("ko-KR").format(data.count)}건</div>
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="border-b border-line text-ink3">
                    <th className="text-left px-4 py-3 font-semibold">고객명(마스킹)</th>
                    <th className="text-left px-4 py-3 font-semibold">설계사 이메일</th>
                    <th className="text-left px-4 py-3 font-semibold">동의 종류</th>
                    <th className="text-left px-4 py-3 font-semibold">동의 주체</th>
                    <th className="text-left px-4 py-3 font-semibold">동의일</th>
                    <th className="text-left px-4 py-3 font-semibold">버전</th>
                    <th className="text-left px-4 py-3 font-semibold">철회</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.results.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-8 text-center text-ink3">
                        로그가 없어요.
                      </td>
                    </tr>
                  )}
                  {data.results.map((log) => (
                    <tr key={log.id}>
                      <td className="px-4 py-3 font-medium text-ink">{log.customer_name_masked}</td>
                      <td className="px-4 py-3 text-ink3">{log.owner_email ?? "-"}</td>
                      <td className="px-4 py-3 text-ink">{log.scope}</td>
                      <td className="px-4 py-3">
                        <span className={`text-[11px] font-bold rounded-full px-2 py-0.5 ${log.subject === "customer_self" ? "bg-success text-white" : "bg-surface2 text-ink3"}`}>
                          {log.subject_display}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-ink3 tnum">{fmt(log.agreed_at)}</td>
                      <td className="px-4 py-3 text-ink3">{log.doc_version}</td>
                      <td className="px-4 py-3">
                        {log.revoked_at ? (
                          <span className="text-[11px] font-semibold text-danger">{fmt(log.revoked_at)}</span>
                        ) : (
                          <span className="text-[11px] text-ink3">-</span>
                        )}
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
              <button
                onClick={() => router.push(`/admin/consent-logs?page=${page - 1}`)}
                className="text-[13px] font-semibold text-brand"
              >
                ← 이전
              </button>
            )}
            <span className="text-[13px] text-ink3 tnum">페이지 {page}</span>
            {data.next && (
              <button
                onClick={() => router.push(`/admin/consent-logs?page=${page + 1}`)}
                className="text-[13px] font-semibold text-brand"
              >
                다음 →
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default function AdminConsentLogsPage() {
  return (
    <Suspense fallback={null}>
      <ConsentLogsContent />
    </Suspense>
  );
}
