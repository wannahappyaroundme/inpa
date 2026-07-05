"use client";

// 오늘 전화할 고객 — 공용 목록 컴포넌트 (홈 카드에서 /call-list 전용 화면으로 이동, 2026-07-05).
// pull 방식: 마운트 시 계산 요청. 행 = 이름(고객 상세 링크) + 사유 칩 + 전화/문자/화법 버튼.
// reasons 는 BE가 내려주는 한글 라벨 그대로 칩으로 렌더(연락 우선순위, 판정 아님).
import Link from "next/link";
import { useEffect, useState } from "react";
import { getCallList, type CallListResponse } from "@/lib/api";

export function CallList({ limit }: { limit?: number }) {
  const [data, setData] = useState<CallListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0); // 증가 = 다시 시도

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(false);
    getCallList(limit)
      .then((r) => { if (alive) setData(r); })
      .catch(() => { if (alive) setError(true); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [limit, refresh]);

  if (loading) {
    return (
      <div className="space-y-2" aria-hidden>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-10 rounded-xl bg-surface2 animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-5 text-center">
        <p className="text-[13px] text-ink3">목록을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.</p>
        <button
          type="button"
          onClick={() => setRefresh((n) => n + 1)}
          className="mt-2 px-3.5 py-1.5 rounded-lg bg-surface2 text-[12px] font-semibold text-ink2 hover:text-ink transition-colors"
        >
          다시 시도
        </button>
      </div>
    );
  }

  if (!data || data.results.length === 0) {
    return (
      <p className="py-5 text-center text-[13px] text-ink3">
        오늘은 챙길 고객을 다 챙겼어요. 새 고객 발굴에 시간을 써보세요.
      </p>
    );
  }

  return (
    <>
      {data.total_candidates > data.results.length && (
        <p className="mb-2 text-right text-[12px] text-ink3">
          챙길 고객 {data.total_candidates}명 중 상위 {data.results.length}명
        </p>
      )}
      <ul className="divide-y divide-line">
        {data.results.map((c) => (
          <li key={c.id} className="py-2.5 flex items-center gap-3">
            <div className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
              <Link
                href={`/customer/${c.id}`}
                className="text-[14px] font-bold text-ink hover:text-brand transition-colors"
              >
                {c.name}
              </Link>
              {c.reasons.slice(0, 3).map((r) => (
                <span
                  key={r}
                  className="px-1.5 py-0.5 rounded-md bg-surface2 text-[11px] font-semibold text-ink2 tnum"
                >
                  {r}
                </span>
              ))}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              {c.mobile_phone_number && (
                <>
                  <a
                    href={`tel:${c.mobile_phone_number}`}
                    className="px-2.5 py-1 rounded-lg bg-brand-soft text-[12px] font-semibold text-brand hover:opacity-80 transition-opacity"
                  >
                    전화
                  </a>
                  <a
                    href={`sms:${c.mobile_phone_number}`}
                    className="px-2.5 py-1 rounded-lg bg-surface2 text-[12px] font-semibold text-ink2 hover:text-ink transition-colors"
                  >
                    문자
                  </a>
                </>
              )}
              <Link
                href={`/scripts?customer=${encodeURIComponent(c.name)}`}
                className="px-2.5 py-1 rounded-lg bg-surface2 text-[12px] font-semibold text-ink2 hover:text-ink transition-colors"
              >
                화법
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
