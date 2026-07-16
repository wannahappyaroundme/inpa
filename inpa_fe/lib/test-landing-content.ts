import { MAIN_ORIGIN } from "./new-host-routing";

export const HERO = {
  eyebrow: "내 손안의 인슈어 파트너",
  title: "설계사님은 클로징만 준비하세요",
  description:
    "고객 관리부터 증권 정리, 보장 확인, 비교, 일정까지 한곳에서 이어집니다.",
} as const;

export const FACTS = [
  {
    title: "100개 이상 담보를 같은 틀로",
    description: "회사마다 다른 담보 이름을 같은 기준으로 모아 봅니다.",
  },
  {
    title: "증권 한 장 자동 정리",
    description: "보험과 담보 내용을 읽어 보기 쉬운 표로 정리합니다.",
  },
  {
    title: "설계사님이 정한 기준 적용",
    description: "넉넉, 적정, 부족 표시는 설계사님이 설정한 기준을 따릅니다.",
  },
] as const;

export type ProductScreenId =
  | "dashboard"
  | "customers"
  | "coverage"
  | "compare"
  | "schedule";

export type ProductScreen = {
  id: ProductScreenId;
  label: string;
  title: string;
  description: string;
  image: `/landing-test/${ProductScreenId}.webp`;
  imageAlt: string;
  width: number;
  height: number;
  highlights: readonly [string, string] | readonly [string, string, string];
  privacyNote?: string;
};

export const PRODUCT_SCREENS: readonly ProductScreen[] = [
  {
    id: "dashboard",
    label: "한눈에 보기",
    title: "오늘의 영업 흐름을 먼저 확인",
    description:
      "목표와 이번 달 활동, 오늘 일정을 한 화면에서 보고 다음 행동을 정합니다.",
    image: "/landing-test/dashboard.webp",
    imageAlt: "인파 대시보드 실제 화면: 월 목표, 영업 단계, 오늘 일정",
    width: 1200,
    height: 570,
    highlights: ["월 목표와 현재 흐름", "고객 단계별 현황", "오늘 일정과 빠른 실행"],
  },
  {
    id: "customers",
    label: "고객 관리",
    title: "고객별 다음 행동을 놓치지 않게",
    description:
      "DB, TA, FA, 청약 흐름과 연락 시점을 함께 보며 고객별 다음 할 일을 이어갑니다.",
    image: "/landing-test/customers.webp",
    imageAlt: "인파 고객 관리 실제 화면: 단계별 고객 현황",
    width: 1200,
    height: 525,
    highlights: ["단계별 고객 보기", "연락 시점과 상태 확인", "고객 정보와 다음 할 일 연결"],
    privacyNote: "일부 개인정보 보호 처리",
  },
  {
    id: "coverage",
    label: "보장 정리",
    title: "복잡한 담보를 같은 틀로 한눈에",
    description:
      "등록한 증권의 담보를 같은 항목으로 모으고, 설계사님 기준에 따라 색으로 확인합니다.",
    image: "/landing-test/coverage.webp",
    imageAlt: "인파 보장 정리 실제 화면: 담보별 넉넉, 적정, 부족 표시",
    width: 1440,
    height: 1089,
    highlights: ["100개 이상 담보 항목", "넉넉, 적정, 부족 표시", "설계사님 기준 적용"],
  },
  {
    id: "compare",
    label: "비교 분석",
    title: "현재와 제안을 나란히 비교",
    description:
      "담보와 보험료 변화를 나란히 정리해 고객 안내 전에 확인할 내용을 준비합니다.",
    image: "/landing-test/compare.webp",
    imageAlt: "인파 비교 분석 실제 화면: 현재와 제안 담보 비교",
    width: 1440,
    height: 442,
    highlights: ["담보별 금액 차이", "보험료 유형별 구분", "고객 안내용 내용 복사"],
  },
  {
    id: "schedule",
    label: "일정 관리",
    title: "예약 요청부터 오늘 일정까지",
    description:
      "고객이 고른 상담 시간을 확인하고, 개인 일정과 함께 한 달 흐름으로 관리합니다.",
    image: "/landing-test/schedule.webp",
    imageAlt: "인파 일정 관리 실제 화면: 달력과 상담 예약 요청",
    width: 1440,
    height: 590,
    highlights: ["상담 가능한 시간 설정", "예약 요청 확인", "개인 일정과 함께 보기"],
  },
];

export function getAdjacentProductScreenIndex(
  currentIndex: number,
  key: "ArrowLeft" | "ArrowRight",
): number {
  const offset = key === "ArrowLeft" ? -1 : 1;

  return (currentIndex + offset + PRODUCT_SCREENS.length) % PRODUCT_SCREENS.length;
}

export function getProductTabKeyAction(
  key: string,
): "select" | "move-left" | "move-right" | "none" {
  if (key === "Enter" || key === " ") return "select";
  if (key === "ArrowLeft") return "move-left";
  if (key === "ArrowRight") return "move-right";
  return "none";
}

export function getProductGalleryIds(id: ProductScreenId) {
  return {
    tabId: `landing-test-product-tab-${id}`,
    panelId: `landing-test-product-panel-${id}`,
    dialogTitleId: `landing-test-product-dialog-title-${id}`,
  } as const;
}

export const WORKFLOW_STEPS = [
  {
    title: "고객과 증권 등록",
    description: "고객 동의를 먼저 보내고, 받은 증권을 고객 정보에 연결합니다.",
  },
  {
    title: "보장 자동 정리",
    description: "보험과 담보를 읽어 같은 기준의 보장 항목으로 정리합니다.",
  },
  {
    title: "현재와 제안 비교",
    description: "선택한 두 구성을 담보와 보험료 기준으로 나란히 확인합니다.",
  },
  {
    title: "고객 안내와 다음 일정 관리",
    description: "확인한 내용을 직접 안내하고 상담 예약과 다음 행동을 이어갑니다.",
  },
] as const;

export const DIFFERENTIATORS = [
  {
    title: "고객 관리와 분석이 한 흐름으로 이어져요",
    description:
      "고객을 등록한 뒤 증권, 보장 정리, 비교, 일정으로 자연스럽게 이어갈 수 있습니다.",
  },
  {
    title: "보장 기준은 설계사님이 직접 정해요",
    description:
      "인파가 임의의 적정 금액을 제시하지 않고, 설계사님이 설정한 기준만 적용합니다.",
  },
] as const;

export const AUDIENCES = [
  {
    label: "개인 설계사",
    title: "혼자 일해도 고객과 일정이 흩어지지 않게",
    description:
      "고객의 현재 단계와 다음 행동을 한곳에 모아 상담 준비에 집중할 수 있습니다.",
    highlights: ["고객 단계별 관리", "증권과 보장 한눈에 보기", "상담 예약과 일정 연결"],
  },
  {
    label: "관리직",
    title: "동의한 팀원의 활동 흐름을 한눈에",
    description:
      "개별 고객 정보 대신 팀원이 공유에 동의한 성과 흐름을 모아 볼 수 있습니다.",
    highlights: ["팀 영업 단계 확인", "월별 활동 흐름", "설계사별 목표 점검"],
  },
] as const;

export const FAQS = [
  {
    question: "베타 기간에는 어떻게 이용하나요?",
    answer:
      "베타 기간에는 핵심 기능을 부담 없이 확인할 수 있어요. 운영 정책이 바뀌면 화면에서 먼저 안내합니다.",
  },
  {
    question: "증권을 올리면 어떤 정보가 정리되나요?",
    answer:
      "고객 동의를 먼저 받은 뒤 증권을 올리면 보험 정보와 담보 내용을 읽어 같은 틀로 정리합니다.",
  },
  {
    question: "넉넉, 적정, 부족 기준은 누가 정하나요?",
    answer:
      "설계사님이 직접 설정합니다. 인파는 임의의 적정 금액을 제공하지 않습니다.",
  },
  {
    question: "고객에게 바로 보낼 수 있나요?",
    answer:
      "정리된 내용을 확인한 뒤 설계사님이 복사해 문자나 메신저로 직접 안내할 수 있습니다.",
  },
  {
    question: "휴대폰에서도 사용할 수 있나요?",
    answer: "별도 설치 없이 휴대폰과 컴퓨터의 웹 브라우저에서 이용할 수 있습니다.",
  },
] as const;

export function buildServiceUrl(path: string, search?: string): string {
  const target = new URL(path, MAIN_ORIGIN);
  const sourceSearch =
    search ?? (typeof window === "undefined" ? "" : window.location.search);

  for (const [key, value] of new URLSearchParams(sourceSearch)) {
    if (key.startsWith("utm_") && !target.searchParams.has(key)) {
      target.searchParams.append(key, value);
    }
  }

  return target.toString();
}
