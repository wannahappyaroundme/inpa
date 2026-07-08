"use client";

// ════════════════════════════════════════════════════════════════════════════
// CoverageFlagModal — 한눈표에서 "담보 위치가 이상해요"를 누르면 뜨는 모달.
// 그 표준 담보에 연결된 내역(coverage-cases)을 골라 운영팀에 확인을 요청한다.
// 반영되면 다음 분석부터 자동 적용(정규화 사전 admin_verified).
//
// ★ 카피 가드(§6): 긍정 프레이밍, '신고' 대신 '알려주기/확인 요청', em-dash 금지.
//   설계사 내부 화면 전용(고객 대면 아님). 라이트 테마 고정(dark: 없음).
// ════════════════════════════════════════════════════════════════════════════

import { useEffect, useState } from "react";
import {
  getCoverageCases,
  createCoverageFlag,
  type CoverageCase,
} from "@/lib/api";
import { fmtAmount } from "@/components/heatmap";

interface CoverageFlagModalProps {
  customerId: number;
  detailId: number;
  detailName: string;
  onClose: () => void;
}

export function CoverageFlagModal({
  customerId,
  detailId,
  detailName,
  onClose,
}: CoverageFlagModalProps) {
  const [cases, setCases] = useState<CoverageCase[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let alive = true;
    getCoverageCases(customerId, detailId)
      .then((rows) => {
        if (!alive) return;
        setCases(rows);
        // 정확히 1건이면 자동 선택
        if (rows.length === 1) setSelectedCaseId(rows[0].case_id);
      })
      .catch(() => {
        if (alive) {
          setCases([]);
          setLoadError(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [customerId, detailId]);

  async function handleSubmit() {
    setSending(true);
    setSendError(null);
    try {
      await createCoverageFlag(customerId, {
        analysis_detail_id: detailId,
        ...(selectedCaseId != null ? { case_id: selectedCaseId } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      });
      setDone(true);
    } catch {
      setSendError("전송이 잠시 어려워요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="coverage-flag-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full sm:max-w-md bg-surface rounded-t-3xl sm:rounded-2xl px-6 pt-6 pb-7 shadow-xl">
        {done ? (
          <>
            <h2 id="coverage-flag-title" className="text-[18px] font-extrabold text-ink">
              알려주셔서 감사해요
            </h2>
            <p className="mt-3 text-[14px] text-ink2 leading-6">
              확인 후 다음 분석부터 자동으로 바로잡을게요.
            </p>
            <button
              onClick={onClose}
              className="mt-6 w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 transition"
            >
              확인
            </button>
          </>
        ) : (
          <>
            <h2 id="coverage-flag-title" className="text-[18px] font-extrabold text-ink">
              담보 위치가 이상해요
            </h2>
            <p className="mt-2 text-[13px] text-ink2 leading-5">
              <b className="text-ink">{detailName}</b> 칸에 잘못 잡힌 담보가 있다면
              알려주세요. 운영팀이 확인해 다음 분석부터 자동으로 바로잡아요.
            </p>

            {/* 케이스 선택 */}
            <div className="mt-4">
              {cases === null && (
                <div className="py-4 text-center text-[13px] text-ink3">불러오는 중...</div>
              )}
              {cases !== null && cases.length === 0 && (
                <div className="rounded-xl bg-surface2 border border-line px-3.5 py-3 text-[13px] text-ink2">
                  {loadError
                    ? "내역을 잠시 불러오기 어려워요. 아래 메모로 상황을 알려주시면 확인해 드릴게요."
                    : "이 칸은 연결된 담보 내역 없이 비어 있어요. 아래 메모로 상황을 알려주시면 확인해 드릴게요."}
                </div>
              )}
              {cases !== null && cases.length > 0 && (
                <fieldset>
                  <legend className="text-[12px] font-semibold text-ink3 mb-1.5">
                    어떤 담보인가요?
                  </legend>
                  <div className="max-h-52 overflow-y-auto space-y-1.5">
                    {cases.map((c) => (
                      <label
                        key={c.case_id}
                        className={`flex items-start gap-2.5 rounded-xl border px-3 py-2.5 cursor-pointer transition ${
                          selectedCaseId === c.case_id
                            ? "border-brand bg-brand-soft"
                            : "border-line bg-surface hover:border-brand"
                        }`}
                      >
                        <input
                          type="radio"
                          name="coverage-flag-case"
                          className="mt-0.5 accent-brand"
                          checked={selectedCaseId === c.case_id}
                          onChange={() => setSelectedCaseId(c.case_id)}
                        />
                        <span className="min-w-0">
                          <span className="block text-[13px] font-semibold text-ink leading-4 break-all">
                            {c.raw_name || c.name}
                          </span>
                          <span className="mt-0.5 block text-[11px] text-ink3">
                            {c.insurance_title || "이름 없는 보험"} ·{" "}
                            <span className="tnum">{fmtAmount(c.assurance_amount)}</span>
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}
            </div>

            {/* 한 줄 메모 (선택) */}
            <div className="mt-4">
              <label
                htmlFor="coverage-flag-note"
                className="block text-[12px] font-semibold text-ink3 mb-1"
              >
                메모 (선택)
              </label>
              <input
                id="coverage-flag-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={300}
                placeholder="예: 이 담보는 유사암 진단비 같아요"
                className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
              />
            </div>

            {sendError && (
              <p className="mt-3 text-[12px] text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2">
                {sendError}
              </p>
            )}

            <div className="mt-5 flex flex-col gap-2.5">
              <button
                onClick={handleSubmit}
                disabled={sending || cases === null}
                className="w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 disabled:opacity-50 transition"
              >
                {sending ? "보내는 중..." : "확인 요청 보내기"}
              </button>
              <button
                onClick={onClose}
                className="w-full rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 py-3 transition"
              >
                닫기
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
