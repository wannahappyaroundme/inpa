import { describe, expect, it } from "vitest";

import type { PersonalTalkTemplate } from "@/lib/api";
import type { CopyCategory } from "@/lib/copy-library";
import {
  buildTalkTemplateView,
  createPersonalPayloadFromDefault,
  filterTalkTemplates,
  substituteTalkTemplate,
} from "@/lib/talk-template-view-model";

const defaults: CopyCategory[] = [
  {
    key: "first",
    label: "첫 분류",
    desc: "첫 분류 설명",
    templates: [
      {
        key: "first-a",
        title: "첫 기본",
        body: "{고객명} 고객님, {설계사명}입니다. 확인할까요?",
        channel: "message",
        isAdvertising: true,
      },
      {
        key: "first-b",
        title: "숨길 기본",
        body: "{고객명} 고객님, 통화로 확인할까요?",
        channel: "call",
      },
    ],
  },
  {
    key: "second",
    label: "둘째 분류",
    desc: "둘째 분류 설명",
    templates: [
      {
        key: "second-a",
        title: "둘째 기본",
        body: "{고객명} 고객님, 다음 항목을 선택해 주세요.",
        channel: "message",
      },
    ],
  },
];

function personal(
  id: number,
  overrides: Partial<PersonalTalkTemplate> = {},
): PersonalTalkTemplate {
  return {
    id,
    owner: 10,
    source_key: null,
    title: `개인 ${id}`,
    body: "{고객명} 고객님, 개인 문구를 확인해 주세요.",
    category: "first",
    channel: "message",
    sort_order: 10,
    is_active: true,
    is_deleted: false,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
    ...overrides,
  };
}

describe("talk template view model", () => {
  it("combines visible defaults and personal rows while exposing hidden defaults for recovery", () => {
    const view = buildTalkTemplateView({
      categories: defaults,
      personalTemplates: [
        personal(8, { title: "동순위 뒤", sort_order: 20 }),
        personal(3, { title: "동순위 앞", sort_order: 20 }),
        personal(11, { title: "둘째 개인", category: "second", sort_order: -1 }),
      ],
      hiddenSourceKeys: ["first-b"],
    });

    expect(view.visible.map((item) => item.viewKey)).toEqual([
      "default:first-a",
      "personal:3",
      "personal:8",
      "default:second-a",
      "personal:11",
    ]);
    expect(view.hiddenDefaults.map((item) => item.sourceKey)).toEqual([
      "first-b",
    ]);
  });

  it("orders unknown personal categories after known categories with a stable id tie-break", () => {
    const view = buildTalkTemplateView({
      categories: defaults,
      personalTemplates: [
        personal(9, { category: "custom", sort_order: 1 }),
        personal(4, { category: "custom", sort_order: 1 }),
      ],
      hiddenSourceKeys: [],
    });

    expect(view.visible.slice(-2).map((item) => item.viewKey)).toEqual([
      "personal:4",
      "personal:9",
    ]);
    expect(view.visible.at(-1)?.categoryLabel).toBe("custom");
  });

  it("keeps the advertising gate on a personal copy through its source key", () => {
    const copied = buildTalkTemplateView({
      categories: defaults,
      personalTemplates: [
        personal(12, { source_key: "first-a" }),
      ],
      hiddenSourceKeys: [],
    }).visible.find((item) => item.viewKey === "personal:12");

    expect(copied?.isAdvertising).toBe(true);
  });

  it("builds a personal payload from a default without substituting placeholders", () => {
    const source = buildTalkTemplateView({
      categories: defaults,
      personalTemplates: [],
      hiddenSourceKeys: [],
    }).visible[0];

    expect(createPersonalPayloadFromDefault(source)).toEqual({
      source_key: "first-a",
      title: "첫 기본",
      body: "{고객명} 고객님, {설계사명}입니다. 확인할까요?",
      category: "first",
      channel: "message",
      sort_order: 0,
      is_active: true,
    });
  });

  it("substitutes customer and profile data into a new string without mutating the stored body", () => {
    const stored =
      "{고객명} 고객님, {소속직책} {설계사명}입니다. 문의: {설계사연락처}\n수신거부: {수신거부안내}";

    const rendered = substituteTalkTemplate(stored, {
      customer: "김고객",
      planner: "박설계",
      affiliation: "인파지점",
      title: "팀장",
      phone: "프로필전화",
      optOut: "직접입력안내",
    });

    expect(rendered).toBe(
      "김고객 고객님, 인파지점 팀장 박설계입니다. 문의: 프로필전화\n수신거부: 직접입력안내",
    );
    expect(stored).toContain("{고객명}");
    expect(rendered).not.toBe(stored);
  });

  it("filters all, personal, and default views without changing their order", () => {
    const visible = buildTalkTemplateView({
      categories: defaults,
      personalTemplates: [personal(2)],
      hiddenSourceKeys: [],
    }).visible;

    expect(filterTalkTemplates(visible, "all")).toEqual(visible);
    expect(
      filterTalkTemplates(visible, "personal").map((item) => item.viewKey),
    ).toEqual(["personal:2"]);
    expect(
      filterTalkTemplates(visible, "default").map((item) => item.viewKey),
    ).toEqual(["default:first-a", "default:first-b", "default:second-a"]);
  });
});
