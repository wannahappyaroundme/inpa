"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Card } from "@/components/ui";
import { copyText } from "@/lib/clipboard";
import {
  getRecruitingCampaign,
  getRecruitingPage,
  getRecruitingSummary,
  listRecruitingCandidates,
  recordRecruitingCampaignCopied,
  type PaginatedResult,
  type RecruitingCandidate,
  type RecruitingCareerBand,
  type RecruitingPage,
  type RecruitingStage,
  type RecruitingSummary,
} from "@/lib/api";
import { CandidateCard } from "./candidate-card";
import {
  CAREER_LABELS,
  STAGE_LABELS,
  friendlyRecruitingError,
} from "./recruiting-labels";
import { RecruitingEmpty, RecruitingError, RecruitingLoading } from "./recruiting-states";
import {
  createLatestRequestGate,
  getBoardColumnPresentation,
  sortRecruitingCandidates,
  type CandidateSortKey,
} from "./recruiting-view-model";

const STAGES = Object.keys(STAGE_LABELS) as RecruitingStage[];
const CAREERS = Object.keys(CAREER_LABELS) as RecruitingCareerBand[];

type DueFilter = "" | "due";

function emptyPage(): PaginatedResult<RecruitingCandidate> {
  return { count: 0, next: null, previous: null, results: [] };
}

export function StatusPanel() {
  const [summary, setSummary] = useState<RecruitingSummary | null>(null);
  const [pageInfo, setPageInfo] = useState<RecruitingPage | null>(null);
  const [campaign, setCampaign] = useState<Awaited<ReturnType<typeof getRecruitingCampaign>> | null>(null);
  const [candidates, setCandidates] = useState<PaginatedResult<RecruitingCandidate>>(emptyPage);
  const [contextLoading, setContextLoading] = useState(true);
  const [listLoading, setListLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState<RecruitingStage | "">("");
  const [career, setCareer] = useState<RecruitingCareerBand | "">("");
  const [due, setDue] = useState<DueFilter>("");
  const [source, setSource] = useState<"" | "relationship">("");
  const [sort, setSort] = useState<CandidateSortKey>("due");
  const [view, setView] = useState<"board" | "list">("board");
  const [currentPage, setCurrentPage] = useState(1);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const listRequestGateRef = useRef(createLatestRequestGate());
  const loadCandidatesRef = useRef<() => Promise<void>>(() => Promise.resolve());

  const loadContext = useCallback(async () => {
    setContextLoading(true);
    setError(null);
    try {
      const [summaryResult, pageResult, campaignResult] = await Promise.all([
        getRecruitingSummary(),
        getRecruitingPage(),
        getRecruitingCampaign(),
      ]);
      setSummary(summaryResult);
      setPageInfo(pageResult);
      setCampaign(campaignResult);
    } catch (reason) {
      setError(friendlyRecruitingError(reason));
    } finally {
      setContextLoading(false);
    }
  }, []);

  const loadCandidates = useCallback(async () => {
    const requestGate = listRequestGateRef.current;
    const requestGeneration = requestGate.begin();
    setListLoading(true);
    setError(null);
    try {
      const result = await listRecruitingCandidates({
        page: currentPage,
        q: search || undefined,
        stage: stage || undefined,
        career_band: career || undefined,
        source: source || undefined,
        due: due === "due" ? true : undefined,
      });
      if (!requestGate.isCurrent(requestGeneration)) return;
      setCandidates(result);
    } catch (reason) {
      if (!requestGate.isCurrent(requestGeneration)) return;
      setError(friendlyRecruitingError(reason));
    } finally {
      if (requestGate.isCurrent(requestGeneration)) setListLoading(false);
    }
  }, [career, currentPage, due, search, source, stage]);

  loadCandidatesRef.current = loadCandidates;

  useEffect(() => {
    void loadContext();
  }, [loadContext]);

  useEffect(() => {
    void loadCandidates();
    return () => {
      listRequestGateRef.current.invalidate();
    };
  }, [loadCandidates]);

  const sorted = useMemo(
    () => sortRecruitingCandidates(candidates.results, sort),
    [candidates.results, sort],
  );
  const mobileSorted = sorted;

  function applySearch(event: FormEvent) {
    event.preventDefault();
    setCurrentPage(1);
    setSearch(searchDraft.trim());
  }

  async function handleCandidateChanged(updated: RecruitingCandidate) {
    listRequestGateRef.current.invalidate();
    setCandidates((current) => ({
      ...current,
      count: stage && updated.stage !== stage ? Math.max(0, current.count - 1) : current.count,
      results: current.results
        .map((candidate) => candidate.id === updated.id ? updated : candidate)
        .filter((candidate) => !stage || candidate.stage === stage),
    }));
    const summaryRefresh = getRecruitingSummary()
      .then(setSummary)
      .catch(() => undefined);
    await Promise.all([loadCandidatesRef.current(), summaryRefresh]);
  }

  async function copyPublicLink() {
    if (!campaign || !pageInfo?.is_published || !campaign.is_active) return;
    const copied = await copyText(`${window.location.origin}${campaign.public_path}`);
    if (!copied) {
      setCopyStatus("링크를 길게 눌러 직접 복사해 주세요.");
      return;
    }
    setCopyStatus("개인 소개 링크를 복사했어요.");
    void recordRecruitingCampaignCopied().catch(() => undefined);
  }

  if ((contextLoading || listLoading) && !summary && candidates.results.length === 0) {
    return <RecruitingLoading />;
  }

  if (error && (!summary || candidates.results.length === 0)) {
    return <RecruitingError message={error} onRetry={() => { void loadContext(); void loadCandidates(); }} />;
  }

  const summaryCards = [
    { label: "오늘 확인", value: summary?.due_today ?? 0 },
    { label: "지난 확인", value: summary?.overdue ?? 0 },
    { label: "이번 달 합류", value: summary?.joined_this_month ?? 0 },
    { label: "정착 확인", value: summary?.settlement_due ?? 0 },
  ];
  const hasActiveFilters = Boolean(search || stage || career || due || source);

  function clearFilters() {
    setSearchDraft("");
    setSearch("");
    setStage("");
    setCareer("");
    setDue("");
    setSource("");
    setCurrentPage(1);
  }

  return (
    <div className="min-w-0 space-y-4">
      {error && (
        <RecruitingError message={error} onRetry={() => { void loadContext(); void loadCandidates(); }} />
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {summaryCards.map((item) => (
          <Card key={item.label} className="p-4">
            <p className="text-[11px] font-semibold text-ink3">{item.label}</p>
            <p className="mt-2 text-[24px] font-extrabold tabular-nums text-ink">{item.value}</p>
          </Card>
        ))}
      </div>

      <Card className="min-w-0 p-3 sm:p-4">
        <form onSubmit={applySearch} className="flex min-w-0 flex-col gap-2 sm:flex-row">
          <label className="min-w-0 flex-1 text-[11px] font-semibold text-ink3">
            이름 또는 연락처 찾기
            <input
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder="찾을 이름이나 연락처를 입력하세요"
              className="mt-1.5 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px] text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/15"
            />
          </label>
          <button type="submit" className="min-h-11 self-end rounded-xl bg-brand px-5 text-[13px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">
            찾기
          </button>
        </form>
        <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-5">
          <label className="text-[11px] font-semibold text-ink3">단계
            <select value={stage} onChange={(event) => { setCurrentPage(1); setStage(event.target.value as RecruitingStage | ""); }} className="mt-1.5 min-h-11 w-full rounded-xl border border-line bg-surface px-2 text-[12px] text-ink">
              <option value="">전체 단계</option>
              {STAGES.map((value) => <option key={value} value={value}>{STAGE_LABELS[value]}</option>)}
            </select>
          </label>
          <label className="text-[11px] font-semibold text-ink3">경력
            <select value={career} onChange={(event) => { setCurrentPage(1); setCareer(event.target.value as RecruitingCareerBand | ""); }} className="mt-1.5 min-h-11 w-full rounded-xl border border-line bg-surface px-2 text-[12px] text-ink">
              <option value="">전체 경력</option>
              {CAREERS.map((value) => <option key={value} value={value}>{CAREER_LABELS[value]}</option>)}
            </select>
          </label>
          <label className="text-[11px] font-semibold text-ink3">들어온 곳
            <select value={source} onChange={(event) => { setCurrentPage(1); setSource(event.target.value as "" | "relationship"); }} className="mt-1.5 min-h-11 w-full rounded-xl border border-line bg-surface px-2 text-[12px] text-ink">
              <option value="">전체</option>
              <option value="relationship">개인 소개</option>
            </select>
          </label>
          <label className="text-[11px] font-semibold text-ink3">확인 날짜
            <select value={due} onChange={(event) => { setCurrentPage(1); setDue(event.target.value as DueFilter); }} className="mt-1.5 min-h-11 w-full rounded-xl border border-line bg-surface px-2 text-[12px] text-ink">
              <option value="">전체</option>
              <option value="due">확인할 항목</option>
            </select>
          </label>
          <label className="col-span-2 text-[11px] font-semibold text-ink3 lg:col-span-1">정렬
            <select value={sort} onChange={(event) => setSort(event.target.value as CandidateSortKey)} className="mt-1.5 min-h-11 w-full rounded-xl border border-line bg-surface px-2 text-[12px] text-ink">
              <option value="due">다음 행동 빠른 순</option>
              <option value="newest">최근 지원 순</option>
              <option value="name">이름 순</option>
            </select>
          </label>
        </div>
      </Card>

      <div className="scrollbar-none flex gap-2 overflow-x-auto pb-1 sm:hidden" aria-label="단계별 빠른 필터">
        <button type="button" onClick={() => { setCurrentPage(1); setStage(""); }} className={`min-h-11 shrink-0 rounded-full px-4 text-[12px] font-bold ${!stage ? "bg-brand text-white" : "border border-line bg-surface text-ink2"}`}>전체</button>
        {STAGES.map((value) => (
          <button key={value} type="button" onClick={() => { setCurrentPage(1); setStage(value); }} className={`min-h-11 shrink-0 rounded-full px-4 text-[12px] font-bold ${stage === value ? "bg-brand text-white" : "border border-line bg-surface text-ink2"}`}>
            {STAGE_LABELS[value]}
          </button>
        ))}
      </div>

      <div className="hidden items-center justify-between gap-3 sm:flex">
        <p className="text-[12px] text-ink3">전체 {candidates.count}명 중 이 페이지의 {candidates.results.length}명을 보고 있어요.</p>
        <div className="flex rounded-xl border border-line bg-surface p-1">
          {(["board", "list"] as const).map((value) => (
            <button key={value} type="button" onClick={() => setView(value)} className={`min-h-11 rounded-lg px-4 text-[12px] font-bold ${view === value ? "bg-brand text-white" : "text-ink2"}`}>
              {value === "board" ? "단계별" : "목록"}
            </button>
          ))}
        </div>
      </div>

      {listLoading && candidates.results.length > 0 && <p role="status" className="text-[12px] text-ink3">목록을 새로 확인하는 중...</p>}

      {!listLoading && candidates.count === 0 && hasActiveFilters ? (
        <div className="rounded-2xl border border-line bg-surface px-5 py-10 text-center shadow-card">
          <p className="text-[15px] font-bold text-ink">선택한 조건에 맞는 지원이 없어요.</p>
          <p className="mt-2 text-[13px] text-ink3">조건을 지우면 전체 영입 대화를 다시 볼 수 있어요.</p>
          <button type="button" onClick={clearFilters} className="mt-4 min-h-11 rounded-xl bg-brand px-5 text-[13px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">전체 지원 보기</button>
        </div>
      ) : !listLoading && candidates.count === 0 ? (
        <div className="space-y-3">
          <RecruitingEmpty />
          {pageInfo?.is_published && campaign?.is_active ? (
            <div className="text-center">
              <button type="button" onClick={copyPublicLink} className="min-h-11 rounded-xl bg-brand px-5 text-[13px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">내 영입 링크 복사</button>
              {copyStatus && <p aria-live="polite" className="mt-2 text-[12px] text-ink2">{copyStatus}</p>}
            </div>
          ) : !pageInfo?.is_published ? (
            <div className="text-center"><Link href="/sales?tab=recruiting&view=page" className="inline-flex min-h-11 items-center rounded-xl bg-brand px-5 text-[13px] font-bold text-white">나의 영입 페이지 공개하기</Link></div>
          ) : (
            <div className="text-center"><Link href="/sales?tab=recruiting&view=campaign" className="inline-flex min-h-11 items-center rounded-xl bg-brand px-5 text-[13px] font-bold text-white">캠페인 링크 다시 시작하기</Link></div>
          )}
        </div>
      ) : (
        <>
          <div className="space-y-3 sm:hidden">
            {mobileSorted.map((candidate) => (
              <CandidateCard key={candidate.id} candidate={candidate} onChanged={handleCandidateChanged} />
            ))}
          </div>

          <div className="hidden sm:block">
            {view === "board" && !hasActiveFilters ? (
              <div className="max-w-full overflow-x-auto rounded-2xl border border-line bg-surface2 p-3">
                <div className="flex min-w-max gap-3">
                  {STAGES.map((stageValue) => {
                    const items = sorted.filter((candidate) => candidate.stage === stageValue);
                    const stageCount = summary?.stage_counts[stageValue] ?? items.length;
                    const column = getBoardColumnPresentation(items.length, stageCount);
                    const showStageList = () => {
                      setCurrentPage(1);
                      setStage(stageValue);
                    };
                    return (
                      <section key={stageValue} aria-label={STAGE_LABELS[stageValue]} className="w-[300px] shrink-0">
                        <div className="mb-2 flex items-center justify-between px-1">
                          <h2 className="text-[13px] font-extrabold text-ink">{STAGE_LABELS[stageValue]}</h2>
                          <span className="rounded-full bg-surface px-2 py-1 text-[10px] font-bold text-ink3">{stageCount}</span>
                        </div>
                        <div className="space-y-3">
                          {items.map((candidate) => <CandidateCard key={candidate.id} compact candidate={candidate} onChanged={handleCandidateChanged} />)}
                          {column.kind === "empty" && <p className="rounded-2xl border border-dashed border-line bg-surface px-4 py-8 text-center text-[11px] text-ink3">이 단계의 지원이 들어오면 여기에 보여요.</p>}
                          {column.kind === "other_page" && (
                            <button type="button" onClick={showStageList} className="w-full rounded-2xl border border-line bg-surface px-4 py-6 text-center text-[11px] font-bold leading-5 text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                              다른 페이지에 {column.hiddenCount}명이 있어요. 이 단계 전체 보기
                            </button>
                          )}
                          {column.kind === "partial" && (
                            <button type="button" onClick={showStageList} className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[11px] font-bold text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                              나머지 {column.hiddenCount}명도 보기
                            </button>
                          )}
                        </div>
                      </section>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {sorted.map((candidate) => <CandidateCard key={candidate.id} candidate={candidate} onChanged={handleCandidateChanged} />)}
              </div>
            )}
          </div>
        </>
      )}

      {candidates.count > 0 && (
        <nav aria-label="영입 지원 페이지" className="flex items-center justify-center gap-3 pt-2">
          <button type="button" disabled={!candidates.previous || listLoading} onClick={() => setCurrentPage((value) => Math.max(1, value - 1))} className="min-h-11 rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-ink2 disabled:opacity-40">이전 20명</button>
          <span className="text-[12px] font-semibold text-ink3">{currentPage}페이지</span>
          <button type="button" disabled={!candidates.next || listLoading} onClick={() => setCurrentPage((value) => value + 1)} className="min-h-11 rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-ink2 disabled:opacity-40">다음 20명</button>
        </nav>
      )}
    </div>
  );
}
