import { useRef, useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BaselineDetailDrawer } from "@/components/baseline-detail-drawer";
import type {
  BaselineDraftDetail,
  BaselineDraftScope,
} from "@/lib/baseline-editor";

const defaultScope: BaselineDraftScope = {
  analysis_detail_id: 101,
  product_group: 0,
  age_band: "all",
  gender: null,
  recommend_min: "3000",
  recommend_max: null,
  unit: 1,
  baseline_source: "planner",
  is_stored: true,
};

const exceptionScope: BaselineDraftScope = {
  analysis_detail_id: 101,
  product_group: 1,
  age_band: "30s",
  gender: 1,
  recommend_min: "5000",
  recommend_max: "7000",
  unit: 1,
  baseline_source: "planner",
  is_stored: true,
};

const detail: BaselineDraftDetail = {
  id: 101,
  name: "일반암 진단비",
  order: 1,
  unit: 1,
  baselines: [defaultScope, exceptionScope],
};

function DrawerHarness() {
  const [open, setOpen] = useState(false);
  const [currentDetail, setCurrentDetail] = useState(detail);
  const openerRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={openerRef} type="button" onClick={() => setOpen(true)}>
        상세 설정
      </button>
      <BaselineDetailDrawer
        open={open}
        detail={currentDetail}
        onClose={() => setOpen(false)}
        onScopeChange={(original, next) => {
          setCurrentDetail((current) => ({
            ...current,
            baselines: next
              ? current.baselines.map((scope) =>
                  scope === original ? next : scope,
                )
              : current.baselines.filter((scope) => scope !== original),
          }));
        }}
        onAddScope={(scope) =>
          setCurrentDetail((current) => ({
            ...current,
            baselines: [...current.baselines, scope],
          }))
        }
      />
    </>
  );
}

describe("담보 상세 기준 드로어", () => {
  it("대화상자 제목과 모든 범위·금액 입력을 제공하고 처음 닫기 버튼에 초점을 둔다", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);

    const opener = screen.getByRole("button", { name: "상세 설정" });
    await user.click(opener);

    const dialog = screen.getByRole("dialog", {
      name: "일반암 진단비 상세 설정",
    });
    expect(within(dialog).getAllByLabelText("상품 범위")).toHaveLength(2);
    expect(within(dialog).getAllByLabelText("연령")).toHaveLength(2);
    expect(within(dialog).getAllByLabelText("성별")).toHaveLength(2);
    expect(within(dialog).getAllByLabelText("기준금액")).toHaveLength(2);
    expect(within(dialog).getAllByLabelText("넉넉 기준금액")).toHaveLength(2);
    expect(within(dialog).getByRole("button", { name: "닫기" })).toHaveFocus();
  });

  it("Tab 초점을 대화상자 안에 가두고 Escape 뒤 호출 버튼으로 돌려보낸다", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);

    const opener = screen.getByRole("button", { name: "상세 설정" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog");
    const close = within(dialog).getByRole("button", { name: "닫기" });

    close.focus();
    await user.tab({ shift: true });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("기존 상세값 지우기는 해당 범위를 null로 전달한다", async () => {
    const user = userEvent.setup();
    const onScopeChange = vi.fn();
    render(
      <BaselineDetailDrawer
        open
        detail={detail}
        onClose={vi.fn()}
        onScopeChange={onScopeChange}
        onAddScope={vi.fn()}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "생명 30대 남성 상세값 지우기" }),
    );

    expect(onScopeChange).toHaveBeenCalledWith(exceptionScope, null);
  });

  it("이전 기준을 확인한 뒤 내 기준으로 사용하도록 전환한다", async () => {
    const user = userEvent.setup();
    const presetScope = { ...defaultScope, baseline_source: "preset" };
    const onScopeChange = vi.fn();
    render(
      <BaselineDetailDrawer
        open
        detail={{ ...detail, baselines: [presetScope, exceptionScope] }}
        onClose={vi.fn()}
        onScopeChange={onScopeChange}
        onAddScope={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        "이 금액을 확인한 뒤 내 기준으로 사용하면 분석에 반영돼요.",
      ),
    ).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "내 기준으로 사용" }));
    expect(onScopeChange).toHaveBeenCalledWith(
      presetScope,
      expect.objectContaining({ baseline_source: "planner" }),
    );
  });

  it("출처 없는 저장 기준도 확인한 뒤 내 기준으로 사용하도록 전환한다", async () => {
    const user = userEvent.setup();
    const linkedScope = { ...defaultScope, baseline_source: null };
    const onScopeChange = vi.fn();
    render(
      <BaselineDetailDrawer
        open
        detail={{ ...detail, baselines: [linkedScope, exceptionScope] }}
        onClose={vi.fn()}
        onScopeChange={onScopeChange}
        onAddScope={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        "이 금액을 확인한 뒤 내 기준으로 사용하면 분석에 반영돼요.",
      ),
    ).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "내 기준으로 사용" }));
    expect(onScopeChange).toHaveBeenCalledWith(
      linkedScope,
      expect.objectContaining({ baseline_source: "planner" }),
    );
  });

  it("새 빈 기준은 직접 입력만 할 수 있다", () => {
    const emptyScope = {
      ...defaultScope,
      recommend_min: null,
      baseline_source: null,
      is_stored: false,
    };
    render(
      <BaselineDetailDrawer
        open
        detail={{ ...detail, baselines: [emptyScope, exceptionScope] }}
        onClose={vi.fn()}
        onScopeChange={vi.fn()}
        onAddScope={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "내 기준으로 사용" }),
    ).toBeNull();
  });

  it("실손과 연금저축 범위를 기존 값으로 표시하고 새 범위로 선택할 수 있다", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await user.click(screen.getByRole("button", { name: "상세 설정" }));

    const productSelects = screen.getAllByLabelText("상품 범위");
    expect(
      within(productSelects[1]).getByRole("option", { name: "실손" }),
    ).toBeInTheDocument();
    expect(
      within(productSelects[1]).getByRole("option", { name: "연금저축" }),
    ).toBeInTheDocument();
  });

  it("기존 실손·연금저축 상세값을 표시하고 각각 편집·삭제할 수 있다", async () => {
    const user = userEvent.setup();
    const indemnity = {
      ...exceptionScope,
      product_group: 3 as const,
    };
    const annuity = {
      ...exceptionScope,
      product_group: 4 as const,
      age_band: "40s" as const,
    };
    const onScopeChange = vi.fn();
    render(
      <BaselineDetailDrawer
        open
        detail={{ ...detail, baselines: [defaultScope, indemnity, annuity] }}
        onClose={vi.fn()}
        onScopeChange={onScopeChange}
        onAddScope={vi.fn()}
      />,
    );

    const indemnityRegion = screen.getByRole("region", {
      name: "실손 30대 남성",
    });
    fireEvent.change(
      within(indemnityRegion).getByLabelText("기준금액"),
      { target: { value: "8100" } },
    );
    expect(onScopeChange).toHaveBeenCalledWith(
      indemnity,
      expect.objectContaining({ product_group: 3, recommend_min: "8100" }),
    );

    await user.click(
      screen.getByRole("button", {
        name: "연금저축 40대 남성 상세값 지우기",
      }),
    );
    expect(onScopeChange).toHaveBeenCalledWith(annuity, null);
  });

  it("상품·연령·성별을 바꿔도 편집 중인 선택 필드의 초점을 유지한다", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await user.click(screen.getByRole("button", { name: "상세 설정" }));

    let exception = screen.getByRole("region", {
      name: "생명 30대 남성",
    });
    let product = within(exception).getByLabelText("상품 범위");
    await user.selectOptions(product, "2");
    expect(product).toHaveFocus();

    exception = screen.getByRole("region", { name: "손해 30대 남성" });
    const age = within(exception).getByLabelText("연령");
    await user.selectOptions(age, "40s");
    expect(age).toHaveFocus();

    exception = screen.getByRole("region", { name: "손해 40대 남성" });
    const gender = within(exception).getByLabelText("성별");
    await user.selectOptions(gender, "2");
    expect(gender).toHaveFocus();
  });

  it("상세 금액 오류를 각 입력에 접근 가능한 설명으로 연결한다", () => {
    render(
      <BaselineDetailDrawer
        open
        detail={detail}
        errors={{
          "101:1:30s:1": {
            recommend_min: "0 이상의 숫자를 입력해 주세요.",
            recommend_max:
              "넉넉 기준금액은 기준금액 이상으로 입력해 주세요.",
          },
        }}
        onClose={vi.fn()}
        onScopeChange={vi.fn()}
        onAddScope={vi.fn()}
      />,
    );

    const exception = screen.getByRole("region", {
      name: "생명 30대 남성",
    });
    const minimum = within(exception).getByLabelText("기준금액");
    const maximum = within(exception).getByLabelText("넉넉 기준금액");
    expect(minimum).toHaveAttribute("aria-invalid", "true");
    expect(maximum).toHaveAttribute("aria-invalid", "true");
    expect(
      document.getElementById(minimum.getAttribute("aria-describedby")!),
    ).toHaveTextContent("0 이상의 숫자를 입력해 주세요.");
    expect(
      document.getElementById(maximum.getAttribute("aria-describedby")!),
    ).toHaveTextContent(
      "넉넉 기준금액은 기준금액 이상으로 입력해 주세요.",
    );
  });
});
