import { Card } from "@/components/ui";
import type { ShareCoverageDetail, ShareSnapshotArchivePayload } from "@/lib/api";

const krw = new Intl.NumberFormat("ko-KR");

function fmtWon(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  if (value >= 100_000_000) return `${krw.format(value / 100_000_000)}억원`;
  if (value >= 10_000) return `${krw.format(value / 10_000)}만원`;
  return `${krw.format(value)}원`;
}

function heldCoverages(payload: ShareSnapshotArchivePayload): ShareCoverageDetail[] {
  return payload.tree
    .flatMap((category) => category.sub_categories)
    .flatMap((subcategory) => subcategory.details)
    .filter((detail) => (detail.held_amount ?? 0) > 0);
}

function capturedAtLabel(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
}

/** 저장된 분석 본문만 표시한다. 예약·전화·문자 같은 현재 행동은 이 컴포넌트에 넣지 않는다. */
export function ShareSnapshotContent({
  payload,
  variant,
}: {
  payload: ShareSnapshotArchivePayload;
  variant: "public" | "preview";
}) {
  const held = heldCoverages(payload);
  const publicView = variant === "public";
  const capturedAt = capturedAtLabel(
    "captured_at" in payload ? payload.captured_at : null,
  );

  return (
    <>
      <section className={publicView ? "pt-6" : "rounded-xl border border-line bg-surface2 px-3 py-2.5"}>
        <p className={publicView ? "text-[15px] text-ink3" : "text-[12px] text-ink3"}>
          <span className={publicView ? "" : "font-semibold text-ink2"}>
            {payload.customer.name_masked}
          </span>
          님의
        </p>
        <h1 className={publicView ? "mt-1 text-[24px] font-extrabold leading-9 text-ink" : "mt-0.5 text-[13px] font-semibold text-ink"}>
          공유 당시 보장 현황이에요
        </h1>
        {publicView && capturedAt && (
          <p className="mt-1 text-[12px] text-ink3">공유 당시 {capturedAt}</p>
        )}
      </section>

      <section className={publicView ? "mt-5 grid grid-cols-2 gap-2.5" : "mt-3 grid grid-cols-2 gap-2"}>
        {[
          { label: "월 보험료", value: fmtWon(payload.summary.monthly_premiums), accent: false },
          { label: "총 납입 보험료", value: fmtWon(payload.summary.total_premiums), accent: true },
        ].map((summary) => (
          <Card key={summary.label} className={publicView ? "px-3 py-3.5 text-center" : "px-3 py-2.5 text-center"}>
            <div className="text-[11px] text-ink3">{summary.label}</div>
            <div className={`${publicView ? "mt-1 text-[16px]" : "mt-0.5 text-[14px]"} font-extrabold tnum ${summary.accent ? "text-accent" : "text-ink"}`}>
              {summary.value}
            </div>
          </Card>
        ))}
      </section>

      <section className={publicView ? "mt-5" : "mt-3"}>
        <h2 className="mb-2 text-[13px] font-semibold text-ink3">
          공유 당시 담보
        </h2>
        {held.length > 0 ? (
          <Card className="divide-y divide-line">
            {held.map((coverage) => (
              <div
                key={coverage.detail_id}
                className={`flex items-center gap-3 ${publicView ? "px-4 py-3" : "px-3 py-2.5"}`}
              >
                <div className={`min-w-0 flex-1 font-semibold text-ink ${publicView ? "text-[15px]" : "text-[13px]"}`}>
                  {coverage.name}
                </div>
                <div className={`${publicView ? "text-[14px]" : "text-[13px]"} shrink-0 font-bold text-ink tnum`}>
                  {fmtWon(coverage.held_amount)}
                </div>
              </div>
            ))}
          </Card>
        ) : (
          <Card className={`${publicView ? "px-4 py-6 text-[14px]" : "px-3 py-6 text-[12px]"} text-center text-ink3`}>
            {publicView
              ? "담당 설계사님이 보장 정보를 정리하고 있어요."
              : "공유 당시 등록된 보유 담보가 없었어요."}
          </Card>
        )}
      </section>

      {!publicView && (
        <section className="mt-3">
          <div className="rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[11px] leading-5 text-ink3">
            {payload.disclaimer || "인파가 등록된 보장 정보를 정리한 참고 자료입니다."}
          </div>
        </section>
      )}

    </>
  );
}
