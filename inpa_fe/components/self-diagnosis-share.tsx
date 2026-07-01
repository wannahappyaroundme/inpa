"use client";

// 셀프진단 링크 공유 위젯 — 발굴 입구(인바운드). availability-share 패턴.
// ★ 정직성: 자동발송 없음(복사/OS 공유시트까지만). 받는 분이 /d/<ref>에서 직접 동의·입력.
// ★ 제3자(잠재고객) 동의: "아는 고객에게만" 가드 문구 고정.

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/ui";
import { getProfile } from "@/lib/api";

export function SelfDiagnosisShare({
  compact = false,
  fill = false,
}: {
  compact?: boolean;
  fill?: boolean;
}) {
  const [refCode, setRefCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getProfile()
      .then((p) => setRefCode(p.ref_code))
      .catch(() => {});
  }, []);

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const link = refCode ? `${origin}/d/${refCode}` : "";
  const shareText = `보장 셀프진단 받아보세요 (1분·무료)\n${link}`;

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
      try {
        await navigator.share({ text: shareText });
      } catch {
        /* 취소 무시 */
      }
    } else {
      void copy();
    }
  }, [shareText, copy]);

  if (!refCode) return null;

  return (
    <Card
      className={`${compact ? "p-3.5" : "px-4 py-5"}${fill ? " h-full flex flex-col" : ""}`}
    >
      <div className="text-[15px] font-bold text-ink">
        고객에게 무료 보장점검 링크 보내기
      </div>
      <p className="mt-1.5 text-[14px] text-ink3 leading-6">
        고객이 이 링크에서 가입한 증권(PDF)을 올리면,
        <br />
        어떤 보장을 얼마나 들었는지{" "}
        <b className="text-ink2">1분 만에 한눈에 정리</b>해 드려요.
        <br />
        점검을 마친 고객은 내 고객 목록에 자동으로 추가됩니다.
        <br />
        <b className="text-ink2">수신 동의를 받았거나 거래 관계가 있는 고객</b>
        에게 전달하세요.
        <br />
        받는 분이 직접 동의·입력합니다.
      </p>
      {/* 하단: 링크(한 줄) + 복사·공유(아랫줄) — 2단 구성 */}
      <div className={`${fill ? "mt-auto pt-4" : "mt-3.5"} space-y-2`}>
        <input
          readOnly
          value={link}
          onFocus={(e) => e.currentTarget.select()}
          className="w-full rounded-xl border border-line bg-surface2 px-3 py-2 text-[12px] text-ink2 truncate"
        />
        <div className="flex items-center gap-2">
          <button
            onClick={copy}
            className="flex-1 rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 active:scale-[0.98] transition"
          >
            {copied ? "복사됨" : "링크 복사"}
          </button>
          <button
            onClick={share}
            className="flex-1 rounded-xl border border-line text-ink2 text-[13px] font-semibold px-3 py-2 hover:bg-surface2"
          >
            공유
          </button>
        </div>
      </div>
    </Card>
  );
}
