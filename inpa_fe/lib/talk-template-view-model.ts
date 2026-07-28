import type {
  PersonalTalkTemplate,
  PersonalTalkTemplatePayload,
  TalkTemplateChannel,
} from "@/lib/api";
import {
  renderCopy,
  type CopyCategory,
  type CopyVariables,
} from "@/lib/copy-library";

export type TalkTemplateKind = "default" | "personal";
export type TalkTemplateFilter = "all" | TalkTemplateKind;

export interface TalkTemplateViewItem {
  viewKey: string;
  kind: TalkTemplateKind;
  personalId: number | null;
  sourceKey: string | null;
  title: string;
  body: string;
  categoryKey: string;
  categoryLabel: string;
  channel: TalkTemplateChannel;
  sortOrder: number;
  isActive: boolean;
  isAdvertising: boolean;
  requiresResultCheck: boolean;
}

export interface TalkTemplateView {
  visible: TalkTemplateViewItem[];
  hiddenDefaults: TalkTemplateViewItem[];
}

interface BuildTalkTemplateViewInput {
  categories: CopyCategory[];
  personalTemplates: PersonalTalkTemplate[];
  hiddenSourceKeys: string[];
}

function personalItem(
  template: PersonalTalkTemplate,
  categoryLabel: string,
  source?: { isAdvertising?: boolean; requiresResultCheck?: boolean },
): TalkTemplateViewItem {
  return {
    viewKey: `personal:${template.id}`,
    kind: "personal",
    personalId: template.id,
    sourceKey: template.source_key,
    title: template.title,
    body: template.body,
    categoryKey: template.category,
    categoryLabel,
    channel: template.channel,
    sortOrder: template.sort_order,
    isActive: template.is_active,
    isAdvertising: Boolean(source?.isAdvertising),
    requiresResultCheck: Boolean(source?.requiresResultCheck),
  };
}

function byPersonalOrder(
  left: PersonalTalkTemplate,
  right: PersonalTalkTemplate,
): number {
  return left.sort_order - right.sort_order || left.id - right.id;
}

export function buildTalkTemplateView({
  categories,
  personalTemplates,
  hiddenSourceKeys,
}: BuildTalkTemplateViewInput): TalkTemplateView {
  const hidden = new Set(hiddenSourceKeys);
  const defaultsByKey = new Map(
    categories.flatMap((category) =>
      category.templates.map((template) => [template.key, template] as const),
    ),
  );
  const knownCategoryLabels = new Map(
    categories.map((category) => [category.key, category.label]),
  );
  const personalByCategory = new Map<string, PersonalTalkTemplate[]>();
  for (const template of personalTemplates) {
    const grouped = personalByCategory.get(template.category) ?? [];
    grouped.push(template);
    personalByCategory.set(template.category, grouped);
  }

  const visible: TalkTemplateViewItem[] = [];
  const hiddenDefaults: TalkTemplateViewItem[] = [];
  for (const category of categories) {
    category.templates.forEach((template, defaultOrder) => {
      const item: TalkTemplateViewItem = {
        viewKey: `default:${template.key}`,
        kind: "default",
        personalId: null,
        sourceKey: template.key,
        title: template.title,
        body: template.body,
        categoryKey: category.key,
        categoryLabel: category.label,
        channel: template.channel,
        sortOrder: defaultOrder,
        isActive: true,
        isAdvertising: Boolean(template.isAdvertising),
        requiresResultCheck: Boolean(template.requiresResultCheck),
      };
      if (hidden.has(template.key)) hiddenDefaults.push(item);
      else visible.push(item);
    });

    const personal = personalByCategory.get(category.key) ?? [];
    personal.sort(byPersonalOrder);
    visible.push(
      ...personal.map((template) =>
        personalItem(
          template,
          category.label,
          template.source_key
            ? defaultsByKey.get(template.source_key)
            : undefined,
        ),
      ),
    );
    personalByCategory.delete(category.key);
  }

  const unknownCategories = [...personalByCategory].sort(([left], [right]) =>
    left.localeCompare(right, "ko"),
  );
  for (const [categoryKey, personal] of unknownCategories) {
    personal.sort(byPersonalOrder);
    visible.push(
      ...personal.map((template) =>
        personalItem(
          template,
          knownCategoryLabels.get(categoryKey) ?? categoryKey,
          template.source_key
            ? defaultsByKey.get(template.source_key)
            : undefined,
        ),
      ),
    );
  }

  return { visible, hiddenDefaults };
}

export function createPersonalPayloadFromDefault(
  source: TalkTemplateViewItem,
): PersonalTalkTemplatePayload {
  if (source.kind !== "default" || !source.sourceKey) {
    throw new Error("기본 화법만 내 템플릿으로 저장할 수 있습니다.");
  }
  return {
    source_key: source.sourceKey,
    title: source.title,
    body: source.body,
    category: source.categoryKey,
    channel: source.channel,
    sort_order: source.sortOrder,
    is_active: true,
  };
}

export function filterTalkTemplates(
  templates: TalkTemplateViewItem[],
  filter: TalkTemplateFilter,
): TalkTemplateViewItem[] {
  if (filter === "all") return templates;
  return templates.filter((template) => template.kind === filter);
}

export function substituteTalkTemplate(
  storedBody: string,
  variables: CopyVariables,
): string {
  return renderCopy(storedBody, variables);
}
