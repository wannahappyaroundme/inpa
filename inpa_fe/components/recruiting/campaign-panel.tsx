"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Card } from "@/components/ui";
import { copyText } from "@/lib/clipboard";
import {
  getRecruitingCampaign,
  getRecruitingPage,
  listRecruitingTemplates,
  recordRecruitingCampaignCopied,
  reissueRecruitingCampaign,
  setRecruitingCampaignActive,
  type RecruitingCampaign,
  type RecruitingPage,
  type RecruitingTemplate,
} from "@/lib/api";
import { ConfirmationDialog } from "./confirmation-dialog";
import { friendlyRecruitingError } from "./recruiting-labels";
import { RecruitingQr } from "./recruiting-qr";
import { RecruitingError, RecruitingLoading } from "./recruiting-states";

export function CampaignPanel({ onMoveToPage }: { onMoveToPage: () => void }) {
  const [campaign, setCampaign] = useState<RecruitingCampaign | null>(null);
  const [page, setPage] = useState<RecruitingPage | null>(null);
  const [templates, setTemplates] = useState<RecruitingTemplate[]>([]);
  const [origin, setOrigin] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [campaignResult, pageResult, templateResult] = await Promise.all([
        getRecruitingCampaign(),
        getRecruitingPage(),
        listRecruitingTemplates(),
      ]);
      setCampaign(campaignResult);
      setPage(pageResult);
      setTemplates(templateResult);
    } catch (reason) {
      setError(friendlyRecruitingError(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setOrigin(window.location.origin);
    void load();
  }, [load]);

  const publicUrl = campaign && origin ? `${origin}${campaign.public_path}` : "";
  const shareTemplate = useMemo(
    () => templates.find((template) => template.kind === "share") ?? null,
    [templates],
  );

  async function copyCampaign(text: string, successMessage: string) {
    setError(null);
    setStatus(null);
    const copied = await copyText(text);
    if (!copied) {
      setError("링크를 길게 눌러 직접 복사해 주세요.");
      return;
    }
    setStatus(successMessage);
    void recordRecruitingCampaignCopied().catch(() => undefined);
  }

  async function toggleActive() {
    if (!campaign || pending) return;
    setPending(true);
    setError(null);
    setStatus(null);
    try {
      const updated = await setRecruitingCampaignActive(!campaign.is_active);
      setCampaign(updated);
      setStatus(updated.is_active ? "개인 소개 링크를 다시 시작했어요." : "링크를 잠시 멈췄어요. 다시 시작해도 주소는 같아요.");
    } catch (reason) {
      setError(friendlyRecruitingError(reason, "링크 상태는 그대로예요. 다시 확인해 주세요."));
    } finally {
      setPending(false);
    }
  }

  async function confirmReissue() {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const updated = await reissueRecruitingCampaign();
      setCampaign(updated);
      setConfirmOpen(false);
      setStatus("새 개인 소개 링크를 만들었어요.");
    } catch (reason) {
      setError(friendlyRecruitingError(reason, "기존 링크는 그대로예요. 다시 확인해 주세요."));
    } finally {
      setPending(false);
    }
  }

  if (loading) return <RecruitingLoading />;
  if (!campaign || !page) return <RecruitingError message={error ?? undefined} onRetry={load} />;

  const shareDraft = shareTemplate ? `${shareTemplate.body}\n\n${publicUrl}` : null;

  return (
    <div className="min-w-0 space-y-4">
      {error && <p role="alert" className="rounded-2xl bg-danger-tint px-4 py-3 text-[13px] font-semibold text-danger-ink">{error}</p>}
      {status && <p aria-live="polite" className="rounded-2xl bg-success-tint px-4 py-3 text-[13px] font-semibold text-success-ink">{status}</p>}

      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "누적 방문", value: campaign.visits },
          { label: "누적 지원", value: campaign.applications },
          { label: "누적 합류", value: campaign.joins },
        ].map((item) => (
          <Card key={item.label} className="p-3 text-center sm:p-5">
            <p className="text-[10px] font-semibold text-ink3 sm:text-[12px]">{item.label}</p>
            <p className="mt-2 text-[22px] font-extrabold tabular-nums text-ink sm:text-[28px]">{item.value}</p>
          </Card>
        ))}
      </div>

      <Card className="min-w-0 p-4 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-[11px] font-bold text-brand">개인 소개</p>
            <h2 className="mt-1 text-[19px] font-extrabold text-ink">아는 설계사에게 보내는 영입 링크</h2>
            <p className="mt-2 text-[12px] leading-5 text-ink3">
              링크와 문구를 복사한 뒤 원하는 대화방이나 문자에서 직접 보내세요.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={campaign.is_active}
            disabled={pending}
            onClick={toggleActive}
            className={`min-h-11 shrink-0 rounded-full px-5 text-[13px] font-bold disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${campaign.is_active ? "bg-success-tint text-success-ink" : "bg-surface2 text-ink2"}`}
          >
            {pending ? "확인하는 중..." : campaign.is_active ? "링크 사용 중" : "링크 멈춤"}
          </button>
        </div>

        {!page.is_published ? (
          <div className="mt-5 rounded-2xl border border-line bg-brand-soft p-5 text-center">
            <p className="text-[14px] font-bold text-ink">페이지를 공개하면 링크로 지원을 받을 수 있어요.</p>
            <button type="button" onClick={onMoveToPage} className="mt-3 min-h-11 rounded-xl bg-brand px-5 text-[13px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">나의 영입 페이지로 이동</button>
          </div>
        ) : !campaign.is_active ? (
          <div className="mt-5 rounded-2xl border border-line bg-surface2 p-5 text-center">
            <p className="text-[14px] font-bold text-ink">링크를 다시 시작하면 같은 주소로 지원을 받을 수 있어요.</p>
            <button type="button" disabled={pending} onClick={toggleActive} className="mt-3 min-h-11 rounded-xl bg-brand px-5 text-[13px] font-bold text-white disabled:opacity-60">같은 링크 다시 시작</button>
          </div>
        ) : (
          <div className="mt-6 grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_280px] lg:items-start">
            <div className="min-w-0">
              <label htmlFor="campaign-url" className="text-[12px] font-bold text-ink2">현재 공개 주소</label>
              <input id="campaign-url" readOnly value={publicUrl} onFocus={(event) => event.currentTarget.select()} className="mt-2 min-h-11 w-full rounded-xl border border-line bg-surface2 px-3 text-[12px] text-ink2 outline-none focus:border-brand" />
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <button type="button" onClick={() => copyCampaign(publicUrl, "개인 소개 링크를 복사했어요.")} className="min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">링크 복사</button>
                {shareDraft && <button type="button" onClick={() => copyCampaign(shareDraft, "보낼 문구와 링크를 복사했어요.")} className="min-h-11 rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">보낼 문구 함께 복사</button>}
              </div>
              {shareDraft ? (
                <div className="mt-5 rounded-2xl bg-surface2 p-4">
                  <p className="text-[11px] font-bold text-ink3">보낼 문구 미리보기</p>
                  <p className="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-ink2">{shareDraft}</p>
                </div>
              ) : (
                <p className="mt-4 rounded-2xl bg-surface2 p-4 text-[12px] leading-5 text-ink2">링크를 복사한 뒤 내 말로 소개해 주세요.</p>
              )}
            </div>
            <RecruitingQr url={publicUrl} />
          </div>
        )}

        <div className="mt-6 border-t border-line pt-5">
          <h3 className="text-[14px] font-extrabold text-ink">새 주소가 필요할 때</h3>
          <p className="mt-1 text-[12px] leading-5 text-ink3">기존 주소를 정리하고 새 개인 소개 주소로 바꿀 수 있어요.</p>
          <button type="button" disabled={pending} onClick={() => setConfirmOpen(true)} className="mt-3 min-h-11 rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-ink2 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">새 링크 만들기</button>
        </div>
      </Card>

      <ConfirmationDialog
        open={confirmOpen}
        title="새 개인 소개 링크를 만들까요?"
        description="새 링크를 만들면 기존 링크로는 새 지원을 받지 않아요. 이미 기록된 방문과 지원 내역은 그대로 남아요."
        confirmLabel="새 링크 만들기"
        pendingLabel="새 링크 만드는 중..."
        pending={pending}
        onConfirm={confirmReissue}
        onClose={() => setConfirmOpen(false)}
      />
    </div>
  );
}
