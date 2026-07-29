import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatCard } from "@/components/ui";

describe("StatCard responsive value layout", () => {
  it("keeps the value and unit on one line and scales the value within the approved range", () => {
    render(
      <StatCard
        label="이번 달 보험료"
        value="182만"
        unit="원"
      />,
    );

    const value = screen.getByText("182만");

    expect(value.parentElement?.parentElement).toHaveClass(
      "[container-type:inline-size]",
    );
    expect(value.parentElement).toHaveClass("whitespace-nowrap");
    expect(value).toHaveStyle({
      fontSize: "clamp(16px, 22cqw, 28px)",
    });
  });
});
