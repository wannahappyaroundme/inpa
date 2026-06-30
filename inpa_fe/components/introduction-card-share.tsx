"use client";

// 내 소개 카드 공유 위젯 — self-diagnosis-share 패턴. /p/<ref> 링크를 카톡·문자·명함QR로.
// ★ 자동발송 없음(복사/OS 공유시트까지만). 받는 분이 소개 카드에서 직접 신청·동의.

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/ui";
import { getProfile } from "@/lib/api";

export function IntroductionCardShare() {
  const [refCode, setRefCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getProfile().then((p) => setRefCode(p.ref_code)).catch(() => {});
  }, []);

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const link = refCode ? `${origin}/p/${refCode}` : "";
  const shareText = `제 소개 카드예요. 무료 보장점검·상담 신청을 한 번에 하실 수 있어요.\n${link}`;

  const copy = useCallback(async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(shareText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* 미지원 환경 무시 */
    }
  }, [shareText, link]);

  const share = useCallback(async () => {
    if (typeof navigator !== "undefined" && navigator.share) {
      try { await navigator.share({ text: shareText }); } catch { /* 취소 무시 */ }
    } else {
      void copy();
    }
  }, [shareText, copy]);

  if (!refCode) return null;

  return (
    <Card className="p-4">
      <div className="text-[15px] font-bold text-ink">내 소개 카드 보내기</div>
      <p className="mt-1 text-[12px] text-ink3 leading-5">
        내 이름·소속·한줄소개가 담긴 <b className="text-ink2">디지털 명함</b>이에요. 카톡·문자로 보내거나 명함에 QR로 넣으세요. 받은 분이 <b className="text-ink2">무료 보장점검</b>을 받거나 <b className="text-ink2">상담을 신청</b>하면 내 고객 목록(DB)에 자동으로 추가됩니다. (한줄소개는 설정에서 바꿔요)
      </p>
      <div className="mt-2.5 flex items-center gap-2">
        <input
          readOnly
          value={link}
          onFocus={(e) => e.currentTarget.select()}
          className="flex-1 min-w-0 rounded-xl border border-line bg-surface2 px-3 py-2 text-[12px] text-ink2 truncate"
        />
        <button
          onClick={copy}
          className="shrink-0 rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 active:scale-[0.98] transition"
        >
          {copied ? "복사됨" : "링크 복사"}
        </button>
        <button
          onClick={share}
          className="shrink-0 rounded-xl border border-line text-ink2 text-[13px] font-semibold px-3 py-2 hover:bg-surface2"
        >
          공유
        </button>
      </div>
    </Card>
  );
}
