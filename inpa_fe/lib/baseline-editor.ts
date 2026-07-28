import type {
  BaselineAgeBand,
  BaselineCatalogResponse,
  BaselineGender,
  BaselineProductGroup,
  BaselineUnit,
  LegacyPlannerBaseline,
  PlannerBaselineBatchChange,
} from "@/lib/api";

export interface BaselineDraftScope {
  analysis_detail_id: number;
  product_group: BaselineProductGroup;
  age_band: BaselineAgeBand;
  gender: BaselineGender;
  recommend_min: string | null;
  recommend_max: string | null;
  unit: BaselineUnit;
  baseline_source: string | null;
}

export interface BaselineDraftDetail {
  id: number;
  name: string;
  order: number;
  unit: BaselineUnit;
  baselines: BaselineDraftScope[];
}

export interface BaselineDraftSubcategory {
  id: number;
  name: string;
  insurance_type: number;
  order: number;
  details: BaselineDraftDetail[];
}

export interface BaselineDraftCategory {
  id: number;
  name: string;
  insurance_type: number;
  order: number;
  subcategories: BaselineDraftSubcategory[];
}

export interface BaselineDraftCatalog {
  revision: number;
  categories: BaselineDraftCategory[];
  legacy_baselines: LegacyPlannerBaseline[];
}

export type BaselineAmountField = "recommend_min" | "recommend_max";
export type BaselineFieldErrors = Record<
  string,
  Partial<Record<BaselineAmountField, string>>
>;

const DEFAULT_SCOPE = {
  product_group: 0,
  age_band: "all",
  gender: null,
} as const;

export function baselineScopeKey(
  scope: Pick<
    BaselineDraftScope,
    "analysis_detail_id" | "product_group" | "age_band" | "gender"
  >,
): string {
  return [
    scope.analysis_detail_id,
    scope.product_group,
    scope.age_band,
    scope.gender ?? "common",
  ].join(":");
}

function scopeHasAmount(scope: BaselineDraftScope): boolean {
  return (
    normalizeBaselineAmount(scope.recommend_min) !== null ||
    normalizeBaselineAmount(scope.recommend_max) !== null
  );
}

export function normalizeBaselineAmount(
  value: string | number | null | undefined,
): string | null {
  if (value === null || value === undefined) return null;
  const trimmed = String(value).trim();
  if (trimmed === "") return null;

  const match = trimmed.match(/^([+-]?)(\d*)(?:\.(\d*))?$/);
  if (!match || (match[2] === "" && match[3] === "")) return trimmed;

  const integer = (match[2] || "0").replace(/^0+(?=\d)/, "");
  const fraction = (match[3] ?? "").replace(/0+$/, "");
  const isZero = integer === "0" && fraction === "";
  const sign = match[1] === "-" && !isZero ? "-" : "";
  return `${sign}${integer}${fraction ? `.${fraction}` : ""}`;
}

export function catalogToDraft(
  catalog: BaselineCatalogResponse,
): BaselineDraftCatalog {
  return {
    revision: catalog.revision,
    legacy_baselines: catalog.legacy_baselines,
    categories: catalog.categories.map((category) => ({
      ...category,
      subcategories: category.subcategories.map((subcategory) => ({
        ...subcategory,
        details: subcategory.details.map((detail) => {
          const scopes: BaselineDraftScope[] = detail.baselines.map((baseline) => ({
            analysis_detail_id: detail.id,
            product_group: baseline.product_group,
            age_band: baseline.age_band,
            gender: baseline.gender,
            recommend_min: normalizeBaselineAmount(baseline.recommend_min),
            recommend_max: normalizeBaselineAmount(baseline.recommend_max),
            unit: baseline.unit,
            baseline_source: baseline.baseline_source,
          }));
          const defaultIndex = scopes.findIndex(
            (scope) =>
              scope.product_group === DEFAULT_SCOPE.product_group &&
              scope.age_band === DEFAULT_SCOPE.age_band &&
              scope.gender === DEFAULT_SCOPE.gender,
          );
          const defaultScope: BaselineDraftScope =
            defaultIndex >= 0
              ? scopes[defaultIndex]
              : {
                  analysis_detail_id: detail.id,
                  ...DEFAULT_SCOPE,
                  recommend_min: null,
                  recommend_max: null,
                  unit: detail.unit,
                  baseline_source: null,
                };
          return {
            ...detail,
            baselines: [
              defaultScope,
              ...scopes.filter((_scope, index) => index !== defaultIndex),
            ],
          };
        }),
      })),
    })),
  };
}

function scopeMap(catalog: BaselineDraftCatalog): Map<string, BaselineDraftScope> {
  const result = new Map<string, BaselineDraftScope>();
  for (const category of catalog.categories) {
    for (const subcategory of category.subcategories) {
      for (const detail of subcategory.details) {
        for (const scope of detail.baselines) {
          result.set(baselineScopeKey(scope), scope);
        }
      }
    }
  }
  return result;
}

function validateAmount(value: string | null): string | null {
  if (value === null) return null;
  if (!/^\d+(?:\.\d+)?$/.test(value)) {
    return "0 이상의 숫자를 입력해 주세요.";
  }
  const [integer, fraction = ""] = value.split(".");
  if (fraction.length > 2) {
    return "소수점 아래는 2자리까지 입력해 주세요.";
  }
  const significantInteger = integer.replace(/^0+/, "");
  const digitCount = significantInteger.length + fraction.length;
  if (digitCount > 14) {
    return "금액은 전체 14자리까지 입력해 주세요.";
  }
  if (significantInteger.length > 12) {
    return "정수 부분은 12자리까지 입력해 주세요.";
  }
  return null;
}

export function validateBaselineChanges(
  changes: PlannerBaselineBatchChange[],
): BaselineFieldErrors {
  const errors: BaselineFieldErrors = {};
  for (const change of changes) {
    const scopeErrors: Partial<Record<BaselineAmountField, string>> = {};
    const minimum = normalizeBaselineAmount(change.recommend_min);
    const maximum = normalizeBaselineAmount(change.recommend_max);
    const minimumError = validateAmount(minimum);
    const maximumError = validateAmount(maximum);
    if (minimumError) scopeErrors.recommend_min = minimumError;
    if (maximumError) scopeErrors.recommend_max = maximumError;
    if (
      !minimumError &&
      !maximumError &&
      minimum !== null &&
      maximum !== null &&
      Number(minimum) > Number(maximum)
    ) {
      scopeErrors.recommend_max =
        "넉넉 기준금액은 기준금액 이상으로 입력해 주세요.";
    }
    if (Object.keys(scopeErrors).length > 0) {
      errors[baselineScopeKey(change)] = scopeErrors;
    }
  }
  return errors;
}

function firstString(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value;
  if (Array.isArray(value)) {
    for (const item of value) {
      const match = firstString(item);
      if (match) return match;
    }
  } else if (value && typeof value === "object") {
    for (const item of Object.values(value as Record<string, unknown>)) {
      const match = firstString(item);
      if (match) return match;
    }
  }
  return null;
}

export function mapBaselineBatchFieldErrors(
  changes: PlannerBaselineBatchChange[],
  data: Record<string, unknown> | undefined,
): BaselineFieldErrors {
  const result: BaselineFieldErrors = {};
  const nested = data?.changes;
  if (!Array.isArray(nested)) return result;
  nested.forEach((item, index) => {
    const change = changes[index];
    if (!change || !item || typeof item !== "object") return;
    const row = item as Record<string, unknown>;
    const fields: Partial<Record<BaselineAmountField, string>> = {};
    for (const field of ["recommend_min", "recommend_max"] as const) {
      const message = firstString(row[field]);
      if (message) fields[field] = message;
    }
    if (Object.keys(fields).length > 0) {
      result[baselineScopeKey(change)] = fields;
    }
  });
  return result;
}

function sameScopeValue(
  left: BaselineDraftScope | undefined,
  right: BaselineDraftScope | undefined,
): boolean {
  if (!left || !right) return false;
  return (
    normalizeBaselineAmount(left.recommend_min) ===
      normalizeBaselineAmount(right.recommend_min) &&
    normalizeBaselineAmount(left.recommend_max) ===
      normalizeBaselineAmount(right.recommend_max) &&
    left.unit === right.unit &&
    left.baseline_source === right.baseline_source
  );
}

function asChange(scope: BaselineDraftScope): PlannerBaselineBatchChange {
  return {
    analysis_detail_id: scope.analysis_detail_id,
    product_group: scope.product_group,
    age_band: scope.age_band,
    gender: scope.gender,
    recommend_min: normalizeBaselineAmount(scope.recommend_min),
    recommend_max: normalizeBaselineAmount(scope.recommend_max),
    unit: scope.unit,
  };
}

export function adoptBaselineScope(
  scope: BaselineDraftScope,
): BaselineDraftScope {
  return { ...scope, baseline_source: "planner" };
}

export function buildBaselineChanges(
  server: BaselineDraftCatalog,
  draft: BaselineDraftCatalog,
): PlannerBaselineBatchChange[] {
  const serverByKey = scopeMap(server);
  const draftByKey = scopeMap(draft);
  const changes: PlannerBaselineBatchChange[] = [];

  for (const [key, draftScope] of draftByKey) {
    const serverScope = serverByKey.get(key);
    if (!serverScope && !scopeHasAmount(draftScope)) continue;
    if (!sameScopeValue(serverScope, draftScope)) {
      changes.push(asChange(draftScope));
    }
  }

  for (const [key, serverScope] of serverByKey) {
    if (!draftByKey.has(key) && scopeHasAmount(serverScope)) {
      changes.push({
        ...asChange(serverScope),
        recommend_min: null,
        recommend_max: null,
      });
    }
  }
  return changes;
}

export function filterBaselineCatalog(
  catalog: BaselineDraftCatalog,
  query: string,
  configuredOnly: boolean,
): BaselineDraftCatalog {
  const normalizedQuery = query.trim().toLocaleLowerCase("ko-KR");
  const categories = catalog.categories.flatMap((category) => {
    const categoryMatches = category.name
      .toLocaleLowerCase("ko-KR")
      .includes(normalizedQuery);
    const subcategories = category.subcategories.flatMap((subcategory) => {
      const subcategoryMatches = subcategory.name
        .toLocaleLowerCase("ko-KR")
        .includes(normalizedQuery);
      const details = subcategory.details.filter((detail) => {
        const matches =
          normalizedQuery === "" ||
          categoryMatches ||
          subcategoryMatches ||
          detail.name.toLocaleLowerCase("ko-KR").includes(normalizedQuery);
        return (
          matches &&
          (!configuredOnly || detail.baselines.some(scopeHasAmount))
        );
      });
      return details.length > 0 ? [{ ...subcategory, details }] : [];
    });
    return subcategories.length > 0 ? [{ ...category, subcategories }] : [];
  });
  return { ...catalog, categories };
}

export function countChangedScopes(
  server: BaselineDraftCatalog,
  draft: BaselineDraftCatalog,
): number {
  return buildBaselineChanges(server, draft).length;
}
