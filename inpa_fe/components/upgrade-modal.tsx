"use client";

// ════════════════════════════════════════════════════════════════════════════
// 한도 초과 소프트 안내 모달 — 402 credit_exhausted 수신 시 공통 사용
//
// 정직성 레드라인:
//   - 결제 강요 없음. 전환 경로는 쿠폰 등록·계좌이체(수동 데스크)·1:1 문의 안내.
//   - 카피 철학(PM 2026-07-03, CLAUDE.md §6): 소진→활용(위치감), 적합성 프레임("딱 맞아요").
//   - VAT 표시 규칙(PM 2026-07-07): 요금제 소개 줄은 VAT 별도 금액만.
//     최종(부가세 포함) 금액은 아래 결제(입금) 단계의 금액 분해에서만 표시.
// 결제는 수동 데스크: 입금 → 1:1 문의 → 관리자 요금제 적용(자동화 없음, KICC PG는 후속).
// 테마: 서비스 페이지 = 라이트 고정. dark: 변형 추가 금지.
// ════════════════════════════════════════════════════════════════════════════

import Link from "next/link";
import { useState } from "react";

/** BE 402 credit_exhausted 추가 필드 (api.ts CreditExhaustedBody 와 동형) */
export interface UpgradeModalInfo {
  kind?: string;
  limit?: number | null;
  used?: number;
}

interface UpgradeModalProps {
  open: boolean;
  onClose: () => void;
  info?: UpgradeModalInfo;
  /**
   * 표시 맥락. 기본(미지정)="credit_exhausted"=한도 초과 안내.
   * "manager_required"=팀 기능은 Manager 요금제 전용(자격 게이트, 한도 초과 아님) — 헤드라인·
   * 요금제 안내·요금제 토글이 Manager 하나로 바뀐다. (spec 2026-07-09 manager-plan-gate)
   */
  reason?: "credit_exhausted" | "manager_required";
}

/** kind → 사용자용 한국어 기능 라벨 */
function kindLabel(kind: string | undefined): string {
  switch (kind) {
    case "ocr":
      return "증권 분석(OCR)";
    case "analysis":
      return "보장 분석";
    case "ai_compare":
      return "AI 비교안내서";
    case "promotion":
      return "판촉물 주문";
    case "customer":
      return "고객 추가";
    default:
      return "이 기능";
  }
}

/** kind → 본문 문장에 넣을 짧은 표현 */
function kindShort(kind: string | undefined): string {
  switch (kind) {
    case "ocr":
      return "OCR(증권 분석)";
    case "analysis":
      return "보장 분석";
    case "ai_compare":
      return "AI 비교안내서";
    case "promotion":
      return "판촉물 주문";
    case "customer":
      return "고객 추가";
    default:
      return "이 기능";
  }
}

// 확정 가격(2026-07-07). base = VAT 별도 월 이용료, vat = 10%, total = 최종 입금액.
// manager(2026-07-09 팀 기능 게이트) = Plus와 동일가, 팀 관리 capability 전용.
const PLAN_PRICING = {
  plus: { name: "플러스", base: "19,900원", vat: "1,990원", total: "21,890원" },
  manager: { name: "Manager", base: "19,900원", vat: "1,990원", total: "21,890원" },
  super: { name: "슈퍼", base: "39,900원", vat: "3,990원", total: "43,890원" },
} as const;

const BANK_ACCOUNT_NUMBER = "459001-04-503030";
const BANK_ACCOUNT_DISPLAY = "국민은행 459001-04-503030 (예금주: 핀고)";

export function UpgradeModal({ open, onClose, info, reason = "credit_exhausted" }: UpgradeModalProps) {
  const isManagerGate = reason === "manager_required";
  const [payPlan, setPayPlan] = useState<keyof typeof PLAN_PRICING>(
    isManagerGate ? "manager" : "plus"
  );
  const [copied, setCopied] = useState(false);

  if (!open) return null;

  const hasNumbers =
    !isManagerGate &&
    typeof info?.used === "number" && typeof info?.limit === "number" && info.limit !== null;

  const visiblePlanCodes: (keyof typeof PLAN_PRICING)[] = isManagerGate
    ? ["manager"]
    : ["plus", "super"];

  const pricing = PLAN_PRICING[payPlan];

  async function copyAccount() {
    try {
      await navigator.clipboard.writeText(BANK_ACCOUNT_NUMBER);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 클립보드 권한이 없으면 계좌가 화면에 그대로 보이므로 조용히 넘어간다.
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="upgrade-modal-title"
      onClick={(e) => {
        // 배경 클릭 시 닫기
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full sm:max-w-md max-h-[90dvh] overflow-y-auto bg-surface rounded-t-3xl sm:rounded-2xl px-6 pt-6 pb-8 shadow-xl">
        {/* 헤더 */}
        <div className="flex items-start justify-between gap-3">
          <h2
            id="upgrade-modal-title"
            className="text-[18px] font-extrabold text-ink leading-snug"
          >
            {isManagerGate
              ? "Manager 요금제에서 팀을 관리할 수 있어요"
              : `이번 달 ${kindLabel(info?.kind)} 한도를 다 쓰셨어요`}
          </h2>
          <button
            onClick={onClose}
            className="shrink-0 mt-0.5 text-[20px] leading-none text-ink3 hover:text-ink transition"
            aria-label="닫기"
          >
            ×
          </button>
        </div>

        {/* 사용량 뱃지 */}
        {hasNumbers && (
          <div className="mt-3 inline-flex items-center gap-1.5 rounded-xl border border-line bg-surface2 px-3 py-1.5">
            <span className="text-[13px] text-ink3">이번 달 사용</span>
            <span className="text-[14px] font-bold text-ink">
              {info!.used} / {info!.limit}회
            </span>
          </div>
        )}

        {/* 본문 */}
        {isManagerGate ? (
          <p className="mt-4 text-[14px] text-ink2 leading-6">
            팀원 인사 관리, 팀원 개별 실적 관리, 팀 전체 실적 관리를 한 화면에서 확인할 수
            있어요.
            <br />
            팀을 이끄는 설계사님에게는 Manager 요금제가 딱 맞아요.
          </p>
        ) : (
          <p className="mt-4 text-[14px] text-ink2 leading-6">
            무료 요금제의 이번 달{" "}
            <b className="font-semibold text-ink">{kindShort(info?.kind)}</b> 한도를 모두
            활용하셨어요.
            <br />
            이만큼 쓰시는 설계사님에게는 플러스 요금제가 딱 맞아요.
          </p>
        )}

        {/* 요금제 소개 — 표시 규칙: VAT 별도 금액만 */}
        <div className="mt-4 rounded-xl border border-line bg-surface2 px-4 py-3">
          <p className="text-[13px] font-bold text-ink">요금제 안내</p>
          <ul className="mt-1.5 space-y-1 text-[13px] text-ink2 leading-5">
            {isManagerGate ? (
              <>
                <li>Manager 월 19,900원 (VAT 별도) · 팀장·지점장·지사장 등 관리자 전용</li>
                <li>Plus 전체 기능 · 팀원 인사·개별 실적·전체 실적 관리</li>
              </>
            ) : (
              <>
                <li>플러스 월 19,900원 (VAT 별도)</li>
                <li>슈퍼 월 39,900원 (VAT 별도) · 한도 무제한</li>
              </>
            )}
          </ul>
        </div>

        {/* 결제(입금) 단계 — 최종 금액은 여기에서만, VAT 분해로 표시 */}
        <div className="mt-3 rounded-xl border border-line px-4 py-3">
          <p className="text-[13px] font-bold text-ink">계좌이체로 시작하기</p>

          {/* 요금제 선택 토글 — manager_required는 Manager 하나뿐이라 토글 없이 이름만 표시 */}
          {visiblePlanCodes.length > 1 ? (
            <div className="mt-2 grid grid-cols-2 gap-1.5" role="group" aria-label="요금제 선택">
              {visiblePlanCodes.map((code) => (
                <button
                  key={code}
                  type="button"
                  onClick={() => setPayPlan(code)}
                  aria-pressed={payPlan === code}
                  className={`rounded-lg border px-3 py-2 text-[13px] font-semibold transition ${
                    payPlan === code
                      ? "border-brand text-brand bg-brand-soft"
                      : "border-line text-ink3 hover:text-ink"
                  }`}
                >
                  {PLAN_PRICING[code].name}
                </button>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-[13px] font-semibold text-brand">
              {PLAN_PRICING[payPlan].name} 요금제
            </p>
          )}

          {/* 금액 분해 */}
          <dl className="mt-3 space-y-1 text-[13px]">
            <div className="flex items-center justify-between">
              <dt className="text-ink3">월 이용료</dt>
              <dd className="font-semibold text-ink">{pricing.base}</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-ink3">VAT(10%)</dt>
              <dd className="font-semibold text-ink">{pricing.vat}</dd>
            </div>
            <div className="flex items-center justify-between border-t border-line pt-1.5 mt-1.5">
              <dt className="font-bold text-ink">최종 입금액</dt>
              <dd className="text-[14px] font-extrabold text-brand">{pricing.total}</dd>
            </div>
          </dl>

          {/* 입금 계좌 + 복사 */}
          <div className="mt-3 flex items-center justify-between gap-2 rounded-lg bg-surface2 px-3 py-2.5">
            <span className="text-[13px] font-semibold text-ink">{BANK_ACCOUNT_DISPLAY}</span>
            <button
              type="button"
              onClick={copyAccount}
              className="shrink-0 rounded-lg border border-line bg-surface px-2.5 py-1 text-[12px] font-semibold text-ink2 transition hover:bg-surface2"
            >
              {copied ? "복사됨" : "복사"}
            </button>
          </div>

          {/* 절차 3단계 */}
          <ol className="mt-3 list-decimal pl-5 space-y-1 text-[12px] text-ink3 leading-5">
            <li>위 계좌로 최종 입금액을 입금해 주세요.</li>
            <li>1:1 문의에 입금자명과 원하는 요금제를 남겨 주세요.</li>
            <li>확인 후 요금제를 적용해 드려요. 세금계산서 발행이 필요하면 사업자 정보를 함께 남겨 주세요.</li>
          </ol>
        </div>

        {/* 안내 텍스트 */}
        <p className="mt-3 text-[12px] text-ink3 leading-5">
          {isManagerGate
            ? "쿠폰이 있다면 설정 > 계정에서 등록해 바로 이어갈 수 있어요."
            : "한도는 매월 1일 초기화돼요. 쿠폰이 있다면 설정 > 계정에서 등록해 바로 이어갈 수 있어요."}
        </p>

        {/* 버튼 영역 */}
        <div className="mt-6 flex flex-col gap-2.5">
          <button
            onClick={onClose}
            className="w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 transition hover:opacity-90 active:scale-[0.98]"
          >
            확인
          </button>
          <Link
            href="/boards"
            onClick={onClose}
            className="w-full rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 py-3 text-center transition hover:bg-surface2"
          >
            1:1 문의하기
          </Link>
        </div>
      </div>
    </div>
  );
}
