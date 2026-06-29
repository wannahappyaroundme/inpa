"use client";

// 미팅 관리 — 다가오는 미팅(확정) 보기 + 영업 시간(예약 가능 시간) 설정 안내.
// ★ 예약 가능 시간은 '일정 탭'의 영업 시간(요일·시간)에서 자동 생성됨(WorkHour 엔진).
//   과거의 수동 슬롯(MeetingSlot) 입력은 영업 시간 방식으로 대체되어 제거됨.

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { CalendarClock, ArrowRight } from "lucide-react";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { listMeetings, type Meeting } from "@/lib/api";

function fmtKST(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ko-KR", {
      month: "long", day: "numeric", weekday: "short",
      hour: "numeric", minute: "2-digit", timeZone: "Asia/Seoul",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export default function MeetingsSettingsPage() {
  const ready = useAuthGuard();
  const router = useRouter();
  const [meetings, setMeetings] = useState<Meeting[]>([]);

  const load = useCallback(() => {
    listMeetings(true)
      .then((m) => setMeetings(m.results))
      .catch(() => { /* useAuthGuard 처리 */ });
  }, []);

  useEffect(() => { if (ready) load(); }, [ready, load]);

  if (!ready) return null;

  return (
    <div className="min-h-dvh">
      <AppNav active="settings" />
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink">미팅 관리</h1>
        <p className="mt-1 text-[13px] text-ink3 leading-5">
          확정된 미팅을 한눈에 보고, 고객에게 열어 줄 예약 가능 시간(영업 시간)은 일정 탭에서 설정하세요.
        </p>

        <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
          {/* 다가오는 미팅 */}
          <Card className="px-5 py-4">
            <div className="text-[15px] font-bold text-ink">다가오는 미팅</div>
            {meetings.length === 0 ? (
              <p className="mt-2 text-[13px] text-ink3">아직 확정된 미팅이 없어요.</p>
            ) : (
              <div className="mt-3 divide-y divide-line">
                {meetings.map((m) => (
                  <div key={m.id} className="py-2.5">
                    <div className="text-[14px] font-semibold text-ink">{fmtKST(m.start_at)}</div>
                    <div className="text-[12px] text-ink3 mt-0.5">
                      {m.customer_name} · {m.method_display}
                      {m.location_detail ? ` · ${m.location_detail}` : ""}
                      {m.customer_note ? ` · “${m.customer_note}”` : ""}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* 예약 가능 시간(영업 시간) — 일정 탭으로 안내 */}
          <Card className="px-5 py-4">
            <div className="flex items-start gap-3">
              <span className="shrink-0 w-10 h-10 rounded-xl grid place-items-center bg-brand-soft text-brand" aria-hidden>
                <CalendarClock className="w-5 h-5" strokeWidth={2} />
              </span>
              <div className="min-w-0">
                <div className="text-[15px] font-bold text-ink">예약 가능 시간(영업 시간)</div>
                <p className="mt-1 text-[12px] text-ink3 leading-5">
                  고객 예약 링크에 열어 줄 시간은 일정 탭의 <b>영업 시간(요일·시간)</b>으로 정해요.
                  설정한 영업 시간에서 이미 잡힌 미팅·일정을 뺀 빈 시간이 자동으로 고객에게 열립니다.
                  (예약 안내 문구·장소도 일정 탭에서 함께 설정해요)
                </p>
              </div>
            </div>
            <button
              onClick={() => router.push("/schedule")}
              className="mt-3 w-full rounded-xl bg-brand text-white text-[13px] font-bold py-2.5 hover:opacity-90 transition inline-flex items-center justify-center gap-1"
            >
              일정 탭에서 영업 시간 설정 <ArrowRight className="w-4 h-4" />
            </button>
          </Card>
        </div>
      </main>
    </div>
  );
}
