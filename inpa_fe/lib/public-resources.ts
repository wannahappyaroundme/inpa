export interface PublicResourceSummary {
  kind: "tool" | "resource";
  path: `/tools/${string}` | `/resources/${string}`;
  title: string;
  description: string;
  actionLabel: string;
}

export const PUBLIC_RESOURCES = [
  {
    kind: "tool",
    path: "/tools/insurance-age",
    title: "보험나이 계산기",
    description: "생년월일과 기준일을 입력해 보험나이를 바로 확인합니다. 입력한 날짜는 브라우저 안에서만 계산합니다.",
    actionLabel: "바로 계산하기",
  },
  {
    kind: "resource",
    path: "/resources/customer-management-sheet",
    title: "고객 관리표 빈 양식",
    description: "고객 단계와 다음 행동을 정리할 수 있는 7개 항목의 빈 CSV 양식을 내려받습니다.",
    actionLabel: "빈 양식 받기",
  },
  {
    kind: "resource",
    path: "/resources/consultation-checklist",
    title: "첫 상담 체크리스트",
    description: "상담 전, 상담 중, 상담 후에 확인할 15개 항목을 체크하고 인쇄합니다.",
    actionLabel: "체크리스트 열기",
  },
] as const satisfies readonly PublicResourceSummary[];

export function getPublicResourcePaths(): string[] {
  return PUBLIC_RESOURCES.map((resource) => resource.path);
}
