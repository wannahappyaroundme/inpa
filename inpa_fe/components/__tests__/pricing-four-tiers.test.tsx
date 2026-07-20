import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { PricingFourTiers } from "@/components/brand-story-sections";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getBillingEvent: vi.fn().mockResolvedValue({ first_paid_bonus_enabled: false }),
}));

it("공용 4단 요금표는 앵커와 UTM 가입 주소를 받는다", () => {
  render(
    <PricingFourTiers
      id="pricing"
      registerHref="https://www.inpa.kr/register?utm_source=nav"
    />,
  );

  expect(document.querySelector("#pricing")).toBeInTheDocument();
  expect(screen.getByText("Manager")).toBeInTheDocument();
  expect(screen.getByText("Plus")).toBeInTheDocument();
  expect(screen.getByText("Super")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "무료로 시작하기" })).toHaveAttribute(
    "href",
    "https://www.inpa.kr/register?utm_source=nav",
  );
});
