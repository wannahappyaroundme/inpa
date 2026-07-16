"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Card } from "@/components/ui";
import {
  getRecruitingPage,
  listRecruitingTemplates,
  updateRecruitingPage,
  type RecruitingPage,
  type RecruitingTemplate,
} from "@/lib/api";
import { friendlyRecruitingError } from "./recruiting-labels";
import { RecruitingError, RecruitingLoading } from "./recruiting-states";
import {
  getActiveSelectedTemplateIds,
  getRecruitingPageEditorIssue,
} from "./recruiting-view-model";

export function PageEditor() {
  const [page, setPage] = useState<RecruitingPage | null>(null);
  const [templates, setTemplates] = useState<RecruitingTemplate[]>([]);
  const [headlineId, setHeadlineId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [region, setRegion] = useState("");
  const [published, setPublished] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [pageResult, templateResult] = await Promise.all([
        getRecruitingPage(),
        listRecruitingTemplates(),
      ]);
      const activeHeadlineIds = new Set(
        templateResult.filter((template) => template.kind === "headline").map((template) => template.id),
      );
      setPage(pageResult);
      setTemplates(templateResult);
      setHeadlineId(
        pageResult.headline_template_id && activeHeadlineIds.has(pageResult.headline_template_id)
          ? pageResult.headline_template_id
          : templateResult.find((template) => template.kind === "headline")?.id ?? null,
      );
      setSelectedIds(getActiveSelectedTemplateIds(pageResult.templates, templateResult));
      setRegion(pageResult.activity_region);
      setPublished(pageResult.is_published);
    } catch (reason) {
      setError(friendlyRecruitingError(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const headlines = useMemo(
    () => templates.filter((template) => template.kind === "headline"),
    [templates],
  );
  const selectable = useMemo(
    () => templates.filter((template) => template.kind === "support" || template.kind === "faq"),
    [templates],
  );
  const selectedHeadline = headlines.find((template) => template.id === headlineId) ?? null;
  const selectedTemplates = selectable.filter((template) => selectedIds.includes(template.id));
  const editorIssue = getRecruitingPageEditorIssue(headlineId, selectedIds.length);

  function toggleTemplate(id: number) {
    setError(null);
    setStatus(null);
    setSelectedIds((current) => {
      if (current.includes(id)) return current.filter((value) => value !== id);
      if (current.length >= 3) {
        setError("지원 내용과 자주 묻는 질문은 합쳐서 3개까지 고를 수 있어요.");
        return current;
      }
      return [...current, id];
    });
  }

  async function save() {
    if (editorIssue === "missing_headline") {
      setError("지원자가 처음 볼 문장을 선택해 주세요.");
      return;
    }
    if (editorIssue === "too_many_templates") {
      setError("지원 내용과 자주 묻는 질문을 3개까지 남겨 주세요.");
      return;
    }
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const updated = await updateRecruitingPage({
        headline_template_id: headlineId,
        template_ids: selectedIds,
        activity_region: region.trim(),
        is_published: published,
      });
      setPage(updated);
      setHeadlineId(updated.headline_template_id);
      setSelectedIds(updated.templates.map((template) => template.id));
      setRegion(updated.activity_region);
      setPublished(updated.is_published);
      setStatus("영입 페이지를 저장했어요.");
    } catch (reason) {
      setError(friendlyRecruitingError(reason, "입력한 내용은 그대로 두었어요. 다시 저장해 주세요."));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <RecruitingLoading />;
  if (!page) return <RecruitingError message={error ?? undefined} onRetry={load} />;

  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)] xl:items-start">
      <Card className="min-w-0 p-4 sm:p-6">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-[18px] font-extrabold text-ink">나의 영입 페이지 꾸미기</h2>
            <p className="mt-1 text-[12px] leading-5 text-ink3">
              승인된 문구 중 내 활동 방식과 맞는 내용을 골라 보여주세요.
            </p>
          </div>
          <Link href="/settings/account" className="inline-flex min-h-11 items-center text-[12px] font-bold text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
            사진·이름 바꾸기
          </Link>
        </div>

        {error && <p role="alert" className="mt-4 rounded-xl bg-danger-tint px-3 py-2.5 text-[12px] font-semibold text-danger-ink">{error}</p>}
        {status && <p aria-live="polite" className="mt-4 rounded-xl bg-success-tint px-3 py-2.5 text-[12px] font-semibold text-success-ink">{status}</p>}
        {editorIssue === "too_many_templates" && (
          <p role="status" className="mt-4 rounded-xl bg-warning-tint px-3 py-2.5 text-[12px] font-semibold text-warning-ink">
            현재 {selectedIds.length}개가 선택되어 있어요. 3개까지 남기면 바로 저장할 수 있어요.
          </p>
        )}

        <fieldset className="mt-6">
          <legend className="text-[14px] font-extrabold text-ink">처음 보여줄 문장</legend>
          <div className="mt-3 grid gap-2">
            {headlines.length === 0 ? (
              <div className="rounded-2xl border border-line bg-brand-soft p-5 text-center">
                <p className="text-[14px] font-bold text-ink">첫 문장을 불러오면 영입 페이지를 완성할 수 있어요.</p>
                <p className="mt-2 text-[12px] leading-5 text-ink2">다시 불러오거나 운영팀에 사용할 문구를 요청해 주세요.</p>
                <div className="mt-4 flex flex-col justify-center gap-2 sm:flex-row">
                  <button type="button" disabled={saving} onClick={() => void load()} className="min-h-11 rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-brand disabled:opacity-60">문구 다시 불러오기</button>
                  <Link href="/boards/inquiry/new" className="inline-flex min-h-11 items-center justify-center rounded-xl bg-brand px-4 text-[13px] font-bold text-white">운영팀에 문구 요청하기</Link>
                </div>
              </div>
            ) : headlines.map((template) => (
              <label key={template.id} className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-2xl border p-3 transition ${headlineId === template.id ? "border-brand bg-brand-soft" : "border-line bg-surface"}`}>
                <input type="radio" name="headline" disabled={saving} checked={headlineId === template.id} onChange={() => setHeadlineId(template.id)} className="mt-1 h-4 w-4 accent-[var(--brand)] disabled:opacity-60" />
                <span>
                  <span className="block text-[13px] font-bold text-ink">{template.title}</span>
                  <span className="mt-1 block text-[12px] leading-5 text-ink2">{template.body}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <label htmlFor="recruiting-region" className="mt-6 block text-[14px] font-extrabold text-ink">
          주로 활동하는 지역
        </label>
        <input
          id="recruiting-region"
          value={region}
          disabled={saving}
          maxLength={60}
          onChange={(event) => setRegion(event.target.value)}
          placeholder="예: 서울 강남·서초"
          className="mt-2 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px] text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/15"
        />
        <p className="mt-1 text-right text-[11px] tabular-nums text-ink3">{region.length}/60</p>

        <fieldset className="mt-6">
          <legend className="text-[14px] font-extrabold text-ink">정착 지원과 자주 묻는 질문</legend>
          <p className="mt-1 text-[11px] text-ink3">합쳐서 최대 3개, 현재 {selectedIds.length}개를 골랐어요.</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {selectable.map((template) => {
              const checked = selectedIds.includes(template.id);
              return (
                <label key={template.id} className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-2xl border p-3 ${checked ? "border-brand bg-brand-soft" : "border-line bg-surface"}`}>
                  <input type="checkbox" disabled={saving} checked={checked} onChange={() => toggleTemplate(template.id)} className="mt-1 h-4 w-4 accent-[var(--brand)] disabled:opacity-60" />
                  <span>
                    <span className="block text-[10px] font-bold text-brand">{template.kind === "support" ? "정착 지원" : "자주 묻는 질문"}</span>
                    <span className="mt-1 block text-[13px] font-bold text-ink">{template.title}</span>
                    <span className="mt-1 block text-[11px] leading-5 text-ink2">{template.body}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <fieldset className="mt-6">
          <legend className="text-[14px] font-extrabold text-ink">공개 상태</legend>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button type="button" disabled={saving} aria-pressed={published} onClick={() => setPublished(true)} className={`min-h-11 rounded-xl border px-3 text-[13px] font-bold disabled:opacity-60 ${published ? "border-brand bg-brand text-white" : "border-line bg-surface text-ink2"}`}>링크로 공개</button>
            <button type="button" disabled={saving} aria-pressed={!published} onClick={() => setPublished(false)} className={`min-h-11 rounded-xl border px-3 text-[13px] font-bold disabled:opacity-60 ${!published ? "border-brand bg-brand text-white" : "border-line bg-surface text-ink2"}`}>나만 보기</button>
          </div>
        </fieldset>

        <button type="button" disabled={saving || editorIssue !== null} onClick={save} className="mt-6 min-h-12 w-full rounded-2xl bg-brand px-5 text-[14px] font-bold text-white disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">
          {saving
            ? "저장하는 중..."
            : editorIssue === "too_many_templates"
              ? "3개까지 남기면 저장할 수 있어요"
              : editorIssue === "missing_headline"
                ? "첫 문장을 불러오면 저장할 수 있어요"
                : "영입 페이지 저장"}
        </button>
      </Card>

      <aside className="min-w-0 xl:sticky xl:top-6" aria-label="영입 페이지 미리보기">
        <p className="mb-2 px-1 text-[12px] font-bold text-ink3">지원자에게 이렇게 보여요</p>
        <div className="overflow-hidden rounded-3xl border border-line bg-surface shadow-card">
          <div className="bg-brand-soft px-5 py-7 text-center sm:px-8">
            <div className="mx-auto grid h-16 w-16 place-items-center overflow-hidden rounded-full border-2 border-white bg-surface text-[20px] font-extrabold text-brand shadow-card">
              {page.planner.profile_image ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={page.planner.profile_image} alt="" className="h-full w-full object-cover" />
              ) : page.planner.display_name.slice(0, 1)}
            </div>
            <h2 className="mt-3 text-[18px] font-extrabold text-ink">{page.planner.display_name}</h2>
            <p className="mt-1 text-[12px] text-ink2">{[page.planner.affiliation, page.planner.title].filter(Boolean).join(" · ") || "함께 이야기할 설계사"}</p>
            {region.trim() && <p className="mt-2 text-[11px] font-semibold text-brand">활동 지역 {region.trim()}</p>}
          </div>
          <div className="p-5 sm:p-7">
            <p className="text-[20px] font-extrabold leading-8 text-ink">{selectedHeadline?.body ?? "첫 문장을 선택하면 소개가 완성돼요."}</p>
            <div className="mt-5 space-y-3">
              {selectedTemplates.map((template) => (
                <section key={template.id} className="rounded-2xl border border-line bg-surface2 p-4">
                  <p className="text-[11px] font-bold text-brand">{template.kind === "support" ? "함께하는 방법" : "궁금한 점"}</p>
                  <h3 className="mt-1 text-[14px] font-extrabold text-ink">{template.title}</h3>
                  <p className="mt-1 text-[12px] leading-5 text-ink2">{template.body}</p>
                </section>
              ))}
              {selectedTemplates.length === 0 && <p className="rounded-2xl bg-surface2 p-4 text-[12px] text-ink3">보여줄 지원 내용을 고르면 이곳에 차례로 담겨요.</p>}
            </div>
            <div className="mt-6 min-h-12 rounded-2xl bg-brand px-5 py-3.5 text-center text-[14px] font-bold text-white">먼저 이야기 나누기</div>
          </div>
        </div>
      </aside>
    </div>
  );
}
