import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  linkLegacyBaseline,
  listBaselines,
  savePlannerBaselineBatch,
  type PlannerBaselineWritePayload,
} from "@/lib/api";

type AnalysisDetailIsRequired =
  {} extends Pick<PlannerBaselineWritePayload, "analysis_detail"> ? false : true;
type ServerOwnedFieldsExcluded =
  Extract<
    keyof PlannerBaselineWritePayload,
    "coverage_key" | "baseline_source" | "preset_origin"
  > extends never
    ? true
    : false;

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status === 400 ? "Bad Request" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

describe("담보 기준 API 계약", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("product_group=0도 목록 조회 쿼리에 포함한다", async () => {
    const fetch = vi.fn().mockResolvedValue(
      jsonResponse({ count: 0, next: null, previous: null, results: [] }),
    );
    vi.stubGlobal("fetch", fetch);

    await listBaselines({ product_group: 0 });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/planner-baselines/?product_group=0",
      expect.any(Object),
    );
  });

  it("직접 저장 payload는 표준 담보가 필수이고 서버 소유 필드를 제외한다", () => {
    const analysisDetailRequired: AnalysisDetailIsRequired = true;
    const serverOwnedFieldsExcluded: ServerOwnedFieldsExcluded = true;

    expect(analysisDetailRequired).toBe(true);
    expect(serverOwnedFieldsExcluded).toBe(true);
  });

  it("중첩된 DRF changes 오류의 실제 문구와 원문 데이터를 보존한다", async () => {
    const body = {
      code: "invalid_baseline",
      changes: [
        {
          recommend_min: ["금액 형식을 확인해 주세요."],
        },
      ],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(body, 400)));

    const promise = savePlannerBaselineBatch({
      revision: 1,
      changes: [
        {
          analysis_detail_id: 101,
          product_group: 3,
          age_band: "30s",
          gender: 1,
          recommend_min: "invalid",
          recommend_max: null,
          unit: 1,
        },
      ],
    });

    await expect(promise).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      message: "금액 형식을 확인해 주세요.",
      data: body,
    } satisfies Partial<ApiError>);
  });

  it("기존 직접 입력 연결은 선택한 행과 표준 담보 ID만 보낸다", async () => {
    const fetch = vi.fn().mockResolvedValue(
      jsonResponse({
        revision: 4,
        baseline: { id: 91, analysis_detail: 102 },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await linkLegacyBaseline(91, 102);

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/planner-baselines/91/link/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ analysis_detail_id: 102 }),
      }),
    );
  });
});
