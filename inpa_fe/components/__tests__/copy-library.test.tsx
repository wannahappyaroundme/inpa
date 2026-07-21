import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { COPY_CATEGORIES, renderCopy } from "@/lib/copy-library";

const copyGuard = require("../../scripts/check-copy.js") as {
  scanCopy: () => { files: string[]; violations: unknown[] };
  stripComments: (source: string) => string;
};

describe("copy library honesty guard", () => {
  it("keeps rendered templates free of fake contacts and overpromising wording", () => {
    const renderedCopy = COPY_CATEGORIES
      .flatMap((category) => [
        category.label,
        category.desc,
        ...category.templates.flatMap((template) => [template.title, renderCopy(template.body, {})]),
      ])
      .join("\n");

    expect(renderedCopy).not.toMatch(/080-[0-9]/);
    expect(renderedCopy).not.toMatch(/부담 없이|무조건|확실한|보장됩니다/);
  });

  it("scans rendered copy-library strings while excluding comments", () => {
    const source = readFileSync(join(process.cwd(), "lib/copy-library.ts"), "utf8");
    expect(source).toContain("COPY_CATEGORIES");
    expect(copyGuard.stripComments("// 부담 없이\nconst copy = '다음 행동';")).not.toMatch(/부담 없이/);
    expect(copyGuard.stripComments('const copy = "https://example.test// 부담 없이";')).toContain("부담 없이");
    expect(copyGuard.stripComments("const copy = `표시 /* 부담 없이 */`;"))
      .toContain("부담 없이");

    const nestedTemplate = "const rendered = `outer ${`inner // 부담 없이`}`;";
    expect(copyGuard.stripComments(nestedTemplate)).toContain("부담 없이");
    const expressionComment = "const rendered = `outer ${value /* 부담 없이 */}`;";
    expect(copyGuard.stripComments(expressionComment)).not.toMatch(/부담 없이/);
    const nestedBlockMarker = "const rendered = `outer ${`inner /* 부담 없이 */`}`;";
    expect(copyGuard.stripComments(nestedBlockMarker)).toContain("부담 없이");

    const result = copyGuard.scanCopy();
    expect(result.files).toContain("lib/copy-library.ts");
    expect(result.violations).toEqual([]);
  });
});
