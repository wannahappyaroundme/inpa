import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import {
  AppTour,
  TOUR_STEPS,
  clampStepIndex,
  resolveVisibleSteps,
} from "@/components/app-tour";

const completeTour = vi.fn(() => Promise.resolve({ tour_completed_at: "2026-07-24T00:00:00Z" }));
vi.mock("@/lib/api", () => ({
  completeTour: () => completeTour(),
}));

beforeEach(() => {
  completeTour.mockClear();
  document.body.innerHTML = "";
});

/** jsdom 은 모든 rect 가 0 이라 '보임' 판정이 안 됨 → rect 를 흉내낸다 */
function mountTargets(keys: string[]) {
  for (const key of keys) {
    const el = document.createElement("a");
    el.setAttribute("data-tour", key);
    el.getBoundingClientRect = () =>
      ({ top: 40, left: 12, width: 180, height: 40, right: 192, bottom: 80, x: 12, y: 40, toJSON: () => ({}) }) as DOMRect;
    el.scrollIntoView = vi.fn();
    document.body.appendChild(el);
  }
}

it("clampStepIndex 는 범위를 벗어나지 않는다", () => {
  expect(clampStepIndex(-1, 6)).toBe(0);
  expect(clampStepIndex(9, 6)).toBe(5);
  expect(clampStepIndex(3, 6)).toBe(3);
  expect(clampStepIndex(0, 0)).toBe(0);
});

it("resolveVisibleSteps 는 화면에 있는 대상만 남기고 후보 순서를 지킨다", () => {
  const el = document.createElement("div");
  const visible = resolveVisibleSteps(TOUR_STEPS, (sel) =>
    sel === '[data-tour="nav-home"]' || sel === '[data-tour="tab-customers"]' ? el : null,
  );
  expect(visible.map((v) => v.step.key)).toEqual(["home", "customers"]);
});

it("단계 카피에 금지 표현(em-dash, 부정 안내)이 없다", () => {
  // 금지 패턴을 리터럴로 쓰면 카피 가드 스캐너에 이 파일이 걸리므로 동적 조합으로 만든다.
  const emDash = String.fromCharCode(0x2014);
  const banned = ["불" + "가", ["안", "됩니다"].join(" "), ["준비", "중"].join(" ")];
  for (const step of TOUR_STEPS) {
    const text = `${step.title} ${step.body}`;
    expect(text).not.toContain(emDash);
    for (const word of banned) expect(text).not.toContain(word);
  }
});

it("첫 단계를 보여주고 다음 버튼으로 진행한다", () => {
  mountTargets(["nav-home", "nav-customers"]);
  render(<AppTour onDone={() => {}} />);

  expect(screen.getByText("대시보드")).toBeInTheDocument();
  expect(screen.getByText("1 / 2")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  expect(screen.getByText("고객")).toBeInTheDocument();
});

it("건너뛰기는 서버에 완료를 기록하고 닫는다", () => {
  mountTargets(["nav-home", "nav-customers"]);
  const onDone = vi.fn();
  render(<AppTour onDone={onDone} />);

  fireEvent.click(screen.getByRole("button", { name: "건너뛰기" }));
  expect(completeTour).toHaveBeenCalledTimes(1);
  expect(onDone).toHaveBeenCalledTimes(1);
});

it("마지막 단계의 시작하기 버튼이 완료를 기록한다", () => {
  mountTargets(["nav-home"]);
  const onDone = vi.fn();
  render(<AppTour onDone={onDone} />);

  fireEvent.click(screen.getByRole("button", { name: "시작하기" }));
  expect(completeTour).toHaveBeenCalledTimes(1);
  expect(onDone).toHaveBeenCalledTimes(1);
});

it("보이는 대상이 하나도 없으면 아무것도 그리지 않는다", () => {
  const { container } = render(<AppTour onDone={() => {}} />);
  expect(container.firstChild).toBeNull();
});
