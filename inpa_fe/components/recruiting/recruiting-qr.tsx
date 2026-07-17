"use client";

import { useCallback, useEffect, useState } from "react";

export function RecruitingQr({ url }: { url: string }) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const generate = useCallback(async () => {
    if (!url) return;
    setDataUrl(null);
    setError(false);
    try {
      const QRCode = await import("qrcode");
      const image = await QRCode.toDataURL(url, {
        width: 320,
        margin: 2,
        color: { dark: "#14171F", light: "#FFFFFF" },
        errorCorrectionLevel: "M",
      });
      setDataUrl(image);
    } catch {
      setError(true);
    }
  }, [url]);

  useEffect(() => {
    void generate();
  }, [attempt, generate]);

  if (error) {
    return (
      <div role="alert" className="rounded-2xl border border-line bg-surface2 p-5 text-center">
        <p className="text-[13px] font-semibold text-ink2">
          QR을 다시 만들면 바로 저장할 수 있어요.
        </p>
        <button
          type="button"
          onClick={() => setAttempt((value) => value + 1)}
          className="mt-3 min-h-11 rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
        >
          QR 다시 만들기
        </button>
      </div>
    );
  }

  if (!dataUrl) {
    return (
      <div role="status" className="grid aspect-square w-full max-w-[240px] place-items-center rounded-2xl bg-surface2">
        <span className="text-[13px] font-semibold text-ink3">QR 만드는 중...</span>
      </div>
    );
  }

  return (
    <div className="text-center">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={dataUrl} alt="개인 소개 영입 링크 QR" className="mx-auto w-full max-w-[240px] rounded-2xl border border-line" />
      <a
        href={dataUrl}
        download="inpa-recruiting-qr.png"
        className="mt-3 inline-flex min-h-11 items-center justify-center rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
      >
        QR 이미지 저장
      </a>
    </div>
  );
}
