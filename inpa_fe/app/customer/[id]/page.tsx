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

import { useState, useEffect, useCallback, Suspense } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card, DisclaimerFooter } from "@/components/ui";
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
import { LineCompareChart } from "@/components/charts";
import {
  getCustomer,
  getHeatmap,
  compareCustomer,
  getCustomerHistory,
  getProfile,
  ApiError,
  type CustomerDetail,
  type HeatmapResponse,
  type HeatmapDetail,
  type CompareResponse,
  type HistoryEvent,
  type ProfileResponse,
} from "@/lib/api";

type TabKey = "analysis" | "switch" | "gap" | "history";

const TABS: { key: TabKey; label: string }[] = [
  { key: "analysis", label: "분석" },
  { key: "switch", label: "비교 분석" },
  { key: "gap", label: "공백" },
  { key: "history", label: "이력" },
];

// ── 헬퍼 ──────────────────────────────────────
function calcAge(birthDay: string | null): string {
  if (!birthDay) return "—";
  const birth = new Date(birthDay);
  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  const m = today.getMonth() - birth.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--;
  return `${age}세`;
}
function genderLabel(g: string | null): string {
  if (g === "M") return "남";
  if (g === "F") return "여";
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

  // 히트맵 그리드 UI 상태
  const [graded, setGraded] = useState(true);
  const [filter, setFilter] = useState<FilterKey>("all");

  const fetchHeatmap = useCallback(
    async (id: number) => {
      setHeatmapLoading(true);
      setHeatmapError(null);
      setHeatmap(null);
      try {
        setHeatmap(await getHeatmap(id));
      } catch (e: unknown) {
        setHeatmapError(
          e instanceof Error ? e.message : "분석 데이터를 불러오지 못했어요."
        );
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
  const sub = [calcAge(customer.birth_day), genderLabel(customer.gender)]
    .filter(Boolean)
    .join(" · ");
  return (
    <Card className="mt-3 p-4 flex items-center gap-3">
      <div
        className="w-12 h-12 rounded-full flex items-center justify-center text-[18px] font-bold shrink-0 text-brand"
        style={{ backgroundColor: customer.color ?? "var(--accent-tint)" }}
      >
        {customer.name[0]}
      </div>
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

// ── 분석 탭 ───────────────────────────────────────────────────────────────
type OcrCtl = ReturnType<typeof useOcrUpload>;

function AnalysisTab({
  customerId,
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
          />
        </div>
      </div>
      {bookingOpen && (
        <BookingModal customerId={customerId} onClose={() => setBookingOpen(false)} />
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

      {/* neutral 안내 */}
      {heatmap?.mode === "neutral" && (
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-line bg-surface2 px-4 py-3">
          <span className="mt-0.5 text-[16px]" aria-hidden>
            ⓘ
          </span>
          <p className="text-[13px] text-ink2 leading-5">
            <b className="font-semibold text-ink">기준 미설정 — 중립 표시</b>
            <br />
            보장 기준선이 설정되지 않아 보유 여부만 표시해요. 기준을 설정하면
            부족·적정·넉넉을 구분할 수 있어요.
          </p>
          <Link
            href="/settings/baseline"
            className="ml-auto shrink-0 text-[12px] font-semibold text-brand whitespace-nowrap"
          >
            기준 설정 ›
          </Link>
        </div>
      )}

      {/* KPI */}
      {heatmap && (
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="월 보험료" value={fmtWon(heatmap.summary.monthly_premiums)} />
          <KpiCard label="총 납입 보험료" value={fmtWon(heatmap.summary.total_premiums)} />
          <KpiCard label="보험 건수" value={`${heatmap.insurance_count}건`} />
          <KpiCard
            label="분석 모드"
            value={heatmap.mode === "neutral" ? "중립" : "기준 적용"}
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
          <div className="mt-3 inline-flex">
            <OcrUploadButton
              customerId={customerId}
              phase={ocr.phase}
              onFileChange={ocr.onFileChange}
            />
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

  useEffect(() => {
    setLoading(true);
    setError(null);
    compareCustomer(customerId)
      .then((d) => setData(d))
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "비교 데이터를 불러오지 못했어요.");
      })
      .finally(() => setLoading(false));
  }, [customerId]);

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

  if (error || !data) {
    return (
      <div className="rounded-xl border border-line bg-surface2 px-4 py-8 text-center">
        <p className="text-[14px] text-ink3">{error ?? "데이터 없음"}</p>
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            compareCustomer(customerId)
              .then((d) => setData(d))
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

  // 보험료 포맷
  function fmtPrem(v: number | null) {
    if (v === null) return "—";
    return new Intl.NumberFormat("ko-KR").format(v) + "원";
  }
  function fmtDelta(d: number | null) {
    if (d === null) return "—";
    const sign = d > 0 ? "+" : "";
    return sign + new Intl.NumberFormat("ko-KR").format(d);
  }

  return (
    <div>
      {/* AI 초안 면책 — 항상 노출, 접기 불가 */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 mb-4">
        <p className="text-[12px] leading-5 text-amber-800">
          <b className="font-semibold">AI 초안 · 최종 확인 및 책임은 설계사에게 있습니다.</b>
          {" "}{data.disclaimer}
        </p>
      </div>

      {/* ── 갈아타기 판정 (★ 설계사 내부 의사결정 근거 — 고객에게 노출되지 않음) ── */}
      {data.verdict && (() => {
        const v = data.verdict;
        const map = {
          KEEP: { label: "유지가 유리 (추정)", cls: "bg-emerald-50 border-emerald-200 text-emerald-900", dot: "🟢" },
          SWITCH: { label: "전환 검토", cls: "bg-blue-50 border-blue-200 text-blue-900", dot: "🔵" },
          NEUTRAL: { label: "중립 — 상황 판단", cls: "bg-surface2 border-line text-ink2", dot: "⚪" },
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
                      <span className="opacity-80"> — {w.detail}</span>
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

      {/* 기존 vs 제안 보장 라인차트(006) — 상대 흐름. 정확 수치는 아래 비교표(가짜데이터 금지 원칙: rows 그대로) */}
      {data.rows.length >= 2 && (
        <div className="rounded-xl border border-line bg-surface px-4 py-3.5 mb-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[13px] font-bold text-ink">보장 비교 (기존 vs 제안)</span>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="inline-flex items-center gap-1 text-ink2">
                <span className="w-2.5 h-[3px] rounded" style={{ background: "var(--existing)" }} />기존
              </span>
              <span className="inline-flex items-center gap-1 text-ink2">
                <span className="w-2.5 h-[3px] rounded" style={{ background: "var(--proposal)" }} />제안
              </span>
            </div>
          </div>
          <LineCompareChart
            series={[
              { label: "기존", color: "var(--existing)", points: data.rows.map((r) => r.current_amount ?? 0) },
              { label: "제안", color: "var(--proposal)", points: data.rows.map((r) => r.proposed_amount ?? 0) },
            ]}
          />
          <p className="mt-1.5 text-[11px] text-ink3">담보별 보장금액의 상대 흐름이에요. 정확한 수치는 아래 비교표에서 확인하세요.</p>
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
                      : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right text-ink3 tnum">
                    {row.proposed_amount !== null
                      ? new Intl.NumberFormat("ko-KR").format(row.proposed_amount)
                      : "—"}
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
              이 초안은 AI가 생성한 참고 자료입니다. 최종 내용 확인 및 고객 안내 책임은 설계사에게 있습니다.
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
          {isExclusive ? "🎯 자사 보장공백" : "보장 공백"}{" "}
          <span className="text-ink3 tnum">{gaps.length}</span>
        </h3>
        <span className="text-[12px] text-ink3">보유 0 담보</span>
      </div>

      {/* graded 일 때만 '부족' 단정 가능, neutral 이면 '미보유' 사실만 */}
      <p className="mt-1.5 text-[12px] leading-5 text-ink3">
        {isExclusive
          ? "보유하지 않은 담보예요. 자사 상품으로 채울 수 있는 보장 기회를 검토하세요(판정·최종책임은 설계사)."
          : heatmap.mode === "graded"
          ? "보유 금액이 0인 담보예요. 부족 여부 판정은 설정한 기준에 따른 결과이며, 권유·최종책임은 설계사에게 있습니다."
          : "보유 금액이 0인 담보(객관적 사실)만 모았어요. 기준 미설정(중립)이라 부족·충분은 단정하지 않습니다."}
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
                {ev.meta && Object.keys(ev.meta).length > 0 && (
                  <p className="mt-0.5 text-[12px] text-ink3 leading-5 truncate">
                    {Object.entries(ev.meta)
                      .slice(0, 2)
                      .map(([k, v]) => `${k}: ${String(v)}`)
                      .join(" · ")}
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
