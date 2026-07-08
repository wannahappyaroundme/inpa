"use client";

import { useEffect, useRef, useState } from "react";

// 글자 단위 타이핑. revealAll → 즉시 전체 표시. 문장부호 뒤에는 잠깐 쉼(타자 리듬).
type Props = {
  text: string;
  active: boolean;
  revealAll: boolean;
  charMs?: number;
  onChar?: (ch: string) => void;
  onDone?: () => void;
  className?: string;
  showCursor?: boolean;
};

const PAUSE_AFTER = new Set([".", ",", "?", "!", ":", "…"]);

export function Typewriter({
  text, active, revealAll, charMs = 70, onChar, onDone, className = "", showCursor = true,
}: Props) {
  const [count, setCount] = useState(0);
  const doneRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cbRef = useRef({ onChar, onDone });
  cbRef.current = { onChar, onDone };

  useEffect(() => {
    doneRef.current = false;
    setCount(0);
  }, [text]);

  useEffect(() => {
    if (!active) return;
    const reduced = typeof window !== "undefined"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (revealAll || reduced) {
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
      cbRef.current.onChar?.(ch); // 공백도 전달해 스페이스바 타건음이 나게 한다

      const pause = PAUSE_AFTER.has(ch) ? 340 : 0;
      const jitter = Math.random() * 40 - 20;
      timerRef.current = setTimeout(tick, charMs + pause + jitter);
    };
    timerRef.current = setTimeout(tick, 160);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [active, revealAll, text, charMs]);

  return (
    <span className={className} aria-label={text}>
      <span aria-hidden>{text.slice(0, count)}</span>
      {showCursor && count < text.length && active && !revealAll ? <span className="tw-cursor" aria-hidden /> : null}
      {showCursor && (count >= text.length || revealAll) ? <span className="tw-cursor" aria-hidden /> : null}
    </span>
  );
}
