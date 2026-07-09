"use client";

// ════════════════════════════════════════════════════════════════════════════
// 고객 1명 중심 상세 셸 — ★ 한 동선 IA 복원 (docs/dev/12 §12 고객상세·탭 IA)
//
// 발굴 → 보장분석 → 비교(나란히 정리)를 한 고객 화면에서 탭으로 연결한다.
// 탭: 분석(히트맵 + 증권 OCR 입구) / 비교 분석(중립 시각화, §97 컴플라이언스 게이트) / 정보 / 계약 / 이력.
//
// 정직성 레드라인:
//  - 분석 판정은 BE 권위(neutral/graded). neutral 이면 부족/충분 단정 금지.
//  - 비교 분석은 판정(KEEP/SWITCH)을 산출하지 않는다(2026-07-09 재정의) — §97 법무 게이트로
//    AI 안내서(guide_draft)만 별도 통제, 가짜 데이터 금지·게이트 사유 명시.
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
import { ContactLogModal } from "@/components/contact-log-modal";
import { InsuranceManualModal } from "@/components/insurance-manual-modal";
import { BaselineRequiredModal } from "@/components/baseline-required-modal";
import { PremiumSplitSection, ComparePremiumSplit } from "@/components/premium-split";
import { UpgradeModal, type UpgradeModalInfo } from "@/components/upgrade-modal";
import { ShareLinkButton } from "@/components/share-link-button";
import { ShareSnapshotButton } from "@/components/share-snapshot-panel";
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
  searchJobs,
  listManualInsurances,
  listContactLogs,
  SALES_STAGES,
  CUSTOMER_STATUSES,
  ApiError,
  type ContactLog,
  type ManualInsuranceItem,
  type CustomerDetail,
  type SalesStage,
  type CustomerStatus,
  type JobMatch,
  type HeatmapResponse,
  type CompareResponse,
  type HistoryEvent,
  type ProfileResponse,
  type ContractChecklistItem,
} from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { buildCompareExportText, compareDiffText } from "@/lib/compare-export";

type TabKey = "analysis" | "switch" | "info" | "contract" | "history";

const TABS: { key: TabKey; label: string }[] = [
  { key: "analysis", label: "분석" },
  { key: "switch", label: "비교 분석" },
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
// 최종 연락일(없으면 등록일) → "YY.MM.DD" + "D+경과일"
function lastContactDDay(lastContacted: string | null, createdAt: string): { date: string; dday: string } {
  const ref = lastContacted ?? createdAt;
  const d = new Date(ref);
  const days = Math.max(0, Math.floor((Date.now() - d.getTime()) / 86_400_000));
  const yy = String(d.getFullYear()).slice(2);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return { date: `${yy}.${mm}.${dd}`, dday: `D+${days}` };
}
// 직업급수 칩 색 — 1급(저위험)=초록 … 3급(고위험)=빨강, 기타=회색
function gradeChip(grade: number): string {
  if (grade === 1) return "bg-emerald-100 text-emerald-700";
  if (grade === 2) return "bg-amber-100 text-amber-700";
  if (grade === 3) return "bg-rose-100 text-rose-700";
  return "bg-surface2 text-ink3";
}
// 보험나이 = 만 나이 + (직전 생일로부터 6개월 이상이면 +1). BE compute_insurance_age와 동일 규칙(실시간 미리보기).
function computeInsuranceAge(birthStr: string): number | null {
  const [y, m, d] = (birthStr || "").split("-").map(Number);
  if (!y || !m || !d) return null;
  const bd = new Date(y, m - 1, d);
  const now = new Date();
  let years = now.getFullYear() - bd.getFullYear();
  let months = now.getMonth() - bd.getMonth();
  if (now.getDate() < bd.getDate()) months -= 1;
  if (months < 0) { years -= 1; months += 12; }
  if (years < 0) return null;
  return years + (months >= 6 ? 1 : 0);
}
const BIRTH_YEARS = Array.from({ length: 100 }, (_, i) => new Date().getFullYear() - i);
const BIRTH_MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);
const BIRTH_DAYS = Array.from({ length: 31 }, (_, i) => i + 1);
const pad2 = (n: number) => String(n).padStart(2, "0");

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
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
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

  // 위촉 형태 — 전속(1)이면 비교 분석(다사 갈아타기 전제) 탭 숨김 + 공백 탭을 자사 업셀로 분기.
  // ★ 2026-07-09 재정의 노트: 비교가 중립 시각화(제안 vs 제안 등)로 넓어지면서 전속 설계사도
  //   쓸모가 있을 수 있음 — 이번 라운드는 리스크 최소화를 위해 기존 숨김 동작 그대로 유지(PM 확인 후 재검토).
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  useEffect(() => {
    getProfile().then(setProfile).catch(() => setProfile(null));
  }, []);
  const isExclusive = profile?.affiliation_type === 1;
  // 정보 탭은 탭바에서 빼고(요약카드 '세부정보' 링크로 접근), 기본 화면=정보 — PM 06.29.
  const visibleTabs = TABS.filter(
    (t) => t.key !== "info" && !(isExclusive && t.key === "switch")
  );

  // 탭 상태 (URL ?tab= 동기화). 기본=정보. 전속이 switch 진입 시 분석으로 폴백.
  const tabParam = searchParams.get("tab") as TabKey | null;
  let activeTab: TabKey =
    tabParam && TABS.some((t) => t.key === tabParam) ? tabParam : "info";
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
    if (activeTab === "analysis") {
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

      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
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
          customer && (
            <CustomerSummary
              customer={customer}
              onChangeStage={changeStage}
              onChangeStatus={changeStatus}
              onTab={setTab}
            />
          )
        )}

        {/* ── 탭 바 ── */}
        {!custError && (
          <>
            <div
              role="tablist"
              aria-label="고객 상세 탭"
              className="mt-5 flex flex-wrap gap-1 border-b border-line"
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
function CustomerSummary({
  customer,
  onChangeStage,
  onChangeStatus,
  onTab,
}: {
  customer: CustomerDetail;
  onChangeStage: (s: SalesStage) => void;
  onChangeStatus: (s: CustomerStatus) => void;
  onTab: (tab: TabKey) => void;
}) {
  const [bookingOpen, setBookingOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [contactLogs, setContactLogs] = useState<ContactLog[]>([]);
  const loadContacts = useCallback(() => {
    listContactLogs(customer.id).then((r) => setContactLogs(r.results)).catch(() => {});
  }, [customer.id]);
  useEffect(() => { loadContacts(); }, [loadContacts]);
  const age =
    customer.insurance_age != null ? `${customer.insurance_age}세` : calcAge(customer.birth_day);
  const sub = [age, genderLabel(customer.gender)]
    .filter(Boolean)
    .join(" · ");
  const dday = lastContactDDay(customer.last_contacted_at, customer.created_at);
  // 세그먼트 토글 — 흰 카드(bg-surface) 위라 트랙은 옅은 회색(bg-surface2), 선택은 흰색+그림자로 또렷하게.
  const seg = "inline-flex rounded-xl bg-surface2 p-0.5 text-[12px] font-semibold";
  const segBtn = (active: boolean) =>
    `px-3 py-1.5 rounded-[10px] transition ${active ? "bg-surface text-brand shadow-sm" : "text-ink3 hover:text-ink2"}`;
  // 단계별 '다음 행동' 버튼 — 주(brand) / 보조(ghost)
  const actPrimary = "rounded-lg bg-brand text-white text-[12px] font-bold px-3 py-1.5 hover:opacity-90 transition";
  const actGhost = "rounded-lg border border-line bg-surface2 text-ink2 text-[12px] font-semibold px-3 py-1.5 hover:bg-surface transition";
  return (
    <>
    <Card className="mt-3 p-4">
      {/* 한 줄: 왼쪽 신원 · 가운데 영업단계+상태 · 오른쪽 최종연락 — PM 06.29 */}
      <div className="flex items-center gap-3 flex-wrap">
        <CustomerAvatar label={customer.avatar_label} color={customer.color} size={48} />
        {/* 왼쪽: 신원 */}
        <div className="min-w-0">
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
        {/* 가운데: 영업 단계 + 상태 */}
        <div className="flex-1 min-w-[240px] flex flex-wrap items-end justify-center gap-x-4 gap-y-2">
          <div>
            <div className="text-[11px] font-semibold text-ink3 mb-1">영업 단계</div>
            <div className={seg}>
              {SALES_STAGES.map((s) => (
                <button key={s.key} onClick={() => onChangeStage(s.key)}
                  aria-pressed={customer.sales_stage === s.key} className={segBtn(customer.sales_stage === s.key)}>
                  {s.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="text-[11px] font-semibold text-ink3 mb-1">상태</div>
            <div className={seg}>
              {CUSTOMER_STATUSES.map((s) => (
                <button key={s.key} onClick={() => onChangeStatus(s.key)}
                  aria-pressed={customer.status === s.key} className={segBtn(customer.status === s.key)}>
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        {/* 오른쪽: 최종연락 */}
        <div className="shrink-0 text-right">
          <div className="text-[11px] text-ink3">최종 연락</div>
          <div className="text-[13px] font-semibold text-ink tnum whitespace-nowrap">
            {dday.date} <span className="text-brand">{dday.dday}</span>
          </div>
          <Link
            href={`/customer/${customer.id}?tab=info`}
            className="mt-1 inline-block text-[12px] font-semibold text-brand"
          >
            세부정보 →
          </Link>
        </div>
      </div>

      {/* ── 단계별 '다음 행동' — 이 단계에서 바로 할 일(퍼널 척추) ── */}
      <div className="mt-3 pt-3 border-t border-line flex items-center gap-2 flex-wrap">
        <span className="text-[11px] font-semibold text-ink3 mr-0.5">다음 할 일</span>
        {customer.sales_stage === "db" && (
          <>
            {customer.mobile_phone_number ? (
              <>
                <a href={`tel:${customer.mobile_phone_number}`} className={actPrimary}>전화</a>
                <a href={`sms:${customer.mobile_phone_number}`} className={actGhost}>문자</a>
              </>
            ) : (
              <Link href={`/customer/${customer.id}?tab=info`} className={actGhost}>연락처 입력</Link>
            )}
            <Link href={`/scripts?customer=${encodeURIComponent(customer.name)}`} className={actGhost}>화법</Link>
          </>
        )}
        {customer.sales_stage === "contact" && (
          <button onClick={() => setBookingOpen(true)} className={actPrimary}>예약 링크 보내기</button>
        )}
        {customer.sales_stage === "meeting" && (
          <>
            <button onClick={() => onTab("analysis")} className={actPrimary}>분석 시작</button>
            <Link href={`/scripts?customer=${encodeURIComponent(customer.name)}`} className={actGhost}>화법</Link>
          </>
        )}
        {customer.sales_stage === "contract" && (
          <button onClick={() => onTab("contract")} className={actPrimary}>청약 체크리스트</button>
        )}
        <button onClick={() => setContactOpen(true)} className={actGhost}>연락 기록</button>
      </div>

      {/* 최근 연락(접촉 결과) — 최근 2건 압축 표시 */}
      {contactLogs.length > 0 && (
        <div className="mt-2 flex items-center gap-x-3 gap-y-1 flex-wrap text-[11px] text-ink3">
          <span className="font-semibold text-ink2">최근 연락</span>
          {contactLogs.slice(0, 2).map((c) => (
            <span key={c.id} className="inline-flex items-center gap-1">
              <span className="rounded-full bg-surface2 border border-line px-1.5 py-0.5 font-semibold text-ink2">{c.result_display}</span>
              <span className="tnum">{new Date(c.created_at).toLocaleDateString("ko-KR", { month: "2-digit", day: "2-digit" })}</span>
              {c.memo ? <span className="truncate max-w-[160px]">· {c.memo}</span> : null}
            </span>
          ))}
        </div>
      )}
    </Card>
    {bookingOpen && (
      <BookingModal customerId={customer.id} onClose={() => setBookingOpen(false)} />
    )}
    {contactOpen && (
      <ContactLogModal customerId={customer.id} onClose={() => setContactOpen(false)} onSaved={loadContacts} />
    )}
    </>
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
  // 생년월일 — 년·월·일 드롭다운(달력 대신). birth 는 셋이 다 차면 "YYYY-MM-DD".
  const _b = (customer.birth_day ?? "").split("-");
  const [by, setBy] = useState(_b[0] ?? "");
  const [bm, setBm] = useState(_b[1] ?? "");
  const [bd, setBd] = useState(_b[2] ?? "");
  const birth = by && bm && bd ? `${by}-${bm.padStart(2, "0")}-${bd.padStart(2, "0")}` : "";
  const [color, setColor] = useState(customer.color ?? "");
  const [avatarLabel, setAvatarLabel] = useState(customer.avatar_label ?? "");
  const [memo, setMemo] = useState(customer.memo ?? "");
  // 직업 변경(검색해서 고르면 급수 자동). pickedJob !== null 이면 저장 시 job_code 전송.
  const [pickedJob, setPickedJob] = useState<JobMatch | null>(null);
  const [jobQuery, setJobQuery] = useState("");
  const [jobResults, setJobResults] = useState<JobMatch[]>([]);
  const [jobOpen, setJobOpen] = useState(false);
  const [savingInfo, setSavingInfo] = useState(false);
  const [savingMemo, setSavingMemo] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // 저장 성공 안내는 폼을 다시 수정하면 사라진다(직업·생년월일 포함 모든 편집 필드).
  useEffect(() => { setMsg(null); }, [name, phone, gender, by, bm, bd, color, avatarLabel, memo, pickedJob]);

  // 직업 검색 — 250ms 디바운스
  useEffect(() => {
    const q = jobQuery.trim();
    if (!q) { setJobResults([]); setJobOpen(false); return; }
    let alive = true;
    const t = setTimeout(() => {
      searchJobs(q).then((rows) => { if (alive) { setJobResults(rows); setJobOpen(true); } }).catch(() => {});
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [jobQuery]);

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
        job_code: pickedJob ? String(pickedJob.id) : undefined,
      });
      onUpdated(c);
      setPickedJob(null);
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
            <div className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">생년월일</span>
              {/* 년:월:일 = 2:1:1 너비 (년이 가장 넓게) — PM 06.29 */}
              <div className="flex gap-1.5">
                <select value={by} onChange={(e) => setBy(e.target.value)} className={`${inputCls} flex-[2] min-w-0`}>
                  <option value="">년</option>
                  {BIRTH_YEARS.map((y) => <option key={y} value={String(y)}>{y}년</option>)}
                </select>
                <select value={bm} onChange={(e) => setBm(e.target.value)} className={`${inputCls} flex-1 min-w-0`}>
                  <option value="">월</option>
                  {BIRTH_MONTHS.map((m) => <option key={m} value={pad2(m)}>{m}월</option>)}
                </select>
                <select value={bd} onChange={(e) => setBd(e.target.value)} className={`${inputCls} flex-1 min-w-0`}>
                  <option value="">일</option>
                  {BIRTH_DAYS.map((d) => <option key={d} value={pad2(d)}>{d}일</option>)}
                </select>
              </div>
            </div>
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

          {/* 직업 — 검색해서 변경(고르면 직업급수 자동) */}
          <div className="mt-3 relative">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px] font-semibold text-ink3">직업 (고르면 직업급수 자동)</span>
              {!pickedJob && (
                <span className="text-[12px] text-ink3">현재: <b className="text-ink2">{customer.job_name ?? "미지정"}</b>{riskLabel ? ` (${riskLabel})` : ""}</span>
              )}
            </div>
            {pickedJob ? (
              <div className="mt-1 flex items-center justify-between gap-2 rounded-xl border border-line bg-accent-tint px-3.5 py-2.5">
                <div className="text-[14px] font-semibold text-ink truncate">{pickedJob.name}</div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className={`rounded-full text-[12px] font-bold px-2 py-0.5 ${gradeChip(pickedJob.risk_grade)}`}>{pickedJob.risk_grade_label}</span>
                  <button type="button" onClick={() => setPickedJob(null)} className="text-[12px] text-ink3 hover:text-ink underline">취소</button>
                </div>
              </div>
            ) : (
              <>
                <input
                  value={jobQuery}
                  onChange={(e) => setJobQuery(e.target.value)}
                  onFocus={() => { if (jobResults.length) setJobOpen(true); }}
                  onBlur={() => setTimeout(() => setJobOpen(false), 120)}
                  placeholder="직업명·키워드로 검색 (예: 의사, 용접, 시의원)"
                  className={`${inputCls} mt-1`}
                />
                {jobOpen && jobQuery.trim() && (
                  <div className="absolute z-10 mt-1 w-full max-h-56 overflow-y-auto rounded-xl border border-line bg-surface shadow-lg">
                    {jobResults.length > 0 ? jobResults.map((j) => (
                      <button key={j.id} type="button" onClick={() => { setPickedJob(j); setJobQuery(""); setJobOpen(false); }}
                        className="flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left hover:bg-surface2 border-b border-line last:border-b-0">
                        <span className="min-w-0">
                          <span className="block text-[14px] text-ink truncate">{j.name}</span>
                          {j.description_short && <span className="block text-[11px] text-ink3 truncate">{j.description_short}</span>}
                        </span>
                        <span className={`shrink-0 rounded-full text-[12px] font-bold px-2 py-0.5 ${gradeChip(j.risk_grade)}`}>{j.risk_grade_label}</span>
                      </button>
                    )) : <div className="px-3.5 py-2.5 text-[13px] text-ink3">검색 결과가 없어요.</div>}
                  </div>
                )}
              </>
            )}
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
            <dt className="text-ink3">보험나이 <span className="text-[10px] text-muted">(생년월일 자동)</span></dt>
            <dd className="text-ink2 text-right">{(() => { const a = computeInsuranceAge(birth) ?? customer.insurance_age; return a != null ? `${a}세` : "-"; })()}</dd>
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
            {piState?.status === "agreed" ? (
              <div className="mt-2.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-center text-[13px] font-bold text-emerald-700">
                ✓ 동의 완료
              </div>
            ) : (
              <>
                <button
                  onClick={sendConsentLink}
                  disabled={consentBusy}
                  className="mt-2.5 w-full rounded-xl border border-brand text-brand text-[13px] font-semibold py-2 disabled:opacity-60"
                >
                  {consentBusy ? "링크 생성 중…" : "동의 요청 링크 복사(고객 본인용)"}
                </button>
                <p className="mt-1.5 text-[11px] text-ink3 leading-4">
                  링크를 복사해 고객에게 전달하면, 고객 본인이 직접 동의해요. 가장 안전한 방법입니다.
                </p>
              </>
            )}
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
        <p className="mt-1 text-[12px] text-ink3">명함·방명록 사진을 올려두면 보관돼요. 명함 정보는 위 칸에 직접 입력해 주세요.</p>
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

// ── 보험별 카드 (보유=portfolio 1 / 제안=portfolio 2) — 한 고객의 여러 보험을 카드로 — PM 06.29 ──
function InsuranceCard({ it }: { it: ManualInsuranceItem }) {
  const typeLabel = it.insurance_type === 1 ? "생명" : "손해";
  const insured = it.insured_name ?? (it.is_same_insured ? "계약자와 동일" : "-");
  return (
    <div className="rounded-xl border border-line bg-surface p-3.5">
      <div className="flex items-start justify-between gap-2">
        <div className="text-[14px] font-bold text-ink truncate">{it.name ?? "이름 없는 보험"}</div>
        <span className="shrink-0 text-[10px] font-semibold rounded-full px-2 py-0.5 bg-surface2 text-ink3 border border-line">{typeLabel}</span>
      </div>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
        <dt className="text-ink3">계약자</dt><dd className="text-ink2 text-right truncate">{it.contractor_name ?? "-"}</dd>
        <dt className="text-ink3">피보험자</dt><dd className="text-ink2 text-right truncate">{insured}</dd>
        <dt className="text-ink3">월 보험료</dt><dd className="text-ink2 text-right tnum">{fmtWon(it.monthly_premiums)}</dd>
        <dt className="text-ink3">기간</dt><dd className="text-ink2 text-right">{it.contract_date ?? "-"} ~ {it.expiry_date ?? "-"}</dd>
      </dl>
      {(it.monthly_renewal_premium != null || it.monthly_non_renewal_premium != null) && (
        <div className="mt-1 flex gap-3 text-[12px] text-ink3">
          {it.monthly_renewal_premium != null && <span>갱신 {fmtWon(it.monthly_renewal_premium)}</span>}
          {it.monthly_non_renewal_premium != null && <span>비갱신 {fmtWon(it.monthly_non_renewal_premium)}</span>}
        </div>
      )}
    </div>
  );
}

function InsuranceCards({ customerId, portfolioType, refreshKey, emptyHint, title }: {
  customerId: number; portfolioType: number; refreshKey?: number; emptyHint?: string; title?: string;
}) {
  const [items, setItems] = useState<ManualInsuranceItem[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    setLoading(true);
    listManualInsurances(customerId)
      .then((r) => setItems(r.results.filter((x) => x.portfolio_type === portfolioType)))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [customerId, portfolioType, refreshKey]);
  if (loading) return <div className="grid sm:grid-cols-2 gap-3">{[1, 2].map((i) => <div key={i} className="h-24 rounded-xl bg-line animate-pulse" />)}</div>;
  if (items.length === 0)
    return emptyHint ? <div className="rounded-xl border border-dashed border-line px-4 py-5 text-center text-[13px] text-ink3">{emptyHint}</div> : null;
  return (
    <div>
      {title && <div className="text-[13px] font-bold text-ink mb-2">{title} <span className="text-ink3 tnum">{items.length}</span></div>}
      <div className="grid sm:grid-cols-2 gap-3">
        {items.map((it) => <InsuranceCard key={it.id} it={it} />)}
      </div>
    </div>
  );
}

// ── 자유 A/B 배정 행 (비교 분석 — 보험 아무거나 A안·B안·미포함 중 하나로) ── 2026-07-09 ──
// ★ 미포함은 '키 삭제'가 아니라 명시적 "none"으로 저장한다: 삭제하면 목록 새로고침(제안 추가 등) 때
//   '미배정'과 구분이 안 돼 portfolio_type 프리셋으로 되살아나, 설계사가 뺀 보험이 고객 텍스트에
//   다시 섞이는 버그가 있었다(리뷰 major). "none"으로 남기면 새로고침이 그 배정을 보존한다.
type SideAssign = "A" | "B" | "none";
function assignInsurance(
  setter: (updater: (prev: Record<number, SideAssign>) => Record<number, SideAssign>) => void,
  id: number,
  value: SideAssign
) {
  setter((prev) => ({ ...prev, [id]: value }));
}
function AssignInsRow({ it, value, onChange }: { it: ManualInsuranceItem; value: SideAssign; onChange: (v: SideAssign) => void }) {
  const sub = [it.contractor_name && `계약 ${it.contractor_name}`, it.insured_name && `피보험 ${it.insured_name}`]
    .filter(Boolean).join(" · ") || (it.insurance_type === 1 ? "생명" : "손해");
  const portfolioTag = it.portfolio_type === 1 ? "보유" : "제안";
  return (
    <div className="flex items-center gap-2.5 rounded-xl border border-line bg-surface px-3 py-2">
      <span className="flex-1 min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="text-[13px] font-semibold text-ink truncate">{it.name ?? "이름 없는 보험"}</span>
          <span className="shrink-0 text-[10px] font-semibold rounded-full px-1.5 py-0.5 bg-surface2 text-ink3 border border-line">{portfolioTag}</span>
        </span>
        <span className="block text-[11px] text-ink3 truncate">{sub}</span>
      </span>
      <span className="shrink-0 text-[11px] text-ink2 tnum">{fmtWon(it.monthly_premiums)}</span>
      <div className="shrink-0 inline-flex rounded-lg border border-line overflow-hidden text-[11px] font-semibold">
        <button
          type="button"
          onClick={() => onChange("A")}
          aria-pressed={value === "A"}
          className={`px-2.5 py-1.5 transition ${value === "A" ? "bg-brand text-white" : "bg-surface text-ink2 hover:bg-surface2"}`}
        >
          A안
        </button>
        <button
          type="button"
          onClick={() => onChange("none")}
          aria-pressed={value === "none"}
          className={`px-2.5 py-1.5 border-x border-line transition ${value === "none" ? "bg-surface2 text-ink" : "bg-surface text-ink3 hover:bg-surface2"}`}
        >
          미포함
        </button>
        <button
          type="button"
          onClick={() => onChange("B")}
          aria-pressed={value === "B"}
          className={`px-2.5 py-1.5 transition ${value === "B" ? "bg-ink text-white" : "bg-surface text-ink2 hover:bg-surface2"}`}
        >
          B안
        </button>
      </div>
    </div>
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
  const [insRefresh, setInsRefresh] = useState(0);
  const [baselineModalDismissed, setBaselineModalDismissed] = useState(false);
  useEffect(() => { if (ocr.phase === "success") setInsRefresh((k) => k + 1); }, [ocr.phase]);
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
          <ShareSnapshotButton customerId={customerId} />
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
            setInsRefresh((k) => k + 1);
          }}
        />
      )}

      <OcrStatusBanner
        phase={ocr.phase}
        errorMsg={ocr.error}
        onDismiss={ocr.clearError}
        onManualEntry={() => setManualOpen(true)}
      />
      {ocr.phase === "consent_required" && (
        <ConsentModal
          onGenerate={() => ocr.generateConsentLink(customerId)}
          consentUrl={ocr.consentUrl}
          consentCopied={ocr.consentCopied}
          onCopy={ocr.copyConsentUrl}
          onDismiss={ocr.dismissConsent}
          loading={ocr.consentLoading}
          reason={ocr.consentReason}
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

      {/* 보유 보험 — 보험별 카드(여러 개일 수 있음) */}
      <div className="mt-4">
        <InsuranceCards customerId={customerId} portfolioType={1} refreshKey={insRefresh} title="보유 보험" />
      </div>

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

      {/* 기준 미설정 안내 모달 — neutral 이고 보험 있을 때 한 번만 표시(닫으면 해제) */}
      {!loading && !error && heatmap && heatmap.mode === "neutral" &&
        heatmap.insurance_count > 0 && !baselineModalDismissed && (
        <BaselineRequiredModal onDismiss={() => setBaselineModalDismissed(true)} />
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
      {heatmap && heatmap.insurance_count > 0 && (
        <PremiumSplitSection summary={heatmap.summary} insurances={heatmap.insurances} />
      )}
    </div>
  );
}

// ── 비교 분석 탭 ── compareCustomer 실연결. 2026-07-09 재정의: 판정(KEEP/SWITCH) 없이
// 두 보험을 나란히 정리해 보여주는 중립 시각화. 정직성 레드라인 전면 적용 ──────────
function SwitchTab({ customerId }: { customerId: number }) {
  const [data, setData] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishTooltip, setPublishTooltip] = useState(false);
  const [upgradeInfo, setUpgradeInfo] = useState<UpgradeModalInfo | undefined>(undefined);
  const [upgradeOpen, setUpgradeOpen] = useState(false);
  // ④ 비교안내서 = 설계사 직접 발송 — 인파는 복사 편의만 제공(자동 발송 없음, §97).
  const [copyMsg, setCopyMsg] = useState<string | null>(null);

  // 보험 목록 + 비교 대상 자유 배정(A안/B안/미포함, 2026-07-09 재정의 — 보유/제안 풀 구분 없이
  // 아무 보험이나 A·B에 넣을 수 있다: 제안 vs 제안·증권 vs 증권도 가능). 마운트 시 보유→A/제안→B
  // 프리셋(회귀 방지 UX), 이후 설계사가 자유 변경. 목록 새로고침 시 기존 배정은 보존, 새 보험만 프리셋.
  const [insurances, setInsurances] = useState<ManualInsuranceItem[]>([]);
  const [assign, setAssign] = useState<Record<number, SideAssign>>({});
  const [insLoaded, setInsLoaded] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);

  const loadInsurances = useCallback(() => {
    listManualInsurances(customerId)
      .then((r) => {
        setInsurances(r.results);
        setAssign((prev) => {
          const next: Record<number, SideAssign> = {};
          for (const it of r.results) {
            // 기존 배정(A·B·none 모두)은 그대로 보존 — 설계사가 뺀 보험을 되살리지 않는다.
            if (it.id in prev) { next[it.id] = prev[it.id]; continue; }
            if (it.portfolio_type === 1) next[it.id] = "A";
            else if (it.portfolio_type === 2) next[it.id] = "B";
            else next[it.id] = "none";
          }
          return next;
        });
        setInsLoaded(true);
      })
      .catch(() => setInsLoaded(true));
  }, [customerId]);
  useEffect(() => { loadInsurances(); }, [loadInsurances]);

  const doCompare = useCallback(() => {
    setLoading(true);
    setError(null);
    setUpgradeInfo(undefined);
    setUpgradeOpen(false);
    const sideAIds = Object.entries(assign).filter(([, v]) => v === "A").map(([id]) => Number(id));
    const sideBIds = Object.entries(assign).filter(([, v]) => v === "B").map(([id]) => Number(id));
    compareCustomer(customerId, { sideAIds, sideBIds })
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
  }, [customerId, assign]);

  // 제안 추가(업로드/직접) 후 목록 새로고침 → 배정 갱신(기존 보존+신규 프리셋) → 재비교.
  const propOcr = useOcrUpload(() => { loadInsurances(); }, 2);

  useEffect(() => {
    if (insLoaded) doCompare();
  }, [doCompare, insLoaded]);

  const aCount = Object.values(assign).filter((v) => v === "A").length;
  const bCount = Object.values(assign).filter((v) => v === "B").length;

  // 발행 버튼 — publishable=false 이므로 항상 disabled
  async function handlePublish() {
    if (!data || data.publishable !== false) return;
    setPublishing(false); // 절대 실행 안 됨 — 타입 명시 목적
    void publishing; // lint 억제
  }

  if (loading && !data) {
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
  // 담보 변동: 추가(신규)/삭제(빠짐)/변경/유지 — A안 vs B안 금액 기준. 라벨 판정은 compare-export 와 공유.
  function diffLabel(cur: number | null, prop: number | null): { text: string; cls: string } {
    const text = compareDiffText(cur, prop);
    const clsBy: Record<string, string> = {
      "추가": "bg-emerald-50 text-emerald-700 border-emerald-200",
      "삭제": "bg-rose-50 text-rose-600 border-rose-200",
      "변경": "bg-amber-50 text-amber-700 border-amber-200",
    };
    return { text, cls: clsBy[text] ?? "bg-surface2 text-ink3 border-line" };
  }

  // ★ 열 이름 적응(사실 정확성 + §97): A안이 전부 보유(portfolio_type==1)이고 B안이 전부 제안(==2)인
  //   '표준 갈아타기' 배치일 때만 친숙한 '현재/제안'을 쓴다. 제안 vs 제안·증권 vs 증권처럼 그렇지
  //   않은 배치에선 A측을 '현재'로 부르면 고객에게 거짓이 되므로 중립 라벨 'A안/B안'을 쓴다.
  const aTypes = new Set(insurances.filter((i) => assign[i.id] === "A").map((i) => i.portfolio_type));
  const bTypes = new Set(insurances.filter((i) => assign[i.id] === "B").map((i) => i.portfolio_type));
  const canonicalSides =
    aTypes.size > 0 && bTypes.size > 0 &&
    [...aTypes].every((t) => t === 1) && [...bTypes].every((t) => t === 2);
  const labelA = canonicalSides ? "현재" : "A안";
  const labelB = canonicalSides ? "제안" : "B안";
  const canExport = aCount > 0 && bCount > 0;

  // ④ 고객에게 보낼 내용 — 중립 사실만(담보·금액·증감 라벨). §97: 판정·권유·switch_warnings(설계사
  // 내부 전용) 절대 미포함, 인파는 복사만 하고 발송하지 않는다(설계사가 직접 카톡·문자로 전달).
  // 텍스트 생성은 가드되는 lib/compare-export 로 분리(권유어 CI 검사 대상).
  async function copyExportText() {
    if (!data || !canExport) return;
    const ok = await copyText(buildCompareExportText(data, labelA, labelB));
    setCopyMsg(ok ? "복사했어요. 고객에게 붙여넣어 보내세요." : "복사에 실패했어요. 다시 시도해 주세요.");
    setTimeout(() => setCopyMsg(null), 3000);
  }

  return (
    <div>
      {/* 비교할 보험 고르기 — 보유·제안 구분 없이 아무 보험이나 A안·B안·미포함 중 하나로 자유 배정.
          제안끼리, 보유끼리도 비교 가능(2026-07-09 재정의). 배정 바뀌면 그 조합으로 재비교(나란히 정리, 판단은 설계사). */}
      <div className="mb-4 rounded-2xl border border-line bg-surface2 p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <div className="text-[13px] font-bold text-ink">
            비교할 보험 고르기 <span className="text-ink3 tnum">A안 {aCount} · B안 {bCount}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <OcrUploadButton customerId={customerId} phase={propOcr.phase} onFileChange={propOcr.onFileChange} inputId="proposal-ocr-input" label="제안서 업로드" />
            <button type="button" onClick={() => setManualOpen(true)} className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition">직접 입력</button>
          </div>
        </div>
        {insurances.length === 0 ? (
          <p className="text-[12px] text-ink3 leading-5">분석 탭에서 증권을 등록하거나 가입제안서를 올리면 여기에서 비교 대상을 고를 수 있어요.</p>
        ) : (
          <div className="space-y-2">
            {insurances.map((it) => (
              <AssignInsRow
                key={it.id}
                it={it}
                value={assign[it.id] ?? "none"}
                onChange={(v) => assignInsurance(setAssign, it.id, v)}
              />
            ))}
          </div>
        )}
        <p className="mt-2.5 text-[11px] leading-4 text-ink3">
          각 보험을 A안·B안 중 하나로 고르거나 비교에서 빼세요. 제안끼리, 보유끼리도 나란히 비교할 수 있어요.
        </p>
      </div>
      <OcrStatusBanner phase={propOcr.phase} errorMsg={propOcr.error} onDismiss={propOcr.clearError} onManualEntry={() => setManualOpen(true)} />
      {propOcr.phase === "consent_required" && (
        <ConsentModal
          onGenerate={() => propOcr.generateConsentLink(customerId)}
          consentUrl={propOcr.consentUrl}
          consentCopied={propOcr.consentCopied}
          onCopy={propOcr.copyConsentUrl}
          onDismiss={propOcr.dismissConsent}
          loading={propOcr.consentLoading}
        />
      )}
      <UpgradeModal open={propOcr.phase === "limit_exceeded"} onClose={propOcr.dismissUpgrade} info={propOcr.upgradeInfo} />
      {manualOpen && (
        <InsuranceManualModal
          customerId={customerId}
          defaultPortfolioType={2}
          onClose={() => setManualOpen(false)}
          onCreated={() => { setManualOpen(false); loadInsurances(); }}
        />
      )}

      {/* AI 초안 면책 — 항상 노출, 접기 불가 */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 mb-4">
        <p className="text-[12px] leading-5 text-amber-800">
          {data.disclaimer}
        </p>
      </div>

      {/* ── 확인해야 할 사항 (중립 사실 — 판정 아님, 설계사 내부 전용) ──────────────
          2026-07-09 재정의: 인파는 KEEP/SWITCH 를 정하지 않는다. 해지환급 손실 추정 등
          설계사가 검토할 사실만 나란히 정리해 보여주고, 판단은 설계사가 한다. */}
      {data.switch_warnings && data.switch_warnings.length > 0 && (
        <div className="rounded-xl border border-line bg-surface2 px-4 py-3.5 mb-4">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-bold text-ink">확인해야 할 사항</span>
            <span className="ml-auto text-[10px] font-semibold rounded-full bg-surface px-2 py-0.5 text-ink3">
              설계사 검토용 · 비공개
            </span>
          </div>
          <ul className="mt-2 space-y-1.5">
            {data.switch_warnings.map((w, i) => (
              <li key={i} className="text-[12px] leading-5 flex gap-1.5 text-ink2">
                <span className="text-ink3">·</span>
                <span>
                  <b className="font-semibold text-ink">{w.label}</b>
                  {w.amount !== null && (
                    <> · {new Intl.NumberFormat("ko-KR").format(w.amount)}원</>
                  )}
                  <span className="opacity-80">: {w.detail}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] leading-4 text-ink3">
            나란히 정리한 참고 사실이에요. 어느 쪽이 나을지는 고객 상황에 맞춰 설계사님이 판단해 주세요.
            갈아타기(승환)라면 이 불리사항(해지손실·면책기간·이율 변동 등)은 고객에게 따로 안내해 주세요.
          </p>
        </div>
      )}

      {/* 보험료 요약 */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="rounded-xl border border-line bg-surface2 px-4 py-3">
          <div className="text-[11px] font-semibold text-ink3">{labelA} 월 보험료</div>
          <div className="mt-1 text-[16px] font-bold text-ink tnum">
            {fmtPrem(data.current.monthly_premiums)}
          </div>
          <div className="mt-0.5 text-[11px] text-ink3 tnum">
            총납 {fmtPrem(data.current.total_premiums)}
          </div>
        </div>
        <div className="rounded-xl border border-line bg-surface2 px-4 py-3">
          <div className="text-[11px] font-semibold text-ink3">{labelB} 월 보험료</div>
          <div className="mt-1 text-[16px] font-bold text-ink tnum">
            {fmtPrem(data.proposed.monthly_premiums)}
          </div>
          <div className="mt-0.5 text-[11px] text-ink3 tnum">
            총납 {fmtPrem(data.proposed.total_premiums)}
          </div>
        </div>
      </div>

      {/* 갱신/비갱신 보험료 요약·증감 표 */}
      <ComparePremiumSplit current={data.current} proposed={data.proposed} labelA={labelA} labelB={labelB} />

      {/* 기존 vs 제안 보장 그룹 막대(006) — 담보별 2줄(기존·제안). 정확 수치 같이 표시 + 아래 비교표 */}
      {data.rows.length >= 2 && (
        <div className="rounded-xl border border-line bg-surface px-4 py-3.5 mb-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[13px] font-bold text-ink">보장 비교 ({labelA} vs {labelB})</span>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="inline-flex items-center gap-1 text-ink2">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--existing)" }} />{labelA}
              </span>
              <span className="inline-flex items-center gap-1 text-ink2">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--proposal)" }} />{labelB}
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
          <p className="mt-2 text-[11px] text-ink3">담보별 {labelA}·{labelB} 보장금액 비교예요. 정확한 수치는 아래 비교표에서 확인하세요.</p>
        </div>
      )}

      {/* 담보 비교표 */}
      {data.rows.length > 0 ? (
        <div className="rounded-xl border border-line overflow-hidden">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-surface2 border-b border-line">
                <th className="px-3 py-2.5 text-left font-semibold text-ink2">담보</th>
                <th className="px-3 py-2.5 text-right font-semibold text-ink2">{labelA}</th>
                <th className="px-3 py-2.5 text-right font-semibold text-ink2">{labelB}</th>
                <th className="px-3 py-2.5 text-right font-semibold text-ink2">증감</th>
                <th className="px-3 py-2.5 text-center font-semibold text-ink2">변동</th>
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
                  <td className="px-3 py-2.5 text-center">
                    {(() => {
                      const d = diffLabel(row.current_amount, row.proposed_amount);
                      return (
                        <span className={`inline-block text-[10px] font-semibold rounded-full px-2 py-0.5 border ${d.cls}`}>
                          {d.text}
                        </span>
                      );
                    })()}
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

      {/* ④ 고객에게 보낼 내용 복사 — 인파는 복사만, 발송은 설계사가 직접(카톡·문자). 중립 사실만
          담아 §97을 지킨다(판정·권유·확인해야 할 사항 미포함, 위 buildExportText 참고). */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={copyExportText}
          disabled={!canExport}
          className="rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-surface"
        >
          고객에게 보낼 내용 복사
        </button>
        {copyMsg
          ? <span className="text-[12px] text-ink3">{copyMsg}</span>
          : !canExport && <span className="text-[12px] text-ink3">A안·B안에 보험을 하나씩 배정하면 복사할 수 있어요.</span>}
      </div>
      <p className="mt-2 text-[11px] leading-4 text-ink3">
        복사되는 내용에는 해지손실·면책 같은 불리사항이 들어가지 않아요. 갈아타기라면 불리사항은 고객에게 따로 안내해 주세요.
      </p>

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
              법무 검토가 끝나면 두 보험을 나란히 정리한 안내 초안을 받아보실 수 있어요.
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
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
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
