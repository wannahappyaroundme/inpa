import type { Metadata } from "next";
import Link from "next/link";
import { InpaMark } from "@/components/inpa-logo";
import { JsonLd, faqPage } from "@/components/structured-data";

// 공개 FAQ — 검색·AI 답변 엔진이 가장 잘 인용하는 형식. 라이트 고정(서비스 페이지 테마 가드).
// ★ 데이터 단일 소스 FAQ_ITEMS → 화면 렌더 + FAQPage JSON-LD 동시 생성(불일치 방지).
// ★ 정직성·§6: 쉬운 말, 과장·배지 없음, em-dash 없음. '인파는 중개 안 함' 레드라인 포함.
const OG_TITLE = "자주 묻는 질문 · 인파(Inpa)";
const OG_DESC =
  "인파(Inpa) 자주 묻는 질문. 보험설계사를 위한 AI 영업 파트너가 증권 분석·보장 비교·요금·개인정보를 어떻게 다루는지 정리했습니다.";

export const metadata: Metadata = {
  title: "자주 묻는 질문",
  description: OG_DESC,
  alternates: { canonical: "/faq" },
  // ★ 페이지별 openGraph 정의 시 루트의 파일 컨벤션 이미지가 상속되지 않으므로(§7 트랩)
  //   전역 OG 이미지를 명시 참조한다. 절대 URL 은 metadataBase 기준.
  openGraph: {
    type: "website",
    locale: "ko_KR",
    siteName: "인파(Inpa)",
    title: OG_TITLE,
    description: OG_DESC,
    url: "/faq",
    images: [{ url: "/opengraph-image.jpg", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: OG_TITLE,
    description: OG_DESC,
    images: ["/opengraph-image.jpg"],
  },
};

const FAQ_ITEMS: { q: string; a: string }[] = [
  {
    q: "인파(Inpa)는 어떤 서비스인가요?",
    a: "인파는 위촉직 보험설계사를 위한 AI 영업 파트너입니다. 새 고객 발굴부터 보험 증권 분석, 보장 비교, 미팅 예약, 고객 관리까지 흩어져 있던 영업 과정을 한 흐름으로 이어 줍니다.",
  },
  {
    q: "누구에게 맞나요?",
    a: "원수사나 GA 소속으로 개인사업자처럼 일하는 보험설계사님께 맞습니다. 특히 고객 발굴이 절실한 새내기 설계사님과, 팀 성과를 한눈에 보고 싶은 관리직에게 도움이 됩니다.",
  },
  {
    q: "보험 증권은 어떻게 분석하나요?",
    a: "증권 PDF를 올리면 AI가 보장 내용을 자동으로 읽어 100여 개 담보 기준으로 정리합니다. 회사마다 다른 담보 이름을 하나로 맞춰 주기 때문에, 여러 보험도 한눈에 비교할 수 있습니다.",
  },
  {
    q: "인파가 보험을 중개하거나 권유하나요?",
    a: "아니요. 인파는 보장 정보를 분석하고 정리하는 소프트웨어입니다. 보장 판단과 고객 안내는 설계사님의 업무이며, 산출물은 AI가 정리한 참고 자료입니다.",
  },
  {
    q: "여러 증권 비교는 어떻게 도와주나요?",
    a: "비교할 증권을 A와 B로 고르면 담보, 보장금액, 보험료를 같은 기준의 표와 그래프로 보여 줍니다. 인파는 어느 증권이 더 낫다고 판단하지 않고 등록된 정보를 정리합니다.",
  },
  {
    q: "요금은 어떻게 되나요?",
    a: "지금은 모든 기능을 무료로 쓸 수 있습니다. 앞으로 많이 사용하는 분을 위한 유료 요금제가 생기며, 자세한 요금은 홈페이지 요금제 안내에서 확인할 수 있어요.",
  },
  {
    q: "고객 개인정보는 어떻게 관리되나요?",
    a: "고객 동의를 받아 처리하고, 꼭 필요한 정보만 최소한으로 다룹니다. 자세한 내용은 개인정보처리방침에서 확인할 수 있습니다.",
  },
  {
    q: "내 고객 정보를 다른 설계사가 볼 수 있나요?",
    a: "아니요. 설계사님이 등록한 고객 정보는 설계사님 본인만 볼 수 있고, 다른 설계사에게 공유되지 않습니다.",
  },
  {
    q: "모바일에서도 쓸 수 있나요?",
    a: "네. 휴대폰 웹 브라우저에서 바로 쓸 수 있고, 홈 화면에 앱처럼 추가해서 쓸 수도 있습니다.",
  },
  {
    q: "어떻게 시작하나요?",
    a: "이메일이나 구글 계정으로 가입하면 바로 시작할 수 있습니다. 증권 한 장이면 첫 분석을 해볼 수 있어요.",
  },
];

export default function FaqPage() {
  return (
    <div className="min-h-screen bg-[var(--surface)] text-[var(--ink)]">
      <JsonLd data={faqPage(FAQ_ITEMS)} />

      {/* 헤더 */}
      <header className="border-b border-[var(--line)] bg-[var(--surface-2)]">
        <div className="mx-auto max-w-3xl px-4 sm:px-6 py-4 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2" aria-label="인파 홈으로">
            <InpaMark size={28} />
            <span className="font-extrabold text-[16px] text-[var(--brand-ink)]">인파 (Inpa)</span>
          </Link>
          <Link
            href="/register"
            className="px-4 py-2 rounded-xl bg-[var(--brand)] text-white text-[14px] font-semibold min-h-[44px] flex items-center hover:opacity-90 transition"
          >
            무료로 시작하기
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 sm:px-6 py-12 sm:py-16">
        <h1 className="text-[30px] sm:text-[40px] font-extrabold text-[var(--brand-ink)] tracking-tight">
          자주 묻는 질문
        </h1>
        <p className="mt-3 text-[15px] sm:text-[16px] text-[var(--ink-3)] leading-relaxed">
          인파가 무엇을 어떻게 돕는지, 자주 받는 질문을 모았습니다. 더 궁금한 점은 아래 이메일로 문의해 주세요.
        </p>

        <div className="mt-10 divide-y divide-[var(--line)] border-y border-[var(--line)]">
          {FAQ_ITEMS.map((it) => (
            <section key={it.q} className="py-6">
              <h2 className="text-[17px] sm:text-[19px] font-bold text-[var(--brand-ink)] leading-snug">
                {it.q}
              </h2>
              <p className="mt-2.5 text-[14px] sm:text-[15px] text-[var(--ink-2)] leading-7">
                {it.a}
              </p>
            </section>
          ))}
        </div>

        {/* 관련 링크 + CTA */}
        <div className="mt-12 rounded-2xl border border-[var(--line)] bg-[var(--surface-2)] p-6 sm:p-8 text-center">
          <p className="text-[16px] font-bold text-[var(--brand-ink)]">증권 한 장이면 시작입니다.</p>
          <p className="mt-1.5 text-[14px] text-[var(--ink-3)]">지금은 모든 기능을 무료로 써볼 수 있어요.</p>
          <Link
            href="/register"
            className="mt-5 inline-flex px-7 py-3.5 rounded-2xl bg-[var(--brand)] text-white font-bold text-[15px] min-h-[50px] items-center justify-center hover:opacity-90 transition"
          >
            무료로 시작하기
          </Link>
        </div>

        <nav className="mt-8 flex flex-wrap justify-center gap-x-5 gap-y-2 text-[13px] text-[var(--ink-3)]">
          <Link href="/" className="hover:text-[var(--ink)] transition">홈</Link>
          <Link href="/legal/terms" className="hover:text-[var(--ink)] transition">이용약관</Link>
          <Link href="/legal/privacy" className="hover:text-[var(--ink)] transition">개인정보처리방침</Link>
          <Link href="/data-policy" className="hover:text-[var(--ink)] transition">데이터 처리 안내</Link>
          <a href="mailto:hello.fingo.official@gmail.com" className="hover:text-[var(--ink)] transition">문의</a>
        </nav>
      </main>
    </div>
  );
}
