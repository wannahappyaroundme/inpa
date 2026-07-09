"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { tokenStore } from "@/lib/api";
import { useUtmCapture } from "@/lib/useUtmCapture";
import {
  LandingHeader, HeroSection, TrustBar, FeaturesSection, FeatureShowcaseSection,
  DifferentiatorsSection, AudienceSection, HowItWorksSection, PricingSection,
  TrustSection, FinalCTASection, LandingFooter,
} from "@/components/landing-sections";

// 인파 랜딩 — 섹션 본체는 components/landing-sections.tsx (new.inpa.kr 랜딩과 공용).
export default function LandingPage() {
  const router = useRouter();
  useUtmCapture(); // 유입 첫터치 캡처(#16) — 화면 변화 없음
  useEffect(() => { if (tokenStore.get()) router.replace("/home"); }, [router]);
  return (
    <>
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
