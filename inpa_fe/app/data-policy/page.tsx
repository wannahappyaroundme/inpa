// 데이터 처리 고지 (공개) — 회사 컴플라이언스 납득용 1장.
// 증권·병력 처리, Claude API 국외이전, 보관·동의·중개금지 원칙을 한 페이지로 설명.
// ★ 정직성 레드라인: 보증 표현 금지. 법적 효력은 정식 약관/개인정보처리방침이 정본.

export const metadata = {
  title: "데이터 처리 안내",
  description: "인파의 증권·민감정보 처리, 국외이전, 동의 원칙 안내",
};

const SECTIONS: { h: string; body: string }[] = [
  {
    h: "1. 인파는 보험을 중개·권유하지 않습니다",
    body: "인파는 보험설계사의 분석·정리 업무를 돕는 소프트웨어입니다. 보장의 충분/부족 판단과 상품 권유, 최종 책임은 담당 설계사에게 있으며, 인파의 산출물은 'AI 초안'으로 표기됩니다.",
  },
  {
    h: "2. 증권 정보 처리",
    body: "설계사가 업로드한 증권(PDF)의 텍스트를 추출해 담보를 표준 '틀'로 정규화합니다. 데이터는 해당 설계사 계정에만 귀속(소유자 전용)되며, 다른 설계사는 접근할 수 없습니다.",
  },
  {
    h: "3. 민감정보(병력)와 국외이전 동의",
    body: "병력 등 민감정보가 포함된 분석은 Claude API(미국, Anthropic)로 전송될 수 있어, 고객의 '국외이전 동의'가 있어야만 처리됩니다. 동의가 없으면 분석 호출 자체가 차단(412)됩니다. 동의 이력은 감사 로그로 보관합니다.",
  },
  {
    h: "4. 셀프진단(잠재고객 본인 진단)",
    body: "잠재고객이 본인 증권을 직접 올리는 셀프진단은 ①국외이전 ②담당 설계사 전달, 두 가지 동의를 모두 받은 뒤에만 진행됩니다. 병력은 수집하지 않으며, 결과는 보유 담보 '사실'만 중립적으로 표시합니다.",
  },
  {
    h: "5. 자동 발송 없음",
    body: "고객에게 자동으로 메시지를 보내지 않습니다. 안내 자료는 설계사가 복사하거나 카카오톡을 직접 여는 데까지만 지원합니다.",
  },
  {
    h: "6. 보관·파기",
    body: "고객 데이터는 설계사 계정에 귀속되며, 설계사 탈퇴 시 연쇄 삭제됩니다. 동의 철회 시 처리를 중단합니다. 구체적 보관기간·파기는 개인정보처리방침을 따릅니다.",
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
          법적 효력은 정식 이용약관·개인정보처리방침이 정본입니다.
        </p>

        <div className="mt-6 space-y-4">
          {SECTIONS.map((s) => (
            <section key={s.h} className="rounded-2xl border border-line bg-surface px-5 py-4">
              <h2 className="text-[15px] font-bold text-ink">{s.h}</h2>
              <p className="mt-1.5 text-[14px] leading-6 text-ink2">{s.body}</p>
            </section>
          ))}
        </div>

        <p className="mt-6 text-[12px] text-ink3 leading-5">
          문의: 고객센터 이메일(정식 출시 시 게재). 본 안내는 보장·심의 완료 등 어떠한 보증도 의미하지 않습니다.
        </p>
      </main>
    </div>
  );
}
