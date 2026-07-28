import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BaselineSettingsPage from "@/app/settings/baseline/page";
import {
  ApiError,
  deleteBaseline,
  getBaselineCatalog,
  linkLegacyBaseline,
  savePlannerBaselineBatch,
  type BaselineCatalogResponse,
} from "@/lib/api";

const navigationMocks = vi.hoisted(() => ({
  programmaticNavigate: vi.fn(),
}));

vi.mock("@/lib/useAuthGuard", () => ({ useAuthGuard: () => true }));
vi.mock("@/components/app-nav", () => ({
  AppNav: ({
    onBeforeNavigate,
  }: {
    onBeforeNavigate?: () => boolean;
  }) => (
    <>
      <a href="/dashboard">대시보드로 이동</a>
      <button
        type="button"
        onClick={() => {
          if (onBeforeNavigate?.() ?? true) {
            navigationMocks.programmaticNavigate();
          }
        }}
      >
        Manager 팀 현황 보기
      </button>
    </>
  ),
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getBaselineCatalog: vi.fn(),
    linkLegacyBaseline: vi.fn(),
    deleteBaseline: vi.fn(),
    savePlannerBaselineBatch: vi.fn(),
  };
});

const apiGet = vi.mocked(getBaselineCatalog);
const apiLinkLegacy = vi.mocked(linkLegacyBaseline);
const apiDelete = vi.mocked(deleteBaseline);
const apiSave = vi.mocked(savePlannerBaselineBatch);

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
                  is_active: true,
                },
              ],
            },
            {
              id: 102,
              name: "뇌혈관 진단비",
              order: 2,
              unit: 1,
              baselines: [],
            },
          ],
        },
      ],
    },
  ],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("담보 전체 기준표 페이지 상태", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiLinkLegacy.mockReset();
    apiDelete.mockReset();
    apiSave.mockReset();
    navigationMocks.programmaticNavigate.mockReset();
    apiGet.mockResolvedValue(structuredClone(catalog));
    apiLinkLegacy.mockResolvedValue({
      revision: 4,
      baseline: {
        id: 91,
        analysis_detail: 102,
        coverage_key: "뇌혈관 진단비",
        product_group: 0,
        age_band: "all",
        gender: null,
        recommend_min: "2500.00",
        recommend_max: null,
        unit: 1,
        baseline_source: "planner",
        preset_origin: null,
        is_active: true,
        created_at: "2026-07-28T00:00:00Z",
        updated_at: "2026-07-28T00:00:00Z",
      },
    });
    apiDelete.mockResolvedValue(undefined);
    apiSave.mockResolvedValue({ revision: 4 });
    window.history.replaceState({}, "", "/settings/baseline");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("불러오는 동안 브랜드 스켈레톤을 보여준다", () => {
    apiGet.mockReturnValue(new Promise(() => undefined));
    render(<BaselineSettingsPage />);

    expect(
      screen.getByRole("status", { name: "담보 기준 불러오는 중" }),
    ).toBeInTheDocument();
  });

  it("불러오기 실패 뒤 다시 시도하면 전체 담보를 표시한다", async () => {
    const user = userEvent.setup();
    apiGet
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(structuredClone(catalog));
    render(<BaselineSettingsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "담보 기준을 불러오지 못했어요.",
    );
    await user.click(screen.getByRole("button", { name: "다시 불러오기" }));

    expect(
      await screen.findByLabelText("일반암 진단비 기준금액"),
    ).toHaveValue("3000");
  });

  it("기존 직접 입력의 적용 상태와 이름 충돌 이유를 보여주고 선택한 담보에 연결한다", async () => {
    const user = userEvent.setup();
    apiGet.mockResolvedValue({
      ...structuredClone(catalog),
      legacy_baselines: [
        {
          id: 91,
          coverage_key: "뇌혈관 진단비",
          product_group: 0,
          age_band: "all",
          gender: null,
          recommend_min: "2500.00",
          recommend_max: null,
          unit: 1,
          is_active: true,
          is_applied: true,
          conflict_code: "multiple_standard_matches",
          conflict_reason:
            "같은 이름의 표준 담보가 여러 곳에 있어 연결할 항목을 확인해 주세요.",
          matching_analysis_detail_ids: [101, 102],
        },
      ],
    });
    render(<BaselineSettingsPage />);

    expect(
      await screen.findByRole("heading", { name: "기존 직접 입력" }),
    ).toBeInTheDocument();
    expect(screen.getByText("분석에 적용 중")).toBeInTheDocument();
    expect(
      screen.getByText(
        "같은 이름의 표준 담보가 여러 곳에 있어 연결할 항목을 확인해 주세요.",
      ),
    ).toBeInTheDocument();

    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "뇌혈관 진단비 연결할 표준 담보",
      }),
      "102",
    );
    await user.click(
      screen.getByRole("button", { name: "뇌혈관 진단비 표준 담보에 연결" }),
    );

    expect(apiLinkLegacy).toHaveBeenCalledWith(91, 102);
    expect(apiGet).toHaveBeenCalledTimes(2);
  });

  it("기존 직접 입력은 확인 뒤 선택한 행만 삭제한다", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiGet.mockResolvedValue({
      ...structuredClone(catalog),
      legacy_baselines: [
        {
          id: 92,
          coverage_key: "직접 적은 담보",
          product_group: 0,
          age_band: "all",
          gender: null,
          recommend_min: "1500.00",
          recommend_max: null,
          unit: 1,
          is_active: true,
          is_applied: false,
          conflict_code: "no_standard_match",
          conflict_reason:
            "같은 이름의 표준 담보를 찾지 못해 연결할 항목을 확인해 주세요.",
          matching_analysis_detail_ids: [],
        },
      ],
    });
    render(<BaselineSettingsPage />);

    expect(await screen.findByText("연결 필요")).toBeInTheDocument();

    await user.click(
      await screen.findByRole("button", {
        name: "직접 적은 담보 기존 값 삭제",
      }),
    );

    expect(apiDelete).toHaveBeenCalledWith(92);
    expect(apiGet).toHaveBeenCalledTimes(2);
  });

  it("확인 전 이전 기준은 연결 뒤 금액 확인이 필요하다고 안내한다", async () => {
    apiGet.mockResolvedValue({
      ...structuredClone(catalog),
      legacy_baselines: [
        {
          id: 93,
          coverage_key: "이전 기준 담보",
          product_group: 0,
          age_band: "all",
          gender: null,
          recommend_min: "1500.00",
          recommend_max: null,
          unit: 1,
          is_active: true,
          is_applied: false,
          requires_adoption: true,
          conflict_code: "link_confirmation_required",
          conflict_reason: "연결할 표준 담보를 확인해 주세요.",
          matching_analysis_detail_ids: [101],
        },
      ],
    });
    render(<BaselineSettingsPage />);

    expect(
      await screen.findByText("연결 후 금액 확인 필요"),
    ).toBeInTheDocument();
    expect(screen.queryByText("연결 후 분석에 적용")).not.toBeInTheDocument();
  });

  it("이전 서버 응답에 활성 상태가 없어도 비활성 기준으로 오해하지 않는다", async () => {
    apiGet.mockResolvedValue({
      ...structuredClone(catalog),
      legacy_baselines: [
        {
          id: 94,
          coverage_key: "연결할 기준 담보",
          product_group: 0,
          age_band: "all",
          gender: null,
          recommend_min: "1500.00",
          recommend_max: null,
          unit: 1,
          is_applied: false,
          conflict_code: "link_confirmation_required",
          conflict_reason: "연결할 표준 담보를 확인해 주세요.",
          matching_analysis_detail_ids: [101],
        },
      ],
    });
    render(<BaselineSettingsPage />);

    expect(await screen.findByText("연결 필요")).toBeInTheDocument();
    expect(screen.queryByText("연결 후 다시 사용 필요")).toBeNull();
  });

  it("일괄 저장 성공은 새 revision을 사용하고 변경 상태를 비운다", async () => {
    const user = userEvent.setup();
    apiSave
      .mockResolvedValueOnce({ revision: 4 })
      .mockResolvedValueOnce({ revision: 5 });
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");

    await user.clear(input);
    await user.type(input, "4500");
    expect(screen.getByText("변경 1개")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "변경 내용 저장" }));

    expect(apiSave).toHaveBeenNthCalledWith(1, {
      revision: 3,
      changes: [
        {
          analysis_detail_id: 101,
          product_group: 0,
          age_band: "all",
          gender: null,
          recommend_min: "4500",
          recommend_max: null,
          unit: 1,
        },
      ],
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "변경 내용을 저장했어요.",
    );
    expect(screen.getByText("변경 0개")).toBeInTheDocument();

    await user.clear(input);
    await user.type(input, "4600");
    await user.click(screen.getByRole("button", { name: "변경 내용 저장" }));
    expect(apiSave).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ revision: 4 }),
    );
  });

  it("출처 없는 이전 기준은 저장할 때 내 기준으로 적용하고 출처는 보내지 않는다", async () => {
    const user = userEvent.setup();
    apiGet.mockResolvedValue({
      ...structuredClone(catalog),
      categories: [{
        ...structuredClone(catalog.categories[0]),
        subcategories: [{
          ...structuredClone(catalog.categories[0].subcategories[0]),
          details: [{
            ...structuredClone(catalog.categories[0].subcategories[0].details[0]),
            baselines: [{
              ...structuredClone(catalog.categories[0].subcategories[0].details[0].baselines[0]),
              baseline_source: null,
            }],
          }],
        }],
      }],
    });
    render(<BaselineSettingsPage />);

    await user.click(
      await screen.findByRole("button", { name: "일반암 진단비 상세 설정" }),
    );
    await user.click(screen.getByRole("button", { name: "내 기준으로 사용" }));
    await user.click(screen.getByRole("button", { name: "변경 내용 저장" }));

    expect(apiSave).toHaveBeenCalledWith({
      revision: 3,
      changes: [{
        analysis_detail_id: 101,
        product_group: 0,
        age_band: "all",
        gender: null,
        recommend_min: "3000",
        recommend_max: null,
        unit: 1,
      }],
    });
  });

  it("비활성 내 기준을 다시 사용하면 기존 요청 형식으로 저장하고 완료 뒤 안내를 지운다", async () => {
    const user = userEvent.setup();
    const inactiveCatalog = structuredClone(catalog) as BaselineCatalogResponse & {
      categories: Array<{ subcategories: Array<{ details: Array<{ baselines: Array<Record<string, unknown>> }> }> }>;
    };
    inactiveCatalog.categories[0].subcategories[0].details[0].baselines[0].is_active = false;
    apiGet.mockResolvedValue(inactiveCatalog);
    render(<BaselineSettingsPage />);

    await user.click(
      await screen.findByRole("button", { name: "일반암 진단비 상세 설정" }),
    );
    await user.click(screen.getByRole("button", { name: "내 기준으로 다시 사용" }));
    await user.click(screen.getByRole("button", { name: "변경 내용 저장" }));

    expect(apiSave).toHaveBeenCalledWith({
      revision: 3,
      changes: [{
        analysis_detail_id: 101,
        product_group: 0,
        age_band: "all",
        gender: null,
        recommend_min: "3000",
        recommend_max: null,
        unit: 1,
      }],
    });
    expect(
      screen.queryByRole("button", { name: "내 기준으로 다시 사용" }),
    ).toBeNull();
  });

  it("금액을 고쳐 저장한 이전 기준은 바로 내 기준으로 표시한다", async () => {
    const user = userEvent.setup();
    apiGet.mockResolvedValue({
      ...structuredClone(catalog),
      categories: [{
        ...structuredClone(catalog.categories[0]),
        subcategories: [{
          ...structuredClone(catalog.categories[0].subcategories[0]),
          details: [{
            ...structuredClone(catalog.categories[0].subcategories[0].details[0]),
            baselines: [{
              ...structuredClone(catalog.categories[0].subcategories[0].details[0].baselines[0]),
              baseline_source: "preset",
            }],
          }],
        }],
      }],
    });
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");

    await user.clear(input);
    await user.type(input, "4500");
    await user.click(screen.getByRole("button", { name: "변경 내용 저장" }));
    await user.click(
      screen.getByRole("button", { name: "일반암 진단비 상세 설정" }),
    );

    expect(
      screen.queryByRole("button", { name: "내 기준으로 사용" }),
    ).toBeNull();
  });

  it("다른 범위를 저장해도 손대지 않은 이전 기준은 내 기준으로 사용하도록 남긴다", async () => {
    const user = userEvent.setup();
    apiGet.mockResolvedValue({
      ...structuredClone(catalog),
      categories: [{
        ...structuredClone(catalog.categories[0]),
        subcategories: [{
          ...structuredClone(catalog.categories[0].subcategories[0]),
          details: [{
            ...structuredClone(catalog.categories[0].subcategories[0].details[0]),
            baselines: [
              {
                ...structuredClone(catalog.categories[0].subcategories[0].details[0].baselines[0]),
                baseline_source: "preset",
              },
              {
                analysis_detail: 101,
                product_group: 1,
                age_band: "30s",
                gender: 1,
                recommend_min: "5000.00",
                recommend_max: null,
                unit: 1,
                baseline_source: null,
              },
            ],
          }],
        }],
      }],
    });
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");

    await user.clear(input);
    await user.type(input, "4500");
    await user.click(screen.getByRole("button", { name: "변경 내용 저장" }));
    await user.click(
      screen.getByRole("button", { name: "일반암 진단비 상세 설정" }),
    );

    expect(screen.getByRole("button", { name: "내 기준으로 사용" })).toBeTruthy();
  });

  it("409 충돌은 입력값을 유지하고 사용자가 선택할 때만 새로 불러온다", async () => {
    const user = userEvent.setup();
    apiSave.mockRejectedValueOnce(
      new ApiError(
        409,
        "baseline_revision_conflict",
        "private server message",
      ),
    );
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");

    await user.clear(input);
    await user.type(input, "6100");
    await user.click(screen.getByRole("button", { name: "변경 내용 저장" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "다른 화면에서 기준이 변경됐어요. 최신 내용을 확인한 뒤 다시 저장해 주세요.",
    );
    expect(input).toHaveValue("6100");

    await user.click(screen.getByRole("button", { name: "새로 불러오기" }));
    expect(await screen.findByLabelText("일반암 진단비 기준금액")).toHaveValue(
      "3000",
    );
  });

  it("저장 중에는 편집 입력과 화면 동작을 비활성화한다", async () => {
    const user = userEvent.setup();
    const pending = deferred<{ revision: number }>();
    apiSave.mockReturnValueOnce(pending.promise);
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");

    await user.clear(input);
    await user.type(input, "4500");
    await user.click(screen.getByRole("button", { name: "변경 내용 저장" }));

    expect(input).toBeDisabled();
    expect(screen.getByRole("searchbox", { name: "담보 검색" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "입력한 담보만" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "저장 중" })).toBeDisabled();

    await act(async () => pending.resolve({ revision: 4 }));
  });

  it("검색 결과와 입력한 담보가 없을 때 각각 다음 행동을 안내한다", async () => {
    const user = userEvent.setup();
    render(<BaselineSettingsPage />);
    const search = await screen.findByRole("searchbox", { name: "담보 검색" });

    await user.type(search, "없는 담보");
    expect(await screen.findByText("검색 결과가 없어요.")).toBeInTheDocument();

    await user.clear(search);
    apiGet.mockResolvedValueOnce({
      ...structuredClone(catalog),
      categories: [
        {
          ...structuredClone(catalog.categories[0]),
          subcategories: [
            {
              ...structuredClone(catalog.categories[0].subcategories[0]),
              details: catalog.categories[0].subcategories[0].details.map(
                (detail) => ({ ...structuredClone(detail), baselines: [] }),
              ),
            },
          ],
        },
      ],
    });
    await user.click(screen.getByRole("button", { name: "새로 고침" }));
    await user.click(screen.getByRole("checkbox", { name: "입력한 담보만" }));
    expect(screen.getByText("입력한 담보가 없어요.")).toBeInTheDocument();
  });

  it("저장하지 않은 변경이 있으면 브라우저 이탈을 경고한다", async () => {
    const user = userEvent.setup();
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");
    await user.clear(input);
    await user.type(input, "4500");

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
  });

  it("저장하지 않은 변경은 공통 내비게이션 링크도 취소하거나 허용할 수 있다", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm");
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");
    await user.clear(input);
    await user.type(input, "4500");
    const link = screen.getByRole("link", { name: "대시보드로 이동" });

    confirm.mockReturnValueOnce(false);
    const canceled = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      button: 0,
    });
    link.dispatchEvent(canceled);
    expect(canceled.defaultPrevented).toBe(true);

    confirm.mockReturnValueOnce(true);
    let guardPreventedAllowedNavigation = true;
    link.addEventListener(
      "click",
      (event) => {
        guardPreventedAllowedNavigation = event.defaultPrevented;
        event.preventDefault();
      },
      { once: true },
    );
    const allowed = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      button: 0,
    });
    link.dispatchEvent(allowed);
    expect(guardPreventedAllowedNavigation).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(2);

    const followupUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(followupUnload);
    expect(followupUnload.defaultPrevented).toBe(false);
  });

  it("뒤로가기를 취소하면 현재 주소를 복원하고 확인을 반복하지 않는다", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");
    await user.clear(input);
    await user.type(input, "4500");

    window.history.replaceState({}, "", "/dashboard");
    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(window.location.pathname).toBe("/settings/baseline");
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("dirty 상태의 Manager 프로그램 이동도 취소하거나 한 번의 확인으로 허용한다", async () => {
    const user = userEvent.setup();
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");
    await user.clear(input);
    await user.type(input, "4500");
    const managerNavigation = screen.getByRole("button", {
      name: "Manager 팀 현황 보기",
    });

    await user.click(managerNavigation);
    expect(navigationMocks.programmaticNavigate).not.toHaveBeenCalled();
    expect(input).toHaveValue("4500");

    await user.click(managerNavigation);
    expect(navigationMocks.programmaticNavigate).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("변경 중 새로고침 실패 뒤 다시 시도도 확인하며 취소하면 입력을 보존한다", async () => {
    const user = userEvent.setup();
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);
    apiGet
      .mockResolvedValueOnce(structuredClone(catalog))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(structuredClone(catalog));
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");
    await user.clear(input);
    await user.type(input, "6200");

    await user.click(screen.getByRole("button", { name: "새로 고침" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "최신 담보 기준을 불러오지 못했어요.",
    );
    expect(input).toHaveValue("6200");

    await user.click(screen.getByRole("button", { name: "다시 불러오기" }));
    expect(apiGet).toHaveBeenCalledTimes(2);
    expect(input).toHaveValue("6200");
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("잘못된 금액은 저장하지 않고 입력 필드에 오류 설명을 연결한다", async () => {
    const user = userEvent.setup();
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");

    await user.clear(input);
    await user.type(input, "-1");
    await user.click(screen.getByRole("button", { name: "변경 내용 저장" }));

    expect(apiSave).not.toHaveBeenCalled();
    expect(input).toHaveAttribute("aria-invalid", "true");
    const describedBy = input.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)).toHaveTextContent(
      "0 이상의 숫자를 입력해 주세요.",
    );
  });

  it("정수부 13자리는 API 전에 막고 같은 입력에 오류를 연결한다", async () => {
    const user = userEvent.setup();
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");

    await user.clear(input);
    await user.type(input, "1234567890123");
    await user.click(screen.getByRole("button", { name: "변경 내용 저장" }));

    expect(apiSave).not.toHaveBeenCalled();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(
      document.getElementById(input.getAttribute("aria-describedby")!),
    ).toHaveTextContent("정수 부분은 12자리까지 입력해 주세요.");
  });

  it("좁은 데스크톱 폭에서는 카드이고 lg부터 표로 전환한다", async () => {
    render(<BaselineSettingsPage />);
    const input = await screen.findByLabelText("일반암 진단비 기준금액");
    const table = input.closest("table");

    expect(table).toHaveClass("lg:table");
    expect(table).not.toHaveClass("sm:table");
  });
});
