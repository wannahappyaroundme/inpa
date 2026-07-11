import type { Metadata } from "next";
import {
  LandingHeader, HeroSection, TrustBar, FeaturesSection, FeatureShowcaseSection,
  DifferentiatorsSection, AudienceSection, HowItWorksSection, PricingSection,
  TrustSection, FinalCTASection, LandingFooter,
} from "@/components/landing-sections";
import { LandingClient } from "@/components/landing-client";
import { JsonLd, ORGANIZATION, WEBSITE, SOFTWARE_APP } from "@/components/structured-data";

// 인파 랜딩 — 섹션 본체는 components/landing-sections.tsx (new.inpa.kr 랜딩과 공용).
// 서버 컴포넌트: 자기참조 canonical(UTM 파라미터 URL 통합) + JSON-LD 를 서버에서 주입한다.
// 클라이언트 부수효과(로그인 리다이렉트·UTM 캡처)는 <LandingClient/> 로 분리(렌더 결과 불변).
export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

export default function LandingPage() {
  return (
    <>
      <JsonLd data={[ORGANIZATION, WEBSITE, SOFTWARE_APP]} />
      <LandingClient />
      <LandingHeader />
      <main>
        <HeroSection />
        <TrustBar />
        <FeaturesSection />
        <FeatureShowcaseSection />
        <DifferentiatorsSection />
        <AudienceSection />
        <HowItWorksSection />
        <PricingSection />
        <TrustSection />
        <FinalCTASection />
      </main>
      <LandingFooter />
    </>
  );
}
