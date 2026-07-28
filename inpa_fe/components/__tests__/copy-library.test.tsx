import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { COPY_CATEGORIES, renderCopy } from "@/lib/copy-library";

const copyGuard = require("../../scripts/check-copy.js") as {
  scanCopy: () => { files: string[]; violations: unknown[] };
  stripComments: (source: string, context?: string) => string;
};

const forbiddenClaims = [
  "마음에 걸리는",
  "편하실 때",
  "천천히 생각",
  "결정은 고객님 몫",
  "보험료를 아낀 분도 많아요",
  "받을 수 있는 돈",
  "어느 쪽이 유리",
  "예전 상품엔 약한",
  "굳이 바꿀 필요 없어",
  "뭘 권하려는 건 아니고",
];

const unverifiedGenericClaims = [
  "무료",
  "객관적으로",
  "정확히 봐",
  "보장 공백",
];

describe("copy library honesty guard", () => {
  const defaults = COPY_CATEGORIES.flatMap((category, categoryOrder) =>
    category.templates.map((template, defaultOrder) => ({
      ...template,
      categoryKey: category.key,
      categoryOrder,
      defaultOrder,
    })),
  );

  it("keeps exactly 30 complete defaults with unique stable keys", () => {
    expect(defaults).toHaveLength(30);
    expect(new Set(defaults.map((template) => template.key))).toHaveLength(30);
    for (const template of defaults) {
      expect(template.key).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
      expect(template.title.trim()).not.toBe("");
      expect(template.body.trim()).not.toBe("");
      expect(["message", "call"]).toContain(template.channel);
    }
  });

  it("asks a real next action without passive or unsupported claims", () => {
    const bodies = defaults.map((template) => template.body).join("\n");
    for (const phrase of [...forbiddenClaims, ...unverifiedGenericClaims]) {
      expect(bodies).not.toContain(phrase);
    }
    for (const template of defaults) {
      expect(template.body).toMatch(/[?？]|확인|선택|진행|예약|준비|보내/);
    }
    expect(bodies).not.toMatch(
      /오늘 저녁|내일 점심|이번 주 목요일|금요일 오전/,
    );
    expect(bodies).not.toContain("10분 안에");
    expect(bodies).not.toContain("어제 인사드린");
    expect(bodies).not.toContain("[링크]");
    expect(
      defaults.find((template) => template.key === "result-share")?.title,
    ).not.toContain("링크");
  });

  it("keeps rendered templates free of fake contacts and overpromising wording", () => {
    const renderedCopy = COPY_CATEGORIES
      .flatMap((category) => [
        category.label,
        category.desc,
        ...category.templates.flatMap((template) => [template.title, renderCopy(template.body, {})]),
      ])
      .join("\n");

    expect(renderedCopy).not.toMatch(/(?:01[016789]|02|0[3-6][1-5]|070|080)[-\s]?\d{3,4}[-\s]?\d{4}/);
    expect(renderedCopy).not.toMatch(/080-[0-9]/);
    expect(renderedCopy).not.toMatch(/부담 없이|무조건|확실한|보장됩니다/);
  });

  it("marks advertising defaults and requires real contact placeholders", () => {
    const advertising = defaults.filter((template) => template.isAdvertising);
    expect(advertising).toHaveLength(1);
    expect(advertising[0].channel).toBe("message");
    expect(advertising[0].body).toContain("{설계사연락처}");
    expect(advertising[0].body).toContain("{수신거부안내}");
  });

  it("does not leave doubled spaces when optional affiliation and title are empty", () => {
    expect(
      renderCopy(
        "안녕하세요. {소속직책} {설계사명}입니다.",
        { planner: "황예진" },
      ),
    ).toBe("안녕하세요. 황예진입니다.");
  });

  it("renders all 30 defaults as complete Korean sentences when every variable is empty", () => {
    const emptyVariables = {
      customer: "",
      planner: "",
      affiliation: "",
      title: "",
      phone: "",
      optOut: "",
    };
    const rendered = defaults.map((template) => ({
      key: template.key,
      body: renderCopy(template.body, emptyVariables),
    }));

    expect(rendered).toHaveLength(30);
    for (const template of rendered) {
      expect(template.body, template.key).not.toContain("고객 고객님");
      expect(template.body, template.key).not.toContain("{고객명}");
      expect(template.body, template.key).not.toMatch(/(^|[\s(])님[,.\s]/);
      expect(template.body, template.key).not.toMatch(
        /(?:^|\s)(?:은|는|이|가|을|를|으로|로|에서|의)(?=\s|[,.!?]|$)/,
      );
      expect(template.body, template.key).not.toMatch(
        /(안녕하세요[,.!?]?\s*){2,}/,
      );
      expect(template.body, template.key).not.toMatch(/[,.!?]{2,}/);
      expect(template.body, template.key).not.toMatch(/[ \t]{2,}/);
      expect(template.body, template.key).not.toMatch(/\{[^{}]+\}/);
    }
    expect(rendered.find((template) => template.key === "referral-thanks")?.body)
      .toMatch(/^고객님,/);
    expect(rendered.find((template) => template.key === "prospect-acquaintance")?.body)
      .toMatch(/^안녕하세요,/);
  });

  it("preserves real customer and planner details in the two empty-value boundary templates", () => {
    const variables = {
      customer: "김인파",
      planner: "황예진",
      affiliation: "인파지점",
      title: "팀장",
      phone: "010-9876-5432",
      optOut: "이 번호로 거부 의사를 알려 주세요",
    };
    const byKey = new Map(
      defaults.map((template) => [
        template.key,
        renderCopy(template.body, variables),
      ]),
    );

    expect(byKey.get("prospect-card")).toContain("김인파");
    expect(byKey.get("prospect-card")).toContain("인파지점 팀장 황예진");
    expect(byKey.get("prospect-longtime")).toContain("김인파");
    expect(byKey.get("prospect-longtime")).toContain(
      "현재 인파지점 팀장으로 일하며",
    );
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

  it("fails closed when TypeScript source cannot be parsed", () => {
    expect(() => copyGuard.stripComments("const incomplete = (", "fixtures/broken.tsx"))
      .toThrow(/카피 검사 파싱 오류.*fixtures\/broken\.tsx/);
    expect(() => copyGuard.stripComments("const incomplete = `outer ${value", "fixtures/broken-template.tsx"))
      .toThrow(/카피 검사 파싱 오류.*fixtures\/broken-template\.tsx/);
  });
});
