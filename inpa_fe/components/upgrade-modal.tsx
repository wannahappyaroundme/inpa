"use client";

// ════════════════════════════════════════════════════════════════════════════
// 한도 초과 소프트 안내 모달 — 402 credit_exhausted 수신 시 공통 사용
//
// 정직성 레드라인:
//   - 결제 강요 없음 (베타, 요금제 미확정). "정식 출시 후" 표현만 사용.
//   - 단정적 약속 없이 "더 많이 이용할 수 있을 예정" 수준 표기.
// 테마: 서비스 페이지 = 라이트 고정. dark: 변형 추가 금지.
// ════════════════════════════════════════════════════════════════════════════

import Link from "next/link";

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
    default:
      return "이 기능";
  }
}

export function UpgradeModal({ open, onClose, info }: UpgradeModalProps) {
  if (!open) return null;

  const hasNumbers =
    typeof info?.used === "number" && typeof info?.limit === "number" && info.limit !== null;

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
      <div className="w-full sm:max-w-md bg-surface rounded-t-3xl sm:rounded-2xl px-6 pt-6 pb-8 shadow-xl">
        {/* 헤더 */}
        <div className="flex items-start justify-between gap-3">
          <h2
            id="upgrade-modal-title"
            className="text-[18px] font-extrabold text-ink leading-snug"
          >
            이번 달 {kindLabel(info?.kind)} 한도를 다 쓰셨어요
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
        <p className="mt-4 text-[14px] text-ink2 leading-6">
          무료 요금제의 이번 달{" "}
          <b className="font-semibold text-ink">{kindShort(info?.kind)}</b> 한도를 모두
          소진했어요.
          <br />
          정식 출시 후에는 플러스 요금제를 통해 더 많이 이용할 수 있을 예정이에요.
        </p>

        {/* 안내 텍스트 */}
        <p className="mt-3 text-[12px] text-ink3 leading-5">
          한도는 매월 1일 초기화돼요. 급히 필요하시면 1:1 문의를 남겨 주세요.
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
