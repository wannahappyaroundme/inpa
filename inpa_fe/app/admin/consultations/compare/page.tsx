"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Card } from "@/components/ui";
import {
  adminCompareConsultation,
  type AdminComparisonResult,
  type AdminComparisonSummary,
  type AdminConsultationComparisonResponse,
} from "@/lib/adminApi";
import { ApiError } from "@/lib/api";
import { useAdminGuard } from "@/lib/useAdminGuard";

const MAX_AUDIO_BYTES = 26214400;
const APPROVED_EXTENSIONS = new Set([
  "flac",
  "mp3",
  "mp4",
  "mpeg",
  "mpga",
  "m4a",
  "ogg",
  "wav",
  "webm",
]);
const SECTION_LABELS: Array<[keyof AdminComparisonSummary, string]> = [
  ["consultation_core", "상담 핵심"],
  ["customer_priorities", "고객이 중요하게 본 내용"],
  ["items_to_confirm", "확인할 내용"],
  ["next_actions", "다음 할 일"],
];
const EVALUATION_LABELS = [
  "빠진 내용",
  "대화에 없는데 만든 내용",
  "금액·날짜 오류",
  "화자 구분 오류",
  "바로 메모로 사용할 수 있음",
];
const FINAL_CHOICES = ["A 우세", "B 우세", "동률", "판단 보류"] as const;
const SAFE_COMPARISON_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  CONSULTATION_COMPARISON_CLOSED:
    "내부 비교 설정을 켜면 바로 확인할 수 있어요.",
  CONSULTATION_COMPARISON_NOT_READY:
    "두 AI 연결 설정을 마치면 비교를 시작할 수 있어요.",
  SYNTHETIC_CONFIRMATION_REQUIRED:
    "가상 녹음 확인을 선택하면 바로 비교할 수 있어요.",
  AUDIO_EMPTY:
    "내용이 담긴 음성 파일을 선택하면 바로 비교할 수 있어요.",
  AUDIO_FORMAT_UNSUPPORTED:
    "지원하는 음성 파일을 선택하면 바로 비교할 수 있어요.",
  AUDIO_INVALID:
    "재생되는 음성 파일을 선택하면 바로 비교할 수 있어요.",
  AUDIO_ONLY_REQUIRED:
    "영상 없이 음성만 담긴 파일을 선택하면 바로 비교할 수 있어요.",
  AUDIO_TOO_LARGE:
    "25MB 이하 음성 파일을 선택하면 바로 비교할 수 있어요.",
  AUDIO_TOO_LONG:
    "5분 이하 가상 상담 음성을 선택하면 바로 비교할 수 있어요.",
};
const GENERIC_COMPARISON_ERROR_MESSAGE =
  "음성 파일은 그대로 두었어요. 연결 상태를 확인한 뒤 비교 시작을 다시 눌러 주세요.";

type FinalChoice = (typeof FINAL_CHOICES)[number];
type EvaluationState = Record<"A" | "B", boolean[]>;

function emptyEvaluation(): EvaluationState {
  return {
    A: EVALUATION_LABELS.map(() => false),
    B: EVALUATION_LABELS.map(() => false),
  };
}

function fileExtension(file: File): string {
  return file.name.split(".").pop()?.toLowerCase() ?? "";
}

function fileSizeLabel(file: File): string {
  if (file.size < 1048576) {
    return `${Math.max(1, Math.ceil(file.size / 1024))}KB`;
  }
  return `${(file.size / 1048576).toFixed(1)}MB`;
}

function SummarySections({
  summary,
  slot,
}: {
  summary: AdminComparisonSummary;
  slot: "A" | "B";
}) {
  return (
    <div className="mt-4 space-y-4">
      {SECTION_LABELS.map(([key, label]) => (
        <section key={key} aria-labelledby={`summary-${slot}-${key}`}>
          <h3
            id={`summary-${slot}-${key}`}
            className="text-[13px] font-extrabold text-ink"
          >
            {label}
          </h3>
          {summary[key].length > 0 ? (
            <ul className="mt-2 space-y-1.5 text-[13px] leading-6 text-ink2">
              {summary[key].map((item, index) => (
                <li key={`${key}-${index}`} className="flex gap-2">
                  <span aria-hidden className="text-brand">•</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-[13px] leading-6 text-ink3">
              확인된 내용 없음
            </p>
          )}
        </section>
      ))}
    </div>
  );
}

function ResultCard({
  result,
  evaluation,
  onEvaluationChange,
  reveal,
}: {
  result: AdminComparisonResult;
  evaluation: boolean[];
  onEvaluationChange: (index: number, checked: boolean) => void;
  reveal: boolean;
}) {
  return (
    <Card
      role="article"
      aria-label={`결과 ${result.slot}`}
      className="p-5 sm:p-6"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[18px] font-extrabold text-ink">
          결과 {result.slot}
        </h2>
        <span className="rounded-full bg-brand-soft px-3 py-1 text-[11px] font-bold text-brand">
          블라인드 평가
        </span>
      </div>

      {result.status === "success" && result.summary ? (
        <SummarySections summary={result.summary} slot={result.slot} />
      ) : (
        <div className="mt-4 rounded-xl bg-canvas p-4">
          <p className="text-[13px] font-bold text-ink">
            한쪽 결과를 다시 확인해 주세요.
          </p>
          <p className="mt-1 text-[12px] leading-5 text-ink3">
            성공한 결과와 공통 전사문을 평가해 주세요.
          </p>
        </div>
      )}

      {result.status === "success" && result.summary && (
        <fieldset className="mt-6 border-t border-line pt-5">
          <legend className="text-[13px] font-extrabold text-ink">
            결과 {result.slot} 평가
          </legend>
          <div className="mt-3 space-y-2.5">
            {EVALUATION_LABELS.map((label, index) => (
              <label
                key={label}
                className="flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border border-line px-3 py-2 text-[13px] text-ink2"
              >
                <input
                  type="checkbox"
                  checked={evaluation[index]}
                  onChange={(event) =>
                    onEvaluationChange(index, event.target.checked)
                  }
                  className="h-4 w-4 accent-[var(--brand)]"
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {reveal && (
        <dl className="mt-5 grid gap-2 rounded-xl bg-canvas p-4 text-[12px] sm:grid-cols-2">
          <div>
            <dt className="font-semibold text-ink3">공급자</dt>
            <dd className="mt-1 font-bold text-ink">{result.provider}</dd>
          </div>
          <div>
            <dt className="font-semibold text-ink3">모델</dt>
            <dd className="mt-1 break-all font-bold text-ink">
              {result.model || "-"}
            </dd>
          </div>
          <div>
            <dt className="font-semibold text-ink3">처리 시간</dt>
            <dd className="mt-1 font-bold text-ink">
              {result.latency_ms.toLocaleString("ko-KR")}ms
            </dd>
          </div>
          <div>
            <dt className="font-semibold text-ink3">입력 / 출력 토큰</dt>
            <dd className="mt-1 font-bold text-ink">
              {result.input_tokens.toLocaleString("ko-KR")} /{" "}
              {result.output_tokens.toLocaleString("ko-KR")}
            </dd>
          </div>
          {result.status !== "success" && (
            <div className="sm:col-span-2">
              <dt className="font-semibold text-ink3">상태 코드</dt>
              <dd className="mt-1 break-all font-bold text-ink">
                {result.error_code || result.status}
              </dd>
            </div>
          )}
        </dl>
      )}
    </Card>
  );
}

export default function AdminConsultationComparisonPage() {
  const ready = useAdminGuard();
  const [audio, setAudio] = useState<File | null>(null);
  const [syntheticConfirmed, setSyntheticConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState(0);
  const [response, setResponse] =
    useState<AdminConsultationComparisonResponse | null>(null);
  const [evaluation, setEvaluation] =
    useState<EvaluationState>(emptyEvaluation);
  const [finalChoice, setFinalChoice] = useState<FinalChoice | null>(null);
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submittingRef = useRef(false);

  useEffect(() => {
    if (!loading) return;
    const summaryTimer = window.setTimeout(() => setLoadingStage(1), 8000);
    const finishingTimer = window.setTimeout(() => setLoadingStage(2), 25000);
    return () => {
      window.clearTimeout(summaryTimer);
      window.clearTimeout(finishingTimer);
    };
  }, [loading]);

  function resetComparisonState() {
    setResponse(null);
    setEvaluation(emptyEvaluation());
    setFinalChoice(null);
    setReveal(false);
    setError(null);
    setLoadingStage(0);
  }

  function handleAudioChange(event: React.ChangeEvent<HTMLInputElement>) {
    setAudio(event.target.files?.[0] ?? null);
    setSyntheticConfirmed(false);
    resetComparisonState();
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submittingRef.current) return;
    if (!audio) {
      setError("가상 상담 음성 파일을 선택해 주세요.");
      return;
    }
    if (!APPROVED_EXTENSIONS.has(fileExtension(audio))) {
      setError(
        "지원하는 음성 파일을 선택해 주세요. (flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm)",
      );
      return;
    }
    if (audio.size > MAX_AUDIO_BYTES) {
      setError("25MB 이하 음성 파일을 선택해 주세요.");
      return;
    }
    if (!syntheticConfirmed) {
      setError("가상 녹음 확인을 선택해 주세요.");
      return;
    }

    submittingRef.current = true;
    setLoading(true);
    setLoadingStage(0);
    setError(null);
    setResponse(null);
    setEvaluation(emptyEvaluation());
    setFinalChoice(null);
    setReveal(false);
    try {
      setResponse(await adminCompareConsultation(audio, true));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? SAFE_COMPARISON_ERROR_MESSAGES[caught.code] ??
              GENERIC_COMPARISON_ERROR_MESSAGE
          : GENERIC_COMPARISON_ERROR_MESSAGE,
      );
    } finally {
      submittingRef.current = false;
      setLoading(false);
    }
  }

  function setSlotEvaluation(
    slot: "A" | "B",
    index: number,
    checked: boolean,
  ) {
    setEvaluation((current) => ({
      ...current,
      [slot]: current[slot].map((value, itemIndex) =>
        itemIndex === index ? checked : value),
    }));
  }

  if (!ready) return null;

  const loadingMessages = [
    "음성을 글로 바꾸고 있어요",
    "두 가지 요약을 만들고 있어요",
    "결과를 정리하고 있어요. 화면을 그대로 두면 이어집니다.",
  ];
  const approvedAudio = audio
    ? APPROVED_EXTENSIONS.has(fileExtension(audio)) &&
      audio.size <= MAX_AUDIO_BYTES
    : false;
  const successfulResults =
    response?.results.filter((result) => result.status === "success") ?? [];
  const availableFinalChoices: readonly FinalChoice[] =
    successfulResults.length === 2
      ? FINAL_CHOICES
      : successfulResults.length === 1
        ? [
            `${successfulResults[0].slot} 우세` as FinalChoice,
            "판단 보류",
          ]
        : [];

  return (
    <div className="max-w-6xl">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="inline-flex rounded-full bg-brand-soft px-3 py-1 text-[11px] font-bold text-brand">
            내부 검토용
          </p>
          <h1 className="mt-1 text-[22px] font-extrabold text-ink">
            상담 AI 비교
          </h1>
          <p className="mt-2 max-w-2xl text-[13px] leading-6 text-ink3">
            가상 상담으로 요약 결과를 나란히 확인합니다.
          </p>
        </div>
        <Link
          href="/admin/consultations"
          className="min-h-11 rounded-xl border border-line bg-surface px-4 py-3 text-[13px] font-bold text-brand"
        >
          상담 녹음 운영으로
        </Link>
      </div>

      <Card className="mt-6 p-5 sm:p-6">
        <form onSubmit={submit}>
          <label
            htmlFor="comparison-audio"
            className="text-[13px] font-extrabold text-ink"
          >
            가상 상담 음성
          </label>
          <p
            id="comparison-audio-note"
            className="mt-1 text-[12px] leading-5 text-ink3"
          >
            25MB 이하 음성 파일을 선택해 주세요.
          </p>
          <p
            id="comparison-storage-note"
            className="mt-1 text-[12px] leading-5 text-ink3"
          >
            이 화면의 음성과 결과는 고객 메모에 저장되지 않습니다.
          </p>
          <input
            id="comparison-audio"
            type="file"
            accept=".flac,.mp3,.mp4,.mpeg,.mpga,.m4a,.ogg,.wav,.webm"
            aria-describedby="comparison-audio-note comparison-storage-note"
            disabled={loading}
            onChange={handleAudioChange}
            className="mt-3 min-h-11 w-full rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] text-ink file:mr-3 file:rounded-lg file:border-0 file:bg-brand-soft file:px-3 file:py-2 file:font-bold file:text-brand"
          />
          {audio && (
            <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-canvas px-3 py-2 text-[12px]">
              <span className="break-all font-bold text-ink">{audio.name}</span>
              <span className="text-ink3">{fileSizeLabel(audio)}</span>
              <span
                className={
                  approvedAudio
                    ? "font-semibold text-success-ink"
                    : "font-semibold text-warn-ink"
                }
              >
                {approvedAudio
                  ? "사용할 수 있는 음성 파일"
                  : "다른 음성 파일을 선택해 주세요"}
              </span>
            </div>
          )}

          <label className="mt-4 flex min-h-11 cursor-pointer items-center gap-3 rounded-xl bg-canvas px-4 py-3 text-[13px] font-semibold text-ink2">
            <input
              type="checkbox"
              aria-label="가상 녹음 확인"
              checked={syntheticConfirmed}
              disabled={loading}
              onChange={(event) => {
                setSyntheticConfirmed(event.target.checked);
                setError(null);
              }}
              className="h-4 w-4 accent-[var(--brand)]"
            />
            <span>
              <span className="block text-ink">
                실제 고객 정보가 없는 가상 녹음입니다
              </span>
              <span className="mt-0.5 block text-[12px] font-normal text-ink3">
                실제 고객의 이름, 연락처, 상담 내용이 없는 음성입니다.
              </span>
            </span>
          </label>

          {error && (
            <p
              role="alert"
              className="mt-4 rounded-xl bg-neg-soft px-4 py-3 text-[13px] font-semibold text-danger-ink"
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="mt-4 min-h-11 rounded-xl bg-brand px-5 text-[13px] font-bold text-white disabled:cursor-wait disabled:opacity-60"
          >
            {loading ? "비교 진행 중" : "비교 시작"}
          </button>
          {loading && (
            <p
              aria-live="polite"
              className="mt-3 text-[13px] font-semibold text-brand"
            >
              {loadingMessages[loadingStage]}
            </p>
          )}
        </form>
      </Card>

      {response && (
        <>
          <details className="mt-6 rounded-2xl border border-line bg-surface px-5 py-4 shadow-card">
            <summary className="min-h-11 cursor-pointer py-3 text-[14px] font-extrabold text-ink">
              공통 전사문 보기
            </summary>
            <div className="border-t border-line pt-4">
              {response.transcript.segments.map((segment, index) => (
                <p
                  key={`${segment.start_seconds}-${index}`}
                  className="mb-3 text-[13px] leading-6 text-ink2"
                >
                  <strong className="mr-2 text-ink">{segment.speaker}</strong>
                  {segment.text}
                </p>
              ))}
            </div>
          </details>

          {successfulResults.length === 0 ? (
            <Card
              role="alert"
              aria-labelledby="comparison-all-failed-title"
              className="mt-4 p-5 sm:p-6"
            >
              <h2
                id="comparison-all-failed-title"
                className="text-[16px] font-extrabold text-ink"
              >
                두 결과를 확인하지 못했어요
              </h2>
              <p className="mt-2 text-[13px] leading-6 text-ink3">
                선택한 음성은 그대로 두었어요. 비교 시작을 다시 눌러 주세요.
              </p>
            </Card>
          ) : (
            <>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                {response.results.map((result) => (
                  <ResultCard
                    key={result.slot}
                    result={result}
                    evaluation={evaluation[result.slot]}
                    onEvaluationChange={(index, checked) =>
                      setSlotEvaluation(result.slot, index, checked)
                    }
                    reveal={reveal}
                  />
                ))}
              </div>

              <Card className="mt-4 p-5 sm:p-6">
                <fieldset>
                  <legend className="text-[15px] font-extrabold text-ink">
                    최종 선택
                  </legend>
                  <p className="mt-1 text-[12px] leading-5 text-ink3">
                    {successfulResults.length === 1
                      ? "성공한 결과를 평가한 뒤 가장 가까운 선택을 남겨 주세요."
                      : "두 결과를 평가한 뒤 가장 가까운 선택을 남겨 주세요."}
                  </p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                    {availableFinalChoices.map((choice) => (
                      <label
                        key={choice}
                        className="flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border border-line px-3 py-2 text-[13px] font-bold text-ink2"
                      >
                        <input
                          type="radio"
                          name="final-choice"
                          checked={finalChoice === choice}
                          onChange={() => {
                            setFinalChoice(choice);
                            setReveal(false);
                          }}
                          className="h-4 w-4 accent-[var(--brand)]"
                        />
                        {choice}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <button
                  type="button"
                  disabled={!finalChoice}
                  onClick={() => setReveal(true)}
                  className="mt-4 min-h-11 rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-brand disabled:cursor-not-allowed disabled:opacity-50"
                >
                  모델명 보기
                </button>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
