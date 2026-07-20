import type { Metadata } from "next";
import { ServiceLanding } from "@/components/service-landing";
import { LandingClient } from "@/components/landing-client";
import { FeedbackWidget } from "@/components/feedback-widget";
import { JsonLd, ORGANIZATION, WEBSITE, SOFTWARE_APP } from "@/components/structured-data";

// 서비스 소개 메인. 서버에서 canonical·JSON-LD를 주입하고,
// 로그인 리다이렉트·UTM 캡처는 <LandingClient/>가 맡는다.
export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

export default function LandingPage() {
  return (
    <>
      <JsonLd data={[ORGANIZATION, WEBSITE, SOFTWARE_APP]} />
      <LandingClient />
      <ServiceLanding />
      {/* 의견 위젯 — 랜딩(비로그인) 익명 모드 */}
      <FeedbackWidget anonymous />
    </>
  );
}
