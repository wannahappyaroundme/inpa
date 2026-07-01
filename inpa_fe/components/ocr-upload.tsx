"use client";

// ════════════════════════════════════════════════════════════════════════════
// 증권 OCR 업로드 — 공유 컴포넌트 (/analysis 와 /customer/[id] 분석 탭 공유)
// 업로드 흐름: idle → uploading → 412(동의 필요) → consent_modal → uploading → success/error
//
// ⚠️ 컴플라이언스: ConsentModal 은 법적 국외이전 동의 흐름. 자동 동의 금지.
//    사용자가 직접 확인 후 버튼 클릭해야 함 (정직성 레드라인).
//    AI 면책 문구 고정: "처리 결과는 AI 초안이며, 최종 확인과 책임은 설계사".
// ════════════════════════════════════════════════════════════════════════════

import { useState, useCallback, useEffect } from "react";
import { InpaMark } from "@/components/inpa-logo";

// 처리 단계 — 사용자에게 'OCR' 같은 기능어 대신 알아듣기 쉬운 진행 표현.
// 실제 파이프라인: pdfplumber 텍스트 추출 → Claude 인식/구조화 → 담보 정규화/분석.
const SCAN_STAGES = ["증권 스캔 중…", "내용 인식 중…", "담보 분류 중…", "보장 분석 중…"];
import {
  uploadInsuranceOcr,
  createConsentRequest,
  ApiError,
} from "@/lib/api";
import { UpgradeModal, type UpgradeModalInfo } from "@/components/upgrade-modal";

export type OcrPhase =
  | "idle"
  | "uploading"
  | "consent_required"
  | "success"
  | "error"
  | "limit_exceeded";

/**
 * OCR 업로드 상태 + 액션을 한곳에 모은 훅.
 * 페이지(분석/고객상세)는 이 훅으로 상태를 받아 버튼·배너·모달을 조립한다.
 *
 * @param onUploaded 업로드 성공 시 콜백(예: 히트맵 새로고침). selectedId 인자 전달.
 */
export function useOcrUpload(onUploaded?: (customerId: number) => void, portfolioType: number = 1) {
  const [phase, setPhase] = useState<OcrPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [consentLoading, setConsentLoading] = useState(false);
  const [consentUrl, setConsentUrl] = useState<string | null>(null);
  const [consentCopied, setConsentCopied] = useState(false);
  const [upgradeInfo, setUpgradeInfo] = useState<UpgradeModalInfo | undefined>(undefined);

  const runUpload = useCallback(
    async (customerId: number, file: File) => {
      setPhase("uploading");
      setError(null);
      try {
        await uploadInsuranceOcr(customerId, file, portfolioType);
        setPhase("success");
        onUploaded?.(customerId);
        setTimeout(() => setPhase("idle"), 2000);
      } catch (e: unknown) {
        if (e instanceof ApiError && e.status === 412) {
          // 국외이전 동의 필요 → 동의 모달 노출
          setPhase("consent_required");
        } else if (e instanceof ApiError && e.status === 402) {
          // 한도 초과 → 소프트 업그레이드 안내 모달
          setUpgradeInfo(e.creditBody ?? { kind: "ocr" });
          setPhase("limit_exceeded");
        } else {
          const msg =
            e instanceof Error ? e.message : "증권 업로드 중 오류가 발생했어요.";
          setError(msg);
          setPhase("error");
        }
      }
    },
    [onUploaded, portfolioType]
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

  /** ★ P3c: 설계사 대리동의 폐기 → 고객 본인 동의 요청 링크 생성(설계사는 전달만). */
  const generateConsentLink = useCallback(async (customerId: number | null) => {
    if (customerId === null) return;
    setConsentLoading(true);
    setError(null);
    try {
      const res = await createConsentRequest(customerId);
      setConsentUrl(res.consent_url);
    } catch {
      setError("동의 링크 생성 중 오류가 발생했어요. 다시 시도해 주세요.");
    } finally {
      setConsentLoading(false);
    }
  }, []);

  /** 업로드 시도 전에도(헤더 등) 동의 모달을 직접 열 수 있게. */
  const openConsent = useCallback(() => {
    setConsentUrl(null);
    setConsentCopied(false);
    setError(null);
    setPhase("consent_required");
  }, []);

  /** 동의 링크 클립보드 복사 (자동발송 없음 — 정직성 레드라인). */
  const copyConsentUrl = useCallback(async () => {
    if (!consentUrl) return;
    try {
      await navigator.clipboard.writeText(consentUrl);
      setConsentCopied(true);
      setTimeout(() => setConsentCopied(false), 2000);
    } catch {
      /* 미지원 환경 무시 */
    }
  }, [consentUrl]);

  const dismissConsent = useCallback(() => {
    setPhase("idle");
    setPendingFile(null);
    setConsentUrl(null);
    setConsentCopied(false);
    setError(null);
  }, []);

  const clearError = useCallback(() => {
    setPhase("idle");
    setError(null);
  }, []);

  const dismissUpgrade = useCallback(() => {
    setPhase("idle");
    setUpgradeInfo(undefined);
  }, []);

  return {
    phase,
    error,
    upgradeInfo,
    consentLoading,
    consentUrl,
    consentCopied,
    onFileChange,
    generateConsentLink,
    openConsent,
    copyConsentUrl,
    dismissConsent,
    clearError,
    dismissUpgrade,
  };
}

// ── OcrUploadButton ── hidden file input + label 패턴 ─────────────────────────

export function OcrUploadButton({
  customerId,
  phase,
  onFileChange,
  inputId = "ocr-file-input",
  label = "증권 등록",
  consented,
  onNeedConsent,
}: {
  customerId: number | null;
  phase: OcrPhase;
  onFileChange: (
    e: React.ChangeEvent<HTMLInputElement>,
    customerId: number | null
  ) => void;
  inputId?: string;
  label?: string;
  /** 고객 본인 국외이전 동의 여부. false 면 파일 선택 대신 동의 안내를 먼저 띄운다. */
  consented?: boolean;
  onNeedConsent?: () => void;
}) {
  const disabled =
    customerId === null || phase === "uploading" || phase === "consent_required";

  // 처리 중 단계 순환(스캔→인식→분류→분석). 마지막 단계에서 정지(완료까지 유지).
  const [stage, setStage] = useState(0);
  useEffect(() => {
    if (phase !== "uploading") {
      setStage(0);
      return;
    }
    const id = setInterval(
      () => setStage((s) => Math.min(s + 1, SCAN_STAGES.length - 1)),
      1100
    );
    return () => clearInterval(id);
  }, [phase]);

  // 동의 전(consented===false)이면 파일을 고르게 두지 않고, 먼저 '고객 동의부터 보내기'로 유도.
  // (못 올린다는 에러 대신 다음 할 일을 알려주는 긍정 흐름 — PM 06.29)
  if (consented === false) {
    return (
      <button
        type="button"
        onClick={onNeedConsent}
        disabled={customerId === null}
        className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-[13px] font-semibold transition select-none ${
          customerId === null
            ? "border-line text-ink3 bg-surface2 cursor-not-allowed"
            : "border-brand text-brand bg-surface hover:bg-accent-tint active:scale-[0.98]"
        }`}
      >
        {label}
      </button>
    );
  }

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
            <InpaMark live size={16} title="처리 중" />
            {SCAN_STAGES[stage]}
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
  onManualEntry,
}: {
  phase: OcrPhase;
  errorMsg: string | null;
  onDismiss: () => void;
  /** 있으면 오류 배너에 '직접 입력' 폴백 버튼을 노출. 인식 실패로 이탈하지 않게(P9c). */
  onManualEntry?: () => void;
}) {
  if (phase !== "error") return null;
  return (
    <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3">
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 text-[15px]" aria-hidden>
          !
        </span>
        <p className="flex-1 text-[13px] text-red-700 leading-5">
          {errorMsg ?? "증권 인식이 잘 안 됐어요."}
          {onManualEntry ? " 직접 입력으로 바로 등록할 수 있어요." : " 잠시 후 다시 시도해 주세요."}
        </p>
        <button
          onClick={onDismiss}
          className="shrink-0 text-[12px] font-semibold text-red-500"
          aria-label="오류 닫기"
        >
          닫기
        </button>
      </div>
      {onManualEntry && (
        <button
          onClick={onManualEntry}
          className="mt-2.5 w-full rounded-xl border border-brand bg-surface text-brand text-[13px] font-semibold py-2 hover:bg-accent-tint transition"
        >
          직접 입력으로 등록하기
        </button>
      )}
    </div>
  );
}

// ── ConsentModal ── 고객 본인 국외이전 동의 요청 (P3c 컴플라이언스 게이트) ────────
// ⚠️ 설계사 대리동의 불가. 고객이 본인 기기에서 /c/<token> 으로 직접 동의해야 분석 가능.
//    설계사는 '동의 요청 링크'를 만들어 전달(클립보드 복사/카톡)만 한다 — 자동발송 없음.

export function ConsentModal({
  onGenerate,
  consentUrl,
  consentCopied,
  onCopy,
  onDismiss,
  loading,
}: {
  onGenerate: () => void;
  consentUrl: string | null;
  consentCopied: boolean;
  onCopy: () => void;
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
          고객 본인 동의가 필요해요
        </h2>
        <p className="mt-3 text-[14px] text-ink2 leading-6">
          증권 분석을 위해 보험 정보가{" "}
          <b className="font-semibold text-ink">Claude AI(미국 소재)</b>로
          국외이전됩니다. 법적으로 <b className="font-semibold text-ink">고객 본인</b>이 직접
          동의해야 분석을 시작할 수 있어요. 아래 동의 요청 링크를 만들어 고객에게 보내세요.
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
          처리 결과는 AI가 정리한 초안이에요. 고객 안내 전 설계사님이 확인해 주세요.
        </p>

        <div className="mt-5 flex flex-col gap-2.5">
          {!consentUrl ? (
            <button
              onClick={onGenerate}
              disabled={loading}
              className="w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 disabled:opacity-60 transition"
            >
              {loading ? "링크 생성 중…" : "동의 요청 링크 만들기"}
            </button>
          ) : (
            <>
              <div className="rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[12px] text-ink2 break-all select-all">
                {consentUrl}
              </div>
              <div className="flex gap-2.5">
                <button
                  onClick={onCopy}
                  className="flex-1 rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 transition"
                >
                  {consentCopied ? "복사됐어요!" : "링크 복사하기"}
                </button>
                <a
                  href={consentUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 px-4 py-3.5 flex items-center"
                >
                  미리보기 ↗
                </a>
              </div>
              <p className="text-[12px] text-ink3 leading-5">
                고객이 링크에서 동의를 완료하면, 다시{" "}
                <b className="font-semibold text-ink2">[증권 등록]</b>을 눌러 분석을 시작하세요.
              </p>
            </>
          )}
          <button
            onClick={onDismiss}
            disabled={loading}
            className="w-full rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 py-3 disabled:opacity-60 transition"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
