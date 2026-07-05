"use client";

// 오늘 전화할 고객 — 전용 화면 (홈 대시보드 카드에서 이동, PM 지시 2026-07-05).
// 연락 우선순위 목록: 생일 임박 > 만기 임박 > 무접촉 순 점수(BE call-list 랭킹 그대로).
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { CallList } from "@/components/call-list";
import { useAuthGuard } from "@/lib/useAuthGuard";

export default function CallListPage() {
  const ready = useAuthGuard();
  if (!ready) return null;

  return (
    <div className="min-h-dvh">
      <AppNav active="call-list" />
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink">오늘 전화할 고객</h1>
        <p className="mt-1 text-[13px] text-ink3 leading-5">
          생일·만기·연락 공백 순서로 정리했어요.
        </p>

        <Card className="mt-4 p-4 sm:p-5">
          <CallList limit={50} />
        </Card>
      </main>
    </div>
  );
}
