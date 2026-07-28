"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import Link from "next/link";
import {
  AlertCircle,
  ChevronDown,
  EyeOff,
  LoaderCircle,
  MessageSquareText,
  Phone,
  Plus,
  RotateCcw,
  Settings,
  Sparkles,
} from "lucide-react";

import { AppNav } from "@/components/app-nav";
import {
  TalkTemplateEditor,
  type TalkTemplateEditorMode,
} from "@/components/talk-template-editor";
import { TalkTemplateShare } from "@/components/talk-template-share";
import {
  ApiError,
  createPersonalTalkTemplate,
  deletePersonalTalkTemplate,
  getProfile,
  listPersonalTalkTemplates,
  putTalkTemplatePreference,
  updatePersonalTalkTemplate,
  type PersonalTalkTemplate,
  type PersonalTalkTemplatePayload,
  type ProfileResponse,
} from "@/lib/api";
import {
  COPY_CATEGORIES,
  getAdvertisingVariableGuidance,
} from "@/lib/copy-library";
import {
  buildTalkTemplateView,
  createPersonalPayloadFromDefault,
  filterTalkTemplates,
  substituteTalkTemplate,
  type TalkTemplateFilter,
  type TalkTemplateViewItem,
} from "@/lib/talk-template-view-model";
import { useAuthGuard } from "@/lib/useAuthGuard";

interface EditorSession {
  mode: TalkTemplateEditorMode;
  personalId: number | null;
  initialValue?: PersonalTalkTemplatePayload;
}

interface MenuAction {
  label: string;
  onSelect: (opener: HTMLButtonElement | null) => void;
  danger?: boolean;
  disabled?: boolean;
}

function TemplateMenu({
  title,
  actions,
}: {
  title: string;
  actions: MenuAction[];
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const initialMenuFocusRef = useRef<"first" | "last">("first");

  useEffect(() => {
    if (!open) return;
    const focusTimer = window.setTimeout(() => {
      const items = Array.from(
        menuRef.current?.querySelectorAll<HTMLButtonElement>(
          '[role="menuitem"]:not([disabled])',
        ) ?? [],
      );
      const target =
        initialMenuFocusRef.current === "last"
          ? items.at(-1)
          : items[0];
      target?.focus();
    });
    function closeFromOutside(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        !rootRef.current?.contains(event.target)
      ) {
        setOpen(false);
      }
    }
    function closeFromFocus(event: FocusEvent) {
      if (
        event.target instanceof Node &&
        !rootRef.current?.contains(event.target)
      ) {
        setOpen(false);
      }
    }
    function closeFromEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    }
    document.addEventListener("pointerdown", closeFromOutside);
    document.addEventListener("keydown", closeFromEscape);
    document.addEventListener("focusin", closeFromFocus);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("pointerdown", closeFromOutside);
      document.removeEventListener("keydown", closeFromEscape);
      document.removeEventListener("focusin", closeFromFocus);
    };
  }, [open]);

  function openFromKeyboard(direction: "first" | "last") {
    initialMenuFocusRef.current = direction;
    setOpen(true);
  }

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>(
        '[role="menuitem"]:not([disabled])',
      ) ?? [],
    );
    if (items.length === 0) return;
    const currentIndex = items.indexOf(
      document.activeElement as HTMLButtonElement,
    );
    let nextIndex: number | null = null;
    if (event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1 + items.length) % items.length;
    } else if (event.key === "ArrowUp") {
      nextIndex =
        (currentIndex - 1 + items.length) % items.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = items.length - 1;
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      buttonRef.current?.focus();
      return;
    }
    if (nextIndex === null) return;
    event.preventDefault();
    items[nextIndex]?.focus();
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-label={`${title} 관리 메뉴`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          initialMenuFocusRef.current = "first";
          setOpen((current) => !current);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            openFromKeyboard("first");
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            openFromKeyboard("last");
          }
        }}
        className="inline-flex min-h-10 items-center gap-1 rounded-xl border border-line bg-surface px-3 text-xs font-bold text-ink2 transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        관리
        <ChevronDown aria-hidden="true" size={14} />
      </button>
      {open && (
        <div
          ref={menuRef}
          role="menu"
          onKeyDown={handleMenuKeyDown}
          className="absolute right-0 top-full z-20 mt-1 min-w-48 overflow-hidden rounded-xl border border-line bg-surface p-1 shadow-xl"
        >
          {actions.map((action) => (
            <button
              key={action.label}
              type="button"
              role="menuitem"
              disabled={action.disabled}
              onClick={() => {
                setOpen(false);
                action.onSelect(buttonRef.current);
              }}
              className={`block min-h-10 w-full rounded-lg px-3 text-left text-xs font-bold transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50 ${
                action.danger ? "text-danger" : "text-ink2"
              }`}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function payloadFromView(
  template: TalkTemplateViewItem,
): PersonalTalkTemplatePayload {
  return {
    source_key: template.sourceKey,
    title: template.title,
    body: template.body,
    category: template.categoryKey,
    channel: template.channel,
    sort_order: template.sortOrder,
    is_active: template.isActive,
  };
}

function duplicateTitle(title: string): string {
  return `${title.slice(0, 96)} 복사본`;
}

function profileValue(value: string | null | undefined): string {
  return value?.trim() ?? "";
}

export default function ScriptsPage() {
  const ready = useAuthGuard();
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState(false);
  const [personalTemplates, setPersonalTemplates] = useState<
    PersonalTalkTemplate[]
  >([]);
  const [hiddenSourceKeys, setHiddenSourceKeys] = useState<string[]>([]);
  const [personalLoading, setPersonalLoading] = useState(true);
  const [personalError, setPersonalError] = useState(false);
  const [customer, setCustomer] = useState("");
  const [optOut, setOptOut] = useState("");
  const [filter, setFilter] = useState<TalkTemplateFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [editor, setEditor] = useState<EditorSession | null>(null);
  const [editorSaving, setEditorSaving] = useState(false);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [shareTemplate, setShareTemplate] =
    useState<TalkTemplateViewItem | null>(null);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const profileRequestRef = useRef(0);
  const personalRequestRef = useRef(0);
  const personalMutationGenerationRef = useRef(0);
  const editorOpenerRef = useRef<HTMLElement | null>(null);

  const loadProfile = useCallback(async () => {
    const requestId = ++profileRequestRef.current;
    setProfileLoading(true);
    setProfileError(false);
    try {
      const response = await getProfile();
      if (profileRequestRef.current !== requestId) return;
      setProfile(response);
    } catch {
      if (profileRequestRef.current !== requestId) return;
      setProfileError(true);
    } finally {
      if (profileRequestRef.current === requestId) setProfileLoading(false);
    }
  }, []);

  const loadPersonal = useCallback(async () => {
    const requestId = ++personalRequestRef.current;
    const mutationGeneration = personalMutationGenerationRef.current;
    setPersonalLoading(true);
    setPersonalError(false);
    try {
      const response = await listPersonalTalkTemplates();
      if (
        personalRequestRef.current !== requestId ||
        personalMutationGenerationRef.current !== mutationGeneration
      ) {
        return false;
      }
      setPersonalTemplates(response.results);
      setHiddenSourceKeys(response.hidden_source_keys);
      return true;
    } catch {
      if (personalRequestRef.current !== requestId) return false;
      setPersonalError(true);
      return false;
    } finally {
      if (personalRequestRef.current === requestId) {
        setPersonalLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!ready) return;
    void loadProfile();
    void loadPersonal();
    return () => {
      profileRequestRef.current += 1;
      personalRequestRef.current += 1;
    };
  }, [loadPersonal, loadProfile, ready]);

  useEffect(() => {
    const queryCustomer = new URLSearchParams(window.location.search).get(
      "customer",
    );
    if (queryCustomer) setCustomer(queryCustomer);
  }, []);

  const view = useMemo(
    () =>
      buildTalkTemplateView({
        categories: COPY_CATEGORIES,
        personalTemplates,
        hiddenSourceKeys,
      }),
    [hiddenSourceKeys, personalTemplates],
  );
  const visibleDefaultCount = view.visible.filter(
    (template) => template.kind === "default",
  ).length;
  const filtered = useMemo(() => {
    const byKind = filterTalkTemplates(view.visible, filter);
    if (categoryFilter === "all") return byKind;
    return byKind.filter(
      (template) => template.categoryKey === categoryFilter,
    );
  }, [categoryFilter, filter, view.visible]);

  const variables = useMemo(
    () => ({
      customer,
      planner: profileValue(profile?.name),
      affiliation: profileValue(profile?.affiliation),
      title: profileValue(profile?.title),
      phone: profileValue(profile?.phone),
      optOut,
    }),
    [customer, optOut, profile],
  );
  const shareText = shareTemplate
    ? substituteTalkTemplate(shareTemplate.body, variables)
    : "";
  const shareNeedsPhone =
    Boolean(shareTemplate?.isAdvertising) && !variables.phone;
  const shareNeedsOptOut =
    Boolean(shareTemplate?.isAdvertising) && !variables.optOut.trim();
  const shareAdvertisingVariableGuidance = shareTemplate
    ? getAdvertisingVariableGuidance(
        shareTemplate.sourceKey,
        shareTemplate.body,
      )
    : null;
  let shareDisabledReason: string | null = null;
  if (shareAdvertisingVariableGuidance) {
    shareDisabledReason = shareAdvertisingVariableGuidance;
  } else if (shareNeedsPhone && shareNeedsOptOut) {
    shareDisabledReason =
      "계정 설정에서 내 전화번호를 저장하고, 이 화면에 수신거부 안내를 입력해 주세요.";
  } else if (shareNeedsPhone) {
    shareDisabledReason = "계정 설정에서 내 전화번호를 저장해 주세요.";
  } else if (shareNeedsOptOut) {
    shareDisabledReason = "이 화면에 수신거부 안내를 입력해 주세요.";
  }

  if (!ready) return null;

  function openCreate(opener: HTMLElement | null = null) {
    editorOpenerRef.current = opener;
    setEditorError(null);
    setEditor({
      mode: "create",
      personalId: null,
    });
  }

  function openEdit(
    template: TalkTemplateViewItem,
    opener: HTMLElement | null,
  ) {
    editorOpenerRef.current = opener;
    setEditorError(null);
    setEditor({
      mode: "edit",
      personalId: template.personalId,
      initialValue: payloadFromView(template),
    });
  }

  function openDuplicate(
    template: TalkTemplateViewItem,
    opener: HTMLElement | null,
  ) {
    editorOpenerRef.current = opener;
    setEditorError(null);
    setEditor({
      mode: "duplicate",
      personalId: null,
      initialValue: {
        ...payloadFromView(template),
        title: duplicateTitle(template.title),
      },
    });
  }

  function openDefaultCopy(
    template: TalkTemplateViewItem,
    opener: HTMLElement | null,
  ) {
    editorOpenerRef.current = opener;
    setEditorError(null);
    setEditor({
      mode: "copy-default",
      personalId: null,
      initialValue: createPersonalPayloadFromDefault(template),
    });
  }

  async function saveEditor(payload: PersonalTalkTemplatePayload) {
    if (!editor) return;
    setEditorSaving(true);
    setEditorError(null);
    setActionError(null);
    setStatusMessage("");
    try {
      if (editor.mode === "edit" && editor.personalId !== null) {
        const updated = await updatePersonalTalkTemplate(
          editor.personalId,
          payload,
        );
        personalMutationGenerationRef.current += 1;
        setPersonalTemplates((current) =>
          current.map((template) =>
            template.id === updated.id ? updated : template,
          ),
        );
        setStatusMessage("나만의 화법을 수정했어요.");
      } else {
        const created = await createPersonalTalkTemplate(payload);
        personalMutationGenerationRef.current += 1;
        setPersonalTemplates((current) => [
          ...current.filter((template) => template.id !== created.id),
          created,
        ]);
        setStatusMessage(
          editor.mode === "duplicate"
            ? "나만의 화법을 복제했어요."
            : "나만의 화법을 저장했어요.",
        );
      }
      setEditor(null);
    } catch (error) {
      if (
        editor.mode === "edit" &&
        error instanceof ApiError &&
        error.status === 404
      ) {
        const refreshed = await loadPersonal();
        if (refreshed) {
          setEditor(null);
          setStatusMessage("최신 나만의 화법 목록을 불러왔어요.");
        } else {
          setEditorError(
            "최신 목록 연결이 중단됐어요. 입력한 내용은 그대로 두었으니 다시 불러온 뒤 저장해 주세요.",
          );
        }
      } else {
        setEditorError(
          "저장 연결이 중단됐어요. 입력한 내용은 그대로 두었으니 다시 시도해 주세요.",
        );
      }
    } finally {
      setEditorSaving(false);
    }
  }

  async function setDefaultHidden(
    template: TalkTemplateViewItem,
    isHidden: boolean,
  ) {
    if (!template.sourceKey) return;
    const pendingKey = `${isHidden ? "hide" : "restore"}:${template.sourceKey}`;
    setActionPending(pendingKey);
    setActionError(null);
    setStatusMessage("");
    try {
      await putTalkTemplatePreference({
        source_key: template.sourceKey,
        is_hidden: isHidden,
      });
      personalMutationGenerationRef.current += 1;
      setHiddenSourceKeys((current) =>
        isHidden
          ? [...new Set([...current, template.sourceKey!])]
          : current.filter((key) => key !== template.sourceKey),
      );
      setStatusMessage(
        isHidden
          ? "기본 화법을 내 목록에서 숨겼어요."
          : "기본 화법을 목록에 되돌렸어요.",
      );
    } catch {
      setActionError(
        isHidden
          ? "숨김 요청이 중단됐어요. 기본 화법은 목록에 그대로 있어요."
          : "복구 요청이 중단됐어요. 숨긴 기본 화법에서 다시 시도해 주세요.",
      );
    } finally {
      setActionPending(null);
    }
  }

  async function removePersonal(template: TalkTemplateViewItem) {
    if (template.personalId === null) return;
    if (
      !window.confirm(
        `"${template.title}" 화법을 삭제할까요? 삭제한 내 화법은 목록에서 사라집니다.`,
      )
    ) {
      return;
    }
    setActionPending(`delete:${template.personalId}`);
    setActionError(null);
    setStatusMessage("");
    try {
      await deletePersonalTalkTemplate(template.personalId);
      personalMutationGenerationRef.current += 1;
      setPersonalTemplates((current) =>
        current.filter((item) => item.id !== template.personalId),
      );
      setStatusMessage("나만의 화법을 삭제했어요.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        const refreshed = await loadPersonal();
        if (refreshed) {
          setStatusMessage("최신 나만의 화법 목록을 불러왔어요.");
        } else {
          setActionError(
            "최신 목록 연결이 중단됐어요. 내 화법은 목록에 그대로 있어요. 다시 불러와 확인해 주세요.",
          );
        }
      } else {
        setActionError(
          "삭제 요청이 중단됐어요. 내 문구는 그대로 남아 있어요. 다시 시도해 주세요.",
        );
      }
    } finally {
      setActionPending(null);
    }
  }

  return (
    <div className="min-h-dvh bg-canvas">
      <AppNav active="scripts" />
      <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs font-bold text-brand">
              <Sparkles aria-hidden="true" size={15} />
              고객과 다음 행동 정하기
            </div>
            <h1 className="mt-2 text-2xl font-extrabold tracking-tight text-ink">
              화법 · 문구
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-ink3">
              상황에 맞는 문구를 고르고, 고객과 이어갈 작은 행동을 바로
              정해 보세요. 최종 문구는 공유창에서 한 번 더 확인할 수 있어요.
            </p>
          </div>
          <button
            type="button"
            onClick={(event) => openCreate(event.currentTarget)}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-brand px-5 text-sm font-bold text-white transition hover:bg-brand/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            <Plus aria-hidden="true" size={17} />
            나만의 화법 추가
          </button>
        </header>

        <section
          aria-labelledby="share-info-title"
          className="mt-6 rounded-2xl border border-line bg-surface p-4 shadow-card sm:p-5"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 id="share-info-title" className="text-sm font-extrabold text-ink">
                공유에 사용할 정보
              </h2>
              <p className="mt-1 text-xs leading-5 text-ink3">
                내 정보는 계정 설정 값을 그대로 사용하고, 고객 이름과
                수신거부 안내는 이 화면에서만 문구에 넣어요.
              </p>
            </div>
            <Link
              href="/settings/account"
              className="inline-flex min-h-10 items-center gap-1.5 rounded-xl border border-line px-3 text-xs font-bold text-ink2 transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            >
              <Settings aria-hidden="true" size={14} />
              계정 설정에서 바꾸기
            </Link>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              ["내 이름", profileValue(profile?.name)],
              ["내 소속", profileValue(profile?.affiliation)],
              ["내 직책", profileValue(profile?.title)],
              ["내 전화번호", profileValue(profile?.phone)],
            ].map(([label, value]) => (
              <label key={label} className="block">
                <span className="text-xs font-bold text-ink3">{label}</span>
                <input
                  readOnly
                  aria-label={label}
                  value={value}
                  placeholder={profileLoading ? "불러오는 중" : "-"}
                  className="mt-1.5 w-full rounded-xl border border-line bg-surface2 px-3 py-2.5 text-sm font-semibold text-ink outline-none"
                />
              </label>
            ))}
          </div>

          {profileError && (
            <div
              role="alert"
              className="mt-3 flex flex-col gap-2 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn-ink sm:flex-row sm:items-center sm:justify-between"
            >
              <span>
                계정 정보 연결이 잠시 끊겼어요. 기본 문구는 그대로 살펴볼
                수 있어요.
              </span>
              <button
                type="button"
                onClick={() => void loadProfile()}
                className="min-h-10 rounded-lg border border-warn/30 bg-surface px-3 text-xs font-bold"
              >
                계정 정보 다시 불러오기
              </button>
            </div>
          )}

          <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
            <label className="block">
              <span className="text-xs font-bold text-ink3">
                고객 이름 (이 화면에서만)
              </span>
              <input
                value={customer}
                onChange={(event) => setCustomer(event.target.value)}
                placeholder="예: 김인파"
                className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-brand"
              />
            </label>
            <label className="block">
              <span className="text-xs font-bold text-ink3">
                수신거부 안내 (광고 문구에만)
              </span>
              <input
                aria-label="수신거부 안내 (광고 문구에만)"
                value={optOut}
                onChange={(event) => setOptOut(event.target.value)}
                placeholder="예: 이 번호로 거부 의사를 알려 주세요"
                className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-brand"
              />
              <span className="mt-1 block text-[11px] leading-4 text-ink3">
                실제로 안내할 방법을 직접 입력해 주세요. 이 값은 저장하지
                않아요.
              </span>
            </label>
          </div>
        </section>

        {personalError && (
          <div
            role="alert"
            className="mt-4 flex flex-col gap-3 rounded-2xl border border-warn/30 bg-warn-soft px-4 py-4 text-sm text-warn-ink sm:flex-row sm:items-center sm:justify-between"
          >
            <div>
              <p className="font-bold">나만의 화법 연결이 잠시 끊겼어요.</p>
              <p className="mt-1 text-xs leading-5">
                기본 화법은 그대로 공유할 수 있어요.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void loadPersonal()}
              className="min-h-10 rounded-xl border border-warn/30 bg-surface px-4 text-xs font-bold"
            >
              나만의 화법 다시 불러오기
            </button>
          </div>
        )}

        {actionError && (
          <div
            role="alert"
            className="mt-4 flex items-start gap-2 rounded-xl border border-danger/20 bg-danger-soft px-4 py-3 text-sm font-semibold text-danger"
          >
            <AlertCircle aria-hidden="true" className="mt-0.5 shrink-0" size={17} />
            {actionError}
          </div>
        )}
        <p role="status" className="sr-only">
          {statusMessage}
        </p>

        <section aria-labelledby="template-list-title" className="mt-6">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h2 id="template-list-title" className="text-lg font-extrabold text-ink">
                사용할 화법 고르기
              </h2>
              <p className="mt-1 text-xs leading-5 text-ink3">
                기본 화법 {visibleDefaultCount}개와 나만의 화법{" "}
                {personalTemplates.length}개를 함께 볼 수 있어요.
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <div
                role="group"
                aria-label="화법 종류"
                className="inline-flex rounded-xl border border-line bg-surface p-1"
              >
                {[
                  ["all", "전체"],
                  ["personal", "나만의 화법"],
                  ["default", "기본 화법"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={filter === value}
                    onClick={() => setFilter(value as TalkTemplateFilter)}
                    className={`min-h-10 rounded-lg px-3 text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                      filter === value
                        ? "bg-brand-soft text-brand"
                        : "text-ink3 hover:bg-surface2"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <label>
                <span className="sr-only">상황 분류</span>
                <select
                  aria-label="상황 분류"
                  value={categoryFilter}
                  onChange={(event) => setCategoryFilter(event.target.value)}
                  className="min-h-12 w-full rounded-xl border border-line bg-surface px-3 text-xs font-bold text-ink2 outline-none focus-visible:ring-2 focus-visible:ring-brand sm:w-44"
                >
                  <option value="all">모든 상황</option>
                  {COPY_CATEGORIES.map((category) => (
                    <option key={category.key} value={category.key}>
                      {category.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {personalLoading && (
            <div className="mt-3 flex items-center gap-2 text-xs font-semibold text-ink3">
              <LoaderCircle aria-hidden="true" className="animate-spin" size={15} />
              나만의 화법을 함께 불러오고 있어요.
            </div>
          )}

          {filtered.length === 0 ? (
            <div className="mt-4 rounded-2xl border border-dashed border-line bg-surface px-5 py-10 text-center">
              <MessageSquareText
                aria-hidden="true"
                className="mx-auto text-ink3"
                size={28}
              />
              <p className="mt-3 text-sm font-bold text-ink">
                {filter === "personal"
                  ? "첫 나만의 화법을 저장해 보세요."
                  : "다른 조건에서 화법을 골라보세요."}
              </p>
              <p className="mt-1 text-xs leading-5 text-ink3">
                다른 분류를 선택하거나 나만의 화법을 추가해 보세요.
              </p>
              <button
                type="button"
                onClick={(event) => openCreate(event.currentTarget)}
                className="mt-4 min-h-10 rounded-xl bg-brand px-4 text-xs font-bold text-white"
              >
                나만의 화법 추가
              </button>
            </div>
          ) : (
            <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {filtered.map((template) => {
                const rendered = substituteTalkTemplate(
                  template.body,
                  variables,
                );
                const pending =
                  template.kind === "default"
                    ? actionPending === `hide:${template.sourceKey}`
                    : actionPending === `delete:${template.personalId}`;
                const actions: MenuAction[] =
                  template.kind === "default"
                    ? [
                        {
                          label: "내 템플릿으로 저장",
                          onSelect: (opener) =>
                            openDefaultCopy(template, opener),
                        },
                        {
                          label: "내 목록에서 숨기기",
                          disabled: pending,
                          onSelect: () =>
                            void setDefaultHidden(template, true),
                        },
                      ]
                    : [
                        {
                          label: "수정",
                          onSelect: (opener) =>
                            openEdit(template, opener),
                        },
                        {
                          label: "복제",
                          onSelect: (opener) =>
                            openDuplicate(template, opener),
                        },
                        {
                          label: "삭제",
                          danger: true,
                          disabled: pending,
                          onSelect: () => void removePersonal(template),
                        },
                      ];
                return (
                  <article
                    key={template.viewKey}
                    className={`flex min-h-80 flex-col rounded-2xl border bg-surface p-5 shadow-card ${
                      template.isActive
                        ? "border-line"
                        : "border-line bg-surface2 opacity-75"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="rounded-full bg-brand-soft px-2 py-1 text-[10px] font-bold text-brand">
                            {template.categoryLabel}
                          </span>
                          <span className="rounded-full bg-surface2 px-2 py-1 text-[10px] font-bold text-ink3">
                            {template.kind === "default"
                              ? "기본 화법"
                              : "나만의 화법"}
                          </span>
                          {!template.isActive && (
                            <span className="rounded-full bg-warn-soft px-2 py-1 text-[10px] font-bold text-warn-ink">
                              사용 안 함
                            </span>
                          )}
                        </div>
                        <h3 className="mt-3 text-base font-extrabold leading-6 text-ink">
                          {template.title}
                        </h3>
                      </div>
                      {template.channel === "call" ? (
                        <Phone
                          aria-label="통화 화법"
                          className="shrink-0 text-ink3"
                          size={18}
                        />
                      ) : (
                        <MessageSquareText
                          aria-label="메시지 화법"
                          className="shrink-0 text-ink3"
                          size={18}
                        />
                      )}
                    </div>

                    <p className="mt-3 line-clamp-6 flex-1 whitespace-pre-wrap text-sm leading-6 text-ink2">
                      {rendered}
                    </p>

                    {template.requiresResultCheck && (
                      <p className="mt-3 rounded-xl bg-brand-soft px-3 py-2 text-[11px] font-semibold leading-5 text-brand">
                        실제 증권과 화면의 내용이 같은지 확인한 뒤 공유해 주세요.
                      </p>
                    )}
                    {template.isAdvertising && (
                      <p className="mt-3 rounded-xl bg-warn-soft px-3 py-2 text-[11px] font-semibold leading-5 text-warn-ink">
                        내 전화번호와 실제 수신거부 안내가 모두 있어야 공유할
                        수 있어요.
                      </p>
                    )}

                    <div className="mt-4 flex items-center justify-between gap-2 border-t border-line pt-4">
                      <button
                        type="button"
                        disabled={!template.isActive}
                        onClick={() => setShareTemplate(template)}
                        className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-brand px-4 text-sm font-bold text-white transition hover:bg-brand/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <MessageSquareText aria-hidden="true" size={16} />
                        공유
                      </button>
                      <TemplateMenu title={template.title} actions={actions} />
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        {view.hiddenDefaults.length > 0 && (
          <section
            role="region"
            aria-label="숨긴 기본 화법"
            className="mt-8 rounded-2xl border border-line bg-surface p-5"
          >
            <div className="flex items-start gap-3">
              <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface2 text-ink3">
                <EyeOff aria-hidden="true" size={17} />
              </span>
              <div>
                <h2 className="text-sm font-extrabold text-ink">
                  숨긴 기본 화법
                </h2>
                <p className="mt-1 text-xs leading-5 text-ink3">
                  숨긴 기본 화법은 언제든 원래 목록으로 되돌릴 수 있어요.
                </p>
              </div>
            </div>
            <ul className="mt-4 divide-y divide-line">
              {view.hiddenDefaults.map((template) => (
                <li
                  key={template.viewKey}
                  className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <p className="text-sm font-bold text-ink">{template.title}</p>
                    <p className="mt-0.5 text-xs text-ink3">
                      {template.categoryLabel}
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={
                      actionPending === `restore:${template.sourceKey}`
                    }
                    onClick={() => void setDefaultHidden(template, false)}
                    className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-xl border border-line px-3 text-xs font-bold text-ink2 transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
                  >
                    <RotateCcw aria-hidden="true" size={14} />
                    기본값으로 되돌리기
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>

      <TalkTemplateEditor
        open={Boolean(editor)}
        mode={editor?.mode ?? "create"}
        initialValue={editor?.initialValue}
        saving={editorSaving}
        error={editorError}
        returnFocusTo={editorOpenerRef.current}
        onSave={(payload) => void saveEditor(payload)}
        onClose={() => {
          if (!editorSaving) setEditor(null);
        }}
      />
      <TalkTemplateShare
        open={Boolean(shareTemplate)}
        title={shareTemplate?.title ?? ""}
        text={shareText}
        disabledReason={shareDisabledReason}
        accountSettingsNeeded={shareNeedsPhone}
        onClose={() => setShareTemplate(null)}
      />
    </div>
  );
}
