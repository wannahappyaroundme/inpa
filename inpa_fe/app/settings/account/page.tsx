"use client";

// 계정·모드 설정 — 위촉 형태(전속/GA), 지점장 KPI 공유, 익명 코호트 동의.
// updateProfile(PATCH /auth/profile/) 로 저장. 동의는 모두 기본 거부(opt-in).

import { useState, useEffect } from "react";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { getProfile, updateProfile, type ProfileResponse } from "@/lib/api";

export default function AccountSettingsPage() {
  const ready = useAuthGuard();
  const [p, setP] = useState<ProfileResponse | null>(null);
  const [managerEmail, setManagerEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    getProfile().then((res) => {
      setP(res);
      setManagerEmail(res.manager_email ?? "");
    }).catch(() => { /* useAuthGuard 처리 */ });
  }, [ready]);

  async function patch(payload: Parameters<typeof updateProfile>[0], note: string) {
    setSaving(true);
    setMsg(null);
    try {
      const res = await updateProfile(payload);
      setP(res);
      setManagerEmail(res.manager_email ?? "");
      setMsg(note);
      setTimeout(() => setMsg(null), 1800);
    } catch {
      setMsg("저장 실패");
    } finally {
      setSaving(false);
    }
  }

  if (!ready || !p) return null;

  return (
    <div className="min-h-dvh">
      <AppNav active="settings" />
      <main className="mx-auto max-w-xl px-4 sm:px-6 py-6 space-y-4">
        <h1 className="text-[22px] font-extrabold text-ink">계정 · 모드 설정</h1>
        {msg && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-[13px] text-emerald-700">{msg}</div>
        )}

        {/* 위촉 형태 */}
        <Card className="px-5 py-4">
          <div className="text-[15px] font-bold text-ink">위촉 형태</div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            전속(원수사)은 다사 갈아타기 비교 대신 <b>자사 보장공백</b> 중심으로 표시됩니다.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            {[{ v: 2, label: "GA / 대리점" }, { v: 1, label: "전속(원수사)" }].map((o) => (
              <button
                key={o.v}
                disabled={saving}
                onClick={() => patch({ affiliation_type: o.v }, "위촉 형태를 저장했어요")}
                className={`rounded-xl border px-4 py-3 text-[14px] font-bold transition ${
                  p.affiliation_type === o.v
                    ? "border-brand bg-accent-tint text-brand"
                    : "border-line text-ink2 hover:bg-surface2"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </Card>

        {/* 지점장 KPI 공유 */}
        <Card className="px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="text-[15px] font-bold text-ink">지점장에게 KPI 공유</div>
            <button
              disabled={saving}
              onClick={() => patch({ manager_share_opt_in: !p.manager_share_opt_in }, "공유 설정을 저장했어요")}
              className={`relative w-11 h-6 rounded-full transition ${p.manager_share_opt_in ? "bg-brand" : "bg-line"}`}
              aria-pressed={p.manager_share_opt_in}
            >
              <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${p.manager_share_opt_in ? "left-[22px]" : "left-0.5"}`} />
            </button>
          </div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            켜면 지점장이 내 <b>집계 KPI</b>(고객수·환수위험·공유열람)만 봅니다. 개별 고객 정보는 공유되지 않아요.
          </p>
          <label className="mt-3 block">
            <span className="text-[12px] text-ink3">지점장 이메일</span>
            <div className="mt-1 flex gap-2">
              <input
                type="email"
                value={managerEmail}
                onChange={(e) => setManagerEmail(e.target.value)}
                placeholder="manager@example.com"
                className="flex-1 rounded-xl border border-line px-3 py-2 text-[14px]"
              />
              <button
                disabled={saving}
                onClick={() => patch({ manager_email: managerEmail.trim() }, "지점장을 연결했어요")}
                className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 disabled:opacity-60"
              >
                연결
              </button>
            </div>
          </label>
        </Card>

        {/* 익명 코호트 동의 */}
        <Card className="px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="text-[15px] font-bold text-ink">익명 코호트 분석 참여</div>
            <button
              disabled={saving}
              onClick={() => patch({ cohort_opt_in: !p.cohort_opt_in }, "코호트 설정을 저장했어요")}
              className={`relative w-11 h-6 rounded-full transition ${p.cohort_opt_in ? "bg-brand" : "bg-line"}`}
              aria-pressed={p.cohort_opt_in}
            >
              <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${p.cohort_opt_in ? "left-[22px]" : "left-0.5"}`} />
            </button>
          </div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            익명·집계 형태로만 보장 분포 통계에 기여합니다(개인 식별 정보 제외). 끄면 참여하지 않아요.
          </p>
        </Card>
      </main>
    </div>
  );
}
