"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ConfirmationDialog } from "@/components/recruiting/confirmation-dialog";
import {
  adminDecideBenefitReview,
  adminListBenefitReviews,
} from "@/lib/adminApi";
import { ApiError, type ManualBenefitReview, type ManualBenefitReviewStatus } from "@/lib/api";
import { useAdminGuard } from "@/lib/useAdminGuard";

const STATUS_TABS: Array<{ label: string; value?: ManualBenefitReviewStatus }> = [
  { label: "전체" },
  { label: "접수", value: "pending" },
  { label: "승인", value: "approved" },
  { label: "반려", value: "rejected" },
  { label: "지급 완료", value: "consumed" },
];

const STATUS_LABEL: Record<ManualBenefitReviewStatus, string> = {
  pending: "접수",
  approved: "승인",
  rejected: "반려",
  consumed: "지급 완료",
};

function dateText(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function AdminBenefitReviewsPage() {
  const ready = useAdminGuard();
  const [status, setStatus] = useState<ManualBenefitReviewStatus | undefined>();
  const [reviews, setReviews] = useState<ManualBenefitReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [decision, setDecision] = useState<{
    review: ManualBenefitReview;
    value: "approved" | "rejected";
  } | null>(null);
  const [reason, setReason] = useState("");
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [decisionConflict, setDecisionConflict] = useState(false);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const mountedRef = useRef(false);
  const loadGenerationRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      loadGenerationRef.current += 1;
    };
  }, []);

  const load = useCallback(async () => {
    const generation = loadGenerationRef.current + 1;
    loadGenerationRef.current = generation;
    setLoading(true);
    setError(null);
    try {
      const result = await adminListBenefitReviews(status);
      if (!mountedRef.current || generation !== loadGenerationRef.current) return false;
      setReviews(result.results);
    } catch (caught) {
      if (!mountedRef.current || generation !== loadGenerationRef.current) return false;
      setError(caught instanceof ApiError ? caught.message : "확인 요청 목록을 다시 불러와 주세요.");
    } finally {
      if (mountedRef.current && generation === loadGenerationRef.current) setLoading(false);
    }
    return true;
  }, [status]);

  useEffect(() => {
    if (ready) void load();
  }, [load, ready]);

  function openDecision(review: ManualBenefitReview, value: "approved" | "rejected") {
    setDecision({ review, value });
    setReason("");
    setDecisionError(null);
    setDecisionConflict(false);
  }

  async function submitDecision() {
    if (!decision || deciding || decisionConflict) return;
    if (!reason.trim()) {
      setDecisionError("처리 사유를 입력해 주세요.");
      reasonRef.current?.focus();
      return;
    }
    setDeciding(true);
    setDecisionError(null);
    try {
      await adminDecideBenefitReview(decision.review.id, {
        decision: decision.value,
        reason: reason.trim(),
      });
      setDecision(null);
      setMessage("확인 요청 처리 결과를 저장했어요.");
      await load();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setMessage("이미 다른 관리자가 처리했어요. 최신 상태를 불러왔어요.");
        setDecisionConflict(true);
        setDecisionError("이미 다른 관리자가 처리한 요청이에요. 최신 목록을 확인해 주세요.");
        await load();
      } else {
        setDecisionError(caught instanceof ApiError ? caught.message : "처리 결과를 다시 확인해 주세요.");
      }
    } finally {
      setDeciding(false);
    }
  }

  if (!ready) return null;

  return (
    <div className="max-w-6xl">
      <h1 className="text-[22px] font-extrabold text-ink">무료 혜택 확인 요청</h1>
      <p className="mt-2 text-[13px] leading-6 text-ink3">마스킹된 번호와 연락처, 확인 사유만 보고 처리합니다.</p>

      {message && <p role="status" aria-live="polite" className="mt-4 text-[13px] text-success-ink">{message}</p>}
      {error && (
        <div role="alert" className="mt-4 rounded-2xl bg-danger-tint p-4 text-[13px] text-danger-ink">
          <p>{error}</p>
          <button type="button" onClick={() => void load()} className="mt-3 min-h-11 rounded-xl border border-danger-ink/20 px-3 font-semibold">목록 다시 불러오기</button>
        </div>
      )}

      <div role="tablist" aria-label="확인 요청 상태" className="mt-5 flex gap-2 overflow-x-auto pb-1">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.label}
            type="button"
            role="tab"
            aria-selected={status === tab.value}
            onClick={() => setStatus(tab.value)}
            className={`min-h-10 shrink-0 rounded-xl px-3 text-[13px] font-bold ${status === tab.value ? "bg-brand text-white" : "border border-line bg-surface text-ink2"}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading && reviews.length === 0 ? (
        <div aria-label="확인 요청 목록 불러오는 중" className="mt-5 grid gap-3">
          {[0, 1, 2].map((item) => <div key={item} className="h-36 animate-pulse rounded-2xl bg-line" />)}
        </div>
      ) : reviews.length === 0 ? (
        <div className="mt-5 rounded-2xl bg-surface p-6 text-center">
          <p className="text-[15px] font-bold text-ink">표시할 확인 요청이 없어요.</p>
          <p className="mt-2 text-[13px] text-ink3">다른 상태를 선택하거나 잠시 뒤 다시 확인해 주세요.</p>
        </div>
      ) : (
        <div className="mt-5 grid gap-3">
          {reviews.map((review) => (
            <article key={review.id} className="rounded-2xl bg-surface p-4 sm:p-5">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-[15px] font-extrabold text-ink">{review.phone_masked}</p>
                  <p className="mt-1 break-all text-[13px] text-ink2">{review.contact_email}</p>
                </div>
                <span className="w-fit rounded-full bg-surface2 px-2.5 py-1 text-[12px] font-bold text-ink2">{STATUS_LABEL[review.status]}</span>
              </div>
              <dl className="mt-4 grid gap-3 text-[13px] leading-5 text-ink2 sm:grid-cols-2">
                <div><dt className="text-ink3">확인 사유</dt><dd className="mt-1 whitespace-pre-wrap">{review.reason}</dd></div>
                <div><dt className="text-ink3">요청일</dt><dd className="mt-1">{dateText(review.created_at)}</dd></div>
                {review.decision_reason && <div><dt className="text-ink3">처리 사유</dt><dd className="mt-1 whitespace-pre-wrap">{review.decision_reason}</dd></div>}
                {review.decided_at && <div><dt className="text-ink3">처리일</dt><dd className="mt-1">{dateText(review.decided_at)}</dd></div>}
              </dl>
              {review.status === "pending" && (
                <div className="mt-4 grid gap-2 sm:grid-cols-2 sm:max-w-sm">
                  <button type="button" onClick={() => openDecision(review, "approved")} className="min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white">승인</button>
                  <button type="button" onClick={() => openDecision(review, "rejected")} className="min-h-11 rounded-xl border border-line px-4 text-[13px] font-bold text-ink2">반려</button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}

      <ConfirmationDialog
        open={Boolean(decision)}
        title={`확인 요청 ${decision?.value === "approved" ? "승인" : "반려"}`}
        description="처리 사유를 남기면 요청 상태가 바뀝니다. 저장 뒤 최신 목록을 다시 확인해요."
        confirmLabel={`${decision?.value === "approved" ? "승인" : "반려"} 확정`}
        pendingLabel="저장 중..."
        pending={deciding}
        confirmDisabled={decisionConflict}
        error={decisionError}
        initialFocusRef={reasonRef}
        onConfirm={() => void submitDecision()}
        onClose={() => { if (!deciding) setDecision(null); }}
      >
        <label htmlFor="benefit-review-decision-reason" className="mt-4 block text-[13px] font-semibold text-ink2">처리 사유</label>
        <textarea ref={reasonRef} id="benefit-review-decision-reason" value={reason} onChange={(event) => setReason(event.target.value)} rows={3} className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink outline-none focus:border-brand" />
      </ConfirmationDialog>
    </div>
  );
}
