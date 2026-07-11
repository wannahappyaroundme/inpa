// JSON-LD 구조화 데이터 — 검색 리치결과 + AI 답변 엔진(ChatGPT·Gemini·Claude·Perplexity)이
// 인파를 '정확한 사실'로 인식하게 한다.
// ★ 정직성 레드라인: 조작된 평점(aggregateRating)·후기·수상 스키마 금지(없는 신뢰신호 날조 금지).
//   사실만 담는다(회사·서비스·무료 시작). 데이터는 전부 정적 상수(사용자 입력 없음).

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.inpa.kr";

const DESCRIPTION =
  "위촉직 보험설계사를 위한 AI 영업 파트너. 고객 발굴부터 보험 증권 분석, 보장 비교, 미팅 예약, 고객 관리까지 한 흐름으로 돕습니다.";

export const ORGANIZATION = {
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": `${SITE_URL}/#organization`,
  name: "인파(Inpa)",
  legalName: "(주)서울엘엔에스금융컨설팅",
  url: SITE_URL,
  logo: {
    "@type": "ImageObject",
    url: `${SITE_URL}/inpa-logo-120.png`,
    width: 120,
    height: 120,
  },
  email: "hello.fingo.official@gmail.com",
  description: DESCRIPTION,
  brand: { "@type": "Brand", name: "핀고(Fingo)" },
  address: {
    "@type": "PostalAddress",
    streetAddress: "서부샛길 606, A동 24층 2409호",
    addressLocality: "금천구",
    addressRegion: "서울특별시",
    addressCountry: "KR",
  },
};

export const WEBSITE = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  "@id": `${SITE_URL}/#website`,
  name: "인파(Inpa)",
  url: SITE_URL,
  inLanguage: "ko-KR",
  publisher: { "@id": `${SITE_URL}/#organization` },
};

export const SOFTWARE_APP = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "@id": `${SITE_URL}/#software`,
  name: "인파(Inpa)",
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  url: SITE_URL,
  inLanguage: "ko-KR",
  description:
    "보험설계사가 고객 발굴부터 증권 분석, 보장 비교, 미팅 예약, 고객 관리까지 한 동선으로 처리하는 AI 영업 파트너. 증권 PDF를 올리면 100여 개 담보 기준으로 자동 정리하고, 회사마다 다른 담보명을 하나로 맞춰 보여줍니다.",
  // 무료 시작만 표기(요금 구체 숫자는 stale 위험이라 스키마에 넣지 않는다).
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "KRW",
    description: "무료로 시작",
  },
  publisher: { "@id": `${SITE_URL}/#organization` },
};

// FAQPage 스키마 — /faq 의 질문/답변 배열에서 생성(화면 렌더와 동일 소스).
export function faqPage(items: { q: string; a: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map((it) => ({
      "@type": "Question",
      name: it.q,
      acceptedAnswer: { "@type": "Answer", text: it.a },
    })),
  };
}

// JSON-LD 스크립트 렌더. data 는 정적 상수(사용자 입력 아님) → dangerouslySetInnerHTML 안전.
// '<' 만 이스케이프해 스크립트 조기종료/HTML 파싱 사고를 막는다(표준 JSON-LD 관례).
export function JsonLd({ data }: { data: object | object[] }) {
  const json = JSON.stringify(data).replace(/</g, "\\u003c");
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: json }} />;
}
