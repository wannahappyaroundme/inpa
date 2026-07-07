"use client";

import { useState, useEffect, useCallback, useRef, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { DisclaimerFooter } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  HeatmapGrid,
  KpiCard,
  fmtWon,
  type FilterKey,
} from "@/components/heatmap";
import {
  useOcrUpload,
  OcrUploadButton,
  OcrStatusBanner,
  ConsentModal,
} from "@/components/ocr-upload";
import { InsuranceManualModal } from "@/components/insurance-manual-modal";
import { BaselineRequiredModal } from "@/components/baseline-required-modal";
import { UpgradeModal } from "@/components/upgrade-modal";
import {
  getHeatmap,
  listCustomers,
  type HeatmapResponse,
  type InsuranceFee,
  type CustomerListItem,
} from "@/lib/api";

// ──────────────────────────────────────────────
// 담보 한눈표(히트맵) — 설계사 전용 도구. 고객 선택 → 분석.
// ★ 한 동선 IA: 고객 선택 시 /customer/<id>?tab=analysis 로 유도(고객 1명 중심 셸).
//   /analysis 는 고객 미선택(선택 허브) 상태 유지 + 빠른 미리보기 호환.
// 상태 판정은 BE 권위(neutral/graded). 충족/부족 단정 금지(neutral 모드).
// ──────────────────────────────────────────────

export default function AnalysisPage() {
  return (
    <Suspense fallback={<AnalysisPageSkeleton />}>
      <AnalysisPageInner />
    </Suspense>
  );
}

function AnalysisPageSkeleton() {
  return (
    <div className="min-h-dvh">
      <AppNav active="analysis" />
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        <div className="h-8 w-40 rounded-xl bg-line animate-pulse" />
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 rounded-2xl bg-line animate-pulse" />
          ))}
        </div>
      </main>
    </div>
  );
}

function AnalysisPageInner() {
  const ready = useAuthGuard();
  const searchParams = useSearchParams();
  const router = useRouter();

  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [customersLoading, setCustomersLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null);
  const [heatmapLoading, setHeatmapLoading] = useState(false);
  const [heatmapError, setHeatmapError] = useState<string | null>(null);

  const [graded, setGraded] = useState(true);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [manualOpen, setManualOpen] = useState(false);
  const [baselineModalDismissed, setBaselineModalDismissed] = useState(false);

  // ── 보험별 보기 (보유 2개 이상일 때 카드 선택) ──
  // selectedInsId=null → 전체 합산(heatmap 재사용, 재조회 없음).
  // 카드 선택 → insurance_id 로 그 보험만 집계한 응답을 insHeatmap 에 로드.
  const [selectedInsId, setSelectedInsId] = useState<number | null>(null);
  const [insHeatmap, setInsHeatmap] = useState<HeatmapResponse | null>(null);
  const [insLoading, setInsLoading] = useState(false);
  const [insError, setInsError] = useState<string | null>(null);
  // 카드 연타 시 늦게 도착한 이전 응답이 새 선택을 덮어쓰지 않도록 요청 번호로 가드.
  const insReqRef = useRef(0);

  // ── 히트맵 로드 (전체 합산) — 고객 변경/증권 등록 시 보험 선택도 초기화 ──
  const fetchHeatmap = useCallback(async (id: number) => {
    setHeatmapLoading(true);
    setHeatmapError(null);
    setHeatmap(null);
    insReqRef.current += 1; // 진행 중이던 보험별 조회 무효화
    setSelectedInsId(null);
    setInsHeatmap(null);
    setInsError(null);
    setInsLoading(false);
    try {
      const data = await getHeatmap(id);
      setHeatmap(data);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "분석 데이터를 불러오지 못했어요.";
      setHeatmapError(msg);
    } finally {
      setHeatmapLoading(false);
    }
  }, []);

  // ── 보험 카드 선택: null=전체(재조회 없음) / id=그 보험만 재조회 ──
  const selectInsurance = useCallback(async (customerId: number, insId: number | null) => {
    const req = ++insReqRef.current;
    setSelectedInsId(insId);
    setInsError(null);
    setInsHeatmap(null);
    if (insId === null) {
      setInsLoading(false);
      return;
    }
    setInsLoading(true);
    try {
      const data = await getHeatmap(customerId, insId);
      if (insReqRef.current === req) setInsHeatmap(data);
    } catch (e: unknown) {
      if (insReqRef.current === req) {
        const msg = e instanceof Error ? e.message : "분석 데이터를 불러오지 못했어요.";
        setInsError(msg);
      }
    } finally {
      if (insReqRef.current === req) setInsLoading(false);
    }
  }, []);

  // ── OCR 업로드 (공유 훅) ───────────────────
  const ocr = useOcrUpload((id) => {
    void fetchHeatmap(id);
  });

  // ── 고객 목록 로드 ──────────────────────────
  // ★ 한 동선 유도: ?customer=<id> 로 들어오면 고객 상세 분석 탭으로 리다이렉트.
  useEffect(() => {
    if (!ready) return;
    const qid = searchParams.get("customer");
    if (qid) {
      router.replace(`/customer/${qid}?tab=analysis`);
      return;
    }
    setCustomersLoading(true);
    listCustomers({ page: 1 })
      .then((res) => {
        setCustomers(res.results);
        if (res.results.length > 0) setSelectedId(res.results[0].id);
      })
      .catch(() => setCustomers([]))
      .finally(() => setCustomersLoading(false));
  }, [ready, searchParams, router]);

  useEffect(() => {
    if (selectedId !== null) {
      fetchHeatmap(selectedId);
      setBaselineModalDismissed(false);
    }
  }, [selectedId, fetchHeatmap]);

  if (!ready) return null;

  const selectedCustomer = customers.find((c) => c.id === selectedId);

  // 보유(portfolio_type=1) 2개 이상일 때만 카드 그리드 노출(0~1개는 기존 화면 그대로).
  const ownedCount = heatmap
    ? heatmap.insurances.filter((i) => i.portfolio_type === 1).length
    : 0;
  const showCards = !!heatmap && ownedCount >= 2;
  const selectedIns =
    heatmap && selectedInsId !== null
      ? heatmap.insurances.find((i) => i.id === selectedInsId) ?? null
      : null;

  // 아래 상세 영역(요약 KPI + 한눈표)이 그리는 데이터: 전체 or 선택한 보험.
  const view = selectedInsId === null ? heatmap : insHeatmap;
  const viewLoading = heatmapLoading || insLoading;
  const viewError = selectedInsId === null ? heatmapError : insError;

  return (
    <div className="min-h-dvh">
      <AppNav active="analysis" />
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        {/* ── 헤더 ── */}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-[13px] text-ink3">담보 한눈표 · 설계사 도구</div>
            <h1 className="text-[22px] font-extrabold text-ink">보장 분석</h1>
          </div>
          <div className="flex items-center gap-2">
            {customersLoading ? (
              <div className="h-9 w-40 rounded-xl bg-line animate-pulse" />
            ) : customers.length > 0 ? (
              <select
                value={selectedId ?? ""}
                onChange={(e) => setSelectedId(Number(e.target.value))}
                className="rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-brand"
              >
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-[13px] text-ink3">고객 없음</span>
            )}
            {selectedId !== null && (
              <Link
                href={`/customer/${selectedId}?tab=analysis`}
                className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition"
              >
                고객 상세 ›
              </Link>
            )}
            {selectedId !== null && (
              <OcrUploadButton
                customerId={selectedId}
                phase={ocr.phase}
                onFileChange={ocr.onFileChange}
              />
            )}
          </div>
        </div>

        <OcrStatusBanner
          phase={ocr.phase}
          errorMsg={ocr.error}
          onDismiss={ocr.clearError}
          onManualEntry={selectedId !== null ? () => setManualOpen(true) : undefined}
        />

        {ocr.phase === "consent_required" && (
          <ConsentModal
            onGenerate={() => ocr.generateConsentLink(selectedId)}
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

        {/* 기준 미설정 안내 모달 — neutral 이고 보험 있을 때 한 번만 표시(닫으면 해제) */}
        {!heatmapLoading && !heatmapError && heatmap &&
          heatmap.mode === "neutral" && heatmap.insurance_count > 0 &&
          !baselineModalDismissed && (
          <BaselineRequiredModal onDismiss={() => setBaselineModalDismissed(true)} />
        )}

        {/* ── 보험별 카드 (보유 2개 이상) — 전체 합산 카드 + 보험별 카드 ── */}
        {!heatmapLoading && !heatmapError && heatmap && showCards && selectedId !== null && (
          <div className="mt-5">
            <p className="mb-2 text-[13px] text-ink3">
              보험을 선택하면 그 보험의 보장만 볼 수 있어요.
            </p>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <button
                type="button"
                aria-pressed={selectedInsId === null}
                onClick={() => void selectInsurance(selectedId, null)}
                className={`rounded-xl border p-3.5 text-left transition ${
                  selectedInsId === null
                    ? "border-brand bg-brand-soft"
                    : "border-line bg-surface hover:bg-surface2"
                }`}
              >
                <div className="text-[14px] font-bold text-ink">전체 한눈에 보기</div>
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
                  <dt className="text-ink3">보험</dt>
                  <dd className="text-ink2 text-right tnum">{heatmap.insurance_count}건 합산</dd>
                  <dt className="text-ink3">월 보험료</dt>
                  <dd className="text-ink2 text-right tnum">{fmtWon(heatmap.summary.monthly_premiums)}</dd>
                </dl>
              </button>
              {heatmap.insurances.map((ins) => (
                <InsuranceSelectCard
                  key={ins.id}
                  ins={ins}
                  selected={selectedInsId === ins.id}
                  onSelect={() => void selectInsurance(selectedId, ins.id)}
                />
              ))}
            </div>
          </div>
        )}

        {/* ── summary KPI (전체 or 선택한 보험 기준) ── */}
        {view && (
          <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <KpiCard label="월 보험료" value={fmtWon(view.summary.monthly_premiums)} />
            <KpiCard label="총 납입 보험료" value={fmtWon(view.summary.total_premiums)} />
            <KpiCard label="보험 건수" value={`${view.insurance_count}건`} />
            <KpiCard
              label="분석 모드"
              value={view.mode === "neutral" ? "기준 미설정" : "기준 적용"}
              valueClass={view.mode === "neutral" ? "text-ink3" : "text-enough"}
            />
          </div>
        )}

        {/* ── 로딩 ── */}
        {viewLoading && (
          <div className="mt-8 space-y-3">
            {[1, 2, 3, 4].map((i) => (
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

        {/* ── 에러 (전체 or 선택한 보험 조회 실패) ── */}
        {viewError && !viewLoading && (
          <div className="mt-6 rounded-xl border border-line bg-surface2 px-4 py-8 text-center">
            <p className="text-[14px] text-ink3">{viewError}</p>
            {selectedId !== null && (
              <button
                onClick={() => {
                  if (selectedInsId === null) fetchHeatmap(selectedId);
                  else void selectInsurance(selectedId, selectedInsId);
                }}
                className="mt-3 text-[13px] font-semibold text-brand"
              >
                다시 시도
              </button>
            )}
          </div>
        )}

        {/* ── 빈 상태(보험 없음) ── */}
        {!heatmapLoading &&
          !heatmapError &&
          heatmap &&
          heatmap.insurance_count === 0 && (
            <div className="mt-6 rounded-2xl border border-dashed border-line px-4 py-12 text-center">
              <p className="text-[15px] font-semibold text-ink2">증권이 아직 없어요</p>
              <p className="mt-1 text-[13px] text-ink3">
                증권을 등록하면 보장 공백이 보여요.
              </p>
              <div className="mt-3 inline-flex flex-wrap items-center justify-center gap-2">
                <OcrUploadButton
                  customerId={selectedId}
                  phase={ocr.phase}
                  onFileChange={ocr.onFileChange}
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

        {manualOpen && selectedId !== null && (
          <InsuranceManualModal
            customerId={selectedId}
            onClose={() => setManualOpen(false)}
            onCreated={() => {
              setManualOpen(false);
              fetchHeatmap(selectedId);
            }}
          />
        )}

        {/* ── 고객 없음 ── */}
        {!customersLoading && customers.length === 0 && (
          <div className="mt-8 text-center text-[14px] text-ink3">
            등록된 고객이 없어요.{" "}
            <Link href="/customers" className="font-semibold text-brand">
              고객 등록 →
            </Link>
          </div>
        )}

        {/* ── 히트맵 그리드 (전체 or 선택한 보험 기준) ── */}
        {!viewLoading &&
          !viewError &&
          view &&
          heatmap &&
          heatmap.insurance_count > 0 && (
            <div className="mt-5">
              {selectedCustomer && (
                <p className="mb-3 text-[13px] text-ink3">
                  <b className="text-ink2">{selectedCustomer.name}</b>님의 보장 한눈표
                  {selectedIns && (
                    <span className="ml-1">
                      · <b className="text-ink2">{selectedIns.name ?? "이름 없는 보험"}</b> 기준
                    </span>
                  )}
                  {view.mode === "neutral" && (
                    <span className="ml-2 inline-flex items-center rounded-full bg-surface2 border border-line px-2 py-0.5 text-[11px] font-semibold text-ink3">
                      기준 미설정
                    </span>
                  )}
                </p>
              )}
              <HeatmapGrid
                heatmap={view}
                graded={graded}
                onGradedChange={setGraded}
                filter={filter}
                onFilterChange={setFilter}
              />
            </div>
          )}

        <DisclaimerFooter />
      </main>
    </div>
  );
}

// ── 보험 선택 카드 — 고객 상세 InsuranceCard 스타일 재사용(보험명·종류·월보험료·담보 수) ──
function InsuranceSelectCard({
  ins,
  selected,
  onSelect,
}: {
  ins: InsuranceFee;
  selected: boolean;
  onSelect: () => void;
}) {
  const typeLabel = ins.insurance_type === 1 ? "생명" : "손해";
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`rounded-xl border p-3.5 text-left transition ${
        selected ? "border-brand bg-brand-soft" : "border-line bg-surface hover:bg-surface2"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-[14px] font-bold text-ink truncate">
          {ins.name ?? "이름 없는 보험"}
        </div>
        <span className="flex shrink-0 items-center gap-1">
          {ins.portfolio_type === 2 && (
            <span className="text-[10px] font-semibold rounded-full px-2 py-0.5 bg-brand-soft text-brand border border-line">
              제안
            </span>
          )}
          <span className="text-[10px] font-semibold rounded-full px-2 py-0.5 bg-surface2 text-ink3 border border-line">
            {typeLabel}
          </span>
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
        <dt className="text-ink3">월 보험료</dt>
        <dd className="text-ink2 text-right tnum">{fmtWon(ins.monthly_premiums)}</dd>
        <dt className="text-ink3">담보</dt>
        <dd className="text-ink2 text-right tnum">{ins.case_fees.length}개</dd>
      </dl>
    </button>
  );
}
