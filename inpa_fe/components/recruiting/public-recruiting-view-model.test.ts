import assert from "node:assert/strict";
import { test } from "node:test";

import type { PublicRecruitingApplicationResult } from "../../lib/api";
import { CAREER_LABELS, CONTACT_LABELS } from "./recruiting-labels";
import {
  MANAGE_STORAGE_KEY,
  clearMatchingManageToken,
  extractManageToken,
  focusIfConnected,
  getApplicationResultKind,
  getLeaderChoiceFailureAction,
  getJoinErrorKind,
  getOrCreateSubmissionAttempt,
  getStopFailurePresentation,
  isSafeRecruitingToken,
  prepareRecruitingJoinAuthReturn,
  readStoredManageToken,
  shouldResetSubmissionAttempt,
  storeManagePath,
  validatePublicApplication,
  writeStoredManageToken,
} from "./public-recruiting-view-model";

class MemoryStorage {
  private values = new Map<string, string>();
  readonly reads: string[] = [];

  getItem(key: string) {
    this.reads.push(key);
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }

  removeItem(key: string) {
    this.values.delete(key);
  }
}

test("공개 경로 토큰은 단일 안전 구간만 허용한다", () => {
  for (const token of ["abc.DEF_9:-", "2dc84ad7-e59e-4d24-8b4a-40b8af20f4f8"]) {
    assert.equal(isSafeRecruitingToken(token), true, token);
  }
  for (const token of ["", ".", "..", "a/b", "a?b", "a#b", "a%2Fb", "한글"]) {
    assert.equal(isSafeRecruitingToken(token), false, token);
  }
});

test("응답을 잃은 지원은 편집된 화면값과 무관하게 첫 전체 payload를 그대로 재사용한다", () => {
  let generated = 0;
  const create = () => `00000000-0000-4000-8000-00000000000${++generated}`;
  const form = {
    name: " 김 지원 ",
    phone: " 010-1234-5678 ",
    careerBand: "3_5" as const,
    currentAffiliation: " 한빛  GA ",
    region: " 서울  강남 ",
    contactWindow: "evening" as const,
    agreed: true,
  };
  const first = getOrCreateSubmissionAttempt(null, form, {
    createSubmissionKey: create,
    priorManageToken: "prior-token",
  });
  form.name = "응답 유실 뒤 바꾼 이름";
  form.phone = "010-9999-9999";
  const retry = getOrCreateSubmissionAttempt(first, form, {
    createSubmissionKey: create,
    priorManageToken: "changed-prior-token",
  });

  assert.equal(retry, first);
  assert.deepEqual(retry, {
    name: "김 지원",
    phone: "010-1234-5678",
    career_band: "3_5",
    current_affiliation: "한빛 GA",
    region: "서울 강남",
    contact_window: "evening",
    submission_key: "00000000-0000-4000-8000-000000000001",
    prior_manage_token: "prior-token",
    agreed: true,
  });
  assert.equal(generated, 1);
});

test("공개 POST의 400만 snapshot을 버리고 429와 네트워크 오류는 유지한다", () => {
  assert.equal(shouldResetSubmissionAttempt({ status: 400 }), true);
  assert.equal(shouldResetSubmissionAttempt({ status: 429 }), false);
  assert.equal(shouldResetSubmissionAttempt(null), false);
});

test("지원 관리 토큰은 전용 키에서만 읽고 빈 값과 잘못된 값을 정리한다", () => {
  const storage = new MemoryStorage();
  storage.setItem("unrelated", "do-not-read");
  storage.setItem(MANAGE_STORAGE_KEY, " ");
  assert.equal(readStoredManageToken(storage), null);
  assert.deepEqual(storage.reads, [MANAGE_STORAGE_KEY]);

  storage.setItem(MANAGE_STORAGE_KEY, "../private");
  assert.equal(readStoredManageToken(storage), null);
  storage.setItem(MANAGE_STORAGE_KEY, "valid-manage-token");
  assert.equal(readStoredManageToken(storage), "valid-manage-token");

  writeStoredManageToken(storage, "replacement-token");
  assert.equal(readStoredManageToken(storage), "replacement-token");
  clearMatchingManageToken(storage, "another-token");
  assert.equal(readStoredManageToken(storage), "replacement-token");
  clearMatchingManageToken(storage, "replacement-token");
  assert.equal(readStoredManageToken(storage), null);

  storage.setItem(MANAGE_STORAGE_KEY, "old-token");
  assert.equal(writeStoredManageToken(storage, "../unsafe"), false);
  assert.equal(readStoredManageToken(storage), null);
});

test("같은 출처의 관리 경로에서만 단일 토큰을 꺼낸다", () => {
  assert.equal(extractManageToken("/r/manage/safe-token"), "safe-token");
  assert.equal(extractManageToken("/r/manage/safe-token/"), null);
  assert.equal(extractManageToken("https://evil.example/r/manage/token"), null);
  assert.equal(extractManageToken("/r/manage/token/extra"), null);
  assert.equal(extractManageToken("/r/manage/token?next=/home"), null);
});

test("malformed 성공 manage_url은 이전 지원 관리 토큰을 남기지 않는다", () => {
  const storage = new MemoryStorage();
  storage.setItem(MANAGE_STORAGE_KEY, "stale-token");

  assert.equal(storeManagePath(storage, "https://evil.example/r/manage/new-token"), null);
  assert.equal(readStoredManageToken(storage), null);
});

test("지원 결과를 접수, 담당자 선택, 기존 링크 확인으로 나눈다", () => {
  const submitted: PublicRecruitingApplicationResult = {
    submitted: true,
    message: "접수",
    manage_url: "/r/manage/token",
  };
  const choice: PublicRecruitingApplicationResult = {
    submitted: false,
    choice_required: true,
    current_leader: { display_name: "현재 리더", affiliation: "현재 GA" },
    new_leader: { display_name: "새 리더", affiliation: "새 GA" },
    choice_token: "choice-token",
  };
  const verification: PublicRecruitingApplicationResult = {
    submitted: false,
    verification_required: true,
    message: "기존 링크 확인",
  };

  assert.equal(getApplicationResultKind(submitted), "submitted");
  assert.equal(getApplicationResultKind(choice), "choice_required");
  assert.equal(getApplicationResultKind(verification), "verification_required");
});

test("합류 오류는 리더 변경 재확인, 만료, 안내, 재시도로 나눈다", () => {
  assert.equal(
    getJoinErrorKind({ status: 409, code: "team_switch_confirmation_required" }),
    "switch_confirmation",
  );
  assert.equal(getJoinErrorKind({ status: 410, code: "recruiting_join_link_expired" }), "expired");
  assert.equal(getJoinErrorKind({ status: 409, code: "other_conflict" }), "message");
  assert.equal(getJoinErrorKind({ status: 503, code: "503" }), "retry");
});

test("담당자 선택 400은 원래 지원 snapshot 재확인으로 돌아가고 429는 같은 선택을 재시도한다", () => {
  assert.equal(getLeaderChoiceFailureAction({ status: 400 }), "restart_application");
  assert.equal(getLeaderChoiceFailureAction({ status: 429 }), "retry_choice");
  assert.equal(getLeaderChoiceFailureAction(null), "retry_choice");
});

test("연락 중단 429와 네트워크 오류는 모달을 닫고 본문 오류를 노출한다", () => {
  assert.deepEqual(getStopFailurePresentation("잠시 후 다시 요청해주세요."), {
    dialogOpen: false,
    inlineError: "잠시 후 다시 요청해주세요.",
  });
  assert.deepEqual(getStopFailurePresentation("연결을 확인해주세요."), {
    dialogOpen: false,
    inlineError: "연결을 확인해주세요.",
  });
});

test("종료 전환 포커스는 실제 DOM에 연결된 대상에만 이동한다", () => {
  let connectedFocused = 0;
  let detachedFocused = 0;
  assert.equal(
    focusIfConnected({ isConnected: true, focus: () => { connectedFocused += 1; } }),
    true,
  );
  assert.equal(
    focusIfConnected({ isConnected: false, focus: () => { detachedFocused += 1; } }),
    false,
  );
  assert.equal(connectedFocused, 1);
  assert.equal(detachedFocused, 0);
});

test("문법상 안전하지 않은 합류 토큰은 오래된 인증 복귀경로를 지운다", () => {
  let remembered: string | null = null;
  let cleared = 0;
  assert.equal(
    prepareRecruitingJoinAuthReturn("../unsafe", {
      remember: (path) => { remembered = path; return true; },
      clear: () => { cleared += 1; },
    }),
    false,
  );
  assert.equal(remembered, null);
  assert.equal(cleared, 1);

  assert.equal(
    prepareRecruitingJoinAuthReturn("safe-token", {
      remember: (path) => { remembered = path; return true; },
      clear: () => { cleared += 1; },
    }),
    true,
  );
  assert.equal(remembered, "/recruiting/join/safe-token");
  assert.equal(cleared, 1);
});

test("지원서는 경력과 연락 시간을 포함한 필수값을 쉬운 문장으로 검증한다", () => {
  const valid = {
    name: " 김 지원 ",
    phone: " 010-1234-5678 ",
    careerBand: "3_5" as const,
    currentAffiliation: " 한빛  GA ",
    region: " 서울  강남 ",
    contactWindow: "evening" as const,
    agreed: true,
  };
  assert.equal(validatePublicApplication(valid), null);
  assert.equal(validatePublicApplication({ ...valid, name: "" }), "이름을 입력해주세요.");
  assert.equal(validatePublicApplication({ ...valid, phone: "" }), "연락처를 입력해주세요.");
  assert.equal(
    validatePublicApplication({ ...valid, careerBand: "" }),
    "보험설계사 경력을 선택해주세요.",
  );
  assert.equal(validatePublicApplication({ ...valid, region: "" }), "활동 지역을 입력해주세요.");
  assert.equal(
    validatePublicApplication({ ...valid, contactWindow: "" }),
    "연락받기 편한 시간을 선택해주세요.",
  );
  assert.equal(
    validatePublicApplication({ ...valid, agreed: false }),
    "개인정보 수집과 연락에 동의하면 지원 내용을 보낼 수 있어요.",
  );
});

test("경력과 연락 시간 코드는 공개 화면의 쉬운 말로만 표시한다", () => {
  assert.deepEqual(CAREER_LABELS, {
    under_1: "1년 미만",
    "1_3": "1~3년",
    "3_5": "3~5년",
    "5_10": "5~10년",
    "10_plus": "10년 이상",
  });
  assert.deepEqual(CONTACT_LABELS, {
    morning: "오전",
    afternoon: "오후",
    evening: "저녁",
    anytime: "언제든",
  });
});
