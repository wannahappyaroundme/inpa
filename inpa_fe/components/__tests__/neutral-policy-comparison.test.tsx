import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { CompareBarChart } from "@/components/charts";
import { ComparePremiumSplit } from "@/components/premium-split";
import type { CompareResponse, CompareSide } from "@/lib/api";
import { buildCompareExportText } from "@/lib/compare-export";
import { compareMock } from "@/lib/mock";

const side = (monthly: number): CompareSide => ({
  monthly_premiums: monthly,
  total_premiums: monthly * 120,
  monthly_renewal_premium: monthly,
  monthly_non_renewal_premium: 0,
  monthly_earned_premium: 0,
  total_renewal_premium: monthly * 120,
  total_non_renewal_premium: 0,
  total_earned_premium: 0,
  insurances: [],
});

describe("neutral multi-policy comparison copy", () => {
  it("announces comparison bars as policy A and policy B", () => {
    render(<CompareBarChart items={[{ label: "암 진단비", current: 10, proposed: 20 }]} />);

    const chart = screen.getByRole("img");
    expect(chart.getAttribute("aria-label")).toContain("증권 A 10 증권 B 20");
    expect(chart.getAttribute("aria-label")).not.toMatch(/기존|제안/);
  });

  it("uses policy A and policy B as the premium table defaults", () => {
    const { container } = render(<ComparePremiumSplit current={side(87_000)} proposed={side(93_000)} />);

    expect(screen.getByText("증권 A")).toBeTruthy();
    expect(screen.getByText("증권 B")).toBeTruthy();
    expect(screen.queryByText("현재")).toBeNull();
    expect(screen.queryByText("제안")).toBeNull();
    expect(container.innerHTML).not.toMatch(/emerald|rose|text-enough|text-short/);
    expect(screen.queryByText(/AI가 정리한 참고 자료/)).toBeNull();
  });

  it("keeps demo products and copied text neutral", () => {
    const response: CompareResponse = {
      mode: "neutral",
      current: side(87_000),
      proposed: side(93_000),
      rows: [{ coverage: "암 진단비", current_amount: 30_000_000, proposed_amount: 50_000_000, delta: 20_000_000 }],
      comparison_source: "deterministic",
      switch_warnings: [],
      guide_draft: null,
      guide_enabled: false,
      guide_source: null,
      publishable: false,
      publish_blocked_reason: "",
      disclaimer: "인파가 등록된 보장 정보를 정리한 참고 자료입니다.",
    };
    const copy = buildCompareExportText(response, "증권 A", "증권 B");

    expect(compareMock.current.product).toMatch(/^증권 A/);
    expect(compareMock.proposed.product).toMatch(/^증권 B/);
    expect(copy).toContain("증권 A");
    expect(copy).toContain("증권 B");
    expect(copy).not.toMatch(/현재와 제안|갈아타기|승환|비교안내서/);
  });

  it("shows an AI notice only when a guide response exists", () => {
    const customerPage = readFileSync(join(process.cwd(), "app/customer/[id]/page.tsx"), "utf8");

    expect(customerPage).toContain("data.guide_enabled && data.guide_draft");
    expect(customerPage).toContain("AI가 정리한 참고 자료");
  });
});
