import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

describe("customer analysis toolbar", () => {
  it("uses a stable three-column mobile layout without breaking Korean labels", () => {
    const source = readFileSync(
      join(process.cwd(), "app/customer/[id]/page.tsx"),
      "utf8",
    );
    const toolbarStart = source.indexOf("담보 한눈표 · 설계사 도구");
    const toolbarSource = source.slice(toolbarStart, toolbarStart + 3_000);
    const actionClasses = toolbarSource.match(/<div className="([^"]+)">\s*<button/)?.[1];

    expect(toolbarStart).toBeGreaterThanOrEqual(0);
    expect(actionClasses).toContain("grid-cols-3");
    expect(actionClasses).toContain("sm:flex");
    expect(actionClasses).toContain("[&_button]:whitespace-nowrap");
    expect(actionClasses).toContain("[&_label]:whitespace-nowrap");
  });
});
