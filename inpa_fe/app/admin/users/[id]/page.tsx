"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useAdminGuard } from "@/lib/useAdminGuard";
import {
  adminGetUser,
  adminUpdateSubscription,
  adminSendResetEmail,
  adminListPlans,
  type AdminUserDetail,
  type AdminPlan,
} from "@/lib/adminApi";
import { Card } from "@/components/ui";

function fmt(d: string | null): string {
  if (!d) return "-";
  return new Date(d).toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

// 이번 달 사용량 라벨 (UsageMeter.ACTION_CHOICES 대응)
const USAGE_LABELS: Record<string, string> = {
  ocr: "증권 OCR",
  ai_compare: "AI 비교안내서",
  analysis: "AI 분석·메시지",
  promotion: "판촉물 주문",
};
const USAGE_ORDER = ["ocr", "ai_compare", "analysis", "promotion"];

export default function AdminUserDetailPage() {
  const ready = useAdminGuard();
  const params = useParams<{ id: string }>();
  const userId = Number(params.id);

  const [user, setUser] = useState<AdminUserDetail | null>(null);
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [planChanging, setPlanChanging] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState("");
  const [planMsg, setPlanMsg] = useState<string | null>(null);

  const [resetSending, setResetSending] = useState(false);
  const [resetMsg, setResetMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    setLoading(true);
    Promise.all([adminGetUser(userId), adminListPlans().catch(() => [] as AdminPlan[])])
      .then(([u, p]) => {
        setUser(u);
        setSelectedPlan(u.plan_code);
        setPlans(p);
      })
      .catch(() => setError("설계사 정보를 불러오지 못했어요."))
      .finally(() => setLoading(false));
  }, [ready, userId]);

  async function handlePlanChange() {
    if (!user || selectedPlan === user.plan_code) return;
    setPlanChanging(true);
    setPlanMsg(null);
    try {
      const res = await adminUpdateSubscription(userId, selectedPlan);
      setUser((prev) =>
        prev ? { ...prev, plan_code: res.plan_code, plan_display: res.plan_display } : prev
      );
      setPlanMsg("요금제가 변경되었어요.");
    } catch {
      setPlanMsg("변경에 실패했어요. 다시 시도하세요.");
    } finally {
      setPlanChanging(false);
    }
  }

  async function handleResetEmail() {
    setResetSending(true);
    setResetMsg(null);
    try {
      await adminSendResetEmail(userId);
      setResetMsg("비밀번호 재설정 이메일을 발송했어요.");
    } catch {
      setResetMsg("발송에 실패했어요.");
    } finally {
      setResetSending(false);
    }
  }

  if (!ready) return null;

  // 요금제 옵션: 서버 plans가 있으면 그걸, 없으면 현재 코드만 (404 방지)
  const planOptions: { code: string; label: string }[] =
    plans.length > 0
      ? plans.map((p) => ({ code: p.code, label: `${p.display_name} (${p.code})` }))
      : user
      ? [{ code: user.plan_code, label: user.plan_display }]
      : [];

  return (
    <div className="p-6">
      <div className="mb-4">
        <Link href="/admin/users" className="text-[13px] text-brand hover:underline">
          ← 목록으로
        </Link>
      </div>
      <h1 className="text-[22px] font-extrabold text-ink mb-6">설계사 상세</h1>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-danger-soft border border-line text-[13px] text-danger">{error}</div>
      )}

      {loading && <div className="text-[14px] text-ink3">불러오는 중...</div>}

      {!loading && user && (
        <div className="space-y-5 max-w-2xl">
          {/* 기본 정보 */}
          <Card className="p-5">
            <h2 className="text-[15px] font-bold text-ink mb-4">기본 정보 (읽기 전용)</h2>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-[13px]">
              <div>
                <dt className="text-ink3 mb-0.5">이메일</dt>
                <dd className="font-medium text-ink break-all">{user.email}</dd>
              </div>
              <div>
                <dt className="text-ink3 mb-0.5">소속</dt>
                <dd className="font-medium text-ink">{user.affiliation ?? "-"}</dd>
              </div>
              <div>
                <dt className="text-ink3 mb-0.5">설계사 유형</dt>
                <dd className="font-medium text-ink">{user.agent_type_display ?? "-"}</dd>
              </div>
              <div>
                <dt className="text-ink3 mb-0.5">경력</dt>
                <dd className="font-medium text-ink">
                  {user.career_years != null ? `${user.career_years}년` : "-"}
                </dd>
              </div>
              <div>
                <dt className="text-ink3 mb-0.5">가입일</dt>
                <dd className="font-medium text-ink tnum">{fmt(user.date_joined)}</dd>
              </div>
              <div>
                <dt className="text-ink3 mb-0.5">마지막 로그인</dt>
                <dd className="font-medium text-ink tnum">{fmt(user.last_login)}</dd>
              </div>
              <div>
                <dt className="text-ink3 mb-0.5">이메일 인증</dt>
                <dd className="font-medium text-ink tnum">
                  {user.email_verified_at ? fmt(user.email_verified_at) : "미인증"}
                </dd>
              </div>
              <div>
                <dt className="text-ink3 mb-0.5">상태</dt>
                <dd className="font-medium text-ink">
                  {user.will_delete_at
                    ? `탈퇴 예정 (${fmt(user.will_delete_at)})`
                    : user.is_dormant
                    ? `휴면${user.dormant_at ? ` (${fmt(user.dormant_at)})` : ""}`
                    : "활성"}
                </dd>
              </div>
            </dl>
          </Card>

          {/* 활동 요약 + 이번 달 사용량 */}
          <Card className="p-5">
            <h2 className="text-[15px] font-bold text-ink mb-4">활동 요약 (이번 달, 읽기 전용)</h2>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="rounded-xl bg-surface2 p-3">
                <div className="text-ink3 text-[12px] mb-0.5">고객 수</div>
                <div className="font-bold tnum text-ink text-[20px]">{user.customer_count}</div>
              </div>
              <div className="rounded-xl bg-surface2 p-3">
                <div className="text-ink3 text-[12px] mb-0.5">보유 포트폴리오</div>
                <div className="font-bold tnum text-ink text-[20px]">{user.portfolio_count}</div>
              </div>
              <div className="rounded-xl bg-surface2 p-3">
                <div className="text-ink3 text-[12px] mb-0.5">요금제</div>
                <div className="font-bold text-ink text-[15px] pt-1">{user.plan_display}</div>
              </div>
            </div>
            <dl className="grid grid-cols-4 gap-x-4 gap-y-2 text-[13px]">
              {USAGE_ORDER.map((action) => (
                <div key={action}>
                  <dt className="text-ink3 mb-0.5 text-[12px]">{USAGE_LABELS[action] ?? action}</dt>
                  <dd className="font-bold tnum text-ink text-[16px]">
                    {user.usage_this_month?.[action] ?? 0}
                  </dd>
                </div>
              ))}
            </dl>
          </Card>

          {/* 요금제 변경 */}
          <Card className="p-5">
            <h2 className="text-[15px] font-bold text-ink mb-4">요금제 변경</h2>
            <div className="flex items-center gap-3">
              <select
                value={selectedPlan}
                onChange={(e) => setSelectedPlan(e.target.value)}
                className="rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-brand"
              >
                {planOptions.map((p) => (
                  <option key={p.code} value={p.code}>{p.label}</option>
                ))}
              </select>
              <button
                onClick={handlePlanChange}
                disabled={planChanging || selectedPlan === user.plan_code}
                className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-50 transition"
              >
                {planChanging ? "변경 중..." : "변경"}
              </button>
            </div>
            {planMsg && (
              <p className="mt-2 text-[12px] text-ink3">{planMsg}</p>
            )}
          </Card>

          {/* 비밀번호 재설정 */}
          <Card className="p-5">
            <h2 className="text-[15px] font-bold text-ink mb-2">비밀번호 재설정</h2>
            <p className="text-[12px] text-ink3 mb-3">
              admin이 직접 변경하지 않고, 설계사 이메일로 재설정 링크를 발송합니다.
            </p>
            <button
              onClick={handleResetEmail}
              disabled={resetSending}
              className="rounded-xl border border-line text-[13px] font-semibold text-brand px-4 py-2 hover:bg-accent-tint transition disabled:opacity-50"
            >
              {resetSending ? "발송 중..." : "재설정 이메일 발송"}
            </button>
            {resetMsg && (
              <p className="mt-2 text-[12px] text-ink3">{resetMsg}</p>
            )}
          </Card>

          {/* 동의 로그 요약 (이 설계사 고객들의 최근 동의, 고객명 마스킹) */}
          <Card className="p-5">
            <h2 className="text-[15px] font-bold text-ink mb-1">고객 동의 로그 (읽기 전용)</h2>
            <p className="text-[12px] text-ink3 mb-3">
              이 설계사 고객들의 최근 동의 기록입니다 (고객명 마스킹, 감사 무결성 보호).
            </p>
            {user.consent_logs.length === 0 ? (
              <p className="text-[13px] text-ink3">동의 로그가 없어요.</p>
            ) : (
              <div className="space-y-2">
                {user.consent_logs.map((log) => (
                  <div key={log.id} className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[13px]">
                    <span className="text-ink font-semibold tnum">{log.customer_name_masked}</span>
                    <span className="text-ink">{log.scope_display}</span>
                    <span className="text-ink3 text-[11px]">{log.subject_display}</span>
                    <span className="text-ink3 tnum">{fmt(log.agreed_at)}</span>
                    {log.revoked_at && (
                      <span className="text-danger text-[11px]">철회 {fmt(log.revoked_at)}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
