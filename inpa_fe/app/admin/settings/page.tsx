"use client";

import { useState, useEffect } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import {
  adminListPlans,
  adminUpdatePlan,
  adminListPolicyVersions,
  adminCreatePolicyVersion,
  adminGetFlags,
  getBillingMode,
  setBillingMode,
  adminGetInsuranceImportSettings,
  adminUpdateInsuranceImportSettings,
  type AdminPlan,
  type PolicyVersion,
  type FeatureFlags,
  type BillingMode,
  type AdminInsuranceImportSettingsResponse,
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

  const [billingMode, setBillingModeState] = useState<BillingMode | null>(null);
  const [billingLoading, setBillingLoading] = useState(true);
  const [billingToggling, setBillingToggling] = useState(false);
  const [billingMsg, setBillingMsg] = useState<string | null>(null);
  const [bonusToggling, setBonusToggling] = useState(false);
  const [bonusMsg, setBonusMsg] = useState<string | null>(null);

  const [importSettings, setImportSettings] = useState<AdminInsuranceImportSettingsResponse | null>(null);
  const [importSettingsLoading, setImportSettingsLoading] = useState(true);
  const [importSettingsSaving, setImportSettingsSaving] = useState(false);
  const [importPerOwner, setImportPerOwner] = useState("");
  const [importGlobal, setImportGlobal] = useState("");
  const [manualCarrierCodes, setManualCarrierCodes] = useState("");
  const [importSettingsError, setImportSettingsError] = useState<string | null>(null);
  const [importSettingsMessage, setImportSettingsMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    adminListPlans().then(setPlans).finally(() => setPlansLoading(false));
    adminListPolicyVersions().then((r) => setPolicies(r.results)).finally(() => setPolLoading(false));
    adminGetFlags().then(setFlags).finally(() => setFlagsLoading(false));
    getBillingMode().then(setBillingModeState).finally(() => setBillingLoading(false));
    adminGetInsuranceImportSettings()
      .then((result) => {
        setImportSettings(result);
        setImportPerOwner(String(result.runtime.per_owner_concurrency));
        setImportGlobal(String(result.runtime.global_concurrency));
        setManualCarrierCodes(result.runtime.force_manual_carrier_codes.join(", "));
      })
      .catch(() => setImportSettingsError("증권 실행 설정을 불러오려면 잠시 후 다시 눌러 주세요."))
      .finally(() => setImportSettingsLoading(false));
  }, [ready]);

  async function saveInsuranceImportSettings() {
    const perOwner = Number(importPerOwner);
    const globalLimit = Number(importGlobal);
    if (
      !Number.isInteger(perOwner) || !Number.isInteger(globalLimit) ||
      perOwner < 1 || perOwner > 100 || globalLimit < 1 || globalLimit > 100
    ) {
      setImportSettingsError("동시 작업 수는 1부터 100 사이의 정수로 입력해 주세요.");
      return;
    }
    if (perOwner > globalLimit) {
      setImportSettingsError("설계사 한 명의 동시 작업 수는 전체 동시 작업 수 이하로 맞춰 주세요.");
      return;
    }
    const codeParts = manualCarrierCodes.trim()
      ? manualCarrierCodes.split(/[\s,]+/).filter(Boolean)
      : [];
    if (codeParts.some((code) => !/^\d+$/.test(code))) {
      setImportSettingsError("사람 확인으로 돌릴 보험사 코드는 숫자로만 입력해 주세요.");
      return;
    }
    const carrierCodes = [...new Set(codeParts.map(Number))].sort((a, b) => a - b);

    setImportSettingsSaving(true);
    setImportSettingsError(null);
    setImportSettingsMessage(null);
    try {
      const result = await adminUpdateInsuranceImportSettings({
        per_owner_concurrency: perOwner,
        global_concurrency: globalLimit,
        force_manual_carrier_codes: carrierCodes,
      });
      setImportSettings(result);
      setImportPerOwner(String(result.runtime.per_owner_concurrency));
      setImportGlobal(String(result.runtime.global_concurrency));
      setManualCarrierCodes(result.runtime.force_manual_carrier_codes.join(", "));
      setImportSettingsMessage("저장했어요. 다음으로 가져오는 증권 작업부터 새 설정을 사용합니다.");
    } catch {
      setImportSettingsError("입력값을 확인한 뒤 다시 저장해 주세요.");
    } finally {
      setImportSettingsSaving(false);
    }
  }

  async function toggleBillingMode() {
    if (!billingMode) return;
    const next = !billingMode.free_tier_unlimited;
    const confirmMsg = next
      ? "다시 무료 무제한(베타)으로 되돌릴까요? 402 한도 안내가 해제됩니다."
      : "유료 한도를 켜면 모든 설계사에게 402(한도 초과 안내)가 발동됩니다. 진행할까요?";
    if (!confirm(confirmMsg)) return;
    setBillingToggling(true);
    setBillingMsg(null);
    try {
      const result = await setBillingMode({ free_tier_unlimited: next });
      setBillingModeState(result);
      setBillingMsg(next ? "무료 무제한(베타)으로 변경됐어요." : "유료 한도 적용으로 변경됐어요.");
    } catch {
      setBillingMsg("변경에 실패했어요. 다시 시도해 주세요.");
    } finally {
      setBillingToggling(false);
    }
  }

  async function toggleFirstPaidBonus() {
    if (!billingMode) return;
    const next = !billingMode.first_paid_bonus_enabled;
    const confirmMsg = next
      ? "첫 유료 결제 보너스 이벤트를 켤까요? 켜는 동안 첫 유료 구독을 부여하면 자동으로 한 달이 더 붙어요."
      : "첫 유료 결제 보너스 이벤트를 끌까요? 이후 부여부터는 보너스가 붙지 않아요."; // 이미 부여된 구독은 유지
    if (!confirm(confirmMsg)) return;
    setBonusToggling(true);
    setBonusMsg(null);
    try {
      const result = await setBillingMode({ first_paid_bonus_enabled: next });
      setBillingModeState(result);
      setBonusMsg(next ? "첫 결제 보너스 이벤트를 켰어요." : "첫 결제 보너스 이벤트를 껐어요.");
    } catch {
      setBonusMsg("변경에 실패했어요. 다시 시도해 주세요.");
    } finally {
      setBonusToggling(false);
    }
  }

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
    <div className="max-w-3xl">
      <h1 className="text-[22px] font-extrabold text-ink mb-6">운영 설정</h1>

      {/* 증권 자동 정리 실행 설정 */}
      <section className="mb-8">
        <h2 className="text-[16px] font-bold text-ink mb-1">증권 자동 정리 실행 설정</h2>
        <p className="text-[12px] text-ink3 mb-3">
          여러 설계사가 동시에 증권을 올릴 때 작업별로 분리된 대기 순서와 동시 처리 수를 관리해요.
        </p>
        {importSettingsLoading && (
          <div className="h-44 rounded-2xl bg-line animate-pulse" aria-label="증권 실행 설정 불러오는 중" />
        )}
        {!importSettingsLoading && importSettings && (
          <Card className="p-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label htmlFor="import-per-owner" className="block text-[12px] font-semibold text-ink mb-1">
                  설계사 한 명당 동시 작업
                </label>
                <input
                  id="import-per-owner"
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={importPerOwner}
                  onChange={(event) => setImportPerOwner(event.target.value)}
                  className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
                />
                <p className="mt-1 text-[11px] text-ink3">한 설계사의 작업이 한꺼번에 차지하는 수를 제한해요.</p>
              </div>
              <div>
                <label htmlFor="import-global" className="block text-[12px] font-semibold text-ink mb-1">
                  서비스 전체 동시 작업
                </label>
                <input
                  id="import-global"
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={importGlobal}
                  onChange={(event) => setImportGlobal(event.target.value)}
                  className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
                />
                <p className="mt-1 text-[11px] text-ink3">모든 설계사의 증권 작업을 합친 상한이에요.</p>
              </div>
            </div>
            <div className="mt-3">
              <label htmlFor="manual-carrier-codes" className="block text-[12px] font-semibold text-ink mb-1">
                항상 사람 확인으로 보내는 보험사 코드
              </label>
              <input
                id="manual-carrier-codes"
                value={manualCarrierCodes}
                onChange={(event) => setManualCarrierCodes(event.target.value)}
                placeholder="예: 0, 1"
                className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
              />
              <p className="mt-1 text-[11px] text-ink3">쉼표로 나눠 입력해요. 빈칸이면 모든 보험사를 같은 흐름으로 처리해요.</p>
            </div>

            <div className="mt-4 rounded-xl bg-surface2 p-3">
              <div className="text-[12px] font-semibold text-ink">배포에서 정한 기준, 읽기 전용</div>
              <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2 text-[12px]">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-ink3">사람 확인 화면 적용</span>
                  <b className="text-ink">{importSettings.deployment.insurance_review_gate_enabled ? "열림" : "닫힘"}</b>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-ink3">원본 보관 시간</span>
                  <b className="text-ink tnum">{importSettings.deployment.source_retention_hours}시간</b>
                </div>
              </div>
              <p className="mt-2 text-[11px] text-ink3">
                이 두 값은 배포 설정에서만 바뀌며, 이 화면에서는 확인만 할 수 있어요.
              </p>
            </div>

            {importSettingsError && (
              <div className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-[12px] text-danger-ink" role="alert">
                {importSettingsError}
              </div>
            )}
            {importSettingsMessage && (
              <div className="mt-3 rounded-xl bg-success-soft px-3 py-2 text-[12px] text-success">
                {importSettingsMessage}
              </div>
            )}
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={saveInsuranceImportSettings}
                disabled={importSettingsSaving}
                className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-50"
              >
                {importSettingsSaving ? "저장 중..." : "실행 설정 저장"}
              </button>
              <span className="text-[11px] text-ink3">
                처리 중인 작업은 시작할 때의 설정을 유지하고, 다음 작업부터 새 설정을 사용해요.
              </span>
            </div>
          </Card>
        )}
        {!importSettingsLoading && !importSettings && importSettingsError && (
          <Card className="p-4">
            <p className="text-[13px] text-ink2">{importSettingsError}</p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-3 rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2"
            >
              다시 불러오기
            </button>
          </Card>
        )}
      </section>

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
                      {(["limit_ocr", "limit_ai_compare", "limit_analysis", "limit_promotion", "limit_customer"] as const).map((field) => (
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
                        OCR {p.limit_ocr ?? "∞"} · AI비교 {p.limit_ai_compare ?? "∞"} · 분석 {p.limit_analysis ?? "∞"} · 고객추가 {p.limit_customer ?? "∞"} · 판촉 {p.limit_promotion ?? "∞"}
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
                    <span className="text-[10px] font-bold rounded-full px-2 py-0.5 bg-warn-soft text-warning">재동의</span>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}
      </section>

      {/* 유료화 모드 */}
      <section className="mb-8">
        <h2 className="text-[16px] font-bold text-ink mb-3">유료화 모드</h2>
        {billingLoading && <div className="text-[13px] text-ink3">불러오는 중...</div>}
        {!billingLoading && billingMode !== null && (
          <Card className="p-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-[14px] font-semibold text-ink mb-1">
                  현재 상태:&nbsp;
                  <span className={billingMode.free_tier_unlimited ? "text-success font-bold" : "text-warning font-bold"}>
                    {billingMode.free_tier_unlimited ? "무료 무제한(베타)" : "유료 한도 적용 중"}
                  </span>
                </div>
                <div className="text-[12px] text-ink3">
                  무제한(베타): 모든 한도 무시, 402 미발동. 유료 한도: 요금제별 한도 적용, 초과 시 402 발동.
                </div>
                <div className="text-[12px] text-warn-ink mt-1 font-semibold">
                  주의: 전환 시 모든 설계사에게 즉시 적용됩니다.
                </div>
                {billingMsg && (
                  <div className="text-[12px] text-ink mt-2">{billingMsg}</div>
                )}
              </div>
              <button
                onClick={toggleBillingMode}
                disabled={billingToggling}
                className={`shrink-0 rounded-xl px-4 py-2 text-[13px] font-bold disabled:opacity-50 ${
                  billingMode.free_tier_unlimited
                    ? "bg-warning text-white hover:opacity-90"
                    : "bg-success text-white hover:opacity-90"
                }`}
              >
                {billingToggling
                  ? "처리 중..."
                  : billingMode.free_tier_unlimited
                  ? "유료 한도 켜기"
                  : "무제한으로 되돌리기"}
              </button>
            </div>
          </Card>
        )}
      </section>

      {/* 첫 결제 보너스 이벤트 */}
      <section className="mb-8">
        <h2 className="text-[16px] font-bold text-ink mb-3">첫 결제 보너스 이벤트</h2>
        {billingLoading && <div className="text-[13px] text-ink3">불러오는 중...</div>}
        {!billingLoading && billingMode !== null && (
          <Card className="p-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-[14px] font-semibold text-ink mb-1">
                  현재 상태:&nbsp;
                  <span className={billingMode.first_paid_bonus_enabled ? "text-success font-bold" : "text-ink3 font-bold"}>
                    {billingMode.first_paid_bonus_enabled ? "이벤트 진행 중" : "이벤트 꺼짐"}
                  </span>
                </div>
                <div className="text-[12px] text-ink3">
                  켜져 있으면, 설계사에게 첫 유료 요금제(월·연)를 부여할 때 한 달이 자동으로 더 붙어요. 사용자당 한 번만 적용되고, 이후 갱신은 정상 기간으로 부여됩니다.
                </div>
                {bonusMsg && (
                  <div className="text-[12px] text-ink mt-2">{bonusMsg}</div>
                )}
              </div>
              <button
                onClick={toggleFirstPaidBonus}
                disabled={bonusToggling}
                className={`shrink-0 rounded-xl px-4 py-2 text-[13px] font-bold disabled:opacity-50 ${
                  billingMode.first_paid_bonus_enabled
                    ? "bg-warning text-white hover:opacity-90"
                    : "bg-success text-white hover:opacity-90"
                }`}
              >
                {bonusToggling
                  ? "처리 중..."
                  : billingMode.first_paid_bonus_enabled
                  ? "이벤트 끄기"
                  : "이벤트 켜기"}
              </button>
            </div>
          </Card>
        )}
      </section>

      {/* 기능 플래그 */}
      <section>
        <h2 className="text-[16px] font-bold text-ink mb-3">기능 플래그</h2>
        <div className="mb-2 text-[12px] text-ink3 bg-surface2 rounded-xl px-3 py-2 border border-line">
          환경변수(env)로만 변경 가능해요. 배포 설정(Render / Vercel)에서 바꾸세요. 런타임 변경은 컴플라이언스 원칙상 차단됩니다.
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
                      <div className="text-[12px] text-ink3">병력 수집: 국외이전 동의 법무 선결 필요</div>
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
