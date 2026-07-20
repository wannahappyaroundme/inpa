const RECRUITING_NOTIFICATION_ACTIONS: Record<
  string,
  { href: string; label: string }
> = {
  recruiting_application: {
    href: "/sales?tab=recruiting&view=status",
    label: "지원자 확인 →",
  },
  recruiting_followup: {
    href: "/sales?tab=recruiting&view=status",
    label: "다음 연락 확인 →",
  },
  recruiting_settlement: {
    href: "/sales?tab=recruiting&view=settlement",
    label: "정착 확인 보기 →",
  },
  manager_promoted: {
    href: "/manager",
    label: "팀 현황 보기 →",
  },
};

export function getNotificationAction(
  type: string,
  customerId: number | null,
): { href: string; label: string } | null {
  const recruitingAction = RECRUITING_NOTIFICATION_ACTIONS[type];
  if (recruitingAction) return recruitingAction;
  if (!customerId) return null;
  if (type === "share_unread") {
    return {
      href: `/customers/${customerId}?tab=share`,
      label: "재발송 준비 →",
    };
  }
  return {
    href: `/customers/${customerId}`,
    label: "고객 보기 →",
  };
}
