"use client";

import { useState } from "react";
import { Card } from "@/components/ui";
import { kpis, calendar, calendarEvents, eventMeta, todayTasks, planner, type EventType } from "@/lib/mock";

const WEEK = ["일", "월", "화", "수", "목", "금", "토"];

export default function DemoDashboard() {
  const [sel, setSel] = useState(calendar.today);
  const first = new Date(calendar.year, calendar.month - 1, 1).getDay();
  const days = new Date(calendar.year, calendar.month, 0).getDate();
  const cells: (number | null)[] = [
    ...Array(first).fill(null),
    ...Array.from({ length: days }, (_, i) => i + 1),
  ];

  return (
    <div>
      <div className="flex items-end justify-between">
        <h1 className="text-[22px] font-extrabold text-ink">
          안녕하세요, {planner.name} 설계사님 <span className="font-normal">👋</span>
        </h1>
        <span className="hidden sm:block text-[13px] text-ink3 tnum">
          {calendar.year}.{String(calendar.month).padStart(2, "0")}.{String(calendar.today).padStart(2, "0")}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {kpis.map((k) => (
          <Card key={k.label} className="px-4 py-3.5">
            <div className="text-[12px] text-ink3">{k.label}</div>
            <div className="mt-1 flex items-baseline gap-1">
              <span className={`text-[24px] font-extrabold tnum ${k.accent ? "text-accent" : "text-ink"}`}>{k.value}</span>
              <span className="text-[13px] text-ink3">{k.unit}</span>
            </div>
          </Card>
        ))}
      </div>

      <div className="mt-5 lg:grid lg:grid-cols-3 lg:gap-5">
        <Card className="lg:col-span-2 p-4 sm:p-5">
          <div className="flex items-center justify-between mb-3">
            <button className="w-8 h-8 rounded-lg hover:bg-surface2 text-ink2 text-[18px]">‹</button>
            <div className="text-[16px] font-bold text-ink">{calendar.year}년 {calendar.month}월</div>
            <button className="w-8 h-8 rounded-lg hover:bg-surface2 text-ink2 text-[18px]">›</button>
          </div>
          <div className="grid grid-cols-7 text-center text-[12px] mb-1">
            {WEEK.map((w, i) => (
              <div key={w} className={i === 0 ? "text-danger" : "text-ink3"}>{w}</div>
            ))}
          </div>
          <div className="grid grid-cols-7">
            {cells.map((d, i) => {
              if (!d) return <div key={i} />;
              const isSun = i % 7 === 0;
              const isToday = d === calendar.today;
              const isSel = d === sel;
              let cls = isSun ? "text-danger" : "text-ink2";
              if (isToday && !isSel) cls = "text-brand font-bold";
              if (isSel) cls = "bg-brand text-white font-bold";
              const evs = calendarEvents[d];
              return (
                <div key={i} className="flex flex-col items-center pt-1.5 pb-1 min-h-[52px]">
                  <button onClick={() => setSel(d)} className={`w-9 h-9 rounded-full flex items-center justify-center text-[14px] font-medium ${cls}`}>{d}</button>
                  {evs && (
                    <div className="flex gap-0.5 mt-1">
                      {evs.slice(0, 3).map((e, j) => (
                        <span key={j} className={`w-1.5 h-1.5 rounded-full ${eventMeta[e].dot}`} />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div className="mt-3 flex flex-wrap gap-3 text-[12px] text-ink3">
            {(Object.keys(eventMeta) as EventType[]).map((e) => (
              <span key={e} className="inline-flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${eventMeta[e].dot}`} />
                {eventMeta[e].label}
              </span>
            ))}
          </div>
        </Card>

        <Card className="mt-4 lg:mt-0 p-4 sm:p-5">
          <div className="text-[15px] font-bold text-ink mb-3">오늘의 일정 · 할 일</div>
          <div className="space-y-3.5">
            {todayTasks.map((t, i) => (
              <div key={i} className="flex gap-3">
                <div className="text-[12px] font-semibold text-ink3 w-11 shrink-0 tnum pt-0.5">{t.time}</div>
                <div className="flex-1 flex items-start gap-2">
                  <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${eventMeta[t.type].dot}`} />
                  <span className="text-[14px] text-ink leading-5">{t.title}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
