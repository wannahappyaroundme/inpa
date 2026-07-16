import { ApiError } from "../../lib/api";
import type {
  RecruitingCareerBand,
  RecruitingContactWindow,
  RecruitingNextAction,
  RecruitingStage,
  SettlementBlocker,
  SettlementNextSupport,
  SettlementState,
} from "../../lib/api";

export const STAGE_LABELS: Record<RecruitingStage, string> = {
  new: "새 지원",
  contact: "연락",
  conversation: "대화·면담",
  preparing: "위촉 준비",
  team_join: "팀 합류",
  recontact: "다시 연락",
  ended: "종료",
};

export const CAREER_LABELS: Record<RecruitingCareerBand, string> = {
  under_1: "1년 미만",
  "1_3": "1~3년",
  "3_5": "3~5년",
  "5_10": "5~10년",
  "10_plus": "10년 이상",
};

export const CONTACT_LABELS: Record<RecruitingContactWindow, string> = {
  morning: "오전",
  afternoon: "오후",
  evening: "저녁",
  anytime: "언제든",
};

export const NEXT_ACTION_LABELS: Record<RecruitingNextAction, string> = {
  call: "전화",
  message: "메시지",
  meeting: "미팅",
  follow_up: "다시 확인",
  none: "없음",
};

export const SETTLEMENT_STATE_LABELS: Record<SettlementState, string> = {
  active: "활동 이어가는 중",
  support_needed: "도움 필요",
  stopped: "활동 중단",
};

export const BLOCKER_LABELS: Record<SettlementBlocker, string> = {
  customer_prospecting: "고객 찾기",
  consultation_prep: "상담 준비",
  product_understanding: "상품 이해",
  work_tools: "업무 도구",
  time_management: "시간 관리",
  organization_adjustment: "새 조직 적응",
  personal: "개인 일정",
  none: "해당 없음",
};

export const SUPPORT_LABELS: Record<SettlementNextSupport, string> = {
  consultation_prep: "상담 준비 함께하기",
  training: "교육 연결하기",
  activity_plan: "활동 계획 세우기",
  tool_help: "도구 사용 돕기",
  leader_meeting: "리더와 이야기하기",
  schedule_only: "다음 일정 잡기",
  close: "확인 마무리",
};

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value.length === 10 ? `${value}T00:00:00+09:00` : value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function toDateTimeInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
}

export function friendlyRecruitingError(
  error: unknown,
  fallback = "잠시 후 다시 확인하면 이어갈 수 있어요.",
): string {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 404) {
    return "설정을 확인하면 설계사 영입을 이어갈 수 있어요.";
  }
  if ([400, 402, 409, 410].includes(error.status) && error.message) {
    return error.message;
  }
  return fallback;
}
