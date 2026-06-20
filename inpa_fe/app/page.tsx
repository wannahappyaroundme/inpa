"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { tokenStore } from "@/lib/api";

// ─── Logo ────────────────────────────────────────────────────────────────────

function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 48 48"
      width={size}
      height={size}
      aria-label="인파"
      role="img"
    >
      <path
        d="M6 34 Q24 14 42 34"
        fill="none"
        stroke="#12B5A4"
        strokeWidth="6"
        strokeLinecap="round"
      />
      <path
        d="M12 33 Q24 3 36 33"
        fill="none"
        stroke="var(--brand)"
        strokeWidth="3.4"
        strokeLinecap="round"
      />
      <circle cx="24" cy="22" r="2.7" fill="var(--brand)" />
    </svg>
  );
}

// ─── Global Header ────────────────────────────────────────────────────────────

function LandingHeader() {
  return (
    <header
      className="sticky top-0 z-30 bg-[var(--surface)] border-b border-[var(--line)]"
      style={{ height: "var(--header-h)" }}
    >
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16 h-full flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <Logo size={30} />
          <span className="font-extrabold text-[var(--brand-ink)] text-[18px] tracking-tight">
            인파
          </span>
        </Link>
        <div className="flex items-center gap-2">
          <Link
            href="/login"
            className="px-4 py-2 rounded-xl border border-[var(--brand)] text-[var(--brand)] text-[14px] font-semibold min-h-[44px] flex items-center hover:bg-[var(--accent-tint)] transition"
          >
            로그인
          </Link>
          <Link
            href="/register"
            className="px-4 py-2 rounded-xl bg-[var(--brand)] text-white text-[14px] font-semibold min-h-[44px] flex items-center hover:opacity-90 transition"
          >
            무료로 시작하기
          </Link>
        </div>
      </div>
    </header>
  );
}

// ─── Section 1: Hero + CTA ────────────────────────────────────────────────────

function HeroSection() {
  return (
    <section className="bg-[var(--accent-tint)] py-16 md:py-24">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <div className="flex flex-col md:flex-row items-center gap-10 md:gap-16">
          {/* Left: Copy + CTA */}
          <div className="flex-1 text-center md:text-left">
            <h1 className="text-[28px] sm:text-[36px] md:text-[42px] font-extrabold text-[var(--brand-ink)] leading-tight tracking-tight">
              설계사님은<br />클로징만 준비하세요
            </h1>
            <p className="mt-4 text-[15px] sm:text-[17px] text-[var(--ink-2)] leading-relaxed max-w-lg mx-auto md:mx-0">
              발굴부터 보장분석, 갈아타기 제안까지 — 인파가 다 합니다.
              설계사님은 계약 마무리에만 집중하세요.
            </p>
            <p className="mt-2 text-[13px] sm:text-[14px] text-[var(--ink-3)] leading-relaxed max-w-md mx-auto md:mx-0">
              증권 업로드 하나로 고객 보장 공백을 3초 안에 시각화.
              합법적인 비교안내서까지 자동 생성.
            </p>
            <div className="mt-8 flex flex-col sm:flex-row gap-3 justify-center md:justify-start">
              <Link
                href="/register"
                className="w-full sm:w-auto px-6 py-3.5 rounded-xl bg-[var(--brand)] text-white font-bold text-[16px] min-h-[48px] flex items-center justify-center hover:opacity-90 transition"
              >
                무료로 시작하기
              </Link>
              <Link
                href="/login"
                className="w-full sm:w-auto px-6 py-3.5 rounded-xl border-2 border-[var(--brand)] text-[var(--brand)] font-bold text-[16px] min-h-[48px] flex items-center justify-center hover:bg-[var(--accent-tint)] transition"
              >
                로그인
              </Link>
            </div>
          </div>

          {/* Right: 제품 미리보기 (CSS 목업 — 실제 화면 모티프, 외부 이미지 의존 없음) */}
          <div className="flex-1 w-full max-w-md md:max-w-none">
            <div className="rounded-[var(--radius-lg)] bg-[var(--surface)] border border-[var(--line)] shadow-md overflow-hidden">
              {/* 윈도우 바 */}
              <div className="flex items-center gap-1.5 px-4 py-2.5 border-b border-[var(--line)] bg-[var(--surface-2)]">
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: "var(--cov-none)" }} />
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: "var(--cov-short)" }} />
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: "var(--cov-enough)" }} />
                <span className="ml-2 text-[11px] font-semibold text-[var(--ink-3)]">김영수님 · 보장 한눈표</span>
              </div>
              <div className="p-4">
                {/* 미니 히트맵 (24칸) */}
                <div className="grid grid-cols-6 gap-1.5">
                  {(["line","line","enough","line","short","line",
                     "line","enough","line","over","line","line",
                     "short","line","line","enough","line","none",
                     "line","line","enough","line","short","line"] as const).map((k, i) => (
                    <span
                      key={i}
                      className="aspect-square rounded-[4px]"
                      style={{ background: k === "line" ? "var(--line)" : `var(--cov-${k})` }}
                    />
                  ))}
                </div>
                {/* 갈아타기 판정 카드 */}
                <div className="mt-4 rounded-xl border border-[var(--line)] p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] font-bold text-[var(--ink)]">갈아타기 분석</span>
                    <span
                      className="text-[11px] font-bold rounded-full px-2 py-0.5"
                      style={{ color: "var(--cov-enough)", background: "var(--accent-tint)" }}
                    >
                      🟢 유지가 유리
                    </span>
                  </div>
                  <div className="mt-2.5 space-y-1.5 text-[12px]">
                    <div className="flex justify-between">
                      <span className="text-[var(--ink-3)]">해지 손실(추정)</span>
                      <span className="font-semibold text-[var(--ink)] tnum">-1,200,000원</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--ink-3)]">면책기간 리셋</span>
                      <span className="font-semibold text-[var(--cov-short)]">재적용 위험</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <p className="mt-2 text-center text-[11px] text-[var(--muted)]">실제 화면 미리보기</p>
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Section 2: Core Features ─────────────────────────────────────────────────

function FeaturesSection() {
  const cards = [
    {
      icon: "⊞",
      title: "보장 한눈표 (히트맵)",
      desc: "고객의 현재 보장을 100개 이상 담보 항목으로 한 화면에 펼쳐 보세요. 충분·부족·없음을 색으로 즉시 확인합니다.",
    },
    {
      icon: "◈",
      title: "히트맵 분석",
      desc: "보장 공백을 자동으로 계산해 우선순위별로 정렬합니다. 설계사님이 설정한 기준선으로 판단합니다.",
    },
    {
      icon: "⇄",
      title: "갈아타기 비교안내서",
      desc: "기존 보험과 새 제안을 나란히 비교하는 공식 비교안내서를 생성합니다. 부당승환 예방 항목이 자동으로 포함됩니다.",
    },
  ];

  return (
    <section className="py-16 md:py-24 bg-[var(--surface)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <h2 className="text-[22px] sm:text-[28px] font-extrabold text-[var(--brand-ink)] text-center mb-10">
          핵심 기능 3가지
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {cards.map((c) => (
            <div
              key={c.title}
              className="rounded-[var(--radius)] bg-[var(--surface-2)] border border-[var(--line)] shadow-sm p-6"
            >
              <div className="text-[28px] text-[var(--accent-blue)] mb-3">{c.icon}</div>
              <h3 className="font-bold text-[16px] text-[var(--ink)] mb-2">{c.title}</h3>
              <p className="text-[13px] text-[var(--ink-3)] leading-relaxed">{c.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── Section 3: Differentiators ───────────────────────────────────────────────

function DifferentiatorsSection() {
  return (
    <section className="py-16 md:py-24 bg-[var(--brand-ink)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <h2 className="text-[22px] sm:text-[28px] font-extrabold text-white text-center mb-10">
          인파만의 차별점
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Item A */}
          <div className="rounded-[var(--radius)] bg-white/10 border border-white/20 p-6">
            <span className="inline-block mb-3 px-3 py-1 rounded-full bg-[var(--accent-tint)] text-[var(--brand)] text-[12px] font-bold">
              §97 체크리스트 자동 완성 — 미달이면 발행 불가
            </span>
            <h3 className="font-bold text-[17px] text-white mb-2">
              부당승환 걱정 없는 비교안내
            </h3>
            <p className="text-[13px] text-white/70 leading-relaxed">
              보험업법 제97조가 요구하는 6가지 비교 항목(해지환급금 손실·면책기간·예정이율 등)을
              자동으로 체크하고 문서에 포함합니다.
              기준 미달 시 발행 자체를 차단해 설계사님을 법적 리스크에서 보호합니다.
            </p>
          </div>
          {/* Item B */}
          <div className="rounded-[var(--radius)] bg-white/10 border border-white/20 p-6">
            <span className="inline-block mb-3 px-3 py-1 rounded-full bg-[var(--accent-tint)] text-[var(--brand)] text-[12px] font-bold">
              담보 100+ 표준화 · 보험사별 명칭 자동 매핑
            </span>
            <h3 className="font-bold text-[17px] text-white mb-2">
              어떤 보험사 증권도 같은 틀로
            </h3>
            <p className="text-[13px] text-white/70 leading-relaxed">
              &apos;암진단급부금&apos;, &apos;일반암진단비&apos;, &apos;암진단 특약&apos; — 회사마다 다른 이름을
              100개 이상의 표준 담보로 자동 정규화합니다.
              OCR이 쌓일수록 매칭 정확도가 높아지는 학습 구조입니다.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Section 4: How It Works ─────────────────────────────────────────────────

function HowItWorksSection() {
  const steps = [
    {
      n: "1",
      icon: "↑",
      title: "증권 업로드",
      desc: "고객 보험 증권 PDF를 드래그하거나 카메라로 찍어 올리세요. 여러 장 한 번에 가능합니다.",
    },
    {
      n: "2",
      icon: "◎",
      title: "AI 자동 분석",
      desc: "인파가 담보를 분류하고 보장 공백을 계산합니다. 보통 10초 이내에 완료됩니다.",
    },
    {
      n: "3",
      icon: "⇪",
      title: "비교안내서 & 메시지 공유",
      desc: "고객에게 보낼 비교안내서와 카톡 메시지를 생성하고, 클립보드로 복사해 전달하세요.",
    },
  ];

  return (
    <section className="py-16 md:py-24 bg-[var(--surface-2)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <h2 className="text-[22px] sm:text-[28px] font-extrabold text-[var(--brand-ink)] text-center mb-10">
          어떻게 사용하나요?
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {steps.map((s, i) => (
            <div key={s.n} className="relative flex flex-col items-start gap-4">
              <div className="flex items-center gap-3">
                <span className="w-9 h-9 rounded-full bg-[var(--brand)] text-white font-bold text-[15px] flex items-center justify-center flex-shrink-0">
                  {s.n}
                </span>
                {/* connector arrow — desktop only, between steps */}
                {i < 2 && (
                  <span className="hidden md:block absolute left-full top-4 -ml-3 text-[var(--muted)] text-[18px]">
                    →
                  </span>
                )}
              </div>
              <div>
                <h3 className="font-bold text-[16px] text-[var(--ink)] mb-1">{s.title}</h3>
                <p className="text-[13px] text-[var(--ink-3)] leading-relaxed">{s.desc}</p>
              </div>
            </div>
          ))}
        </div>
        {/* 정직성 레드라인: 원탭 자동발송 없음 */}
        <p className="mt-8 text-center text-[12px] text-[var(--ink-3)]">
          자동 발송은 지원하지 않습니다. 메시지는 클립보드 복사 후 직접 전달해 주세요.
        </p>
      </div>
    </section>
  );
}

// ─── Section 5: Pricing (Freemium) ───────────────────────────────────────────

function PricingSection() {
  return (
    <section className="py-16 md:py-24 bg-[var(--surface)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <h2 className="text-[22px] sm:text-[28px] font-extrabold text-[var(--brand-ink)] text-center mb-3">
          요금제
        </h2>
        <p className="text-center text-[14px] text-[var(--ink-3)] mb-10">
          지금 가입하면 베타 기간 전 기능을 무료로 이용합니다.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-2xl mx-auto">
          {/* Free plan */}
          <div className="rounded-[var(--radius-lg)] bg-[var(--surface)] border border-[var(--line)] p-6 flex flex-col gap-3">
            <div className="text-[13px] font-semibold text-[var(--ink-3)] uppercase tracking-wide">무료 플랜</div>
            <div className="text-[32px] font-extrabold text-[var(--ink)]">0원</div>
            <ul className="flex flex-col gap-2 text-[13px] text-[var(--ink-2)]">
              <li className="flex gap-2"><span className="text-[var(--success)]">✓</span>증권 OCR 월 N건 (베타 확정)</li>
              <li className="flex gap-2"><span className="text-[var(--success)]">✓</span>비교안내서 월 1건 체험</li>
              <li className="flex gap-2"><span className="text-[var(--success)]">✓</span>보장 히트맵 조회 무제한</li>
              <li className="flex gap-2"><span className="text-[var(--muted)]">–</span>AI 분석·메시지 제한</li>
            </ul>
            <Link
              href="/register"
              className="mt-auto w-full py-3 rounded-xl bg-[var(--brand)] text-white font-bold text-[15px] text-center min-h-[48px] flex items-center justify-center hover:opacity-90 transition"
            >
              무료로 시작하기
            </Link>
          </div>

          {/* Plus plan */}
          <div className="rounded-[var(--radius-lg)] bg-[var(--surface)] border-2 border-[var(--brand)] p-6 flex flex-col gap-3 relative overflow-hidden">
            <span className="absolute top-0 left-0 right-0 h-1 bg-[var(--brand)]" />
            <div className="flex items-center gap-2">
              <div className="text-[13px] font-semibold text-[var(--brand)] uppercase tracking-wide">Plus 플랜</div>
              <span className="px-2 py-0.5 rounded-full bg-[var(--accent-tint)] text-[var(--brand)] text-[11px] font-bold">추천</span>
            </div>
            <div className="text-[22px] font-extrabold text-[var(--ink)]">추후 공개</div>
            <ul className="flex flex-col gap-2 text-[13px] text-[var(--ink-2)]">
              <li className="flex gap-2"><span className="text-[var(--success)]">✓</span>증권 OCR 더 많이</li>
              <li className="flex gap-2"><span className="text-[var(--success)]">✓</span>비교안내서 복수 발행</li>
              <li className="flex gap-2"><span className="text-[var(--success)]">✓</span>AI 분석·메시지 제한 완화</li>
              <li className="flex gap-2"><span className="text-[var(--success)]">✓</span>판촉물 주문 제한 완화</li>
            </ul>
            <button
              type="button"
              className="mt-auto w-full py-3 rounded-xl border-2 border-[var(--brand)] text-[var(--brand)] font-bold text-[15px] min-h-[48px] hover:bg-[var(--accent-tint)] transition"
            >
              베타 신청 / 문의하기
            </button>
          </div>
        </div>
        <p className="mt-6 text-center text-[12px] text-[var(--muted)]">
          베타 기간 한도는 실측 후 공개됩니다. 지금 가입하면 베타 기간 전 기능을 무료로 이용합니다.
        </p>
      </div>
    </section>
  );
}

// ─── Section 6: Trust / Honesty ──────────────────────────────────────────────

function TrustSection() {
  return (
    <section className="py-16 md:py-24 bg-[var(--accent-tint)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <h2 className="text-[22px] sm:text-[28px] font-extrabold text-[var(--brand-ink)] text-center mb-10">
          인파가 지키는 원칙
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Item 1 */}
          <div className="rounded-[var(--radius)] bg-[var(--surface)] border border-[var(--line)] p-6 flex gap-4">
            <div className="text-[var(--success)] text-[26px] flex-shrink-0">🛡</div>
            <div>
              <h3 className="font-bold text-[15px] text-[var(--ink)] mb-2">
                AI 초안, 최종책임은 설계사
              </h3>
              <p className="text-[13px] text-[var(--ink-3)] leading-relaxed">
                인파가 생성한 비교안내서·메시지는 AI 초안입니다.
                보장 판단과 최종 전달의 책임은 담당 설계사님에게 있습니다.
              </p>
            </div>
          </div>

          {/* Item 2 */}
          <div className="rounded-[var(--radius)] bg-[var(--surface)] border border-[var(--line)] p-6 flex gap-4">
            <div className="text-[var(--ink-2)] text-[26px] flex-shrink-0">⊘</div>
            <div>
              <h3 className="font-bold text-[15px] text-[var(--ink)] mb-2">
                &ldquo;심의완료&rdquo; &ldquo;안전&rdquo; 배지 없음
              </h3>
              <p className="text-[13px] text-[var(--ink-3)] leading-relaxed">
                인파는 특정 보험 상품이 심의를 완료했다거나 안전하다는 배지를 표시하지 않습니다.
                모든 보험 선택은 설계사님과 고객의 판단입니다.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Section 7: Footer ────────────────────────────────────────────────────────

function LandingFooter() {
  return (
    <footer className="bg-[var(--brand-ink)] text-[var(--surface)] py-12">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        {/* Top: Logo + Links */}
        <div className="flex flex-col md:flex-row gap-8 md:gap-0 md:justify-between">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <Logo size={24} />
              <span className="font-extrabold text-[17px]">인파 (Inpa)</span>
            </div>
            <p className="text-[12px] text-white/60 max-w-xs">
              보험설계사의 AI 영업 파트너. 발굴부터 보장분석, 갈아타기 제안까지.
            </p>
          </div>

          <div className="flex flex-col gap-2 text-[13px]">
            <Link href="/legal/terms" className="text-white/70 hover:text-white transition">
              이용약관
            </Link>
            <Link href="/legal/privacy" className="text-white/70 hover:text-white transition">
              개인정보처리방침
            </Link>
            <Link href="/inquiry/new" className="text-white/70 hover:text-white transition">
              1:1 문의
            </Link>
          </div>
        </div>

        {/* Business info placeholder */}
        <div className="mt-8 pt-6 border-t border-white/20 text-[12px] text-white/40 flex flex-col gap-1">
          <p>
            상호명: [미확정] | 사업자등록번호: [미확정] | 대표자: [미확정]
          </p>
          <p>
            주소: [미확정] | 이메일: [미확정]
          </p>
          <p className="mt-2">© 2026 Inpa. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const router = useRouter();

  // 로그인 상태이면 /home 으로 리다이렉트 (SSG 빌드에 영향 없음)
  useEffect(() => {
    if (tokenStore.get()) {
      router.replace("/home");
    }
  }, [router]);

  return (
    <>
      <LandingHeader />
      <main>
        <HeroSection />
        <FeaturesSection />
        <DifferentiatorsSection />
        <HowItWorksSection />
        <PricingSection />
        <TrustSection />
      </main>
      <LandingFooter />
    </>
  );
}
