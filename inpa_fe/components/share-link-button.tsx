"use client";

// 고객 공유 링크 버튼 — 보장 한눈표 공유뷰(/s/<token>) 발급 + 복사.
// ★ 정직성: 이건 '보장 현황' 공유지 §97 비교안내서(승환 권유)가 아님. 자동발송 없음(복사까지만).

import { useState, useCallback } from "react";
import { createShareLink, ApiError } from "@/lib/api";
import { copyText } from "@/lib/clipboard";

export function ShareLinkButton({ customerId }: { customerId: number }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [expires, setExpires] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await createShareLink(customerId);
      const origin = typeof window !== "undefined" ? window.location.origin : "";
      setUrl(`${origin}${r.share_url}`);
      setExpires(r.share_expires_at);
      setOpen(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "공유 링크 생성에 실패했어요.");
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  const copy = useCallback(async () => {
    if (await copyText(url)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    }
  }, [url]);

  return (
    <>
      <button
        type="button"
        onClick={generate}
        disabled={loading}
        className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition disabled:opacity-60"
      >
        {loading ? "생성 중…" : "공유 링크"}
      </button>
      {error && <span className="text-[12px] text-danger self-center">{error}</span>}
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 sm:p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full sm:max-w-md bg-surface rounded-t-2xl sm:rounded-2xl p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-[16px] font-extrabold text-ink">고객 공유 링크</h2>
              <button onClick={() => setOpen(false)} aria-label="닫기" className="text-ink3 text-[20px] leading-none px-1">✕</button>
            </div>
            <p className="mt-1 text-[12px] text-ink3 leading-5">
              고객에게 <b>보장 한눈표(현황)</b>를 보여주는 링크예요. AI 비교안내서가 아니라 보유 보장 공유이고, 자동 발송은 없어요. 복사해서 직접 전달하세요.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <input
                readOnly
                value={url}
                onFocus={(e) => e.currentTarget.select()}
                className="flex-1 min-w-0 rounded-xl border border-line bg-surface2 px-3 py-2 text-[12px] text-ink2 truncate"
              />
              <button onClick={copy} className="shrink-0 rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2">
                {copied ? "복사됨" : "복사"}
              </button>
            </div>
            <p className="mt-2 text-[11px] text-ink3">
              만료: {expires ? new Date(expires).toLocaleDateString("ko-KR") : "-"} (90일) · 다시 만들면 이전 링크는 즉시 만료돼요.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
