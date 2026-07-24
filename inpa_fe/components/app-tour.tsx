"use client";

/* 첫 로그인 화면 안내(스포트라이트 투어).
 *
 * 동작: 화면 전체를 어둡게 깔고, 각 단계의 대상 요소만 밝게 비추면서
 * 말풍선으로 한 줄씩 설명한다. 다음/이전/건너뛰기, Esc=건너뛰기.
 * 대상은 data-tour 속성으로 찾는다(사이드바·하단 탭·홈 카드에 부착).
 * 화면에 없는 대상(예: 모바일에서 숨은 메뉴)은 그 단계만 건너뛴다.
 *
 * 완료/건너뛰기 시 completeTour() 로 서버에 기록(멱등) → 기기를 바꿔도
 * 다시 뜨지 않는다. 설정 > 계정의 '처음 안내 다시 보기'(/home?tour=1)로 재실행.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { completeTour } from "@/lib/api";

export type TourStep = {
  key: string;
  /** 후보 셀렉터 목록 — 화면에 보이는 첫 요소를 대상으로 삼는다 */
  targets: readonly string[];
  title: string;
  body: string;
};

/* 단계 정의 — 사이드바 순서(핵심 5개)+ 첫 행동 유도 1개, 총 6단계.
 * 렌더 카피 규칙: 쉬운 말, 긍정 안내, em-dash 금지. */
export const TOUR_STEPS: readonly TourStep[] = [
  {
    key: "home",
    targets: ['[data-tour="nav-home"]', '[data-tour="tab-home"]'],
    title: "대시보드",
    body: "이번 달 목표와 오늘 할 일이 한눈에 모여요. 매일 아침 여기서 시작해 보세요.",
  },
  {
    key: "customers",
    targets: ['[data-tour="nav-customers"]', '[data-tour="tab-customers"]'],
    title: "고객",
    body: "고객을 등록하면 DB, TA, FA, 청약 단계로 나눠 관리할 수 있어요. 연락할 때가 된 고객도 알려드려요.",
  },
  {
    key: "analysis",
    targets: ['[data-tour="nav-analysis"]', '[data-tour="tab-analysis"]'],
    title: "분석",
    body: "고객 증권을 올리면 보장을 같은 기준으로 자동 정리해 드려요. 부족한 보장은 색으로 바로 보여요.",
  },
  {
    key: "schedule",
    targets: ['[data-tour="nav-schedule"]', '[data-tour="tab-schedule"]'],
    title: "일정",
    body: "상담 예약 요청과 개인 일정을 달력 하나로 관리해요. 고객이 예약하면 여기로 알려드려요.",
  },
  {
    key: "sales",
    targets: ['[data-tour="nav-sales"]'],
    title: "영업",
    body: "고객 영업과 설계사 영업을 여기서 시작해요. 오늘 전화할 고객도 골라드려요.",
  },
  {
    key: "self-diagnosis",
    targets: ['[data-tour="self-diagnosis-card"]'],
    title: "첫 시작은 이 링크예요",
    body: "고객에게 무료 보장점검 링크를 보내 보세요. 고객이 증권을 올리면 자동으로 분석되고 내 고객 목록에 추가돼요.",
  },
] as const;

/** 인덱스를 단계 범위 안으로 고정 (테스트 대상 순수 함수) */
export function clampStepIndex(index: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(Math.max(index, 0), total - 1);
}

/** 화면에 실제로 보이는 단계만 남긴다 (테스트 주입용 finder) */
export function resolveVisibleSteps(
  steps: readonly TourStep[],
  find: (selector: string) => Element | null,
): { step: TourStep; el: Element }[] {
  const out: { step: TourStep; el: Element }[] = [];
  for (const step of steps) {
    for (const sel of step.targets) {
      const el = find(sel);
      if (el) {
        out.push({ step, el });
        break;
      }
    }
  }
  return out;
}

function isVisible(el: Element): boolean {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

type Rect = { top: number; left: number; width: number; height: number };

const PAD = 8; // 스포트라이트 여백(px)

export function AppTour({ onDone }: { onDone: () => void }) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const doneRef = useRef(false);

  const visible = useMemo(
    () =>
      resolveVisibleSteps(TOUR_STEPS, (sel) => {
        const el = document.querySelector(sel);
        return el && isVisible(el) ? el : null;
      }),
    [],
  );
  const total = visible.length;
  const current = visible[clampStepIndex(index, total)];

  const finish = useCallback(() => {
    if (doneRef.current) return;
    doneRef.current = true;
    completeTour().catch(() => {
      /* 기록 실패해도 화면 진행은 막지 않는다(다음 로그인 때 다시 안내) */
    });
    onDone();
  }, [onDone]);

  // 대상 위치 측정 + 리사이즈/스크롤 추적
  useEffect(() => {
    if (!current) return;
    const el = current.el;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    el.scrollIntoView({ block: "nearest" });
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [current]);

  // Esc = 건너뛰기, 좌우 화살표 이동
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish();
      if (e.key === "ArrowRight") setIndex((i) => clampStepIndex(i + 1, total));
      if (e.key === "ArrowLeft") setIndex((i) => clampStepIndex(i - 1, total));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [finish, total]);

  if (!current || !rect) return null;

  const isLast = clampStepIndex(index, total) === total - 1;

  // 말풍선 위치: 대상 오른쪽 우선, 공간 없으면 아래, 화면 밖으로 안 나가게 고정
  const vw = typeof window === "undefined" ? 1280 : window.innerWidth;
  const vh = typeof window === "undefined" ? 800 : window.innerHeight;
  const BUBBLE_W = Math.min(320, vw - 32);
  const spaceRight = vw - (rect.left + rect.width);
  const placeRight = spaceRight > BUBBLE_W + 32;
  const bubbleLeft = placeRight
    ? rect.left + rect.width + 16
    : Math.min(Math.max(16, rect.left), vw - BUBBLE_W - 16);
  const bubbleTop = placeRight
    ? Math.min(Math.max(16, rect.top - 8), vh - 220)
    : Math.min(rect.top + rect.height + 14, vh - 220);

  return (
    <div className="fixed inset-0 z-[80]" role="dialog" aria-modal="true" aria-label="화면 안내">
      {/* 스포트라이트: 대상만 밝게, 나머지는 어둡게 */}
      <div
        className="absolute rounded-2xl transition-all duration-300 ease-out"
        style={{
          top: rect.top - PAD,
          left: rect.left - PAD,
          width: rect.width + PAD * 2,
          height: rect.height + PAD * 2,
          boxShadow: "0 0 0 9999px rgba(9, 14, 26, 0.62)",
        }}
        aria-hidden
      />
      {/* 클릭 가드(안내 중 다른 곳 눌림 방지) */}
      <div className="absolute inset-0" onClick={(e) => e.stopPropagation()} aria-hidden />

      {/* 말풍선 */}
      <div
        className="absolute rounded-2xl bg-white shadow-xl border border-line p-4 transition-all duration-300 ease-out"
        style={{ top: bubbleTop, left: bubbleLeft, width: BUBBLE_W }}
      >
        <div className="text-[11px] font-bold text-brand mb-1 tnum">
          {clampStepIndex(index, total) + 1} / {total}
        </div>
        <h2 className="text-[15px] font-extrabold text-ink break-keep">{current.step.title}</h2>
        <p className="mt-1.5 text-[13px] leading-5 text-ink2 break-keep">{current.step.body}</p>

        <div className="mt-3 flex items-center justify-between">
          <button
            type="button"
            onClick={finish}
            className="text-[12px] font-semibold text-muted hover:text-ink2 min-h-9 px-1"
          >
            건너뛰기
          </button>
          <div className="flex items-center gap-2">
            {clampStepIndex(index, total) > 0 && (
              <button
                type="button"
                onClick={() => setIndex((i) => clampStepIndex(i - 1, total))}
                className="min-h-9 rounded-xl border border-line px-3 text-[13px] font-bold text-ink2 hover:bg-surface2"
              >
                이전
              </button>
            )}
            <button
              type="button"
              onClick={() => (isLast ? finish() : setIndex((i) => clampStepIndex(i + 1, total)))}
              className="min-h-9 rounded-xl bg-brand px-4 text-[13px] font-bold text-white hover:bg-brand-ink"
            >
              {isLast ? "시작하기" : "다음"}
            </button>
          </div>
        </div>

        {/* 진행 점 */}
        <div className="mt-3 flex items-center gap-1.5" aria-hidden>
          {visible.map((s, i) => (
            <span
              key={s.step.key}
              className={`h-1.5 rounded-full transition-all ${
                i === clampStepIndex(index, total) ? "w-4 bg-brand" : "w-1.5 bg-line"
              }`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
