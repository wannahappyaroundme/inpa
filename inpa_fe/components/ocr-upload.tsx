"use client";

// ════════════════════════════════════════════════════════════════════════════
// 증권 OCR 업로드 — 공유 컴포넌트 (/analysis 와 /customer/[id] 분석 탭 공유)
// 업로드 흐름: idle → uploading → 412(동의 필요) → consent_modal → uploading → success/error
//
// ⚠️ 컴플라이언스: ConsentModal 은 법적 국외이전 동의 흐름. 자동 동의 금지.
//    사용자가 직접 확인 후 버튼 클릭해야 함 (정직성 레드라인).
//    AI 면책 문구 고정: "처리 결과는 AI 초안이며, 최종 확인과 책임은 설계사".
// ════════════════════════════════════════════════════════════════════════════

import {
  useState,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
} from "react";
import { useRouter } from "next/navigation";
import { InpaMark } from "@/components/inpa-logo";

import {
  createInsuranceImport,
  getInsuranceImportConfig,
  uploadInsuranceOcr,
  createConsentRequest,
  getConsentTexts,
  ApiError,
  type ConsentText,
} from "@/lib/api";
import { createIdempotencyKey, preflightInsuranceImport } from "@/lib/insurance-imports";
import { UpgradeModal, type UpgradeModalInfo } from "@/components/upgrade-modal";

export type OcrPhase =
  | "idle"
  | "preparing"
  | "uploading"
  | "consent_required"
  | "success"
  | "error"
  | "limit_exceeded"
  | "duplicate_confirmed";

export interface ConfirmedDuplicateInfo {
  customerId: number;
  insuranceId: number;
  insuranceVersion: number;
  resolutionToken: string;
}

interface InsuranceUploadAttempt {
  customerId: number;
  file: File;
  intent: "add" | "replace";
  targetInsuranceId?: number;
  duplicateResolutionToken?: string;
  idempotencyKey: string;
}

/**
 * OCR 업로드 상태 + 액션을 한곳에 모은 훅.
 * 페이지(분석/고객상세)는 이 훅으로 상태를 받아 버튼·배너·모달을 조립한다.
 *
 * @param onUploaded 업로드 성공 시 콜백(예: 히트맵 새로고침). selectedId 인자 전달.
 */
export function useOcrUpload(
  onUploaded?: (customerId: number) => void,
  portfolioType: 1 | 2 = 1,
  activeCustomerId: number | null = null
) {
  const router = useRouter();
  const [phase, setPhase] = useState<OcrPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [consentLoading, setConsentLoading] = useState(false);
  const [consentUrl, setConsentUrl] = useState<string | null>(null);
  const [consentCopied, setConsentCopied] = useState(false);
  // 412 사유: "reconsent"(구버전 동의 → 재동의) | "missing"(동의 없음). 모달 안내 문구 분기.
  const [consentReason, setConsentReason] = useState<string | undefined>(undefined);
  const [upgradeInfo, setUpgradeInfo] = useState<UpgradeModalInfo | undefined>(undefined);
  const [workflowEnabled, setWorkflowEnabled] = useState<boolean | null>(null);
  const [duplicateInfo, setDuplicateInfo] = useState<ConfirmedDuplicateInfo | null>(null);
  const [retryAvailable, setRetryAvailable] = useState(false);
  const pendingAttempt = useRef<InsuranceUploadAttempt | null>(null);
  const boundCustomerId = useRef<number | null>(activeCustomerId);
  const customerGeneration = useRef(0);
  const lifecycleGeneration = useRef(0);
  const consentRequestGeneration = useRef(0);
  const mounted = useRef(false);
  const configPromise = useRef<Promise<boolean> | null>(null);

  useLayoutEffect(() => {
    mounted.current = true;
    lifecycleGeneration.current += 1;
    return () => {
      mounted.current = false;
      lifecycleGeneration.current += 1;
      consentRequestGeneration.current += 1;
      pendingAttempt.current = null;
    };
  }, []);

  useLayoutEffect(() => {
    if (boundCustomerId.current === activeCustomerId) return;
    boundCustomerId.current = activeCustomerId;
    customerGeneration.current += 1;
    consentRequestGeneration.current += 1;
    pendingAttempt.current = null;
    setDuplicateInfo(null);
    setRetryAvailable(false);
    setError(null);
    setConsentLoading(false);
    setConsentUrl(null);
    setConsentCopied(false);
    setConsentReason(undefined);
    setPhase("idle");
  }, [activeCustomerId]);

  const loadConfig = useCallback((force = false): Promise<boolean> => {
    if (!force && workflowEnabled !== null) return Promise.resolve(workflowEnabled);
    if (!force && configPromise.current) return configPromise.current;
    const requestGeneration = lifecycleGeneration.current;
    let pending: Promise<boolean>;
    pending = getInsuranceImportConfig()
      .then((config) => {
        if (
          mounted.current &&
          lifecycleGeneration.current === requestGeneration
        ) {
          setWorkflowEnabled(config.review_workflow_enabled);
        }
        return config.review_workflow_enabled;
      })
      .finally(() => {
        if (configPromise.current === pending) configPromise.current = null;
      });
    configPromise.current = pending;
    return pending;
  }, [workflowEnabled]);

  useEffect(() => {
    void loadConfig().catch(() => {
      // 파일 선택 시 안전한 재시도 안내를 표시한다.
    });
  }, [loadConfig]);

  const runUpload = useCallback(
    async (attempt: InsuranceUploadAttempt) => {
      const { customerId, file } = attempt;
      if (boundCustomerId.current !== null && boundCustomerId.current !== customerId) return;
      const generation = customerGeneration.current;
      const mountedGeneration = lifecycleGeneration.current;
      const isCurrentCustomer = () =>
        mounted.current &&
        lifecycleGeneration.current === mountedGeneration &&
        customerGeneration.current === generation &&
        (boundCustomerId.current === null || boundCustomerId.current === customerId);
      pendingAttempt.current = attempt;
      setPhase("preparing");
      setError(null);
      setRetryAvailable(false);
      try {
        const preflight = await preflightInsuranceImport(file);
        if (!isCurrentCustomer()) return;
        if (!preflight.ok) {
          pendingAttempt.current = null;
          setError(preflight.message);
          setPhase("error");
          return;
        }
        let reviewWorkflow: boolean;
        try {
          reviewWorkflow = await loadConfig();
        } catch {
          if (!isCurrentCustomer()) return;
          setError("증권 등록 방식을 확인하지 못했어요. 다시 시도해 주세요.");
          setRetryAvailable(true);
          setPhase("error");
          return;
        }
        if (!isCurrentCustomer()) return;
        if (reviewWorkflow) {
          if (!isCurrentCustomer()) return;
          setPhase("uploading");
          const result = await createInsuranceImport(customerId, file, {
            intent: attempt.intent,
            portfolioType,
            targetInsuranceId: attempt.targetInsuranceId,
            duplicateResolutionToken: attempt.duplicateResolutionToken,
            idempotencyKey: attempt.idempotencyKey,
          });
          if (!isCurrentCustomer()) return;
          pendingAttempt.current = null;
          router.push(`/customer/${customerId}/insurance-imports/${result.job_id}`);
          return;
        }
        if (!isCurrentCustomer()) return;
        setPhase("uploading");
        await uploadInsuranceOcr(customerId, file, portfolioType);
        if (!isCurrentCustomer()) return;
        pendingAttempt.current = null;
        setPhase("success");
        onUploaded?.(customerId);
        setTimeout(() => {
          if (isCurrentCustomer()) setPhase("idle");
        }, 2000);
      } catch (e: unknown) {
        if (!isCurrentCustomer()) return;
        if (e instanceof ApiError && e.status === 412) {
          // 국외이전 동의 필요 → 동의 모달 노출. reason으로 안내 문구 분기.
          setConsentReason(e.reason ?? "missing");
          setPhase("consent_required");
        } else if (e instanceof ApiError && e.status === 402) {
          // 한도 초과 → 소프트 업그레이드 안내 모달
          setUpgradeInfo(e.creditBody ?? { kind: "ocr" });
          setPhase("limit_exceeded");
        } else if (e instanceof ApiError && e.status === 409 && e.code === "DUPLICATE_CONFIRMED") {
          const insuranceId = e.data?.insurance_id;
          const insuranceVersion = e.data?.insurance_version;
          const resolutionToken = e.data?.duplicate_resolution_token;
          if (
            typeof insuranceId === "number" &&
            typeof insuranceVersion === "number" &&
            typeof resolutionToken === "string" &&
            resolutionToken.length > 0
          ) {
            setDuplicateInfo({ customerId, insuranceId, insuranceVersion, resolutionToken });
            setPhase("duplicate_confirmed");
          } else {
            pendingAttempt.current = null;
            setError("확인할 보험을 다시 불러와 주세요.");
            setPhase("error");
          }
        } else {
          const msg =
            e instanceof Error ? e.message : "증권 업로드 중 오류가 발생했어요.";
          const retryable =
            !(e instanceof ApiError) || e.status >= 500 || e.status === 429;
          if (!retryable) pendingAttempt.current = null;
          setRetryAvailable(retryable);
          setError(msg);
          setPhase("error");
        }
      }
    },
    [loadConfig, onUploaded, portfolioType, router]
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
      setDuplicateInfo(null);
      await runUpload({
        customerId,
        file,
        intent: "add",
        idempotencyKey: createIdempotencyKey(),
      });
    },
    [runUpload]
  );

  /** ★ P3c: 설계사 대리동의 폐기 → 고객 본인 동의 요청 링크 생성(설계사는 전달만).
   *  성공/실패를 boolean 으로 돌려줘 모달이 실패 배너를 띄우고 재시도할 수 있게 한다. */
  const generateConsentLink = useCallback(async (customerId: number | null): Promise<boolean> => {
    if (customerId === null) return false;
    const requestGeneration = ++consentRequestGeneration.current;
    const lifecycle = lifecycleGeneration.current;
    const customer = customerGeneration.current;
    const isCurrentRequest = () =>
      mounted.current &&
      lifecycleGeneration.current === lifecycle &&
      customerGeneration.current === customer &&
      consentRequestGeneration.current === requestGeneration &&
      (boundCustomerId.current === null || boundCustomerId.current === customerId);
    setConsentLoading(true);
    setError(null);
    try {
      const res = await createConsentRequest(customerId);
      if (!isCurrentRequest()) return true;
      setConsentUrl(res.consent_url);
      return true;
    } catch {
      if (!isCurrentRequest()) return true;
      setError("동의 링크 생성 중 오류가 발생했어요. 다시 시도해 주세요.");
      return false;
    } finally {
      if (isCurrentRequest()) setConsentLoading(false);
    }
  }, []);

  /** 업로드 시도 전에도(헤더 등) 동의 모달을 직접 열 수 있게. */
  const openConsent = useCallback(() => {
    consentRequestGeneration.current += 1;
    setConsentLoading(false);
    setConsentUrl(null);
    setConsentCopied(false);
    setConsentReason("missing");
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
    consentRequestGeneration.current += 1;
    pendingAttempt.current = null;
    setConsentLoading(false);
    setPhase("idle");
    setConsentUrl(null);
    setConsentCopied(false);
    setConsentReason(undefined);
    setError(null);
  }, []);

  const clearError = useCallback(() => {
    pendingAttempt.current = null;
    setPhase("idle");
    setError(null);
    setRetryAvailable(false);
  }, []);

  const retryUpload = useCallback(() => {
    const attempt = pendingAttempt.current;
    if (!attempt) return;
    setWorkflowEnabled(null);
    void runUpload(attempt);
  }, [runUpload]);

  const openDuplicateInsurance = useCallback(() => {
    if (!duplicateInfo) return;
    router.push(`/customer/${duplicateInfo.customerId}?tab=analysis&insurance=${duplicateInfo.insuranceId}`);
  }, [duplicateInfo, router]);

  const resolveDuplicateReplace = useCallback(() => {
    const previous = pendingAttempt.current;
    if (!duplicateInfo || !previous || previous.customerId !== duplicateInfo.customerId) {
      pendingAttempt.current = null;
      setDuplicateInfo(null);
      setPhase("idle");
      return;
    }
    const resolved: InsuranceUploadAttempt = {
      customerId: duplicateInfo.customerId,
      file: previous.file,
      intent: "replace",
      targetInsuranceId: duplicateInfo.insuranceId,
      duplicateResolutionToken: duplicateInfo.resolutionToken,
      idempotencyKey: createIdempotencyKey(),
    };
    setDuplicateInfo(null);
    void runUpload(resolved);
  }, [duplicateInfo, runUpload]);

  const dismissUpgrade = useCallback(() => {
    pendingAttempt.current = null;
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
    consentReason,
    duplicateInfo,
    onFileChange,
    generateConsentLink,
    openConsent,
    copyConsentUrl,
    dismissConsent,
    clearError,
    retryAvailable,
    retryUpload: retryAvailable ? retryUpload : undefined,
    retryConfig: retryAvailable ? retryUpload : undefined,
    openDuplicateInsurance,
    resolveDuplicateReplace,
    prepareDuplicateReplace: resolveDuplicateReplace,
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
    customerId === null || phase === "preparing" || phase === "uploading" || phase === "consent_required";

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
        {phase === "preparing" || phase === "uploading" ? (
          <>
            <InpaMark live size={16} title="처리 중" />
            {phase === "preparing" ? "파일 확인 중…" : "증권 접수 중…"}
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
  onRetry,
  onManualEntry,
}: {
  phase: OcrPhase;
  errorMsg: string | null;
  onDismiss: () => void;
  onRetry?: () => void;
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
          {onManualEntry
            ? " 직접 입력으로 바로 등록할 수 있어요."
            : onRetry
              ? ""
              : " 잠시 후 다시 시도해 주세요."}
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
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2.5 w-full rounded-xl border border-line bg-surface py-2 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition"
        >
          다시 시도
        </button>
      )}
    </div>
  );
}

export function InsuranceDuplicateChoice({
  info,
  onOpenExisting,
  onReplace,
}: {
  info: ConfirmedDuplicateInfo | null;
  onOpenExisting: () => void;
  onReplace: () => void;
}) {
  if (!info) return null;
  return (
    <div className="mt-3 rounded-xl border border-line bg-surface2 px-4 py-4" role="dialog" aria-label="이미 확인한 증권">
      <p className="text-[14px] font-bold text-ink">이미 확인한 증권이에요</p>
      <p className="mt-1 text-[13px] leading-5 text-ink3">
        기존 보험을 확인하거나, 새 증권 내용으로 교체할 수 있어요.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={onOpenExisting} className="rounded-xl bg-brand px-3 py-2 text-[13px] font-semibold text-white">
          기존 보험 보기
        </button>
        <button type="button" onClick={onReplace} className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2">
          새 증권으로 교체
        </button>
      </div>
    </div>
  );
}

// ── ConsentModal ── 고객 본인 국외이전 동의 요청 (P3c 컴플라이언스 게이트) ────────
// ⚠️ 설계사 대리동의 불가. 고객이 본인 기기에서 /c/<token> 으로 직접 동의해야 분석 가능.
//    설계사는 '동의 요청 링크'를 만들어 전달(클립보드 복사/카톡)만 한다 — 자동발송 없음.

// 서버 미응답 시 로컬 폴백 — 반드시 v2 문구(옛 '즉시 삭제'는 절대 쓰지 않는다).
const OVERSEAS_FALLBACK: ConsentText = {
  title: "보험 정보 국외이전 (Claude API, 미국)",
  body: [
    "이전 국가·수탁자: 미국 Anthropic(Claude API)",
    "이전 항목: 증권의 보험정보(담보·보험료 등)",
  ],
  retention:
    "보유 기간: Anthropic의 데이터 처리·보관 정책에 따릅니다(입력 정보는 AI 학습에 사용되지 않아요).",
};

export function ConsentModal({
  onGenerate,
  consentUrl,
  consentCopied,
  onCopy,
  onDismiss,
  loading,
  reason,
  error,
}: {
  /** 성공/실패를 boolean 으로 돌려주면 모달이 실패 배너를 띄운다(useOcrUpload.generateConsentLink). */
  onGenerate: () => void | Promise<unknown>;
  consentUrl: string | null;
  consentCopied: boolean;
  onCopy: () => void;
  onDismiss: () => void;
  loading: boolean;
  /** "reconsent" 면 '안내문이 새로워졌어요' 긍정 안내로 분기. */
  reason?: string;
  /** 훅에서 내려주는 에러(선택). 있으면 그대로 배너에 표시. */
  error?: string | null;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const primaryActionRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  // 최신 국외이전 고지문을 서버에서 받아 렌더(실패 시 v2 로컬 폴백).
  const [overseas, setOverseas] = useState<ConsentText>(OVERSEAS_FALLBACK);
  // 링크 생성 실패 배너 — onGenerate 가 false 를 돌려주면 표시(재시도 가능).
  const [genErr, setGenErr] = useState<string | null>(null);
  const handleGenerate = async () => {
    setGenErr(null);
    const ok = await onGenerate();
    if (ok === false) setGenErr("동의 링크를 만들지 못했어요. 잠시 후 다시 시도해 주세요.");
  };
  const shownErr = error ?? genErr;
  useLayoutEffect(() => {
    const returnFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousOverflow = document.body.style.overflow;
    const inertedElements: Array<{ element: HTMLElement; wasInert: boolean }> = [];
    const dialog = dialogRef.current;
    let current: HTMLElement | null = dialog;
    while (current?.parentElement) {
      const parent = current.parentElement;
      for (const sibling of Array.from(parent.children)) {
        if (sibling === current || !(sibling instanceof HTMLElement)) continue;
        inertedElements.push({ element: sibling, wasInert: sibling.inert === true });
        sibling.inert = true;
      }
      if (parent === document.body) break;
      current = parent;
    }
    document.body.style.overflow = "hidden";
    primaryActionRef.current?.focus();
    if (dialog && !dialog.contains(document.activeElement)) dialog.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      for (const { element, wasInert } of inertedElements) element.inert = wasInert;
      returnFocus?.focus();
    };
  }, []);

  useEffect(() => {
    if (consentUrl) primaryActionRef.current?.focus();
  }, [consentUrl]);

  const handleDialogKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      if (loading) dialogRef.current?.focus();
      else onDismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ) ?? []
    );
    if (focusable.length === 0) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = closeRef.current && focusable.includes(closeRef.current)
      ? closeRef.current
      : focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  useEffect(() => {
    let alive = true;
    getConsentTexts()
      .then((res) => {
        const t = res.texts?.overseas_medical;
        if (alive && t) setOverseas(t);
      })
      .catch(() => {
        /* 폴백 유지 */
      });
    return () => {
      alive = false;
    };
  }, []);
  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="consent-modal-title"
      tabIndex={-1}
      onKeyDown={handleDialogKeyDown}
    >
      <div className="w-full sm:max-w-md bg-surface rounded-t-3xl sm:rounded-2xl px-6 pt-6 pb-8 shadow-xl">
        <h2
          id="consent-modal-title"
          className="text-[18px] font-extrabold text-ink"
        >
          {reason === "reconsent" ? "동의 안내문이 새로워졌어요" : "고객 본인 동의가 필요해요"}
        </h2>
        <p className="mt-3 text-[14px] text-ink2 leading-6">
          {reason === "reconsent" ? (
            <>
              동의 안내문이 새로워졌어요. 고객에게{" "}
              <b className="font-semibold text-ink">동의 링크를 다시 보내면</b> 바로 분석할 수
              있어요. 아래 링크를 만들어 고객에게 보내세요.
            </>
          ) : (
            <>
              증권 분석을 위해 보험 정보가{" "}
              <b className="font-semibold text-ink">Claude AI(미국 소재)</b>로
              국외이전됩니다. 법적으로 <b className="font-semibold text-ink">고객 본인</b>이 직접
              동의해야 분석을 시작할 수 있어요. 아래 동의 요청 링크를 만들어 고객에게 보내세요.
            </>
          )}
        </p>

        {/* 동의 범위 요약 — 고지문 단일 소스(consent-texts)에서 렌더 */}
        <ul className="mt-4 space-y-1.5 text-[13px] text-ink3 leading-5">
          {overseas.body.map((line) => (
            <li key={line}>{line}</li>
          ))}
          <li>이전 목적: 증권 정보를 자동으로 읽고 담보를 표준 틀로 정리</li>
          <li>{overseas.retention}</li>
        </ul>

        {/* AI 면책 — 정직성 레드라인 */}
        <p className="mt-3 text-[12px] text-muted">
          처리 결과는 AI가 정리한 초안이에요. 고객 안내 전 설계사님이 확인해 주세요.
        </p>

        <div className="mt-5 flex flex-col gap-2.5">
          {!consentUrl ? (
            <>
              {shownErr && (
                <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 text-[13px] text-red-700 leading-5">
                  {shownErr}
                </div>
              )}
              <button
                ref={primaryActionRef}
                onClick={handleGenerate}
                disabled={loading}
                className="w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 disabled:opacity-60 transition"
              >
                {loading ? "링크 생성 중…" : shownErr ? "다시 시도하기" : "동의 요청 링크 만들기"}
              </button>
            </>
          ) : (
            <>
              <div className="rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[12px] text-ink2 break-all select-all">
                {consentUrl}
              </div>
              <div className="flex gap-2.5">
                <button
                  ref={primaryActionRef}
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
            ref={closeRef}
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
