"use client";

// A · 고객 공유뷰. 고객이 share_token 링크로 봄 (비인증).
// ⚠️ 인파는 보험을 중개·권유하지 않음 → 공개 공유는 '보유 담보(사실)'와 '보험료 합계(사실)'만.
//    mode=neutral 강제(부족/충분 판정 라벨 없음). noindex(layout.tsx에서 robots 처리).

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { Card, DisclaimerFooter } from "@/components/ui";
import { ContentProtect, Watermark } from "@/components/content-guard";
import { SkeletonBar, SkeletonCard, SkeletonRow, TokenLoadingShell } from "@/components/token-skeleton";
import {
  getShareView,
  postShareEvent,
  ApiError,
  type ShareViewResponse,
  type ShareCoverageDetail,
} from "@/lib/api";

// ── 금액 포매터 ────────────────────────────────────────────────────────────
const krw = new Intl.NumberFormat("ko-KR");
function fmtWon(val: number | null | undefined): string {
  if (val === null || val === undefined) return "-";
  if (val >= 100_000_000) return `${krw.format(val / 100_000_000)}억원`;
  if (val >= 10_000) return `${krw.format(val / 10_000)}만원`;
  return `${krw.format(val)}원`;
}

function ShareSkeleton() {
  return (
    <TokenLoadingShell headerLabel="인파">
      <SkeletonBar w="w-32" h="h-4" />
      <SkeletonBar w="w-56" h="h-9" />
      <div className="grid grid-cols-2 gap-2.5">
        <SkeletonCard className="h-16" />
        <SkeletonCard className="h-16" />
      </div>
      <div className="space-y-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <SkeletonRow key={i} className="rounded-2xl" />
        ))}
      </div>
      {/* 하단 고정 CTA 자리 */}
      <div
        className="sticky bottom-0 -mx-5 mt-2 px-5 pt-3 bg-surface/95 border-t border-line"
        style={{ paddingBottom: "max(14px, env(safe-area-inset-bottom))" }}
      >
        <SkeletonBar h="h-[52px]" className="rounded-2xl" />
      </div>
    </TokenLoadingShell>
  );
}

function ShareNotFound() {
  return (
    <div className="mx-auto w-full max-w-md min-h-dvh flex flex-col items-center justify-center bg-surface2 px-6 text-center">
      <div className="text-[40px] mb-4">🔍</div>
      <h1 className="text-[20px] font-extrabold text-ink">링크를 열 수 없어요</h1>
      <p className="mt-2 text-[14px] text-ink3 leading-6">
        링크가 만료됐거나 잘못된 것 같아요. 담당 설계사에게 새 링크를 요청해 주세요.
      </p>
    </div>
  );
}

export default function SharePage() {
  const params = useParams();
  const token = typeof params?.token === "string" ? params.token : "";

  const [data, setData] = useState<ShareViewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!token) {
      setNotFound(true);
      setLoading(false);
      return;
    }
    getShareView(token)
      .then((res) => setData(res))
      .catch((e: unknown) => {
        // 만료/없음/네트워크 → 안내(404 포함)
        if (e instanceof ApiError) setNotFound(true);
        else setNotFound(true);
      })
      .finally(() => setLoading(false));
  }, [token]);

  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* 미지원 환경 무시 */
    }
    if (token) postShareEvent(token, "clipboard_copy");
  }, [token]);

  // ── 상담 연결 레이어 (예약 링크가 없을 때도 버튼이 항상 다음 행동으로 이어지게) ──
  const [contactOpen, setContactOpen] = useState(false);
  const [callbackSent, setCallbackSent] = useState(false);

  const handleCta = useCallback(() => {
    if (token) postShareEvent(token, "cta_click");
    // 예약 가능하면(설계사 영업시간 존재) 예약 페이지로 이동. 아니면 연락 레이어 열기.
    if (data?.booking_url) {
      window.location.href = data.booking_url;
      return;
    }
    setContactOpen((v) => !v); // 다시 누르면 접기
  }, [token, data?.booking_url]);

  const handleCallback = useCallback(() => {
    if (token) postShareEvent(token, "callback_request");
    setCallbackSent(true);
  }, [token]);

  if (loading) return <ShareSkeleton />;
  if (notFound || !data) return <ShareNotFound />;

  // 보유 담보(사실) = tree 평탄화 후 held_amount > 0 만. 공개 공유는 판정 라벨 없음.
  const held: ShareCoverageDetail[] = data.tree
    .flatMap((cat) => cat.sub_categories)
    .flatMap((sub) => sub.details)
    .filter((d) => (d.held_amount ?? 0) > 0);

  return (
    <ContentProtect className="relative mx-auto w-full max-w-md min-h-dvh flex flex-col bg-surface2">
      <Watermark text="인파 · 보장분석 공유" />
      <header className="px-5 pt-5 pb-3 bg-accent-tint">
        <div className="flex items-center gap-1.5 text-[13px] font-bold text-brand">
          <span className="text-[15px]">⌃</span> 인파
        </div>
      </header>

      <main className="flex-1 px-5 pb-6">
        {/* 고객(마스킹) 히어로 */}
        <section className="pt-6">
          <p className="text-[15px] text-ink3">{data.customer.name_masked}님의</p>
          <h1 className="mt-1 text-[24px] leading-9 font-extrabold text-ink">
            지금 보장 현황이에요
          </h1>
        </section>

        {/* 보험료 합계 (사실) */}
        <section className="mt-5 grid grid-cols-2 gap-2.5">
          {[
            { label: "월 보험료", value: fmtWon(data.summary?.monthly_premiums) },
            { label: "총 납입 보험료", value: fmtWon(data.summary?.total_premiums), accent: true },
          ].map((k) => (
            <Card key={k.label} className="px-3 py-3.5 text-center">
              <div className="text-[11px] text-ink3">{k.label}</div>
              <div className={`mt-1 text-[16px] font-extrabold tnum ${k.accent ? "text-accent" : "text-ink"}`}>
                {k.value}
              </div>
            </Card>
          ))}
        </section>

        {/* 보유 담보 (사실만 — 판정 없음) */}
        <section className="mt-5">
          <h2 className="text-[13px] font-semibold text-ink3 mb-2">지금 보장받는 담보</h2>
          {held.length > 0 ? (
            <Card className="divide-y divide-line">
              {held.map((c) => (
                <div key={c.detail_id} className="flex items-center gap-3 px-4 py-3">
                  <div className="flex-1 min-w-0 text-[15px] font-semibold text-ink">{c.name}</div>
                  <div className="text-[14px] font-bold text-ink tnum shrink-0">
                    {fmtWon(c.held_amount)}
                  </div>
                </div>
              ))}
            </Card>
          ) : (
            <Card className="px-4 py-6 text-center text-[14px] text-ink3">
              등록된 보유 담보가 아직 없어요.
            </Card>
          )}
        </section>

        {/* 면책 고지 — BE 제공 disclaimer + 정직성 레드라인 */}
        <section className="mt-4">
          <div className="rounded-xl border border-line bg-surface2 px-4 py-3 text-[12px] text-ink3 leading-5">
            {data.disclaimer ||
              "인파가 등록된 보장 정보를 정리한 참고 자료입니다."}
          </div>
        </section>

        {/* 클립보드 복사 */}
        <section className="mt-3">
          <button
            onClick={handleCopy}
            className="w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] font-semibold text-ink2 transition active:scale-[0.99]"
          >
            {copied ? "링크 복사됐어요!" : "이 링크 복사하기"}
          </button>
        </section>

        <DisclaimerFooter />
      </main>

      {/* 하단 고정 CTA */}
      <div
        className="sticky bottom-0 z-20 bg-surface/95 backdrop-blur border-t border-line px-4 pt-3"
        style={{ paddingBottom: "max(14px, env(safe-area-inset-bottom))" }}
      >
        {contactOpen && !data.booking_url && (
          <div className="mb-3 rounded-2xl border border-line bg-surface px-4 py-4">
            {callbackSent ? (
              <p className="text-[14px] font-semibold text-ink text-center leading-6">
                요청을 전달했어요. 곧 연락드릴 거예요.
              </p>
            ) : (
              <>
                <p className="text-[13px] font-semibold text-ink2">
                  담당 설계사에게 바로 연결해 드릴게요.
                </p>
                <div className="mt-2.5 space-y-2">
                  {data.planner_contact && (
                    <div className="flex gap-2">
                      <a
                        href={`tel:${data.planner_contact}`}
                        className="flex-1 rounded-xl border border-line bg-surface2 px-3 py-2.5 text-center text-[14px] font-bold text-ink"
                      >
                        전화하기
                      </a>
                      <a
                        href={`sms:${data.planner_contact}`}
                        className="flex-1 rounded-xl border border-line bg-surface2 px-3 py-2.5 text-center text-[14px] font-bold text-ink"
                      >
                        문자하기
                      </a>
                    </div>
                  )}
                  <button
                    onClick={handleCallback}
                    className="w-full rounded-xl bg-brand text-white px-3 py-2.5 text-[14px] font-bold active:scale-[0.99] transition"
                  >
                    연락 요청 남기기
                  </button>
                </div>
                <p className="mt-2 text-[11px] text-ink3 leading-4 text-center">
                  요청을 남기면 담당 설계사가 확인하고 연락드려요.
                </p>
              </>
            )}
          </div>
        )}
        <button
          onClick={handleCta}
          className="w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 active:scale-[0.99] transition"
        >
          {data.booking_url ? "바로 상담 예약하기 →" : "담당 설계사에게 물어보기"}
        </button>
      </div>
    </ContentProtect>
  );
}
