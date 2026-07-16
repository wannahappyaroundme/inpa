import type {
  RecruitingCandidate,
  RecruitingCareerBand,
  RecruitingContactWindow,
  RecruitingSettlement,
  RecruitingStage,
} from "../../lib/api";

export const RECRUITING_TABS = [
  "status",
  "page",
  "campaign",
  "settlement",
] as const;

export type RecruitingTab = (typeof RECRUITING_TABS)[number];

export function normalizeRecruitingTab(value: string | null | undefined): RecruitingTab {
  return RECRUITING_TABS.includes(value as RecruitingTab)
    ? (value as RecruitingTab)
    : "status";
}

export type CandidateDisplayIdentity =
  | {
      kind: "applicant";
      displayName: string;
      phone: string;
      careerBand: RecruitingCareerBand;
      currentAffiliation: string;
      region: string;
      contactWindow: RecruitingContactWindow;
    }
  | {
      kind: "joined";
      displayName: string;
      profileImage: string | null;
      phone: null;
    }
  | {
      kind: "closed";
      displayName: "지원 종료";
      closedMessage: string;
      closedAt: string;
      phone: null;
    };

export function getCandidateDisplayIdentity(
  candidate: RecruitingCandidate,
): CandidateDisplayIdentity {
  if (candidate.selection_status === "replaced") {
    return {
      kind: "closed",
      displayName: "지원 종료",
      closedMessage: candidate.closed_message,
      closedAt: candidate.updated_at,
      phone: null,
    };
  }

  if (candidate.stage === "team_join") {
    return {
      kind: "joined",
      displayName: candidate.joined_agent?.display_name || "합류 설계사",
      profileImage: candidate.joined_agent?.profile_image ?? null,
      phone: null,
    };
  }

  return {
    kind: "applicant",
    displayName: candidate.name,
    phone: candidate.phone,
    careerBand: candidate.career_band,
    currentAffiliation: candidate.current_affiliation,
    region: candidate.region,
    contactWindow: candidate.contact_window,
  };
}

export interface SettlementDueGroups {
  past: RecruitingSettlement[];
  today: RecruitingSettlement[];
  upcoming: RecruitingSettlement[];
  completed: RecruitingSettlement[];
}

export function groupSettlementsByDue(
  settlements: RecruitingSettlement[],
  today: string,
): SettlementDueGroups {
  const groups: SettlementDueGroups = {
    past: [],
    today: [],
    upcoming: [],
    completed: [],
  };

  for (const settlement of settlements) {
    if (settlement.completed_at) groups.completed.push(settlement);
    else if (settlement.due_on < today) groups.past.push(settlement);
    else if (settlement.due_on === today) groups.today.push(settlement);
    else groups.upcoming.push(settlement);
  }

  const byDue = (left: RecruitingSettlement, right: RecruitingSettlement) =>
    left.due_on.localeCompare(right.due_on) || left.week - right.week || left.id - right.id;
  groups.past.sort(byDue);
  groups.today.sort(byDue);
  groups.upcoming.sort(byDue);
  groups.completed.sort((left, right) => {
    const completed = (right.completed_at ?? "").localeCompare(left.completed_at ?? "");
    return completed || byDue(left, right);
  });
  return groups;
}

const MANUAL_STAGE_CHOICES: Record<RecruitingStage, RecruitingStage[]> = {
  new: ["contact", "recontact", "ended"],
  contact: ["conversation", "recontact", "ended"],
  conversation: ["preparing", "recontact", "ended"],
  preparing: ["conversation", "recontact", "ended"],
  team_join: [],
  recontact: ["contact", "ended"],
  ended: ["recontact"],
};

export function allowedManualStageChoices(
  candidate: RecruitingCandidate,
): RecruitingStage[] {
  if (candidate.selection_status === "replaced") return [];
  return [...MANUAL_STAGE_CHOICES[candidate.stage]];
}

export function sortCandidatesByNextAction(
  candidates: RecruitingCandidate[],
): RecruitingCandidate[] {
  return candidates
    .map((candidate, index) => ({ candidate, index }))
    .sort((left, right) => {
      const leftDate =
        left.candidate.selection_status === "active" && left.candidate.next_action_at
          ? Date.parse(left.candidate.next_action_at)
          : Number.POSITIVE_INFINITY;
      const rightDate =
        right.candidate.selection_status === "active" && right.candidate.next_action_at
          ? Date.parse(right.candidate.next_action_at)
          : Number.POSITIVE_INFINITY;
      return leftDate - rightDate || left.index - right.index;
    })
    .map(({ candidate }) => candidate);
}
