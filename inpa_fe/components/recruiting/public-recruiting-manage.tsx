"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  getPublicRecruitingManage,
  stopPublicRecruitingManage,
  type PublicRecruitingManage,
} from "../../lib/api";
import { ConfirmationDialog } from "./confirmation-dialog";
import { formatDate, STAGE_LABELS } from "./recruiting-labels";
import {
  clearMatchingManageToken,
  focusIfConnected,
  getStopFailurePresentation,
  isSafeRecruitingToken,
  readStoredManageToken,
  shouldFocusManageTerminalHeading,
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

type ManageState = "loading" | "ready" | "retry" | "unavailable" | "account";

function browserStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function terminalTokenError(error: unknown) {
  return error instanceof ApiError && (error.status === 404 || error.status === 410);
}

export function PublicRecruitingManageView({ token }: { token: string }) {
  const [state, setState] = useState<ManageState>("loading");
  const [data, setData] = useState<PublicRecruitingManage | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [stopPending, setStopPending] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const generationRef = useRef(0);
  const terminalHeadingRef = useRef<HTMLHeadingElement>(null);

  const clearStoredMatch = useCallback(() => {
    const storage = browserStorage();
    readStoredManageToken(storage);
    clearMatchingManageToken(storage, token);
  }, [token]);

  const load = useCallback(async () => {
    const generation = ++generationRef.current;
    if (!isSafeRecruitingToken(token)) {
      clearStoredMatch();
      setState("unavailable");
      return;
    }
    setState("loading");
    try {
      const response = await getPublicRecruitingManage(token);
      if (generation !== generationRef.current) return;
      setData(response);
      if (response.contact_stopped) clearStoredMatch();
      setState("ready");
    } catch (error) {
      if (generation !== generationRef.current) return;
      if (terminalTokenError(error)) {
        clearStoredMatch();
        setState("unavailable");
      } else {
        setState("retry");
      }
    }
  }, [clearStoredMatch, token]);

  useEffect(() => {
    void load();
    return () => {
      generationRef.current += 1;
    };
  }, [load]);

  useEffect(() => {
    if (shouldFocusManageTerminalHeading(state, Boolean(data?.contact_stopped))) {
      focusIfConnected(terminalHeadingRef.current);
    }
  }, [data, state]);

  async function stopContact() {
    if (stopPending) return;
    setStopPending(true);
    setStopError(null);
    try {
      const response = await stopPublicRecruitingManage(token);
      clearStoredMatch();
      setData({
        contact_stopped: true,
        submitted_at: data?.submitted_at ?? new Date().toISOString(),
        message: response.message,
      });
      setMessage(response.message);
      setConfirmOpen(false);
      setState("ready");
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        error.code === "team_account_management_required"
      ) {
        setMessage(error.message);
        setConfirmOpen(false);
        setState("account");
      } else if (terminalTokenError(error)) {
        clearStoredMatch();
        setConfirmOpen(false);
        setState("unavailable");
      } else if (error instanceof ApiError && error.status === 429) {
        const presentation = getStopFailurePresentation("잠시 후 연락 중단 요청을 다시 보내주세요.");
        setConfirmOpen(presentation.dialogOpen);
        setStopError(presentation.inlineError);
      } else {
        const presentation = getStopFailurePresentation("연결을 확인한 뒤 연락 중단 요청을 다시 보내주세요.");
        setConfirmOpen(presentation.dialogOpen);
        setStopError(presentation.inlineError);
      }
    } finally {
      setStopPending(false);
    }
  }

  if (state === "loading") return <PublicRecruitingLoading label="지원 상태를 불러오는 중이에요." />;
  if (state === "unavailable") {
    return (
      <PublicRecruitingNotice
        role="alert"
        headingRef={terminalHeadingRef}
        title="지원 상태는 새 링크에서 이어서 확인할 수 있어요."
        description="이 링크를 보내주신 설계사에게 새 링크를 받아보세요."
      />
    );
  }
  if (state === "retry") {
    return (
      <PublicRecruitingNotice
        role="alert"
        title="연결을 확인하면 지원 상태를 다시 볼 수 있어요."
        description="브라우저에 저장된 관리 링크는 그대로 유지돼요."
        action={
          <button type="button" onClick={() => void load()} className={PUBLIC_PRIMARY_BUTTON}>
            다시 불러오기
          </button>
        }
      />
    );
  }
  if (state === "account") {
    return (
      <PublicRecruitingNotice
        role="status"
        headingRef={terminalHeadingRef}
        title="인파 계정에서 팀 연결을 확인할 수 있어요."
        description={message || "연결 상태를 확인하고 정보 정리는 문의함에서 요청할 수 있어요."}
        action={
          <>
            <Link href="/settings/account" className={PUBLIC_PRIMARY_BUTTON}>계정에서 연결 상태 확인하기</Link>
            <Link href="/boards/inquiry/new" className={PUBLIC_SECONDARY_BUTTON}>문의 남기기</Link>
          </>
        }
      />
    );
  }
  if (!data) return null;
  if (data.contact_stopped) {
    return (
      <PublicRecruitingFrame>
        <section role="status" className="rounded-3xl border border-line bg-surface px-5 py-10 text-center shadow-card sm:px-8">
          <h1
            ref={terminalHeadingRef}
            tabIndex={-1}
            className="text-[20px] font-extrabold text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            연락 중단 요청을 반영했어요.
          </h1>
          <p className="mt-3 text-[14px] leading-6 text-ink3">{message || data.message}</p>
          <dl className="mx-auto mt-5 max-w-xs rounded-2xl bg-surface2 p-4">
            <dt className="text-[12px] text-ink3">지원한 날</dt>
            <dd className="mt-1 text-[14px] font-bold text-ink">{formatDate(data.submitted_at)}</dd>
          </dl>
        </section>
      </PublicRecruitingFrame>
    );
  }

  const canStop = data.stage !== "team_join" && data.stage !== "ended";
  return (
    <PublicRecruitingFrame>
      <div className="space-y-5">
        <PublicPlannerCard planner={data.leader} />
        <section className="rounded-3xl border border-line bg-surface p-5 shadow-card sm:p-7">
          <p className="text-[12px] font-bold text-brand">내 지원 상태</p>
          <h1 className="mt-2 text-[22px] font-extrabold text-ink">{STAGE_LABELS[data.stage]}</h1>
          <dl className="mt-5 grid gap-3 rounded-2xl bg-surface2 p-4 sm:grid-cols-2">
            <div>
              <dt className="text-[12px] text-ink3">지원한 날</dt>
              <dd className="mt-1 text-[14px] font-bold text-ink">{formatDate(data.submitted_at)}</dd>
            </div>
            <div>
              <dt className="text-[12px] text-ink3">연락 상태</dt>
              <dd className="mt-1 text-[14px] font-bold text-ink">
                {data.stage === "team_join"
                  ? "팀 연결됨"
                  : data.stage === "ended"
                    ? "대화 마무리"
                    : "연락 이어가는 중"}
              </dd>
            </div>
          </dl>
          {data.stage === "team_join" ? (
            <div className="mt-6 rounded-2xl border border-line bg-surface2 p-4">
              <p className="text-[13px] leading-6 text-ink2">팀 연결은 인파 계정에서 확인하고 관리할 수 있어요.</p>
              <div className="mt-4 flex flex-col gap-3">
                <Link href="/settings/account" className={`${PUBLIC_PRIMARY_BUTTON} w-full`}>계정에서 연결 상태 확인하기</Link>
                <Link href="/boards/inquiry/new" className={`${PUBLIC_SECONDARY_BUTTON} w-full`}>문의 남기기</Link>
              </div>
            </div>
          ) : data.stage === "ended" ? (
            <p role="status" className="mt-6 rounded-2xl bg-surface2 p-4 text-[13px] leading-6 text-ink2">지원 대화가 마무리됐어요.</p>
          ) : (
            <div className="mt-6 border-t border-line pt-5">
              <p className="text-[13px] leading-6 text-ink3">더 이상 영입 연락을 원하지 않으면 여기에서 바로 멈출 수 있어요.</p>
              <button type="button" onClick={() => setConfirmOpen(true)} className={`${PUBLIC_SECONDARY_BUTTON} mt-3 w-full`}>연락 그만 받기</button>
              {stopError && <p role="alert" className="mt-3 text-[13px] leading-5 text-cnone">{stopError}</p>}
            </div>
          )}
        </section>
      </div>
      {canStop && (
        <ConfirmationDialog
          open={confirmOpen}
          title="영입 연락을 그만 받을까요?"
          description="확인하면 담당 설계사의 연락을 멈추고 남은 정보 정리 절차가 시작돼요."
          confirmLabel="연락 그만 받기"
          pendingLabel="요청을 보내는 중이에요"
          cancelLabel="연락 계속 받을게요"
          pending={stopPending}
          onClose={() => setConfirmOpen(false)}
          onConfirm={() => void stopContact()}
        />
      )}
    </PublicRecruitingFrame>
  );
}
