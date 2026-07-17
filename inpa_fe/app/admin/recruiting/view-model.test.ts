import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PURGE_REASON_LABELS,
  RECRUITING_EVENT_LABELS,
  RECRUITING_STAGE_LABELS,
  RECRUITING_TEMPLATE_KIND_LABELS,
  createLatestRequestGate,
  focusAdminRecruitingTarget,
  getAdminRecruitingFailure,
  getCandidateContactStatusLabel,
  getRecruitingActorLabel,
  getRecruitingRolloutCopy,
  getRecruitingTemplateIssue,
  normalizeAdminRecruitingPage,
  shouldRefreshCandidatesAfterPurge,
} from "./view-model.js";

const validDraft = {
  code: "welcome-note",
  kind: "headline" as const,
  title: "함께 오래 성장하기",
  body: "함께 오래 일할 동료를 찾고 있어요.",
  sortOrder: 10,
};

test("페이지 값은 안전한 양의 정수만 유지한다", () => {
  assert.equal(normalizeAdminRecruitingPage(1), 1);
  assert.equal(normalizeAdminRecruitingPage(27), 27);
  for (const value of [0, -2, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.equal(normalizeAdminRecruitingPage(value), 1);
  }
});

test("운영 콘솔의 단계, 기록, 문구, 정리 사유는 쉬운 한국어로 표시한다", () => {
  assert.deepEqual(RECRUITING_STAGE_LABELS, {
    new: "새 지원",
    contact: "연락",
    conversation: "대화·면담",
    preparing: "위촉 준비",
    team_join: "팀 합류",
    recontact: "다시 연락",
    ended: "종료",
  });
  assert.equal(RECRUITING_EVENT_LABELS.candidate_purged, "정보 정리");
  assert.equal(RECRUITING_EVENT_LABELS.leader_changed, "담당 변경");
  assert.deepEqual(RECRUITING_TEMPLATE_KIND_LABELS, {
    headline: "첫 문장",
    support: "정착 지원",
    faq: "자주 묻는 질문",
    share: "공유 안내",
  });
  assert.deepEqual(PURGE_REASON_LABELS, {
    user_request: "지원자 요청",
    retention: "보관 기간 만료",
    admin_correction: "운영 정보 바로잡기",
  });
});

test("새 문구는 서버 계약과 같은 길이, 코드 형식, 정렬 순서를 확인한다", () => {
  assert.equal(getRecruitingTemplateIssue(validDraft, "create"), null);
  assert.equal(
    getRecruitingTemplateIssue({ ...validDraft, code: "Welcome Note" }, "create"),
    "코드는 영문 소문자와 숫자, 하이픈, 밑줄만 사용할 수 있어요.",
  );
  assert.equal(
    getRecruitingTemplateIssue({ ...validDraft, title: " ".repeat(3) }, "create"),
    "제목을 입력해주세요.",
  );
  assert.equal(
    getRecruitingTemplateIssue({ ...validDraft, title: "가".repeat(81) }, "create"),
    "제목은 80자까지 입력할 수 있어요.",
  );
  assert.equal(
    getRecruitingTemplateIssue({ ...validDraft, body: "가".repeat(301) }, "create"),
    "내용은 300자까지 입력할 수 있어요.",
  );
  assert.equal(
    getRecruitingTemplateIssue({ ...validDraft, sortOrder: 32768 }, "create"),
    "정렬 순서는 0부터 32767 사이의 정수로 입력해주세요.",
  );
});

test("기존 문구 수정은 바뀌지 않는 코드와 종류를 다시 검증하지 않는다", () => {
  assert.equal(
    getRecruitingTemplateIssue({ ...validDraft, code: "", kind: "faq" }, "edit"),
    null,
  );
});

test("403은 관리자 로그인 안내로, 그 외 API 오류는 서버의 다음 행동 메시지로 보여준다", () => {
  assert.deepEqual(
    getAdminRecruitingFailure(403, "권한이 없습니다.", "다시 불러와주세요."),
    {
      message: "관리자 계정으로 로그인하면 영입 운영 정보를 확인할 수 있어요.",
      needsAdminLogin: true,
    },
  );
  assert.deepEqual(
    getAdminRecruitingFailure(
      409,
      "합류 기록은 그대로 두고 계정 관리에서 다음 절차를 이어가주세요.",
      "다시 불러와주세요.",
    ),
    {
      message: "합류 기록은 그대로 두고 계정 관리에서 다음 절차를 이어가주세요.",
      needsAdminLogin: false,
    },
  );
  assert.deepEqual(getAdminRecruitingFailure(null, "", "다시 불러와주세요."), {
    message: "다시 불러와주세요.",
    needsAdminLogin: false,
  });
});

test("공개 설정이 꺼져 있어도 운영 준비를 이어갈 수 있다고 안내한다", () => {
  assert.deepEqual(getRecruitingRolloutCopy(false), {
    label: "설계사 화면 공개 전",
    description: "문구와 정보 정리 기준은 지금 확인하고 준비할 수 있어요.",
  });
  assert.deepEqual(getRecruitingRolloutCopy(true), {
    label: "설계사 화면 공개 중",
    description: "설계사 영입 화면이 현재 공개되어 있어요.",
  });
});

test("목록은 가장 최근에 시작한 요청만 화면 상태를 바꿀 수 있다", () => {
  const gate = createLatestRequestGate();
  const first = gate.begin();
  const second = gate.begin();

  assert.equal(gate.isCurrent(first), false);
  assert.equal(gate.isCurrent(second), true);

  gate.invalidate();
  assert.equal(gate.isCurrent(second), false);
  assert.equal(gate.isCurrent(gate.begin()), true);
});

test("운영 기록 처리자는 계정과 공개 요청, 시스템 처리를 사실대로 구분한다", () => {
  assert.equal(getRecruitingActorLabel("stage_changed", 17), "처리 계정 #17");
  assert.equal(getRecruitingActorLabel("contact_stopped", null), "지원자 요청");
  assert.equal(getRecruitingActorLabel("leader_changed", null), "지원자 선택");
  assert.equal(getRecruitingActorLabel("candidate_purged", null), "시스템 처리");
});

test("연락 상태는 중단 기록과 종료·합류 단계에서 확인되는 사실만 표시한다", () => {
  assert.equal(getCandidateContactStatusLabel("contact", false), "연락 중단 기록 없음");
  assert.equal(getCandidateContactStatusLabel("ended", false), "연락 중단 기록 없음");
  assert.equal(getCandidateContactStatusLabel("team_join", false), "팀 합류");
  assert.equal(getCandidateContactStatusLabel("ended", true), "연락 중단 기록 있음");
});

test("정보 정리 뒤에는 화면에 남아 있는 지원 정보 구역으로 초점을 옮긴다", () => {
  let connectedFocused = 0;
  let detachedFocused = 0;

  focusAdminRecruitingTarget({
    isConnected: true,
    focus: () => {
      connectedFocused += 1;
    },
  });
  focusAdminRecruitingTarget({
    isConnected: false,
    focus: () => {
      detachedFocused += 1;
    },
  });

  assert.equal(connectedFocused, 1);
  assert.equal(detachedFocused, 0);
});

test("지원 정보 새로고침은 정리 창이 닫힌 다음에만 시작한다", () => {
  assert.equal(shouldRefreshCandidatesAfterPurge(false, false), false);
  assert.equal(shouldRefreshCandidatesAfterPurge(true, true), false);
  assert.equal(shouldRefreshCandidatesAfterPurge(false, true), true);
});
