import type {
  PublicRecruitingApplicationResult,
  RecruitingCareerBand,
  RecruitingContactWindow,
} from "../../lib/api";

export const MANAGE_STORAGE_KEY = "inpa_recruiting_manage";

const SAFE_RECRUITING_TOKEN = /^[A-Za-z0-9._:-]+$/;
const MANAGE_PATH = /^\/r\/manage\/([A-Za-z0-9._:-]+)$/;

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface PublicApplicationFormValues {
  name: string;
  phone: string;
  careerBand: RecruitingCareerBand | "";
  currentAffiliation: string;
  region: string;
  contactWindow: RecruitingContactWindow | "";
  agreed: boolean;
}

export function isSafeRecruitingToken(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value !== "." &&
    value !== ".." &&
    SAFE_RECRUITING_TOKEN.test(value)
  );
}

export function getOrCreateSubmissionKey(
  current: string | null,
  create: () => string,
): string {
  if (current) return current;
  return create();
}

export function readStoredManageToken(storage: StorageLike | null): string | null {
  if (!storage) return null;
  try {
    const token = storage.getItem(MANAGE_STORAGE_KEY);
    if (!isSafeRecruitingToken(token)) {
      storage.removeItem(MANAGE_STORAGE_KEY);
      return null;
    }
    return token;
  } catch {
    return null;
  }
}

export function writeStoredManageToken(
  storage: StorageLike | null,
  token: unknown,
): boolean {
  if (!storage) return false;
  try {
    if (!isSafeRecruitingToken(token)) {
      storage.removeItem(MANAGE_STORAGE_KEY);
      return false;
    }
    storage.setItem(MANAGE_STORAGE_KEY, token);
    return true;
  } catch {
    return false;
  }
}

export function clearMatchingManageToken(
  storage: StorageLike | null,
  token: unknown,
): void {
  if (!storage || !isSafeRecruitingToken(token)) return;
  try {
    if (storage.getItem(MANAGE_STORAGE_KEY) === token) {
      storage.removeItem(MANAGE_STORAGE_KEY);
    }
  } catch {
    // Storage may be unavailable in privacy-restricted browsers.
  }
}

export function extractManageToken(path: unknown): string | null {
  if (typeof path !== "string") return null;
  const match = MANAGE_PATH.exec(path);
  if (!match || !isSafeRecruitingToken(match[1])) return null;
  return match[1];
}

export type ApplicationResultKind =
  | "submitted"
  | "choice_required"
  | "verification_required";

export function getApplicationResultKind(
  result: PublicRecruitingApplicationResult,
): ApplicationResultKind {
  if (result.submitted) return "submitted";
  if ("choice_required" in result && result.choice_required) return "choice_required";
  return "verification_required";
}

export type JoinErrorKind =
  | "switch_confirmation"
  | "expired"
  | "message"
  | "retry";

export function getJoinErrorKind(error: {
  status: number;
  code: string;
}): JoinErrorKind {
  if (error.status === 409 && error.code === "team_switch_confirmation_required") {
    return "switch_confirmation";
  }
  if (error.status === 410) return "expired";
  if (error.status === 409 || error.status === 400) return "message";
  return "retry";
}

export function validatePublicApplication(
  values: PublicApplicationFormValues,
): string | null {
  if (!values.name.trim()) return "이름을 입력해주세요.";
  if (!values.phone.trim()) return "연락처를 입력해주세요.";
  if (!values.careerBand) return "보험설계사 경력을 선택해주세요.";
  if (!values.region.trim()) return "활동 지역을 입력해주세요.";
  if (!values.contactWindow) return "연락받기 편한 시간을 선택해주세요.";
  if (!values.agreed) {
    return "개인정보 수집과 연락에 동의하면 지원 내용을 보낼 수 있어요.";
  }
  return null;
}

export function normalizePublicApplicationText(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}
