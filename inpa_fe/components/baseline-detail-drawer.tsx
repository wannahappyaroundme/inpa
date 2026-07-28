"use client";

import { useEffect, useRef } from "react";
import { Plus, Trash2, X } from "lucide-react";
import type {
  BaselineDraftDetail,
  BaselineDraftScope,
  BaselineFieldErrors,
} from "@/lib/baseline-editor";
import { adoptBaselineScope, baselineScopeKey } from "@/lib/baseline-editor";
import type {
  BaselineAgeBand,
  BaselineGender,
  BaselineProductGroup,
} from "@/lib/api";

interface BaselineDetailDrawerProps {
  open: boolean;
  detail: BaselineDraftDetail;
  disabled?: boolean;
  errors?: BaselineFieldErrors;
  onClose: () => void;
  onScopeChange: (
    original: BaselineDraftScope,
    next: BaselineDraftScope | null,
  ) => void;
  onAddScope: (scope: BaselineDraftScope) => void;
}

const PRODUCT_GROUPS: {
  value: BaselineProductGroup;
  label: string;
}[] = [
  { value: 0, label: "전체 상품" },
  { value: 1, label: "생명" },
  { value: 2, label: "손해" },
  { value: 3, label: "실손" },
  { value: 4, label: "연금저축" },
];

const AGE_BANDS: { value: BaselineAgeBand; label: string }[] = [
  { value: "all", label: "전연령" },
  { value: "20s", label: "20대" },
  { value: "30s", label: "30대" },
  { value: "40s", label: "40대" },
  { value: "50s", label: "50대" },
  { value: "60s+", label: "60대 이상" },
];

const GENDERS: { value: "common" | "1" | "2"; label: string }[] = [
  { value: "common", label: "성별 공통" },
  { value: "1", label: "남성" },
  { value: "2", label: "여성" },
];

function isDefaultScope(scope: BaselineDraftScope): boolean {
  return (
    scope.product_group === 0 &&
    scope.age_band === "all" &&
    scope.gender === null
  );
}

function scopeLabel(scope: BaselineDraftScope): string {
  const product =
    PRODUCT_GROUPS.find(({ value }) => value === scope.product_group)?.label ??
    "";
  const age =
    AGE_BANDS.find(({ value }) => value === scope.age_band)?.label ?? "";
  const gender =
    GENDERS.find(({ value }) =>
      value === (scope.gender === null ? "common" : String(scope.gender)),
    )?.label ?? "";
  return `${product} ${age} ${gender}`;
}

function unitLabel(unit: BaselineDraftScope["unit"]): string {
  if (unit === 1) return "만원";
  if (unit === 2) return "원";
  return "구좌";
}

function genderValue(gender: BaselineGender): "common" | "1" | "2" {
  return gender === null ? "common" : String(gender) as "1" | "2";
}

function scopeIdentity(scope: BaselineDraftScope): string {
  return `${scope.product_group}:${scope.age_band}:${scope.gender ?? "common"}`;
}

function ScopeEditor({
  scope,
  base,
  disabled,
  errors,
  onChange,
  onDelete,
}: {
  scope: BaselineDraftScope;
  base: boolean;
  disabled: boolean;
  errors?: BaselineFieldErrors[string];
  onChange: (next: BaselineDraftScope) => void;
  onDelete?: () => void;
}) {
  const prefix = `baseline-${scope.analysis_detail_id}-${scopeIdentity(scope)}`;
  const minimumError = errors?.recommend_min;
  const maximumError = errors?.recommend_max;
  const minimumErrorId = `${prefix}-minimum-error`;
  const maximumErrorId = `${prefix}-maximum-error`;
  return (
    <section
      className={`rounded-2xl border p-4 ${
        base ? "border-brand/20 bg-brand-soft/40" : "border-line bg-surface"
      }`}
      aria-label={base ? "전체 기본값" : scopeLabel(scope)}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-ink">
            {base ? "전체 기본값" : "상세 기준"}
          </h3>
          <p className="mt-1 text-xs leading-5 text-ink3">
            {base
              ? "모든 상품과 연령에 먼저 적용되는 값이에요."
              : "해당 조건에는 이 값을 우선 적용해요."}
          </p>
          {scope.baseline_source === "preset" && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <p className="text-xs leading-5 text-ink2">
                이 금액을 확인한 뒤 내 기준으로 사용하면 분석에 반영돼요.
              </p>
              <button
                type="button"
                onClick={() => onChange(adoptBaselineScope(scope))}
                disabled={disabled}
                className="min-h-10 rounded-xl border border-brand/30 bg-surface px-3 text-xs font-bold text-brand transition hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
              >
                내 기준으로 사용
              </button>
            </div>
          )}
        </div>
        {onDelete && (
          <button
            type="button"
            onClick={onDelete}
            disabled={disabled}
            aria-label={`${scopeLabel(scope)} 상세값 지우기`}
            className="inline-flex min-h-10 min-w-10 items-center justify-center rounded-xl text-ink3 transition hover:bg-danger-tint hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Trash2 aria-hidden="true" size={17} />
          </button>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="text-xs font-semibold text-ink2">
          상품 범위
          <select
            id={`${prefix}-product`}
            aria-label="상품 범위"
            value={scope.product_group}
            onChange={(event) =>
              onChange({
                ...scope,
                product_group: Number(event.target.value) as BaselineProductGroup,
              })
            }
            disabled={disabled || base}
            className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:bg-surface2 disabled:text-ink3"
          >
            {PRODUCT_GROUPS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-semibold text-ink2">
          연령
          <select
            id={`${prefix}-age`}
            aria-label="연령"
            value={scope.age_band}
            onChange={(event) =>
              onChange({
                ...scope,
                age_band: event.target.value as BaselineAgeBand,
              })
            }
            disabled={disabled || base}
            className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:bg-surface2 disabled:text-ink3"
          >
            {AGE_BANDS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-semibold text-ink2">
          성별
          <select
            id={`${prefix}-gender`}
            aria-label="성별"
            value={genderValue(scope.gender)}
            onChange={(event) =>
              onChange({
                ...scope,
                gender:
                  event.target.value === "common"
                    ? null
                    : Number(event.target.value) as 1 | 2,
              })
            }
            disabled={disabled || base}
            className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:bg-surface2 disabled:text-ink3"
          >
            {GENDERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs font-semibold text-ink2">
          기준금액
          <span className="relative mt-1.5 block">
            <input
              aria-label="기준금액"
              aria-invalid={minimumError ? "true" : undefined}
              aria-describedby={minimumError ? minimumErrorId : undefined}
              inputMode="decimal"
              value={scope.recommend_min ?? ""}
              onChange={(event) =>
                onChange({ ...scope, recommend_min: event.target.value })
              }
              disabled={disabled}
              placeholder="금액 입력"
              className="w-full rounded-xl border border-line bg-surface py-2.5 pl-3 pr-12 text-right text-sm font-semibold text-ink placeholder:font-normal placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:bg-surface2"
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink3">
              {unitLabel(scope.unit)}
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
        <label className="text-xs font-semibold text-ink2">
          넉넉 기준금액
          <span className="ml-1 font-normal text-ink3">(선택)</span>
          <span className="relative mt-1.5 block">
            <input
              aria-label="넉넉 기준금액"
              aria-invalid={maximumError ? "true" : undefined}
              aria-describedby={maximumError ? maximumErrorId : undefined}
              inputMode="decimal"
              value={scope.recommend_max ?? ""}
              onChange={(event) =>
                onChange({ ...scope, recommend_max: event.target.value })
              }
              disabled={disabled}
              placeholder="선택 입력"
              className="w-full rounded-xl border border-line bg-surface py-2.5 pl-3 pr-12 text-right text-sm font-semibold text-ink placeholder:font-normal placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:bg-surface2"
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink3">
              {unitLabel(scope.unit)}
            </span>
          </span>
          {maximumError && (
            <span
              id={maximumErrorId}
              className="mt-1.5 block text-xs font-semibold text-danger"
            >
              {maximumError}
            </span>
          )}
        </label>
      </div>
    </section>
  );
}

export function BaselineDetailDrawer({
  open,
  detail,
  disabled = false,
  errors = {},
  onClose,
  onScopeChange,
  onAddScope,
}: BaselineDetailDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    openerRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      openerRef.current?.focus();
    };
  }, [open]);

  if (!open) return null;

  const defaultScope =
    detail.baselines.find(isDefaultScope) ??
    ({
      analysis_detail_id: detail.id,
      product_group: 0,
      age_band: "all",
      gender: null,
      recommend_min: null,
      recommend_max: null,
      unit: detail.unit,
      baseline_source: null,
    } satisfies BaselineDraftScope);
  const exceptions = detail.baselines.filter((scope) => !isDefaultScope(scope));
  const occupied = new Set(detail.baselines.map(scopeIdentity));
  let availableScope: BaselineDraftScope | null = null;
  for (const product of PRODUCT_GROUPS) {
    for (const age of AGE_BANDS) {
      for (const gender of GENDERS) {
        const candidate: BaselineDraftScope = {
          analysis_detail_id: detail.id,
          product_group: product.value,
          age_band: age.value,
          gender:
            gender.value === "common" ? null : Number(gender.value) as 1 | 2,
          recommend_min: null,
          recommend_max: null,
          unit: detail.unit,
          baseline_source: null,
        };
        if (!occupied.has(scopeIdentity(candidate))) {
          availableScope = candidate;
          break;
        }
      }
      if (availableScope) break;
    }
    if (availableScope) break;
  }

  return (
    <div className="fixed inset-0 z-[100]">
      <button
        type="button"
        aria-label="상세 설정 닫기"
        onClick={onClose}
        className="absolute inset-0 bg-ink/35 backdrop-blur-[2px]"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="baseline-detail-title"
        className="absolute inset-y-0 right-0 flex w-full flex-col bg-surface shadow-2xl sm:max-w-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4 sm:px-6">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-brand">담보별 상세 기준</p>
            <h2
              id="baseline-detail-title"
              className="mt-1 truncate text-lg font-extrabold text-ink"
            >
              {detail.name} 상세 설정
            </h2>
            <p className="mt-1 text-xs leading-5 text-ink3">
              조건별 값이 있으면 전체 기본값보다 먼저 적용돼요.
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-xl border border-line text-ink3 transition hover:bg-surface2 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <X aria-hidden="true" size={20} />
          </button>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto bg-canvas px-4 py-5 sm:px-6">
          <ScopeEditor
            scope={defaultScope}
            base
            disabled={disabled}
            errors={errors[baselineScopeKey(defaultScope)]}
            onChange={(next) => onScopeChange(defaultScope, next)}
          />

          <div className="flex items-end justify-between gap-3 pt-2">
            <div>
              <h3 className="text-sm font-bold text-ink">조건별 상세 기준</h3>
              <p className="mt-1 text-xs leading-5 text-ink3">
                필요한 조건만 추가하고, 비워 둔 값은 저장하지 않아요.
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold text-ink3">
              {exceptions.length}개
            </span>
          </div>

          {exceptions.length === 0 && (
            <div className="rounded-2xl border border-dashed border-line bg-surface px-4 py-6 text-center">
              <p className="text-sm font-semibold text-ink2">
                전체 기본값을 모든 조건에 적용하고 있어요.
              </p>
              <p className="mt-1 text-xs text-ink3">
                다른 금액이 필요한 조건만 추가해 보세요.
              </p>
            </div>
          )}

          {exceptions.map((scope, index) => (
            <ScopeEditor
              key={`${scope.analysis_detail_id}:exception:${index}`}
              scope={scope}
              base={false}
              disabled={disabled}
              errors={errors[baselineScopeKey(scope)]}
              onChange={(next) => onScopeChange(scope, next)}
              onDelete={() => onScopeChange(scope, null)}
            />
          ))}

          <button
            type="button"
            disabled={disabled || !availableScope}
            onClick={() => availableScope && onAddScope(availableScope)}
            className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-brand/40 bg-brand-soft/30 px-4 text-sm font-bold text-brand transition hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus aria-hidden="true" size={18} />
            상세 기준 추가
          </button>
        </div>

        <footer className="border-t border-line bg-surface px-5 py-4 sm:px-6">
          <button
            type="button"
            onClick={onClose}
            className="min-h-12 w-full rounded-xl bg-brand px-4 text-sm font-bold text-white transition hover:bg-brand/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            편집 마치기
          </button>
        </footer>
      </div>
    </div>
  );
}
