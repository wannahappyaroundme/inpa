"use client";

// ════════════════════════════════════════════════════════════════════════════
// 고객 1명 중심 상세 셸 — ★ 한 동선 IA 복원 (docs/dev/12 §12 고객상세·탭 IA)
//
// 발굴 → 보장분석 → 갈아타기 제안을 한 고객 화면에서 탭으로 연결한다.
// 탭 4종: 분석(히트맵 + 증권 OCR 입구) / 갈아타기(§97 컴플라이언스 게이트 placeholder)
//        / 공백(미보유 담보) / 이력(접점 placeholder).
//
// 정직성 레드라인:
//  - 분석 판정은 BE 권위(neutral/graded). neutral 이면 부족/충분 단정 금지.
//  - 갈아타기는 §97 법무 게이트 + BE 미구현 → 가짜 데이터 금지, 게이트 사유 명시.
//  - 공백 탭: 부족/충분 단정은 mode='graded' 일 때만.
// ════════════════════════════════════════════════════════════════════════════

import { useState, useEffect, useCallback, Suspense, type ChangeEvent } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card, DisclaimerFooter, CustomerAvatar, AVATAR_PALETTE } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  HeatmapGrid,
  KpiCard,
  fmtAmount,
  fmtWon,
  type FilterKey,
} from "@/components/heatmap";
import {
  useOcrUpload,
  OcrUploadButton,
  OcrStatusBanner,
  ConsentModal,
} from "@/components/ocr-upload";
import { BookingModal } from "@/components/booking-modal";
import { InsuranceManualModal } from "@/components/insurance-manual-modal";
import { UpgradeModal, type UpgradeModalInfo } from "@/components/upgrade-modal";
import { ShareLinkButton } from "@/components/share-link-button";
import { CompareBarChart } from "@/components/charts";
import {
  getCustomer,
  getHeatmap,
  compareCustomer,
  getCustomerHistory,
  getProfile,
  updateCustomer,
  uploadBusinessCard,
  listChecklist,
  applyChecklistTemplate,
  toggleChecklistItem,
  addChecklistItem,
  deleteChecklistItem,
  createConsentRequest,
  SALES_STAGES,
  CUSTOMER_STATUSES,
  ApiError,
  type CustomerDetail,
  type SalesStage,
  type CustomerStatus,
  type HeatmapResponse,
  type HeatmapDetail,
  type CompareResponse,
  type HistoryEvent,
  type ProfileResponse,
  type ContractChecklistItem,
} from "@/lib/api";
import { copyText } from "@/lib/clipboard";

type TabKey = "analysis" | "switch" | "gap" | "info" | "contract" | "history";

const TABS: { key: TabKey; label: string }[] = [
  { key: "analysis", label: "분석" },
  { key: "switch", label: "비교 분석" },
  { key: "gap", label: "공백" },
  { key: "info", label: "정보" },
  { key: "contract", label: "계약" },
  { key: "history", label: "이력" },
];

// ── 헬퍼 ──────────────────────────────────────
function calcAge(birthDay: string | null): string {
  if (!birthDay) return "-";
  const birth = new Date(birthDay);
  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  const m = today.getMonth() - birth.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--;
  return `${age}세`;
}
function genderLabel(g: string | null): string {
  const s = g == null ? "" : String(g);
  if (s === "1" || s === "M") return "남";
  if (s === "2" || s === "F") return "여";
  return "";
}

// ════════════════════════════════════════════════════════════════════════════

export default function CustomerDetailPage() {
  return (
    <Suspense fallback={<DetailSkeleton />}>
      <CustomerDetailInner />
    </Suspense>
  );
}

function DetailSkeleton() {
  return (
    <div className="min-h-dvh">
      <AppNav active="customers" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <div className="h-20 rounded-2xl bg-line animate-pulse" />
        <div className="mt-4 h-10 w-full rounded-xl bg-line animate-pulse" />
        <div className="mt-6 h-40 rounded-2xl bg-line animate-pulse" />
      </main>
    </div>
  );
}

function CustomerDetailInner() {
  const ready = useAuthGuard();
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();

  const customerId = Number(params.id);
  const idValid = Number.isFinite(customerId) && customerId > 0;

  // 위촉 형태 — 전속(1)이면 갈아타기(다사) 탭 숨김 + 공백 탭을 자사 업셀로 분기.
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  useEffect(() => {
    getProfile().then(setProfile).catch(() => setProfile(null));
  }, []);
  const isExclusive = profile?.affiliation_type === 1;
  const visibleTabs = isExclusive ? TABS.filter((t) => t.key !== "switch") : TABS;

  // 탭 상태 (URL ?tab= 동기화). 전속이 switch 진입 시 분석으로 폴백.
  const tabParam = searchParams.get("tab") as TabKey | null;
  let activeTab: TabKey =
    tabParam && TABS.some((t) => t.key === tabParam) ? tabParam : "analysis";
  if (activeTab === "switch" && isExclusive) activeTab = "analysis";

  // 고객 상세
  const [customer, setCustomer] = useState<CustomerDetail | null>(null);
  const [custLoading, setCustLoading] = useState(true);
  const [custError, setCustError] = useState<{
    status: number;
    msg: string;
  } | null>(null);

  // 히트맵 (분석/공백 탭 공유)
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null);
  const [heatmapLoading, setHeatmapLoading] = useState(false);
  const [heatmapError, setHeatmapError] = useState<string | null>(null);
  const [heatmapUpgradeInfo, setHeatmapUpgradeInfo] = useState<UpgradeModalInfo | undefined>(undefined);

  // 히트맵 그리드 UI 상태
  const [graded, setGraded] = useState(true);
  const [filter, setFilter] = useState<FilterKey>("all");

  const fetchHeatmap = useCallback(
    async (id: number) => {
      setHeatmapLoading(true);
      setHeatmapError(null);
      setHeatmap(null);
      setHeatmapUpgradeInfo(undefined);
      try {
        setHeatmap(await getHeatmap(id));
      } catch (e: unknown) {
        if (e instanceof ApiError && e.status === 402) {
          setHeatmapUpgradeInfo(e.creditBody ?? { kind: "analysis" });
        } else {
          setHeatmapError(
            e instanceof Error ? e.message : "분석 데이터를 불러오지 못했어요."
          );
        }
      } finally {
        setHeatmapLoading(false);
      }
    },
    []
  );

  const ocr = useOcrUpload((id) => {
    void fetchHeatmap(id);
  });

  // ── 고객 로드 ──
  useEffect(() => {
    if (!ready || !idValid) return;
    setCustLoading(true);
    setCustError(null);
    getCustomer(customerId)
      .then((c) => setCustomer(c))
      .catch((e: unknown) => {
        const status = e instanceof ApiError ? e.status : 0;
        const msg =
          status === 404
            ? "고객을 찾을 수 없어요."
            : e instanceof Error
            ? e.message
            : "고객 정보를 불러오지 못했어요.";
        setCustError({ status, msg });
      })
      .finally(() => setCustLoading(false));
  }, [ready, idValid, customerId]);

  // ── 히트맵 로드 (분석·공백 탭에서 필요) ──
  useEffect(() => {
    if (!ready || !idValid || custError) return;
    if (activeTab === "analysis" || activeTab === "gap") {
      if (heatmap === null && !heatmapLoading && !heatmapError) {
        void fetchHeatmap(customerId);
      }
    }
  }, [
    ready,
    idValid,
    custError,
    activeTab,
    heatmap,
    heatmapLoading,
    heatmapError,
    customerId,
    fetchHeatmap,
  ]);

  function setTab(tab: TabKey) {
    router.replace(`/customer/${customerId}?tab=${tab}`);
  }

  // 영업 단계 변경(DB·TA·FA·청약) — 칸반 select 대체. 낙관적 업데이트 후 실패 시 재조회.
  const changeStage = useCallback(
    async (to: SalesStage) => {
      setCustomer((c) => (c && c.sales_stage !== to ? { ...c, sales_stage: to } : c));
      try {
        setCustomer(await updateCustomer(customerId, { sales_stage: to }));
      } catch {
        getCustomer(customerId).then(setCustomer).catch(() => {});
      }
    },
    [customerId]
  );

  // 고객 상태 변경(진행중·보류·휴면·종료) — 낙관적 업데이트 후 실패 시 재조회.
  const changeStatus = useCallback(
    async (to: CustomerStatus) => {
      setCustomer((c) => (c && c.status !== to ? { ...c, status: to } : c));
      try {
        setCustomer(await updateCustomer(customerId, { status: to }));
      } catch {
        getCustomer(customerId).then(setCustomer).catch(() => {});
      }
    },
    [customerId]
  );

  if (!ready) return null;

  // 잘못된 ID
  if (!idValid) {
    return (
      <NotFoundShell message="잘못된 고객 주소예요." />
    );
  }

  return (
    <div className="min-h-dvh">
      <AppNav active="customers" />

      <UpgradeModal
        open={heatmapUpgradeInfo !== undefined}
        onClose={() => setHeatmapUpgradeInfo(undefined)}
        info={heatmapUpgradeInfo}
      />

      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        {/* 뒤로 */}
        <Link
          href="/customers"
          className="inline-flex items-center gap-1 text-[13px] font-semibold text-ink3 hover:text-ink2"
        >
          ‹ 고객 목록
        </Link>

        {/* ── 고객 요약 헤더 ── */}
        {custLoading ? (
          <div className="mt-3 h-20 rounded-2xl bg-line animate-pulse" />
        ) : custError ? (
          <div className="mt-3 rounded-2xl border border-line bg-surface2 px-4 py-10 text-center">
            <p className="text-[15px] font-semibold text-ink2">{custError.msg}</p>
            <Link
              href="/customers"
              className="mt-3 inline-block text-[13px] font-semibold text-brand"
            >
              고객 목록으로 →
            </Link>
          </div>
        ) : (
          customer && <CustomerSummary customer={customer} />
        )}

        {/* ── 영업 단계 변경 (DB·TA·FA·청약) — 칸반에서 이동 ── */}
        {customer && !custError && (
          <div className="mt-3">
            <div className="text-[11px] font-semibold text-ink3 mb-1">영업 단계</div>
            <div className="inline-flex rounded-xl border border-line bg-surface2 p-0.5 text-[12px] font-semibold">
              {SALES_STAGES.map((s) => (
                <button
                  key={s.key}
                  onClick={() => changeStage(s.key)}
                  aria-pressed={customer.sales_stage === s.key}
                  className={`px-3 py-1.5 rounded-[10px] transition ${
                    customer.sales_stage === s.key ? "bg-surface text-brand shadow-sm" : "text-ink3 hover:text-ink2"
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── 고객 상태 변경 (진행중·보류·휴면·종료) — PM 06.29 ── */}
        {customer && !custError && (
          <div className="mt-3">
            <div className="text-[11px] font-semibold text-ink3 mb-1">상태</div>
            <div className="inline-flex rounded-xl border border-line bg-surface2 p-0.5 text-[12px] font-semibold">
              {CUSTOMER_STATUSES.map((s) => (
                <button
                  key={s.key}
                  onClick={() => changeStatus(s.key)}
                  aria-pressed={customer.status === s.key}
                  className={`px-3 py-1.5 rounded-[10px] transition ${
                    customer.status === s.key ? "bg-surface text-brand shadow-sm" : "text-ink3 hover:text-ink2"
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── 탭 바 ── */}
        {!custError && (
          <>
            <div
              role="tablist"
              aria-label="고객 상세 탭"
              className="mt-5 flex gap-1 border-b border-line overflow-x-auto"
            >
              {visibleTabs.map((t) => (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={activeTab === t.key}
                  onClick={() => setTab(t.key)}
                  className={`relative px-4 py-2.5 text-[14px] font-semibold whitespace-nowrap transition ${
                    activeTab === t.key
                      ? "text-brand"
                      : "text-ink3 hover:text-ink2"
                  }`}
                >
                  {t.label}
                  {activeTab === t.key && (
                    <span className="absolute left-2 right-2 -bottom-px h-0.5 rounded-full bg-brand" />
                  )}
                </button>
              ))}
            </div>

            {/* ── 탭 콘텐츠 ── */}
            <div className="mt-5">
              {activeTab === "analysis" && (
                <AnalysisTab
                  customerId={customerId}
                  consented={!!customer?.consent_overseas_at}
                  heatmap={heatmap}
                  loading={heatmapLoading}
                  error={heatmapError}
                  onRetry={() => fetchHeatmap(customerId)}
                  graded={graded}
                  onGradedChange={setGraded}
                  filter={filter}
                  onFilterChange={setFilter}
                  ocr={ocr}
                />
              )}
              {activeTab === "switch" && <SwitchTab customerId={customerId} />}
              {activeTab === "gap" && (
                <GapTab
                  heatmap={heatmap}
                  loading={heatmapLoading}
                  error={heatmapError}
                  onRetry={() => fetchHeatmap(customerId)}
                  isExclusive={isExclusive}
                />
              )}
              {activeTab === "info" && customer && (
                <InfoTab customer={customer} onUpdated={setCustomer} />
              )}
              {activeTab === "contract" && <ChecklistTab customerId={customerId} />}
              {activeTab === "history" && <HistoryTab customerId={customerId} />}
            </div>
          </>
        )}

        <DisclaimerFooter />
      </main>
    </div>
  );
}

// ── 고객 요약 헤더 ────────────────────────────────────────────────────────
function CustomerSummary({ customer }: { customer: CustomerDetail }) {
  const age =
    customer.insurance_age != null ? `${customer.insurance_age}세` : calcAge(customer.birth_day);
  const sub = [age, genderLabel(customer.gender)]
    .filter(Boolean)
    .join(" · ");
  return (
    <Card className="mt-3 p-4 flex items-center gap-3">
      <CustomerAvatar label={customer.avatar_label} color={customer.color} size={48} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[18px] font-bold text-ink">{customer.name}</span>
          {sub && <span className="text-[13px] text-ink3">{sub}</span>}
          {customer.tags.slice(0, 3).map((tag) => (
            <span
              key={tag.id}
              className="text-[11px] font-semibold rounded-full px-2 py-0.5"
              style={{
                backgroundColor: tag.color ? `${tag.color}20` : undefined,
                color: tag.color ?? undefined,
              }}
            >
              {tag.label}
            </span>
          ))}
        </div>
        <div className="mt-0.5 text-[12px] text-ink3">
          {customer.mobile_phone_number ?? "연락처 없음"}
          {customer.family_count > 0 && <span> · 가족 {customer.family_count}명</span>}
          {customer.consent_overseas_at ? (
            <span> · 국외이전 동의 완료</span>
          ) : (
            <span> · 국외이전 동의 전</span>
          )}
        </div>
      </div>
    </Card>
  );
}

// ── 정보 탭 (폴리오식: 좌=메모 / 우=상세정보 / 하단=명함) — PM 06.24 ──
function InfoTab({
  customer,
  onUpdated,
}: {
  customer: CustomerDetail;
  onUpdated: (c: CustomerDetail) => void;
}) {
  const [name, setName] = useState(customer.name);
  const [phone, setPhone] = useState(customer.mobile_phone_number ?? "");
  const [gender, setGender] = useState(customer.gender == null ? "" : String(customer.gender));
  const [birth, setBirth] = useState(customer.birth_day ?? "");
  const [color, setColor] = useState(customer.color ?? "");
  const [avatarLabel, setAvatarLabel] = useState(customer.avatar_label ?? "");
  const [memo, setMemo] = useState(customer.memo ?? "");
  const [savingInfo, setSavingInfo] = useState(false);
  const [savingMemo, setSavingMemo] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // 저장 성공 안내는 폼을 다시 수정하면 사라진다(이전 저장 메시지가 계속 남지 않게).
  useEffect(() => { setMsg(null); }, [name, phone, gender, birth, color, avatarLabel, memo]);

  const flash = (m: string) => { setMsg(m); setErr(null); };
  const fail = (e: unknown) => { setErr(e instanceof ApiError ? e.message : "저장에 실패했어요."); setMsg(null); };

  async function saveInfo() {
    setSavingInfo(true);
    try {
      const c = await updateCustomer(customer.id, {
        name: name.trim(),
        mobile_phone_number: phone.trim(),
        gender: gender || undefined,
        birth_day: birth || undefined,
        color,
        avatar_label: avatarLabel.trim(),
      });
      onUpdated(c);
      flash("상세정보를 저장했어요.");
    } catch (e) { fail(e); } finally { setSavingInfo(false); }
  }
  async function saveMemo() {
    setSavingMemo(true);
    try {
      const c = await updateCustomer(customer.id, { memo });
      onUpdated(c);
      flash("메모를 저장했어요.");
    } catch (e) { fail(e); } finally { setSavingMemo(false); }
  }
  async function onPickCard(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const c = await uploadBusinessCard(customer.id, file);
      onUpdated(c);
      flash("명함을 업로드했어요.");
    } catch (e2) { fail(e2); } finally { setUploading(false); e.target.value = ""; }
  }

  const inputCls =
    "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand transition";

  // 동의 배지 헬퍼
  const piState = customer.consents?.personal_info;
  const mkState = customer.consents?.marketing;
  const subjectTag = (s: string | null | undefined) =>
    s === "customer_self" ? "본인 동의" : s === "planner_attested" ? "설계사 기록" : "";
  const consentLine = (label: string, state: { status: string; subject: string | null } | undefined) => {
    if (!state || state.status === "none") return `${label} 미동의`;
    if (state.status === "revoked") return `${label} 철회`;
    const tag = subjectTag(state.subject);
    return `${label} 동의${tag ? ` · ${tag}` : ""}`;
  };

  // 동의 요청 링크 — 클립보드 복사까지만(자동발송 없음).
  const [consentBusy, setConsentBusy] = useState(false);
  const sendConsentLink = useCallback(async () => {
    setConsentBusy(true);
    try {
      const res = await createConsentRequest(customer.id, ["personal_info", "marketing"]);
      const ok = await copyText(res.consent_url);
      flash(ok ? "동의 요청 링크를 복사했어요. 고객에게 보내세요." : res.consent_url);
    } catch (e) {
      fail(e);
    } finally {
      setConsentBusy(false);
    }
  }, [customer.id]);

  const riskLabel =
    customer.job_risk_grade && customer.job_risk_grade <= 3 ? `위험 ${customer.job_risk_grade}급` : null;

  return (
    <div className="space-y-4">
      {(msg || err) && (
        <div className={`rounded-xl px-4 py-2.5 text-[13px] ${err ? "border border-rose-200 bg-rose-50 text-rose-700" : "border border-emerald-200 bg-emerald-50 text-emerald-700"}`}>
          {err ?? msg}
        </div>
      )}

      <div className="grid lg:grid-cols-[1fr_1.2fr] gap-4">
        {/* 왼쪽: 메모 */}
        <Card className="p-4 flex flex-col">
          <h3 className="text-[15px] font-bold text-ink">메모</h3>
          <textarea
            value={memo}
            onChange={(e) => setMemo(e.target.value)}
            rows={10}
            placeholder="상담 내용·특이사항·다음 액션을 적어두세요."
            className={`${inputCls} mt-2 flex-1 resize-none`}
          />
          <button
            onClick={saveMemo}
            disabled={savingMemo}
            className="mt-2 self-end rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-60"
          >
            {savingMemo ? "저장 중…" : "메모 저장"}
          </button>
        </Card>

        {/* 오른쪽: 상세정보 */}
        <Card className="p-4">
          <div className="flex items-center gap-3">
            <CustomerAvatar label={avatarLabel} color={color || null} size={44} />
            <h3 className="text-[15px] font-bold text-ink">상세정보</h3>
          </div>

          <div className="mt-3 grid sm:grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">이름</span>
              <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">연락처</span>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" className={inputCls} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">생년월일</span>
              <input type="date" value={birth} onChange={(e) => setBirth(e.target.value)} className={inputCls} />
            </label>
            <div className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">성별</span>
              <div className="flex gap-1.5">
                {([["1", "남"], ["2", "여"]] as const).map(([v, l]) => (
                  <button key={v} type="button"
                    onClick={() => setGender((g) => (g === v ? "" : v))}
                    className={`flex-1 rounded-xl border py-2.5 text-[14px] font-semibold ${gender === v ? "border-brand bg-accent-tint text-brand" : "border-line text-ink3"}`}>
                    {l}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* 아바타 글씨·색상 — 글씨 비우면 인파 로고. 색은 공통 배경 */}
          <div className="mt-3 flex flex-col gap-2">
            <span className="text-[12px] font-semibold text-ink3">아바타 글씨·색상</span>
            <div className="flex items-center gap-3">
              <CustomerAvatar label={avatarLabel} color={color || null} size={40} />
              <input
                value={avatarLabel}
                onChange={(e) => setAvatarLabel(e.target.value.slice(0, 3))}
                placeholder="약자·숫자 (비우면 로고)"
                maxLength={3}
                className="flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
              />
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[11px] text-ink3 mr-0.5">배경</span>
              <button type="button" onClick={() => setColor("")}
                className={`h-7 px-2 rounded-full border text-[10px] font-semibold ${color === "" ? "border-brand text-brand" : "border-line text-ink3"}`}>기본</button>
              {AVATAR_PALETTE.map((hex) => (
                <button key={hex} type="button" onClick={() => setColor(hex)} aria-label={`배경 ${hex}`}
                  className={`w-7 h-7 rounded-full border-2 ${color === hex ? "border-brand" : "border-transparent"}`}
                  style={{ backgroundColor: hex }} />
              ))}
            </div>
          </div>

          {/* 읽기 전용 파생 정보 */}
          <dl className="mt-3 grid grid-cols-2 gap-y-1.5 text-[13px]">
            <dt className="text-ink3">보험나이</dt>
            <dd className="text-ink2 text-right">{customer.insurance_age != null ? `${customer.insurance_age}세` : "-"}</dd>
            <dt className="text-ink3">직업</dt>
            <dd className="text-ink2 text-right">{customer.job_name ?? "-"}{riskLabel ? ` (${riskLabel})` : ""}</dd>
            <dt className="text-ink3">영업 단계</dt>
            <dd className="text-ink2 text-right">{customer.sales_stage.toUpperCase()}</dd>
          </dl>

          {/* 동의 배지 + 요청 링크 */}
          <div className="mt-3 rounded-xl border border-line bg-surface px-4 py-3">
            <div className="text-[12px] font-semibold text-ink3">동의</div>
            <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
              <span className="rounded-full bg-accent-tint px-2 py-0.5 text-brand">{consentLine("개인정보", piState)}</span>
              <span className="rounded-full bg-accent-tint px-2 py-0.5 text-brand">{consentLine("마케팅", mkState)}</span>
            </div>
            <button
              onClick={sendConsentLink}
              disabled={consentBusy}
              className="mt-2.5 w-full rounded-xl border border-brand text-brand text-[13px] font-semibold py-2 disabled:opacity-60"
            >
              {consentBusy ? "링크 생성 중…" : "동의 요청 링크 복사(고객 본인용)"}
            </button>
            <p className="mt-1.5 text-[11px] text-ink3 leading-4">
              가장 안전한 건 고객 본인이 링크로 직접 동의하는 거예요. 링크를 복사해 고객에게 전달하세요.
            </p>
          </div>

          <button onClick={saveInfo} disabled={savingInfo}
            className="mt-4 w-full rounded-xl bg-brand text-white text-[14px] font-bold py-2.5 disabled:opacity-60">
            {savingInfo ? "저장 중…" : "상세정보 저장"}
          </button>
        </Card>
      </div>

      {/* 하단: 명함 */}
      <Card className="p-4">
        <h3 className="text-[15px] font-bold text-ink">명함</h3>
        <p className="mt-1 text-[12px] text-ink3">명함·방명록 사진을 올려두면 보관돼요. (자동 인식은 준비 중이에요. 정보는 위에서 직접 입력해 주세요.)</p>
        <div className="mt-3 flex items-center gap-4 flex-wrap">
          {customer.business_card ? (
            <a href={customer.business_card} target="_blank" rel="noreferrer">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={customer.business_card} alt="명함" className="h-28 rounded-xl border border-line object-contain bg-surface2" />
            </a>
          ) : (
            <div className="h-28 w-44 rounded-xl border border-dashed border-line bg-surface2 flex items-center justify-center text-[12px] text-ink3">명함 없음</div>
          )}
          <label className="rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] font-semibold text-ink2 cursor-pointer hover:bg-surface2">
            {uploading ? "업로드 중…" : customer.business_card ? "명함 교체" : "명함 업로드"}
            <input type="file" accept="image/*" onChange={onPickCard} disabled={uploading} className="hidden" />
          </label>
        </div>
      </Card>
    </div>
  );
}

// ── 계약 탭 (설명의무 체크리스트) — PM 06.24 ──
function ChecklistTab({ customerId }: { customerId: number }) {
  const [items, setItems] = useState<ContractChecklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newLabel, setNewLabel] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    listChecklist(customerId)
      .then((r) => setItems(r.results))
      .catch(() => setErr("불러오지 못했어요."))
      .finally(() => setLoading(false));
  }, [customerId]);
  useEffect(() => { load(); }, [load]);

  async function applyTemplate() {
    setBusy(true); setErr(null);
    try { await applyChecklistTemplate(customerId); load(); }
    catch { setErr("템플릿 적용에 실패했어요."); } finally { setBusy(false); }
  }
  async function toggle(id: number) {
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, is_done: !it.is_done } : it)));
    try { await toggleChecklistItem(customerId, id); } catch { load(); }
  }
  async function addItem() {
    if (!newLabel.trim()) return;
    setBusy(true);
    try { await addChecklistItem(customerId, newLabel.trim()); setNewLabel(""); load(); }
    catch { setErr("추가에 실패했어요."); } finally { setBusy(false); }
  }
  async function remove(id: number) {
    setItems((prev) => prev.filter((it) => it.id !== id));
    try { await deleteChecklistItem(customerId, id); } catch { load(); }
  }

  const doneCount = items.filter((i) => i.is_done).length;

  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-[15px] font-bold text-ink">설명의무 체크리스트</h3>
        {items.length > 0 && <span className="text-[12px] text-ink3 tnum">{doneCount}/{items.length} 완료</span>}
      </div>
      <p className="mt-1 text-[12px] text-ink3 leading-5">
        상담 시 설명 의무 이행을 직접 점검·기록해요.
      </p>

      {/* §97 불리사항 구두고지 안내 — 설계사 내부 전용(고객 화면·공유뷰 비노출) */}
      <div className="mt-3 rounded-xl border border-amber-300/70 bg-amber-50 px-3.5 py-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-bold text-amber-900">갈아타기(승환) 계약이면, 불리사항 구두 고지</span>
          <span className="ml-auto shrink-0 text-[10px] font-semibold rounded-full bg-white/70 text-amber-800 px-2 py-0.5">설계사 내부 · 고객 비노출</span>
        </div>
        <p className="mt-1.5 text-[12px] leading-5 text-amber-900/90">
          기존 계약을 해지하고 새로 가입하는 경우 <b>해지 환급 손실·면책(감액) 기간 리셋</b> 등 고객에게 불리할 수 있는 점을 상담에서 <b>반드시 구두로 고지</b>하세요. 고객별 구체 항목은 <b>비교 탭</b>에서 확인할 수 있어요.
        </p>
      </div>

      {err && <div className="mt-2 text-[13px] text-rose-700">{err}</div>}

      {loading ? (
        <div className="mt-4 h-20 rounded-xl bg-line animate-pulse" />
      ) : items.length === 0 ? (
        <div className="mt-5 text-center">
          <p className="text-[13px] text-ink3">아직 체크리스트가 없어요.</p>
          <button onClick={applyTemplate} disabled={busy}
            className="mt-3 rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-60">
            {busy ? "생성 중…" : "기본 템플릿 불러오기"}
          </button>
        </div>
      ) : (
        <>
          <ul className="mt-3 space-y-1.5">
            {items.map((it) => (
              <li key={it.id} className="flex items-center gap-2.5">
                <button onClick={() => toggle(it.id)} aria-label="완료 토글"
                  className={`w-5 h-5 rounded border shrink-0 flex items-center justify-center ${it.is_done ? "bg-brand border-brand" : "border-line"}`}>
                  {it.is_done && <span className="text-white text-[11px] leading-none">✓</span>}
                </button>
                <span className={`flex-1 text-[14px] ${it.is_done ? "line-through text-ink3" : "text-ink"}`}>{it.label}</span>
                <button onClick={() => remove(it.id)} aria-label="삭제" className="text-ink3 hover:text-rose-600 text-[13px] px-1">✕</button>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex gap-2">
            <input value={newLabel} onChange={(e) => setNewLabel(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addItem(); }}
              placeholder="항목 추가" className="flex-1 rounded-xl border border-line px-3 py-2 text-[13px]" />
            <button onClick={addItem} disabled={busy || !newLabel.trim()}
              className="rounded-xl border border-line text-ink2 text-[13px] font-semibold px-3 disabled:opacity-50">추가</button>
          </div>
        </>
      )}
    </Card>
  );
}

// ── 분석 탭 ───────────────────────────────────────────────────────────────
type OcrCtl = ReturnType<typeof useOcrUpload>;

function AnalysisTab({
  customerId,
  consented,
  heatmap,
  loading,
  error,
  onRetry,
  graded,
  onGradedChange,
  filter,
  onFilterChange,
  ocr,
}: {
  customerId: number;
  consented: boolean;
  heatmap: HeatmapResponse | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  graded: boolean;
  onGradedChange: (g: boolean) => void;
  filter: FilterKey;
  onFilterChange: (f: FilterKey) => void;
  ocr: OcrCtl;
}) {
  const [bookingOpen, setBookingOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  return (
    <div>
      {/* 증권 OCR 업로드 입구 (분석 탭으로 이동) */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13px] text-ink3">담보 한눈표 · 설계사 도구</div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setBookingOpen(true)}
            className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition"
          >
            미팅 예약 링크
          </button>
          <button
            type="button"
            onClick={ocr.openConsent}
            className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition"
          >
            고객 동의 링크
          </button>
          <OcrUploadButton
            customerId={customerId}
            phase={ocr.phase}
            onFileChange={ocr.onFileChange}
            consented={consented}
            onNeedConsent={ocr.openConsent}
          />
          <button
            type="button"
            onClick={() => setManualOpen(true)}
            className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition"
          >
            직접 입력
          </button>
          <ShareLinkButton customerId={customerId} />
        </div>
      </div>
      {bookingOpen && (
        <BookingModal customerId={customerId} onClose={() => setBookingOpen(false)} />
      )}
      {manualOpen && (
        <InsuranceManualModal
          customerId={customerId}
          onClose={() => setManualOpen(false)}
          onCreated={() => {
            setManualOpen(false);
            onRetry();
          }}
        />
      )}

      <OcrStatusBanner
        phase={ocr.phase}
        errorMsg={ocr.error}
        onDismiss={ocr.clearError}
      />
      {ocr.phase === "consent_required" && (
        <ConsentModal
          onGenerate={() => ocr.generateConsentLink(customerId)}
          consentUrl={ocr.consentUrl}
          consentCopied={ocr.consentCopied}
          onCopy={ocr.copyConsentUrl}
          onDismiss={ocr.dismissConsent}
          loading={ocr.consentLoading}
        />
      )}

      <UpgradeModal
        open={ocr.phase === "limit_exceeded"}
        onClose={ocr.dismissUpgrade}
        info={ocr.upgradeInfo}
      />

      {/* 기준 미설정 안내는 히트맵 컴포넌트(HeatmapGrid) 상단 CTA로 일원화 — 중복 박스 제거(PM 06.29) */}

      {/* KPI */}
      {heatmap && (
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="월 보험료" value={fmtWon(heatmap.summary.monthly_premiums)} />
          <KpiCard label="총 납입 보험료" value={fmtWon(heatmap.summary.total_premiums)} />
          <KpiCard label="보험 건수" value={`${heatmap.insurance_count}건`} />
          <KpiCard
            label="분석 모드"
            value={heatmap.mode === "neutral" ? "기준 미설정" : "기준 적용"}
            valueClass={heatmap.mode === "neutral" ? "text-ink3" : "text-enough"}
          />
        </div>
      )}

      {/* 로딩 */}
      {loading && (
        <div className="mt-8 space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-start gap-3">
              <div className="w-16 h-6 rounded bg-line animate-pulse shrink-0" />
              <div className="flex gap-2 flex-wrap">
                {Array.from({ length: 4 }).map((_, j) => (
                  <div key={j} className="w-20 h-8 rounded-lg bg-line animate-pulse" />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 에러 */}
      {error && !loading && (
        <div className="mt-6 rounded-xl border border-line bg-surface2 px-4 py-8 text-center">
          <p className="text-[14px] text-ink3">{error}</p>
          <button onClick={onRetry} className="mt-3 text-[13px] font-semibold text-brand">
            다시 시도
          </button>
        </div>
      )}

      {/* 보험 없음 */}
      {!loading && !error && heatmap && heatmap.insurance_count === 0 && (
        <div className="mt-6 rounded-xl border border-dashed border-line px-4 py-12 text-center">
          <p className="text-[15px] font-semibold text-ink2">증권이 아직 없어요</p>
          <p className="mt-1 text-[13px] text-ink3">
            증권을 등록하면 보장 한눈표가 보여요.
          </p>
          <div className="mt-3 inline-flex flex-wrap items-center justify-center gap-2">
            <OcrUploadButton
              customerId={customerId}
              phase={ocr.phase}
              onFileChange={ocr.onFileChange}
              consented={consented}
              onNeedConsent={ocr.openConsent}
            />
            <button
              type="button"
              onClick={() => setManualOpen(true)}
              className="rounded-xl border border-line bg-surface px-4 py-2 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition"
            >
              직접 입력
            </button>
          </div>
        </div>
      )}

      {/* 히트맵 그리드 */}
      {!loading && !error && heatmap && heatmap.insurance_count > 0 && (
        <div className="mt-5">
          <HeatmapGrid
            heatmap={heatmap}
            graded={graded}
            onGradedChange={onGradedChange}
            filter={filter}
            onFilterChange={onFilterChange}
          />
        </div>
      )}
    </div>
  );
}

// ── 갈아타기 탭 ── compareCustomer 실연결. 정직성 레드라인 전면 적용 ──────────
function SwitchTab({ customerId }: { customerId: number }) {
  const [data, setData] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishTooltip, setPublishTooltip] = useState(false);
  const [upgradeInfo, setUpgradeInfo] = useState<UpgradeModalInfo | undefined>(undefined);
  const [upgradeOpen, setUpgradeOpen] = useState(false);

  const doCompare = useCallback(() => {
    setLoading(true);
    setError(null);
    setUpgradeInfo(undefined);
    setUpgradeOpen(false);
    compareCustomer(customerId)
      .then((d) => setData(d))
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 402) {
          setUpgradeInfo(e.creditBody ?? { kind: "ai_compare" });
          setUpgradeOpen(true);
        } else {
          setError(e instanceof Error ? e.message : "비교 데이터를 불러오지 못했어요.");
        }
      })
      .finally(() => setLoading(false));
  }, [customerId]);

  useEffect(() => {
    doCompare();
  }, [doCompare]);

  // 발행 버튼 — publishable=false 이므로 항상 disabled
  async function handlePublish() {
    if (!data || data.publishable !== false) return;
    setPublishing(false); // 절대 실행 안 됨 — 타입 명시 목적
    void publishing; // lint 억제
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 rounded-xl bg-line animate-pulse" />
        ))}
      </div>
    );
  }

  if (upgradeInfo !== undefined) {
    return (
      <>
        <div className="rounded-xl border border-line bg-surface2 px-4 py-8 text-center">
          <p className="text-[14px] text-ink3">이번 달 AI 비교안내서 한도를 모두 사용했어요.</p>
          <button
            onClick={() => setUpgradeOpen(true)}
            className="mt-3 text-[13px] font-semibold text-brand"
          >
            안내 다시 보기
          </button>
        </div>
        <UpgradeModal
          open={upgradeOpen}
          onClose={() => setUpgradeOpen(false)}
          info={upgradeInfo}
        />
      </>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-xl border border-line bg-surface2 px-4 py-8 text-center">
        <p className="text-[14px] text-ink3">{error ?? "데이터 없음"}</p>
        <button
          onClick={doCompare}
          className="mt-3 text-[13px] font-semibold text-brand"
        >
          다시 시도
        </button>
      </div>
    );
  }

  // 보험료 포맷
  function fmtPrem(v: number | null) {
    if (v === null) return "-";
    return new Intl.NumberFormat("ko-KR").format(v) + "원";
  }
  function fmtDelta(d: number | null) {
    if (d === null) return "-";
    const sign = d > 0 ? "+" : "";
    return sign + new Intl.NumberFormat("ko-KR").format(d);
  }

  return (
    <div>
      {/* AI 초안 면책 — 항상 노출, 접기 불가 */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 mb-4">
        <p className="text-[12px] leading-5 text-amber-800">
          {data.disclaimer}
        </p>
      </div>

      {/* ── 갈아타기 판정 (★ 설계사 내부 의사결정 근거 — 고객에게 노출되지 않음) ── */}
      {data.verdict && (() => {
        const v = data.verdict;
        const map = {
          KEEP: { label: "유지가 유리 (추정)", cls: "bg-emerald-50 border-emerald-200 text-emerald-900", dot: "🟢" },
          SWITCH: { label: "전환 검토", cls: "bg-blue-50 border-blue-200 text-blue-900", dot: "🔵" },
          NEUTRAL: { label: "중립(상황 판단)", cls: "bg-surface2 border-line text-ink2", dot: "⚪" },
        } as const;
        const m = map[v.decision] ?? map.NEUTRAL;
        const net = v.customer_net_benefit_estimate;
        return (
          <div className={`rounded-xl border px-4 py-3.5 mb-4 ${m.cls}`}>
            <div className="flex items-center gap-2">
              <span className="text-[14px] font-extrabold">{m.dot} {m.label}</span>
              <span className="ml-auto text-[10px] font-semibold rounded-full bg-white/60 px-2 py-0.5">
                설계사 검토용 · 비공개
              </span>
            </div>
            <p className="mt-1.5 text-[13px] leading-5">{v.reason}</p>
            {net !== null && (
              <p className="mt-1 text-[12px] tnum font-semibold">
                1년 기준 추정 순손익: {net >= 0 ? "+" : ""}
                {new Intl.NumberFormat("ko-KR").format(net)}원
              </p>
            )}
            {data.switch_warnings && data.switch_warnings.length > 0 && (
              <ul className="mt-2.5 space-y-1 border-t border-black/10 pt-2">
                {data.switch_warnings.map((w, i) => (
                  <li key={i} className="text-[12px] leading-5 flex gap-1.5">
                    <span>⚠️</span>
                    <span>
                      <b className="font-semibold">{w.label}</b>
                      {w.amount !== null && (
                        <> · {new Intl.NumberFormat("ko-KR").format(w.amount)}원</>
                      )}
                      <span className="opacity-80">: {w.detail}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-[10.5px] leading-4 opacity-70">{v.disclaimer}</p>
          </div>
        );
      })()}

      {/* 보험료 요약 */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="rounded-xl border border-line bg-surface2 px-4 py-3">
          <div className="text-[11px] font-semibold text-ink3">현재 월 보험료</div>
          <div className="mt-1 text-[16px] font-bold text-ink tnum">
            {fmtPrem(data.current.monthly_premiums)}
          </div>
          <div className="mt-0.5 text-[11px] text-ink3 tnum">
            총납 {fmtPrem(data.current.total_premiums)}
          </div>
        </div>
        <div className="rounded-xl border border-line bg-surface2 px-4 py-3">
          <div className="text-[11px] font-semibold text-ink3">제안 월 보험료</div>
          <div className="mt-1 text-[16px] font-bold text-ink tnum">
            {fmtPrem(data.proposed.monthly_premiums)}
          </div>
          <div className="mt-0.5 text-[11px] text-ink3 tnum">
            총납 {fmtPrem(data.proposed.total_premiums)}
          </div>
        </div>
      </div>

      {/* 기존 vs 제안 보장 그룹 막대(006) — 담보별 2줄(기존·제안). 정확 수치 같이 표시 + 아래 비교표 */}
      {data.rows.length >= 2 && (
        <div className="rounded-xl border border-line bg-surface px-4 py-3.5 mb-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[13px] font-bold text-ink">보장 비교 (기존 vs 제안)</span>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="inline-flex items-center gap-1 text-ink2">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--existing)" }} />기존
              </span>
              <span className="inline-flex items-center gap-1 text-ink2">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--proposal)" }} />제안
              </span>
            </div>
          </div>
          <CompareBarChart
            items={data.rows.map((r) => ({
              label: r.coverage,
              current: r.current_amount ?? 0,
              proposed: r.proposed_amount ?? 0,
            }))}
            format={fmtAmount}
          />
          <p className="mt-2 text-[11px] text-ink3">담보별 기존·제안 보장금액 비교예요. 정확한 수치는 아래 비교표에서 확인하세요.</p>
        </div>
      )}

      {/* 담보 비교표 */}
      {data.rows.length > 0 ? (
        <div className="rounded-xl border border-line overflow-hidden">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-surface2 border-b border-line">
                <th className="px-3 py-2.5 text-left font-semibold text-ink2">담보</th>
                <th className="px-3 py-2.5 text-right font-semibold text-ink2">현재</th>
                <th className="px-3 py-2.5 text-right font-semibold text-ink2">제안</th>
                <th className="px-3 py-2.5 text-right font-semibold text-ink2">증감</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, i) => (
                <tr key={i} className="border-b border-line last:border-0">
                  <td className="px-3 py-2.5 text-ink font-medium">{row.coverage}</td>
                  <td className="px-3 py-2.5 text-right text-ink3 tnum">
                    {row.current_amount !== null
                      ? new Intl.NumberFormat("ko-KR").format(row.current_amount)
                      : "-"}
                  </td>
                  <td className="px-3 py-2.5 text-right text-ink3 tnum">
                    {row.proposed_amount !== null
                      ? new Intl.NumberFormat("ko-KR").format(row.proposed_amount)
                      : "-"}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right tnum font-semibold ${
                      row.delta === null
                        ? "text-ink3"
                        : row.delta > 0
                        ? "text-enough"
                        : row.delta < 0
                        ? "text-short"
                        : "text-ink3"
                    }`}
                  >
                    {fmtDelta(row.delta)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-line px-4 py-10 text-center">
          <p className="text-[14px] text-ink3">비교할 담보 데이터가 없어요.</p>
        </div>
      )}

      {/* AI 비교안내서 — guide_enabled=false 면 법무 게이트 안내만 */}
      <div className="mt-5">
        {data.guide_enabled ? (
          <div className="rounded-xl border border-line bg-surface2 px-4 py-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-[14px] font-bold text-ink">AI 비교안내서 초안</h4>
              <span className="text-[11px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5">
                AI 초안
              </span>
            </div>
            <pre className="text-[13px] text-ink2 leading-6 whitespace-pre-wrap font-sans">
              {data.guide_draft}
            </pre>
            <p className="mt-3 text-[11px] text-muted leading-5">
              AI가 정리한 참고 자료예요. 고객 안내 전 설계사님이 확인해 주세요.
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-amber-200 bg-amber-50 px-4 py-5 text-center">
            <p className="text-[13px] font-semibold text-amber-800">
              AI 비교안내서는 법무 검토 완료 후 활성화됩니다
            </p>
            <p className="mt-1.5 text-[12px] text-amber-700 leading-5">
              비교 분석 안내는 부당승환 관련 법적 요건이 확정되어야 제공돼요.
              가짜 데이터로 화면을 채우지 않습니다(정직성 레드라인).
            </p>
          </div>
        )}
      </div>

      {/* 발행 버튼 — publishable=false 이므로 항상 disabled + 차단 사유 tooltip */}
      <div className="mt-4 relative">
        <div
          className="inline-block w-full"
          onMouseEnter={() => setPublishTooltip(true)}
          onMouseLeave={() => setPublishTooltip(false)}
          onFocus={() => setPublishTooltip(true)}
          onBlur={() => setPublishTooltip(false)}
        >
          <button
            disabled
            aria-disabled="true"
            onClick={handlePublish}
            className="w-full rounded-2xl bg-surface2 border border-line text-[14px] font-bold text-ink3 py-3.5 cursor-not-allowed opacity-60"
          >
            비교안내서 발행
          </button>
        </div>
        {publishTooltip && data.publish_blocked_reason && (
          <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-72 rounded-xl bg-ink/90 px-3 py-2 text-[12px] text-white leading-5 text-center z-10 pointer-events-none">
            {data.publish_blocked_reason}
          </div>
        )}
        <p className="mt-2 text-[11px] text-center text-muted">
          발행 기능은 법무·백엔드 게이트 통과 전까지 비활성입니다.
        </p>
      </div>
    </div>
  );
}

// ── 공백 탭 ── 보유 0(미보유) 담보 모음. 부족/충분 단정은 graded 일 때만 ─────
function GapTab({
  heatmap,
  loading,
  error,
  onRetry,
  isExclusive = false,
}: {
  heatmap: HeatmapResponse | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  isExclusive?: boolean;
}) {
  if (loading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-12 rounded-xl bg-line animate-pulse" />
        ))}
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-xl border border-line bg-surface2 px-4 py-8 text-center">
        <p className="text-[14px] text-ink3">{error}</p>
        <button onClick={onRetry} className="mt-3 text-[13px] font-semibold text-brand">
          다시 시도
        </button>
      </div>
    );
  }
  if (!heatmap || heatmap.insurance_count === 0) {
    return (
      <div className="rounded-xl border border-dashed border-line px-4 py-12 text-center">
        <p className="text-[15px] font-semibold text-ink2">아직 분석할 증권이 없어요</p>
        <p className="mt-1 text-[13px] text-ink3">
          분석 탭에서 증권을 등록하면 보장 공백을 모아 볼 수 있어요.
        </p>
      </div>
    );
  }

  // 미보유(보유 0) 담보 수집 — held_amount === 0 또는 null
  const gaps: { category: string; sub: string; detail: HeatmapDetail }[] = [];
  for (const cat of heatmap.tree) {
    for (const sub of cat.sub_categories) {
      for (const d of sub.details) {
        if (d.held_amount === null || d.held_amount === 0) {
          gaps.push({ category: cat.name, sub: sub.name, detail: d });
        }
      }
    }
  }

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h3 className="text-[15px] font-bold text-ink">
          {isExclusive ? "🎯 보장 공백(채울 기회)" : "보장 공백"}{" "}
          <span className="text-ink3 tnum">{gaps.length}</span>
        </h3>
        <span className="text-[12px] text-ink3">보유 0 담보</span>
      </div>

      {/* graded 일 때만 '부족' 단정 가능, neutral 이면 '미보유' 사실만 */}
      <p className="mt-1.5 text-[12px] leading-5 text-ink3">
        {isExclusive
          ? "보유하지 않은 담보예요. 새로운 상품으로 채울 수 있는 보장 기회를 검토하세요."
          : heatmap.mode === "graded"
          ? "보유 금액이 0인 담보예요. 부족 여부 판정은 설정한 기준에 따른 결과입니다."
          : "보유 금액이 0인 담보(객관적 사실)만 모았어요. 기준을 정하면 부족 여부까지 한눈에 볼 수 있어요."}
      </p>

      {gaps.length === 0 ? (
        <div className="mt-5 rounded-xl border border-line bg-surface2 px-4 py-10 text-center text-[14px] text-ink3">
          미보유(보유 0) 담보가 없어요.
        </div>
      ) : (
        <div className="mt-4 space-y-2">
          {gaps.map(({ category, sub, detail }) => (
            <div
              key={detail.detail_id}
              className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3"
            >
              <span className="w-2 h-2 rounded-full bg-cnone shrink-0" aria-hidden />
              <div className="flex-1 min-w-0">
                <div className="text-[14px] font-semibold text-ink">
                  {detail.name}
                </div>
                <div className="text-[11px] text-ink3">
                  {category} · {sub}
                </div>
              </div>
              {/* 부족 배지: graded + shortage 일 때만 */}
              {heatmap.mode === "graded" && detail.status === "shortage" ? (
                <span className="shrink-0 inline-flex items-center rounded-full bg-amber-50 border-l-4 border-l-short border border-amber-200 px-2 py-0.5 text-[11px] font-semibold text-ink">
                  부족
                </span>
              ) : (
                <span className="shrink-0 text-[12px] text-ink3 tnum">
                  {fmtAmount(detail.held_amount)}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── 이력 탭 ── getCustomerHistory 실연결. 타입별 아이콘·시각 표시 ─────────────
function HistoryTab({ customerId }: { customerId: number }) {
  const [events, setEvents] = useState<HistoryEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getCustomerHistory(customerId)
      .then((d) => setEvents(d.events ?? []))
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "이력을 불러오지 못했어요.");
      })
      .finally(() => setLoading(false));
  }, [customerId]);

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 rounded-xl bg-line animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-line bg-surface2 px-4 py-8 text-center">
        <p className="text-[14px] text-ink3">{error}</p>
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            getCustomerHistory(customerId)
              .then((d) => setEvents(d.events ?? []))
              .catch((e: unknown) => setError(e instanceof Error ? e.message : "오류"))
              .finally(() => setLoading(false));
          }}
          className="mt-3 text-[13px] font-semibold text-brand"
        >
          다시 시도
        </button>
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-line px-4 py-12 text-center">
        <p className="text-[15px] font-semibold text-ink2">접점 이력이 없어요</p>
        <p className="mt-1 text-[13px] text-ink3">
          공유 열람·상담·메시지 등 이력이 생기면 이곳에 표시됩니다.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h3 className="text-[15px] font-bold text-ink mb-4">
        접점 이력{" "}
        <span className="text-ink3 font-normal tnum">{events.length}건</span>
      </h3>
      <ol className="relative border-l-2 border-line ml-2 space-y-0">
        {events.map((ev, i) => (
          <li key={i} className="pl-6 pb-5 relative">
            {/* 타임라인 도트 (이벤트 타입별 색) */}
            <span
              className={`absolute -left-[9px] top-1 w-4 h-4 rounded-full border-2 border-surface ${historyDotColor(ev.type)}`}
              aria-hidden
            />
            <div className="flex items-start gap-2">
              <span className="text-[16px] shrink-0" aria-hidden>
                {historyIcon(ev.type)}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="text-[14px] font-semibold text-ink">{ev.label}</span>
                  <span className="text-[11px] text-ink3 tnum shrink-0">
                    {fmtEventAt(ev.at)}
                  </span>
                </div>
                {historyDetail(ev.type, ev.meta) && (
                  <p className="mt-0.5 text-[12px] text-ink3 leading-5 truncate">
                    {historyDetail(ev.type, ev.meta)}
                  </p>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** 이력 부가설명 — 내부필드(scope·*_id·portfolio_type 등)는 노출 금지, 사람이 읽는 값만. */
function historyDetail(type: string, meta: Record<string, unknown>): string | null {
  if (!meta) return null;
  if (type === "insurance_registered") {
    const name = typeof meta.name === "string" ? meta.name.trim() : "";
    return name || null; // 보험 상품명만(내부 id·종류 비노출)
  }
  if (type === "consent_agreed") {
    const v = typeof meta.doc_version === "string" ? meta.doc_version.trim() : "";
    return v ? `동의서 ${v}` : null;
  }
  return null; // 그 외(철회·공유·복사 등)는 label로 충분
}

/** 이벤트 타입 → 아이콘 문자 */
function historyIcon(type: string): string {
  switch (type) {
    case "share_view":     return "👁";
    case "ocr_upload":     return "📄";
    case "analysis":       return "📊";
    case "compare":        return "⚖️";
    case "message":        return "💬";
    case "consult":        return "🤝";
    case "created":        return "✅";
    default:               return "•";
  }
}

/** 이벤트 타입 → 타임라인 도트 Tailwind 색 */
function historyDotColor(type: string): string {
  switch (type) {
    case "share_view":  return "bg-indigo-400";
    case "ocr_upload":  return "bg-brand";
    case "analysis":    return "bg-enough";
    case "compare":     return "bg-amber-400";
    case "message":     return "bg-sky-400";
    case "consult":     return "bg-green-500";
    default:            return "bg-line";
  }
}

/** ISO → 읽기 쉬운 날짜·시각 */
function fmtEventAt(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ko-KR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

// ── 공통 NotFound 셸 ──────────────────────────────────────────────────────
function NotFoundShell({ message }: { message: string }) {
  return (
    <div className="min-h-dvh">
      <AppNav active="customers" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <div className="mt-10 rounded-2xl border border-line bg-surface2 px-4 py-12 text-center">
          <p className="text-[15px] font-semibold text-ink2">{message}</p>
          <Link
            href="/customers"
            className="mt-3 inline-block text-[13px] font-semibold text-brand"
          >
            고객 목록으로 →
          </Link>
        </div>
      </main>
    </div>
  );
}
