"use client";

import { useState, useEffect } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import {
  adminListPlans,
  adminUpdatePlan,
  adminListPolicyVersions,
  adminCreatePolicyVersion,
  adminGetFlags,
  type AdminPlan,
  type PolicyVersion,
  type FeatureFlags,
} from "@/lib/adminApi";
import { Card } from "@/components/ui";

const POL_TYPE_LABELS: Record<string, string> = {
  tos:      "이용약관",
  pp:       "개인정보처리방침",
  overseas: "국외이전 동의",
};

export default function AdminSettingsPage() {
  const ready = useAdminGuard();

  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [plansLoading, setPlansLoading] = useState(true);
  const [editingPlan, setEditingPlan] = useState<AdminPlan | null>(null);
  const [planSaving, setPlanSaving] = useState(false);

  const [policies, setPolicies] = useState<PolicyVersion[]>([]);
  const [polLoading, setPolLoading] = useState(true);
  const [newPol, setNewPol] = useState(false);
  const [polType, setPolType] = useState<"tos" | "pp" | "overseas">("tos");
  const [polVersion, setPolVersion] = useState("");
  const [polEffective, setPolEffective] = useState("");
  const [polReconsent, setPolReconsent] = useState(false);
  const [polSaving, setPolSaving] = useState(false);

  const [flags, setFlags] = useState<FeatureFlags | null>(null);
  const [flagsLoading, setFlagsLoading] = useState(true);

  useEffect(() => {
    if (!ready) return;
    adminListPlans().then(setPlans).finally(() => setPlansLoading(false));
    adminListPolicyVersions().then((r) => setPolicies(r.results)).finally(() => setPolLoading(false));
    adminGetFlags().then(setFlags).finally(() => setFlagsLoading(false));
  }, [ready]);

  function openEditPlan(p: AdminPlan) {
    setEditingPlan({ ...p });
  }

  async function savePlan() {
    if (!editingPlan) return;
    if (!confirm(`'${editingPlan.code}' 요금제 한도를 변경하시겠어요? 모든 설계사에게 즉시 적용됩니다.`)) return;
    setPlanSaving(true);
    try {
      const updated = await adminUpdatePlan(editingPlan.code, editingPlan);
      setPlans((prev) => prev.map((p) => (p.code === updated.code ? updated : p)));
      setEditingPlan(null);
    } catch {
      alert("저장에 실패했어요.");
    } finally {
      setPlanSaving(false);
    }
  }

  async function savePolicy() {
    if (!polVersion.trim() || !polEffective) return;
    if (!confirm("약관 신규 버전을 등록하면 즉시 적용됩니다. 계속하시겠어요?")) return;
    setPolSaving(true);
    try {
      const created = await adminCreatePolicyVersion({
        policy_type: polType,
        version: polVersion,
        effective_at: polEffective,
        requires_reconsent: polReconsent,
      });
      setPolicies((prev) => [created, ...prev]);
      setNewPol(false);
      setPolVersion("");
    } catch {
      alert("등록에 실패했어요.");
    } finally {
      setPolSaving(false);
    }
  }

  if (!ready) return null;

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-[22px] font-extrabold text-ink mb-6">운영 설정</h1>

      {/* 요금제 한도 */}
      <section className="mb-8">
        <h2 className="text-[16px] font-bold text-ink mb-3">요금제 & 한도</h2>
        {plansLoading && <div className="text-[13px] text-ink3">불러오는 중...</div>}
        {!plansLoading && (
          <div className="space-y-3">
            {plans.map((p) => (
              <Card key={p.code} className="p-4">
                {editingPlan?.code === p.code ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="font-bold text-ink">{p.code}</span>
                      <span className="text-[12px] text-ink3">{p.display_name}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      {(["limit_ocr", "limit_ai_compare", "limit_analysis", "limit_promotion"] as const).map((field) => (
                        <div key={field}>
                          <label className="block text-[11px] font-semibold text-ink3 mb-1">{field} (null=무제한)</label>
                          <input
                            type="number"
                            value={editingPlan[field] ?? ""}
                            onChange={(e) =>
                              setEditingPlan((prev) =>
                                prev ? { ...prev, [field]: e.target.value === "" ? null : Number(e.target.value) } : prev
                              )
                            }
                            placeholder="무제한"
                            className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
                          />
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={savePlan}
                        disabled={planSaving}
                        className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-50"
                      >
                        {planSaving ? "저장 중..." : "저장"}
                      </button>
                      <button
                        onClick={() => setEditingPlan(null)}
                        className="rounded-xl border border-line text-[13px] font-semibold text-ink2 px-4 py-2 hover:bg-surface2"
                      >
                        취소
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-bold text-ink">{p.code}</span>
                        <span className="text-[12px] text-ink3">{p.display_name}</span>
                        <span className="text-[12px] text-ink3 tnum">{p.price_krw.toLocaleString()}원</span>
                      </div>
                      <div className="text-[12px] text-ink3">
                        OCR {p.limit_ocr ?? "∞"} · AI비교 {p.limit_ai_compare ?? "∞"} · 분석 {p.limit_analysis ?? "∞"} · 판촉 {p.limit_promotion ?? "∞"}
                      </div>
                    </div>
                    <button
                      onClick={() => openEditPlan(p)}
                      className="text-[13px] font-semibold text-brand hover:underline shrink-0"
                    >
                      편집
                    </button>
                  </div>
                )}
              </Card>
            ))}
            {plans.length === 0 && (
              <div className="text-[13px] text-ink3">요금제 정보가 없어요.</div>
            )}
          </div>
        )}
      </section>

      {/* 약관 버전 */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[16px] font-bold text-ink">약관 버전</h2>
          <button
            onClick={() => setNewPol(true)}
            className="text-[13px] font-semibold text-brand hover:underline"
          >
            + 신규 버전 등록
          </button>
        </div>

        {newPol && (
          <Card className="p-4 mb-3">
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[12px] font-semibold text-ink3 mb-1">종류</label>
                  <select
                    value={polType}
                    onChange={(e) => setPolType(e.target.value as typeof polType)}
                    className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
                  >
                    {(["tos", "pp", "overseas"] as const).map((t) => (
                      <option key={t} value={t}>{POL_TYPE_LABELS[t]}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[12px] font-semibold text-ink3 mb-1">버전</label>
                  <input
                    value={polVersion}
                    onChange={(e) => setPolVersion(e.target.value)}
                    placeholder="예: 2026-06-20"
                    className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
                  />
                </div>
              </div>
              <div>
                <label className="block text-[12px] font-semibold text-ink3 mb-1">시행일</label>
                <input
                  type="date"
                  value={polEffective}
                  onChange={(e) => setPolEffective(e.target.value)}
                  className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
                />
              </div>
              <label className="flex items-center gap-2 text-[13px] text-ink cursor-pointer">
                <input type="checkbox" checked={polReconsent} onChange={(e) => setPolReconsent(e.target.checked)} />
                재동의 필요
              </label>
              <div className="flex gap-2">
                <button
                  onClick={savePolicy}
                  disabled={polSaving || !polVersion.trim() || !polEffective}
                  className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-50"
                >
                  {polSaving ? "등록 중..." : "등록"}
                </button>
                <button
                  onClick={() => setNewPol(false)}
                  className="rounded-xl border border-line text-[13px] font-semibold text-ink2 px-4 py-2 hover:bg-surface2"
                >
                  취소
                </button>
              </div>
            </div>
          </Card>
        )}

        {polLoading && <div className="text-[13px] text-ink3">불러오는 중...</div>}
        {!polLoading && (
          <Card>
            <div className="divide-y divide-line">
              {policies.length === 0 && (
                <div className="px-4 py-6 text-center text-[13px] text-ink3">등록된 약관 버전이 없어요.</div>
              )}
              {policies.map((pol) => (
                <div key={pol.id} className="px-4 py-3 flex items-center gap-4">
                  <span className="text-[12px] font-semibold text-ink">{POL_TYPE_LABELS[pol.policy_type] ?? pol.policy_type}</span>
                  <span className="text-[12px] text-ink3">{pol.version}</span>
                  <span className="text-[12px] text-ink3 tnum">{pol.effective_at}</span>
                  {pol.requires_reconsent && (
                    <span className="text-[10px] font-bold rounded-full px-2 py-0.5 bg-orange-50 text-warning">재동의</span>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}
      </section>

      {/* 기능 플래그 */}
      <section>
        <h2 className="text-[16px] font-bold text-ink mb-3">기능 플래그</h2>
        <div className="mb-2 text-[12px] text-ink3 bg-surface2 rounded-xl px-3 py-2 border border-line">
          환경변수(env)로만 변경 가능 — 배포 설정(Render / Vercel)에서 바꾸세요. 런타임 변경은 컴플라이언스 원칙상 차단됩니다.
        </div>
        {flagsLoading && <div className="text-[13px] text-ink3">불러오는 중...</div>}
        {flags && (
          <Card className="p-4">
            <div className="space-y-3">
              {Object.entries(flags).map(([key, val]) => (
                <div key={key} className="flex items-center justify-between">
                  <div>
                    <div className="text-[14px] font-semibold text-ink">{key}</div>
                    {key === "FREE_TIER_UNLIMITED" && (
                      <div className="text-[12px] text-ink3">True=베타(무제한) / False=정식(한도 적용)</div>
                    )}
                    {key === "COMPARE_PUBLISH_ENABLED" && (
                      <div className="text-[12px] text-ink3">§97 법무 완료 전까지 False 유지</div>
                    )}
                    {key === "ANALYZE_MEDICAL_ENABLED" && (
                      <div className="text-[12px] text-ink3">병력 수집 — 국외이전 동의 법무 선결 필요</div>
                    )}
                  </div>
                  <span
                    className={`px-4 py-1.5 rounded-xl text-[13px] font-bold select-none ${
                      val
                        ? "bg-success text-white"
                        : "bg-surface2 text-ink3"
                    }`}
                  >
                    {val ? "ON" : "OFF"}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}
      </section>
    </div>
  );
}
