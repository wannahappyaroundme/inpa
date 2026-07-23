"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ConfirmationDialog } from "@/components/recruiting/confirmation-dialog";
import {
  ApiError,
  createCustomerMemo,
  deleteCustomerMemo,
  getCustomerMemo,
  listCustomerMemos,
  updateCustomerMemo,
  type CustomerMemo,
  type PaginatedResult,
} from "@/lib/api";

interface CustomerMemosProps {
  customerId: number;
  onCountChange: (count: number) => void;
}

interface MemoListViewProps {
  data: PaginatedResult<CustomerMemo> | null;
  mode: "list" | "create";
  draft: string;
  loadError: string | null;
  creating: boolean;
  createError: string | null;
  loading: boolean;
  loadingMore: boolean;
  onDraftChange: (value: string) => void;
  onCreate: () => Promise<void>;
  onEdit: (memo: CustomerMemo, body: string) => Promise<EditResult>;
  onRefreshLatest: (memoId: number) => Promise<boolean>;
  onDelete: (memoId: number) => Promise<string | null>;
  onReload: () => Promise<boolean>;
  onReconcile: () => Promise<boolean>;
  onLoadMore: () => Promise<void>;
  onModeChange: (mode: "list" | "create") => void;
  customerId: number;
  focusRestoreVersion: number;
}

interface EditResult {
  kind: "saved" | "noop" | "error" | "reconciled" | "refresh_needed" | "stale";
  message?: string;
}

const MAX_BODY_LENGTH = 10_000;
const dateFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Seoul",
});

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

function formatMemoDate(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return dateFormatter
    .format(date)
    .replace(/\bAM\b/g, "오전")
    .replace(/\bPM\b/g, "오후");
}

function sourceTimeLabel(memo: CustomerMemo): string {
  if (memo.source === "legacy_migrated") return "옮긴 시각";
  if (memo.source === "ai_summary") return "상담 시각";
  return "작성 시각";
}

function pageFromNext(next: string, fallback: number): number {
  try {
    const value = new URL(next, "https://inpa.local").searchParams.get("page");
    const page = Number(value);
    return Number.isInteger(page) && page > 0 ? page : fallback;
  } catch {
    return fallback;
  }
}

function countLabel(count: number): string {
  return `상담 메모 ${count.toLocaleString("ko-KR")}개`;
}

export function CustomerMemos({ customerId, onCountChange }: CustomerMemosProps) {
  const [data, setData] = useState<PaginatedResult<CustomerMemo> | null>(null);
  const [mode, setMode] = useState<"list" | "create">("list");
  const [draft, setDraft] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [creating, setCreating] = useState(false);
  const dataRef = useRef<PaginatedResult<CustomerMemo> | null>(null);
  const countCallbackRef = useRef(onCountChange);
  const customerGenerationRef = useRef(0);
  const listGenerationRef = useRef(0);
  const pageRef = useRef(1);
  const moreBusyRef = useRef(false);
  const createBusyRef = useRef(false);
  const memoRefreshVersionsRef = useRef(new Map<number, number>());
  const [focusRestoreVersion, setFocusRestoreVersion] = useState(0);

  useEffect(() => {
    countCallbackRef.current = onCountChange;
  }, [onCountChange]);

  const replaceData = useCallback((next: PaginatedResult<CustomerMemo> | null) => {
    dataRef.current = next;
    setData(next);
  }, []);

  const emitCount = useCallback((count: number) => {
    countCallbackRef.current(count);
  }, []);

  const loadPage = useCallback(async (page: number, append: boolean, customerGeneration: number): Promise<boolean> => {
    const requestId = ++listGenerationRef.current;
    const isCurrent = () => customerGeneration === customerGenerationRef.current && requestId === listGenerationRef.current;
    if (append) setLoadingMore(true);
    else {
      setLoading(true);
      setLoadError(null);
    }

    try {
      const result = await listCustomerMemos(customerId, page);
      if (!isCurrent()) return false;

      if (append) {
        const current = dataRef.current;
        if (!current) return false;
        const knownIds = new Set(current.results.map((memo) => memo.id));
        const next = {
          ...result,
          results: [...current.results, ...result.results.filter((memo) => !knownIds.has(memo.id))],
        };
        replaceData(next);
      } else {
        replaceData(result);
      }
      pageRef.current = page;
      setLoadError(null);
      emitCount(result.count);
      return true;
    } catch (error) {
      if (!isCurrent()) return false;
      setLoadError(messageFrom(error, "상담 메모를 불러오지 못했어요. 다시 불러와 주세요."));
      return false;
    } finally {
      if (isCurrent()) {
        setLoading(false);
        setLoadingMore(false);
        moreBusyRef.current = false;
      }
    }
  }, [customerId, emitCount, replaceData]);

  useEffect(() => {
    const customerGeneration = ++customerGenerationRef.current;
    listGenerationRef.current += 1;
    pageRef.current = 1;
    moreBusyRef.current = false;
    createBusyRef.current = false;
    memoRefreshVersionsRef.current.clear();
    setCreating(false);
    setLoadingMore(false);
    replaceData(null);
    setMode("list");
    setDraft("");
    setCreateError(null);
    setLoadError(null);
    setLoading(true);
    void loadPage(1, false, customerGeneration);
    return () => {
      customerGenerationRef.current += 1;
      listGenerationRef.current += 1;
    };
  }, [customerId, loadPage, replaceData]);

  const reload = useCallback(async (customerGeneration = customerGenerationRef.current) => {
    return loadPage(1, false, customerGeneration);
  }, [loadPage]);

  const reconcileLoadedPages = useCallback(async (
    customerGeneration = customerGenerationRef.current,
    failureMessage = "메모 목록을 다시 맞추면 최신 순서로 이어서 볼 수 있어요.",
  ): Promise<boolean> => {
    if (moreBusyRef.current) return false;
    moreBusyRef.current = true;
    const requestId = ++listGenerationRef.current;
    const highestLoadedPage = Math.max(1, pageRef.current);
    const isCurrent = () => (
      customerGeneration === customerGenerationRef.current
      && requestId === listGenerationRef.current
    );
    setLoadingMore(true);
    setLoadError(null);

    try {
      const pages: PaginatedResult<CustomerMemo>[] = [];
      for (let page = 1; page <= highestLoadedPage; page += 1) {
        const result = await listCustomerMemos(customerId, page);
        if (!isCurrent()) return false;
        pages.push(result);
        if (!result.next) break;
      }
      const first = pages[0];
      const last = pages.at(-1);
      if (!first || !last) return false;
      const knownIds = new Set<number>();
      const results = pages.flatMap((page) => page.results).filter((memo) => {
        if (knownIds.has(memo.id)) return false;
        knownIds.add(memo.id);
        return true;
      });
      const previousCount = dataRef.current?.count;
      replaceData({
        count: first.count,
        next: last.next,
        previous: null,
        results,
      });
      pageRef.current = pages.length;
      setLoadError(null);
      if (previousCount !== first.count) emitCount(first.count);
      return true;
    } catch {
      if (!isCurrent()) return false;
      setLoadError(failureMessage);
      return false;
    } finally {
      if (isCurrent()) {
        moreBusyRef.current = false;
        setLoadingMore(false);
      }
    }
  }, [customerId, emitCount, replaceData]);

  const refreshMemo = useCallback(async (
    memoId: number,
    customerGeneration = customerGenerationRef.current,
  ): Promise<boolean> => {
    const version = (memoRefreshVersionsRef.current.get(memoId) ?? 0) + 1;
    memoRefreshVersionsRef.current.set(memoId, version);
    const isCurrent = () => (
      customerGeneration === customerGenerationRef.current
      && memoRefreshVersionsRef.current.get(memoId) === version
    );
    try {
      const latest = await getCustomerMemo(customerId, memoId);
      if (!isCurrent()) return false;
      const current = dataRef.current;
      if (!current || !current.results.some((memo) => memo.id === memoId)) return false;
      replaceData({
        ...current,
        results: current.results.map((memo) => memo.id === memoId ? latest : memo),
      });
      return true;
    } catch {
      return false;
    }
  }, [customerId, replaceData]);

  const beginMutation = useCallback(() => {
    const customerGeneration = customerGenerationRef.current;
    listGenerationRef.current += 1;
    moreBusyRef.current = false;
    setLoadingMore(false);
    return customerGeneration;
  }, []);

  const isCurrentCustomer = useCallback((customerGeneration: number) => (
    customerGeneration === customerGenerationRef.current
  ), []);

  const saveNew = useCallback(async () => {
    if (createBusyRef.current) return;
    const body = draft.trim();
    if (!body) {
      setCreateError("메모 내용을 입력해 주세요.");
      return;
    }
    if (body.length > MAX_BODY_LENGTH) {
      setCreateError("메모는 10,000자까지 입력할 수 있어요.");
      return;
    }

    const customerGeneration = beginMutation();
    createBusyRef.current = true;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await createCustomerMemo(customerId, body);
      if (!isCurrentCustomer(customerGeneration)) return;
      const current = dataRef.current;
      if (!current) return;
      const next = {
        ...current,
        count: current.count + 1,
        results: [created, ...current.results.filter((memo) => memo.id !== created.id)],
      };
      replaceData(next);
      emitCount(next.count);
      setDraft("");
      setMode("list");
    } catch (error) {
      if (!isCurrentCustomer(customerGeneration)) return;
      setCreateError(messageFrom(error, "메모를 저장하지 못했어요. 다시 저장해 주세요."));
    } finally {
      if (isCurrentCustomer(customerGeneration)) {
        createBusyRef.current = false;
        setCreating(false);
      }
    }
  }, [beginMutation, customerId, draft, emitCount, isCurrentCustomer, replaceData]);

  const saveEdit = useCallback(async (memo: CustomerMemo, body: string): Promise<EditResult> => {
    const normalized = body.trim();
    if (!normalized) return { kind: "error", message: "메모 내용을 입력해 주세요." };
    if (normalized.length > MAX_BODY_LENGTH) {
      return { kind: "error", message: "메모는 10,000자까지 입력할 수 있어요." };
    }
    if (normalized === memo.body) return { kind: "noop" };

    const customerGeneration = beginMutation();
    try {
      const changed = await updateCustomerMemo(customerId, memo, normalized);
      if (!isCurrentCustomer(customerGeneration)) return { kind: "stale" };
      const current = dataRef.current;
      if (current) {
        replaceData({
          ...current,
          results: current.results.map((item) => item.id === changed.id ? changed : item),
        });
      }
      return { kind: "saved" };
    } catch (error) {
      if (!isCurrentCustomer(customerGeneration)) return { kind: "stale" };
      if (error instanceof ApiError && error.code === "MEMO_EDIT_CONFLICT") {
        const reloaded = await refreshMemo(memo.id, customerGeneration);
        if (!isCurrentCustomer(customerGeneration)) return { kind: "stale" };
        if (!reloaded) {
          return {
            kind: "refresh_needed",
            message: "최신 내용을 다시 불러오면 작성한 내용을 이어서 저장할 수 있어요.",
          };
        }
        return {
          kind: "reconciled",
          message: "내가 작성한 내용은 그대로 남아 있어요. 최신 내용을 확인한 뒤 다시 저장해 주세요.",
        };
      }
      return { kind: "error", message: messageFrom(error, "메모를 저장하지 못했어요. 다시 저장해 주세요.") };
    }
  }, [beginMutation, customerId, isCurrentCustomer, refreshMemo, replaceData]);

  const removeMemo = useCallback(async (memoId: number): Promise<string | null> => {
    const customerGeneration = beginMutation();
    try {
      await deleteCustomerMemo(customerId, memoId);
      if (!isCurrentCustomer(customerGeneration)) return null;
      const current = dataRef.current;
      if (!current) return null;
      const next = {
        ...current,
        count: Math.max(0, current.count - 1),
        results: current.results.filter((memo) => memo.id !== memoId),
      };
      replaceData(next);
      emitCount(next.count);
      setFocusRestoreVersion((current) => current + 1);
      await reconcileLoadedPages(
        customerGeneration,
        "삭제는 완료했어요. 메모 목록만 다시 맞춰 주세요.",
      );
      return null;
    } catch (error) {
      if (!isCurrentCustomer(customerGeneration)) return null;
      return messageFrom(error, "메모를 삭제하지 못했어요. 다시 시도해 주세요.");
    }
  }, [beginMutation, customerId, emitCount, isCurrentCustomer, reconcileLoadedPages, replaceData]);

  const loadMore = useCallback(async () => {
    const current = dataRef.current;
    if (!current?.next || moreBusyRef.current) return;
    const customerGeneration = customerGenerationRef.current;
    moreBusyRef.current = true;
    await loadPage(pageFromNext(current.next, pageRef.current + 1), true, customerGeneration);
  }, [loadPage]);

  return (
    <MemoListView
      data={data}
      mode={mode}
      draft={draft}
      loadError={loadError}
      creating={creating}
      createError={createError}
      loading={loading}
      loadingMore={loadingMore}
      onDraftChange={setDraft}
      onCreate={saveNew}
      onEdit={saveEdit}
      onRefreshLatest={refreshMemo}
      onDelete={removeMemo}
      onReload={reload}
      onReconcile={reconcileLoadedPages}
      onLoadMore={loadMore}
      onModeChange={(nextMode) => {
        setMode(nextMode);
        setCreateError(null);
      }}
      customerId={customerId}
      focusRestoreVersion={focusRestoreVersion}
    />
  );
}

function MemoListView({
  data,
  mode,
  draft,
  loadError,
  creating,
  createError,
  loading,
  loadingMore,
  onDraftChange,
  onCreate,
  onEdit,
  onRefreshLatest,
  onDelete,
  onReload,
  onReconcile,
  onLoadMore,
  onModeChange,
  customerId,
  focusRestoreVersion,
}: MemoListViewProps) {
  const normalizedDraft = draft.trim();
  const draftTooLong = normalizedDraft.length > MAX_BODY_LENGTH;
  const createButtonRef = useRef<HTMLButtonElement>(null);
  const createTextareaRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const previousModeRef = useRef(mode);

  useEffect(() => {
    const previousMode = previousModeRef.current;
    previousModeRef.current = mode;
    const frame = requestAnimationFrame(() => {
      if (mode === "create") createTextareaRef.current?.focus();
      else if (previousMode === "create") createButtonRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [mode]);

  useEffect(() => {
    if (focusRestoreVersion === 0) return;
    const frame = requestAnimationFrame(() => {
      if (createButtonRef.current?.isConnected) createButtonRef.current.focus();
      else listRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [focusRestoreVersion]);

  function closeCreate() {
    onModeChange("list");
  }

  if (loading && !data) {
    return (
      <section aria-busy="true" aria-label="상담 메모를 불러오는 중" className="space-y-3">
        {[0, 1, 2].map((item) => (
          <div key={item} aria-label="상담 메모를 불러오는 중" className="animate-pulse rounded-2xl border border-line bg-surface p-4 shadow-card">
            <div className="h-4 w-1/4 rounded bg-surface2" />
            <div className="mt-3 h-4 w-full rounded bg-surface2" />
            <div className="mt-2 h-4 w-4/5 rounded bg-surface2" />
          </div>
        ))}
      </section>
    );
  }

  if (!data && loadError) {
    return (
      <section className="rounded-2xl border border-line bg-surface p-5 shadow-card" aria-live="polite">
        <h2 className="text-[17px] font-extrabold text-ink">상담 메모</h2>
        <p role="alert" className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-[13px] leading-5 text-danger-ink">{loadError}</p>
        <button type="button" onClick={() => void onReload()} className="mt-4 min-h-11 rounded-xl bg-brand px-4 text-[14px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">
          다시 불러오기
        </button>
      </section>
    );
  }

  if (!data) return null;

  return (
    <section className="rounded-2xl border border-line bg-surface p-4 shadow-card sm:p-5" aria-busy={loadingMore || creating}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[17px] font-extrabold text-ink">{countLabel(data.count)}</h2>
          <p className="mt-1 text-[13px] text-ink3">상담 뒤 기억할 내용을 차분히 남겨보세요.</p>
        </div>
        {mode === "list" && (
          <button ref={createButtonRef} type="button" onClick={() => onModeChange("create")} className="min-h-11 rounded-xl bg-brand px-4 text-[14px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">
            메모 작성
          </button>
        )}
      </div>

      {loadError && (
        <div className="mt-4 rounded-xl bg-danger-tint px-3 py-3">
          <p role="alert" className="text-[13px] leading-5 text-danger-ink">{loadError}</p>
          <button type="button" disabled={loadingMore} onClick={() => void onReconcile()} className="mt-2 min-h-11 rounded-xl bg-surface px-3 text-[13px] font-bold text-brand disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">
            {loadingMore ? "메모 목록을 맞추는 중" : "메모 목록 다시 맞추기"}
          </button>
        </div>
      )}

      {mode === "create" && (
        <form className="mt-5 rounded-2xl border border-brand/30 bg-brand-soft p-4" onSubmit={(event) => { event.preventDefault(); void onCreate(); }}>
          <label htmlFor="customer-memo-create" className="text-[14px] font-bold text-ink">새 메모</label>
          <textarea
            id="customer-memo-create"
            ref={createTextareaRef}
            aria-describedby="customer-memo-create-count"
            aria-invalid={Boolean(createError) || draftTooLong}
            aria-readonly={creating}
            readOnly={creating}
            value={draft}
            onChange={(event) => onDraftChange(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Escape" && !creating) closeCreate(); }}
            rows={5}
            placeholder="상담에서 확인한 내용과 다음 약속을 적어보세요."
            className="mt-2 min-h-32 w-full resize-y rounded-xl border border-line bg-surface px-3 py-3 text-[14px] leading-6 text-ink placeholder:text-muted outline-none focus:border-brand focus-visible:ring-2 focus-visible:ring-brand"
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[12px]">
            <p id="customer-memo-create-count" className={draftTooLong ? "font-semibold text-danger-ink" : "text-ink3"}>{normalizedDraft.length.toLocaleString("ko-KR")} / 10,000자</p>
            <p className="text-ink3">내용을 확인한 뒤 저장해 주세요.</p>
          </div>
          {createError && <p role="alert" className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-[13px] leading-5 text-danger-ink">{createError}</p>}
          {creating && <p role="status" aria-live="polite" className="mt-3 text-[13px] font-semibold text-ink2">메모를 저장하고 있어요</p>}
          <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" disabled={creating} onClick={closeCreate} className="min-h-11 rounded-xl border border-line bg-surface px-4 text-[14px] font-semibold text-ink2 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">취소</button>
            <button type="submit" disabled={creating || draftTooLong} className="min-h-11 rounded-xl bg-brand px-4 text-[14px] font-bold text-white disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">{creating ? "저장 중" : createError ? "다시 저장" : "메모 저장"}</button>
          </div>
        </form>
      )}

      {data.count === 0 ? (
        <div className="mt-6 rounded-2xl bg-surface2 px-4 py-8 text-center">
          <p className="text-[15px] font-bold text-ink">첫 상담 메모를 남겨보세요.</p>
          <p className="mt-2 text-[13px] leading-5 text-ink2">다음 만남에서 이어갈 내용을 한 줄부터 적을 수 있어요.</p>
        </div>
      ) : (
        <ul ref={listRef} tabIndex={-1} className="mt-5 space-y-3" aria-label="상담 메모 목록">
          {data.results.map((memo) => <li key={`${customerId}-${memo.id}`}><MemoCard memo={memo} onEdit={onEdit} onRefreshLatest={onRefreshLatest} onDelete={onDelete} /></li>)}
        </ul>
      )}

      {data.next && (
        <button type="button" disabled={loadingMore} onClick={() => void onLoadMore()} className="mt-4 min-h-11 w-full rounded-xl border border-line bg-surface px-4 text-[14px] font-bold text-brand disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">
          {loadingMore ? "이전 메모를 불러오는 중" : "이전 메모 더 보기"}
        </button>
      )}
    </section>
  );
}

function MemoCard({ memo, onEdit, onRefreshLatest, onDelete }: {
  memo: CustomerMemo;
  onEdit: (memo: CustomerMemo, body: string) => Promise<EditResult>;
  onRefreshLatest: (memoId: number) => Promise<boolean>;
  onDelete: (memoId: number) => Promise<string | null>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(memo.body);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [reconciled, setReconciled] = useState(false);
  const [refreshNeeded, setRefreshNeeded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const editTextareaRef = useRef<HTMLTextAreaElement>(null);
  const editBusyRef = useRef(false);
  const deleteBusyRef = useRef(false);
  const normalizedDraft = draft.trim();
  const draftTooLong = normalizedDraft.length > MAX_BODY_LENGTH;

  useEffect(() => {
    if (!editing) setDraft(memo.body);
  }, [editing, memo.body]);

  useEffect(() => {
    if (!editing) return;
    const frame = requestAnimationFrame(() => editTextareaRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [editing]);

  async function save() {
    if (editBusyRef.current || draftTooLong || refreshNeeded) return;
    editBusyRef.current = true;
    setSaving(true);
    setError(null);
    const result = await onEdit(memo, draft);
    editBusyRef.current = false;
    setSaving(false);
    if (result.kind === "saved" || result.kind === "noop") {
      setReconciled(false);
      setRefreshNeeded(false);
      setEditing(false);
      requestAnimationFrame(() => editButtonRef.current?.focus());
      return;
    }
    if (result.kind === "stale") return;
    setReconciled(result.kind === "reconciled");
    setRefreshNeeded(result.kind === "refresh_needed");
    setError(result.message ?? "메모를 저장하지 못했어요. 다시 저장해 주세요.");
  }

  async function refreshLatest() {
    if (refreshing) return;
    setRefreshing(true);
    setError(null);
    const refreshed = await onRefreshLatest(memo.id);
    setRefreshing(false);
    if (!refreshed) {
      setError("최신 내용을 다시 불러오면 작성한 내용을 이어서 저장할 수 있어요.");
      return;
    }
    setRefreshNeeded(false);
    setReconciled(true);
    setError("내가 작성한 내용은 그대로 남아 있어요. 최신 내용을 확인한 뒤 다시 저장해 주세요.");
  }

  function cancelEdit() {
    setDraft(memo.body);
    setError(null);
    setReconciled(false);
    setRefreshNeeded(false);
    setEditing(false);
    requestAnimationFrame(() => editButtonRef.current?.focus());
  }

  async function confirmDelete() {
    if (deleteBusyRef.current) return;
    deleteBusyRef.current = true;
    setDeleting(true);
    const result = await onDelete(memo.id);
    deleteBusyRef.current = false;
    setDeleting(false);
    if (!result) {
      setDeleteOpen(false);
      return;
    }
    setDeleteOpen(false);
    setDeleteError(result);
  }

  return (
    <article className="rounded-2xl border border-line bg-surface p-4" aria-busy={saving || deleting}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="inline-flex rounded-full bg-surface2 px-2.5 py-1 text-[12px] font-bold text-ink2">{memo.source_label || "-"}</span>
          <p className="mt-2 text-[12px] text-ink3">{sourceTimeLabel(memo)} {formatMemoDate(memo.occurred_at ?? memo.created_at)}</p>
          {memo.edited_at && <p className="mt-1 text-[12px] text-ink3">마지막 수정 {formatMemoDate(memo.edited_at)} · 수정됨</p>}
        </div>
        {!editing && (
          <div className="flex shrink-0 gap-2">
            <button ref={editButtonRef} type="button" onClick={() => { setEditing(true); setError(null); setReconciled(false); setRefreshNeeded(false); }} className="min-h-11 rounded-xl px-3 text-[13px] font-bold text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2" aria-label={`메모 수정: ${memo.body}`}>수정</button>
            <button type="button" onClick={() => { setDeleteOpen(true); setDeleteError(null); }} className="min-h-11 rounded-xl px-3 text-[13px] font-bold text-danger-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2" aria-label={`메모 삭제: ${memo.body}`}>삭제</button>
          </div>
        )}
      </div>

      {editing ? (
        <div className="mt-4">
          <label htmlFor={`customer-memo-${memo.id}`} className="sr-only">메모 수정</label>
          <textarea ref={editTextareaRef} id={`customer-memo-${memo.id}`} aria-describedby={`customer-memo-${memo.id}-count`} aria-invalid={Boolean(error) || draftTooLong} aria-readonly={saving} readOnly={saving} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape" && !saving && !refreshing) cancelEdit(); }} rows={5} className="min-h-32 w-full resize-y rounded-xl border border-line bg-surface px-3 py-3 text-[14px] leading-6 text-ink outline-none focus:border-brand focus-visible:ring-2 focus-visible:ring-brand" />
          <p id={`customer-memo-${memo.id}-count`} className={`mt-2 text-[12px] ${draftTooLong ? "font-semibold text-danger-ink" : "text-ink3"}`}>{normalizedDraft.length.toLocaleString("ko-KR")} / 10,000자</p>
          {reconciled && <p className="mt-3 rounded-xl bg-surface2 px-3 py-2 text-[13px] leading-5 text-ink2">최신 메모: {memo.body || "-"}</p>}
          {error && <p role="alert" className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-[13px] leading-5 text-danger-ink">{error}</p>}
          {saving && <p role="status" aria-live="polite" className="mt-3 text-[13px] font-semibold text-ink2">메모를 저장하고 있어요</p>}
          <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" disabled={saving || refreshing} onClick={cancelEdit} className="min-h-11 rounded-xl border border-line bg-surface px-4 text-[14px] font-semibold text-ink2 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">취소</button>
            {refreshNeeded ? (
              <button type="button" disabled={refreshing} onClick={() => void refreshLatest()} className="min-h-11 rounded-xl bg-brand px-4 text-[14px] font-bold text-white disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">{refreshing ? "최신 내용을 불러오는 중" : "최신 내용 다시 불러오기"}</button>
            ) : (
              <button type="button" disabled={saving || draftTooLong} onClick={() => void save()} className="min-h-11 rounded-xl bg-brand px-4 text-[14px] font-bold text-white disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">수정 저장</button>
            )}
          </div>
        </div>
      ) : (
        <p className="mt-4 whitespace-pre-wrap break-words text-[14px] leading-6 text-ink">{memo.body || "-"}</p>
      )}

      {deleteError && (
        <div className="mt-4 rounded-xl bg-danger-tint px-3 py-3">
          <p role="alert" className="text-[13px] leading-5 text-danger-ink">{deleteError}</p>
          <button type="button" onClick={() => void confirmDelete()} className="mt-2 min-h-11 rounded-xl bg-surface px-3 text-[13px] font-bold text-danger-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">삭제 다시 시도</button>
        </div>
      )}

      <ConfirmationDialog
        open={deleteOpen}
        title="이 메모를 삭제할까요?"
        description="삭제한 메모는 다시 볼 수 없어요. 내용을 한 번 더 확인해 주세요."
        confirmLabel="삭제할게요"
        pendingLabel="삭제 중"
        pending={deleting}
        onConfirm={() => void confirmDelete()}
        onClose={() => setDeleteOpen(false)}
      />
    </article>
  );
}
