"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ManagerSwitchConfirmModal } from "@/components/manager-switch-confirm-modal";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { attestOnboarding, getProfile, ApiError, type OnboardingAttestPayload } from "@/lib/api";

interface TourStep {
  emoji: string;
  title: string;
  desc: string;
  detail: string;
}

// 핵심 기능 투어: 고객 등록 → 증권 OCR → 보장분석 히트맵 → 갈아타기 → 공유
const STEPS: TourStep[] = [
  {
    emoji: "🧑‍🤝‍🧑",
    title: "1. 고객을 등록하세요",
    desc: "이름·생년월일만 있으면 시작이에요.",
    detail:
      "발굴한 잠재 고객도, 기존 고객도 한 곳에서 관리합니다. 태그·색상으로 분류하고 가족 구성까지 묶어 볼 수 있어요.",
  },
  {
    emoji: "📄",
    title: "2. 증권 PDF를 올리면 자동으로 읽어요",
    desc: "보험사·상품·담보를 자동으로 정리합니다.",
    detail:
      "여러 보험사 증권의 담보명을 표준 담보 '틀'로 정규화해, 회사가 달라도 같은 기준으로 비교할 수 있게 맞춰줍니다.",
  },
  {
    emoji: "🗺️",
    title: "3. 보장분석 히트맵으로 한눈에",
    desc: "담보별 보유 현황을 색으로 봅니다.",
    detail:
      "100개 이상 담보 '틀' 위에서 보유 금액을 표시합니다. 충분/부족 같은 판단과 권유는 설계사님 몫이에요. 인파는 사실만 정리합니다.",
  },
  {
    emoji: "🔁",
    title: "4. 비교 분석표를 자동으로",
    desc: "기존 vs 제안을 나란히 정리합니다.",
    detail:
      "보장을 비교 분석 자료로 정리해, 부당승환 리스크를 줄입니다.",
  },
  {
    emoji: "📤",
    title: "5. 고객에게 공유하세요",
    desc: "링크 또는 클립보드 복사로 전달합니다.",
    detail:
      "안내 자료를 복사하거나 카톡을 열어 고객에게 바로 전달할 수 있게 도와드려요. 마무리(클로징)는 설계사님이 준비하세요.",
  },
];

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center justify-center gap-2">
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`h-2 rounded-full transition-all ${
            i === current ? "w-6 bg-brand" : "w-2 bg-[var(--line-2)]"
          }`}
        />
      ))}
    </div>
  );
}

export default function OnboardingPage() {
  const ready = useAuthGuard();
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [phase, setPhase] = useState<"tour" | "setup">("tour");
  const [affiliationType, setAffiliationType] = useState<number | null>(null);
  const [managerEmail, setManagerEmail] = useState("");
  const [currentManagerEmail, setCurrentManagerEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingManagerSwitch, setPendingManagerSwitch] = useState<OnboardingAttestPayload | null>(null);

  useEffect(() => {
    if (!ready) return;
    let active = true;
    getProfile()
      .then((profile) => {
        if (!active) return;
        const currentEmail = profile.manager_email ?? "";
        setCurrentManagerEmail(currentEmail);
        setManagerEmail((value) => value || currentEmail);
      })
      .catch(() => { /* useAuthGuard 처리 */ });
    return () => {
      active = false;
    };
  }, [ready]);

  if (!ready) return null;

  const isLast = step === STEPS.length - 1;
  const current = STEPS[step];

  async function finish() {
    const payload: OnboardingAttestPayload = {
      affiliation_type: affiliationType,
      manager_email: managerEmail.trim() || undefined,
    };
    setError(null);
    setSaving(true);
    try {
      await attestOnboarding(payload);
      router.replace("/home");
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.status === 409 &&
        err.code === "team_switch_confirmation_required"
      ) {
        setPendingManagerSwitch(payload);
        setSaving(false);
        return;
      }
      const msg =
        err instanceof ApiError ? err.message : "저장 중 오류가 발생했습니다.";
      setError(msg || "저장 중 오류가 발생했습니다.");
      setSaving(false);
    }
  }

  async function confirmManagerSwitch() {
    if (!pendingManagerSwitch) return;
    setError(null);
    setSaving(true);
    try {
      await attestOnboarding({
        ...pendingManagerSwitch,
        confirm_manager_switch: true,
      });
      router.replace("/home");
    } catch (err) {
      setPendingManagerSwitch(null);
      setError(err instanceof ApiError ? err.message : "저장 중 오류가 발생했습니다.");
      setSaving(false);
    }
  }

  function cancelManagerSwitch() {
    setPendingManagerSwitch(null);
    setManagerEmail(currentManagerEmail);
    setError(null);
  }

  function next() {
    if (isLast) {
      setPhase("setup"); // 투어 끝 → 위촉 형태 설정
    } else {
      setStep((s) => Math.min(s + 1, STEPS.length - 1));
    }
  }

  return (
    <div className="min-h-dvh bg-[var(--surface-2)] flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        {/* 헤더 */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <svg viewBox="0 0 48 48" width="28" height="28" aria-hidden>
              <path d="M16.5 41 V15.5 H25 A7 7 0 0 1 25 29.5 H16.5" fill="none" stroke="#1E40C4" strokeWidth="7.6" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
            </svg>
            <span className="font-extrabold text-[18px] text-[var(--brand-ink)]">인파</span>
          </div>
          <button
            onClick={finish}
            disabled={saving}
            className="text-[13px] text-[var(--ink-3)] hover:text-[var(--brand)] transition disabled:opacity-50"
          >
            건너뛰기
          </button>
        </div>

        {/* 투어 카드 / 위촉 형태 설정 */}
        <div className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] shadow-card p-7">
          {phase === "tour" ? (
            <>
              <div className="text-[52px] leading-none mb-4">{current.emoji}</div>
              <h1 className="text-[22px] font-extrabold text-[var(--ink)] leading-tight">
                {current.title}
              </h1>
              <p className="mt-2 text-[15px] font-semibold text-[var(--brand)]">{current.desc}</p>
              <p className="mt-3 text-[14px] leading-6 text-[var(--ink-2)]">{current.detail}</p>
            </>
          ) : (
            <>
              <div className="text-[52px] leading-none mb-4">🪪</div>
              <h1 className="text-[22px] font-extrabold text-[var(--ink)] leading-tight">
                위촉 형태를 알려주세요
              </h1>
              <p className="mt-2 text-[14px] leading-6 text-[var(--ink-2)]">
                전속(원수사 소속)이면 타사 비교 분석 대신 <b>자사 보장공백</b> 중심으로 화면이 맞춰져요.
                나중에 설정에서 바꿀 수 있어요.
              </p>
              <div className="mt-5 grid grid-cols-2 gap-3">
                {[
                  { v: 2, label: "GA / 대리점", desc: "여러 보험사 비교 분석" },
                  { v: 1, label: "전속(원수사)", desc: "자사 상품 중심" },
                ].map((o) => (
                  <button
                    key={o.v}
                    onClick={() => setAffiliationType(o.v)}
                    className={`text-left rounded-xl border px-4 py-3 transition ${
                      affiliationType === o.v
                        ? "border-[var(--brand)] bg-[var(--accent-tint)]"
                        : "border-[var(--line)] hover:bg-[var(--surface-2)]"
                    }`}
                  >
                    <div className="text-[14px] font-bold text-[var(--ink)]">{o.label}</div>
                    <div className="text-[12px] text-[var(--ink-3)] mt-0.5">{o.desc}</div>
                  </button>
                ))}
              </div>
              <label className="mt-4 block">
                <span className="text-[13px] text-[var(--ink-3)]">관리직 이메일 (선택, KPI 공유 시)</span>
                <input
                  type="email"
                  value={managerEmail}
                  onChange={(e) => setManagerEmail(e.target.value)}
                  placeholder="manager@example.com"
                  className="mt-1 w-full rounded-xl border border-[var(--line)] px-3 py-2.5 text-[14px]"
                />
              </label>
            </>
          )}

          {error && (
            <div className="mt-4 p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger">
              {error}
            </div>
          )}

          {phase === "tour" && (
            <div className="mt-7">
              <StepDots current={step} total={STEPS.length} />
            </div>
          )}

          <div className="mt-6 flex items-center gap-3">
            {phase === "tour" && step > 0 && (
              <button
                onClick={() => setStep((s) => Math.max(s - 1, 0))}
                disabled={saving}
                className="flex-1 py-3 rounded-xl border border-[var(--line)] text-[14px] font-semibold text-[var(--ink-2)] min-h-[48px] hover:bg-[var(--surface-2)] transition disabled:opacity-50"
              >
                이전
              </button>
            )}
            {phase === "setup" && (
              <button
                onClick={() => setPhase("tour")}
                disabled={saving}
                className="flex-1 py-3 rounded-xl border border-[var(--line)] text-[14px] font-semibold text-[var(--ink-2)] min-h-[48px] hover:bg-[var(--surface-2)] transition disabled:opacity-50"
              >
                이전
              </button>
            )}
            <button
              onClick={phase === "tour" ? next : finish}
              disabled={saving}
              className="flex-[2] py-3 rounded-xl bg-[var(--brand)] text-white font-bold text-[15px] min-h-[48px] hover:opacity-90 transition disabled:opacity-60 flex items-center justify-center gap-2"
            >
              {saving ? (
                <>
                  <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  시작하는 중...
                </>
              ) : phase === "setup" ? (
                "인파 시작하기"
              ) : (
                "다음"
              )}
            </button>
          </div>
        </div>

        {/* 면책 (정직성 레드라인) */}
        <p className="mt-5 px-1 text-[12px] leading-5 text-[var(--muted)]">
          인파는 보험을 중개·권유하지 않는 분석·정리 소프트웨어입니다. 보장 판단과 고객 안내는
          설계사님의 업무이며, 산출물은 <b className="text-[var(--ink-3)]">AI가 정리한 참고 자료</b>입니다.
        </p>
      </div>
      <ManagerSwitchConfirmModal
        open={pendingManagerSwitch !== null}
        email={pendingManagerSwitch?.manager_email ?? ""}
        saving={saving}
        onConfirm={confirmManagerSwitch}
        onCancel={cancelManagerSwitch}
      />
    </div>
  );
}
