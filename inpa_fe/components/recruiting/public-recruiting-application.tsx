"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  applyPublicRecruitingCampaign,
  getPublicRecruitingPage,
  submitPublicRecruitingLeaderChoice,
  type PublicRecruitingApplicationResult,
  type PublicRecruitingChoiceRequired,
  type PublicRecruitingPage,
  type PublicRecruitingSubmitted,
} from "../../lib/api";
import { CAREER_LABELS, CONTACT_LABELS } from "./recruiting-labels";
import {
  extractManageToken,
  getApplicationResultKind,
  getOrCreateSubmissionKey,
  isSafeRecruitingToken,
  normalizePublicApplicationText,
  readStoredManageToken,
  validatePublicApplication,
  writeStoredManageToken,
  type PublicApplicationFormValues,
  type StorageLike,
} from "./public-recruiting-view-model";
import {
  PUBLIC_PRIMARY_BUTTON,
  PublicPlannerCard,
  PublicRecruitingFrame,
  PublicRecruitingLoading,
  PublicRecruitingNotice,
} from "./public-recruiting-ui";

const EMPTY_FORM: PublicApplicationFormValues = {
  name: "",
  phone: "",
  careerBand: "",
  currentAffiliation: "",
  region: "",
  contactWindow: "",
  agreed: false,
};

type LoadState = "loading" | "ready" | "unavailable" | "retry";
type LeaderChoice = "keep_current" | "switch_to_new";

function browserStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isTerminalLinkError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.status === 410);
}

function InputLabel({ htmlFor, children }: { htmlFor: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-2 block text-[13px] font-bold text-ink2">
      {children}
    </label>
  );
}

const FIELD_CLASS =
  "min-h-12 w-full rounded-2xl border border-line bg-surface px-4 text-[15px] text-ink outline-none transition placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:bg-surface2 disabled:text-ink3";

export function PublicRecruitingApplication({ token }: { token: string }) {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [page, setPage] = useState<PublicRecruitingPage | null>(null);
  const [form, setForm] = useState<PublicApplicationFormValues>(EMPTY_FORM);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PublicRecruitingApplicationResult | null>(null);
  const [manageToken, setManageToken] = useState<string | null>(null);
  const [leaderChoice, setLeaderChoice] = useState<LeaderChoice | null>(null);
  const [choicePending, setChoicePending] = useState(false);
  const [choiceError, setChoiceError] = useState<string | null>(null);
  const submissionKeyRef = useRef<string | null>(null);
  const loadGenerationRef = useRef(0);

  const loadPage = useCallback(async () => {
    const generation = ++loadGenerationRef.current;
    if (!isSafeRecruitingToken(token)) {
      setLoadState("unavailable");
      return;
    }
    setLoadState("loading");
    try {
      const response = await getPublicRecruitingPage(token);
      if (generation !== loadGenerationRef.current) return;
      setPage(response);
      setLoadState("ready");
    } catch (loadError) {
      if (generation !== loadGenerationRef.current) return;
      setLoadState(isTerminalLinkError(loadError) ? "unavailable" : "retry");
    }
  }, [token]);

  useEffect(() => {
    void loadPage();
    return () => {
      loadGenerationRef.current += 1;
    };
  }, [loadPage]);

  function updateForm<Key extends keyof PublicApplicationFormValues>(
    key: Key,
    value: PublicApplicationFormValues[Key],
  ) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function completeSubmission(response: PublicRecruitingSubmitted) {
    const nextManageToken = extractManageToken(response.manage_url);
    if (nextManageToken) {
      writeStoredManageToken(browserStorage(), nextManageToken);
    }
    setManageToken(nextManageToken);
    setResult(response);
    submissionKeyRef.current = null;
  }

  async function submitApplication(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!page || pending) return;
    setError(null);
    const validationError = validatePublicApplication(form);
    if (validationError) {
      setError(validationError);
      return;
    }

    let submissionKey: string;
    try {
      submissionKey = getOrCreateSubmissionKey(
        submissionKeyRef.current,
        () => window.crypto.randomUUID(),
      );
    } catch {
      setError("브라우저를 새로 열면 지원 내용을 안전하게 보낼 수 있어요.");
      return;
    }
    submissionKeyRef.current = submissionKey;
    setPending(true);
    try {
      const response = await applyPublicRecruitingCampaign(token, {
        name: normalizePublicApplicationText(form.name),
        phone: form.phone.trim(),
        career_band: form.careerBand as Exclude<typeof form.careerBand, "">,
        current_affiliation: normalizePublicApplicationText(form.currentAffiliation),
        region: normalizePublicApplicationText(form.region),
        contact_window: form.contactWindow as Exclude<typeof form.contactWindow, "">,
        submission_key: submissionKey,
        prior_manage_token: readStoredManageToken(browserStorage()),
        agreed: true,
      });
      const kind = getApplicationResultKind(response);
      if (kind === "submitted") {
        completeSubmission(response as PublicRecruitingSubmitted);
      } else {
        setResult(response);
        setLeaderChoice(null);
      }
    } catch (submitError) {
      if (isTerminalLinkError(submitError)) {
        setLoadState("unavailable");
      } else if (submitError instanceof ApiError && submitError.status === 429) {
        setError(submitError.message || "잠시 후 같은 내용으로 다시 보내주세요.");
      } else if (submitError instanceof ApiError && submitError.status === 400) {
        setError(submitError.message || "입력한 내용을 한 번 더 확인해주세요.");
      } else {
        setError("연결을 확인한 뒤 같은 내용으로 다시 보내주세요.");
      }
    } finally {
      setPending(false);
    }
  }

  async function submitLeaderChoice() {
    if (
      !leaderChoice ||
      choicePending ||
      !result ||
      getApplicationResultKind(result) !== "choice_required"
    ) {
      return;
    }
    const choiceResult = result as PublicRecruitingChoiceRequired;
    setChoiceError(null);
    setChoicePending(true);
    try {
      const response = await submitPublicRecruitingLeaderChoice(
        choiceResult.choice_token,
        leaderChoice,
      );
      completeSubmission(response);
    } catch (submitError) {
      if (isTerminalLinkError(submitError)) {
        setChoiceError("이 링크를 보내주신 설계사에게 새 링크를 받아보세요.");
      } else if (submitError instanceof ApiError && submitError.status === 429) {
        setChoiceError("잠시 후 선택한 담당자로 다시 이어가주세요.");
      } else {
        setChoiceError("연결을 확인한 뒤 선택한 담당자로 다시 이어가주세요.");
      }
    } finally {
      setChoicePending(false);
    }
  }

  if (loadState === "loading") return <PublicRecruitingLoading />;
  if (loadState === "unavailable") {
    return (
      <PublicRecruitingNotice
        role="alert"
        title="새 링크에서 지원을 이어갈 수 있어요."
        description="이 링크를 보내주신 설계사에게 새 링크를 받아보세요."
      />
    );
  }
  if (loadState === "retry" || !page) {
    return (
      <PublicRecruitingNotice
        role="alert"
        title="연결을 확인하면 지원 화면을 다시 열 수 있어요."
        description="입력한 내용은 이 브라우저 화면에 그대로 남아 있어요."
        action={
          <button type="button" onClick={() => void loadPage()} className={PUBLIC_PRIMARY_BUTTON}>
            다시 불러오기
          </button>
        }
      />
    );
  }

  if (result && getApplicationResultKind(result) === "submitted") {
    return (
      <PublicRecruitingNotice
        role="status"
        title="지원 내용을 잘 보냈어요."
        description={(result as PublicRecruitingSubmitted).message}
        action={
          manageToken ? (
            <Link href={`/r/manage/${manageToken}`} className={PUBLIC_PRIMARY_BUTTON}>
              내 지원 상태 확인
            </Link>
          ) : (
            <p role="alert" className="text-[13px] leading-6 text-ink3">
              지원 상태 링크는 담당 설계사에게 확인해주세요.
            </p>
          )
        }
      />
    );
  }

  const choiceResult =
    result && getApplicationResultKind(result) === "choice_required"
      ? (result as PublicRecruitingChoiceRequired)
      : null;
  const verificationResult =
    result && getApplicationResultKind(result) === "verification_required" ? result : null;
  const publicTemplates = [...page.support, ...page.faq].slice(0, 3);

  return (
    <PublicRecruitingFrame>
      <div className="space-y-5 sm:space-y-6">
        <PublicPlannerCard planner={page.planner} />

        <section className="rounded-3xl border border-line bg-surface px-5 py-7 shadow-card sm:px-7">
          <p className="text-[12px] font-bold text-brand">함께할 설계사 동료를 찾고 있어요</p>
          <h1 className="mt-2 break-keep text-[24px] font-extrabold leading-9 text-ink sm:text-[30px] sm:leading-10">
            {page.headline?.body || "함께 오래 일할 동료를 찾고 있어요"}
          </h1>
          {page.activity_region && (
            <p className="mt-3 text-[13px] text-ink3">주요 활동 지역: {page.activity_region}</p>
          )}
        </section>

        {publicTemplates.length > 0 && (
          <section aria-labelledby="recruiting-support-title">
            <h2 id="recruiting-support-title" className="text-[18px] font-extrabold text-ink">
              함께 일하는 방식
            </h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {publicTemplates.map((template) =>
                template.kind === "faq" ? (
                  <details key={template.id} className="rounded-2xl border border-line bg-surface p-5 shadow-card open:border-brand/30">
                    <summary className="min-h-11 cursor-pointer list-none text-[14px] font-bold leading-6 text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                      {template.title}
                    </summary>
                    <p className="pt-2 text-[13px] leading-6 text-ink3">{template.body}</p>
                  </details>
                ) : (
                  <article key={template.id} className="rounded-2xl border border-line bg-surface p-5 shadow-card">
                    <h3 className="text-[14px] font-bold text-ink">{template.title}</h3>
                    <p className="mt-2 text-[13px] leading-6 text-ink3">{template.body}</p>
                  </article>
                ),
              )}
            </div>
          </section>
        )}

        {verificationResult ? (
          <section role="status" className="rounded-3xl border border-line bg-surface px-5 py-8 text-center shadow-card sm:px-7">
            <h2 className="text-[19px] font-extrabold text-ink">이전 지원 상태를 먼저 확인해주세요.</h2>
            <p className="mt-3 text-[14px] leading-6 text-ink3">
              {"message" in verificationResult ? verificationResult.message : "이전 신청 관리 링크를 열면 담당자 선택을 이어갈 수 있어요."}
            </p>
          </section>
        ) : choiceResult ? (
          <section className="rounded-3xl border border-line bg-surface p-5 shadow-card sm:p-7">
            <h2 className="text-[19px] font-extrabold text-ink">어느 담당자와 이어갈까요?</h2>
            <p className="mt-2 text-[13px] leading-6 text-ink3">선택한 담당자에게만 현재 지원 대화가 이어져요.</p>
            <fieldset disabled={choicePending} className="mt-5 space-y-3">
              <legend className="sr-only">담당자 선택</legend>
              {([
                ["keep_current", "현재 담당자 유지", choiceResult.current_leader],
                ["switch_to_new", "새 담당자 선택", choiceResult.new_leader],
              ] as const).map(([value, label, leader]) => (
                <label
                  key={value}
                  className={`flex min-h-[72px] cursor-pointer items-center gap-3 rounded-2xl border p-4 transition focus-within:ring-2 focus-within:ring-brand ${
                    leaderChoice === value ? "border-brand bg-brand-soft" : "border-line bg-surface"
                  }`}
                >
                  <input
                    type="radio"
                    name="leader-choice"
                    value={value}
                    checked={leaderChoice === value}
                    onChange={() => setLeaderChoice(value)}
                    className="h-5 w-5 shrink-0 accent-[var(--brand)]"
                  />
                  <span className="min-w-0">
                    <span className="block text-[12px] font-bold text-brand">{label}</span>
                    <span className="mt-1 block break-words text-[14px] font-bold text-ink">{leader.display_name}</span>
                    {leader.affiliation && <span className="mt-0.5 block break-words text-[12px] text-ink3">{leader.affiliation}</span>}
                  </span>
                </label>
              ))}
            </fieldset>
            {choiceError && <p role="alert" className="mt-3 text-[13px] leading-5 text-cnone">{choiceError}</p>}
            <button
              type="button"
              disabled={!leaderChoice || choicePending}
              onClick={() => void submitLeaderChoice()}
              className={`${PUBLIC_PRIMARY_BUTTON} mt-5 w-full`}
            >
              {choicePending ? "선택을 이어가는 중이에요" : "선택한 담당자와 이어가기"}
            </button>
          </section>
        ) : (
          <section className="rounded-3xl border border-line bg-surface p-5 shadow-card sm:p-7">
            <h2 className="text-[19px] font-extrabold text-ink">먼저 편하게 이야기 나눠보세요.</h2>
            <p className="mt-2 text-[13px] leading-6 text-ink3">현재 소속과 경력에 맞춰 담당 설계사가 직접 연락드려요.</p>
            <form onSubmit={submitApplication} className="mt-6 space-y-5" noValidate>
              <fieldset disabled={pending} className="space-y-5">
                <legend className="sr-only">설계사 동료 지원 정보</legend>
                <div>
                  <InputLabel htmlFor="recruit-name">이름</InputLabel>
                  <input id="recruit-name" name="name" autoComplete="name" maxLength={30} value={form.name} onChange={(event) => updateForm("name", event.target.value)} className={FIELD_CLASS} required />
                </div>
                <div>
                  <InputLabel htmlFor="recruit-phone">연락처</InputLabel>
                  <input id="recruit-phone" name="tel" type="tel" inputMode="tel" autoComplete="tel" maxLength={30} placeholder="010-1234-5678" value={form.phone} onChange={(event) => updateForm("phone", event.target.value)} className={FIELD_CLASS} required />
                </div>
                <div>
                  <InputLabel htmlFor="recruit-career">보험설계사 경력</InputLabel>
                  <select id="recruit-career" value={form.careerBand} onChange={(event) => updateForm("careerBand", event.target.value as PublicApplicationFormValues["careerBand"])} className={FIELD_CLASS} required>
                    <option value="">경력을 선택해주세요</option>
                    {Object.entries(CAREER_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>
                <div>
                  <InputLabel htmlFor="recruit-affiliation">현재 소속 (선택)</InputLabel>
                  <input id="recruit-affiliation" name="organization" autoComplete="organization" maxLength={100} value={form.currentAffiliation} onChange={(event) => updateForm("currentAffiliation", event.target.value)} className={FIELD_CLASS} />
                </div>
                <div>
                  <InputLabel htmlFor="recruit-region">활동 지역</InputLabel>
                  <input id="recruit-region" name="address-level1" autoComplete="address-level1" maxLength={60} placeholder="예: 서울 강남" value={form.region} onChange={(event) => updateForm("region", event.target.value)} className={FIELD_CLASS} required />
                </div>
                <div>
                  <InputLabel htmlFor="recruit-contact-window">연락받기 편한 시간</InputLabel>
                  <select id="recruit-contact-window" value={form.contactWindow} onChange={(event) => updateForm("contactWindow", event.target.value as PublicApplicationFormValues["contactWindow"])} className={FIELD_CLASS} required>
                    <option value="">시간을 선택해주세요</option>
                    {Object.entries(CONTACT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>
                <details className="rounded-2xl border border-line bg-surface2 px-4 py-3">
                  <summary className="min-h-11 cursor-pointer py-2 text-[13px] font-bold text-ink2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">개인정보 수집과 연락 안내 전체 보기</summary>
                  <p className="pb-2 text-[12px] leading-6 text-ink3">{page.consent_text}</p>
                </details>
                <label className="flex min-h-11 cursor-pointer items-start gap-3 rounded-xl focus-within:ring-2 focus-within:ring-brand">
                  <input type="checkbox" checked={form.agreed} onChange={(event) => updateForm("agreed", event.target.checked)} className="mt-1 h-5 w-5 shrink-0 accent-[var(--brand)]" required />
                  <span className="text-[13px] leading-6 text-ink2">개인정보 수집과 담당 설계사의 연락에 동의해요. (필수)</span>
                </label>
              </fieldset>
              {error && <p role="alert" className="text-[13px] leading-5 text-cnone">{error}</p>}
              {pending && <p role="status" aria-live="polite" className="text-[13px] text-ink3">지원 내용을 보내고 있어요.</p>}
              <button type="submit" disabled={pending} className={`${PUBLIC_PRIMARY_BUTTON} w-full`}>
                {pending ? "보내는 중이에요" : "먼저 이야기 나눠보기"}
              </button>
            </form>
          </section>
        )}

        <p className="text-center text-[11px] leading-5 text-muted">이 페이지는 보험설계사 동료 지원만을 위한 화면이에요.</p>
      </div>
    </PublicRecruitingFrame>
  );
}
