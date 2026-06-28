// 공지사항 상세 — AllowAny GET, 비로그인 접근 가능

"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { getNotice, type NoticeItem } from "@/lib/api";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default function NoticeDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();

  const noticeId = Number(params.id);

  const [notice, setNotice] = useState<NoticeItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!noticeId) return;
    getNotice(noticeId)
      .then(setNotice)
      .catch((e) => {
        if (e?.status === 404) setError("존재하지 않는 공지사항이에요.");
        else setError("공지사항을 불러오지 못했어요.");
      })
      .finally(() => setLoading(false));
  }, [noticeId]);

  if (loading) {
    return (
      <div className="min-h-dvh">
        <AppNav active="board" />
        <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
          <div className="py-12 text-center text-[14px] text-ink3">불러오는 중...</div>
        </main>
      </div>
    );
  }

  if (error || !notice) {
    return (
      <div className="min-h-dvh">
        <AppNav active="board" />
        <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
          <button onClick={() => router.back()} className="text-[13px] text-ink3 mb-4">‹ 뒤로</button>
          <div className="py-12 text-center">
            <p className="text-[15px] font-semibold text-ink3">{error ?? "공지사항을 찾을 수 없어요."}</p>
            <Link href="/boards/notice" className="mt-4 inline-block text-[13px] text-brand">공지사항 목록으로</Link>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-dvh">
      <AppNav active="board" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <button onClick={() => router.back()} className="text-[13px] text-ink3 flex items-center gap-1 hover:text-ink transition mb-5">
          ‹ 공지사항 목록
        </button>

        <Card className="p-5">
          {notice.is_pinned && (
            <span className="inline-block rounded-full bg-brand-soft text-brand text-[11px] font-bold px-2.5 py-0.5 mb-3">📌 공지</span>
          )}
          <h1 className="text-[20px] font-extrabold text-ink mb-3">{notice.title}</h1>
          <div className="flex items-center gap-2 text-[12px] text-ink3 pb-4 border-b border-line mb-5">
            <span>인파 운영팀</span>
            <span>·</span>
            <span className="tnum">{formatDate(notice.created_at)}</span>
            {notice.updated_at !== notice.created_at && (
              <span className="text-muted">(수정됨)</span>
            )}
          </div>

          {/* 본문 — XSS: 텍스트 전용, dangerouslySetInnerHTML 사용 안 함 */}
          <div className="text-[14px] text-ink leading-6 whitespace-pre-wrap break-words">
            {notice.body}
          </div>
        </Card>

        {/* 하단 내비게이션 */}
        <div className="mt-4 flex justify-between text-[13px]">
          <Link href="/boards/notice" className="text-brand hover:underline">
            ‹ 공지사항 목록
          </Link>
        </div>
      </main>
    </div>
  );
}
