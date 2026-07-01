"use client";

// 랜딩 Phase B 경량 모션 — 라이브러리 없이 IntersectionObserver + rAF.
// prefers-reduced-motion 존중(즉시 최종 상태). 모션은 transform/opacity만(리플로우 없음).
import { useEffect, useRef, useState, type ReactNode } from "react";

function prefersReduced() {
  return typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function useInView<T extends HTMLElement>(immediate = false) {
  const ref = useRef<T>(null);
  // immediate=첫 화면(above-the-fold): SSR부터 is-in으로 렌더 → JS 없이도 즉시 보임(LCP 개선).
  const [inView, setInView] = useState(immediate);
  useEffect(() => {
    if (immediate) return;
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined" || prefersReduced()) {
      setInView(true);
      return;
    }
    const io = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setInView(true); io.disconnect(); } },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [immediate]);
  return { ref, inView };
}

/** 스크롤 진입 시 아래에서 떠오르며 페이드인. immediate=첫 화면은 숨기지 않고 즉시 렌더. */
export function Reveal({ children, className = "", delay = 0, immediate = false }: { children: ReactNode; className?: string; delay?: number; immediate?: boolean }) {
  const { ref, inView } = useInView<HTMLDivElement>(immediate);
  return (
    <div
      ref={ref}
      className={`reveal ${inView ? "is-in" : ""} ${className}`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

/** 뷰 진입 시 0 → to 카운트업(easeOutCubic). reduced-motion 시 즉시 최종값. */
export function CountUp({ to, suffix = "", duration = 1100 }: { to: number; suffix?: string; duration?: number }) {
  const { ref, inView } = useInView<HTMLSpanElement>();
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!inView) return;
    if (prefersReduced()) { setN(to); return; }
    let raf = 0;
    let startTs = 0;
    const step = (ts: number) => {
      if (!startTs) startTs = ts;
      const p = Math.min(1, (ts - startTs) / duration);
      setN(Math.round(to * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [inView, to, duration]);
  return <span ref={ref} className="tnum">{n}{suffix}</span>;
}
