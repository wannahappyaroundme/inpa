import { describe, expect, it } from "vitest";
import {
  buildBaselineChanges,
  catalogToDraft,
  countChangedScopes,
  filterBaselineCatalog,
  mapBaselineBatchFieldErrors,
  normalizeBaselineAmount,
  normalizeSavedBaselineDraft,
  validateBaselineChanges,
} from "@/lib/baseline-editor";
import type {
  BaselineCatalogResponse,
  PlannerBaselineBatchChange,
} from "@/lib/api";

const catalog: BaselineCatalogResponse = {
  revision: 3,
  legacy_baselines: [],
  categories: [
    {
      id: 1,
      name: "진단비",
      insurance_type: 0,
      order: 1,
      subcategories: [
        {
          id: 11,
          name: "암",
          insurance_type: 0,
          order: 1,
          details: [
            {
              id: 101,
              name: "일반암 진단비",
              order: 1,
              unit: 1,
              baselines: [
                {
                  analysis_detail: 101,
                  product_group: 0,
                  age_band: "all",
                  gender: null,
                  recommend_min: "3000.00",
                  recommend_max: null,
                  unit: 1,
                  baseline_source: "planner",
                },
                {
                  analysis_detail: 101,
                  product_group: 1,
                  age_band: "30s",
                  gender: 1,
                  recommend_min: "5000.00",
                  recommend_max: "7000.00",
                  unit: 1,
                  baseline_source: "planner",
                },
              ],
            },
          ],
        },
        {
          id: 12,
          name: "뇌",
          insurance_type: 0,
          order: 2,
          details: [
            {
              id: 102,
              name: "뇌혈관 진단비",
              order: 1,
              unit: 1,
              baselines: [],
            },
          ],
        },
      ],
    },
    {
      id: 2,
      name: "수술비",
      insurance_type: 2,
      order: 2,
      subcategories: [
        {
          id: 21,
          name: "상해",
          insurance_type: 2,
          order: 1,
          details: [
            {
              id: 201,
              name: "골절 수술비",
              order: 1,
              unit: 2,
              baselines: [],
            },
          ],
        },
      ],
    },
  ],
};

describe("담보 기준 편집 변환", () => {
  it("빈 금액은 null로 바꾸고 유효한 0과 같은 숫자 표현을 보존한다", () => {
    expect(normalizeBaselineAmount("   ")).toBeNull();
    expect(normalizeBaselineAmount(null)).toBeNull();
    expect(normalizeBaselineAmount("0")).toBe("0");
    expect(normalizeBaselineAmount("005000.00")).toBe("5000");
  });

  it("모든 담보에 전체 상품·전연령·성별 공통 기본 행을 만든다", () => {
    const draft = catalogToDraft(catalog);
    const emptyDetail =
      draft.categories[0].subcategories[1].details[0];

    expect(emptyDetail.baselines).toEqual([
      {
        analysis_detail_id: 102,
        product_group: 0,
        age_band: "all",
        gender: null,
        recommend_min: null,
        recommend_max: null,
        unit: 1,
        baseline_source: null,
        is_stored: false,
      },
    ]);
    expect(draft.categories[0].subcategories[0].details[0].baselines[0]).toEqual({
      analysis_detail_id: 101,
      product_group: 0,
      age_band: "all",
      gender: null,
      recommend_min: "3000",
      recommend_max: null,
      unit: 1,
      baseline_source: "planner",
      is_stored: true,
    });
  });

  it("바뀐 값만 보내고 기존 값을 비우면 삭제 변경을 보낸다", () => {
    const server = catalogToDraft(catalog);
    const draft = structuredClone(server);
    const cancer = draft.categories[0].subcategories[0].details[0];
    const brain = draft.categories[0].subcategories[1].details[0];
    cancer.baselines[0].recommend_min = null;
    cancer.baselines[0].recommend_max = null;
    brain.baselines[0].recommend_min = "5000";

    expect(buildBaselineChanges(server, draft)).toEqual([
      {
        analysis_detail_id: 101,
        product_group: 0,
        age_band: "all",
        gender: null,
        recommend_min: null,
        recommend_max: null,
        unit: 1,
      },
      {
        analysis_detail_id: 102,
        product_group: 0,
        age_band: "all",
        gender: null,
        recommend_min: "5000",
        recommend_max: null,
        unit: 1,
      },
    ]);
    expect(countChangedScopes(server, draft)).toBe(2);
  });

  it("표시 형식만 다른 같은 금액은 변경으로 세지 않는다", () => {
    const server = catalogToDraft(catalog);
    const draft = structuredClone(server);
    draft.categories[0].subcategories[0].details[0].baselines[0].recommend_min =
      "3000.00";

    expect(buildBaselineChanges(server, draft)).toEqual([]);
    expect(countChangedScopes(server, draft)).toBe(0);
  });

  it("변경하지 않은 이전 기준을 내 기준으로 사용하면 저장 변경을 만든다", () => {
    const server = structuredClone(catalog);
    server.categories[0].subcategories[0].details[0].baselines[0] = {
      ...server.categories[0].subcategories[0].details[0].baselines[0],
      recommend_min: "5000",
      recommend_max: null,
      baseline_source: "preset",
    };
    const serverDraft = catalogToDraft(server);
    const draft = structuredClone(serverDraft);
    draft.categories[0].subcategories[0].details[0].baselines[0].baseline_source =
      "planner";

    expect(buildBaselineChanges(serverDraft, draft)).toEqual([
      expect.objectContaining({
        recommend_min: "5000",
        recommend_max: null,
      }),
    ]);
  });

  it("저장한 범위만 설계사 기준으로 정리하고 나머지 이전 기준은 보존한다", () => {
    const draft = catalogToDraft(catalog);
    const savedScope =
      draft.categories[0].subcategories[0].details[0].baselines[0];
    savedScope.recommend_min = "04500.00";
    savedScope.baseline_source = "preset";
    const untouchedScope =
      draft.categories[0].subcategories[0].details[0].baselines[1];
    untouchedScope.recommend_min = "05000.00";
    untouchedScope.baseline_source = null;
    const deletedScope =
      draft.categories[0].subcategories[1].details[0].baselines[0];
    deletedScope.recommend_min = "3000";
    deletedScope.baseline_source = "preset";
    deletedScope.is_stored = true;
    const changes: PlannerBaselineBatchChange[] = [
      {
        analysis_detail_id: savedScope.analysis_detail_id,
        product_group: savedScope.product_group,
        age_band: savedScope.age_band,
        gender: savedScope.gender,
        recommend_min: "4500",
        recommend_max: null,
        unit: savedScope.unit,
      },
      {
        analysis_detail_id: deletedScope.analysis_detail_id,
        product_group: deletedScope.product_group,
        age_band: deletedScope.age_band,
        gender: deletedScope.gender,
        recommend_min: null,
        recommend_max: null,
        unit: deletedScope.unit,
      },
    ];
    const saved = normalizeSavedBaselineDraft(draft, changes, 4);

    expect(saved.revision).toBe(4);
    expect(
      saved.categories[0].subcategories[0].details[0].baselines[0],
    ).toMatchObject({
      recommend_min: "4500",
      baseline_source: "planner",
      is_stored: true,
    });
    expect(
      saved.categories[0].subcategories[0].details[0].baselines[1],
    ).toMatchObject({
      recommend_min: "05000.00",
      baseline_source: null,
      is_stored: true,
    });
    expect(
      saved.categories[0].subcategories[1].details[0].baselines[0],
    ).toMatchObject({
      recommend_min: null,
      recommend_max: null,
      baseline_source: null,
      is_stored: false,
    });
    expect(savedScope.baseline_source).toBe("preset");
  });

  it("대분류·중분류·담보명 검색을 각각 지원하고 빈 그룹은 제거한다", () => {
    const draft = catalogToDraft(catalog);

    expect(
      filterBaselineCatalog(draft, "수술비", false).categories.map(
        (category) => category.name,
      ),
    ).toEqual(["수술비"]);
    expect(
      filterBaselineCatalog(draft, "뇌", false).categories[0].subcategories.map(
        (subcategory) => subcategory.name,
      ),
    ).toEqual(["뇌"]);
    expect(
      filterBaselineCatalog(draft, "일반암", false)
        .categories[0].subcategories[0].details.map((detail) => detail.name),
    ).toEqual(["일반암 진단비"]);
    expect(filterBaselineCatalog(draft, "없는 담보", false).categories).toEqual(
      [],
    );
  });

  it("입력한 담보만 보기는 상세 범위 중 하나라도 값이 있는 담보를 남긴다", () => {
    const draft = catalogToDraft(catalog);
    const configured = filterBaselineCatalog(draft, "", true);

    expect(
      configured.categories[0].subcategories[0].details.map(
        (detail) => detail.name,
      ),
    ).toEqual(["일반암 진단비"]);
    expect(configured.categories).toHaveLength(1);
  });

  it("음수·소수 자릿수·전체 자릿수·최소 최대 관계를 저장 전에 검사한다", () => {
    const base = {
      analysis_detail_id: 101,
      product_group: 0 as const,
      age_band: "all" as const,
      gender: null,
      recommend_min: "-1",
      recommend_max: "100",
      unit: 1 as const,
    };

    expect(validateBaselineChanges([base])).toEqual({
      "101:0:all:common": {
        recommend_min: "0 이상의 숫자를 입력해 주세요.",
      },
    });
    expect(
      validateBaselineChanges([
        { ...base, recommend_min: "1.234", recommend_max: null },
      ]),
    ).toEqual({
      "101:0:all:common": {
        recommend_min: "소수점 아래는 2자리까지 입력해 주세요.",
      },
    });
    expect(
      validateBaselineChanges([
        {
          ...base,
          recommend_min: "123456789012345",
          recommend_max: null,
        },
      ]),
    ).toEqual({
      "101:0:all:common": {
        recommend_min: "금액은 전체 14자리까지 입력해 주세요.",
      },
    });
    expect(
      validateBaselineChanges([
        { ...base, recommend_min: "200", recommend_max: "100" },
      ]),
    ).toEqual({
      "101:0:all:common": {
        recommend_max:
          "넉넉 기준금액은 기준금액 이상으로 입력해 주세요.",
      },
    });
  });

  it("서버 DecimalField와 같은 정수부 12자리·소수부 2자리 경계를 적용한다", () => {
    const change = (recommend_min: string) => ({
      analysis_detail_id: 101,
      product_group: 0 as const,
      age_band: "all" as const,
      gender: null,
      recommend_min,
      recommend_max: null,
      unit: 1 as const,
    });

    expect(validateBaselineChanges([change("123456789012")])).toEqual({});
    expect(validateBaselineChanges([change("123456789012.34")])).toEqual({});
    expect(validateBaselineChanges([change("000123456789012.34")])).toEqual(
      {},
    );
    for (const value of ["1234567890123", "12345678901234"]) {
      expect(validateBaselineChanges([change(value)])).toEqual({
        "101:0:all:common": {
          recommend_min: "정수 부분은 12자리까지 입력해 주세요.",
        },
      });
    }
    expect(validateBaselineChanges([change("123456789012.345")])).toEqual({
      "101:0:all:common": {
        recommend_min: "소수점 아래는 2자리까지 입력해 주세요.",
      },
    });
  });

  it("일괄 저장의 changes[index] 오류를 해당 범위 입력으로 연결한다", () => {
    const changes = [
      {
        analysis_detail_id: 101,
        product_group: 3 as const,
        age_band: "30s" as const,
        gender: 1 as const,
        recommend_min: "100",
        recommend_max: "200",
        unit: 1 as const,
      },
    ];

    expect(
      mapBaselineBatchFieldErrors(changes, {
        changes: [
          {
            recommend_min: ["금액 형식을 확인해 주세요."],
            recommend_max: ["최댓값을 확인해 주세요."],
          },
        ],
      }),
    ).toEqual({
      "101:3:30s:1": {
        recommend_min: "금액 형식을 확인해 주세요.",
        recommend_max: "최댓값을 확인해 주세요.",
      },
    });
  });

  it("기존 실손·연금저축 범위를 손실 없이 편집 초안과 변경 요청에 유지한다", () => {
    const extended = structuredClone(catalog);
    extended.categories[0].subcategories[0].details[0].baselines.push(
      {
        analysis_detail: 101,
        product_group: 3,
        age_band: "40s",
        gender: 2,
        recommend_min: "8000.00",
        recommend_max: null,
        unit: 1,
      },
      {
        analysis_detail: 101,
        product_group: 4,
        age_band: "50s",
        gender: null,
        recommend_min: "9000.00",
        recommend_max: null,
        unit: 1,
      },
    );
    const server = catalogToDraft(extended);
    const draft = structuredClone(server);
    const scopes = draft.categories[0].subcategories[0].details[0].baselines;
    expect(scopes.map((scope) => scope.product_group)).toEqual([0, 1, 3, 4]);

    scopes.find((scope) => scope.product_group === 3)!.recommend_min = "8100";
    expect(buildBaselineChanges(server, draft)).toEqual([
      expect.objectContaining({
        product_group: 3,
        recommend_min: "8100",
      }),
    ]);
  });
});
