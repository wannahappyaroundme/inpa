import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { PricingFourTiers } from "@/components/brand-story-sections";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getBillingEvent: vi.fn().mockResolvedValue({ first_paid_bonus_enabled: false }),
}));

it("요금표는 Manager를 별도 결제 카드로 만들지 않고 Plus 역할로 안내한다", () => {
  render(
    <PricingFourTiers
      id="pricing"
      registerHref="https://www.inpa.kr/register?utm_source=nav"
    />,
  );

  expect(document.querySelector("#pricing")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "인파 요금제" })).toBeInTheDocument();
  expect(screen.queryByText("Manager", { selector: "span" })).not.toBeInTheDocument();
  expect(screen.queryByText("관리자 전용")).not.toBeInTheDocument();
  expect(screen.getByText("Plus")).toBeInTheDocument();
  expect(screen.getByText("Super")).toBeInTheDocument();
  expect(
    screen.getByText("첫 설계사 합류 시 Manager 역할 자동 활성화"),
  ).toBeInTheDocument();
  expect(screen.getByText("팀원과 팀 전체 흐름 관리")).toBeInTheDocument();
  expect(screen.getAllByText("19,900원")).toHaveLength(1);
  expect(screen.getByRole("link", { name: "무료로 시작하기" })).toHaveAttribute(
    "href",
    "https://www.inpa.kr/register?utm_source=nav",
  );
});
