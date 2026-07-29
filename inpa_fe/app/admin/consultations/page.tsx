"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Card } from "@/components/ui";
import {
  adminAddConsultationPilot,
  adminGetConsultationSettings,
  adminRemoveConsultationPilot,
  adminUpdateConsultationPilot,
  adminUpdateConsultationSettings,
  type AdminConsultationRun,
  type AdminConsultationResponse,
} from "@/lib/adminApi";
import { useAdminGuard } from "@/lib/useAdminGuard";

function CountCard({
  label,
  value,
  note,
}: {
  label: string;
  value: number | null;
  note: string;
}) {
  return (
    <Card className="p-4">
      <p className="text-[12px] font-semibold text-ink3">{label}</p>
      <p className="mt-2 text-[26px] font-extrabold text-ink">
        {value === null ? "-" : value.toLocaleString("ko-KR")}
      </p>
      <p className="mt-1 text-[11px] leading-5 text-ink3">{note}</p>
    </Card>
  );
}

function providerLabel(provider?: string) {
  if (provider === "openai") return "OpenAI";
  if (provider === "anthropic") return "Anthropic";
  if (provider === "clova") return "CLOVA";
  return provider || "-";
}

function SummaryRunTable({ runs }: { runs: AdminConsultationRun[] }) {
  return (
    <div className="mt-3 overflow-x-auto rounded-2xl bg-surface">
      <table className="min-w-full text-left text-[12px] text-ink2">
        <thead className="border-b border-line text-ink3">
          <tr>
            <th className="px-3 py-3 font-semibold">작업 ID</th>
            <th className="px-3 py-3 font-semibold">음성 변환</th>
            <th className="px-3 py-3 font-semibold">요약 / 모델</th>
            <th className="px-3 py-3 font-semibold">처리 시간</th>
            <th className="px-3 py-3 font-semibold">입력/출력 토큰</th>
            <th className="px-3 py-3 font-semibold">비용 추정</th>
            <th className="px-3 py-3 font-semibold">결과</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {runs.map((run) => (
            <tr key={run.id}>
              <td className="px-3 py-3 font-mono">{run.id.slice(0, 8)}</td>
              <td className="px-3 py-3">{providerLabel(run.stt_provider)}</td>
              <td className="px-3 py-3">
                {providerLabel(run.summary_provider)} / {run.summary_model || "-"}
              </td>
              <td className="px-3 py-3">
                {(run.processing_seconds ?? 0).toLocaleString("ko-KR")}초
              </td>
              <td className="px-3 py-3">{run.input_tokens}/{run.output_tokens}</td>
              <td className="px-3 py-3">
                {run.estimated_cost_krw.toLocaleString("ko-KR")}원
              </td>
              <td className="px-3 py-3">
                {run.error_code || run.outcome || run.status}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AdminConsultationsPage() {
  const ready = useAdminGuard();
  const [data, setData] = useState<AdminConsultationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [email, setEmail] = useState("");
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await adminGetConsultationSettings());
    } catch {
      setError("상담 녹음 운영 상태를 다시 불러와 주세요.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (ready) void load();
  }, [load, ready]);

  async function toggleRecording() {
    if (!data || saving) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const next = !data.settings.recording_enabled;
      const updated = await adminUpdateConsultationSettings({
        recording_enabled: next,
      });
      setData(updated);
      setMessage(next ? "녹음 기능을 켰어요." : "새 녹음 시작을 잠시 멈췄어요.");
    } catch {
      setError("환경 설정과 저장공간 연결을 확인한 뒤 다시 눌러 주세요.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleSummary() {
    if (!data || saving) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const next = !data.settings.ai_summary_enabled;
      const updated = await adminUpdateConsultationSettings({
        ai_summary_enabled: next,
      });
      setData(updated);
      setMessage(next ? "AI 요약 기능을 켰어요." : "새 AI 요약 시작을 잠시 멈췄어요.");
    } catch {
      setError("음성 변환과 AI 연결 설정을 확인한 뒤 다시 눌러 주세요.");
    } finally {
      setSaving(false);
    }
  }

  async function saveCostLimits() {
    if (!data || saving) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const updated = await adminUpdateConsultationSettings({
        daily_ai_cost_limit_krw: data.settings.daily_ai_cost_limit_krw,
        monthly_ai_cost_limit_krw: data.settings.monthly_ai_cost_limit_krw,
      });
      setData(updated);
      setMessage("AI 비용 상한을 저장했어요.");
    } catch {
      setError("하루 상한과 한 달 상한을 확인한 뒤 다시 저장해 주세요.");
    } finally {
      setSaving(false);
    }
  }

  async function addPilot(event: React.FormEvent) {
    event.preventDefault();
    const safeEmail = email.trim();
    if (!safeEmail || adding) return;
    setAdding(true);
    setMessage(null);
    setError(null);
    try {
      const pilot = await adminAddConsultationPilot({
        email: safeEmail,
        recording_allowed: true,
        summary_allowed: false,
      });
      setData((current) => current ? {
        ...current,
        pilot_users: [
          ...current.pilot_users.filter((row) => row.user_id !== pilot.user_id),
          pilot,
        ].sort((a, b) => a.email.localeCompare(b.email)),
      } : current);
      setEmail("");
      setMessage("파일럿 계정을 추가했어요.");
    } catch {
      setError("가입된 설계사 이메일을 확인한 뒤 다시 추가해 주세요.");
    } finally {
      setAdding(false);
    }
  }

  if (!ready) return null;
  if (loading && !data) {
    return (
      <div className="max-w-5xl" aria-label="상담 녹음 운영 상태 불러오는 중">
        <div className="h-8 w-48 animate-pulse rounded-lg bg-line" />
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((item) => (
            <div key={item} className="h-32 animate-pulse rounded-2xl bg-line" />
          ))}
        </div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="max-w-xl rounded-2xl bg-surface p-6">
        <h1 className="text-[22px] font-extrabold text-ink">상담 녹음 운영</h1>
        <p role="alert" className="mt-3 text-[13px] text-ink2">{error}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-4 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white"
        >
          운영 상태 다시 불러오기
        </button>
      </div>
    );
  }

  const status = data.status;
  const retentionDays = (
    Number.isInteger(data.retention_days) && data.retention_days > 0
      ? data.retention_days
      : null
  );
  return (
    <div className="max-w-5xl">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-extrabold text-ink">상담 녹음 운영</h1>
          <p className="mt-2 text-[13px] leading-6 text-ink3">
            원음과 고객 내용은 열지 않고, 업로드와 삭제 상태만 확인합니다.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/admin/consultations/compare"
            className="min-h-11 rounded-xl border border-line bg-surface px-4 py-3 text-[13px] font-bold text-brand"
          >
            상담 AI 비교
          </Link>
          <button
            type="button"
            disabled={saving || (!data.environment_gate_open && !data.settings.recording_enabled)}
            onClick={() => void toggleRecording()}
            className="min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white disabled:opacity-50"
          >
            {saving
              ? "저장 중"
              : data.settings.recording_enabled
                ? "새 녹음 시작 멈추기"
                : "녹음 기능 켜기"}
          </button>
          <button
            type="button"
            disabled={saving || (!data.ai_environment_gate_open && !data.settings.ai_summary_enabled)}
            onClick={() => void toggleSummary()}
            className="min-h-11 rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-brand disabled:opacity-50"
          >
            {saving
              ? "저장 중"
              : data.settings.ai_summary_enabled
                ? "새 AI 요약 시작 멈추기"
                : "AI 요약 기능 켜기"}
          </button>
        </div>
      </div>

      {!data.environment_gate_open && (
        <p className="mt-4 rounded-2xl bg-surface p-4 text-[13px] leading-6 text-ink2">
          서버 환경 설정과 저장공간 연결을 마치면 여기서 녹음 기능을 켤 수 있어요.
        </p>
      )}
      {!data.ai_environment_gate_open && (
        <p className="mt-3 rounded-2xl bg-surface p-4 text-[13px] leading-6 text-ink2">
          음성 변환과 AI 연결 검증을 마치면 여기서 요약 기능을 켤 수 있어요.
        </p>
      )}
      {message && <p aria-live="polite" className="mt-4 text-[13px] text-success-ink">{message}</p>}
      {error && <p role="alert" className="mt-4 text-[13px] text-danger-ink">{error}</p>}
      {retentionDays === null && (
        <div role="alert" className="mt-4 rounded-2xl bg-surface p-4">
          <p className="text-[13px] leading-6 text-ink2">
            서버 보관 기간을 다시 불러오면 자동 삭제 일정을 확인할 수 있어요.
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-2 min-h-11 rounded-xl border border-line px-3 text-[12px] font-bold text-brand"
          >
            보관 기간 다시 불러오기
          </button>
        </div>
      )}

      <section className="mt-6" aria-labelledby="consultation-status-title">
        <h2 id="consultation-status-title" className="text-[16px] font-extrabold text-ink">
          원본 보관 상태
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <CountCard label="진행 중 업로드" value={status.active_upload_count} note="분할 업로드를 이어가는 녹음" />
          <CountCard
            label="보관 중 원본"
            value={status.ready_source_count}
            note={retentionDays === null
              ? "서버 보관 기간 확인 후 자동 삭제 대상"
              : `${retentionDays}일 이내 자동 삭제 대상`}
          />
          <CountCard label="삭제 완료" value={status.deleted_count} note="원본 부재 확인까지 마친 건" />
          <CountCard label="만료 시각 지난 원본" value={status.overdue_source_count} note="삭제 작업이 우선 처리할 건" />
          <CountCard label="삭제 재확인" value={status.delete_failure_count} note="다음 삭제 작업에서 다시 확인할 건" />
          <CountCard label="연결 없는 저장 파일" value={status.orphan_object_count} note={status.storage_audit_available ? "DB 연결 없이 저장공간에 남은 파일" : "저장공간 점검을 실행하면 표시됩니다"} />
          <CountCard label="찾을 수 없는 원본" value={status.missing_object_count} note={status.storage_audit_available ? "DB에는 있으나 저장공간에서 찾지 못한 파일" : "저장공간 점검을 실행하면 표시됩니다"} />
        </div>
      </section>

      <section className="mt-8" aria-labelledby="summary-status-title">
        <h2 id="summary-status-title" className="text-[16px] font-extrabold text-ink">
          AI 요약 처리 상태
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <CountCard label="대기 중" value={status.summary_queued_count} note="처리 순서를 기다리는 건" />
          <CountCard label="정리 중" value={status.summary_processing_count} note="음성 변환 또는 요약 중인 건" />
          <CountCard label="메모 생성 완료" value={status.summary_success_count} note="편집 가능한 메모가 생성된 건" />
          <CountCard label="직접 메모 안내" value={status.summary_failed_count} note="직접 작성으로 이어간 건" />
          <CountCard label="중복 방지 종료" value={status.summary_ambiguous_count} note="공급자 접수 여부가 불명확한 건" />
          <CountCard label="변경 사항 반영 종료" value={status.summary_cancelled_count} note="동의 철회 또는 원본 삭제를 반영한 건" />
          <CountCard label="음성 처리 분" value={status.summary_processing_minutes} note="외부 처리를 시작한 올림 분수 합계" />
          <CountCard label="AI 비용 추정(원)" value={status.summary_estimated_cost_krw} note="실제 청구서와 다를 수 있는 운영 추정치" />
          <CountCard label="완료 중간값(초)" value={status.summary_p50_seconds} note="완료 건 처리 시간의 중간값" />
          <CountCard label="완료 95% 지점(초)" value={status.summary_p95_seconds} note="완료 건 처리 시간의 95% 지점" />
        </div>

        <div className="mt-4 rounded-2xl bg-surface p-4">
          <h3 className="text-[14px] font-extrabold text-ink">AI 비용 상한</h3>
          <p className="mt-1 text-[12px] leading-5 text-ink3">
            저장된 토큰 비용 추정치가 상한에 닿으면 새 요약 요청을 잠시 멈춥니다.
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-[12px] font-semibold text-ink2">
              하루 상한(원)
              <input
                type="number"
                min={1000}
                value={data.settings.daily_ai_cost_limit_krw}
                onChange={(event) => setData((current) => current ? {
                  ...current,
                  settings: {
                    ...current.settings,
                    daily_ai_cost_limit_krw: Number(event.target.value),
                  },
                } : current)}
                className="mt-1 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px] text-ink"
              />
            </label>
            <label className="text-[12px] font-semibold text-ink2">
              한 달 상한(원)
              <input
                type="number"
                min={10000}
                value={data.settings.monthly_ai_cost_limit_krw}
                onChange={(event) => setData((current) => current ? {
                  ...current,
                  settings: {
                    ...current.settings,
                    monthly_ai_cost_limit_krw: Number(event.target.value),
                  },
                } : current)}
                className="mt-1 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px] text-ink"
              />
            </label>
          </div>
          <button
            type="button"
            disabled={saving}
            onClick={() => void saveCostLimits()}
            className="mt-3 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white disabled:opacity-50"
          >
            비용 상한 저장
          </button>
        </div>

        {status.recent_summary_runs.length > 0 && (
          <SummaryRunTable runs={status.recent_summary_runs} />
        )}

        {(status.pilot_recent_summary_runs?.length ?? 0) > 0 && (
          <div className="mt-6">
            <h3 className="text-[14px] font-extrabold text-ink">
              시연 계정 파일럿 확인
            </h3>
            <p className="mt-1 text-[12px] leading-5 text-ink3">
              실제 호출 시간과 비용은 확인하되, 서비스 운영 합계에는 포함하지 않습니다.
            </p>
            <SummaryRunTable runs={status.pilot_recent_summary_runs ?? []} />
          </div>
        )}
      </section>

      <section className="mt-8" aria-labelledby="pilot-title">
        <h2 id="pilot-title" className="text-[16px] font-extrabold text-ink">파일럿 계정</h2>
        <p className="mt-1 text-[12px] text-ink3">
          먼저 확인할 설계사만 추가해 운영 범위를 좁힙니다.
        </p>
        <form onSubmit={(event) => void addPilot(event)} className="mt-3 flex flex-col gap-2 sm:flex-row">
          <label htmlFor="consultation-pilot-email" className="sr-only">설계사 이메일</label>
          <input
            id="consultation-pilot-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="가입된 설계사 이메일"
            className="min-h-11 flex-1 rounded-xl border border-line bg-surface px-3 text-[13px] text-ink"
          />
          <button type="submit" disabled={adding} className="min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white disabled:opacity-50">
            {adding ? "추가 중" : "파일럿 추가"}
          </button>
        </form>

        {data.pilot_users.length === 0 ? (
          <div className="mt-3 rounded-2xl bg-surface p-5 text-[13px] leading-6 text-ink3">
            파일럿 설계사를 추가하면 해당 계정부터 녹음 흐름을 확인할 수 있어요.
          </div>
        ) : (
          <div className="mt-3 divide-y divide-line overflow-hidden rounded-2xl bg-surface">
            {data.pilot_users.map((pilot) => (
              <div key={pilot.user_id} className="flex flex-wrap items-center gap-3 p-4">
                <p className="min-w-0 flex-1 break-all text-[13px] font-bold text-ink">{pilot.email}</p>
                <button
                  type="button"
                  onClick={async () => {
                    const changed = await adminUpdateConsultationPilot(pilot.user_id, {
                      recording_allowed: !pilot.recording_allowed,
                    });
                    setData((current) => current ? {
                      ...current,
                      pilot_users: current.pilot_users.map((row) => row.user_id === changed.user_id ? changed : row),
                    } : current);
                  }}
                  className="min-h-11 rounded-xl border border-line px-3 text-[12px] font-bold text-ink2"
                >
                  {pilot.recording_allowed ? "녹음 허용 중" : "녹음 허용"}
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    const changed = await adminUpdateConsultationPilot(pilot.user_id, {
                      summary_allowed: !pilot.summary_allowed,
                    });
                    setData((current) => current ? {
                      ...current,
                      pilot_users: current.pilot_users.map((row) => row.user_id === changed.user_id ? changed : row),
                    } : current);
                  }}
                  className="min-h-11 rounded-xl border border-line px-3 text-[12px] font-bold text-ink2"
                >
                  {pilot.summary_allowed ? "AI 요약 허용 중" : "AI 요약 허용"}
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    await adminRemoveConsultationPilot(pilot.user_id);
                    setData((current) => current ? {
                      ...current,
                      pilot_users: current.pilot_users.filter((row) => row.user_id !== pilot.user_id),
                    } : current);
                  }}
                  className="min-h-11 rounded-xl px-3 text-[12px] font-bold text-danger-ink"
                >
                  파일럿에서 빼기
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
