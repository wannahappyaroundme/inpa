"use client";

// ════════════════════════════════════════════════════════════════════════════
// 증권 OCR 업로드 — 공유 컴포넌트 (/analysis 와 /customer/[id] 분석 탭 공유)
// 업로드 흐름: idle → uploading → 412(동의 필요) → consent_modal → uploading → success/error
//
// ⚠️ 컴플라이언스: ConsentModal 은 법적 국외이전 동의 흐름. 자동 동의 금지.
//    사용자가 직접 확인 후 버튼 클릭해야 함 (정직성 레드라인).
//    AI 면책 문구 고정: "처리 결과는 AI 초안이며, 최종 확인과 책임은 설계사".
// ════════════════════════════════════════════════════════════════════════════

import { useState, useCallback } from "react";
import {
  uploadInsuranceOcr,
  createConsentLog,
  ApiError,
} from "@/lib/api";

export type OcrPhase =
  | "idle"
  | "uploading"
  | "consent_required"
  | "success"
  | "error";

/**
 * OCR 업로드 상태 + 액션을 한곳에 모은 훅.
 * 페이지(분석/고객상세)는 이 훅으로 상태를 받아 버튼·배너·모달을 조립한다.
 *
 * @param onUploaded 업로드 성공 시 콜백(예: 히트맵 새로고침). selectedId 인자 전달.
 */
export function useOcrUpload(onUploaded?: (customerId: number) => void) {
  const [phase, setPhase] = useState<OcrPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [consentLoading, setConsentLoading] = useState(false);

  const runUpload = useCallback(
    async (customerId: number, file: File) => {
      setPhase("uploading");
      setError(null);
      try {
        await uploadInsuranceOcr(customerId, file);
        setPhase("success");
        onUploaded?.(customerId);
        setTimeout(() => setPhase("idle"), 2000);
      } catch (e: unknown) {
        if (e instanceof ApiError && e.status === 412) {
          // 국외이전 동의 필요 → 동의 모달 노출
          setPhase("consent_required");
        } else {
          const msg =
            e instanceof Error ? e.message : "증권 업로드 중 오류가 발생했어요.";
          setError(msg);
          setPhase("error");
        }
      }
    },
    [onUploaded]
  );

  /** 파일 input change 핸들러 */
  const onFileChange = useCallback(
    async (
      e: React.ChangeEvent<HTMLInputElement>,
      customerId: number | null
    ) => {
      const file = e.target.files?.[0];
      if (!file || customerId === null) return;
      e.target.value = ""; // 동일 파일 재선택 허용
      setPendingFile(file);
      await runUpload(customerId, file);
    },
    [runUpload]
  );

  /** 동의 확인 후 재업로드 (사용자가 직접 버튼 클릭) */
  const agreeAndRetry = useCallback(
    async (customerId: number | null) => {
      if (customerId === null || pendingFile === null) return;
      setConsentLoading(true);
      try {
        await createConsentLog(customerId, {
          scope: "overseas_medical",
          purpose:
            "증권 OCR 분석(Claude API, 미국 소재) — 보험정보 국외이전",
          doc_version: "1.0",
        });
        setPhase("uploading");
        await runUpload(customerId, pendingFile);
      } catch {
        setError("동의 처리 중 오류가 발생했어요. 다시 시도해 주세요.");
        setPhase("error");
      } finally {
        setConsentLoading(false);
      }
    },
    [pendingFile, runUpload]
  );

  const dismissConsent = useCallback(() => {
    setPhase("idle");
    setPendingFile(null);
    setError(null);
  }, []);

  const clearError = useCallback(() => {
    setPhase("idle");
    setError(null);
  }, []);

  return {
    phase,
    error,
    consentLoading,
    onFileChange,
    agreeAndRetry,
    dismissConsent,
    clearError,
  };
}

// ── OcrUploadButton ── hidden file input + label 패턴 ─────────────────────────

export function OcrUploadButton({
  customerId,
  phase,
  onFileChange,
  inputId = "ocr-file-input",
  label = "증권 등록",
}: {
  customerId: number | null;
  phase: OcrPhase;
  onFileChange: (
    e: React.ChangeEvent<HTMLInputElement>,
    customerId: number | null
  ) => void;
  inputId?: string;
  label?: string;
}) {
  const disabled =
    customerId === null || phase === "uploading" || phase === "consent_required";

  return (
    <>
      <input
        id={inputId}
        type="file"
        accept=".pdf"
        className="sr-only"
        disabled={disabled}
        onChange={(e) => onFileChange(e, customerId)}
        aria-label="증권 PDF 업로드"
      />
      <label
        htmlFor={inputId}
        className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-[13px] font-semibold transition cursor-pointer select-none ${
          disabled
            ? "border-line text-ink3 bg-surface2 cursor-not-allowed"
            : "border-brand text-brand bg-surface hover:bg-accent-tint active:scale-[0.98]"
        }`}
        aria-disabled={disabled}
      >
        {phase === "uploading" ? (
          <>
            <span className="inline-block w-3.5 h-3.5 rounded-full border-2 border-brand border-t-transparent animate-spin" />
            분석 중…
          </>
        ) : phase === "success" ? (
          "완료!"
        ) : (
          label
        )}
      </label>
    </>
  );
}

// ── OcrStatusBanner ── 오류 배너 ─────────────────────────────────────────────

export function OcrStatusBanner({
  phase,
  errorMsg,
  onDismiss,
}: {
  phase: OcrPhase;
  errorMsg: string | null;
  onDismiss: () => void;
}) {
  if (phase !== "error") return null;
  return (
    <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-4 py-3">
      <span className="mt-0.5 text-[15px]" aria-hidden>
        !
      </span>
      <p className="flex-1 text-[13px] text-red-700 leading-5">
        {errorMsg ?? "증권 업로드 중 오류가 발생했어요. 다시 시도해 주세요."}
      </p>
      <button
        onClick={onDismiss}
        className="shrink-0 text-[12px] font-semibold text-red-500"
        aria-label="오류 닫기"
      >
        닫기
      </button>
    </div>
  );
}

// ── ConsentModal ── 국외이전 동의 (컴플라이언스 게이트) ──────────────────────
// ⚠️ 법적 동의 흐름. 자동 동의 처리 금지. 사용자가 직접 확인 후 버튼 클릭.

export function ConsentModal({
  onAgree,
  onDismiss,
  loading,
}: {
  onAgree: () => void;
  onDismiss: () => void;
  loading: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="consent-modal-title"
    >
      <div className="w-full sm:max-w-md bg-surface rounded-t-3xl sm:rounded-2xl px-6 pt-6 pb-8 shadow-xl">
        <h2
          id="consent-modal-title"
          className="text-[18px] font-extrabold text-ink"
        >
          보험정보 국외이전 동의
        </h2>
        <p className="mt-3 text-[14px] text-ink2 leading-6">
          증권 OCR 분석을 위해 고객의 보험 정보를{" "}
          <b className="font-semibold text-ink">Claude AI(미국 소재)</b>로
          처리합니다. 고객의 동의를 받은 경우에만 진행하세요.
        </p>

        {/* 동의 범위 요약 */}
        <ul className="mt-4 space-y-1.5 text-[13px] text-ink3 leading-5">
          <li>수집·이전 항목: 증권의 보험정보(담보·보험료 등)</li>
          <li>이전 국가·수탁자: 미국 Anthropic(Claude API)</li>
          <li>이전 목적: AI 기반 증권 파싱 및 담보 정규화</li>
          <li>보유 기간: 처리 후 즉시 삭제</li>
        </ul>

        {/* AI 면책 — 정직성 레드라인 */}
        <p className="mt-3 text-[12px] text-muted">
          처리 결과는 AI 초안이며, 최종 확인과 책임은 설계사에게 있습니다.
        </p>

        <div className="mt-5 flex flex-col gap-2.5">
          <button
            onClick={onAgree}
            disabled={loading}
            className="w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 disabled:opacity-60 transition"
          >
            {loading ? "처리 중…" : "동의하고 분석 시작"}
          </button>
          <button
            onClick={onDismiss}
            disabled={loading}
            className="w-full rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 py-3 disabled:opacity-60 transition"
          >
            취소
          </button>
        </div>
      </div>
    </div>
  );
}
