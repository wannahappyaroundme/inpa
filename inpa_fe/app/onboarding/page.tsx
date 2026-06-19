"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { attestOnboarding, ApiError } from "@/lib/api";

interface TourStep {
  emoji: string;
  title: string;
  desc: string;
  detail: string;
}

// 핵심 기능 투어: 고객 등록 → 증권 OCR → 보장분석 히트맵 → 갈아타기 → 공유
const STEPS: TourStep[] = [
  {
    emoji: "🧑‍🤝‍🧑",
    title: "1. 고객을 등록하세요",
    desc: "이름·생년월일만 있으면 시작이에요.",
    detail:
      "발굴한 잠재 고객도, 기존 고객도 한 곳에서 관리합니다. 태그·색상으로 분류하고 가족 구성까지 묶어 볼 수 있어요.",
  },
  {
    emoji: "📄",
    title: "2. 증권을 사진으로 올리면 OCR이 읽어요",
    desc: "보험사·상품·담보를 자동으로 정리합니다.",
    detail:
      "여러 보험사 증권의 담보명을 표준 담보 '틀'로 정규화해, 회사가 달라도 같은 기준으로 비교할 수 있게 맞춰줍니다. (AI 초안 — 최종 확인은 설계사님)",
  },
  {
    emoji: "🗺️",
    title: "3. 보장분석 히트맵으로 한눈에",
    desc: "담보별 보유 현황을 색으로 봅니다.",
    detail:
      "100개 이상 담보 '틀' 위에서 보유 금액을 표시합니다. 충분/부족 같은 판단과 권유는 설계사님 몫이에요 — 인파는 사실만 정리합니다.",
  },
  {
    emoji: "🔁",
    title: "4. 갈아타기 비교표를 자동으로",
    desc: "기존 vs 제안을 나란히 정리합니다.",
    detail:
      "승환(갈아타기)을 비교안내 자료로 합법적으로 정리해, 부당승환 리스크를 줄입니다. 생성물에는 'AI 초안·최종책임 설계사' 면책이 항상 붙어요.",
  },
  {
    emoji: "📤",
    title: "5. 고객에게 공유하세요",
    desc: "링크 또는 클립보드 복사로 전달합니다.",
    detail:
      "자동 발송은 하지 않아요. 안내 자료를 복사하거나 카톡을 열어 직접 보내는 데까지 도와드립니다. 마무리(클로징)는 설계사님이 준비하세요.",
  },
];

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center justify-center gap-2">
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`h-2 rounded-full transition-all ${
            i === current ? "w-6 bg-[var(--brand)]" : "w-2 bg-[var(--line-2)]"
          }`}
        />
      ))}
    </div>
  );
}

export default function OnboardingPage() {
  const ready = useAuthGuard();
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!ready) return null;

  const isLast = step === STEPS.length - 1;
  const current = STEPS[step];

  async function finish() {
    setError(null);
    setSaving(true);
    try {
      await attestOnboarding();
      router.replace("/home");
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : "저장 중 오류가 발생했습니다.";
      setError(msg || "저장 중 오류가 발생했습니다.");
      setSaving(false);
    }
  }

  function next() {
    if (isLast) {
      finish();
    } else {
      setStep((s) => Math.min(s + 1, STEPS.length - 1));
    }
  }

  return (
    <div className="min-h-dvh bg-[var(--surface-2)] flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        {/* 헤더 */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <svg viewBox="0 0 48 48" width="28" height="28" aria-hidden>
              <path d="M6 34 Q24 14 42 34" fill="none" stroke="#12B5A4" strokeWidth="6" strokeLinecap="round" />
              <path d="M12 33 Q24 3 36 33" fill="none" stroke="var(--brand)" strokeWidth="3.4" strokeLinecap="round" />
              <circle cx="24" cy="22" r="2.7" fill="var(--brand)" />
            </svg>
            <span className="font-extrabold text-[18px] text-[var(--brand-ink)]">인파</span>
          </div>
          <button
            onClick={finish}
            disabled={saving}
            className="text-[13px] text-[var(--ink-3)] hover:text-[var(--brand)] transition disabled:opacity-50"
          >
            건너뛰기
          </button>
        </div>

        {/* 투어 카드 */}
        <div className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] shadow-sm p-7">
          <div className="text-[52px] leading-none mb-4">{current.emoji}</div>
          <h1 className="text-[22px] font-extrabold text-[var(--ink)] leading-tight">
            {current.title}
          </h1>
          <p className="mt-2 text-[15px] font-semibold text-[var(--brand)]">{current.desc}</p>
          <p className="mt-3 text-[14px] leading-6 text-[var(--ink-2)]">{current.detail}</p>

          {error && (
            <div className="mt-4 p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">
              {error}
            </div>
          )}

          <div className="mt-7">
            <StepDots current={step} total={STEPS.length} />
          </div>

          <div className="mt-6 flex items-center gap-3">
            {step > 0 && (
              <button
                onClick={() => setStep((s) => Math.max(s - 1, 0))}
                disabled={saving}
                className="flex-1 py-3 rounded-xl border border-[var(--line)] text-[14px] font-semibold text-[var(--ink-2)] min-h-[48px] hover:bg-[var(--surface-2)] transition disabled:opacity-50"
              >
                이전
              </button>
            )}
            <button
              onClick={next}
              disabled={saving}
              className="flex-[2] py-3 rounded-xl bg-[var(--brand)] text-white font-bold text-[15px] min-h-[48px] hover:opacity-90 transition disabled:opacity-60 flex items-center justify-center gap-2"
            >
              {saving ? (
                <>
                  <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  시작하는 중...
                </>
              ) : isLast ? (
                "인파 시작하기"
              ) : (
                "다음"
              )}
            </button>
          </div>
        </div>

        {/* 면책 (정직성 레드라인) */}
        <p className="mt-5 px-1 text-[12px] leading-5 text-[var(--muted)]">
          인파의 분석·비교 자료는 <b className="text-[var(--ink-3)]">AI 초안</b>이며, 보장 충분 여부 등
          판단과 권유, 최종 책임은 담당 설계사에게 있습니다.
        </p>
      </div>
    </div>
  );
}
