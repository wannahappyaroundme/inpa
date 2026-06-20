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
import {
  getCustomer,
  getHeatmap,
  ApiError,
  type CustomerDetail,
  type HeatmapResponse,
  type HeatmapDetail,
} from "@/lib/api";

type TabKey = "analysis" | "switch" | "gap" | "history";

const TABS: { key: TabKey; label: string }[] = [
  { key: "analysis", label: "분석" },
  { key: "switch", label: "갈아타기" },
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

  // 탭 상태 (URL ?tab= 동기화)
  const tabParam = searchParams.get("tab") as TabKey | null;
  const activeTab: TabKey =
    tabParam && TABS.some((t) => t.key === tabParam) ? tabParam : "analysis";

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
              {TABS.map((t) => (
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
              {activeTab === "switch" && <SwitchTab />}
              {activeTab === "gap" && (
                <GapTab
                  heatmap={heatmap}
                  loading={heatmapLoading}
                  error={heatmapError}
                  onRetry={() => fetchHeatmap(customerId)}
                />
              )}
              {activeTab === "history" && <HistoryTab />}
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
  return (
    <div>
      {/* 증권 OCR 업로드 입구 (분석 탭으로 이동) */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13px] text-ink3">담보 한눈표 · 설계사 도구</div>
        <OcrUploadButton
          customerId={customerId}
          phase={ocr.phase}
          onFileChange={ocr.onFileChange}
        />
      </div>

      <OcrStatusBanner
        phase={ocr.phase}
        errorMsg={ocr.error}
        onDismiss={ocr.clearError}
      />
      {ocr.phase === "consent_required" && (
        <ConsentModal
          onAgree={() => ocr.agreeAndRetry(customerId)}
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

// ── 갈아타기 탭 ── §97 컴플라이언스 게이트 placeholder (가짜 데이터 금지) ────
function SwitchTab() {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-surface2 px-5 py-10 text-center">
      <span className="inline-flex items-center rounded-full bg-amber-50 border border-amber-200 px-3 py-1 text-[12px] font-bold text-amber-700">
        준비 중 · 컴플라이언스 게이트
      </span>
      <h3 className="mt-4 text-[16px] font-bold text-ink">
        갈아타기 비교안내서
      </h3>
      <p className="mx-auto mt-2 max-w-md text-[13px] leading-6 text-ink2">
        갈아타기(승환) 비교안내서는 <b className="text-ink">보험업법 §97 부당승환</b>{" "}
        관련 법적 요건이 확정되어야 제공할 수 있어요. 현재 비교안내 기능은
        <b className="text-ink"> 법무 게이트 + 백엔드 미구현</b> 상태라 화면을 열지 않습니다.
      </p>
      <ul className="mx-auto mt-4 max-w-md space-y-1.5 text-left text-[12px] text-ink3 leading-5">
        <li>· 게이트 사유 ①: §97 비교안내 법적 요건(필수 고지·불리점 표기) 미확정</li>
        <li>· 게이트 사유 ②: 비교 산출 백엔드(compare API) 미구현</li>
        <li>· 우회 금지: 가짜·예시 비교 데이터로 화면을 채우지 않습니다(정직성 레드라인)</li>
      </ul>
      <p className="mx-auto mt-4 max-w-md text-[11px] text-muted leading-5">
        제공 시에도 결과물은 AI 초안이며, 비교안내의 최종 확인·책임은 설계사에게 있습니다.
      </p>
    </div>
  );
}

// ── 공백 탭 ── 보유 0(미보유) 담보 모음. 부족/충분 단정은 graded 일 때만 ─────
function GapTab({
  heatmap,
  loading,
  error,
  onRetry,
}: {
  heatmap: HeatmapResponse | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
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
          보장 공백{" "}
          <span className="text-ink3 tnum">{gaps.length}</span>
        </h3>
        <span className="text-[12px] text-ink3">보유 0 담보</span>
      </div>

      {/* graded 일 때만 '부족' 단정 가능, neutral 이면 '미보유' 사실만 */}
      <p className="mt-1.5 text-[12px] leading-5 text-ink3">
        {heatmap.mode === "graded"
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

// ── 이력 탭 ── 공유 열람/접점 이력 placeholder (데이터 소스 준비 시 연결) ────
function HistoryTab() {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-surface2 px-5 py-12 text-center">
      <h3 className="text-[16px] font-bold text-ink">접점 이력</h3>
      <p className="mx-auto mt-2 max-w-md text-[13px] leading-6 text-ink2">
        공유 링크 열람·상담·메시지 등 고객 접점 이력을 모아 볼 자리예요. 이력
        데이터 소스가 연결되면 이곳에 시간순으로 표시됩니다.
      </p>
      <p className="mt-3 text-[12px] text-muted">
        지금은 연결된 이력 데이터가 없어요(빈 상태).
      </p>
    </div>
  );
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
