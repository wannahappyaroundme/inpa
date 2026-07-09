"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { Typewriter } from "@/components/typewriter";
import { TypewriterSound } from "@/lib/typewriter-sound";
import { InpaMark } from "@/components/inpa-logo";
import {
  LandingHeader, TrustBar, FeaturesSection, FeatureShowcaseSection,
  DifferentiatorsSection, AudienceSection, HowItWorksSection,
  TrustSection, FinalCTASection, LandingFooter,
} from "@/components/landing-sections";
import {
  BrandDefinitionSection, PlannerJourneySection, SalesProcessMapSection,
  ClosingHeroSection, PersonaSection, PricingFourTiers,
} from "@/components/brand-story-sections";

// new.inpa.kr 시네마 랜딩 — 게이트(소리 허용) → 장면 6개(클릭 전환) → 스크롤 랜딩.
// 시안: landing_page.pdf p2~p14 / 스펙: docs/superpowers/specs/2026-07-07-new-inpa-cinematic-landing-design.md

type Beat = { text: string; mono?: boolean };
type Scene = {
  id: string;
  bg: "black" | "scatter" | "crowd" | "blue";
  beats: Beat[];
  instant?: boolean; // 사진·파랑 배경 장면: 타이핑 대신 줄 단위로 한 번에 등장 + 1.5배 큰 글씨 (PM 2026-07-08)
};

const SCENES: Scene[] = [
  { id: "definition", bg: "black", beats: [{ text: "人波 : 수많은 사람을 이르는 말" }] },
  { id: "problem", bg: "scatter", instant: true, beats: [
    { text: "오늘도 흩어진 고객 명단, 엑셀, 메모장, 카톡 사이를 헤매고 있나요?" },
    { text: "보험설계사의 업무는 늘 人波 속에 있습니다." },
  ]},
  { id: "reveal", bg: "black", beats: [{ text: "INPA : Insure Partner", mono: true }] },
  { id: "bridge", bg: "black", beats: [{ text: "人波 속에서 INPA가...", mono: true }] },
  { id: "crowd", bg: "crowd", instant: true, beats: [{ text: "수많은 인파 속, 흔들림 없는 안내" }] },
  { id: "promise", bg: "blue", instant: true, beats: [{ text: "오직 당신만을 위한 인슈어 파트너가 되어드립니다" }] },
];

const BG_IMAGES = ["/landing-new/scatter-bg.webp", "/landing-new/crowd-dark.webp"];

type Mode = "gate" | "film" | "landing";

export function CinemaLanding() {
  const [mode, setMode] = useState<Mode>("gate");
  const [sceneIdx, setSceneIdx] = useState(0);
  const [beatIdx, setBeatIdx] = useState(0);
  const [beatDone, setBeatDone] = useState(false);
  const [revealAll, setRevealAll] = useState(false);
  const [muted, setMuted] = useState(false);
  const soundRef = useRef<TypewriterSound | null>(null);

  const scene = SCENES[sceneIdx];

  // 다음 장면 배경 미리 받아 클릭 시 끊김 방지
  useEffect(() => {
    if (typeof window === "undefined") return;
    BG_IMAGES.forEach((src) => { const img = new Image(); img.src = src; });
  }, []);

  const start = useCallback((withSound: boolean) => {
    const s = new TypewriterSound();
    if (withSound) s.init(); // 사용자 제스처 안 — 자동재생 정책 통과 지점
    s.setMuted(!withSound);
    soundRef.current = s;
    setMuted(!withSound);
    setMode("film");
  }, []);

  const skipToLanding = useCallback(() => {
    setMode("landing");
    if (typeof window !== "undefined") window.scrollTo(0, 0);
  }, []);

  const advance = useCallback(() => {
    if (mode !== "film") return;
    if (!beatDone) { setRevealAll(true); return; } // 타이핑 중 클릭 = 문장 즉시 완성
    const s = SCENES[sceneIdx];
    if (beatIdx < s.beats.length - 1) {
      setBeatIdx((b) => b + 1); setBeatDone(false); setRevealAll(false);
      return;
    }
    if (sceneIdx < SCENES.length - 1) {
      setSceneIdx((i) => i + 1); setBeatIdx(0); setBeatDone(false); setRevealAll(false);
      return;
    }
    skipToLanding();
  }, [mode, beatDone, sceneIdx, beatIdx, skipToLanding]);

  // 키보드: Space / Enter / → 로 진행
  useEffect(() => {
    if (mode !== "film") return;
    const onKey = (e: KeyboardEvent) => {
      // 건너뛰기·음소거 버튼에 포커스가 있으면 버튼 동작이 우선(키보드 접근성)
      if ((e.target as HTMLElement | null)?.closest?.("button")) return;
      if (e.key === " " || e.key === "Enter" || e.key === "ArrowRight") { e.preventDefault(); advance(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode, advance]);

  // 사진 배경 장면(instant): 줄이 통째로 등장 — 등장 즉시 진행 가능 + 낮은 타건음 1회
  useEffect(() => {
    if (mode !== "film") return;
    if (!SCENES[sceneIdx].instant) return;
    setBeatDone(true);
    soundRef.current?.key(true);
  }, [mode, sceneIdx, beatIdx]);

  const toggleMute = useCallback(() => {
    setMuted((m) => {
      const next = !m;
      if (!next && soundRef.current && !soundRef.current.isReady) soundRef.current.init();
      soundRef.current?.setMuted(next);
      return next;
    });
  }, []);

  const bgClass = useMemo(() => {
    switch (scene.bg) {
      case "blue": return "bg-[var(--brand)]";
      case "black": case "scatter": case "crowd": default: return "bg-black";
    }
  }, [scene.bg]);

  if (mode === "landing") {
    return (
      <>
        <LandingHeader />
        <main>
          <BrandDefinitionSection />
          <PlannerJourneySection />
          <SalesProcessMapSection />
          <ClosingHeroSection />
          <TrustBar />
          <FeaturesSection />
          <FeatureShowcaseSection />
          <DifferentiatorsSection />
          <AudienceSection />
          <HowItWorksSection />
          <PersonaSection />
          <PricingFourTiers />
          <TrustSection />
          <FinalCTASection />
        </main>
        <LandingFooter />
      </>
    );
  }

  if (mode === "gate") {
    return (
      <div className="fixed inset-0 z-50 bg-black text-white flex flex-col items-center justify-center gap-10 px-6 text-center">
        <InpaMark size={72} live intense pColor="#FFFFFF" />
        <div>
          <p className="text-[15px] text-white/60">인파(Inpa)</p>
          <h1 className="mt-2 text-[24px] sm:text-[30px] font-extrabold tracking-tight">1분, 인파가 준비한 짧은 이야기</h1>
        </div>
        <div className="flex flex-col sm:flex-row gap-3">
          <button type="button" onClick={() => start(true)}
            className="px-7 py-4 rounded-2xl bg-white text-black font-bold text-[16px] min-h-[52px] hover:bg-white/90 transition">
            소리와 함께 시작하기
          </button>
          <button type="button" onClick={() => start(false)}
            className="px-7 py-4 rounded-2xl border border-white/30 text-white font-bold text-[16px] min-h-[52px] hover:bg-white/10 transition">
            조용히 보기
          </button>
        </div>
        <button type="button" onClick={skipToLanding} className="text-[14px] text-white/45 underline underline-offset-4 hover:text-white/70 transition">
          건너뛰고 서비스 소개 보기
        </button>
      </div>
    );
  }

  // mode === "film"
  return (
    <div role="button" tabIndex={0} onClick={advance} onKeyDown={() => {}}
      aria-label="화면을 누르면 다음 장면으로 넘어갑니다"
      className={`fixed inset-0 z-50 ${bgClass} text-white cursor-pointer select-none overflow-hidden transition-colors duration-700`}>
      {/* 배경 레이어 */}
      {scene.bg === "scatter" ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src="/landing-new/scatter-bg.webp" alt="" aria-hidden className="absolute inset-0 w-full h-full object-cover" />
      ) : null}
      {scene.bg === "crowd" ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src="/landing-new/crowd-dark.webp" alt="" aria-hidden className="absolute inset-0 w-full h-full object-cover opacity-90" />
      ) : null}
      {scene.bg === "blue" ? (
        <div className="absolute inset-0 flex items-center justify-center opacity-15">
          <InpaMark size={560} pColor="#FFFFFF" dotColor="#8D3B72" />
        </div>
      ) : null}

      {/* 상단 컨트롤 */}
      <div className="absolute top-0 inset-x-0 flex items-center justify-end gap-2 p-4 sm:p-6">
        <button type="button" aria-label={muted ? "소리 켜기" : "소리 끄기"}
          onClick={(e) => { e.stopPropagation(); toggleMute(); }}
          className="w-11 h-11 rounded-full border border-white/25 flex items-center justify-center text-white/70 hover:bg-white/10 transition">
          {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
        <button type="button" onClick={(e) => { e.stopPropagation(); skipToLanding(); }}
          className="px-4 h-11 rounded-full border border-white/25 text-[14px] font-semibold text-white/70 hover:bg-white/10 transition">
          건너뛰기
        </button>
      </div>

      {/* 자막(장면 텍스트) */}
      <div className="absolute inset-0 flex flex-col items-center justify-center px-6">
        <div className={scene.bg === "scatter" ? "text-[var(--ink)]" : "text-white"}>
          {scene.beats.slice(0, beatIdx + 1).map((b, i) => (
            <p key={`${scene.id}-${i}`}
              className={`text-center leading-relaxed ${b.mono ? "font-mono tracking-wide" : "font-bold"} ${
                scene.instant
                  ? (i === 0 && scene.beats.length > 1
                      ? "text-[23px] sm:text-[36px] text-[var(--ink-3)]" // 도입(질문) 줄: 살짝 회색 + 75% 크기 (PM)
                      : "text-[30px] sm:text-[48px]")
                  : "text-[20px] sm:text-[32px]"} ${
                i > 0 ? "mt-5 font-extrabold" : ""} ${i > 0 && i === beatIdx && scene.instant ? "line-rise" : ""}`}>
              {i < beatIdx ? b.text : scene.instant ? (
                i === 0 ? <span className="line-pop">{b.text}</span> : b.text
              ) : (
                <Typewriter
                  text={b.text}
                  active={mode === "film"}
                  revealAll={revealAll}
                  onChar={(ch) => soundRef.current?.key(ch === " ")}
                  onDone={() => { setBeatDone(true); soundRef.current?.ding(); }}
                />
              )}
            </p>
          ))}
        </div>
      </div>

      {/* 하단: 진행 도트 + 계속 힌트 */}
      <div className="absolute bottom-0 inset-x-0 flex flex-col items-center gap-4 p-6">
        <p className={`text-[13px] transition-opacity duration-500 ${beatDone ? "opacity-70" : "opacity-0"} ${scene.bg === "scatter" ? "text-[var(--ink-3)]" : "text-white/70"}`}>
          화면을 눌러 계속
        </p>
        <div className="flex gap-2" aria-hidden>
          {SCENES.map((s, i) => (
            <span key={s.id} className={`w-2 h-2 rounded-full transition ${i === sceneIdx ? "bg-[var(--danger)]" : scene.bg === "scatter" ? "bg-black/20" : "bg-white/25"}`} />
          ))}
        </div>
      </div>
    </div>
  );
}
