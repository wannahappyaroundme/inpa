"use client";

// 의견 위젯 — 우하단 둥근 FAB(채팅 아이콘 + "의견"). 클릭할 때만 열린다(자동 팝업/뱃지 없음).
// 로그인 화면(app-nav) + 랜딩(익명)에 마운트. 고객 대면 토큰 페이지·/admin·로그인·시네마 랜딩엔 미마운트.
// 라이트 고정(서비스 화면 규칙, dark: 미사용). 카피: 쉬운 말·긍정 표현·em-dash 금지.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { MessageCircle, Star, X, ArrowLeft, Send } from "lucide-react";
import { InpaMark } from "./inpa-logo";
import { submitFeedback, type FeedbackPayload, type InquiryCategory } from "@/lib/api";

type Mode = "feedback" | "feature" | "bug" | "other";
type View = "chips" | "form" | "done";

const CHOICES: { mode: Mode; label: string; desc: string }[] = [
  { mode: "feedback", label: "이용 의견", desc: "써보니 어떠셨나요" },
  { mode: "feature", label: "기능 제안", desc: "있으면 좋겠어요" },
  { mode: "bug", label: "불편 신고", desc: "이상한 점이 있어요" },
];

function collectMeta() {
  if (typeof window === "undefined") return {};
  return {
    path: window.location.pathname,
    user_agent: navigator.userAgent,
    viewport: `${window.innerWidth}×${window.innerHeight}`,
  };
}

export function FeedbackWidget({ anonymous = false }: { anonymous?: boolean }) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>("chips");
  const [mode, setMode] = useState<Mode>("feedback");
  const [rating, setRating] = useState(0);
  const [body, setBody] = useState("");
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const panelRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);

  const reset = useCallback(() => {
    setView("chips");
    setMode("feedback");
    setRating(0);
    setBody("");
    setEmail("");
    setError(null);
    setSending(false);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
  }, []);

  // 닫힐 때 상태 초기화(다음에 열면 처음부터).
  useEffect(() => {
    if (!open) {
      const t = setTimeout(reset, 200);
      return () => clearTimeout(t);
    }
  }, [open, reset]);

  // Escape 로 닫기 + 열릴 때 패널로 포커스 이동.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    const t = setTimeout(() => panelRef.current?.focus(), 30);
    return () => {
      document.removeEventListener("keydown", onKey);
      clearTimeout(t);
    };
  }, [open, close]);

  // form 진입 시 본문 입력칸으로 포커스.
  useEffect(() => {
    if (view === "form") {
      const t = setTimeout(() => bodyRef.current?.focus(), 40);
      return () => clearTimeout(t);
    }
  }, [view]);

  function pickMode(m: Mode) {
    setMode(m);
    setBody("");
    setRating(0);
    setError(null);
    setView("form");
  }

  const canSubmit =
    body.trim().length > 0 && (mode !== "feedback" || rating > 0) && !sending;

  async function handleSubmit() {
    if (!canSubmit) return;
    setSending(true);
    setError(null);
    const payload: FeedbackPayload = {
      category: mode as InquiryCategory,
      body: body.trim(),
    };
    if (mode === "feedback") payload.rating = rating;
    if (mode === "bug") payload.meta = collectMeta();
    if (anonymous && email.trim()) payload.contact_email = email.trim();
    try {
      await submitFeedback(payload);
      setView("done");
    } catch {
      setError("보내지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSending(false);
    }
  }

  // 모바일 오프셋: 인증 화면은 하단 탭바(76px) 위로, 랜딩(익명)은 하단 여백만. sm+ 은 bottom-6.
  const fabBottom = anonymous
    ? "bottom-[calc(1rem_+_env(safe-area-inset-bottom))] sm:bottom-6"
    : "bottom-[calc(76px_+_1rem_+_env(safe-area-inset-bottom))] sm:bottom-6";
  const panelBottom = anonymous
    ? "bottom-[calc(1rem_+_env(safe-area-inset-bottom))] sm:bottom-6"
    : "bottom-[calc(76px_+_1rem_+_env(safe-area-inset-bottom))] sm:bottom-6";

  return (
    <>
      {/* FAB — 클릭할 때만 패널이 열린다. z-40 (모달 z-50 아래). */}
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="인파팀에게 의견 보내기"
          className={`fixed right-4 sm:right-6 ${fabBottom} z-40 flex items-center gap-2 rounded-full bg-brand text-white pl-4 pr-5 h-12 shadow-card hover:bg-brand-ink transition`}
        >
          <MessageCircle className="w-5 h-5" strokeWidth={2.2} />
          <span className="text-[14px] font-bold">의견</span>
        </button>
      )}

      {open && (
        <>
          {/* 배경 — 클릭하면 닫힘 */}
          <div
            className="fixed inset-0 z-40 bg-black/20"
            onClick={close}
            aria-hidden
          />

          {/* 패널 */}
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label="인파팀에게 의견 보내기"
            tabIndex={-1}
            className={`fixed right-3 left-3 sm:left-auto sm:right-6 ${panelBottom} z-50 sm:w-[380px] max-h-[80vh] flex flex-col rounded-2xl bg-surface border border-line shadow-card outline-none overflow-hidden`}
          >
            {/* 헤더 */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-line shrink-0">
              {view === "form" ? (
                <button
                  type="button"
                  onClick={() => setView("chips")}
                  aria-label="뒤로"
                  className="w-8 h-8 -ml-1 rounded-lg flex items-center justify-center text-ink2 hover:bg-surface2 transition"
                >
                  <ArrowLeft className="w-[18px] h-[18px]" />
                </button>
              ) : (
                <InpaMark size={22} />
              )}
              <span className="flex-1 text-[15px] font-extrabold text-ink">
                인파팀에게 들려주세요
              </span>
              <button
                type="button"
                onClick={close}
                aria-label="닫기"
                className="w-8 h-8 rounded-lg flex items-center justify-center text-ink3 hover:bg-surface2 hover:text-ink transition"
              >
                <X className="w-[18px] h-[18px]" />
              </button>
            </div>

            {/* 본문 (스크롤) */}
            <div className="flex-1 overflow-y-auto px-4 py-4">
              {view === "chips" && (
                <div className="space-y-3">
                  <div className="rounded-2xl rounded-tl-md bg-brand-soft text-ink px-3.5 py-2.5 text-[13.5px] leading-6 max-w-[85%]">
                    안녕하세요, 인파팀이에요. 어떤 이야기를 들려주실래요?
                  </div>
                  <div className="space-y-2 pt-1">
                    {CHOICES.map((c) => (
                      <button
                        key={c.mode}
                        type="button"
                        onClick={() => pickMode(c.mode)}
                        className="w-full text-left rounded-xl border border-line px-3.5 py-2.5 hover:border-brand hover:bg-brand-soft transition"
                      >
                        <div className="text-[14px] font-bold text-ink">{c.label}</div>
                        <div className="text-[12px] text-ink3 mt-0.5">{c.desc}</div>
                      </button>
                    ))}
                    {/* 1:1 문의 — 로그인 상태면 문의 작성으로, 익명이면 이 자리에서 남기기 */}
                    {anonymous ? (
                      <button
                        type="button"
                        onClick={() => pickMode("other")}
                        className="w-full text-left rounded-xl border border-line px-3.5 py-2.5 hover:border-brand hover:bg-brand-soft transition"
                      >
                        <div className="text-[14px] font-bold text-ink">1:1 문의</div>
                        <div className="text-[12px] text-ink3 mt-0.5">직접 물어보고 싶어요</div>
                      </button>
                    ) : (
                      <Link
                        href="/boards/inquiry/new"
                        onClick={close}
                        className="block rounded-xl border border-line px-3.5 py-2.5 hover:border-brand hover:bg-brand-soft transition"
                      >
                        <div className="text-[14px] font-bold text-ink">1:1 문의</div>
                        <div className="text-[12px] text-ink3 mt-0.5">문의 내역에서 답변을 받아볼 수 있어요</div>
                      </Link>
                    )}
                  </div>
                </div>
              )}

              {view === "form" && (
                <div className="space-y-3">
                  {mode === "feedback" && (
                    <div>
                      <div className="text-[13px] font-semibold text-ink2 mb-1.5">
                        별점을 남겨주세요
                      </div>
                      <div className="flex gap-1" role="radiogroup" aria-label="별점">
                        {[1, 2, 3, 4, 5].map((n) => (
                          <button
                            key={n}
                            type="button"
                            role="radio"
                            aria-checked={rating === n}
                            aria-label={`${n}점`}
                            onClick={() => setRating(n)}
                            className="p-0.5"
                          >
                            <Star
                              className={`w-7 h-7 transition ${
                                n <= rating ? "text-warn fill-warn" : "text-line"
                              }`}
                              strokeWidth={1.8}
                            />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  <textarea
                    ref={bodyRef}
                    value={body}
                    onChange={(e) => setBody(e.target.value.slice(0, 2000))}
                    rows={4}
                    placeholder={
                      mode === "bug"
                        ? "어떤 점이 불편했는지 편하게 적어주세요"
                        : mode === "feature"
                        ? "있으면 좋겠다 싶은 기능을 적어주세요"
                        : mode === "other"
                        ? "궁금한 점을 자유롭게 적어주세요"
                        : "느낀 점을 자유롭게 적어주세요"
                    }
                    className="w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink outline-none focus:border-brand resize-none leading-6"
                  />

                  {mode === "bug" && (
                    <p className="text-[12px] text-ink3 leading-5">
                      빠른 확인을 위해 지금 보고 계신 화면 주소가 함께 전달돼요.
                    </p>
                  )}

                  {anonymous && (
                    <div>
                      <label className="block text-[13px] font-semibold text-ink2 mb-1.5">
                        답변 받을 이메일 (선택)
                      </label>
                      <input
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="name@example.com"
                        className="w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink outline-none focus:border-brand"
                      />
                    </div>
                  )}

                  {error && (
                    <div className="rounded-xl bg-danger-tint border border-line px-3 py-2 text-[13px] text-danger-ink">
                      {error}
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={handleSubmit}
                    disabled={!canSubmit}
                    className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-brand text-white text-[14px] font-bold py-3 disabled:opacity-50 hover:bg-brand-ink transition"
                  >
                    <Send className="w-4 h-4" strokeWidth={2.2} />
                    {sending ? "보내는 중..." : "보내기"}
                  </button>
                </div>
              )}

              {view === "done" && (
                <div className="space-y-3 py-2">
                  <div className="flex items-center gap-2">
                    <InpaMark size={26} live />
                    <span className="text-[15px] font-extrabold text-ink">고맙습니다</span>
                  </div>
                  <div className="rounded-2xl rounded-tl-md bg-brand-soft text-ink px-3.5 py-2.5 text-[13.5px] leading-6">
                    {anonymous
                      ? email.trim()
                        ? "잘 받았어요. 이메일로 답변드릴게요."
                        : "잘 받았어요. 이메일을 남겨주시면 답변드려요."
                      : "잘 받았어요. 답변이 오면 알림으로 알려드려요."}
                  </div>
                  {!anonymous && (
                    <Link
                      href="/boards/inquiry"
                      onClick={close}
                      className="block text-center rounded-xl border border-line px-3.5 py-2.5 text-[13.5px] font-semibold text-brand hover:bg-brand-soft transition"
                    >
                      문의 내역 보기
                    </Link>
                  )}
                  <button
                    type="button"
                    onClick={close}
                    className="w-full rounded-xl bg-surface2 text-ink2 text-[13.5px] font-semibold py-2.5 hover:bg-line transition"
                  >
                    닫기
                  </button>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
