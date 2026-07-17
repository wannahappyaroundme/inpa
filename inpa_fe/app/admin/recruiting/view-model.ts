export type AdminRecruitingStage =
  | "new"
  | "contact"
  | "conversation"
  | "preparing"
  | "team_join"
  | "recontact"
  | "ended";

export type AdminRecruitingEventType =
  | "stage_changed"
  | "contact_stopped"
  | "leader_changed"
  | "team_joined"
  | "settlement_completed"
  | "settlement_reopened"
  | "candidate_purged";

export type AdminRecruitingTemplateKind =
  | "headline"
  | "support"
  | "faq"
  | "share";

export type AdminRecruitingPurgeReason =
  | "user_request"
  | "retention"
  | "admin_correction";

export const RECRUITING_STAGE_LABELS: Record<AdminRecruitingStage, string> = {
  new: "새 지원",
  contact: "연락",
  conversation: "대화·면담",
  preparing: "위촉 준비",
  team_join: "팀 합류",
  recontact: "다시 연락",
  ended: "종료",
};

export const RECRUITING_EVENT_LABELS: Record<AdminRecruitingEventType, string> = {
  stage_changed: "단계 변경",
  contact_stopped: "연락 중단",
  leader_changed: "담당 변경",
  team_joined: "팀 합류",
  settlement_completed: "정착 확인",
  settlement_reopened: "정착 일정 재개",
  candidate_purged: "정보 정리",
};

export const RECRUITING_TEMPLATE_KIND_LABELS: Record<
  AdminRecruitingTemplateKind,
  string
> = {
  headline: "첫 문장",
  support: "정착 지원",
  faq: "자주 묻는 질문",
  share: "공유 안내",
};

export const PURGE_REASON_LABELS: Record<AdminRecruitingPurgeReason, string> = {
  user_request: "지원자 요청",
  retention: "보관 기간 만료",
  admin_correction: "운영 정보 바로잡기",
};

export function getRecruitingActorLabel(
  eventType: AdminRecruitingEventType,
  actorId: number | null,
): string {
  if (actorId !== null) return `처리 계정 #${actorId}`;
  if (eventType === "contact_stopped") return "지원자 요청";
  if (eventType === "leader_changed") return "지원자 선택";
  return "시스템 처리";
}

export function getCandidateContactStatusLabel(
  stage: AdminRecruitingStage,
  contactOptedOut: boolean,
): string {
  if (contactOptedOut) return "연락 중단 기록 있음";
  if (stage === "team_join") return "팀 합류";
  if (stage === "ended") return "지원 종료";
  return "연락 중단 기록 없음";
}

export function focusAdminRecruitingTarget(
  target: { isConnected: boolean; focus: () => void } | null,
): void {
  if (target?.isConnected) target.focus();
}

export function shouldRefreshCandidatesAfterPurge(
  dialogOpen: boolean,
  refreshQueued: boolean,
): boolean {
  return !dialogOpen && refreshQueued;
}

export function normalizeAdminRecruitingPage(value: number): number {
  return Number.isSafeInteger(value) && value > 0 ? value : 1;
}

export interface AdminRecruitingTemplateDraft {
  code: string;
  kind: AdminRecruitingTemplateKind;
  title: string;
  body: string;
  sortOrder: number;
}

export function getRecruitingTemplateIssue(
  draft: AdminRecruitingTemplateDraft,
  mode: "create" | "edit",
): string | null {
  if (mode === "create") {
    const code = draft.code.trim();
    if (!code) return "코드를 입력해주세요.";
    if (code.length > 60) return "코드는 60자까지 입력할 수 있어요.";
    if (!/^[a-z0-9]+(?:[-_][a-z0-9]+)*$/.test(code)) {
      return "코드는 영문 소문자와 숫자, 하이픈, 밑줄만 사용할 수 있어요.";
    }
  }

  const title = draft.title.trim();
  if (!title) return "제목을 입력해주세요.";
  if (title.length > 80) return "제목은 80자까지 입력할 수 있어요.";

  const body = draft.body.trim();
  if (!body) return "내용을 입력해주세요.";
  if (body.length > 300) return "내용은 300자까지 입력할 수 있어요.";

  if (
    !Number.isSafeInteger(draft.sortOrder) ||
    draft.sortOrder < 0 ||
    draft.sortOrder > 32767
  ) {
    return "정렬 순서는 0부터 32767 사이의 정수로 입력해주세요.";
  }

  return null;
}

export interface AdminRecruitingFailure {
  message: string;
  needsAdminLogin: boolean;
}

export function getAdminRecruitingFailure(
  status: number | null,
  apiMessage: string,
  fallback: string,
): AdminRecruitingFailure {
  if (status === 403) {
    return {
      message: "관리자 계정으로 로그인하면 영입 운영 정보를 확인할 수 있어요.",
      needsAdminLogin: true,
    };
  }
  return {
    message: apiMessage.trim() || fallback,
    needsAdminLogin: false,
  };
}

export function getRecruitingRolloutCopy(enabled: boolean): {
  label: string;
  description: string;
} {
  return enabled
    ? {
        label: "설계사 화면 공개 중",
        description: "설계사 영입 화면이 현재 공개되어 있어요.",
      }
    : {
        label: "설계사 화면 공개 전",
        description: "문구와 정보 정리 기준은 지금 확인하고 준비할 수 있어요.",
      };
}

export interface LatestRequestGate {
  begin: () => number;
  invalidate: () => void;
  isCurrent: (generation: number) => boolean;
}

export function createLatestRequestGate(): LatestRequestGate {
  let generation = 0;
  return {
    begin() {
      generation += 1;
      return generation;
    },
    invalidate() {
      generation += 1;
    },
    isCurrent(requestGeneration) {
      return requestGeneration === generation;
    },
  };
}
