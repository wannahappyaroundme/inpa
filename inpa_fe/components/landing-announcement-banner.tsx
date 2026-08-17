"use client";

/* 랜딩 맨 위 새 기능 공지 바.
 *
 * 문구·링크·저장 키를 모두 props 로 받아 다음 공지에도 그대로 재사용한다.
 * 저장 키에는 버전 문자열을 넣어 둔다(예: inpa_banner_consult_v1). 새 공지를 올릴 때
 * 키의 버전만 올리면 이전 공지를 닫아 둔 사람에게도 새 공지가 다시 보인다.
 *
 * 숨김 규칙 두 가지 (같은 저장 키를 서로 다른 저장소에 쓴다)
 *  - X 닫기: sessionStorage 에 기록 → 이번 방문 동안만 숨김(탭을 닫으면 다시 보인다).
 *  - 24시간 동안 보지 않기: localStorage 에 만료 시각(ms)을 저장 → 그 시각까지 숨김.
 *
 * 서버 렌더 시점에는 저장소를 읽을 수 없으므로 마운트 전에는 아무것도 그리지 않는다
 * (첫 렌더 결과가 서버와 어긋나지 않게 한다). 프라이빗 모드처럼 저장소 접근이 막힌
 * 환경에서도 화면이 멈추지 않도록 읽기·쓰기를 모두 try/catch 로 감싼다.
 */

import { X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

/** 상담 녹음·AI 핵심 메모 공개 공지(v1). 문구를 바꿀 땐 뒤의 버전을 올린다. */
export const CONSULTATION_BANNER_STORAGE_KEY = "inpa_banner_consult_v1"; // gitleaks:allow

const HIDE_FOR_A_DAY_MS = 24 * 60 * 60 * 1000;

export type LandingAnnouncementBannerProps = {
  /** 저장 키(버전 포함). 이번 방문 숨김과 24시간 숨김이 같은 키를 쓴다. */
  storageKey?: string;
  /** 화면 폭과 상관없이 늘 보이는 첫 문장. */
  headline?: string;
  /** 화면이 넓을 때만 덧붙이는 둘째 문장. */
  detail?: string;
  ctaLabel?: string;
  ctaHref?: string;
  /** 링크 클릭 계측처럼 바깥에서 붙이는 동작. */
  onCtaClick?: () => void;
};

/** 저장소에 남은 숨김 기록이 아직 살아 있는지 확인한다. */
function isHidden(storageKey: string): boolean {
  try {
    if (window.sessionStorage.getItem(storageKey)) return true;
  } catch {
    // 저장소를 읽지 못하면 공지를 그대로 보여준다.
  }
  try {
    const until = Number(window.localStorage.getItem(storageKey));
    if (Number.isFinite(until) && until > Date.now()) return true;
  } catch {
    // 위와 같음.
  }
  return false;
}

export function LandingAnnouncementBanner({
  storageKey = CONSULTATION_BANNER_STORAGE_KEY,
  headline = "상담 녹음과 AI 핵심 메모가 열렸어요.",
  detail = "상담을 마치면 핵심 내용이 메모로 정리됩니다.",
  ctaLabel = "무료로 시작하기",
  ctaHref = "/register",
  onCtaClick,
}: LandingAnnouncementBannerProps = {}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(!isHidden(storageKey));
  }, [storageKey]);

  const closeForVisit = useCallback(() => {
    setOpen(false);
    try {
      window.sessionStorage.setItem(storageKey, "closed");
    } catch {
      // 기록하지 못해도 이번 화면에서는 바로 사라진다.
    }
  }, [storageKey]);

  const hideForADay = useCallback(() => {
    setOpen(false);
    try {
      window.localStorage.setItem(storageKey, String(Date.now() + HIDE_FOR_A_DAY_MS));
    } catch {
      // 위와 같음.
    }
  }, [storageKey]);

  if (!open) return null;

  return (
    <section aria-label="새 기능 공지" className="bg-[var(--brand)] text-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2.5 sm:px-6 lg:px-8">
        <p className="flex w-full min-w-0 items-center gap-2 break-keep text-[13px] font-bold leading-5 sm:w-auto sm:flex-1 sm:text-sm">
          <span className="inline-flex shrink-0 items-center rounded-full bg-white/20 px-2 py-0.5 text-[11px] font-extrabold tracking-wide">
            NEW
          </span>
          <span className="break-keep">{headline}</span>
          <span className="hidden break-keep sm:inline"> {detail}</span>
        </p>

        <div className="ml-auto flex shrink-0 items-center gap-1">
          <a
            href={ctaHref}
            onClick={onCtaClick}
            className="inline-flex min-h-8 items-center justify-center rounded-full bg-white px-3 text-[13px] font-extrabold text-[var(--brand)] hover:bg-white/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            {ctaLabel}
          </a>
          <button
            type="button"
            onClick={hideForADay}
            className="inline-flex min-h-8 items-center rounded-lg px-2 text-[11px] font-semibold text-white/85 underline-offset-4 hover:text-white hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white sm:text-xs"
          >
            24시간 동안 보지 않기
          </button>
          <button
            type="button"
            onClick={closeForVisit}
            aria-label="공지 닫기"
            className="inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-white/85 hover:bg-white/15 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            <X size={16} aria-hidden />
          </button>
        </div>
      </div>
    </section>
  );
}
