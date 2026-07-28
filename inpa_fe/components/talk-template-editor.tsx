"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { X } from "lucide-react";

import type { PersonalTalkTemplatePayload } from "@/lib/api";
import {
  COPY_CATEGORIES,
  getAdvertisingVariableGuidance,
} from "@/lib/copy-library";

export type TalkTemplateEditorMode =
  | "create"
  | "edit"
  | "duplicate"
  | "copy-default";

interface TalkTemplateEditorProps {
  open: boolean;
  mode: TalkTemplateEditorMode;
  initialValue?: PersonalTalkTemplatePayload;
  saving: boolean;
  error: string | null;
  returnFocusTo?: HTMLElement | null;
  onSave: (payload: PersonalTalkTemplatePayload) => void;
  onClose: () => void;
}

interface EditorDraft {
  source_key: string | null;
  title: string;
  body: string;
  category: string;
  channel: "message" | "call";
  sort_order: string;
  is_active: boolean;
}

interface EditorErrors {
  title?: string;
  body?: string;
  category?: string;
  sort_order?: string;
}

const MODE_TITLES: Record<TalkTemplateEditorMode, string> = {
  create: "나만의 화법 추가",
  edit: "나만의 화법 수정",
  duplicate: "나만의 화법 복제",
  "copy-default": "기본 화법을 내 템플릿으로 저장",
};

const VARIABLES = [
  ["고객명", "{고객명}"],
  ["설계사명", "{설계사명}"],
  ["소속직책", "{소속직책}"],
] as const;

function initialDraft(
  initialValue?: PersonalTalkTemplatePayload,
): EditorDraft {
  return {
    source_key: initialValue?.source_key ?? null,
    title: initialValue?.title ?? "",
    body: initialValue?.body ?? "",
    category: initialValue?.category ?? COPY_CATEGORIES[0].key,
    channel: initialValue?.channel ?? "message",
    sort_order: String(initialValue?.sort_order ?? 0),
    is_active: initialValue?.is_active ?? true,
  };
}

function validate(draft: EditorDraft): EditorErrors {
  const errors: EditorErrors = {};
  const title = draft.title.trim();
  const category = draft.category.trim();
  if (!title) errors.title = "제목을 입력해 주세요.";
  else if (draft.title.length > 100) {
    errors.title = "제목은 100자까지 입력할 수 있어요.";
  }
  if (!category) errors.category = "분류를 입력해 주세요.";
  else if (draft.category.length > 40) {
    errors.category = "분류는 40자까지 입력할 수 있어요.";
  }
  if (!draft.body.trim()) errors.body = "본문을 입력해 주세요.";
  else if (draft.body.length > 5000) {
    errors.body = "본문은 5,000자까지 입력할 수 있어요.";
  } else {
    const advertisingGuidance = getAdvertisingVariableGuidance(
      draft.source_key,
      draft.body,
    );
    if (advertisingGuidance) errors.body = advertisingGuidance;
  }
  const sortOrder = Number(draft.sort_order);
  if (!Number.isInteger(sortOrder)) {
    errors.sort_order = "정렬 순서는 정수로 입력해 주세요.";
  }
  return errors;
}

export function TalkTemplateEditor({
  open,
  mode,
  initialValue,
  saving,
  error,
  returnFocusTo,
  onSave,
  onClose,
}: TalkTemplateEditorProps) {
  const titleId = useId();
  const titleErrorId = useId();
  const categoryErrorId = useId();
  const bodyErrorId = useId();
  const sortErrorId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const savingRef = useRef(saving);
  const onCloseRef = useRef(onClose);
  const [draft, setDraft] = useState<EditorDraft>(() =>
    initialDraft(initialValue),
  );
  const [errors, setErrors] = useState<EditorErrors>({});
  savingRef.current = saving;
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    setDraft(initialDraft(initialValue));
    setErrors({});
  }, [initialValue, mode, open]);

  useEffect(() => {
    if (!open) return;
    openerRef.current =
      returnFocusTo ??
      (document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(() => titleInputRef.current?.focus());

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !savingRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (
        !event.shiftKey &&
        document.activeElement === last
      ) {
        event.preventDefault();
        first.focus();
      } else if (!dialogRef.current.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    const opener = openerRef.current;
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      if (opener?.isConnected) opener.focus();
    };
  }, [open]);

  if (!open) return null;

  function insertVariable(variable: string) {
    const textarea = bodyRef.current;
    const start = textarea?.selectionStart ?? draft.body.length;
    const end = textarea?.selectionEnd ?? start;
    const nextBody =
      draft.body.slice(0, start) + variable + draft.body.slice(end);
    const nextCaret = start + variable.length;
    setDraft((current) => ({ ...current, body: nextBody }));
    setErrors((current) => ({ ...current, body: undefined }));
    window.setTimeout(() => {
      bodyRef.current?.focus();
      bodyRef.current?.setSelectionRange(nextCaret, nextCaret);
    });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const nextErrors = validate(draft);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    onSave({
      source_key: draft.source_key,
      title: draft.title.trim(),
      body: draft.body,
      category: draft.category.trim(),
      channel: draft.channel,
      sort_order: Number(draft.sort_order),
      is_active: draft.is_active,
    });
  }

  const titleRemaining = Math.max(0, 100 - draft.title.length);
  const categoryRemaining = Math.max(0, 40 - draft.category.length);
  const bodyRemaining = Math.max(0, 5000 - draft.body.length);
  const categoryIsKnown = COPY_CATEGORIES.some(
    (category) => category.key === draft.category,
  );

  return (
    <div
      className="fixed inset-0 z-[100] flex items-end justify-center sm:items-center sm:p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) onClose();
      }}
    >
      <div className="absolute inset-0 -z-10 bg-ink/40 backdrop-blur-[2px]" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="flex max-h-[94dvh] w-full flex-col overflow-hidden rounded-t-3xl bg-surface shadow-2xl sm:max-w-2xl sm:rounded-3xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4 sm:px-6">
          <div>
            <p className="text-xs font-semibold text-brand">나만의 화법</p>
            <h2 id={titleId} className="mt-1 text-lg font-extrabold text-ink">
              {MODE_TITLES[mode]}
            </h2>
            <p className="mt-1 text-xs leading-5 text-ink3">
              고객에게 보낼 원문과 변수만 저장돼요.
            </p>
          </div>
          <button
            type="button"
            aria-label="닫기"
            disabled={saving}
            onClick={onClose}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-line text-ink3 transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X aria-hidden="true" size={20} />
          </button>
        </header>

        <form
          onSubmit={submit}
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className="space-y-5 overflow-y-auto bg-canvas px-5 py-5 sm:px-6">
            <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_11rem]">
              <label className="block">
                <span className="flex items-center justify-between gap-3 text-sm font-bold text-ink">
                  제목
                  <span className="text-xs font-medium text-ink3">
                    제목 {titleRemaining}자 남음
                  </span>
                </span>
                <input
                  ref={titleInputRef}
                  aria-label="제목"
                  value={draft.title}
                  disabled={saving}
                  aria-invalid={errors.title ? "true" : undefined}
                  aria-describedby={errors.title ? titleErrorId : undefined}
                  onChange={(event) => {
                    setDraft((current) => ({
                      ...current,
                      title: event.target.value,
                    }));
                    setErrors((current) => ({
                      ...current,
                      title: undefined,
                    }));
                  }}
                  className="mt-2 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:bg-surface2"
                />
                {errors.title && (
                  <span
                    id={titleErrorId}
                    role="alert"
                    className="mt-1.5 block text-xs font-semibold text-danger"
                  >
                    {errors.title}
                  </span>
                )}
              </label>

              <div className="block">
                <span className="text-sm font-bold text-ink">분류</span>
                <select
                  aria-label="분류"
                  value={categoryIsKnown ? draft.category : "__custom__"}
                  disabled={saving}
                  aria-invalid={errors.category ? "true" : undefined}
                  aria-describedby={
                    errors.category ? categoryErrorId : undefined
                  }
                  onChange={(event) => {
                    setDraft((current) => ({
                      ...current,
                      category:
                        event.target.value === "__custom__"
                          ? ""
                          : event.target.value,
                    }));
                    setErrors((current) => ({
                      ...current,
                      category: undefined,
                    }));
                  }}
                  className="mt-2 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:bg-surface2"
                >
                  {COPY_CATEGORIES.map((category) => (
                    <option key={category.key} value={category.key}>
                      {category.label}
                    </option>
                  ))}
                  <option value="__custom__">직접 입력</option>
                </select>
                {!categoryIsKnown && (
                  <label className="mt-2 block">
                    <span className="flex items-center justify-between gap-2 text-xs font-bold text-ink2">
                      직접 만든 분류
                      <span className="font-medium text-ink3">
                        분류 {categoryRemaining}자 남음
                      </span>
                    </span>
                    <input
                      aria-label="직접 만든 분류"
                      value={draft.category}
                      disabled={saving}
                      aria-invalid={errors.category ? "true" : undefined}
                      aria-describedby={
                        errors.category ? categoryErrorId : undefined
                      }
                      onChange={(event) => {
                        setDraft((current) => ({
                          ...current,
                          category: event.target.value,
                        }));
                        setErrors((current) => ({
                          ...current,
                          category: undefined,
                        }));
                      }}
                      className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:bg-surface2"
                    />
                  </label>
                )}
                {errors.category && (
                  <span
                    id={categoryErrorId}
                    role="alert"
                    className="mt-1.5 block text-xs font-semibold text-danger"
                  >
                    {errors.category}
                  </span>
                )}
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="text-sm font-bold text-ink">사용 방식</span>
                <select
                  aria-label="사용 방식"
                  value={draft.channel}
                  disabled={saving}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      channel: event.target.value as "message" | "call",
                    }))
                  }
                  className="mt-2 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:bg-surface2"
                >
                  <option value="message">메시지</option>
                  <option value="call">통화</option>
                </select>
              </label>

              <label className="block">
                <span className="text-sm font-bold text-ink">정렬 순서</span>
                <input
                  aria-label="정렬 순서"
                  type="number"
                  step="1"
                  value={draft.sort_order}
                  disabled={saving}
                  aria-invalid={errors.sort_order ? "true" : undefined}
                  aria-describedby={
                    errors.sort_order ? sortErrorId : undefined
                  }
                  onChange={(event) => {
                    setDraft((current) => ({
                      ...current,
                      sort_order: event.target.value,
                    }));
                    setErrors((current) => ({
                      ...current,
                      sort_order: undefined,
                    }));
                  }}
                  className="mt-2 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:bg-surface2"
                />
                {errors.sort_order && (
                  <span
                    id={sortErrorId}
                    role="alert"
                    className="mt-1.5 block text-xs font-semibold text-danger"
                  >
                    {errors.sort_order}
                  </span>
                )}
              </label>
            </div>

            <fieldset>
              <legend className="text-sm font-bold text-ink">
                본문에 변수 넣기
              </legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {VARIABLES.map(([label, variable]) => (
                  <button
                    key={variable}
                    type="button"
                    disabled={saving}
                    aria-label={`${label} 변수 넣기`}
                    onClick={() => insertVariable(variable)}
                    className="rounded-full border border-brand/20 bg-brand-soft px-3 py-1.5 text-xs font-bold text-brand transition hover:border-brand/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
                  >
                    {variable}
                  </button>
                ))}
              </div>
            </fieldset>

            <label className="block">
              <span className="flex items-center justify-between gap-3 text-sm font-bold text-ink">
                본문
                <span className="text-xs font-medium text-ink3">
                  본문 {bodyRemaining}자 남음
                </span>
              </span>
              <textarea
                ref={bodyRef}
                aria-label="본문"
                value={draft.body}
                disabled={saving}
                rows={9}
                aria-invalid={errors.body ? "true" : undefined}
                aria-describedby={errors.body ? bodyErrorId : undefined}
                onChange={(event) => {
                  setDraft((current) => ({
                    ...current,
                    body: event.target.value,
                  }));
                  setErrors((current) => ({
                    ...current,
                    body: undefined,
                  }));
                }}
                className="mt-2 min-h-48 w-full resize-y rounded-xl border border-line bg-surface px-3 py-3 text-sm leading-6 text-ink outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:bg-surface2"
              />
              {errors.body && (
                <span
                  id={bodyErrorId}
                  role="alert"
                  className="mt-1.5 block text-xs font-semibold text-danger"
                >
                  {errors.body}
                </span>
              )}
            </label>

            <label className="flex items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3">
              <input
                type="checkbox"
                checked={draft.is_active}
                disabled={saving}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    is_active: event.target.checked,
                  }))
                }
                className="mt-0.5 h-4 w-4 accent-brand"
              />
              <span>
                <span className="block text-sm font-bold text-ink">
                  목록에서 사용
                </span>
                <span className="mt-0.5 block text-xs leading-5 text-ink3">
                  끄면 목록에 남아 있지만 사용하지 않는 문구로 표시돼요.
                </span>
              </span>
            </label>

            {error && (
              <p
                role="alert"
                className="rounded-xl border border-danger/20 bg-danger-soft px-4 py-3 text-sm font-semibold text-danger"
              >
                {error}
              </p>
            )}
          </div>

          <footer className="flex items-center justify-end gap-2 border-t border-line bg-surface px-5 py-4 sm:px-6">
            <button
              type="button"
              disabled={saving}
              onClick={onClose}
              className="min-h-11 rounded-xl border border-line px-5 text-sm font-bold text-ink2 transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={saving}
              className="min-h-11 rounded-xl bg-brand px-6 text-sm font-bold text-white transition hover:bg-brand/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? "저장 중" : "저장"}
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}
