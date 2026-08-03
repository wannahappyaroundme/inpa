"use client";

import { useState } from "react";

import { trackPublicResourceUse } from "@/lib/public-resource-events";

const SECTIONS = [
  {
    title: "상담 전 준비",
    items: [
      "고객 이름과 연락처를 확인했어요",
      "상담 목적과 고객이 궁금해하는 점을 적었어요",
      "약속 시간과 장소 또는 통화 방법을 확인했어요",
      "필요한 증권과 기존 상담 기록을 모았어요",
      "상담에서 확인할 질문을 순서대로 정했어요",
    ],
  },
  {
    title: "상담 중 확인",
    items: [
      "고객이 원하는 상담 목표를 다시 확인했어요",
      "현재 가입한 보험과 월 보험료를 확인했어요",
      "증권의 계약자, 피보험자와 기간을 확인했어요",
      "고객 설명과 증권 원문이 다른 부분을 표시했어요",
      "다음에 확인할 자료와 약속을 함께 정했어요",
    ],
  },
  {
    title: "상담 후 정리",
    items: [
      "상담 메모와 고객의 주요 질문을 남겼어요",
      "영업 단계와 진행 상태를 현재 상황에 맞췄어요",
      "추가로 받을 자료와 담당 행동을 적었어요",
      "다음 연락 날짜와 방법을 정했어요",
      "고객에게 전할 내용을 원문과 함께 다시 확인했어요",
    ],
  },
] as const;

const TOTAL_ITEMS = SECTIONS.reduce((total, section) => total + section.items.length, 0);

export function ConsultationChecklist() {
  const [checked, setChecked] = useState<Set<string>>(() => new Set());

  function toggle(key: string) {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function printChecklist() {
    trackPublicResourceUse("consultation_checklist", "print", "resource");
    window.print();
  }

  return (
    <section className="rounded-3xl border border-line bg-surface p-5 shadow-card print:border-0 print:p-0 print:shadow-none sm:p-8" aria-labelledby="consultation-checklist-title">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[12px] font-extrabold tracking-[0.14em] text-brand">상담 흐름 확인</p>
          <h2 id="consultation-checklist-title" className="mt-2 text-[26px] font-black text-brand-ink sm:text-[30px]">첫 상담 체크리스트</h2>
          <p className="mt-2 text-[13px] text-ink3">{checked.size}개 확인, 전체 {TOTAL_ITEMS}개</p>
        </div>
        <div className="flex gap-2 print:hidden">
          <button type="button" onClick={() => setChecked(new Set())} className="min-h-[44px] rounded-xl border border-line bg-white px-4 py-2 text-[13px] font-bold text-ink2 hover:border-brand hover:text-brand">
            전체 초기화
          </button>
          <button type="button" onClick={printChecklist} className="min-h-[44px] rounded-xl bg-brand px-4 py-2 text-[13px] font-black text-white hover:opacity-90">
            인쇄하기
          </button>
        </div>
      </div>

      <fieldset aria-label="첫 상담 체크 항목" className="mt-7 space-y-6">
        {SECTIONS.map((section, sectionIndex) => (
          <div key={section.title} className="break-inside-avoid rounded-2xl border border-line p-4 sm:p-5">
            <h3 className="text-[18px] font-black text-brand-ink">{section.title}</h3>
            <div className="mt-4 space-y-3">
              {section.items.map((item, itemIndex) => {
                const key = `${sectionIndex}-${itemIndex}`;
                return (
                  <label key={item} className="flex cursor-pointer items-start gap-3 rounded-xl py-1 text-[14px] leading-6 text-ink2">
                    <input
                      type="checkbox"
                      checked={checked.has(key)}
                      onChange={() => toggle(key)}
                      className="mt-1 h-5 w-5 shrink-0 accent-[var(--brand)]"
                    />
                    <span>{item}</span>
                  </label>
                );
              })}
            </div>
          </div>
        ))}
      </fieldset>
    </section>
  );
}
