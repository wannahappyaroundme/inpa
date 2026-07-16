import assert from "node:assert/strict";
import { test } from "node:test";

import type {
  RecruitingActiveCandidate,
  RecruitingCandidate,
  RecruitingReplacedCandidate,
  RecruitingSettlement,
  RecruitingTemplate,
} from "../../lib/api";
import {
  allowedManualStageChoices,
  createLatestRequestGate,
  getActiveSelectedTemplateIds,
  getCandidateDisplayIdentity,
  getRecruitingPageEditorIssue,
  groupSettlementsByDue,
  normalizeRecruitingTab,
  sortRecruitingCandidates,
  sortCandidatesByNextAction,
} from "./recruiting-view-model";

function activeCandidate(
  overrides: Partial<RecruitingActiveCandidate> = {},
): RecruitingActiveCandidate {
  return {
    id: 1,
    campaign_id: 10,
    campaign: { id: 10, name: "개인 소개", channel: "relationship" },
    name: "김지원",
    phone: "01012345678",
    career_band: "3_5",
    current_affiliation: "한빛GA",
    region: "서울",
    contact_window: "evening",
    stage: "conversation",
    selection_status: "active",
    next_action: "meeting",
    next_action_at: "2026-07-18T09:00:00+09:00",
    last_contacted_at: null,
    ended_at: null,
    joined_at: null,
    joined_agent: null,
    created_at: "2026-07-10T09:00:00+09:00",
    updated_at: "2026-07-16T09:00:00+09:00",
    duplicate_contact: false,
    closed_message: "",
    ...overrides,
  };
}

function settlement(
  id: number,
  dueOn: string,
  overrides: Partial<RecruitingSettlement> = {},
): RecruitingSettlement {
  return {
    id,
    candidate_id: id,
    joined_agent_name: `합류 설계사 ${id}`,
    week: 1,
    due_on: dueOn,
    state: "active",
    blocker: "",
    next_support: "",
    completed_at: null,
    ...overrides,
  };
}

function template(
  id: number,
  kind: RecruitingTemplate["kind"],
): RecruitingTemplate {
  return {
    id,
    code: `${kind}-${id}`,
    kind,
    title: `문구 ${id}`,
    body: `내용 ${id}`,
    sort_order: id,
  };
}

test("알 수 없거나 비어 있는 탭은 영입 현황으로만 정규화한다", () => {
  assert.equal(normalizeRecruitingTab(null), "status");
  assert.equal(normalizeRecruitingTab(""), "status");
  assert.equal(normalizeRecruitingTab("javascript:alert(1)"), "status");
  assert.equal(normalizeRecruitingTab("page"), "page");
  assert.equal(normalizeRecruitingTab("campaign"), "campaign");
  assert.equal(normalizeRecruitingTab("settlement"), "settlement");
});

test("진행 중 지원자는 지원서 신원과 상세 연락처를 사용한다", () => {
  assert.deepEqual(getCandidateDisplayIdentity(activeCandidate()), {
    kind: "applicant",
    displayName: "김지원",
    phone: "01012345678",
    careerBand: "3_5",
    currentAffiliation: "한빛GA",
    region: "서울",
    contactWindow: "evening",
  });
});

test("팀 합류 단계는 합류 계정 프로필만 사용하고 과거 지원 정보는 버린다", () => {
  const candidate = activeCandidate({
    stage: "team_join",
    name: "노출되면 안 되는 이름",
    phone: "01099999999",
    current_affiliation: "과거 소속",
    region: "과거 지역",
    joined_agent: {
      id: 88,
      display_name: "박합류",
      profile_image: "/media/joined.jpg",
    },
  });

  assert.deepEqual(getCandidateDisplayIdentity(candidate), {
    kind: "joined",
    displayName: "박합류",
    profileImage: "/media/joined.jpg",
    phone: null,
  });
});

test("담당 변경 종료 기록은 닫힘 안내와 날짜만 사용한다", () => {
  const candidate: RecruitingReplacedCandidate = {
    id: 91,
    stage: "ended",
    selection_status: "replaced",
    closed_message: "후보가 다른 담당자를 선택해 대화가 종료되었어요.",
    created_at: "2026-07-01T09:00:00+09:00",
    updated_at: "2026-07-15T14:00:00+09:00",
  };

  assert.deepEqual(getCandidateDisplayIdentity(candidate), {
    kind: "closed",
    displayName: "지원 종료",
    closedMessage: candidate.closed_message,
    closedAt: candidate.updated_at,
    phone: null,
  });
});

test("정착 확인은 지난 확인, 오늘, 예정, 완료 순서로 나누고 기한이 빠른 순으로 정렬한다", () => {
  const grouped = groupSettlementsByDue(
    [
      settlement(1, "2026-07-15"),
      settlement(2, "2026-07-10"),
      settlement(3, "2026-07-17"),
      settlement(4, "2026-08-01"),
      settlement(5, "2026-07-20"),
      settlement(6, "2026-07-09", {
        completed_at: "2026-07-16T09:00:00+09:00",
      }),
      settlement(7, "2026-07-08", {
        state: "stopped",
        completed_at: "2026-07-17T09:00:00+09:00",
      }),
    ],
    "2026-07-17",
  );

  assert.deepEqual(grouped.past.map((item) => item.id), [2, 1]);
  assert.deepEqual(grouped.today.map((item) => item.id), [3]);
  assert.deepEqual(grouped.upcoming.map((item) => item.id), [5, 4]);
  assert.deepEqual(grouped.completed.map((item) => item.id), [7, 6]);
});

test("수동 단계 선택은 서버 허용 흐름만 보이고 팀 합류와 담당 변경 기록은 잠근다", () => {
  const cases: Array<[RecruitingCandidate, string[]]> = [
    [activeCandidate({ stage: "new" }), ["contact", "recontact", "ended"]],
    [activeCandidate({ stage: "contact" }), ["conversation", "recontact", "ended"]],
    [activeCandidate({ stage: "conversation" }), ["preparing", "recontact", "ended"]],
    [activeCandidate({ stage: "preparing" }), ["conversation", "recontact", "ended"]],
    [activeCandidate({ stage: "recontact" }), ["contact", "ended"]],
    [activeCandidate({ stage: "ended" }), ["recontact"]],
    [activeCandidate({ stage: "team_join" }), []],
    [
      {
        id: 92,
        stage: "ended",
        selection_status: "replaced",
        closed_message: "종료",
        created_at: "2026-07-01T09:00:00+09:00",
        updated_at: "2026-07-15T14:00:00+09:00",
      },
      [],
    ],
  ];

  for (const [candidate, expected] of cases) {
    assert.deepEqual(allowedManualStageChoices(candidate), expected, candidate.stage);
    assert.equal(allowedManualStageChoices(candidate).includes("team_join"), false);
  }
});

test("모바일 지원자 카드는 다음 행동이 빠른 순이고 날짜 없는 항목은 마지막이다", () => {
  const sorted = sortCandidatesByNextAction([
    activeCandidate({ id: 1, next_action_at: null }),
    activeCandidate({ id: 2, next_action_at: "2026-07-19T09:00:00+09:00" }),
    activeCandidate({ id: 3, next_action_at: "2026-07-18T09:00:00+09:00" }),
    {
      id: 4,
      stage: "ended",
      selection_status: "replaced",
      closed_message: "종료",
      created_at: "2026-07-01T09:00:00+09:00",
      updated_at: "2026-07-15T14:00:00+09:00",
    },
  ]);

  assert.deepEqual(sorted.map((candidate) => candidate.id), [3, 2, 1, 4]);
});

test("지원자 정렬은 모바일과 목록에서 같은 선택값을 따른다", () => {
  const candidates = [
    activeCandidate({ id: 1, name: "하나", created_at: "2026-07-10T09:00:00+09:00", next_action_at: null }),
    activeCandidate({ id: 2, name: "가람", created_at: "2026-07-17T09:00:00+09:00", next_action_at: "2026-07-19T09:00:00+09:00" }),
    activeCandidate({ id: 3, name: "나래", created_at: "2026-07-14T09:00:00+09:00", next_action_at: "2026-07-18T09:00:00+09:00" }),
  ];

  assert.deepEqual(sortRecruitingCandidates(candidates, "due").map((item) => item.id), [3, 2, 1]);
  assert.deepEqual(sortRecruitingCandidates(candidates, "newest").map((item) => item.id), [2, 3, 1]);
  assert.deepEqual(sortRecruitingCandidates(candidates, "name").map((item) => item.id), [2, 3, 1]);
});

test("최신 요청 세대만 데이터·오류·로딩 상태를 바꿀 수 있다", () => {
  const gate = createLatestRequestGate();
  const first = gate.begin();
  const second = gate.begin();

  assert.equal(gate.isCurrent(first), false);
  assert.equal(gate.isCurrent(second), true);

  let loading = true;
  if (gate.isCurrent(first)) loading = false;
  assert.equal(loading, true, "오래된 요청은 로딩을 끝내지 않는다");
  if (gate.isCurrent(second)) loading = false;
  assert.equal(loading, false, "최신 요청만 로딩을 끝낸다");

  gate.invalidate();
  assert.equal(gate.isCurrent(second), false, "저장 성공은 진행 중인 목록 응답을 무효화한다");
  const afterMutation = gate.begin();
  assert.equal(gate.isCurrent(afterMutation), true, "저장 뒤 최신 조건 재조회가 새 세대가 된다");
});

test("기존 4개 문구는 숨기거나 자르지 않고 3개로 줄일 때까지 저장을 안내한다", () => {
  const selected = [
    template(1, "support"),
    template(2, "support"),
    template(3, "faq"),
    template(4, "faq"),
  ];
  const available = [template(8, "headline"), ...selected];

  assert.deepEqual(getActiveSelectedTemplateIds(selected, available), [1, 2, 3, 4]);
  assert.equal(getRecruitingPageEditorIssue(8, 4), "too_many_templates");
  assert.equal(getRecruitingPageEditorIssue(8, 3), null);
});

test("첫 문장이 비어 있으면 문의와 재시도 전까지 저장을 잠근다", () => {
  assert.equal(getRecruitingPageEditorIssue(null, 0), "missing_headline");
});
