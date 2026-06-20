"use client";

// 셀프진단 인바운드(공개·비로그인) — 잠재고객이 ?ref 설계사 링크로 본인 증권 진단.
// ★ 동의 2건(국외이전 + 설계사 전달) 없으면 업로드 불가. 결과는 보유 담보 '사실'만(neutral).
//   병력 미수집. AI 초안·중개권유 아님·최종책임 설계사.

import { useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { Card } from "@/components/ui";
import { postSelfDiagnosis, ApiError, type SelfDiagnosisResult } from "@/lib/api";

const krw = new Intl.NumberFormat("ko-KR");
function fmtWon(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v >= 100_000_000) return `${krw.format(v / 100_000_000)}억원`;
  if (v >= 10_000) return `${krw.format(v / 10_000)}만원`;
  return `${krw.format(v)}원`;
}

export default function SelfDiagnosisPage() {
  const params = useParams();
  const ref = typeof params?.ref === "string" ? params.ref : "";

  const [consentOverseas, setConsentOverseas] = useState(false);
  const [consentShare, setConsentShare] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SelfDiagnosisResult | null>(null);

  const canSubmit = consentOverseas && consentShare && file && !loading;

  const submit = useCallback(async () => {
    if (!file) {
      setError("증권 PDF를 첨부해 주세요.");
      return;
    }
    setLoading(true);
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("consent_overseas", "true");
    fd.append("consent_share", "true");
    if (name.trim()) fd.append("name", name.trim());
    if (phone.trim()) fd.append("phone", phone.trim());
    try {
      setResult(await postSelfDiagnosis(ref, fd));
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "진단에 실패했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setLoading(false);
    }
  }, [file, name, phone, ref]);

  // ── 결과 화면 ──
  if (result) {
    const held = result.tree
      .flatMap((c) => c.sub_categories)
      .flatMap((s) => s.details)
      .filter((d) => (d.held_amount ?? 0) > 0);
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
        <header className="px-5 pt-5 pb-3 bg-accent-tint">
          <div className="text-[13px] font-bold text-brand">⌃ 인파 무료 보장점검</div>
        </header>
        <main className="px-5 pb-10">
          <h1 className="pt-6 text-[22px] font-extrabold text-ink leading-8">
            지금 보장받는 담보예요
          </h1>
          <div className="mt-4 grid grid-cols-2 gap-2.5">
            <Card className="px-3 py-3.5 text-center">
              <div className="text-[11px] text-ink3">월 보험료</div>
              <div className="mt-1 text-[15px] font-extrabold tnum text-ink">{fmtWon(result.summary?.monthly_premiums)}</div>
            </Card>
            <Card className="px-3 py-3.5 text-center">
              <div className="text-[11px] text-ink3">총 납입</div>
              <div className="mt-1 text-[15px] font-extrabold tnum text-accent">{fmtWon(result.summary?.total_premiums)}</div>
            </Card>
          </div>
          <h2 className="mt-5 text-[13px] font-semibold text-ink3 mb-2">보유 담보</h2>
          {held.length > 0 ? (
            <Card className="divide-y divide-line">
              {held.map((c) => (
                <div key={c.detail_id} className="flex items-center gap-3 px-4 py-3">
                  <div className="flex-1 min-w-0 text-[15px] font-semibold text-ink">{c.name}</div>
                  <div className="text-[14px] font-bold text-ink tnum shrink-0">{fmtWon(c.held_amount)}</div>
                </div>
              ))}
            </Card>
          ) : (
            <Card className="px-4 py-6 text-center text-[14px] text-ink3">읽어들인 보유 담보가 없어요.</Card>
          )}
          <div className="mt-4 rounded-xl border border-line bg-surface px-4 py-3 text-[12px] text-ink3 leading-5">
            {result.disclaimer || "이 자료는 등록된 증권 정보를 정리한 AI 초안이며, 보장 충분성 판단·최종 책임은 담당 설계사에게 있습니다."}
          </div>
          <div className="mt-3 rounded-2xl bg-brand text-white text-center text-[15px] font-bold py-4">
            담당 설계사가 곧 연락드릴 거예요 🙌
          </div>
        </main>
      </div>
    );
  }

  // ── 입력 화면 ──
  return (
    <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
      <header className="px-5 pt-5 pb-3 bg-accent-tint">
        <div className="text-[13px] font-bold text-brand">⌃ 인파 무료 보장점검</div>
      </header>
      <main className="px-5 pb-10">
        <h1 className="pt-6 text-[22px] font-extrabold text-ink leading-8">
          내 보험, 1분 무료 점검
        </h1>
        <p className="mt-2 text-[14px] text-ink3 leading-6">
          가입한 증권(PDF)을 올리면 보유 담보를 한눈에 정리해 드려요. 담당 설계사가 확인 후 도와드립니다.
        </p>

        {/* 동의 */}
        <Card className="mt-5 px-4 py-4 space-y-3">
          <label className="flex items-start gap-2.5 cursor-pointer">
            <input type="checkbox" checked={consentOverseas} onChange={(e) => setConsentOverseas(e.target.checked)} className="mt-0.5" />
            <span className="text-[13px] text-ink2 leading-5">
              <b>(필수)</b> 증권 분석을 위해 보험정보가 Claude API(미국, Anthropic)로 <b>국외이전</b>되는 데 동의합니다.
            </span>
          </label>
          <label className="flex items-start gap-2.5 cursor-pointer">
            <input type="checkbox" checked={consentShare} onChange={(e) => setConsentShare(e.target.checked)} className="mt-0.5" />
            <span className="text-[13px] text-ink2 leading-5">
              <b>(필수)</b> 진단 결과가 <b>담당 설계사에게 전달</b>되어 상담에 활용되는 데 동의합니다.
            </span>
          </label>
        </Card>

        {/* 선택 정보 */}
        <div className="mt-3 grid grid-cols-2 gap-2.5">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="이름(선택)"
            className="rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px]" />
          <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="연락처(선택)"
            className="rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px]" />
        </div>

        {/* 파일 */}
        <label className="mt-3 block">
          <span className="text-[13px] text-ink3">증권 PDF</span>
          <input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 w-full text-[13px] file:mr-3 file:rounded-lg file:border-0 file:bg-accent-tint file:px-3 file:py-2 file:text-brand file:font-semibold" />
        </label>

        {error && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">{error}</div>
        )}

        <button
          onClick={submit}
          disabled={!canSubmit}
          className="mt-4 w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 disabled:opacity-50 active:scale-[0.99] transition"
        >
          {loading ? "분석 중…" : "무료 진단 받기"}
        </button>
        <p className="mt-3 text-[11px] text-ink3 leading-5 text-center">
          인파는 보험을 중개·권유하지 않습니다. 결과는 AI 초안이며 병력 정보는 수집하지 않습니다.
        </p>
      </main>
    </div>
  );
}
