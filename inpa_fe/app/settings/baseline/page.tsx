"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import {
  ChevronDown,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import { AppNav } from "@/components/app-nav";
import { BaselineDetailDrawer } from "@/components/baseline-detail-drawer";
import {
  ApiError,
  deleteBaseline,
  getBaselineCatalog,
  linkLegacyBaseline,
  savePlannerBaselineBatch,
  type BaselineUnit,
  type LegacyPlannerBaseline,
} from "@/lib/api";
import {
  buildBaselineChanges,
  baselineScopeKey,
  catalogToDraft,
  countChangedScopes,
  filterBaselineCatalog,
  mapBaselineBatchFieldErrors,
  normalizeSavedBaselineDraft,
  validateBaselineChanges,
  type BaselineDraftCatalog,
  type BaselineDraftDetail,
  type BaselineDraftScope,
  type BaselineFieldErrors,
} from "@/lib/baseline-editor";
import { useAuthGuard } from "@/lib/useAuthGuard";

const REVISION_CONFLICT_COPY =
  "다른 화면에서 기준이 변경됐어요. 최신 내용을 확인한 뒤 다시 저장해 주세요.";
const NAVIGATION_CONFIRM_COPY =
  "저장하기 전에 이동하면 입력한 변경 내용이 사라져요. 이동할까요?";

type PageMessage =
  | { kind: "success"; text: string }
  | { kind: "error"; text: string }
  | { kind: "conflict"; text: string };

function unitLabel(unit: BaselineUnit): string {
  if (unit === 1) return "만원";
  if (unit === 2) return "원";
  return "구좌";
}

function productGroupLabel(productGroup: number): string {
  return (
    {
      0: "전체 상품",
      1: "생명",
      2: "손해",
      3: "실손",
      4: "연금저축",
    }[productGroup] ?? "상품 범위 확인"
  );
}

function ageBandLabel(ageBand: string): string {
  return (
    {
      all: "전연령",
      "20s": "20대",
      "30s": "30대",
      "40s": "40대",
      "50s": "50대",
      "60s+": "60대 이상",
    }[ageBand] ?? "연령 확인"
  );
}

function genderLabel(gender: number | null): string {
  if (gender === 1) return "남성";
  if (gender === 2) return "여성";
  return "성별 공통";
}

function legacyScopeLabel(baseline: LegacyPlannerBaseline): string {
  return [
    productGroupLabel(baseline.product_group),
    ageBandLabel(baseline.age_band),
    genderLabel(baseline.gender),
  ].join(" · ");
}

function legacyStatusLabel(baseline: LegacyPlannerBaseline): string {
  if (baseline.is_applied) return "분석에 적용 중";
  if (baseline.requires_adoption) return "연결 후 금액 확인 필요";
  if (baseline.is_active === false) return "연결 후 다시 사용 필요";
  return "연결 필요";
}

function amountLabel(value: string | null, unit: BaselineUnit): string {
  if (value === null) return "-";
  const normalized = value.replace(/\.00$/, "");
  return `${normalized}${unitLabel(unit)}`;
}

function scopeIdentity(scope: BaselineDraftScope): string {
  return `${scope.product_group}:${scope.age_band}:${scope.gender ?? "common"}`;
}

function hasAmount(scope: BaselineDraftScope): boolean {
  return (
    (scope.recommend_min !== null && scope.recommend_min.trim() !== "") ||
    (scope.recommend_max !== null && scope.recommend_max.trim() !== "")
  );
}

function findDetail(
  catalog: BaselineDraftCatalog,
  detailId: number,
): BaselineDraftDetail | null {
  for (const category of catalog.categories) {
    for (const subcategory of category.subcategories) {
      const detail = subcategory.details.find((item) => item.id === detailId);
      if (detail) return detail;
    }
  }
  return null;
}

function replaceDetailScopes(
  catalog: BaselineDraftCatalog,
  detailId: number,
  scopes: BaselineDraftScope[],
): BaselineDraftCatalog {
  return {
    ...catalog,
    categories: catalog.categories.map((category) => ({
      ...category,
      subcategories: category.subcategories.map((subcategory) => ({
        ...subcategory,
        details: subcategory.details.map((detail) =>
          detail.id === detailId ? { ...detail, baselines: scopes } : detail,
        ),
      })),
    })),
  };
}

function LoadingSkeleton() {
  return (
    <div
      role="status"
      aria-label="담보 기준 불러오는 중"
      className="mt-5 space-y-4"
    >
      <span className="sr-only">담보 기준을 불러오고 있어요.</span>
      {[0, 1, 2].map((category) => (
        <div
          key={category}
          className="overflow-hidden rounded-2xl border border-line bg-surface"
        >
          <div className="flex items-center gap-3 border-b border-line px-5 py-4">
            <div className="h-5 w-24 animate-pulse rounded-md bg-brand-soft" />
            <div className="ml-auto h-4 w-12 animate-pulse rounded bg-surface2" />
          </div>
          <div className="space-y-3 p-4">
            {[0, 1].map((row) => (
              <div
                key={row}
                className="grid grid-cols-[1fr_160px] gap-5 rounded-xl bg-canvas px-4 py-4"
              >
                <div className="h-4 animate-pulse rounded bg-line" />
                <div className="h-10 animate-pulse rounded-xl bg-line" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function CoverageTable({
  details,
  disabled,
  errors,
  onMinimumChange,
  onOpenDetail,
}: {
  details: BaselineDraftDetail[];
  disabled: boolean;
  errors: BaselineFieldErrors;
  onMinimumChange: (detail: BaselineDraftDetail, value: string) => void;
  onOpenDetail: (detailId: number) => void;
}) {
  return (
    <table className="block w-full border-separate border-spacing-0 lg:table">
      <thead className="hidden bg-canvas lg:table-header-group">
        <tr>
          <th
            scope="col"
            className="w-full px-5 py-3 text-left text-xs font-semibold text-ink3"
          >
            담보명
          </th>
          <th
            scope="col"
            className="min-w-56 px-5 py-3 text-right text-xs font-semibold text-ink3"
          >
            기준금액
          </th>
          <th
            scope="col"
            className="w-32 px-5 py-3 text-center text-xs font-semibold text-ink3"
          >
            조건별 설정
          </th>
        </tr>
      </thead>
      <tbody className="block space-y-3 p-3 lg:table-row-group lg:space-y-0 lg:p-0">
        {details.map((detail) => {
          const base = detail.baselines[0];
          const minimumError =
            errors[baselineScopeKey(base)]?.recommend_min;
          const minimumErrorId = `baseline-main-${detail.id}-minimum-error`;
          const exceptionCount = detail.baselines.filter(
            (scope) =>
              !(
                scope.product_group === 0 &&
                scope.age_band === "all" &&
                scope.gender === null
              ) && hasAmount(scope),
          ).length;
          return (
            <tr
              key={detail.id}
              className="block rounded-2xl border border-line bg-surface px-4 py-4 lg:table-row lg:rounded-none lg:border-0 lg:px-0 lg:py-0"
            >
              <td className="block lg:table-cell lg:border-t lg:border-line lg:px-5 lg:py-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-bold text-ink">
                      {detail.name}
                    </div>
                    <div className="mt-1 text-xs text-ink3 lg:hidden">
                      전체 상품 · 전연령 · 성별 공통
                    </div>
                  </div>
                  {exceptionCount > 0 && (
                    <span className="shrink-0 rounded-full bg-brand-soft px-2 py-1 text-[11px] font-bold text-brand">
                      상세 {exceptionCount}
                    </span>
                  )}
                </div>
              </td>
              <td className="mt-4 block lg:mt-0 lg:table-cell lg:border-t lg:border-line lg:px-5 lg:py-4">
                <label className="block">
                  <span className="mb-1.5 block text-xs font-semibold text-ink2 lg:sr-only">
                    기준금액
                  </span>
                  <span className="relative block">
                    <input
                      aria-label={`${detail.name} 기준금액`}
                      aria-invalid={minimumError ? "true" : undefined}
                      aria-describedby={
                        minimumError ? minimumErrorId : undefined
                      }
                      inputMode="decimal"
                      value={base.recommend_min ?? ""}
                      onChange={(event) =>
                        onMinimumChange(detail, event.target.value)
                      }
                      disabled={disabled}
                      placeholder="금액 입력"
                      className="min-h-11 w-full rounded-xl border border-line bg-surface py-2.5 pl-3 pr-12 text-right text-sm font-bold text-ink placeholder:font-normal placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:bg-surface2"
                    />
                    <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink3">
                      {unitLabel(base.unit)}
                    </span>
                  </span>
                  {minimumError && (
                    <span
                      id={minimumErrorId}
                      className="mt-1.5 block text-xs font-semibold text-danger"
                    >
                      {minimumError}
                    </span>
                  )}
                </label>
              </td>
              <td className="mt-3 block lg:mt-0 lg:table-cell lg:border-t lg:border-line lg:px-5 lg:py-4 lg:text-center">
                <button
                  type="button"
                  onClick={() => onOpenDetail(detail.id)}
                  disabled={disabled}
                  aria-label={`${detail.name} 상세 설정`}
                  className="inline-flex min-h-11 w-full items-center justify-center gap-2 whitespace-nowrap rounded-xl border border-line bg-surface px-3 text-xs font-bold text-ink2 transition hover:border-brand/30 hover:bg-brand-soft hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50 lg:w-auto"
                >
                  <SlidersHorizontal aria-hidden="true" size={15} />
                  상세 설정
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default function BaselineSettingsPage() {
  const ready = useAuthGuard();
  const requestGeneration = useRef(0);
  const [server, setServer] = useState<BaselineDraftCatalog | null>(null);
  const [draft, setDraft] = useState<BaselineDraftCatalog | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<PageMessage | null>(null);
  const [query, setQuery] = useState("");
  const [configuredOnly, setConfiguredOnly] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [selectedDetailId, setSelectedDetailId] = useState<number | null>(null);
  const [fieldErrors, setFieldErrors] = useState<BaselineFieldErrors>({});
  const [legacySelections, setLegacySelections] = useState<
    Record<number, string>
  >({});
  const [legacyActionId, setLegacyActionId] = useState<number | null>(null);

  const loadCatalog = useCallback(async () => {
    const generation = ++requestGeneration.current;
    setLoading(true);
    setLoadError(false);
    setMessage(null);
    try {
      const response = await getBaselineCatalog();
      if (generation !== requestGeneration.current) return;
      const next = catalogToDraft(response);
      setServer(next);
      setDraft(structuredClone(next));
      setExpanded(new Set(next.categories.map((category) => category.id)));
      setSelectedDetailId(null);
      setFieldErrors({});
      setLegacySelections(
        Object.fromEntries(
          next.legacy_baselines.map((baseline) => [
            baseline.id,
            baseline.matching_analysis_detail_ids.length === 1
              ? String(baseline.matching_analysis_detail_ids[0])
              : "",
          ]),
        ),
      );
      return true;
    } catch {
      if (generation !== requestGeneration.current) return;
      setLoadError(true);
      return false;
    } finally {
      if (generation === requestGeneration.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!ready) return;
    void loadCatalog();
    return () => {
      requestGeneration.current += 1;
    };
  }, [ready, loadCatalog]);

  const changedCount = useMemo(
    () => (server && draft ? countChangedScopes(server, draft) : 0),
    [server, draft],
  );
  const dirty = changedCount > 0;

  const confirmDiscard = useCallback(
    (message: string) => !dirty || window.confirm(message),
    [dirty],
  );
  const confirmProgrammaticNavigation = useCallback(
    () => confirmDiscard(NAVIGATION_CONFIRM_COPY),
    [confirmDiscard],
  );

  useEffect(() => {
    if (!dirty) return;
    const guardedHref = window.location.href;
    const guardedHistoryState = window.history.state;
    let allowConfirmedUnload = false;
    let resetConfirmedUnload: ReturnType<typeof setTimeout> | null = null;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (allowConfirmedUnload) return;
      event.preventDefault();
      event.returnValue = "";
    };
    const guardInternalAnchor = (event: globalThis.MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }
      const target =
        event.target instanceof Element
          ? event.target.closest<HTMLAnchorElement>("a[href]")
          : null;
      if (!target || target.target === "_blank" || target.hasAttribute("download")) {
        return;
      }
      const destination = new URL(target.href, guardedHref);
      if (
        destination.origin !== window.location.origin ||
        destination.href === guardedHref
      ) {
        return;
      }
      const confirmed = window.confirm(
        NAVIGATION_CONFIRM_COPY,
      );
      if (!confirmed) {
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }
      allowConfirmedUnload = true;
      resetConfirmedUnload = setTimeout(() => {
        allowConfirmedUnload = false;
        resetConfirmedUnload = null;
      }, 0);
    };
    const guardHistoryNavigation = (event: PopStateEvent) => {
      if (
        window.confirm(
          NAVIGATION_CONFIRM_COPY,
        )
      ) {
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      window.history.pushState(guardedHistoryState, "", guardedHref);
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    document.addEventListener("click", guardInternalAnchor, true);
    window.addEventListener("popstate", guardHistoryNavigation, true);
    return () => {
      window.removeEventListener("beforeunload", warnBeforeUnload);
      document.removeEventListener("click", guardInternalAnchor, true);
      window.removeEventListener("popstate", guardHistoryNavigation, true);
      if (resetConfirmedUnload !== null) {
        clearTimeout(resetConfirmedUnload);
      }
    };
  }, [dirty]);

  const filtered = useMemo(
    () =>
      draft
        ? filterBaselineCatalog(draft, query, configuredOnly)
        : null,
    [draft, query, configuredOnly],
  );

  useEffect(() => {
    if (!query.trim() || !filtered) return;
    setExpanded((current) => {
      const next = new Set(current);
      filtered.categories.forEach((category) => next.add(category.id));
      return next;
    });
  }, [query, filtered]);

  const selectedDetail =
    draft && selectedDetailId !== null
      ? findDetail(draft, selectedDetailId)
      : null;
  const standardDetailOptions = useMemo(
    () =>
      draft
        ? draft.categories.flatMap((category) =>
            category.subcategories.flatMap((subcategory) =>
              subcategory.details.map((detail) => ({
                id: detail.id,
                label: `${category.name} · ${subcategory.name} · ${detail.name}`,
              })),
            ),
          )
        : [],
    [draft],
  );

  function clearScopeErrors(...scopes: BaselineDraftScope[]) {
    setFieldErrors((current) => {
      const keys = scopes.map(baselineScopeKey);
      if (!keys.some((key) => current[key])) return current;
      const next = { ...current };
      keys.forEach((key) => delete next[key]);
      return next;
    });
  }

  function setScope(
    detailId: number,
    original: BaselineDraftScope,
    next: BaselineDraftScope | null,
  ) {
    if (!draft) return;
    const detail = findDetail(draft, detailId);
    if (!detail) return;
    if (
      next &&
      scopeIdentity(next) !== scopeIdentity(original) &&
      detail.baselines.some(
        (scope) =>
          scope !== original &&
          scopeIdentity(scope) === scopeIdentity(next),
      )
    ) {
      setMessage({
        kind: "error",
        text: "같은 상품·연령·성별 기준이 이미 있어요. 다른 조건을 선택해 주세요.",
      });
      return;
    }
    const scopes = next
      ? detail.baselines.map((scope) => (scope === original ? next : scope))
      : detail.baselines.filter((scope) => scope !== original);
    setDraft(replaceDetailScopes(draft, detailId, scopes));
    clearScopeErrors(original, ...(next ? [next] : []));
    setMessage(null);
  }

  function addScope(detailId: number, scope: BaselineDraftScope) {
    if (!draft) return;
    const detail = findDetail(draft, detailId);
    if (!detail) return;
    if (
      detail.baselines.some(
        (current) => scopeIdentity(current) === scopeIdentity(scope),
      )
    ) {
      setMessage({
        kind: "error",
        text: "같은 상품·연령·성별 기준이 이미 있어요. 다른 조건을 선택해 주세요.",
      });
      return;
    }
    setDraft(
      replaceDetailScopes(draft, detailId, [...detail.baselines, scope]),
    );
    clearScopeErrors(scope);
    setMessage(null);
  }

  function changeMinimum(detail: BaselineDraftDetail, value: string) {
    const base = detail.baselines[0];
    setScope(detail.id, base, { ...base, recommend_min: value });
  }

  async function saveChanges() {
    if (!server || !draft || changedCount === 0 || saving) return;
    const changes = buildBaselineChanges(server, draft);
    const clientErrors = validateBaselineChanges(changes);
    if (Object.keys(clientErrors).length > 0) {
      setFieldErrors(clientErrors);
      setMessage({
        kind: "error",
        text: "입력한 금액을 확인해 주세요.",
      });
      return;
    }
    setSaving(true);
    setFieldErrors({});
    setMessage(null);
    try {
      const response = await savePlannerBaselineBatch({
        revision: server.revision,
        changes,
      });
      const saved = normalizeSavedBaselineDraft(
        draft,
        changes,
        response.revision,
      );
      setServer(saved);
      setDraft(structuredClone(saved));
      setFieldErrors({});
      setMessage({ kind: "success", text: "변경 내용을 저장했어요." });
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        error.code === "baseline_revision_conflict"
      ) {
        setMessage({ kind: "conflict", text: REVISION_CONFLICT_COPY });
      } else {
        if (error instanceof ApiError) {
          setFieldErrors(mapBaselineBatchFieldErrors(changes, error.data));
        }
        setMessage({
          kind: "error",
          text:
            error instanceof ApiError && error.message
              ? error.message
              : "저장에 실패했어요. 입력 내용을 확인하고 다시 시도해 주세요.",
        });
      }
    } finally {
      setSaving(false);
    }
  }

  function refreshCatalog() {
    if (!confirmDiscard(
      "새로 불러오면 지금 입력한 변경 내용이 사라져요. 계속할까요?",
    )) {
      return;
    }
    void loadCatalog();
  }

  async function linkLegacy(
    baseline: LegacyPlannerBaseline,
  ) {
    const selected = Number(legacySelections[baseline.id]);
    if (!Number.isInteger(selected) || selected <= 0 || dirty) return;
    setLegacyActionId(baseline.id);
    setMessage(null);
    try {
      await linkLegacyBaseline(baseline.id, selected);
      if (await loadCatalog()) {
        setMessage({
          kind: "success",
          text: "기존 값을 선택한 표준 담보에 연결했어요.",
        });
      }
    } catch (error) {
      setMessage({
        kind: "error",
        text:
          error instanceof ApiError && error.message
            ? error.message
            : "연결할 담보를 다시 확인하고 시도해 주세요.",
      });
    } finally {
      setLegacyActionId(null);
    }
  }

  async function removeLegacy(
    baseline: LegacyPlannerBaseline,
  ) {
    if (
      dirty ||
      !window.confirm(
        `'${baseline.coverage_key}' 기존 값을 삭제할까요?`,
      )
    ) {
      return;
    }
    setLegacyActionId(baseline.id);
    setMessage(null);
    try {
      await deleteBaseline(baseline.id);
      if (await loadCatalog()) {
        setMessage({ kind: "success", text: "선택한 기존 값을 삭제했어요." });
      }
    } catch (error) {
      setMessage({
        kind: "error",
        text:
          error instanceof ApiError && error.message
            ? error.message
            : "기존 값을 다시 확인하고 시도해 주세요.",
      });
    } finally {
      setLegacyActionId(null);
    }
  }

  if (!ready) return null;

  return (
    <div className="min-h-dvh bg-canvas">
      <AppNav
        active="settings"
        onBeforeNavigate={confirmProgrammaticNavigation}
      />
      <main
        className="mx-auto max-w-[1440px] px-4 pb-36 pt-5 sm:px-6 sm:pb-32 sm:pt-7"
        aria-busy={saving}
      >
        <Link
          href="/analysis"
          className="inline-flex min-h-10 items-center rounded-lg px-1 text-xs font-bold text-ink3 transition hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          ‹ 분석으로
        </Link>

        <header className="mt-2 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold text-brand">분석 설정</p>
            <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-ink sm:text-[28px]">
              보장 기준 설정
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-ink3">
              설계사님이 사용하는 기준금액을 전체 담보에 빠르게 입력하세요.
              입력한 값만 저장하고 분석에 반영해요.
            </p>
          </div>
          <button
            type="button"
            onClick={refreshCatalog}
            disabled={loading || saving}
            aria-label="새로 고침"
            className="inline-flex min-h-11 items-center justify-center gap-2 self-start rounded-xl border border-line bg-surface px-4 text-xs font-bold text-ink2 transition hover:border-brand/30 hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw
              aria-hidden="true"
              size={15}
              className={loading ? "animate-spin" : ""}
            />
            새로 고침
          </button>
        </header>

        <section className="mt-5 rounded-2xl border border-brand/15 bg-brand-soft/40 px-4 py-4 sm:px-5">
          <h2 className="text-sm font-bold text-ink">기준금액 입력 방법</h2>
          <p className="mt-1 text-xs leading-5 text-ink2 sm:text-sm sm:leading-6">
            기준금액은 적정으로 보는 시작 금액이에요. 넉넉 기준금액과
            상품·연령·성별에 따른 값은 각 담보의 상세 설정에서 입력할 수
            있어요. 비워 둔 담보는 금액에 따른 상태를 표시하지 않아요.
          </p>
        </section>

        {draft && draft.legacy_baselines.length > 0 && (
          <section
            aria-labelledby="legacy-baseline-title"
            className="mt-5 rounded-2xl border border-warn/30 bg-surface p-4 shadow-card sm:p-5"
          >
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2
                  id="legacy-baseline-title"
                  className="text-base font-extrabold text-ink"
                >
                  기존 직접 입력
                </h2>
                <p className="mt-1 text-sm leading-6 text-ink3">
                  이전에 입력한 기준을 확인하고 알맞은 표준 담보에 연결해
                  주세요. 연결할 값이 아니라면 선택해서 삭제할 수 있어요.
                </p>
              </div>
              <span className="self-start rounded-full bg-warn-soft px-3 py-1 text-xs font-bold text-warn-ink">
                확인 {draft.legacy_baselines.length}개
              </span>
            </div>

            {dirty && (
              <p
                role="status"
                className="mt-4 rounded-xl bg-brand-soft px-3 py-2 text-xs font-semibold text-brand"
              >
                변경 내용을 먼저 저장하면 기존 값을 이어서 정리할 수 있어요.
              </p>
            )}

            <div className="mt-4 space-y-3">
              {draft.legacy_baselines.map((baseline) => {
                const exactOptions = new Set(
                  baseline.matching_analysis_detail_ids,
                );
                const orderedOptions = [
                  ...standardDetailOptions.filter((option) =>
                    exactOptions.has(option.id),
                  ),
                  ...standardDetailOptions.filter(
                    (option) => !exactOptions.has(option.id),
                  ),
                ];
                const actionPending = legacyActionId === baseline.id;
                return (
                  <article
                    key={baseline.id}
                    className="rounded-2xl border border-line bg-canvas p-4"
                  >
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-extrabold text-ink">
                            {baseline.coverage_key}
                          </h3>
                          <span
                            className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
                              baseline.is_applied
                                ? "bg-success-tint text-success"
                                : "bg-surface2 text-ink2"
                            }`}
                          >
                            {legacyStatusLabel(baseline)}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-ink3">
                          {legacyScopeLabel(baseline)}
                        </p>
                        <p className="mt-2 text-sm font-bold text-ink2">
                          기준금액 {amountLabel(
                            baseline.recommend_min,
                            baseline.unit,
                          )}
                          {baseline.recommend_max !== null &&
                            ` · 넉넉 기준금액 ${amountLabel(
                              baseline.recommend_max,
                              baseline.unit,
                            )}`}
                        </p>
                        <p className="mt-2 text-xs leading-5 text-warn-ink">
                          {baseline.conflict_reason}
                        </p>
                      </div>
                    </div>

                    <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
                      <label className="block">
                        <span className="sr-only">
                          {baseline.coverage_key} 연결할 표준 담보
                        </span>
                        <select
                          aria-label={`${baseline.coverage_key} 연결할 표준 담보`}
                          value={legacySelections[baseline.id] ?? ""}
                          onChange={(event) =>
                            setLegacySelections((current) => ({
                              ...current,
                              [baseline.id]: event.target.value,
                            }))
                          }
                          disabled={dirty || actionPending}
                          className="min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:bg-surface2"
                        >
                          <option value="">표준 담보 선택</option>
                          {orderedOptions.map((option) => (
                            <option key={option.id} value={option.id}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        aria-label={`${baseline.coverage_key} 표준 담보에 연결`}
                        onClick={() => void linkLegacy(baseline)}
                        disabled={
                          dirty ||
                          actionPending ||
                          !(legacySelections[baseline.id] ?? "")
                        }
                        className="min-h-11 rounded-xl bg-ink px-4 text-xs font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:bg-line disabled:text-ink3"
                      >
                        {actionPending ? "처리 중..." : "표준 담보에 연결"}
                      </button>
                      <button
                        type="button"
                        aria-label={`${baseline.coverage_key} 기존 값 삭제`}
                        onClick={() => void removeLegacy(baseline)}
                        disabled={dirty || actionPending}
                        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-line bg-surface px-4 text-xs font-bold text-ink2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Trash2 aria-hidden="true" size={15} />
                        삭제
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        )}

        <div className="mt-5 rounded-2xl border border-line bg-surface p-3 shadow-card sm:p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <label className="relative block flex-1">
              <span className="sr-only">담보 검색</span>
              <Search
                aria-hidden="true"
                size={18}
                className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink3"
              />
              <input
                type="search"
                aria-label="담보 검색"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                disabled={loading || saving || !draft}
                placeholder="담보명이나 분류 이름 검색"
                className="min-h-12 w-full rounded-xl border border-line bg-surface pl-11 pr-4 text-sm text-ink placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:bg-surface2"
              />
            </label>
            <label className="inline-flex min-h-12 cursor-pointer items-center justify-between gap-3 rounded-xl border border-line px-4 text-sm font-bold text-ink2 focus-within:ring-2 focus-within:ring-brand sm:justify-start">
              입력한 담보만
              <span className="relative inline-flex h-6 w-11 shrink-0">
                <input
                  type="checkbox"
                  aria-label="입력한 담보만"
                  checked={configuredOnly}
                  onChange={(event) => setConfiguredOnly(event.target.checked)}
                  disabled={loading || saving || !draft}
                  className="peer sr-only"
                />
                <span className="absolute inset-0 rounded-full bg-line transition peer-checked:bg-brand peer-disabled:opacity-50" />
                <span className="absolute left-1 top-1 h-4 w-4 rounded-full bg-white shadow transition peer-checked:translate-x-5" />
              </span>
            </label>
          </div>
        </div>

        {message?.kind === "success" && (
          <div
            role="status"
            className="mt-4 rounded-2xl border border-success/20 bg-success-tint px-4 py-3 text-sm font-semibold text-success"
          >
            {message.text}
          </div>
        )}
        {message?.kind === "error" && (
          <div
            role="alert"
            className="mt-4 rounded-2xl border border-danger/20 bg-danger-tint px-4 py-3 text-sm font-semibold text-danger"
          >
            {message.text}
          </div>
        )}
        {message?.kind === "conflict" && (
          <div
            role="alert"
            className="mt-4 flex flex-col gap-3 rounded-2xl border border-warn/30 bg-warn-soft px-4 py-4 text-sm text-ink2 sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="font-semibold">{message.text}</span>
            <button
              type="button"
              onClick={() => void loadCatalog()}
              disabled={loading || saving}
              className="min-h-11 shrink-0 rounded-xl bg-ink px-4 text-xs font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
            >
              새로 불러오기
            </button>
          </div>
        )}

        {loading && !draft && <LoadingSkeleton />}

        {loadError && !draft && (
          <section
            role="alert"
            className="mt-5 rounded-2xl border border-danger/20 bg-surface px-5 py-10 text-center shadow-card"
          >
            <h2 className="text-base font-extrabold text-ink">
              담보 기준을 불러오지 못했어요.
            </h2>
            <p className="mt-2 text-sm text-ink3">
              연결을 확인한 뒤 다시 불러와 주세요.
            </p>
            <button
              type="button"
              onClick={refreshCatalog}
              className="mt-5 min-h-11 rounded-xl bg-brand px-5 text-sm font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
            >
              다시 불러오기
            </button>
          </section>
        )}

        {loadError && draft && (
          <div
            role="alert"
            className="mt-4 flex flex-col gap-3 rounded-2xl border border-warn/30 bg-warn-soft px-4 py-4 text-sm text-ink2 sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="font-semibold">
              최신 담보 기준을 불러오지 못했어요. 현재 입력 내용은 그대로
              두었어요.
            </span>
            <button
              type="button"
              onClick={refreshCatalog}
              disabled={loading || saving}
              className="min-h-11 shrink-0 rounded-xl border border-ink/15 bg-surface px-4 text-xs font-bold text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
            >
              다시 불러오기
            </button>
          </div>
        )}

        {filtered && filtered.categories.length === 0 && (
          <section className="mt-5 rounded-2xl border border-dashed border-line bg-surface px-5 py-12 text-center">
            {query.trim() ? (
              <>
                <h2 className="text-base font-extrabold text-ink">
                  검색 결과가 없어요.
                </h2>
                <p className="mt-2 text-sm text-ink3">
                  담보명이나 분류 이름을 다시 확인해 보세요.
                </p>
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  disabled={saving}
                  className="mt-5 min-h-11 rounded-xl border border-line px-5 text-sm font-bold text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
                >
                  검색어 지우기
                </button>
              </>
            ) : configuredOnly ? (
              <>
                <h2 className="text-base font-extrabold text-ink">
                  입력한 담보가 없어요.
                </h2>
                <p className="mt-2 text-sm text-ink3">
                  전체 담보를 보고 필요한 기준금액부터 입력해 보세요.
                </p>
                <button
                  type="button"
                  onClick={() => setConfiguredOnly(false)}
                  disabled={saving}
                  className="mt-5 min-h-11 rounded-xl bg-brand px-5 text-sm font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:opacity-50"
                >
                  전체 담보 보기
                </button>
              </>
            ) : (
              <>
                <h2 className="text-base font-extrabold text-ink">
                  담보 목록을 다시 불러와 주세요.
                </h2>
                <p className="mt-2 text-sm text-ink3">
                  새로 고침을 누르면 최신 담보 목록을 확인할 수 있어요.
                </p>
              </>
            )}
          </section>
        )}

        {filtered && filtered.categories.length > 0 && (
          <div className="mt-5 space-y-4">
            {filtered.categories.map((category) => {
              const open = expanded.has(category.id);
              const detailCount = category.subcategories.reduce(
                (sum, subcategory) => sum + subcategory.details.length,
                0,
              );
              return (
                <section
                  key={category.id}
                  className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card"
                >
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={`baseline-category-${category.id}`}
                    onClick={() =>
                      setExpanded((current) => {
                        const next = new Set(current);
                        if (next.has(category.id)) next.delete(category.id);
                        else next.add(category.id);
                        return next;
                      })
                    }
                    disabled={saving}
                    className="flex min-h-16 w-full items-center gap-3 px-4 text-left transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-60 sm:px-5"
                  >
                    <span className="text-base font-extrabold text-ink">
                      {category.name}
                    </span>
                    <span className="rounded-full bg-surface2 px-2.5 py-1 text-xs font-bold text-ink3">
                      {detailCount}개
                    </span>
                    <ChevronDown
                      aria-hidden="true"
                      size={19}
                      className={`ml-auto text-ink3 transition-transform ${
                        open ? "rotate-180" : ""
                      }`}
                    />
                  </button>
                  {open && (
                    <div
                      id={`baseline-category-${category.id}`}
                      className="border-t border-line"
                    >
                      {category.subcategories.map((subcategory) => (
                        <section
                          key={subcategory.id}
                          aria-labelledby={`baseline-subcategory-${subcategory.id}`}
                          className="border-b border-line last:border-b-0"
                        >
                          <h3
                            id={`baseline-subcategory-${subcategory.id}`}
                            className="bg-canvas px-4 py-3 text-xs font-extrabold text-ink2 sm:px-5"
                          >
                            {subcategory.name}
                          </h3>
                          <CoverageTable
                            details={subcategory.details}
                            disabled={saving}
                            errors={fieldErrors}
                            onMinimumChange={changeMinimum}
                            onOpenDetail={setSelectedDetailId}
                          />
                        </section>
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        )}
      </main>

      {server && draft && (
        <div className="fixed bottom-16 left-0 right-0 z-40 border-t border-line bg-surface/95 px-4 py-3 shadow-[0_-10px_30px_rgba(23,34,55,0.08)] backdrop-blur sm:bottom-0 sm:left-60 sm:px-6">
          <div className="mx-auto flex max-w-[1168px] items-center justify-between gap-4">
            <div>
              <div className="text-sm font-extrabold text-ink">
                변경 {changedCount}개
              </div>
              <p className="mt-0.5 hidden text-xs text-ink3 sm:block">
                바뀐 항목만 한 번에 저장해요.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void saveChanges()}
              disabled={saving || changedCount === 0}
              aria-label={saving ? "저장 중" : "변경 내용 저장"}
              className="min-h-12 min-w-40 rounded-xl bg-brand px-5 text-sm font-extrabold text-white transition hover:bg-brand/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-line disabled:text-ink3"
            >
              {saving ? "저장 중..." : "변경 내용 저장"}
            </button>
          </div>
        </div>
      )}

      {selectedDetail && (
        <BaselineDetailDrawer
          open
          detail={selectedDetail}
          disabled={saving}
          errors={fieldErrors}
          onClose={() => setSelectedDetailId(null)}
          onScopeChange={(original, next) =>
            setScope(selectedDetail.id, original, next)
          }
          onAddScope={(scope) => addScope(selectedDetail.id, scope)}
        />
      )}
    </div>
  );
}
