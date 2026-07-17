export interface NavigationAccessProfile {
  is_manager: boolean;
  managed_agents_count: number;
  recruiting_enabled: boolean;
}

export function getNavigationAccess(profile: NavigationAccessProfile): {
  isManager: boolean;
  recruitingEnabled: boolean;
} {
  return {
    isManager: profile.is_manager,
    recruitingEnabled: profile.recruiting_enabled,
  };
}

export function rollupMoreUnread({
  board,
  promotion,
  admin,
  recruiting,
  isAdmin,
  recruitingEnabled,
}: {
  board: number;
  promotion: number;
  admin: number;
  recruiting: number;
  isAdmin: boolean;
  recruitingEnabled: boolean;
}): number {
  return (
    board +
    promotion +
    (isAdmin ? admin : 0) +
    (recruitingEnabled ? recruiting : 0)
  );
}

export function shouldOpenManagerPromotion(profile: {
  is_manager: boolean;
  manager_promoted_at: string | null;
  manager_promotion_seen_at: string | null;
}): boolean {
  return Boolean(
    profile.is_manager &&
      profile.manager_promoted_at !== null &&
      profile.manager_promotion_seen_at === null,
  );
}

export type ManagerPromotionIntent = "team" | "recruit" | "close";

export function getManagerPromotionDestination(
  intent: ManagerPromotionIntent,
  recruitingEnabled: boolean,
): string | null {
  if (intent === "team") return "/manager";
  if (intent === "recruit" && recruitingEnabled) {
    return "/recruiting?tab=page";
  }
  return null;
}

export function getManagerPromotionSecondaryLabel(
  recruitingEnabled: boolean,
): "다음 설계사 영입하기" | "확인" {
  return recruitingEnabled ? "다음 설계사 영입하기" : "확인";
}

export function getWrappedFocusIndex(
  currentIndex: number,
  count: number,
  backwards: boolean,
): number | null {
  if (count === 0) return null;
  if (currentIndex < 0) return backwards ? count - 1 : 0;
  if (backwards && currentIndex === 0) return count - 1;
  if (!backwards && currentIndex === count - 1) return 0;
  return null;
}
