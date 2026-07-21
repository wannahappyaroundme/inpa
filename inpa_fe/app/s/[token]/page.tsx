"use client";

// A · 고객 공유뷰. 고객이 share_token 링크로 봄 (비인증).
// ⚠️ 인파는 보험을 중개·권유하지 않음 → 공개 공유는 '보유 담보(사실)'와 '보험료 합계(사실)'만.
//    mode=neutral 강제(부족/충분 판정 라벨 없음). noindex(layout.tsx에서 robots 처리).

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import { ContentProtect, Watermark } from "@/components/content-guard";
import { ShareSnapshotContent } from "@/components/share-snapshot-content";
import { SkeletonBar, SkeletonCard, SkeletonRow, TokenLoadingShell } from "@/components/token-skeleton";
import {
  getShareView,
  normalizeShareViewResponse,
  postShareEvent,
  ApiError,
  type NormalizedShareViewResponse,
} from "@/lib/api";

function ShareSkeleton() {
  return (
    <TokenLoadingShell headerLabel="인파">
      <SkeletonBar w="w-32" h="h-4" />
      <SkeletonBar w="w-56" h="h-9" />
      <div className="grid grid-cols-2 gap-2.5">
        <SkeletonCard className="h-16" />
        <SkeletonCard className="h-16" />
      </div>
      <div className="space-y-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <SkeletonRow key={i} className="rounded-2xl" />
        ))}
      </div>
      {/* 하단 고정 CTA 자리 */}
      <div
        className="sticky bottom-0 -mx-5 mt-2 px-5 pt-3 bg-surface/95 border-t border-line"
        style={{ paddingBottom: "max(14px, env(safe-area-inset-bottom))" }}
      >
        <SkeletonBar h="h-[52px]" className="rounded-2xl" />
      </div>
    </TokenLoadingShell>
  );
}

function ShareClosed() {
  return (
    <div className="mx-auto w-full max-w-md min-h-dvh flex flex-col items-center justify-center bg-surface2 px-6 text-center">
      <div className="text-[40px] mb-4">🔍</div>
      <h1 className="text-[20px] font-extrabold text-ink">링크 사용 기간이 끝났어요</h1>
      <p className="mt-2 text-[14px] text-ink3 leading-6">
        담당 설계사에게 새 링크를 요청하면 보장 현황을 다시 확인할 수 있어요.
      </p>
    </div>
  );
}

function ShareRetry({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-md flex-col items-center justify-center bg-surface2 px-6 text-center">
      <div className="mb-4 text-[40px]">↻</div>
      <h1 className="text-[20px] font-extrabold text-ink">잠시 연결이 원활하지 않아요</h1>
      <p className="mt-2 text-[14px] leading-6 text-ink3">
        보장 현황은 그대로 있어요. 잠시 뒤 다시 불러와 주세요.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-5 rounded-xl bg-brand px-5 py-3 text-[14px] font-bold text-white"
      >
        다시 불러오기
      </button>
    </div>
  );
}

type LoadState = "loading" | "ready" | "terminal" | "retryable";
type CallbackState = "idle" | "sending" | "sent" | "error";

export default function SharePage() {
  const params = useParams();
  const token = typeof params?.token === "string" ? params.token : "";

  const [data, setData] = useState<NormalizedShareViewResponse | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [retryKey, setRetryKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [callbackState, setCallbackState] = useState<CallbackState>("idle");
  const requestRef = useRef(0);
  const callbackRequestRef = useRef(0);
  const interactionGenerationRef = useRef(0);
  const copyTimerRef = useRef<number | null>(null);
  const contactFirstActionRef = useRef<HTMLElement>(null);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  const clearCopyTimer = useCallback(() => {
    if (copyTimerRef.current !== null) {
      window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    const requestId = ++requestRef.current;
    callbackRequestRef.current += 1;
    interactionGenerationRef.current += 1;
    clearCopyTimer();
    let active = true;
    setData(null);
    setLoadState("loading");
    setCopied(false);
    setContactOpen(false);
    setCallbackState("idle");
    if (!token) {
      setLoadState("terminal");
      return () => {
        active = false;
        requestRef.current += 1;
        callbackRequestRef.current += 1;
        interactionGenerationRef.current += 1;
        clearCopyTimer();
      };
    }
    getShareView(token)
      .then((response) => {
        const normalized = normalizeShareViewResponse(response);
        if (active && requestRef.current === requestId) {
          setData(normalized);
          setLoadState("ready");
        }
      })
      .catch((e: unknown) => {
        if (!active || requestRef.current !== requestId) return;
        if (e instanceof ApiError && (e.status === 404 || e.status === 410)) {
          setLoadState("terminal");
        } else {
          setLoadState("retryable");
        }
      });
    return () => {
      active = false;
      requestRef.current += 1;
      callbackRequestRef.current += 1;
      interactionGenerationRef.current += 1;
      clearCopyTimer();
    };
  }, [clearCopyTimer, retryKey, token]);

  const handleCopy = useCallback(async () => {
    const copyGeneration = ++interactionGenerationRef.current;
    const copyToken = token;
    clearCopyTimer();
    setCopied(false);
    try {
      await navigator.clipboard.writeText(window.location.href);
      if (
        interactionGenerationRef.current !== copyGeneration ||
        tokenRef.current !== copyToken
      ) {
        return;
      }
      setCopied(true);
      copyTimerRef.current = window.setTimeout(() => {
        if (
          interactionGenerationRef.current === copyGeneration &&
          tokenRef.current === copyToken
        ) {
          copyTimerRef.current = null;
          setCopied(false);
        }
      }, 2000);
    } catch {
      /* 미지원 환경 무시 */
    }
    if (token) void postShareEvent(token, "clipboard_copy").catch(() => undefined);
  }, [clearCopyTimer, token]);

  // ── 상담 연결 레이어 (예약 링크가 없을 때도 버튼이 항상 다음 행동으로 이어지게) ──
  const handleCta = useCallback(() => {
    if (token) void postShareEvent(token, "cta_click").catch(() => undefined);
    // 예약 가능하면(설계사 영업시간 존재) 예약 페이지로 이동. 아니면 연락 레이어 열기.
    if (data?.actions.booking_url) {
      window.location.href = data.actions.booking_url;
      return;
    }
    setContactOpen((v) => !v); // 다시 누르면 접기
  }, [token, data?.actions.booking_url]);

  useEffect(() => {
    if (contactOpen) contactFirstActionRef.current?.focus();
  }, [contactOpen]);

  const handleCallback = useCallback(async () => {
    if (!token || callbackState === "sending") return;
    const callbackToken = token;
    const requestId = ++callbackRequestRef.current;
    setCallbackState("sending");
    try {
      const result = await postShareEvent(callbackToken, "callback_request");
      if (
        callbackRequestRef.current !== requestId ||
        tokenRef.current !== callbackToken
      ) return;
      if (
        result.recorded === true &&
        (result.notification === "created" || result.notification === "already_notified")
      ) {
        setCallbackState("sent");
        return;
      }
      setCallbackState("error");
    } catch {
      if (
        callbackRequestRef.current === requestId &&
        tokenRef.current === callbackToken
      ) {
        setCallbackState("error");
      }
    }
  }, [callbackState, token]);

  if (loadState === "loading") return <ShareSkeleton />;
  if (loadState === "terminal") return <ShareClosed />;
  if (loadState === "retryable" || !data) {
    return <ShareRetry onRetry={() => setRetryKey((key) => key + 1)} />;
  }
  const { snapshot, actions } = data;

  return (
    <ContentProtect className="relative mx-auto w-full max-w-md min-h-dvh flex flex-col bg-surface2">
      <Watermark text="인파 · 보장분석 공유" />
      <header className="px-5 pt-5 pb-3 bg-accent-tint">
        <div className="flex items-center gap-1.5 text-[13px] font-bold text-brand">
          <span className="text-[15px]">⌃</span> 인파
        </div>
      </header>

      <main className="flex-1 px-5 pb-6">
        <ShareSnapshotContent payload={snapshot} variant="public" />

        <section className="mt-4">
          <div className="rounded-xl border border-line bg-surface2 px-4 py-3 text-[12px] leading-5 text-ink3">
            인파가 등록된 보장 정보를 정리한 참고 자료입니다.
          </div>
        </section>

        {/* 클립보드 복사 */}
        <section className="mt-3">
          <button
            onClick={handleCopy}
            className="w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] font-semibold text-ink2 transition active:scale-[0.99]"
          >
            {copied ? "링크 복사됐어요!" : "이 링크 복사하기"}
          </button>
        </section>
      </main>

      {/* 하단 고정 CTA */}
      <div
        className="sticky bottom-0 z-20 bg-surface/95 backdrop-blur border-t border-line px-4 pt-3"
        style={{ paddingBottom: "max(14px, env(safe-area-inset-bottom))" }}
      >
        {contactOpen && !actions.booking_url && (
          <div id="share-contact-panel" role="region" aria-label="담당 설계사 연락" className="mb-3 rounded-2xl border border-line bg-surface px-4 py-4">
            {callbackState === "sent" ? (
              <p className="text-[14px] font-semibold text-ink text-center leading-6">
                요청을 전달했어요. 곧 연락드릴 거예요.
              </p>
            ) : (
              <>
                <p className="text-[13px] font-semibold text-ink2">
                  담당 설계사에게 바로 연결해 드릴게요.
                </p>
                <div className="mt-2.5 space-y-2">
                  {actions.planner_contact && (
                    <div className="flex gap-2">
                      <a
                        ref={(node) => { contactFirstActionRef.current = node; }}
                        href={`tel:${actions.planner_contact}`}
                        className="flex-1 rounded-xl border border-line bg-surface2 px-3 py-2.5 text-center text-[14px] font-bold text-ink"
                      >
                        전화하기
                      </a>
                      <a
                        href={`sms:${actions.planner_contact}`}
                        className="flex-1 rounded-xl border border-line bg-surface2 px-3 py-2.5 text-center text-[14px] font-bold text-ink"
                      >
                        문자하기
                      </a>
                    </div>
                  )}
                  <button
                    ref={!actions.planner_contact ? (node) => { contactFirstActionRef.current = node; } : undefined}
                    onClick={() => void handleCallback()}
                    disabled={callbackState === "sending"}
                    className="w-full rounded-xl bg-brand text-white px-3 py-2.5 text-[14px] font-bold active:scale-[0.99] transition disabled:opacity-60"
                  >
                    {callbackState === "sending"
                      ? "요청 전달 중…"
                      : callbackState === "error"
                        ? "연락 요청 다시 남기기"
                        : "연락 요청 남기기"}
                  </button>
                </div>
                {callbackState === "error" && (
                  <p role="alert" className="mt-2 text-center text-[12px] leading-5 text-ink2">
                    연결이 잠시 원활하지 않아요. 다시 누르면 연락 요청을 이어갈 수 있어요.
                  </p>
                )}
                <p className="mt-2 text-[11px] text-ink3 leading-4 text-center">
                  요청을 남기면 담당 설계사가 확인하고 연락드려요.
                </p>
              </>
            )}
          </div>
        )}
        <button
          onClick={handleCta}
          data-booking-url={actions.booking_url ?? ""}
          aria-expanded={actions.booking_url ? undefined : contactOpen}
          aria-controls={actions.booking_url ? undefined : "share-contact-panel"}
          className="w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 active:scale-[0.99] transition"
        >
          {actions.booking_url ? "바로 상담 예약하기 →" : "담당 설계사에게 물어보기"}
        </button>
      </div>
    </ContentProtect>
  );
}
