"use client";

// 셀프진단 인바운드(공개·비로그인) — 잠재고객이 ?ref 설계사 링크로 본인 증권 진단.
// ★ 본인 식별 정보(이름·연락처·생년월일·성별) 필수. 개인정보 수집·이용(설계사 전달) 동의 필수.
//   국외이전(Claude)·제3자 제공·마케팅은 선택(법상 강제 금지). 증권 PDF는 선택 — 없으면 리드만 접수.
//   결과는 보유 담보 '사실'만(neutral). 병력 미수집. AI 초안·중개권유 아님·최종책임 설계사.

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { Card } from "@/components/ui";
import { InpaMark } from "@/components/inpa-logo";
import { postSelfDiagnosis, ApiError, type SelfDiagnosisResult } from "@/lib/api";

const krw = new Intl.NumberFormat("ko-KR");
function fmtWon(v: number | null | undefined): string {
  if (v === null || v === undefined) return "-";
  if (v >= 100_000_000) return `${krw.format(v / 100_000_000)}억원`;
  if (v >= 10_000) return `${krw.format(v / 10_000)}만원`;
  return `${krw.format(v)}원`;
}

const pad2 = (s: string) => s.padStart(2, "0");
const THIS_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 101 }, (_, i) => THIS_YEAR - i); // 올해 ~ 100년 전
const MONTHS = Array.from({ length: 12 }, (_, i) => String(i + 1));
const DAYS = Array.from({ length: 31 }, (_, i) => String(i + 1));

// 분석 중 돌아가는 안내 문구 — 지루하지 않게 순환.
const LOADING_MSGS = [
  "증권을 살펴보고 있어요",
  "보장 내용을 스캔하고 있어요",
  "담보를 하나씩 정리하고 있어요",
  "거의 다 됐어요",
];

export default function SelfDiagnosisPage() {
  const params = useParams();
  const ref = typeof params?.ref === "string" ? params.ref : "";

  const [consentOverseas, setConsentOverseas] = useState(false);
  const [consentShare, setConsentShare] = useState(false);
  const [consentMarketing, setConsentMarketing] = useState(false);
  const [consentThirdParty, setConsentThirdParty] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [birthY, setBirthY] = useState("");
  const [birthM, setBirthM] = useState("");
  const [birthD, setBirthD] = useState("");
  const [gender, setGender] = useState(""); // '1'(남) | '2'(여)
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false); // 증권 분석 로딩 화면(파일 있을 때만)
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SelfDiagnosisResult | null>(null);
  const [showNoPdfModal, setShowNoPdfModal] = useState(false);
  const [msgIdx, setMsgIdx] = useState(0);

  // 로딩 문구 순환
  useEffect(() => {
    if (!analyzing) return;
    setMsgIdx(0);
    const t = setInterval(() => setMsgIdx((i) => (i + 1) % LOADING_MSGS.length), 1600);
    return () => clearInterval(t);
  }, [analyzing]);

  const allAgreed = consentOverseas && consentShare && consentMarketing && consentThirdParty;
  const agreeAll = () => {
    const next = !allAgreed;
    setConsentOverseas(next);
    setConsentShare(next);
    setConsentMarketing(next);
    setConsentThirdParty(next);
  };

  const phoneDigits = phone.replace(/[^0-9]/g, "");
  const birth = birthY && birthM && birthD ? `${birthY}-${pad2(birthM)}-${pad2(birthD)}` : "";

  const submit = async () => {
    // 본인 식별 정보 필수 검증
    if (!name.trim()) return setError("이름을 입력해 주세요.");
    if (!/^01[0-9]{8,9}$/.test(phoneDigits)) return setError("올바른 휴대폰 번호를 입력해 주세요.");
    if (!birth) return setError("생년월일을 선택해 주세요.");
    if (!gender) return setError("성별을 선택해 주세요.");
    if (!consentOverseas || !consentShare) return setError("필수 동의 항목에 체크해 주세요.");

    setError(null);
    setLoading(true);
    if (file) setAnalyzing(true);

    const fd = new FormData();
    fd.append("name", name.trim());
    fd.append("phone", phoneDigits);
    fd.append("birth", birth);
    fd.append("gender", gender);
    fd.append("consent_overseas", "true");
    fd.append("consent_share", "true");
    if (consentMarketing) fd.append("consent_marketing", "true");
    if (consentThirdParty) fd.append("consent_thirdparty", "true");
    if (file) fd.append("file", file);

    try {
      const res = await postSelfDiagnosis(ref, fd);
      if (file) setResult(res);
      else setShowNoPdfModal(true);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "잠시 후 다시 시도해 주세요.");
    } finally {
      setLoading(false);
      setAnalyzing(false);
    }
  };

  // ── 분석 로딩 화면 (증권 PDF 첨부 시) ──
  if (analyzing && !result) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 flex flex-col items-center justify-center px-8 text-center">
        <InpaMark live intense size={104} className="overflow-visible" pColor="#1E40C4" />
        <div className="mt-10 text-[19px] font-extrabold text-ink leading-7">{LOADING_MSGS[msgIdx]}</div>
        <p className="mt-2 text-[13px] text-ink3 leading-5">
          증권을 자동으로 정리하고 있어요. 잠시만 기다려 주세요.
        </p>
      </div>
    );
  }

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
            {result.disclaimer || "인파가 등록된 보장 정보를 정리한 참고 자료입니다."}
          </div>
          {result.booking_url ? (
            <>
              <a
                href={result.booking_url}
                className="mt-3 block rounded-2xl bg-brand text-white text-center text-[16px] font-bold py-4 hover:opacity-90 transition"
              >
                바로 상담 예약하기 →
              </a>
              <p className="mt-2 text-center text-[12px] text-ink3">
                편한 시간을 직접 고르면 담당 설계사가 확인해 드려요.
              </p>
            </>
          ) : (
            <div className="mt-3 rounded-2xl bg-brand text-white text-center text-[15px] font-bold py-4">
              담당 설계사가 곧 연락드릴 거예요 🙌
            </div>
          )}
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
          간단한 정보만 남기면 담당 설계사가 보장을 살펴드려요. 증권(PDF)을 올리면 보유 담보까지 바로 정리해 드립니다.
        </p>

        {/* 본인 정보 (필수) */}
        <Card className="mt-5 px-4 py-4 space-y-3">
          <div className="text-[13px] font-bold text-ink">본인 정보</div>
          <div className="grid grid-cols-2 gap-2.5">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="이름"
              className="rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px]" />
            <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" placeholder="연락처(- 없이)"
              className="rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px]" />
          </div>

          <div>
            <div className="text-[12px] text-ink3 mb-1">생년월일</div>
            <div className="grid grid-cols-3 gap-2">
              <select value={birthY} onChange={(e) => setBirthY(e.target.value)}
                className="rounded-xl border border-line bg-surface px-2 py-2.5 text-[14px]">
                <option value="">년</option>
                {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
              <select value={birthM} onChange={(e) => setBirthM(e.target.value)}
                className="rounded-xl border border-line bg-surface px-2 py-2.5 text-[14px]">
                <option value="">월</option>
                {MONTHS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <select value={birthD} onChange={(e) => setBirthD(e.target.value)}
                className="rounded-xl border border-line bg-surface px-2 py-2.5 text-[14px]">
                <option value="">일</option>
                {DAYS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
          </div>

          <div>
            <div className="text-[12px] text-ink3 mb-1">성별</div>
            <div className="grid grid-cols-2 gap-2">
              {([["1", "남"], ["2", "여"]] as const).map(([val, label]) => (
                <button key={val} type="button" onClick={() => setGender(val)}
                  className={`rounded-xl border py-2.5 text-[14px] font-semibold transition ${
                    gender === val ? "border-brand bg-accent-tint text-brand" : "border-line bg-surface text-ink2"
                  }`}>
                  {label}
                </button>
              ))}
            </div>
          </div>
        </Card>

        {/* 증권 PDF (선택) */}
        <Card className="mt-3 px-4 py-4">
          <div className="text-[13px] font-bold text-ink">증권 PDF <span className="font-normal text-ink3">(선택)</span></div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">올리면 보유 담보를 바로 정리해 드려요. 없으면 설계사가 직접 도와드립니다.</p>
          <input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-2 w-full text-[13px] file:mr-3 file:rounded-lg file:border-0 file:bg-accent-tint file:px-3 file:py-2 file:text-brand file:font-semibold" />
          {file && <div className="mt-2 text-[12px] text-brand font-semibold truncate">📄 {file.name}</div>}
        </Card>

        {/* 동의 */}
        <Card className="mt-3 px-4 py-4">
          <button type="button" onClick={agreeAll}
            className={`w-full rounded-xl border py-2.5 text-[14px] font-bold transition ${
              allAgreed ? "border-brand bg-brand text-white" : "border-brand/40 bg-accent-tint text-brand"
            }`}>
            {allAgreed ? "전체 동의 완료" : "전체 동의하기"}
          </button>
          <div className="mt-3 space-y-3">
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input type="checkbox" checked={consentOverseas} onChange={(e) => setConsentOverseas(e.target.checked)} className="mt-0.5" />
              <span className="text-[13px] text-ink2 leading-5">
                <b>(필수)</b> 증권 분석을 위해 보험정보가 Claude API(미국, Anthropic)로 <b>국외이전</b>되는 데 동의합니다.
              </span>
            </label>
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input type="checkbox" checked={consentShare} onChange={(e) => setConsentShare(e.target.checked)} className="mt-0.5" />
              <span className="text-[13px] text-ink2 leading-5">
                <b>(필수)</b> 내 정보가 <b>담당 설계사에게 전달</b>되어 보장 상담에 활용(수집·이용)되는 데 동의합니다.
              </span>
            </label>
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input type="checkbox" checked={consentThirdParty} onChange={(e) => setConsentThirdParty(e.target.checked)} className="mt-0.5" />
              <span className="text-[13px] text-ink2 leading-5">
                <b>(선택)</b> 인파(플랫폼)가 더 나은 보장 분석·맞춤 안내를 위해 내 정보를 보관·활용하는 데 동의합니다. (거부해도 진단은 진행돼요)
              </span>
            </label>
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input type="checkbox" checked={consentMarketing} onChange={(e) => setConsentMarketing(e.target.checked)} className="mt-0.5" />
              <span className="text-[13px] text-ink2 leading-5">
                <b>(선택)</b> 보장 관련 유용한 정보·이벤트 안내를 받는 데 동의합니다. (거부해도 진단은 진행돼요)
              </span>
            </label>
          </div>
        </Card>

        {error && (
          <div className="mt-3 rounded-xl border border-line bg-danger-tint px-4 py-2.5 text-[13px] text-danger">{error}</div>
        )}

        <button
          onClick={submit}
          disabled={loading}
          className="mt-4 w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 disabled:opacity-50 active:scale-[0.99] transition"
        >
          {loading ? "처리 중…" : file ? "무료 진단 받기" : "상담 신청하기"}
        </button>
        <p className="mt-3 text-[11px] text-ink3 leading-5 text-center">
          인파는 보험을 중개하지 않습니다. 결과는 참고용이며, 병력 정보는 수집하지 않습니다.
        </p>
      </main>

      {/* 증권 미첨부 → 접수 안내 모달 */}
      {showNoPdfModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-6">
          <div className="w-full max-w-sm rounded-2xl bg-surface p-6 text-center shadow-card">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-accent-tint">
              <InpaMark size={34} pColor="#1E40C4" />
            </div>
            <h3 className="mt-4 text-[18px] font-extrabold text-ink">상담 신청이 접수됐어요</h3>
            <p className="mt-2 text-[14px] text-ink3 leading-6">
              담당 설계사가 직접 연락드려 보장을 꼼꼼히 살펴드릴게요. 증권을 준비해 두시면 더 빠르게 도와드릴 수 있어요.
            </p>
            <button onClick={() => setShowNoPdfModal(false)}
              className="mt-5 w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 active:scale-[0.99] transition">
              나가기
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
