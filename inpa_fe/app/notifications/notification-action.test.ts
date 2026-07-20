import assert from "node:assert/strict";
import { test } from "node:test";

import { getNotificationAction } from "./notification-action";

test("영입 알림은 잘못 연결된 고객 번호가 있어도 영입 화면으로만 보낸다", () => {
  assert.deepEqual(getNotificationAction("recruiting_application", 99), {
    href: "/sales?tab=recruiting&view=status",
    label: "지원자 확인 →",
  });
  assert.deepEqual(getNotificationAction("recruiting_followup", 99), {
    href: "/sales?tab=recruiting&view=status",
    label: "다음 연락 확인 →",
  });
  assert.deepEqual(getNotificationAction("recruiting_settlement", 99), {
    href: "/sales?tab=recruiting&view=settlement",
    label: "정착 확인 보기 →",
  });
  assert.deepEqual(getNotificationAction("manager_promoted", 99), {
    href: "/manager",
    label: "팀 현황 보기 →",
  });
});

test("기존 고객 알림과 공유 알림의 이동은 그대로 유지한다", () => {
  assert.deepEqual(getNotificationAction("birthday_soon", 12), {
    href: "/customers/12",
    label: "고객 보기 →",
  });
  assert.deepEqual(getNotificationAction("share_unread", 12), {
    href: "/customers/12?tab=share",
    label: "재발송 준비 →",
  });
  assert.equal(getNotificationAction("task_due", null), null);
});
