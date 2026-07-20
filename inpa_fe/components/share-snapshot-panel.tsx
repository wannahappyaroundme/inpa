"use client";

// 공유 기록. 저장된 v2 본문과 서버 수명 상태만 표시하며 현재 고객 데이터를 재조회하지 않는다.

import { useCallback, useEffect, useRef, useState } from "react";
import { ShareSnapshotContent } from "@/components/share-snapshot-content";
import {
  ApiError,
  getShareSnapshot,
  isShareSnapshotPayload,
  listShareSnapshots,
  revokeShareSnapshot,
  type ShareSnapshotDetail,
  type ShareSnapshotLifecycle,
  type ShareSnapshotListItem,
} from "@/lib/api";

function fmtDateTime(iso: string | null): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function lifecycleLabel(lifecycle: ShareSnapshotLifecycle): string {
  if (lifecycle === "active") return "사용 중";
  if (lifecycle === "revoked") return "회수됨";
  if (lifecycle === "expired") return "기간 종료";
  return "이전 공유 기록";
}

function revokedLabel(reason: string): string {
  if (reason === "manual") return "직접 회수됨";
  if (reason === "reissued") return "새 링크로 교체됨";
  if (reason === "legacy_revoke") return "이전 링크 정리됨";
  if (reason === "consent_withdrawn") return "고객 동의 변경으로 종료됨";
  return "회수됨";
}

function historyError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return "공유 기록을 찾을 수 없어요.";
    if (error.status === 409) return "기록 상태가 바뀌었어요. 목록을 다시 불러와 주세요.";
    if (error.status === 429) return "요청이 잠시 몰렸어요. 잠시 뒤 다시 불러와 주세요.";
    if (error.status >= 500) return error.message || fallback;
    return error.message || fallback;
  }
  return fallback;
}

export function ShareSnapshotButton({ customerId }: { customerId: number }) {
  const [open, setOpen] = useState(false);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const close = useCallback(() => {
    setOpen(false);
    window.setTimeout(() => openerRef.current?.focus(), 0);
  }, []);

  return (
    <>
      <button
        ref={openerRef}
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 transition hover:bg-surface2"
      >
        공유 기록
      </button>
      {open && <ShareSnapshotModal customerId={customerId} onClose={close} />}
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
  const [selectedItem, setSelectedItem] = useState<ShareSnapshotListItem | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<ShareSnapshotDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [revokeConfirm, setRevokeConfirm] = useState(false);
  const [revokeLoadingActions, setRevokeLoadingActions] = useState<Record<number, number>>({});
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const mountedRef = useRef(false);
  const customerRef = useRef(customerId);
  const listRequestRef = useRef(0);
  const detailRequestRef = useRef(0);
  const revokeRequestRef = useRef(0);
  const operationGenerationRef = useRef(0);
  const selectedSnapshotRef = useRef<number | null>(selectedItem?.id ?? null);
  const revokeActionsRef = useRef(new Map<number, number>());
  const latestRevokeActionsRef = useRef(new Map<number, number>());
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const initialCloseRef = useRef<HTMLButtonElement | null>(null);
  const backButtonRef = useRef<HTMLButtonElement | null>(null);
  const returnFocusSnapshotRef = useRef<number | null>(null);
  const revokeConfirmButtonRef = useRef<HTMLButtonElement | null>(null);
  const revokeButtonRef = useRef<HTMLButtonElement | null>(null);
  customerRef.current = customerId;
  selectedSnapshotRef.current = selectedItem?.id ?? null;

  const closeModal = useCallback(() => {
    operationGenerationRef.current += 1;
    selectedSnapshotRef.current = null;
    onClose();
  }, [onClose]);

  useEffect(() => {
    mountedRef.current = true;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    initialCloseRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeModal();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("*")).filter(
        (element) => element.matches(
          "button:not(:disabled), input:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])"
        )
      );
      if (focusable.length === 0) return;
      const currentIndex = focusable.indexOf(document.activeElement as HTMLElement);
      const nextIndex = event.shiftKey
        ? (currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1)
        : (currentIndex < 0 || currentIndex === focusable.length - 1 ? 0 : currentIndex + 1);
      event.preventDefault();
      focusable[nextIndex].focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      mountedRef.current = false;
      operationGenerationRef.current += 1;
      listRequestRef.current += 1;
      detailRequestRef.current += 1;
      revokeRequestRef.current += 1;
      revokeActionsRef.current.clear();
      latestRevokeActionsRef.current.clear();
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [closeModal]);

  useEffect(() => {
    if (selectedItem) {
      backButtonRef.current?.focus();
      return;
    }
    const snapshotId = returnFocusSnapshotRef.current;
    if (snapshotId === null) return;
    returnFocusSnapshotRef.current = null;
    dialogRef.current
      ?.querySelector<HTMLButtonElement>(`[data-share-snapshot-id="${snapshotId}"]`)
      ?.focus();
  }, [selectedItem?.id]);

  useEffect(() => {
    if (revokeConfirm) revokeConfirmButtonRef.current?.focus();
  }, [revokeConfirm]);

  const loadList = useCallback(async (preserveCurrent = false) => {
    const requestId = ++listRequestRef.current;
    if (!preserveCurrent) {
      setItems(null);
      setListError(null);
    }
    try {
      const response = await listShareSnapshots(customerId);
      if (
        mountedRef.current &&
        customerRef.current === customerId &&
        listRequestRef.current === requestId
      ) {
        setItems(response);
      }
    } catch (error) {
      if (
        mountedRef.current &&
        customerRef.current === customerId &&
        listRequestRef.current === requestId
      ) {
        if (preserveCurrent) return;
        setListError(historyError(error, "공유 기록을 불러오지 못했어요."));
        setItems([]);
      }
    }
  }, [customerId]);

  useEffect(() => {
    operationGenerationRef.current += 1;
    detailRequestRef.current += 1;
    revokeRequestRef.current += 1;
    revokeActionsRef.current.clear();
    latestRevokeActionsRef.current.clear();
    selectedSnapshotRef.current = null;
    returnFocusSnapshotRef.current = null;
    setSelectedItem(null);
    setSelectedDetail(null);
    setDetailLoading(false);
    setDetailError(null);
    setRevokeConfirm(false);
    setRevokeLoadingActions({});
    setRevokeError(null);
    void loadList();
  }, [customerId, loadList]);

  const loadDetail = useCallback((item: ShareSnapshotListItem) => {
    const operationGeneration = ++operationGenerationRef.current;
    selectedSnapshotRef.current = item.id;
    setSelectedItem(item);
    setSelectedDetail(null);
    setDetailError(null);
    setRevokeConfirm(false);
    setRevokeError(null);
    const requestId = ++detailRequestRef.current;

    if (item.link_status === "history_only" || item.payload_version !== "v2-immutable-analysis") {
      setDetailLoading(false);
      return;
    }

    setDetailLoading(true);
    void (async () => {
      const selectionIsCurrent = () => (
        mountedRef.current &&
        customerRef.current === customerId &&
        operationGenerationRef.current === operationGeneration &&
        selectedSnapshotRef.current === item.id &&
        detailRequestRef.current === requestId
      );
      try {
        const detail = await getShareSnapshot(customerId, item.id);
        if (!selectionIsCurrent()) return;
        if (
          detail.payload_version !== "v2-immutable-analysis" ||
          !isShareSnapshotPayload(detail.payload)
        ) {
          setDetailError("저장된 화면의 형식을 확인하고 있어요. 잠시 뒤 다시 불러와 주세요.");
          return;
        }
        setSelectedDetail(detail);
        setSelectedItem(detail);
      } catch (error) {
        if (selectionIsCurrent()) {
          setDetailError(historyError(error, "그때 화면을 불러오지 못했어요."));
        }
      } finally {
        if (selectionIsCurrent()) setDetailLoading(false);
      }
    })();
  }, [customerId]);

  const revoke = useCallback(async () => {
    if (
      !selectedItem ||
      selectedItem.link_status !== "active" ||
      selectedItem.payload_version !== "v2-immutable-analysis" ||
      revokeActionsRef.current.has(selectedItem.id)
    ) {
      return;
    }
    const snapshotId = selectedItem.id;
    const actionToken = ++revokeRequestRef.current;
    revokeActionsRef.current.set(snapshotId, actionToken);
    latestRevokeActionsRef.current.set(snapshotId, actionToken);
    setRevokeLoadingActions((current) => ({ ...current, [snapshotId]: actionToken }));
    setRevokeError(null);
    const actionIsLatest = () => (
      mountedRef.current &&
      customerRef.current === customerId &&
      latestRevokeActionsRef.current.get(snapshotId) === actionToken
    );
    const actionIsCurrent = () => (
      actionIsLatest() &&
      revokeActionsRef.current.get(snapshotId) === actionToken
    );
    const selectionMatchesAction = () => (
      actionIsLatest() &&
      selectedSnapshotRef.current === snapshotId
    );
    try {
      await revokeShareSnapshot(customerId, snapshotId);
      if (!actionIsCurrent()) return;
      const revokedAt = new Date().toISOString();
      const toRevoked = <T extends ShareSnapshotListItem>(value: T): T => ({
        ...value,
        link_status: "revoked",
        revoked_at: revokedAt,
        revoked_reason: "manual",
      });
      setItems((current) => current?.map((item) => item.id === snapshotId ? toRevoked(item) : item) ?? current);
      if (selectionMatchesAction()) {
        setSelectedItem((current) => current && current.id === snapshotId ? toRevoked(current) : current);
        setSelectedDetail((current) => current && current.id === snapshotId ? toRevoked(current) : current);
        setRevokeConfirm(false);
      }
      void loadList(true);
      if (selectionMatchesAction()) {
        const detailRequestId = ++detailRequestRef.current;
        void getShareSnapshot(customerId, snapshotId).then((detail) => {
          if (
            actionIsLatest() &&
            selectedSnapshotRef.current === snapshotId &&
            detailRequestRef.current === detailRequestId &&
            detail.payload_version === "v2-immutable-analysis" &&
            isShareSnapshotPayload(detail.payload)
          ) {
            setSelectedDetail(detail);
            setSelectedItem(detail);
          }
        }).catch(() => {
          // 회수 상태는 이미 반영되었으므로 저장된 본문 새로고침 실패는 화면을 되돌리지 않는다.
        });
      }
    } catch (error) {
      if (selectionMatchesAction()) {
        setRevokeError(historyError(error, "링크를 회수하지 못했어요. 다시 시도해 주세요."));
      }
    } finally {
      if (actionIsCurrent()) {
        revokeActionsRef.current.delete(snapshotId);
        setRevokeLoadingActions((current) => {
          if (current[snapshotId] !== actionToken) return current;
          const next = { ...current };
          delete next[snapshotId];
          return next;
        });
      }
    }
  }, [customerId, loadList, selectedItem]);

  const backToList = () => {
    operationGenerationRef.current += 1;
    selectedSnapshotRef.current = null;
    returnFocusSnapshotRef.current = selectedItem?.id ?? null;
    detailRequestRef.current += 1;
    setSelectedItem(null);
    setSelectedDetail(null);
    setDetailLoading(false);
    setDetailError(null);
    setRevokeConfirm(false);
    setRevokeError(null);
  };

  const selectedRevokeActionToken = selectedItem
    ? revokeActionsRef.current.get(selectedItem.id)
    : undefined;
  const revokeLoading = Boolean(
    selectedItem &&
    selectedRevokeActionToken !== undefined &&
    revokeLoadingActions[selectedItem.id] === selectedRevokeActionToken
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4"
      onClick={closeModal}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="share-history-title"
        className="max-h-[85vh] w-full overflow-y-auto rounded-t-2xl bg-surface p-5 shadow-xl sm:max-w-md sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        {selectedItem ? (
          <>
            <div className="flex items-center gap-2">
              <button
                ref={backButtonRef}
                type="button"
                onClick={backToList}
                className="text-[13px] font-semibold text-ink3"
              >
                ← 목록으로
              </button>
              <button
                type="button"
                onClick={closeModal}
                aria-label="닫기"
                className="ml-auto px-1 text-[20px] leading-none text-ink3"
              >
                ✕
              </button>
            </div>
            <h2 id="share-history-title" className="mt-2 text-[15px] font-bold text-ink">
              {fmtDateTime(selectedItem.captured_at)} 공유 기록
            </h2>
            <SnapshotMetadata item={selectedItem} />

            {selectedItem.link_status === "history_only" ? (
              <div className="mt-3 rounded-xl border border-line bg-surface2 px-3 py-5 text-center text-[12px] leading-5 text-ink3">
                이 기록에서는 공유 날짜와 보험 건수를 확인할 수 있어요.
              </div>
            ) : detailLoading ? (
              <div className="mt-3 h-40 animate-pulse rounded-xl bg-line" aria-label="공유 화면 불러오는 중" />
            ) : detailError ? (
              <div role="alert" className="mt-3 rounded-xl border border-line bg-surface2 px-3 py-5 text-center text-[12px] leading-5 text-ink3">
                {detailError}
                <button
                  type="button"
                  onClick={() => void loadDetail(selectedItem)}
                  className="mt-2 block w-full font-semibold text-brand"
                >
                  다시 불러오기
                </button>
              </div>
            ) : selectedDetail && isShareSnapshotPayload(selectedDetail.payload) ? (
              <div className="mt-3">
                <ShareSnapshotContent payload={selectedDetail.payload} variant="preview" />
              </div>
            ) : null}

            {selectedItem.link_status === "active" && selectedItem.payload_version === "v2-immutable-analysis" && (
              <div className="mt-4 border-t border-line pt-3">
                {revokeLoading ? (
                  <button
                    type="button"
                    disabled
                    className="w-full rounded-xl border border-line px-3 py-2 text-[13px] font-semibold text-ink2 opacity-60"
                  >
                    회수 중…
                  </button>
                ) : revokeConfirm ? (
                  <div className="rounded-xl bg-surface2 p-3">
                    <p className="text-[12px] leading-5 text-ink3">
                      이 링크는 바로 닫히고 공유 기록은 그대로 남아요.
                    </p>
                    <div className="mt-2 flex gap-2">
                      <button
                        ref={revokeConfirmButtonRef}
                        type="button"
                        onClick={() => void revoke()}
                        className="flex-1 rounded-xl bg-danger px-3 py-2 text-[13px] font-bold text-white"
                      >
                        회수 확인
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setRevokeConfirm(false);
                          window.setTimeout(() => revokeButtonRef.current?.focus(), 0);
                        }}
                        className="rounded-xl border border-line px-3 py-2 text-[13px] font-semibold text-ink2"
                      >
                        계속 사용
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    ref={revokeButtonRef}
                    type="button"
                    onClick={() => setRevokeConfirm(true)}
                    className="w-full rounded-xl border border-line px-3 py-2 text-[13px] font-semibold text-ink2"
                  >
                    링크 회수
                  </button>
                )}
                {revokeError && <p role="alert" className="mt-2 text-[12px] text-danger">{revokeError}</p>}
              </div>
            )}
          </>
        ) : (
          <>
            <div className="flex items-center justify-between">
              <h2 id="share-history-title" className="text-[16px] font-extrabold text-ink">공유 기록</h2>
              <button
                ref={initialCloseRef}
                type="button"
                onClick={closeModal}
                aria-label="닫기"
                className="px-1 text-[20px] leading-none text-ink3"
              >
                ✕
              </button>
            </div>
            <p className="mt-1 text-[12px] leading-5 text-ink3">
              고객에게 공유한 시점의 화면을 기록으로 남깁니다. 표시된 날짜에 자동 삭제됩니다.
            </p>

            <div className="mt-3">
              {items === null && !listError ? (
                <div className="space-y-2" aria-label="공유 기록 불러오는 중">
                  {[1, 2].map((id) => <div key={id} className="h-20 animate-pulse rounded-xl bg-line" />)}
                </div>
              ) : listError ? (
                <div role="alert" className="rounded-xl border border-line bg-surface2 px-4 py-6 text-center text-[13px] leading-5 text-ink3">
                  {listError}
                  <button
                    type="button"
                    onClick={() => void loadList()}
                    className="mt-2 block w-full font-semibold text-brand"
                  >
                    다시 불러오기
                  </button>
                </div>
              ) : items?.length === 0 ? (
                <div className="rounded-xl border border-dashed border-line px-4 py-8 text-center">
                  <p className="text-[14px] font-semibold text-ink2">공유 기록이 없어요</p>
                  <p className="mt-1 text-[12px] leading-5 text-ink3">
                    공유 링크를 만들면 그 순간의 화면이 여기에 남아요.
                  </p>
                </div>
              ) : (
                <ul className="space-y-2">
                  {items?.map((item) => {
                    const label = item.link_status === "revoked"
                      ? revokedLabel(item.revoked_reason)
                      : lifecycleLabel(item.link_status);
                    return (
                      <li key={item.id}>
                        <button
                          type="button"
                          data-share-snapshot-id={item.id}
                          aria-label={`${label} ${fmtDateTime(item.captured_at)} 상세 보기`}
                          onClick={() => loadDetail(item)}
                          className="w-full rounded-xl border border-line bg-surface2 px-3 py-3 text-left transition hover:bg-line/40"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-[13px] font-semibold text-ink">{fmtDateTime(item.captured_at)}</span>
                            <span className="shrink-0 rounded-full bg-surface px-2 py-0.5 text-[11px] font-semibold text-ink2">
                              {label}
                            </span>
                          </div>
                          <div className="mt-1 text-[11px] leading-4 text-ink3">
                            보험 {item.insurance_count}건 · {fmtDate(item.retention_expires_at)} 자동 삭제 예정
                          </div>
                          {item.first_viewed_at && (
                            <div className="mt-0.5 text-[11px] leading-4 text-ink3">
                              고객이 처음 확인한 날 {fmtDateTime(item.first_viewed_at)}
                            </div>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function SnapshotMetadata({ item }: { item: ShareSnapshotListItem }) {
  const state = item.link_status === "revoked"
    ? revokedLabel(item.revoked_reason)
    : lifecycleLabel(item.link_status);
  return (
    <div className="mt-3 rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[11px] leading-5 text-ink3">
      <div>상태: <span className="font-semibold text-ink2">{state}</span></div>
      <div>보험 {item.insurance_count}건</div>
      {item.first_viewed_at && <div>고객이 처음 확인한 날: {fmtDateTime(item.first_viewed_at)}</div>}
      <div>기록 삭제 예정일: {fmtDate(item.retention_expires_at)}</div>
    </div>
  );
}
