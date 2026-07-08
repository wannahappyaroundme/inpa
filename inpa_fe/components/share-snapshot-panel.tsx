"use client";

// 공유 기록 — 공유(/s) 링크를 만든 순간 고객에게 보여준 화면을 그대로 남긴 기록.
// 설계사 내부 전용 화면(light 고정, §6). 고객 대면 화면(app/s 등)과는 무관 — 별도 조회 API.

import { useCallback, useEffect, useState } from "react";
import {
  listShareSnapshots,
  getShareSnapshot,
  ApiError,
  type ShareSnapshotListItem,
  type ShareSnapshotDetail,
} from "@/lib/api";
import { fmtWon } from "@/components/heatmap";

function fmtDateTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ko-KR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function fmtDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ko-KR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function ShareSnapshotButton({ customerId }: { customerId: number }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition"
      >
        공유 기록
      </button>
      {open && <ShareSnapshotModal customerId={customerId} onClose={() => setOpen(false)} />}
    </>
  );
}

function ShareSnapshotModal({
  customerId,
  onClose,
}: {
  customerId: number;
  onClose: () => void;
}) {
  const [items, setItems] = useState<ShareSnapshotListItem[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ShareSnapshotDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    listShareSnapshots(customerId)
      .then(setItems)
      .catch((e: unknown) => {
        setListError(e instanceof ApiError ? e.message : "공유 기록을 불러오지 못했어요.");
      });
  }, [customerId]);

  const openDetail = useCallback(
    (id: number) => {
      setDetailLoading(true);
      setDetailError(null);
      getShareSnapshot(customerId, id)
        .then(setSelected)
        .catch((e: unknown) => {
          setDetailError(e instanceof ApiError ? e.message : "그때 화면을 불러오지 못했어요.");
        })
        .finally(() => setDetailLoading(false));
    },
    [customerId]
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 sm:p-4"
      onClick={onClose}
    >
      <div
        className="w-full sm:max-w-md max-h-[85vh] overflow-y-auto bg-surface rounded-t-2xl sm:rounded-2xl p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {selected ? (
          <>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="text-[13px] font-semibold text-ink3"
              >
                ← 목록으로
              </button>
              <button
                onClick={onClose}
                aria-label="닫기"
                className="ml-auto text-ink3 text-[20px] leading-none px-1"
              >
                ✕
              </button>
            </div>
            <h2 className="mt-2 text-[15px] font-bold text-ink">
              {fmtDateTime(selected.captured_at)}에 보여드린 화면
            </h2>
            <SnapshotDetailView detail={selected} />
          </>
        ) : (
          <>
            <div className="flex items-center justify-between">
              <h2 className="text-[16px] font-extrabold text-ink">공유 기록</h2>
              <button
                onClick={onClose}
                aria-label="닫기"
                className="text-ink3 text-[20px] leading-none px-1"
              >
                ✕
              </button>
            </div>
            <p className="mt-1 text-[12px] text-ink3 leading-5">
              고객에게 공유한 시점의 화면을 기록으로 남깁니다. 6개월 후 자동 삭제됩니다.
            </p>

            <div className="mt-3">
              {listError ? (
                <div className="rounded-xl border border-line bg-surface2 px-4 py-6 text-center text-[13px] text-ink3">
                  {listError}
                </div>
              ) : items === null ? (
                <div className="space-y-2">
                  {[1, 2].map((i) => (
                    <div key={i} className="h-14 rounded-xl bg-line animate-pulse" />
                  ))}
                </div>
              ) : items.length === 0 ? (
                <div className="rounded-xl border border-dashed border-line px-4 py-8 text-center">
                  <p className="text-[14px] font-semibold text-ink2">공유 기록이 없어요</p>
                  <p className="mt-1 text-[12px] text-ink3 leading-5">
                    공유 링크를 만들어 보내면 그 순간의 화면이 여기 기록으로 남아요.
                  </p>
                </div>
              ) : (
                <ul className="space-y-2">
                  {items.map((it) => (
                    <li key={it.id}>
                      <button
                        type="button"
                        onClick={() => openDetail(it.id)}
                        className="w-full text-left rounded-xl border border-line bg-surface2 px-3 py-3 hover:bg-line/40 transition"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[13px] font-semibold text-ink">
                            {fmtDateTime(it.captured_at)}
                          </span>
                          <span className="text-[12px] text-ink3 shrink-0 tnum">
                            보험 {it.insurance_count}건
                          </span>
                        </div>
                        <div className="mt-1 text-[11px] text-ink3">
                          {it.consent_overseas && <span>국외이전 동의 완료 · </span>}
                          {fmtDate(it.retention_expires_at)} 자동 삭제 예정
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {detailLoading && (
                <p className="mt-2 text-[12px] text-ink3">불러오는 중...</p>
              )}
              {detailError && (
                <p className="mt-2 text-[12px] text-cnone">{detailError}</p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** 그 시점 /s 화면 재구성 — 읽기전용(설계사 내부), payload.tree 값 그대로 표시. */
function SnapshotDetailView({ detail }: { detail: ShareSnapshotDetail }) {
  const payload = detail.payload;
  const held = payload.tree
    .flatMap((cat) => cat.sub_categories)
    .flatMap((sub) => sub.details)
    .filter((d) => (d.held_amount ?? 0) > 0);

  return (
    <div className="mt-3">
      <div className="rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[12px] text-ink3">
        <span className="font-semibold text-ink2">{payload.customer?.name_masked}</span>
        님에게 보여드린 보장 현황이에요.
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-xl border border-line bg-surface px-3 py-2.5 text-center">
          <div className="text-[11px] text-ink3">월 보험료</div>
          <div className="mt-0.5 text-[14px] font-extrabold text-ink tnum">
            {fmtWon(payload.summary?.monthly_premiums ?? null)}
          </div>
        </div>
        <div className="rounded-xl border border-line bg-surface px-3 py-2.5 text-center">
          <div className="text-[11px] text-ink3">총 납입 보험료</div>
          <div className="mt-0.5 text-[14px] font-extrabold text-ink tnum">
            {fmtWon(payload.summary?.total_premiums ?? null)}
          </div>
        </div>
      </div>

      <div className="mt-3">
        <div className="text-[12px] font-semibold text-ink3 mb-1.5">그때 보여드린 담보</div>
        {held.length > 0 ? (
          <div className="rounded-xl border border-line divide-y divide-line">
            {held.map((c) => (
              <div key={c.detail_id} className="flex items-center gap-3 px-3 py-2.5">
                <div className="flex-1 min-w-0 text-[13px] font-medium text-ink">{c.name}</div>
                <div className="text-[13px] font-bold text-ink tnum shrink-0">
                  {fmtWon(c.held_amount)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-line px-3 py-6 text-center text-[12px] text-ink3">
            그 시점에는 등록된 보유 담보가 없었어요.
          </div>
        )}
      </div>

      {payload.disclaimer && (
        <div className="mt-3 rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[11px] text-ink3 leading-5">
          {payload.disclaimer}
        </div>
      )}
    </div>
  );
}
