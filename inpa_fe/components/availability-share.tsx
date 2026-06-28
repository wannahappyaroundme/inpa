"use client";

// 가용시간 공유 문구 — 자동(열린 슬롯 정리) + 수동(요일·시간 직접). 클립보드 복사까지만.
// ★ 정직성 레드라인: 자동발송 없음. 설계사가 복사해 카톡/문자로 직접 붙여넣기.

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/ui";
import { listMeetingSlots, type MeetingSlot } from "@/lib/api";

const WEEK = ["월", "화", "수", "목", "금", "토", "일"];

function fmtSlot(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ko-KR", {
      month: "numeric", day: "numeric", weekday: "short",
      hour: "numeric", minute: "2-digit", timeZone: "Asia/Seoul",
    }).format(new Date(iso));
  } catch { return iso; }
}

export function AvailabilityShare() {
  const [tab, setTab] = useState<"auto" | "manual">("auto");
  const [slots, setSlots] = useState<MeetingSlot[]>([]);
  const [copied, setCopied] = useState(false);

  // 수동 입력
  const [days, setDays] = useState<boolean[]>([true, false, true, false, true, false, false]);
  const [from, setFrom] = useState("10:00");
  const [to, setTo] = useState("12:00");

  useEffect(() => {
    listMeetingSlots(true).then((r) => setSlots(r.results)).catch(() => setSlots([]));
  }, []);

  const autoText = slots.length
    ? "예약 가능한 시간이에요 🗓️\n" + slots.map((s) => `· ${fmtSlot(s.start_at)}`).join("\n") +
      "\n\n편하신 시간을 알려주세요!"
    : "아직 등록한 가능 시간이 없어요. ‘예약(가용시간) 관리’에서 먼저 추가해주세요.";

  const manualText = (() => {
    const sel = WEEK.filter((_, i) => days[i]);
    if (!sel.length) return "요일을 하나 이상 골라주세요.";
    return `매주 ${sel.join("·")}요일 ${from}~${to} 상담 가능합니다 🙂\n편하신 날짜·시간 알려주시면 맞춰드릴게요!`;
  })();

  const text = tab === "auto" ? autoText : manualText;

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* 미지원 환경 무시 */ }
  }, [text]);

  return (
    <Card className="px-5 py-4">
      <div className="text-[15px] font-bold text-ink">가용시간 공유 문구</div>
      <p className="mt-1 text-[12px] text-ink3 leading-5">
        고객에게 보낼 가능 시간 문구를 만들어 복사하세요.
      </p>
      <div className="mt-3 flex gap-1.5">
        <button onClick={() => setTab("auto")}
          className={`flex-1 rounded-lg py-2 text-[13px] font-semibold ${tab === "auto" ? "bg-brand text-white" : "bg-surface2 text-ink2"}`}>등록한 시간 자동</button>
        <button onClick={() => setTab("manual")}
          className={`flex-1 rounded-lg py-2 text-[13px] font-semibold ${tab === "manual" ? "bg-brand text-white" : "bg-surface2 text-ink2"}`}>요일·시간 직접</button>
      </div>

      {tab === "manual" && (
        <div className="mt-3 space-y-2">
          <div className="flex gap-1">
            {WEEK.map((w, i) => (
              <button key={w} onClick={() => setDays((d) => d.map((v, j) => (j === i ? !v : v)))}
                className={`flex-1 rounded-lg py-2 text-[13px] font-semibold ${days[i] ? "bg-accent-tint text-brand" : "bg-surface2 text-ink2"}`}>{w}</button>
            ))}
          </div>
          <div className="flex gap-2 items-center">
            <input type="time" value={from} onChange={(e) => setFrom(e.target.value)}
              className="flex-1 rounded-xl border border-line px-3 py-2 text-[14px]" />
            <span className="text-ink3">~</span>
            <input type="time" value={to} onChange={(e) => setTo(e.target.value)}
              className="flex-1 rounded-xl border border-line px-3 py-2 text-[14px]" />
          </div>
        </div>
      )}

      <pre className="mt-3 whitespace-pre-wrap rounded-xl bg-surface2 px-3 py-2.5 text-[13px] text-ink leading-5 font-sans">{text}</pre>
      <button onClick={copy}
        className="mt-2 w-full rounded-xl bg-brand text-white text-[13px] font-bold py-2.5 transition">
        {copied ? "복사됐어요! 카톡·문자에 붙여넣기" : "문구 복사하기"}
      </button>
    </Card>
  );
}
