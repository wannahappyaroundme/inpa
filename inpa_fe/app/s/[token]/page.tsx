"use client";

// A · 고객 공유뷰 (삼쩜삼형). 고객이 share_token 링크로 봄.
// ⚠️ 인파는 보험을 중개·권유하지 않음 → '납입 현황(사실)'과 '보유 담보(사실)'만. 판정 라벨 없음.
// ★ noindex: 검색엔진 수집 차단 (개인 보험 정보 — 공개 인덱싱 불가)

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { Card, DisclaimerFooter } from "@/components/ui";
import {
  getShareView,
  postShareEvent,
  ApiError,
  type ShareViewResponse,
} from "@/lib/api";

// ── 금액 포매터 ────────────────────────────────────────────────────────────
const krw = new Intl.NumberFormat("ko-KR");
function fmtWon(val: number | null): string {
  if (val === null) return "—";
  if (val >= 100_000_000) return `${krw.format(val / 100_000_000)}억원`;
  if (val >= 10_000) return `${krw.format(val / 10_000)}만원`;
  return `${krw.format(val)}원`;
}

// ── 스켈레톤 ──────────────────────────────────────────────────────────────
function ShareSkeleton() {
  return (
    <div className="mx-auto w-full max-w-md min-h-dvh flex flex-col bg-surface2 animate-pulse">
      <div className="h-12 bg-accent-tint" />
      <div className="px-5 pt-6 space-y-3">
        <div className="h-4 w-32 rounded bg-line" />
        <div className="h-9 w-56 rounded bg-line" />
        <div className="h-2.5 w-full rounded-full bg-line mt-5" />
        <div className="mt-4 grid grid-cols-3 gap-2.5">
          {[1, 2, 3].map((i) => <div key={i} className="h-16 rounded-2xl bg-line" />)}
        </div>
        <div className="mt-4 space-y-2">
          {[1, 2, 3, 4, 5].map((i) => <div key={i} className="h-12 rounded-2xl bg-line" />)}
        </div>
      </div>
    </div>
  );
}

// ── 만료/없음 안내 ─────────────────────────────────────────────────────────
function ShareExpiredOrNotFound({ expired }: { expired: boolean }) {
  return (
    <div className="mx-auto w-full max-w-md min-h-dvh flex flex-col items-center justify-center bg-surface2 px-6 text-center">
      <div className="text-[40px] mb-4">{expired ? "⏰" : "🔍"}</div>
      <h1 className="text-[20px] font-extrabold text-ink">
        {expired ? "링크가 만료됐어요" : "링크를 찾을 수 없어요"}
      </h1>
      <p className="mt-2 text-[14px] text-ink3 leading-6">
        {expired
          ? "공유 기간이 지났어요. 담당 설계사에게 새 링크를 요청해 주세요."
          : "링크가 잘못되었거나 삭제된 것 같아요. 담당 설계사에게 확인해 주세요."}
      </p>
    </div>
  );
}

// ── 메인 컴포넌트 ──────────────────────────────────────────────────────────
export default function SharePage() {
  const params = useParams();
  const token = typeof params?.token === "string" ? params.token : "";

  const [data, setData] = useState<ShareViewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [expired, setExpired] = useState(false);
  const [notFound, setNotFound] = useState(false);

  // ── 데이터 로드 ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!token) {
      setNotFound(true);
      setLoading(false);
      return;
    }
    getShareView(token)
      .then((res) => {
        if (res.is_expired) {
          setExpired(true);
        } else {
          setData(res);
        }
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) {
          setNotFound(true);
        } else {
          // 네트워크 오류 등 — notFound로 처리(graceful degradation)
          setNotFound(true);
        }
      })
      .finally(() => setLoading(false));
  }, [token]);

  // ── 클립보드 복사 ──────────────────────────────────────────────────────
  const [copied, setCopied] = useState(false);
  const handleClipboardCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API 미지원 환경 — 조용히 무시
    }
    // 이벤트 적재 (fire-and-forget)
    if (token) postShareEvent(token, "clipboard_copy");
  }, [token]);

  // ── CTA (담당 설계사에게 물어보기) ────────────────────────────────────
  const handleCtaClick = useCallback(() => {
    if (token) postShareEvent(token, "cta_click");
    if (data?.planner_contact) {
      // 연락처가 있으면 전화/메시지 선택 시트 열기 (딥링크)
      window.location.href = `tel:${data.planner_contact.replace(/\D/g, "")}`;
    }
  }, [token, data]);

  // ── 렌더 분기 ──────────────────────────────────────────────────────────
  if (loading) return <ShareSkeleton />;
  if (expired) return <ShareExpiredOrNotFound expired={true} />;
  if (notFound || !data) return <ShareExpiredOrNotFound expired={false} />;

  const ps = data.payment_summary;
  const progress = ps.pay_progress ?? 0;

  return (
    <>
      {/* noindex — 개인 보험정보 검색엔진 수집 차단 */}
      {/* Next.js metadata export는 Server Component에서만 가능 — client에서는 head 직접 삽입 없이
          이 주석을 가이드로 남김. 실 운영 시 layout.tsx에서 robots="noindex,nofollow" 처리 권장. */}

      <div className="mx-auto w-full max-w-md min-h-dvh flex flex-col bg-surface2">
        {/* 설계사 브랜딩 미니 헤더 */}
        <header className="px-5 pt-5 pb-3 bg-accent-tint">
          <div className="text-[13px] font-semibold text-brand">{data.planner_name}</div>
        </header>

        <main className="flex-1 px-5 pb-6">
          {/* 납입 현황 히어로 */}
          <section className="pt-6 pb-1">
            <p className="text-[15px] text-ink3">
              {data.customer_name}님
              {ps.product_name ? ` · ${ps.product_name}` : ""}
            </p>

            {ps.remaining_amount !== null ? (
              <h1 className="mt-2 text-[26px] leading-9 font-extrabold text-ink">
                만기까지 앞으로
                <br />
                <span className="text-accent">{fmtWon(ps.remaining_amount)}</span> 더 내면 끝이에요
              </h1>
            ) : (
              <h1 className="mt-2 text-[24px] leading-9 font-extrabold text-ink">
                납입 현황을 확인해 보세요
              </h1>
            )}

            {ps.expiry_text && (
              <p className="mt-1.5 text-[13px] text-ink3">{ps.expiry_text}</p>
            )}

            {/* 납입률 */}
            {ps.pay_progress !== null && (
              <div className="mt-5">
                <div className="flex justify-between text-[12px] text-ink3 mb-1.5">
                  <span>납입률</span>
                  <span className="font-bold text-ink2 tnum">{progress}%</span>
                </div>
                <div className="h-2.5 rounded-full bg-line overflow-hidden">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
                  />
                </div>
                <div className="mt-2 flex justify-between text-[12px]">
                  <span className="text-ink3">
                    낸 보험료{" "}
                    <b className="text-ink2 tnum">{fmtWon(ps.paid_amount)}</b>
                  </span>
                  <span className="text-ink3">
                    남은 보험료{" "}
                    <b className="text-ink2 tnum">{fmtWon(ps.remaining_amount)}</b>
                  </span>
                </div>
              </div>
            )}
          </section>

          {/* KPI 카드 3 (사실) */}
          <section className="mt-5 grid grid-cols-3 gap-2.5">
            {[
              { label: "월 보험료", value: fmtWon(ps.monthly_premiums) },
              { label: "낸 보험료", value: fmtWon(ps.paid_amount) },
              {
                label: "남은 보험료",
                value: fmtWon(ps.remaining_amount),
                accent: true,
              },
            ].map((k) => (
              <Card key={k.label} className="px-3 py-3.5 text-center">
                <div className="text-[11px] text-ink3">{k.label}</div>
                <div
                  className={`mt-1 text-[15px] font-extrabold tnum ${
                    k.accent ? "text-accent" : "text-ink"
                  }`}
                >
                  {k.value}
                </div>
              </Card>
            ))}
          </section>

          {/* 보유 담보 (사실만 — 판정 없음) */}
          {data.coverages.length > 0 && (
            <section className="mt-5">
              <h2 className="text-[13px] font-semibold text-ink3 mb-2">
                지금 보장받는 담보
              </h2>
              <Card className="divide-y divide-line">
                {data.coverages.map((c, idx) => (
                  <div
                    key={`${c.name}-${idx}`}
                    className="flex items-center gap-3 px-4 py-3"
                  >
                    <div className="flex-1 min-w-0 text-[15px] font-semibold text-ink">
                      {c.name}
                    </div>
                    <div className="text-[14px] font-bold text-ink tnum shrink-0">
                      {c.amount_text}
                    </div>
                  </div>
                ))}
              </Card>
            </section>
          )}

          {/* AI 면책 고지 — 정직성 레드라인 */}
          <section className="mt-4">
            <div className="rounded-xl border border-line bg-surface2 px-4 py-3 text-[12px] text-ink3 leading-5">
              이 자료는 등록된 증권 정보를 정리한 것이에요.{" "}
              <b className="font-semibold text-ink3">보장이 충분한지 판단은 담당 설계사</b>를 통해 확인해 주세요.
              AI가 처리한 초안이며, 최종 책임은 설계사에게 있습니다.
            </div>
          </section>

          {/* 설계사 배너 */}
          <section className="mt-4">
            <div className="flex items-center gap-3 rounded-2xl bg-accent-tint px-4 py-3.5">
              <div className="flex-1">
                <div className="text-[15px] font-bold text-ink">
                  내 보장, 이대로 괜찮은지 궁금하다면
                </div>
                <div className="text-[13px] font-semibold text-brand">
                  담당 설계사와 확인하기 ›
                </div>
              </div>
              <div className="w-9 h-9 rounded-full bg-brand/10 flex items-center justify-center text-[18px]">
                💬
              </div>
            </div>
          </section>

          {/* 클립보드 복사 */}
          <section className="mt-3">
            <button
              onClick={handleClipboardCopy}
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
          <button
            onClick={handleCtaClick}
            className="w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 active:scale-[0.99] transition"
          >
            담당 설계사에게 물어보기
          </button>
        </div>
      </div>
    </>
  );
}
