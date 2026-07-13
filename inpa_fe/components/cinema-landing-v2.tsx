"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { track } from "@vercel/analytics";
import { TypewriterSound2 } from "@/lib/typewriter-sound2";
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

// 시네마 랜딩 v2 (/version 미리보기) — v1(cinema-landing.tsx)은 불변.
// 업그레이드: 소등 의식 → 크로스 디졸브 → 장면별 리듬 → 슬로우 푸시인/비네트 →
// 신호등 점 소생 → 타이포 타이틀 승격(명조·혼합 폰트) → "불 켜짐" 엔딩 → 계측/UTM.
// 협의체 기록: docs/superpowers/specs/2026-07-10-cinema-landing-v2-upgrade-council.md

type Beat = { text: string };
type Scene = {
  id: string;
  bg: "black" | "scatter" | "crowd" | "blue";
  beats: Beat[];
  instant?: boolean;   // 사진·파랑 배경: 줄 단위 등장 + 큰 글씨
  emphasize?: boolean; // 완성 후 '人波'만 밝게 남김
  mono?: boolean;      // 타자기체(영문만 mono, 한글은 Pretendard + tracking)
  charMs?: number;     // 장면별 타속(리듬 차등)
};

const SCENES: Scene[] = [
  { id: "definition", bg: "black", emphasize: true, charMs: 85, beats: [{ text: "人波 : 수많은 사람을 이르는 말" }] },
  { id: "problem", bg: "scatter", instant: true, beats: [
    { text: "오늘도 흩어진 고객 명단, 엑셀, 메모장, 카톡 사이를 헤매고 있나요?" },
    { text: "보험설계사의 업무는 늘 人波 속에 있습니다." },
  ]},
  { id: "reveal", bg: "black", mono: true, charMs: 55, beats: [{ text: "INPA : Insurance Partner" }] },
  { id: "bridge", bg: "black", mono: true, charMs: 70, beats: [{ text: "人波 속에서 INPA가..." }] },
  { id: "crowd", bg: "crowd", instant: true, beats: [{ text: "수많은 인파 속, 흔들림 없는 안내" }] },
  { id: "promise", bg: "blue", instant: true, beats: [{ text: "오직 당신만을 위한 인슈어 파트너가 되어드립니다" }] },
];

const BG_IMAGES = ["/landing-new/scatter-bg.webp", "/landing-new/crowd-dark.webp"];
const PAUSE_AFTER = new Set([".", ",", "?", "!", ":", "…"]);

function cinemaTrack(name: string, data?: Record<string, string>) {
  try { track(name, { version: "v2", ...data }); } catch { /* 계측 실패는 경험에 영향 없음 */ }
}

function reducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** v2 타자기: 글자를 span 단위로 그려 영문/한글 혼합 폰트를 지원한다. */
function TypewriterV2({ text, active, revealAll, charMs = 70, charClass, onChar, onDone }: {
  text: string;
  active: boolean;
  revealAll: boolean;
  charMs?: number;
  charClass?: (ch: string) => string;
  onChar?: (ch: string) => void;
  onDone?: () => void;
}) {
  const [count, setCount] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const doneRef = useRef(false);
  const cbRef = useRef({ onChar, onDone });
  cbRef.current = { onChar, onDone };

  useEffect(() => { setCount(0); doneRef.current = false; }, [text]);

  useEffect(() => {
    if (!active) return;
    if (revealAll || reducedMotion()) {
      setCount(text.length);
      if (!doneRef.current) { doneRef.current = true; cbRef.current.onDone?.(); }
      return;
    }
    let i = 0;
    const tick = () => {
      if (i >= text.length) {
        if (!doneRef.current) { doneRef.current = true; cbRef.current.onDone?.(); }
        return;
      }
      const ch = text[i];
      i += 1;
      setCount(i);
      cbRef.current.onChar?.(ch);
      const pause = PAUSE_AFTER.has(ch) ? 340 : 0;
      const jitter = Math.random() * 40 - 20;
      timerRef.current = setTimeout(tick, charMs + pause + jitter);
    };
    timerRef.current = setTimeout(tick, 160);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [text, active, revealAll, charMs]);

  return (
    <>
      {Array.from(text.slice(0, count)).map((ch, i) => (
        <span key={i} className={charClass?.(ch) ?? undefined}>{ch}</span>
      ))}
      {count < text.length && <span className="tw-cursor" aria-hidden />}
    </>
  );
}

/** 영문·숫자·기호·공백만 타자기체, 한글은 Pretendard + 자간(혼합 베이스라인 어긋남 방지). */
const monoCharClass = (ch: string) => (/[A-Za-z0-9:.\s]/.test(ch) ? "font-mono" : "tracking-[0.08em]");

/** S1 완성 후: "人波"만 밝게 남기고 나머지를 가라앉힌다. */
function EmphasizedDefinition({ text }: { text: string }) {
  const idx = text.indexOf("人波");
  if (idx !== 0) return <>{text}</>;
  return (
    <>
      <span>人波</span>
      <span className="cine2-dim">{text.slice(2)}</span>
    </>
  );
}

type Mode = "gate" | "dimming" | "film" | "closing" | "landing";

export function CinemaLandingV2() {
  const [mode, setMode] = useState<Mode>("gate");
  const [sceneIdx, setSceneIdx] = useState(0);
  const [beatIdx, setBeatIdx] = useState(0);
  const [beatDone, setBeatDone] = useState(false);
  const [revealAll, setRevealAll] = useState(false);
  const [textOut, setTextOut] = useState(false);      // 전환 중 텍스트 페이드아웃
  const [hintVisible, setHintVisible] = useState(false); // "화면을 눌러 계속" 지연 노출
  const [muted, setMuted] = useState(false);
  const soundRef = useRef<TypewriterSound2 | null>(null);
  const transitioningRef = useRef(false);

  const scene = SCENES[sceneIdx];
  const filmVisible = mode === "film" || mode === "closing";

  useEffect(() => {
    if (typeof window === "undefined") return;
    BG_IMAGES.forEach((src) => { const img = new Image(); img.src = src; });
  }, []);

  // 장면 도달 계측
  useEffect(() => {
    if (mode !== "film") return;
    cinemaTrack("cinema_scene", { id: SCENES[sceneIdx].id });
  }, [mode, sceneIdx]);

  // 힌트 1.2초 지연(문장을 음미할 침묵)
  useEffect(() => {
    if (!beatDone) { setHintVisible(false); return; }
    const t = setTimeout(() => setHintVisible(true), 1200);
    return () => clearTimeout(t);
  }, [beatDone]);

  const start = useCallback((withSound: boolean) => {
    const s = new TypewriterSound2();
    if (withSound) s.init(); // 사용자 제스처 안 — 자동재생 정책 통과 지점
    s.setMuted(!withSound);
    soundRef.current = s;
    setMuted(!withSound);
    cinemaTrack("cinema_gate", { choice: withSound ? "sound" : "quiet" });
    if (reducedMotion()) { setMode("film"); return; }
    setMode("dimming"); // 소등 의식: 게이트 400ms 페이드아웃 → 완전 암전 800ms
    setTimeout(() => setMode("film"), 1200);
  }, []);

  const skipToLanding = useCallback((fromGate = false) => {
    if (fromGate) cinemaTrack("cinema_gate", { choice: "skip" });
    setMode("landing");
    if (typeof window !== "undefined") window.scrollTo(0, 0);
  }, []);

  // "불 켜짐" 엔딩: 텍스트 잦아듦 → 흰빛 확장 → 랜딩 (reduced-motion은 즉시)
  const startClosing = useCallback(() => {
    cinemaTrack("cinema_complete");
    if (typeof window !== "undefined") window.scrollTo(0, 0);
    if (reducedMotion()) { setMode("landing"); return; }
    setMode("closing");
    setTimeout(() => soundRef.current?.finale(), 300);
    setTimeout(() => setMode("landing"), 1350);
  }, []);

  const advance = useCallback(() => {
    if (mode !== "film" || transitioningRef.current) return;
    if (!beatDone) { setRevealAll(true); return; } // 타이핑 중 클릭 = 문장 즉시 완성
    const s = SCENES[sceneIdx];
    const lastBeat = beatIdx >= s.beats.length - 1;
    const lastScene = sceneIdx >= SCENES.length - 1;
    if (lastBeat && lastScene) { startClosing(); return; }
    // 크로스 디졸브: 텍스트 220ms 페이드아웃 후 다음 비트/장면
    transitioningRef.current = true;
    setTextOut(true);
    setTimeout(() => {
      if (lastBeat) { setSceneIdx((i) => i + 1); setBeatIdx(0); }
      else setBeatIdx((b) => b + 1);
      setBeatDone(false); setRevealAll(false); setTextOut(false);
      transitioningRef.current = false;
    }, 220);
  }, [mode, beatDone, sceneIdx, beatIdx, startClosing]);

  // 사진·파랑 장면(instant): 줄이 통째로 등장 — 즉시 진행 가능 + 낮은 타건음 1회
  useEffect(() => {
    if (mode !== "film" || textOut) return;
    if (!SCENES[sceneIdx].instant) return;
    setBeatDone(true);
    soundRef.current?.key(true);
  }, [mode, sceneIdx, beatIdx, textOut]);

  // 키보드: Space / Enter / → (버튼 포커스 시 버튼 동작 우선)
  useEffect(() => {
    if (mode !== "film") return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement | null)?.closest?.("button")) return;
      if (e.key === " " || e.key === "Enter" || e.key === "ArrowRight") { e.preventDefault(); advance(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode, advance]);

  const toggleMute = useCallback(() => {
    setMuted((m) => {
      const next = !m;
      if (!next && soundRef.current && !soundRef.current.isReady) soundRef.current.init();
      soundRef.current?.setMuted(next);
      return next;
    });
  }, []);

  // 랜딩 CTA: 계측 + UTM 부착(www 가입까지 유입 귀속; 프록시가 쿼리를 보존한다)
  const onLandingClickCapture = useCallback((e: React.MouseEvent) => {
    const a = (e.target as HTMLElement).closest?.("a");
    if (!a) return;
    const href = a.getAttribute("href") ?? "";
    if (!href.includes("/register") && !href.includes("/login")) return;
    try {
      const url = new URL(href, window.location.origin);
      if (!url.searchParams.has("utm_source")) {
        url.searchParams.set("utm_source", "new_inpa_kr");
        url.searchParams.set("utm_medium", "brand_landing");
        url.searchParams.set("utm_campaign", "cinema_v2");
        a.setAttribute("href", `${url.pathname}${url.search}`);
      }
    } catch { /* 원본 href 유지 */ }
    cinemaTrack("cinema_cta", { href });
  }, []);

  const landing = (
    <div onClickCapture={onLandingClickCapture}>
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
    </div>
  );

  if (mode === "landing") return landing;

  if (mode === "gate" || mode === "dimming") {
    return (
      // 바깥은 항상 불투명 검정(소등 중에도 암전 유지), 안쪽 내용만 페이드아웃
      <div className="fixed inset-0 z-50 bg-black text-white">
        <div className={`h-full flex flex-col items-center justify-center gap-10 px-6 text-center transition-opacity duration-[400ms] ${mode === "dimming" ? "opacity-0" : "opacity-100"}`}>
          <InpaMark size={72} live intense pColor="#FFFFFF" />
          <div>
            <p className="text-[15px] text-white/60">인파(Inpa)</p>
            <h1 className="mt-2 text-[24px] sm:text-[30px] font-extrabold tracking-tight">1분, 인파가 준비한 짧은 이야기</h1>
          </div>
          <div className="flex flex-col sm:flex-row gap-3">
            <button type="button" onClick={() => start(true)} disabled={mode === "dimming"}
              className="px-7 py-4 rounded-2xl bg-white text-black font-bold text-[16px] min-h-[52px] hover:bg-white/90 transition">
              소리와 함께 시작하기
            </button>
            <button type="button" onClick={() => start(false)} disabled={mode === "dimming"}
              className="px-7 py-4 rounded-2xl border border-white/30 text-white font-bold text-[16px] min-h-[52px] hover:bg-white/10 transition">
              조용히 보기
            </button>
          </div>
          <button type="button" onClick={() => skipToLanding(true)} className="text-[14px] text-white/45 underline underline-offset-4 hover:text-white/70 transition">
            건너뛰고 서비스 소개 보기
          </button>
        </div>
      </div>
    );
  }

  // mode === "film" | "closing"
  return (
    <>
      {/* 불 켜짐: 랜딩을 밑에 미리 깔아 두고 오버레이가 걷힌다 */}
      {mode === "closing" && landing}
      <div role="button" tabIndex={0} onClick={advance} onKeyDown={() => {}}
        aria-label="화면을 누르면 다음 장면으로 넘어갑니다"
        className={`fixed inset-0 z-50 bg-black text-white cursor-pointer select-none overflow-hidden ${mode === "closing" ? "pointer-events-none" : ""}`}>

        {/* 배경 레이어 스택 — 전부 상시 마운트, opacity 크로스 디졸브(배경 자체는 v1처럼 정지·원본 그대로) */}
        <div className={`absolute inset-0 transition-opacity duration-700 ${scene.bg === "scatter" && filmVisible ? "opacity-100" : "opacity-0"}`} aria-hidden>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/landing-new/scatter-bg.webp" alt="" className="w-full h-full object-cover" />
        </div>
        <div className={`absolute inset-0 transition-opacity duration-700 ${scene.bg === "crowd" && filmVisible ? "opacity-90" : "opacity-0"}`} aria-hidden>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/landing-new/crowd-dark.webp" alt="" className="w-full h-full object-cover" />
        </div>
        <div className={`absolute inset-0 bg-[var(--brand)] transition-opacity duration-700 ${scene.bg === "blue" ? "opacity-100" : "opacity-0"}`} aria-hidden>
          {scene.bg === "blue" && (
            <div className="absolute inset-0 flex items-center justify-center opacity-20 cine2-settle">
              <InpaMark size={560} live pColor="#FFFFFF" dotColor="#8D3B72" />
            </div>
          )}
        </div>

        {/* 상단 컨트롤 */}
        <div className={`absolute top-0 inset-x-0 flex items-center justify-end gap-2 p-4 sm:p-6 transition-opacity duration-300 ${mode === "closing" ? "opacity-0" : "opacity-100"}`}>
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

        {/* 자막(장면 텍스트) — 타이틀 크기, 전환 시 페이드아웃 */}
        <div className={`absolute inset-0 flex flex-col items-center justify-center px-6 transition-opacity ${textOut || mode === "closing" ? "opacity-0 duration-300" : "opacity-100 duration-200"}`}>
          <div className={scene.bg === "scatter" ? "text-[var(--ink)]" : "text-white"}>
            {scene.beats.slice(0, beatIdx + 1).map((b, i) => {
              const isLead = i === 0 && scene.beats.length > 1; // 도입(질문) 줄
              const sizeCls = scene.instant
                ? (isLead ? "text-[20px] sm:text-[33px] lg:text-[40px] text-[var(--ink-3)]" : "text-[26px] sm:text-[44px] lg:text-[54px]")
                : "text-[26px] sm:text-[44px] lg:text-[54px]";
              const faceCls = scene.mono ? "font-semibold" : "font-bold";
              return (
                <p key={`${scene.id}-${i}`}
                  className={`text-center leading-relaxed ${faceCls} ${sizeCls} ${i > 0 ? "mt-6 font-extrabold" : ""} ${i > 0 && i === beatIdx && scene.instant ? "line-rise" : ""}`}>
                  {i < beatIdx ? b.text : scene.instant ? (
                    i === 0 ? <span className="line-pop">{b.text}</span> : b.text
                  ) : beatDone && scene.emphasize ? (
                    <EmphasizedDefinition text={b.text} />
                  ) : (
                    <TypewriterV2
                      text={b.text}
                      active={mode === "film"}
                      revealAll={revealAll}
                      charMs={scene.charMs}
                      charClass={scene.mono ? monoCharClass : undefined}
                      onChar={(ch) => soundRef.current?.key(ch === " ")}
                      onDone={() => { setBeatDone(true); soundRef.current?.lineEnd(); }}
                    />
                  )}
                </p>
              );
            })}
          </div>
        </div>

        {/* 하단: 진행 도트 + 계속 힌트(1.2초 지연) */}
        <div className={`absolute bottom-0 inset-x-0 flex flex-col items-center gap-4 p-6 transition-opacity duration-300 ${mode === "closing" ? "opacity-0" : "opacity-100"}`}>
          <p className={`text-[13px] transition-opacity duration-500 ${hintVisible && !textOut ? "opacity-70" : "opacity-0"} ${scene.bg === "scatter" ? "text-[var(--ink-3)]" : "text-white/70"}`}>
            화면을 눌러 계속
          </p>
          <div className="flex gap-2" aria-hidden>
            {SCENES.map((s, i) => (
              <span key={s.id} className={`w-2 h-2 rounded-full transition ${i === sceneIdx ? "bg-[var(--danger)]" : scene.bg === "scatter" ? "bg-black/20" : "bg-white/25"}`} />
            ))}
          </div>
        </div>

        {/* 불 켜짐: 중앙에서 흰빛이 번져 화면을 밀어낸다 */}
        {mode === "closing" && (
          <div className="absolute inset-0 flex items-center justify-center" aria-hidden>
            <div className="cine2-iris w-[24vmax] h-[24vmax] rounded-full bg-white" />
          </div>
        )}
      </div>
    </>
  );
}
