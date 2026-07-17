import assert from "node:assert/strict";
import { test } from "node:test";

import { normalizeAdminApiError } from "./admin-api-error.js";

test("배열 형태의 code 검증 오류는 문자열 상태 코드와 첫 필드 메시지로 정규화한다", () => {
  assert.deepEqual(
    normalizeAdminApiError(
      { code: ["이미 사용 중인 코드예요. 다른 코드를 입력해주세요."] },
      400,
      "Bad Request",
    ),
    {
      code: "400",
      detail: "이미 사용 중인 코드예요. 다른 코드를 입력해주세요.",
    },
  );
});

test("문자열 오류 코드는 유지하고 서버의 다음 행동 메시지를 우선한다", () => {
  assert.deepEqual(
    normalizeAdminApiError(
      {
        code: "recruiting_join_history_preserved",
        message: "합류 기록은 그대로 두고 계정 관리에서 다음 절차를 이어가주세요.",
      },
      409,
      "Conflict",
    ),
    {
      code: "recruiting_join_history_preserved",
      detail: "합류 기록은 그대로 두고 계정 관리에서 다음 절차를 이어가주세요.",
    },
  );
});

test("알려진 오류 정보가 없으면 상태 코드와 HTTP 문구를 사용한다", () => {
  assert.deepEqual(normalizeAdminApiError({}, 503, "Service Unavailable"), {
    code: "503",
    detail: "Service Unavailable",
  });
});
