"use client";

import { useState } from "react";

import { trackPublicResourceUse } from "@/lib/public-resource-events";

export const CUSTOMER_MANAGEMENT_CSV =
  "\ufeff고객명,연락처,영업 단계,진행 상태,마지막 연락일,다음 행동,메모\r\n";

const COLUMNS = [
  ["고객명", "고객을 구분할 이름"],
  ["연락처", "전화나 문자에 쓰는 연락처"],
  ["영업 단계", "DB, TA, FA, 청약"],
  ["진행 상태", "진행중, 보류, 휴면, 종료"],
  ["마지막 연락일", "마지막으로 연락한 날짜"],
  ["다음 행동", "다음 연락이나 상담 준비"],
  ["메모", "기억할 상담 내용"],
] as const;

export function CustomerManagementSheet() {
  const [downloaded, setDownloaded] = useState(false);

  function download() {
    const blob = new Blob([CUSTOMER_MANAGEMENT_CSV], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "inpa-customer-management-sheet.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setDownloaded(true);
      trackPublicResourceUse("customer_sheet", "download", "resource");
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  return (
    <section className="rounded-3xl border border-line bg-surface p-5 shadow-card sm:p-8" aria-labelledby="customer-sheet-title">
      <p className="text-[12px] font-extrabold tracking-[0.14em] text-brand">빈 양식으로 시작</p>
      <h2 id="customer-sheet-title" className="mt-2 text-[26px] font-black text-brand-ink sm:text-[30px]">고객 관리표 항목</h2>
      <p className="mt-3 max-w-2xl text-[14px] leading-7 text-ink3">
        샘플 고객 없이 제목 행만 들어 있습니다. 내려받은 뒤 엑셀이나 구글 시트에서 내 고객 정보를 직접 입력해 주세요.
      </p>

      <div className="mt-7 overflow-hidden rounded-2xl border border-line">
        <div className="grid bg-brand-ink px-4 py-3 text-[12px] font-bold text-white sm:grid-cols-[180px_1fr]">
          <span>항목</span><span className="hidden sm:block">기록 내용</span>
        </div>
        {COLUMNS.map(([name, description]) => (
          <div key={name} className="grid gap-1 border-t border-line px-4 py-3 first:border-t-0 sm:grid-cols-[180px_1fr] sm:gap-4">
            <span className="text-[13px] font-extrabold text-brand-ink">{name}</span>
            <span className="text-[13px] leading-6 text-ink3">{description}</span>
          </div>
        ))}
      </div>

      <button type="button" onClick={download} className="mt-7 min-h-[52px] w-full rounded-xl bg-brand px-6 py-3 text-[14px] font-black text-white transition hover:opacity-90 sm:w-auto">
        빈 고객 관리표 내려받기
      </button>
      {downloaded && <p role="status" className="mt-3 text-[13px] font-semibold text-success-ink">빈 고객 관리표를 내려받았어요.</p>}
    </section>
  );
}
