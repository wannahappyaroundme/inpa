"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  acceptRecruitingJoin,
  getProfile,
  getRecruitingJoinInfo,
  tokenStore,
  type RecruitingJoinInfo,
} from "../../lib/api";
import { clearAuthReturn, rememberAuthReturn } from "../../lib/auth-return";
import { ConfirmationDialog } from "./confirmation-dialog";
import {
  focusIfConnected,
  getJoinErrorKind,
  isSafeRecruitingToken,
  prepareRecruitingJoinAuthReturn,
  readStoredManageToken,
  shouldFocusJoinTerminalHeading,
  type StorageLike,
} from "./public-recruiting-view-model";
import {
  PUBLIC_PRIMARY_BUTTON,
  PUBLIC_SECONDARY_BUTTON,
  PublicPlannerCard,
  PublicRecruitingFrame,
  PublicRecruitingLoading,
  PublicRecruitingNotice,
} from "./public-recruiting-ui";

type InfoState = "loading" | "ready" | "retry" | "expired";
type AuthState = "checking" | "logged_out" | "ready" | "retry";

function browserStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function RecruitingJoin({ token }: { token: string }) {
  const router = useRouter();
  const [infoState, setInfoState] = useState<InfoState>("loading");
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [info, setInfo] = useState<RecruitingJoinInfo | null>(null);
  const [joinPending, setJoinPending] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [switchConfirmOpen, setSwitchConfirmOpen] = useState(false);
  const [joined, setJoined] = useState(false);
  const infoGenerationRef = useRef(0);
  const authGenerationRef = useRef(0);
  const terminalHeadingRef = useRef<HTMLHeadingElement>(null);

  const loadInfo = useCallback(async () => {
    const generation = ++infoGenerationRef.current;
    if (!isSafeRecruitingToken(token)) {
      setInfoState("expired");
      return;
    }
    setInfoState("loading");
    try {
      const response = await getRecruitingJoinInfo(token);
      if (generation !== infoGenerationRef.current) return;
      setInfo(response);
      setInfoState("ready");
    } catch (error) {
      if (generation !== infoGenerationRef.current) return;
      if (error instanceof ApiError && (error.status === 404 || error.status === 410)) {
        clearAuthReturn();
        setInfoState("expired");
      } else {
        setInfoState("retry");
      }
    }
  }, [token]);

  const checkAuth = useCallback(async () => {
    const generation = ++authGenerationRef.current;
    if (
      !prepareRecruitingJoinAuthReturn(token, {
        remember: rememberAuthReturn,
        clear: clearAuthReturn,
      })
    ) {
      setAuthState("logged_out");
      return;
    }
    if (!tokenStore.get()) {
      setAuthState("logged_out");
      return;
    }
    setAuthState("checking");
    try {
      const profile = await getProfile();
      if (generation !== authGenerationRef.current) return;
      if (!profile.onboarding_completed_at) {
        router.replace("/onboarding");
        return;
      }
      setAuthState("ready");
    } catch {
      if (generation !== authGenerationRef.current) return;
      if (tokenStore.get()) setAuthState("retry");
      else setAuthState("logged_out");
    }
  }, [router, token]);

  useEffect(() => {
    void loadInfo();
    void checkAuth();
    return () => {
      infoGenerationRef.current += 1;
      authGenerationRef.current += 1;
    };
  }, [checkAuth, loadInfo]);

  useEffect(() => {
    if (shouldFocusJoinTerminalHeading(infoState, joined)) {
      focusIfConnected(terminalHeadingRef.current);
    }
  }, [infoState, joined]);

  async function accept(confirmSwitch: boolean) {
    if (joinPending) return;
    const manageToken = readStoredManageToken(browserStorage());
    if (!manageToken) {
      setJoinError(
        "지원 신청 때 받은 내 지원 관리 링크를 먼저 열면 합류를 이어갈 수 있어요.",
      );
      return;
    }
    setJoinPending(true);
    setJoinError(null);
    try {
      await acceptRecruitingJoin(token, manageToken, confirmSwitch);
      clearAuthReturn();
      setSwitchConfirmOpen(false);
      setJoined(true);
    } catch (error) {
      if (error instanceof ApiError) {
        const kind = getJoinErrorKind(error);
        if (kind === "switch_confirmation") {
          if (confirmSwitch) {
            setSwitchConfirmOpen(false);
            setJoinError(error.message || "현재 팀 연결을 확인한 뒤 다시 선택해주세요.");
          } else {
            setSwitchConfirmOpen(true);
          }
        } else if (kind === "expired") {
          clearAuthReturn();
          setSwitchConfirmOpen(false);
          setInfoState("expired");
        } else if (kind === "message") {
          setSwitchConfirmOpen(false);
          setJoinError(error.message || "계정의 팀 연결을 확인하면 이어갈 수 있어요.");
        } else {
          setSwitchConfirmOpen(false);
          setJoinError("연결을 확인한 뒤 합류 요청을 다시 보내주세요.");
        }
      } else {
        setSwitchConfirmOpen(false);
        setJoinError("연결을 확인한 뒤 합류 요청을 다시 보내주세요.");
      }
    } finally {
      setJoinPending(false);
    }
  }

  if (infoState === "loading") return <PublicRecruitingLoading label="합류 정보를 불러오는 중이에요." />;
  if (infoState === "expired") {
    return (
      <PublicRecruitingNotice
        role="alert"
        headingRef={terminalHeadingRef}
        title="새 합류 링크에서 이어갈 수 있어요."
        description="리더에게 새 합류 링크를 받으면 바로 이어갈 수 있어요."
      />
    );
  }
  if (infoState === "retry" || !info) {
    return (
      <PublicRecruitingNotice
        role="alert"
        title="연결을 확인하면 합류 정보를 다시 볼 수 있어요."
        description="잠시 후 같은 링크에서 다시 확인해주세요."
        action={<button type="button" onClick={() => void loadInfo()} className={PUBLIC_PRIMARY_BUTTON}>다시 불러오기</button>}
      />
    );
  }
  if (joined) {
    return (
      <PublicRecruitingNotice
        role="status"
        headingRef={terminalHeadingRef}
        title="함께할 준비가 끝났어요."
        description="팀 연결이 완료됐어요. 이제 인파에서 함께 일할 흐름을 이어갈 수 있어요."
        action={<Link href="/home" className={PUBLIC_PRIMARY_BUTTON}>인파 홈으로 가기</Link>}
      />
    );
  }

  const planner = {
    display_name: info.display_name,
    affiliation: info.affiliation,
    title: info.title,
    profile_image: info.profile_image,
  };

  return (
    <PublicRecruitingFrame>
      <div className="space-y-5">
        <PublicPlannerCard planner={planner} />
        <section className="rounded-3xl border border-line bg-surface px-5 py-8 text-center shadow-card sm:px-8">
          <p className="text-[12px] font-bold text-brand">팀 합류 확인</p>
          <h1 className="mt-2 break-keep text-[24px] font-extrabold leading-9 text-ink">
            {info.headline || `${info.display_name} 리더와 함께할 준비가 됐어요.`}
          </h1>
          <p className="mx-auto mt-3 max-w-lg text-[14px] leading-6 text-ink3">
            합류를 확인하면 이 리더와 팀 연결이 시작되고 정착 일정을 함께 이어갈 수 있어요.
          </p>

          {authState === "checking" ? (
            <p role="status" aria-live="polite" className="mt-6 text-[13px] text-ink3">계정 상태를 확인하고 있어요.</p>
          ) : authState === "logged_out" ? (
            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
              <Link href="/login" className={PUBLIC_PRIMARY_BUTTON}>로그인하고 합류하기</Link>
              <Link href="/register" className={PUBLIC_SECONDARY_BUTTON}>처음이라면 가입하기</Link>
            </div>
          ) : authState === "retry" ? (
            <div className="mt-6">
              <p role="alert" className="text-[13px] leading-6 text-ink3">계정 연결을 확인한 뒤 다시 시도해주세요.</p>
              <button type="button" onClick={() => void checkAuth()} className={`${PUBLIC_PRIMARY_BUTTON} mt-3`}>계정 다시 확인하기</button>
            </div>
          ) : (
            <div className="mt-6">
              {joinError && <p role="alert" className="mb-3 text-[13px] leading-6 text-cnone">{joinError}</p>}
              <button type="button" disabled={joinPending} onClick={() => void accept(false)} className={`${PUBLIC_PRIMARY_BUTTON} w-full sm:w-auto`}>
                {joinPending ? "팀 연결을 확인하고 있어요" : "이 리더와 합류 확정하기"}
              </button>
            </div>
          )}
        </section>
      </div>

      <ConfirmationDialog
        open={switchConfirmOpen}
        title="팀 리더 연결을 변경할까요?"
        description="확인하면 현재 연결 대신 이 리더와 정착 일정을 이어가게 돼요."
        confirmLabel="이 리더로 변경하기"
        pendingLabel="연결을 변경하고 있어요"
        cancelLabel="현재 연결 유지하기"
        pending={joinPending}
        onClose={() => setSwitchConfirmOpen(false)}
        onConfirm={() => void accept(true)}
      />
    </PublicRecruitingFrame>
  );
}
