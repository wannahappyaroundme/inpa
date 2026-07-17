"use client";

// Claude 호출당 비용·파싱 결과 계측 (프리런치 리뷰 #17).
// ★ 비용은 전부 "추정치"(토큰 × 모델 단가 × 환율 추정)입니다. 실제 청구서와 다를 수 있어요.
//   판정어 없이 사실 수치만 표시합니다. 데모 계정(@inpa.local) 제외.

import { useState, useEffect, useCallback, useRef } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import { adminGetClaudeCost, type AdminClaudeCostResponse } from "@/lib/adminApi";
import { Card } from "@/components/ui";
import { BarChart, DonutChart } from "@/components/charts";
import { createLatestRequestGuard, runLatestRequest } from "@/lib/latest-request";

const KO = new Intl.NumberFormat("ko-KR");

const OUTCOME_LABEL: Record<string, string> = {
  success: "성공",
  empty: "빈 결과",
  json_invalid: "형식 오류",
  schema_invalid: "형식 확인 필요",
  privacy_rejected: "개인정보 차단",
  transport_failure: "연결 오류",
  config_failure: "실행 구성 확인 필요",
  api_error: "API 오류",
  timeout: "시간 초과",
  no_key: "연결 키 확인 필요",
  package_missing: "실행 구성 확인 필요",
  other: "기타",
};
const OUTCOME_COLOR: Record<string, string> = {
  success: "var(--brand)",
  empty: "var(--accent)",
  json_invalid: "var(--danger)",
  schema_invalid: "var(--danger)",
  privacy_rejected: "var(--danger)",
  transport_failure: "var(--danger)",
  config_failure: "var(--ink3)",
  api_error: "var(--danger)",
  timeout: "var(--danger)",
  no_key: "var(--ink3)",
  package_missing: "var(--ink3)",
  other: "var(--ink3)",
};

const RANGES = [
  { v: 7, l: "7일" },
  { v: 30, l: "30일" },
  { v: 90, l: "90일" },
  { v: 0, l: "전체" },
];

function won(n: number) {
  return `${KO.format(Math.round(n))}원`;
}

function duration(ms: number | null) {
  if (ms === null) return "-";
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}분`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(1)}초`;
  return `${KO.format(ms)}ms`;
}

function percent(value: number | null) {
  return value === null ? "-" : `${value.toFixed(1)}%`;
}

const JOB_STATUS_LABEL: Record<string, string> = {
  queued: "대기",
  extracting: "자동 정리",
  validating: "형식 확인",
  review_required: "사람 확인",
  confirmed: "확정",
  failed: "다시 확인",
  canceled: "취소",
  superseded: "교체",
  other: "기타",
};

const REVIEW_STATE_LABEL: Record<string, string> = {
  review_ready: "바로 확인",
  needs_review: "직접 확인",
  no_evidence: "근거 부족",
  unmatched: "담보 연결 필요",
  invalid: "값 확인 필요",
  manual: "직접 입력",
};

export default function AdminClaudeCostPage() {
  const ready = useAdminGuard();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AdminClaudeCostResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestGuard = useRef(createLatestRequestGuard());

  const load = useCallback(async () => {
    await runLatestRequest(
      requestGuard.current,
      () => adminGetClaudeCost(days),
      {
        onStart: () => {
          setLoading(true);
          setError(null);
          setData(null);
        },
        onSuccess: setData,
        onError: () => {
          setData(null);
          setError("비용 데이터를 다시 불러와 주세요.");
        },
        onFinish: () => setLoading(false),
      },
    );
  }, [days]);

  useEffect(() => {
    if (!ready) return;
    void load();
    return () => requestGuard.current.supersede();
  }, [ready, load]);

  useEffect(
    () => () => requestGuard.current.dispose(),
    [],
  );

  if (!ready) return null;

  const outcomeSegments = data
    ? Object.entries(data.outcome_counts)
        .filter(([, v]) => v > 0)
        .map(([k, v]) => ({
          label: OUTCOME_LABEL[k] ?? k,
          value: v,
          color: OUTCOME_COLOR[k] ?? "var(--ink3)",
        }))
    : [];

  const dailyBars =
    data?.daily.map((d) => ({ label: (d.date ?? "").slice(5) || "-", value: d.cost_krw })) ?? [];

  return (
    <div>
      <div className="flex items-start justify-between gap-3 flex-wrap mb-6">
        <div>
          <h1 className="text-[22px] font-extrabold text-ink">Claude 비용·결과 계측</h1>
          <p className="mt-1 text-[13px] text-ink3">
            비용은 토큰 수 × 모델 단가 × 환율({data ? KO.format(data.usd_krw_rate) : "-"}원/USD
            가정)로 계산한 <b className="text-ink2">추정치</b>예요. 실제 청구서와 다를 수 있어요.
            (데모 계정 제외)
          </p>
        </div>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r.v}
              onClick={() => {
                if (r.v === days) return;
                requestGuard.current.supersede();
                setData(null);
                setError(null);
                setLoading(true);
                setDays(r.v);
              }}
              className={`rounded-lg px-3 py-1.5 text-[13px] font-semibold transition ${
                days === r.v ? "bg-brand-soft text-brand" : "bg-surface2 text-ink2 hover:bg-line"
              }`}
            >
              {r.l}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-line bg-danger-tint p-3 text-[13px] text-danger-ink">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => void load()}
            className="shrink-0 rounded-lg bg-surface px-3 py-1.5 font-semibold text-ink2"
          >
            다시 불러오기
          </button>
        </div>
      )}
      {loading && <div className="mt-2 h-40 rounded-2xl bg-line animate-pulse" />}

      {data && !loading && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Card className="px-4 py-3.5">
              <div className="text-[11px] text-ink3">총 호출</div>
              <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                {KO.format(data.total_calls)}건
              </div>
            </Card>
            <Card className="px-4 py-3.5">
              <div className="text-[11px] text-ink3">총 추정 비용</div>
              <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                {won(data.total_cost_krw)}
              </div>
            </Card>
            <Card className="px-4 py-3.5">
              <div className="text-[11px] text-ink3">성공률</div>
              <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                {data.success_rate === null ? "-" : `${data.success_rate.toFixed(1)}%`}
              </div>
            </Card>
          </div>

          <Card className="mt-3 p-4">
            <div className="text-[13px] font-semibold text-ink">토큰 사용량</div>
            <p className="mt-0.5 text-[11px] text-ink3">
              모든 AI 호출 기록에서 합산한 수치예요. 증권 작업 결과에 저장된 값은 비용 합계에 더하지 않아요.
            </p>
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                ["입력", data.total_tokens.input],
                ["출력", data.total_tokens.output],
                ["캐시 사용", data.total_tokens.cache_read],
                ["캐시 생성", data.total_tokens.cache_creation],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-xl bg-surface2 px-3 py-2.5">
                  <div className="text-[11px] text-ink3">{label}</div>
                  <div className="mt-1 text-[16px] font-bold text-ink tnum">
                    {KO.format(Number(value))}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-3">
            <Card className="p-4">
              <div className="text-[13px] font-semibold text-ink mb-2">일별 추정 비용 추이</div>
              <BarChart data={dailyBars} format={won} />
            </Card>
            <Card className="p-4">
              <div className="text-[13px] font-semibold text-ink mb-2">파싱 결과 분포</div>
              {outcomeSegments.length === 0 ? (
                <div className="h-24 flex items-center justify-center text-[12px] text-ink3">
                  데이터가 아직 없어요
                </div>
              ) : (
                <div className="flex items-center gap-4">
                  <DonutChart segments={outcomeSegments} className="w-28 shrink-0" />
                  <div className="flex-1 space-y-1.5">
                    {outcomeSegments.map((s) => (
                      <div key={s.label} className="flex items-center justify-between text-[12px]">
                        <span className="flex items-center gap-1.5 text-ink2">
                          <span
                            className="inline-block w-2 h-2 rounded-full"
                            style={{ background: s.color }}
                          />
                          {s.label}
                        </span>
                        <span className="tnum text-ink font-semibold">{s.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          </div>

          <Card className="mt-3 overflow-x-auto">
            <div className="px-3 pt-3 text-[13px] font-semibold text-ink">기능별 비용</div>
            <table className="w-full text-[13px] mt-2">
              <thead>
                <tr className="text-ink3 border-b border-line">
                  <th className="text-left font-semibold px-3 py-2">기능</th>
                  <th className="text-right font-semibold px-2 py-2">호출수</th>
                  <th className="text-right font-semibold px-3 py-2">추정 비용</th>
                </tr>
              </thead>
              <tbody>
                {data.by_action.map((a) => (
                  <tr key={a.action} className="border-b border-line/60">
                    <td className="px-3 py-2 text-ink">{a.action}</td>
                    <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(a.calls)}</td>
                    <td className="text-right px-3 py-2 tnum text-ink font-semibold">
                      {won(a.cost_krw)}
                    </td>
                  </tr>
                ))}
                {data.by_action.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-3 py-8 text-center text-ink3">
                      집계된 호출이 없어요.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Card>

          <section className="mt-7">
            <div className="mb-3">
              <h2 className="text-[17px] font-bold text-ink">증권 자동 정리와 사람 검토</h2>
              <p className="mt-1 text-[12px] text-ink3">
                최초 자동 정리 결과를 기준으로 집계해요. 설계사가 나중에 고친 값은 최초 정확도 숫자를 바꾸지 않아요.
              </p>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <Card className="px-4 py-3.5">
                <div className="text-[11px] text-ink3">전체 작업</div>
                <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                  {KO.format(data.insurance_review.job_count)}건
                </div>
              </Card>
              <Card className="px-4 py-3.5">
                <div className="text-[11px] text-ink3">자동 정리 시간 중앙값</div>
                <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                  {duration(data.insurance_review.processing_ms.p50)}
                </div>
              </Card>
              <Card className="px-4 py-3.5">
                <div className="text-[11px] text-ink3">사람 검토 시간 중앙값</div>
                <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                  {duration(data.insurance_review.review_ms_proxy.p50)}
                </div>
              </Card>
              <Card className="px-4 py-3.5">
                <div className="text-[11px] text-ink3">확정 전 수정 작업 비율</div>
                <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                  {percent(data.insurance_review.corrections.job_correction_rate)}
                </div>
              </Card>
            </div>

            <Card className="mt-3 p-4">
              <div className="text-[13px] font-semibold text-ink">작업 상태</div>
              {Object.keys(data.insurance_review.status_counts).length === 0 ? (
                <div className="mt-3 text-[12px] text-ink3">첫 작업이 접수되면 상태별 건수를 보여드려요.</div>
              ) : (
                <div className="mt-3 flex flex-wrap gap-2">
                  {Object.entries(data.insurance_review.status_counts).map(([key, value]) => (
                    <div key={key} className="rounded-xl bg-surface2 px-3 py-2 text-[12px] text-ink2">
                      {JOB_STATUS_LABEL[key] ?? key} <b className="ml-1 text-ink tnum">{KO.format(value)}건</b>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card className="mt-3 overflow-x-auto">
              <div className="px-4 pt-4 text-[13px] font-semibold text-ink">작업 시간</div>
              <p className="px-4 mt-0.5 text-[11px] text-ink3">
                중앙값과 상위 95% 지점을 함께 봐요. 사람 검토 시간은 최초 결과가 나온 뒤 확정할 때까지의 대용 수치예요.
              </p>
              <table className="w-full text-[12px] mt-2">
                <thead>
                  <tr className="text-ink3 border-b border-line">
                    <th className="text-left font-semibold px-4 py-2">구간</th>
                    <th className="text-right font-semibold px-2 py-2">표본</th>
                    <th className="text-right font-semibold px-2 py-2">중앙값</th>
                    <th className="text-right font-semibold px-2 py-2">상위 95%</th>
                    <th className="text-right font-semibold px-4 py-2">시간 순서 확인</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["대기 완료", data.insurance_review.queue_wait_ms],
                    ["현재 대기", data.insurance_review.current_queue_wait_ms],
                    ["자동 정리", data.insurance_review.processing_ms],
                    ["사람 검토", data.insurance_review.review_ms_proxy],
                  ].map(([label, metric]) => {
                    const item = metric as typeof data.insurance_review.processing_ms;
                    return (
                      <tr key={String(label)} className="border-b border-line/60">
                        <td className="px-4 py-2 text-ink">{label as string}</td>
                        <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(item.sample_count)}건</td>
                        <td className="text-right px-2 py-2 tnum text-ink">{duration(item.p50)}</td>
                        <td className="text-right px-2 py-2 tnum text-ink">{duration(item.p95)}</td>
                        <td className="text-right px-4 py-2 tnum text-ink2">{KO.format(item.invalid_timing_count)}건</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>

            <div className="mt-3 grid grid-cols-1 lg:grid-cols-3 gap-3">
              <Card className="p-4">
                <div className="text-[13px] font-semibold text-ink">재시도와 점유 만료</div>
                <dl className="mt-3 space-y-2 text-[12px]">
                  <div className="flex justify-between"><dt className="text-ink3">재시도 작업</dt><dd className="font-semibold text-ink tnum">{KO.format(data.insurance_review.attempts.retry_jobs)}건 ({percent(data.insurance_review.attempts.retry_job_rate)})</dd></div>
                  <div className="flex justify-between"><dt className="text-ink3">추가 시도</dt><dd className="font-semibold text-ink tnum">{KO.format(data.insurance_review.attempts.retry_attempts)}회</dd></div>
                  <div className="flex justify-between"><dt className="text-ink3">작업 점유 만료</dt><dd className="font-semibold text-ink tnum">{KO.format(data.insurance_review.leases.expired)}회</dd></div>
                </dl>
              </Card>
              <Card className="p-4">
                <div className="text-[13px] font-semibold text-ink">확정 전 수정</div>
                <dl className="mt-3 space-y-2 text-[12px]">
                  <div className="flex justify-between"><dt className="text-ink3">확정 작업</dt><dd className="font-semibold text-ink tnum">{KO.format(data.insurance_review.corrections.confirmed_jobs)}건</dd></div>
                  <div className="flex justify-between"><dt className="text-ink3">수정한 작업</dt><dd className="font-semibold text-ink tnum">{KO.format(data.insurance_review.corrections.jobs_with_edits)}건</dd></div>
                  <div className="flex justify-between"><dt className="text-ink3">수정 행동</dt><dd className="font-semibold text-ink tnum">{KO.format(data.insurance_review.corrections.edit_actions)}회</dd></div>
                </dl>
              </Card>
              <Card className="p-4">
                <div className="text-[13px] font-semibold text-ink">작업 결과 확인</div>
                <dl className="mt-3 space-y-2 text-[12px]">
                  <div className="flex justify-between"><dt className="text-ink3">AI 호출</dt><dd className="font-semibold text-ink tnum">{KO.format(data.insurance_review.failures.provider_calls)}건</dd></div>
                  <div className="flex justify-between"><dt className="text-ink3">확인할 호출</dt><dd className="font-semibold text-ink tnum">{KO.format(data.insurance_review.failures.failed_calls)}건 ({percent(data.insurance_review.failures.failure_rate)})</dd></div>
                  <div className="flex justify-between"><dt className="text-ink3">AI 담보 0건</dt><dd className="font-semibold text-ink tnum">{KO.format(data.insurance_review.failures.zero_provider_rows)}건</dd></div>
                </dl>
              </Card>
            </div>

            <Card className="mt-3 overflow-x-auto">
              <div className="px-4 pt-4 text-[13px] font-semibold text-ink">최초 자동 정리 상태</div>
              <p className="px-4 mt-0.5 text-[11px] text-ink3">
                유효한 최초 기록 {KO.format(data.insurance_review.validation.initial_metrics_sample_count)}건,
                AI 호출 전 {KO.format(data.insurance_review.validation.no_provider_job_count)}건,
                집계 대기 {KO.format(data.insurance_review.validation.pending_provider_metrics_count)}건,
                기록 형식 확인 {KO.format(data.insurance_review.validation.invalid_initial_metrics_count)}건,
                AI 담보 {KO.format(data.insurance_review.validation.provider_rows)}건,
                검토 담보 {KO.format(data.insurance_review.validation.row_count)}건 기준이에요.
              </p>
              <table className="w-full text-[12px] mt-2">
                <thead>
                  <tr className="text-ink3 border-b border-line">
                    <th className="text-left font-semibold px-4 py-2">상태</th>
                    <th className="text-right font-semibold px-2 py-2">건수</th>
                    <th className="text-right font-semibold px-4 py-2">비율</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.insurance_review.validation.state_counts).map(([key, value]) => (
                    <tr key={key} className="border-b border-line/60">
                      <td className="px-4 py-2 text-ink">{REVIEW_STATE_LABEL[key] ?? key}</td>
                      <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(value)}</td>
                      <td className="text-right px-4 py-2 tnum text-ink font-semibold">
                        {percent(data.insurance_review.validation.state_rates[key] ?? null)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>

            <Card className="mt-3 mb-3 overflow-x-auto">
              <div className="px-4 pt-4 text-[13px] font-semibold text-ink">보험사별 최초 연결 결과</div>
              <table className="w-full text-[12px] mt-2">
                <thead>
                  <tr className="text-ink3 border-b border-line">
                    <th className="text-left font-semibold px-4 py-2">보험사 코드</th>
                    <th className="text-right font-semibold px-2 py-2">작업 표본</th>
                    <th className="text-right font-semibold px-2 py-2">연결</th>
                    <th className="text-right font-semibold px-2 py-2">연결 확인</th>
                    <th className="text-right font-semibold px-4 py-2">확인 비율</th>
                  </tr>
                </thead>
                <tbody>
                  {data.insurance_review.by_carrier.map((carrier) => (
                    <tr key={carrier.carrier_code} className="border-b border-line/60">
                      <td className="px-4 py-2 text-ink tnum">{carrier.carrier_code}</td>
                      <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(carrier.sample_count)}</td>
                      <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(carrier.assigned)}</td>
                      <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(carrier.unmatched)}</td>
                      <td className="text-right px-4 py-2 tnum text-ink font-semibold">{percent(carrier.unmatched_rate)}</td>
                    </tr>
                  ))}
                  {data.insurance_review.by_carrier.length === 0 && (
                    <tr><td colSpan={5} className="px-4 py-8 text-center text-ink3">보험사 코드가 확인된 작업부터 보여드려요.</td></tr>
                  )}
                </tbody>
              </table>
            </Card>
          </section>

          <Card className="mt-3 mb-6 overflow-x-auto">
            <div className="px-3 pt-3 text-[13px] font-semibold text-ink">회사별 미매칭 담보 비율</div>
            <p className="px-3 pb-1 text-[11px] text-ink3">
              담보 매칭 실패 건수 ÷ (매칭+미매칭), 회사코드 기준 사실 수치예요.
            </p>
            <table className="w-full text-[13px] mt-1">
              <thead>
                <tr className="text-ink3 border-b border-line">
                  <th className="text-left font-semibold px-3 py-2">회사코드</th>
                  <th className="text-right font-semibold px-2 py-2">매칭</th>
                  <th className="text-right font-semibold px-2 py-2">미매칭</th>
                  <th className="text-right font-semibold px-3 py-2">미매칭율</th>
                </tr>
              </thead>
              <tbody>
                {data.by_carrier.map((c) => (
                  <tr key={c.carrier_code} className="border-b border-line/60">
                    <td className="px-3 py-2 text-ink tnum">{c.carrier_code}</td>
                    <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(c.matched)}</td>
                    <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(c.unmatched)}</td>
                    <td className="text-right px-3 py-2 tnum text-ink font-semibold">
                      {c.unmatched_rate}%
                    </td>
                  </tr>
                ))}
                {data.by_carrier.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-8 text-center text-ink3">
                      집계된 담보 매칭 데이터가 없어요.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}
