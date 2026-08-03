// 데이터 처리 고지 (공개) — 회사 컴플라이언스 납득용 1장.
// 증권·병력 처리, Claude API 국외이전, 보관·동의·중개금지 원칙을 한 페이지로 설명.
// ★ 정직성 레드라인: 보증 표현 금지. 법적 효력은 정식 약관/개인정보처리방침이 정본.

import type { Metadata } from "next";
import { PUBLIC_INDEX_ROBOTS } from "@/lib/search-policy";

export const metadata: Metadata = {
  title: "데이터 처리 안내",
  description: "인파의 증권·민감정보 처리, 국외이전, 동의 원칙 안내",
  alternates: { canonical: "/data-policy" },
  robots: PUBLIC_INDEX_ROBOTS,
};

const SECTIONS: { h: string; body: string }[] = [
  {
    h: "1. 인파는 보험을 중개·권유하지 않습니다",
    body: "인파는 보험을 중개·권유하지 않는 분석·정리 소프트웨어입니다. 보장 판단과 고객 안내는 설계사님의 업무이며, 산출물은 AI가 정리한 참고 자료입니다.",
  },
  {
    h: "2. 현재 이용할 수 있는 증권 정보",
    body: "현재 서비스에서는 설계사가 직접 입력한 증권 정보로 보장 내용을 정리하고 여러 증권을 나란히 볼 수 있습니다. 증권 원문과 자동 정리 결과를 함께 확인하는 검토형 증권 정리는 운영 확인을 마친 범위에서만 열리며, 기본 설정은 닫혀 있습니다.",
  },
  {
    h: "3. 고객 동의와 외부 AI 처리",
    body: "검토형 증권 정리 흐름이 열린 경우에는 먼저 고객 동의를 확인합니다. 이름·연락처·주민등록번호 같은 신원 정보는 외부 AI로 보내기 전에 가리고, 담보와 금액 등 정리에 필요한 내용은 Anthropic의 Claude 등 외부 AI 서비스로 전송될 수 있습니다. 동의 내용과 처리 시점은 기록으로 남깁니다.",
  },
  {
    h: "4. 계정별 접근",
    body: "설계사가 등록한 고객과 증권 정보는 해당 설계사 계정에서만 확인할 수 있습니다. 다른 설계사 계정과 섞이지 않도록 분리해 관리합니다.",
  },
  {
    h: "5. 고객 전달은 설계사가 직접",
    body: "인파는 고객에게 직접 메시지를 보내지 않습니다. 안내 자료는 설계사가 복사해 전달하며, 고객 연락 채널과 동의를 설계사가 직접 관리하도록 한 설계입니다.",
  },
  {
    h: "6. 원본 파일 정리",
    body: "검토형 증권 정리에서 받은 원본 파일은 증권 정리 결과를 확정하거나 작업을 취소하면 정리합니다. 정리 과정이 바로 끝나지 않으면 정기 작업에서 다시 확인합니다.",
  },
  {
    h: "7. 탈퇴와 데이터 삭제",
    body: "설계사가 탈퇴하면 계정에 연결된 고객·분석·일정 정보는 개인정보처리방침에 따라 삭제합니다. 보관 기준과 삭제 방법도 개인정보처리방침에서 확인할 수 있습니다.",
  },
];

export default function DataPolicyPage() {
  return (
    <div className="min-h-dvh bg-surface2">
      <main className="mx-auto max-w-2xl px-5 py-10">
        <div className="flex items-center gap-1.5 text-[14px] font-bold text-brand">
          <span className="text-[16px]">⌃</span> 인파(Inpa)
        </div>
        <h1 className="mt-4 text-[24px] font-extrabold text-ink leading-tight">
          데이터 처리 안내
        </h1>
        <p className="mt-2 text-[13px] text-ink3 leading-6">
          설계사·소속 회사가 인파의 데이터 처리 방식을 한눈에 확인할 수 있도록 정리한 안내입니다.
          세부 기준은 이용약관과 개인정보처리방침에서 확인할 수 있습니다.
        </p>

        <div className="mt-6 space-y-4">
          {SECTIONS.map((s) => (
            <section key={s.h} className="rounded-2xl border border-line bg-surface px-5 py-4">
              <h2 className="text-[15px] font-bold text-ink">{s.h}</h2>
              <p className="mt-1.5 text-[14px] leading-6 text-ink2">{s.body}</p>
            </section>
          ))}
        </div>

        <div className="mt-6 space-y-1 text-[12px] text-ink3 leading-5">
          <p>
            탈퇴는 로그인 후 <a href="/settings/account" className="font-semibold text-brand hover:underline">계정 설정</a>에서 진행할 수 있습니다.
          </p>
          <p>
            데이터 처리·삭제 문의: <a href="mailto:hello.fingo.official@gmail.com" className="font-semibold text-brand hover:underline">hello.fingo.official@gmail.com</a>
          </p>
          <p>
            <a href="/legal/terms" className="hover:underline">이용약관</a>
            <span aria-hidden="true"> · </span>
            <a href="/legal/privacy" className="hover:underline">개인정보처리방침</a>
          </p>
        </div>
      </main>
    </div>
  );
}
