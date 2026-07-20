import assert from "node:assert/strict";
import { test } from "node:test";

import {
  getManagerPromotionDestination,
  getManagerPromotionSecondaryLabel,
  getNavigationAccess,
  getWrappedFocusIndex,
  rollupMoreUnread,
  shouldOpenManagerPromotion,
} from "./recruiting-integration";

test("영입 기능은 서버 플래그가 켜진 프로필에만 보인다", () => {
  assert.deepEqual(
    getNavigationAccess({
      is_manager: false,
      managed_agents_count: 0,
      recruiting_enabled: true,
    }),
    { isManager: false, recruitingEnabled: true },
  );
  assert.deepEqual(
    getNavigationAccess({
      is_manager: false,
      managed_agents_count: 3,
      recruiting_enabled: false,
    }),
    { isManager: false, recruitingEnabled: false },
  );
});

test("관리자 메뉴는 팀원 수가 아니라 서버의 관리자 역할만 따른다", () => {
  assert.equal(
    getNavigationAccess({
      is_manager: false,
      managed_agents_count: 4,
      recruiting_enabled: true,
    }).isManager,
    false,
  );
  assert.equal(
    getNavigationAccess({
      is_manager: true,
      managed_agents_count: 0,
      recruiting_enabled: true,
    }).isManager,
    true,
  );
});

test("모바일 더보기 배지는 영입 메뉴가 보일 때만 영입 미읽음을 더한다", () => {
  const counts = {
    board: 2,
    promotion: 3,
    admin: 5,
    recruiting: 7,
  };

  assert.equal(
    rollupMoreUnread({ ...counts, isAdmin: true, recruitingEnabled: true }),
    17,
  );
  assert.equal(
    rollupMoreUnread({ ...counts, isAdmin: false, recruitingEnabled: false }),
    5,
  );
});

test("첫 관리자 승격 안내는 역할과 두 시각 조건을 모두 만족할 때만 연다", () => {
  const pending = {
    is_manager: true,
    manager_promoted_at: "2026-07-17T09:00:00+09:00",
    manager_promotion_seen_at: null,
  };

  assert.equal(shouldOpenManagerPromotion(pending), true);
  assert.equal(shouldOpenManagerPromotion({ ...pending, is_manager: false }), false);
  assert.equal(shouldOpenManagerPromotion({ ...pending, manager_promoted_at: null }), false);
  assert.equal(
    shouldOpenManagerPromotion({
      ...pending,
      manager_promotion_seen_at: "2026-07-17T09:01:00+09:00",
    }),
    false,
  );
});

test("영입 기능이 꺼진 승격 안내는 두 번째 선택에서 이동하지 않는다", () => {
  assert.equal(getManagerPromotionDestination("team", false), "/manager");
  assert.equal(
    getManagerPromotionDestination("recruit", true),
    "/sales?tab=recruiting&view=page",
  );
  assert.equal(getManagerPromotionDestination("recruit", false), null);
  assert.equal(getManagerPromotionDestination("close", true), null);
  assert.equal(getManagerPromotionSecondaryLabel(true), "다음 설계사 영입하기");
  assert.equal(getManagerPromotionSecondaryLabel(false), "확인");
});

test("승격 안내 밖에 초점이 생겨도 다음 탭 입력을 안내 안으로 되돌린다", () => {
  assert.equal(getWrappedFocusIndex(-1, 3, false), 0);
  assert.equal(getWrappedFocusIndex(-1, 3, true), 2);
  assert.equal(getWrappedFocusIndex(2, 3, false), 0);
  assert.equal(getWrappedFocusIndex(0, 3, true), 2);
  assert.equal(getWrappedFocusIndex(1, 3, false), null);
  assert.equal(getWrappedFocusIndex(1, 3, true), null);
  assert.equal(getWrappedFocusIndex(-1, 0, false), null);
});
