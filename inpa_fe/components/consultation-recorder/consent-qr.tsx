"use client";

import { useCallback, useEffect, useState } from "react";

export function ConsentQr({ url }: { url: string }) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const generate = useCallback(async () => {
    setDataUrl(null);
    setError(false);
    try {
      const QRCode = await import("qrcode");
      const image = await QRCode.toDataURL(url, {
        width: 280,
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
      <div className="rounded-xl bg-surface2 p-3 text-center" role="alert">
        <p className="text-[12px] text-ink2">QR을 다시 만들면 고객이 바로 열 수 있어요.</p>
        <button
          type="button"
          onClick={() => setAttempt((value) => value + 1)}
          className="mt-2 min-h-11 rounded-xl border border-line bg-surface px-3 text-[13px] font-bold text-brand"
        >
          QR 다시 만들기
        </button>
      </div>
    );
  }

  if (!dataUrl) {
    return (
      <div
        role="status"
        className="grid aspect-square w-40 place-items-center rounded-xl bg-surface2 text-[12px] text-ink3"
      >
        QR 만드는 중...
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={dataUrl}
      alt="상담 녹음 고객 동의 링크 QR"
      className="h-40 w-40 rounded-xl border border-line bg-white p-1"
    />
  );
}
