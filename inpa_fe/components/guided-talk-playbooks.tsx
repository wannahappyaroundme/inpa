"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Copy,
  MessageCircleQuestion,
  Phone,
  UserRoundCheck,
  X,
} from "lucide-react";
import { track } from "@vercel/analytics";

import { copyText } from "@/lib/clipboard";
import {
  GUIDED_TALK_OBJECTIONS,
  GUIDED_TALK_PLAYBOOKS,
  GUIDED_TALK_VERSION,
  renderGuidedTalk,
  type GuidedTalkAction,
  type GuidedTalkVariables,
} from "@/lib/guided-talk-playbooks";

interface GuidedTalkPlaybooksProps {
  variables: GuidedTalkVariables;
  customerId: number | null;
  onOpenQuick: (categoryKey: string) => void;
  onPlaybookChange?: (playbookKey: string) => void;
  initialPlaybookKey?: string;
}

type TalkEventProperties = Record<string, string | number | boolean>;

function trackTalkEvent(
  eventName: string,
  properties: TalkEventProperties,
): void {
  try {
    track(eventName, {
      version: GUIDED_TALK_VERSION,
      ...properties,
    });
  } catch {
    // 계측 연결은 실전 화법 사용을 막지 않는다.
  }
}

function actionHref(
  action: GuidedTalkAction,
  customerId: number | null,
): string | null {
  if (action.target === "schedule") return "/schedule";
  if (action.target === "customer-analysis") {
    return customerId
      ? `/customer/${customerId}?tab=analysis`
      : "/customers";
  }
  if (action.target === "end-call") {
    return customerId ? `/customer/${customerId}` : "/customers";
  }
  return null;
}

export function GuidedTalkPlaybooks({
  variables,
  customerId,
  onOpenQuick,
  onPlaybookChange,
  initialPlaybookKey,
}: GuidedTalkPlaybooksProps) {
  const initialPlaybook =
    GUIDED_TALK_PLAYBOOKS.find(
      (playbook) => playbook.key === initialPlaybookKey,
    ) ?? GUIDED_TALK_PLAYBOOKS[0];
  const [playbookKey, setPlaybookKey] = useState(initialPlaybook.key);
  const [stepIndex, setStepIndex] = useState(0);
  const [activeObjectionKey, setActiveObjectionKey] = useState<string | null>(
    null,
  );
  const [copyMessage, setCopyMessage] = useState("");
  const branchHeadingRef = useRef<HTMLHeadingElement>(null);
  const stepHeadingRef = useRef<HTMLHeadingElement>(null);
  const branchButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const stepButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const focusTimerRef = useRef<number | null>(null);
  const copyOperationRef = useRef(0);
  const mountedRef = useRef(true);
  const currentPlaybookKeyRef = useRef(initialPlaybook.key);
  const trackedPlaybookKeyRef = useRef<string | null>(null);

  const playbook =
    GUIDED_TALK_PLAYBOOKS.find((item) => item.key === playbookKey) ??
    GUIDED_TALK_PLAYBOOKS[0];
  const step = playbook.steps[stepIndex] ?? playbook.steps[0];
  const renderedSpokenText = useMemo(
    () => renderGuidedTalk(step.spokenText, variables),
    [step.spokenText, variables],
  );
  const activeObjection = activeObjectionKey
    ? GUIDED_TALK_OBJECTIONS[activeObjectionKey]
    : null;
  const isLastStep = stepIndex === playbook.steps.length - 1;
  const disclosureReady = Boolean(
    variables.planner?.trim() && variables.affiliation?.trim(),
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      copyOperationRef.current += 1;
      if (focusTimerRef.current !== null) {
        window.clearTimeout(focusTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (currentPlaybookKeyRef.current !== initialPlaybook.key) {
      copyOperationRef.current += 1;
      currentPlaybookKeyRef.current = initialPlaybook.key;
      setPlaybookKey(initialPlaybook.key);
      setStepIndex(0);
      setActiveObjectionKey(null);
      setCopyMessage("");
    }
    trackPlaybookEntry(initialPlaybook);
  }, [initialPlaybook]);

  useEffect(() => {
    copyOperationRef.current += 1;
    setCopyMessage("");
  }, [renderedSpokenText]);

  function scheduleFocus(callback: () => void) {
    if (focusTimerRef.current !== null) {
      window.clearTimeout(focusTimerRef.current);
    }
    focusTimerRef.current = window.setTimeout(() => {
      focusTimerRef.current = null;
      callback();
    });
  }

  function trackPlaybookEntry(
    nextPlaybook: (typeof GUIDED_TALK_PLAYBOOKS)[number],
  ) {
    if (trackedPlaybookKeyRef.current === nextPlaybook.key) return;
    trackedPlaybookKeyRef.current = nextPlaybook.key;
    trackTalkEvent("talk_playbook_open", {
      playbook_key: nextPlaybook.key,
    });
    trackTalkEvent("talk_stage_view", {
      playbook_key: nextPlaybook.key,
      step_key: nextPlaybook.steps[0].key,
    });
  }

  function selectPlaybook(nextPlaybookKey: string) {
    if (nextPlaybookKey === playbook.key) return;
    const nextPlaybook = GUIDED_TALK_PLAYBOOKS.find(
      (item) => item.key === nextPlaybookKey,
    );
    if (!nextPlaybook) return;
    copyOperationRef.current += 1;
    currentPlaybookKeyRef.current = nextPlaybookKey;
    setPlaybookKey(nextPlaybookKey);
    setStepIndex(0);
    setActiveObjectionKey(null);
    setCopyMessage("");
    trackPlaybookEntry(nextPlaybook);
    onPlaybookChange?.(nextPlaybookKey);
    scheduleFocus(() => {
      stepButtonRefs.current[nextPlaybook.steps[0].key]?.scrollIntoView?.({
        block: "nearest",
        inline: "center",
      });
      stepHeadingRef.current?.focus();
    });
  }

  function moveToStep(nextIndex: number) {
    const boundedIndex = Math.min(
      Math.max(nextIndex, 0),
      playbook.steps.length - 1,
    );
    copyOperationRef.current += 1;
    setStepIndex(boundedIndex);
    setActiveObjectionKey(null);
    setCopyMessage("");
    trackTalkEvent("talk_stage_view", {
      playbook_key: playbook.key,
      step_key: playbook.steps[boundedIndex].key,
    });
    scheduleFocus(() => {
      stepButtonRefs.current[
        playbook.steps[boundedIndex].key
      ]?.scrollIntoView?.({
        block: "nearest",
        inline: "center",
      });
      stepHeadingRef.current?.focus();
    });
  }

  function toggleObjection(objectionKey: string) {
    if (activeObjectionKey === objectionKey) {
      setActiveObjectionKey(null);
      scheduleFocus(() => branchButtonRefs.current[objectionKey]?.focus());
      return;
    }
    setActiveObjectionKey(objectionKey);
    trackTalkEvent("talk_objection_open", {
      playbook_key: playbook.key,
      step_key: step.key,
      branch_key: objectionKey,
    });
    scheduleFocus(() => branchHeadingRef.current?.focus());
  }

  function closeObjection() {
    const closingKey = activeObjectionKey;
    setActiveObjectionKey(null);
    if (closingKey) {
      scheduleFocus(() => branchButtonRefs.current[closingKey]?.focus());
    }
  }

  async function copySpokenText() {
    if (!disclosureReady) return;
    const operation = ++copyOperationRef.current;
    setCopyMessage("");
    const copied = await copyText(renderedSpokenText);
    if (!mountedRef.current || operation !== copyOperationRef.current) return;
    setCopyMessage(
      copied
        ? "말할 문장을 복사했어요."
        : "문장을 선택해 직접 복사해 주세요.",
    );
  }

  function runQuickAction(action: GuidedTalkAction) {
    const category =
      action.target === "quick-appointment" ? "appointment" : "result";
    trackTalkEvent("talk_next_action", {
      playbook_key: playbook.key,
      step_key: step.key,
      action_key: action.key,
    });
    onOpenQuick(category);
  }

  function trackLinkAction(action: GuidedTalkAction) {
    trackTalkEvent("talk_next_action", {
      playbook_key: playbook.key,
      step_key: step.key,
      action_key: action.key,
    });
  }

  return (
    <section aria-labelledby="guided-talk-title">
      <div>
        <h2 id="guided-talk-title" className="text-lg font-extrabold text-ink">
          오늘 장면 고르기
        </h2>
        <p className="mt-1 text-xs leading-5 text-ink3">
          현재 장면을 고르면, 한 단계씩 말할 문장과 고객 반응을 함께 볼 수
          있어요.
        </p>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {GUIDED_TALK_PLAYBOOKS.map((item) => {
          const selected = item.key === playbook.key;
          const Icon =
            item.key === "referred-customer-first-call"
              ? Phone
              : UserRoundCheck;
          return (
            <button
              key={item.key}
              type="button"
              aria-pressed={selected}
              onClick={() => selectPlaybook(item.key)}
              className={`min-h-36 rounded-2xl border p-5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
                selected
                  ? "border-brand bg-brand-soft shadow-card"
                  : "border-line bg-surface hover:border-brand/40"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <span
                  className={`inline-flex h-10 w-10 items-center justify-center rounded-xl ${
                    selected
                      ? "bg-brand text-white"
                      : "bg-surface2 text-ink3"
                  }`}
                >
                  <Icon aria-hidden="true" size={18} />
                </span>
                <span className="rounded-full bg-surface px-2.5 py-1 text-[11px] font-bold text-ink3">
                  {item.durationLabel}
                </span>
              </div>
              <span className="mt-4 block text-base font-extrabold text-ink">
                {item.title}
              </span>
              <span className="mt-1.5 block text-xs leading-5 text-ink3">
                {item.description}
              </span>
            </button>
          );
        })}
      </div>

      <div className="mt-5 rounded-2xl border border-line bg-surface p-4 shadow-card sm:p-5">
        <div className="flex flex-col gap-2 border-b border-line pb-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-bold text-brand">{playbook.title}</p>
            <h3 className="mt-1 text-base font-extrabold text-ink">
              {playbook.goal}
            </h3>
            <p className="mt-1 text-xs leading-5 text-ink3">
              {playbook.startCondition}
            </p>
          </div>
          <span className="shrink-0 rounded-full bg-surface2 px-3 py-1.5 text-xs font-bold text-ink2">
            현재 {stepIndex + 1}/{playbook.steps.length}
          </span>
        </div>

        <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-[220px_minmax(0,1fr)_320px]">
          <nav aria-label={`${playbook.title} 단계`} className="min-w-0">
            <ol className="flex snap-x gap-2 overflow-x-auto pb-2 xl:flex-col xl:overflow-visible xl:pb-0">
              {playbook.steps.map((item, index) => {
                const current = index === stepIndex;
                return (
                  <li key={item.key} className="min-w-48 snap-start xl:min-w-0">
                    <button
                      ref={(element) => {
                        stepButtonRefs.current[item.key] = element;
                      }}
                      type="button"
                      aria-label={`${index + 1}단계 ${item.title}`}
                      aria-current={current ? "step" : undefined}
                      onClick={() => moveToStep(index)}
                      className={`flex min-h-12 w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                        current
                          ? "border-brand bg-brand-soft text-brand"
                          : "border-line bg-surface text-ink2 hover:bg-surface2"
                      }`}
                    >
                      <span
                        className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] ${
                          current
                            ? "bg-brand text-white"
                            : "bg-surface2 text-ink3"
                        }`}
                      >
                        {index + 1}
                      </span>
                      <span>{item.title}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>

          <article className="min-w-0 rounded-2xl border border-line bg-canvas p-4 sm:p-5">
            <p className="text-xs font-bold text-brand">
              이번 단계 목표
            </p>
            <h4
              ref={stepHeadingRef}
              tabIndex={-1}
              className="mt-1 text-lg font-extrabold text-ink outline-none"
            >
              {step.title}
            </h4>
            <p className="mt-1 text-sm leading-6 text-ink3">{step.goal}</p>

            <div className="mt-5 rounded-2xl border border-brand/20 bg-surface p-4 sm:p-5">
              <p className="text-xs font-extrabold text-brand">
                이렇게 말해보세요
              </p>
              <p className="mt-3 whitespace-pre-wrap text-[15px] font-semibold leading-7 text-ink">
                {renderedSpokenText}
              </p>
              <button
                type="button"
                disabled={!disclosureReady}
                onClick={() => void copySpokenText()}
                className="mt-4 inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-line bg-surface px-4 text-xs font-bold text-ink2 transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Copy aria-hidden="true" size={15} />
                말할 문장 복사
              </button>
              {!disclosureReady && (
                <p className="mt-2 text-xs font-semibold leading-5 text-warn-ink">
                  계정 설정에서 내 이름과 소속을 채우면, 신분을 밝힌
                  문장을 복사할 수 있어요.
                </p>
              )}
              <p role="status" className="mt-2 min-h-5 text-xs font-semibold text-brand">
                {copyMessage}
              </p>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl bg-surface p-4">
                <p className="text-xs font-extrabold text-ink">
                  고객에게 물을 것
                </p>
                <ul className="mt-2 space-y-2 text-xs leading-5 text-ink2">
                  {step.questions.map((question) => (
                    <li key={question} className="flex gap-2">
                      <MessageCircleQuestion
                        aria-hidden="true"
                        className="mt-0.5 shrink-0 text-brand"
                        size={14}
                      />
                      {question}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-xl bg-surface p-4">
                <p className="text-xs font-extrabold text-ink">
                  확인할 것
                </p>
                <ul className="mt-2 space-y-2 text-xs leading-5 text-ink2">
                  {step.checklist.map((item) => (
                    <li key={item} className="flex gap-2">
                      <Check
                        aria-hidden="true"
                        className="mt-0.5 shrink-0 text-brand"
                        size={14}
                      />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            {step.coachNote && (
              <div className="mt-3 rounded-xl bg-surface2 px-4 py-3">
                <p className="text-xs font-extrabold text-ink">진행 메모</p>
                <p className="mt-1 text-xs leading-5 text-ink3">
                  {step.coachNote}
                </p>
              </div>
            )}

            {isLastStep && (
              <section
                aria-labelledby="talk-next-action-title"
                className="mt-4 rounded-2xl border border-brand/20 bg-brand-soft p-4"
              >
                <h5
                  id="talk-next-action-title"
                  className="text-sm font-extrabold text-brand"
                >
                  다음 행동 하나 정하기
                </h5>
                <p className="mt-1 text-xs leading-5 text-ink2">
                  상담을 마치기 전에 고객과 정한 행동을 바로 이어가세요.
                </p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {playbook.nextActions.map((action) => {
                    const href = actionHref(action, customerId);
                    const className =
                      "flex min-h-12 flex-col justify-center rounded-xl border border-brand/20 bg-surface px-4 py-2.5 text-left transition hover:border-brand/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand";
                    const content = (
                      <>
                        <span className="text-xs font-extrabold text-ink">
                          {action.label}
                        </span>
                        <span className="mt-0.5 text-[11px] leading-4 text-ink3">
                          {action.description}
                        </span>
                      </>
                    );
                    return href ? (
                      <Link
                        key={action.key}
                        href={href}
                        aria-label={action.label}
                        onClick={() => trackLinkAction(action)}
                        className={className}
                      >
                        {content}
                      </Link>
                    ) : (
                      <button
                        key={action.key}
                        type="button"
                        aria-label={action.label}
                        onClick={() => runQuickAction(action)}
                        className={className}
                      >
                        {content}
                      </button>
                    );
                  })}
                </div>
              </section>
            )}
          </article>

          <aside
            aria-labelledby="talk-objection-title"
            className="min-w-0 rounded-2xl border border-line bg-surface2 p-4"
          >
            <h4
              id="talk-objection-title"
              className="text-sm font-extrabold text-ink"
            >
              고객 반응에 맞춰 말하기
            </h4>
            <p className="mt-1 text-xs leading-5 text-ink3">
              고객 반응을 고르면 이어갈 문장이나 마무리 문장을 바로 볼
              수 있어요.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {step.objectionKeys.map((objectionKey) => {
                const objection = GUIDED_TALK_OBJECTIONS[objectionKey];
                const expanded = activeObjectionKey === objectionKey;
                return (
                  <button
                    key={objectionKey}
                    ref={(element) => {
                      branchButtonRefs.current[objectionKey] = element;
                    }}
                    type="button"
                    aria-expanded={expanded}
                    aria-controls={`talk-objection-${objectionKey}`}
                    onClick={() => toggleObjection(objectionKey)}
                    className={`min-h-11 rounded-xl border px-3 text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                      expanded
                        ? "border-brand bg-brand-soft text-brand"
                        : "border-line bg-surface text-ink2 hover:border-brand/30"
                    }`}
                  >
                    {objection.label}
                  </button>
                );
              })}
            </div>

            {activeObjection && (
              <section
                id={`talk-objection-${activeObjection.key}`}
                role="region"
                aria-labelledby={`talk-objection-heading-${activeObjection.key}`}
                className="mt-4 rounded-2xl border border-brand/20 bg-surface p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[11px] font-bold text-brand">
                      고객 반응 대응
                    </p>
                    <h5
                      ref={branchHeadingRef}
                      id={`talk-objection-heading-${activeObjection.key}`}
                      tabIndex={-1}
                      className="mt-1 text-sm font-extrabold text-ink outline-none"
                    >
                      {activeObjection.label} 대응
                    </h5>
                  </div>
                  <button
                    type="button"
                    aria-label="대응 닫기"
                    onClick={closeObjection}
                    className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-ink3 transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                  >
                    <X aria-hidden="true" size={17} />
                  </button>
                </div>
                <div className="mt-3">
                  <p className="text-[11px] font-extrabold text-ink3">
                    {activeObjection.terminal
                      ? "연락을 마칠 때"
                      : "범위를 줄여 한 번 제안할 때"}
                  </p>
                  <p className="mt-1 text-sm font-semibold leading-6 text-ink">
                    {renderGuidedTalk(
                      activeObjection.responseText,
                      variables,
                    )}
                  </p>
                </div>
                {!activeObjection.terminal && (
                  <div className="mt-4 border-t border-line pt-4">
                    <p className="text-[11px] font-extrabold text-ink3">
                      한 번 더 거절하면
                    </p>
                    <p className="mt-1 text-sm leading-6 text-ink2">
                      {renderGuidedTalk(
                        activeObjection.secondRefusalText,
                        variables,
                      )}
                    </p>
                  </div>
                )}
                {activeObjection.terminal && (
                  <p className="mt-3 rounded-xl bg-surface2 px-3 py-2 text-[11px] font-bold text-ink2">
                    이 반응에서는 추가 제안 없이 연락을 마쳐요. 고객
                    상세에서 상태와 연락 결과도 정리해 주세요.
                  </p>
                )}
              </section>
            )}
          </aside>

          <div className="flex items-center justify-between gap-3 border-t border-line pt-4 xl:col-start-2 xl:row-start-2">
            <button
              type="button"
              disabled={stepIndex === 0}
              onClick={() => moveToStep(stepIndex - 1)}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-line px-4 text-xs font-bold text-ink2 transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ArrowLeft aria-hidden="true" size={15} />
              이전 단계
            </button>
            <button
              type="button"
              disabled={isLastStep}
              onClick={() => moveToStep(stepIndex + 1)}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-brand px-4 text-xs font-bold text-white transition hover:bg-brand/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40"
            >
              다음 단계
              <ArrowRight aria-hidden="true" size={15} />
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
