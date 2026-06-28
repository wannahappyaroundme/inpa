"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  listNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  deleteNotification,
  acceptMeeting,
  declineMeeting,
  type NotificationItem,
  type NotifType,
} from "@/lib/api";

// ─── 타입별 아이콘·색 매핑 (dev/22 §4.2) ─────────────────────────────────────
// expiry_soon: 보라 (cal-expiry). 빨강 금지(§97 비교안내 전용).
const NOTIF_META: Record<
  NotifType,
  { icon: string; colorClass: string; label: string }
> = {
  expiry_soon:       { icon: "🟣", colorClass: "text-purple-600",   label: "만기 임박" },
  birthday_soon:     { icon: "🎂", colorClass: "text-pink-500",        label: "고객 생일" },
  consult_reminder:  { icon: "💬", colorClass: "text-brand",                              label: "상담 약속" },
  task_due:          { icon: "✅", colorClass: "text-success",                            label: "할 일 마감" },
  share_unread:      { icon: "📨", colorClass: "text-ink3",                               label: "미열람 공유" },
  unpaid_d_alert:    { icon: "⚠️",  colorClass: "text-rose-600",        label: "환수 위험" },
  self_diagnosis_lead: { icon: "🎯", colorClass: "text-brand",                            label: "셀프진단 리드" },
  board_comment:     { icon: "💬", colorClass: "text-brand",                              label: "댓글" },
  board_like:        { icon: "❤️",  colorClass: "text-danger",                            label: "좋아요" },
  meeting_booked:    { icon: "📅", colorClass: "text-brand",                              label: "예약 요청" },
};

// ─── 날짜 그룹 분류 ────────────────────────────────────────────────────────────
function getDateGroup(createdAt: string): string {
  const now = new Date();
  const d = new Date(createdAt);
  const todayStr = now.toDateString();
  const dStr = d.toDateString();

  if (todayStr === dStr) return "오늘";

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (yesterday.toDateString() === dStr) return "어제";

  const weekAgo = new Date(now);
  weekAgo.setDate(now.getDate() - 7);
  if (d >= weekAgo) return "이번 주";

  return "이전";
}

function formatTime(createdAt: string): string {
  const d = new Date(createdAt);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mn = String(d.getMinutes()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mn}`;
}

// ─── 스켈레톤 ────────────────────────────────────────────────────────────────
function SkeletonRow() {
  return (
    <div className="p-4 animate-pulse flex gap-3">
      <div className="w-8 h-8 rounded-full bg-line shrink-0" />
      <div className="flex-1 space-y-2">
        <div className="h-3.5 bg-line rounded w-2/3" />
        <div className="h-3 bg-line rounded w-1/2" />
      </div>
    </div>
  );
}

// ─── 단일 알림 카드 ───────────────────────────────────────────────────────────
function NotifCard({
  item,
  onRead,
  onDelete,
  onAccept,
  onDecline,
}: {
  item: NotificationItem;
  onRead: (id: number) => void;
  onDelete: (id: number) => void;
  onAccept: (item: NotificationItem) => void;
  onDecline: (item: NotificationItem) => void;
}) {
  const meta = NOTIF_META[item.notif_type] ?? NOTIF_META["consult_reminder"];

  // 클릭 시 읽음 처리 + 이동
  const handleClick = () => {
    if (!item.is_read) onRead(item.id);
  };

  // 고객 링크 결정
  const customerHref = item.customer ? `/customers/${item.customer}` : null;
  // share_unread는 고객 공유탭으로
  const actionHref =
    item.notif_type === "share_unread" && item.customer
      ? `/customers/${item.customer}?tab=share`
      : customerHref;

  const actionLabel =
    item.notif_type === "share_unread" ? "재발송 준비 →" : "고객 보기 →";

  return (
    <Card
      className={`relative overflow-hidden transition ${
        !item.is_read ? "bg-accent-tint border-brand/20" : ""
      }`}
    >
      {/* 미읽음 도트 */}
      {!item.is_read && (
        <span
          className="absolute left-3 top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-brand"
          aria-label="미읽음"
        />
      )}
      <div
        className={`p-4 ${!item.is_read ? "pl-6" : ""}`}
        onClick={handleClick}
        role="button"
        tabIndex={0}
        aria-label={item.title}
        onKeyDown={(e) => e.key === "Enter" && handleClick()}
      >
        <div className="flex items-start gap-3">
          {/* 아이콘 */}
          <span className="text-[20px] shrink-0 leading-none mt-0.5" aria-hidden>
            {meta.icon}
          </span>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              {/* 타입 배지 */}
              <span
                className={`text-[11px] font-bold rounded-full px-2 py-0.5 bg-surface2 ${meta.colorClass}`}
              >
                {meta.label}
              </span>
              {!item.is_read && (
                <span className="text-[11px] text-brand font-semibold">● 미읽음</span>
              )}
              <span className="ml-auto text-[12px] text-ink3 tnum shrink-0">
                {formatTime(item.created_at)}
              </span>
            </div>

            {/* 제목 */}
            <p
              className={`mt-1 text-[14px] leading-5 ${
                !item.is_read ? "font-bold text-ink" : "font-semibold text-ink"
              }`}
            >
              {item.title}
            </p>

            {/* 본문 */}
            <p className="mt-0.5 text-[13px] text-ink3 leading-5">{item.body}</p>

            {/* 액션 */}
            <div className="mt-2 flex items-center gap-3">
              {actionHref && (
                <Link
                  href={actionHref}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (!item.is_read) onRead(item.id);
                  }}
                  className="text-[13px] font-semibold text-brand hover:underline"
                >
                  {actionLabel}
                </Link>
              )}
              {/* 캘린더 이동 */}
              {item.calendar_event_id && (
                <Link
                  href={`/home?cal_date=${item.target_date ?? ""}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (!item.is_read) onRead(item.id);
                  }}
                  className="text-[13px] font-semibold text-ink3 hover:underline"
                >
                  캘린더에서 보기 →
                </Link>
              )}
              {/* 예약 요청 — 대기면 수락/거절, 처리됐으면 상태 표시 */}
              {item.notif_type === "meeting_booked" && item.meeting && item.meeting_status === "pending" && (
                <>
                  <button
                    onClick={(e) => { e.stopPropagation(); onAccept(item); }}
                    className="rounded-lg bg-brand text-white text-[12px] font-bold px-3 py-1.5"
                  >
                    수락
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); onDecline(item); }}
                    className="rounded-lg border border-line text-ink2 text-[12px] font-semibold px-3 py-1.5 hover:bg-surface2"
                  >
                    거절
                  </button>
                </>
              )}
              {item.notif_type === "meeting_booked" && item.meeting_status && item.meeting_status !== "pending" && (
                <span className="text-[12px] font-semibold text-ink3">
                  {item.meeting_status === "confirmed" ? "수락함 ✓"
                    : item.meeting_status === "declined" ? "거절함"
                    : "취소됨"}
                </span>
              )}
            </div>
          </div>

          {/* 삭제 버튼 */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(item.id);
            }}
            aria-label="알림 삭제"
            className="shrink-0 w-7 h-7 flex items-center justify-center text-ink3 hover:text-danger rounded-lg hover:bg-surface2 transition ml-1"
          >
            ×
          </button>
        </div>
      </div>
    </Card>
  );
}

// ─── 알림 센터 본체 ───────────────────────────────────────────────────────────
function NotificationsContent() {
  const ready = useAuthGuard();

  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  const [readAllLoading, setReadAllLoading] = useState(false);

  const fetchPage = useCallback(async (p: number, reset: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const res = await listNotifications({ page: p });
      setItems((prev) => (reset ? res.results : [...prev, ...res.results]));
      setHasMore(res.next !== null);
      setPage(p);
    } catch {
      setError("알림을 불러오지 못했어요. 잠시 후 다시 시도하세요.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!ready) return;
    fetchPage(1, true);
  }, [ready, fetchPage]);

  const handleRead = useCallback(async (id: number) => {
    try {
      await markNotificationRead(id);
      setItems((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      );
    } catch {
      // 읽음 실패는 UX 차단 없이 조용히 처리
    }
  }, []);

  const handleDelete = useCallback(async (id: number) => {
    try {
      await deleteNotification(id);
      setItems((prev) => prev.filter((n) => n.id !== id));
    } catch {
      // 삭제 실패 — 조용히 처리
    }
  }, []);

  const handleAccept = useCallback(async (item: NotificationItem) => {
    if (!item.meeting) return;
    try {
      await acceptMeeting(item.meeting);
      setItems((prev) => prev.map((n) =>
        n.id === item.id ? { ...n, meeting_status: "confirmed", is_read: true } : n));
    } catch {
      // 실패 — 조용히 처리(다시 시도 가능)
    }
  }, []);

  const handleDecline = useCallback(async (item: NotificationItem) => {
    if (!item.meeting) return;
    try {
      await declineMeeting(item.meeting);
      setItems((prev) => prev.map((n) =>
        n.id === item.id ? { ...n, meeting_status: "declined", is_read: true } : n));
    } catch {
      // 실패 — 조용히 처리
    }
  }, []);

  const handleReadAll = async () => {
    setReadAllLoading(true);
    try {
      await markAllNotificationsRead();
      setItems((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } catch {
      // 조용히 처리
    } finally {
      setReadAllLoading(false);
    }
  };

  if (!ready) return null;

  // 날짜 그룹 순서
  const GROUP_ORDER = ["오늘", "어제", "이번 주", "이전"];
  const grouped: Record<string, NotificationItem[]> = {};
  for (const item of items) {
    const g = getDateGroup(item.created_at);
    if (!grouped[g]) grouped[g] = [];
    grouped[g].push(item);
  }

  const unreadCount = items.filter((n) => !n.is_read).length;

  return (
    <div className="min-h-dvh">
      <AppNav active="notifications" />
      <main className="mx-auto max-w-2xl px-4 sm:px-6 py-6">
        {/* 헤더 */}
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-[22px] font-extrabold text-ink">
            알림
            {unreadCount > 0 && (
              <span className="ml-2 text-[14px] font-bold text-brand tnum">
                {unreadCount}
              </span>
            )}
          </h1>
          <div className="flex items-center gap-2">
            {unreadCount > 0 && (
              <button
                onClick={handleReadAll}
                disabled={readAllLoading}
                className="text-[13px] font-semibold text-brand disabled:opacity-50 hover:underline"
              >
                {readAllLoading ? "처리 중..." : "전체 읽음 처리"}
              </button>
            )}
            <Link
              href="/settings/reminders"
              className="text-[13px] font-semibold text-ink3 hover:text-ink"
            >
              알림 설정 →
            </Link>
          </div>
        </div>

        {/* 에러 */}
        {error && (
          <div
            role="alert"
            aria-live="assertive"
            className="mb-4 p-3 rounded-xl bg-danger-tint border border-danger/20 text-[13px] text-danger flex items-center justify-between"
          >
            <span>{error}</span>
            <button
              onClick={() => fetchPage(1, true)}
              aria-label="알림 다시 불러오기"
              className="ml-3 font-semibold underline"
            >
              재시도
            </button>
          </div>
        )}

        {/* 로딩 스켈레톤 */}
        {loading && items.length === 0 && (
          <Card className="divide-y divide-line">
            <SkeletonRow />
            <SkeletonRow />
            <SkeletonRow />
          </Card>
        )}

        {/* 빈 상태 */}
        {!loading && !error && items.length === 0 && (
          <Card className="p-8 text-center">
            <p className="text-[32px] mb-3">🔔</p>
            <p className="text-[15px] font-semibold text-ink mb-1">
              아직 알림이 없어요
            </p>
            <p className="text-[13px] text-ink3 mb-5">
              고객을 등록하면 만기·생일 알림이 시작됩니다.
            </p>
            <Link
              href="/customers"
              className="inline-block rounded-xl bg-brand text-white text-[13px] font-bold px-5 py-2.5"
            >
              첫 고객 등록
            </Link>
          </Card>
        )}

        {/* 알림 목록 — 날짜 그룹 */}
        {GROUP_ORDER.map((group) => {
          const groupItems = grouped[group];
          if (!groupItems?.length) return null;
          return (
            <div key={group} className="mb-5">
              <h2 className="text-[12px] font-bold text-ink3 uppercase tracking-wider mb-2">
                {group}
              </h2>
              <div className="space-y-2">
                {groupItems.map((item) => (
                  <NotifCard
                    key={item.id}
                    item={item}
                    onRead={handleRead}
                    onDelete={handleDelete}
                    onAccept={handleAccept}
                    onDecline={handleDecline}
                  />
                ))}
              </div>
            </div>
          );
        })}

        {/* 더 보기 */}
        {hasMore && !loading && (
          <div className="text-center mt-2">
            <button
              onClick={() => fetchPage(page + 1, false)}
              className="text-[13px] font-semibold text-brand hover:underline"
            >
              더 보기
            </button>
          </div>
        )}
        {loading && items.length > 0 && (
          <div className="text-center mt-4 text-[13px] text-ink3">불러오는 중...</div>
        )}

        {/* 고객 자동발송 아님 안내 (정직성 레드라인) */}
        <p className="mt-8 text-[11px] text-muted text-center leading-5">
          인파 알림은 설계사 본인에게만 전송됩니다.
        </p>
      </main>
    </div>
  );
}

// useSearchParams 없음 → Suspense 불필요하지만, 향후 확장 대비 + 페이지 규칙상 래핑
export default function NotificationsPage() {
  return (
    <Suspense>
      <NotificationsContent />
    </Suspense>
  );
}
