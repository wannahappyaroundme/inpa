// 고객 전송용 비교 텍스트 빌더 — 설계사가 복사해 카톡·문자로 직접 보낸다(인파는 발송하지 않음).
//
// ★ §97 부당승환 레드라인(고객 대면 텍스트): 여기서 만드는 문자열은 고객이 직접 읽는다.
//   중립 사실(담보명·금액·증감 라벨 + 보험료 요약)만 담는다. 판정(KEEP/SWITCH)·권유·확인해야 할
//   사항(switch_warnings, 설계사 내부 전용)은 절대 포함하지 않는다.
//   이 파일은 check-copy.js 권유어 가드의 검사 대상이다(설계사 페이지 안에 두지 않고 분리한 이유 =
//   페이지엔 정당한 §97 내부 안내 문구가 있어 전체를 가드에 넣으면 오탐이 나기 때문).
import type { CompareResponse } from "@/lib/api";

const krw = new Intl.NumberFormat("ko-KR");

// 보장금액: 억·만 단위로 축약(제품 표준 표기와 동일 규칙). 0/미상은 '-'.
function fmtAmount(val: number | null): string {
  if (val === null || val === 0) return "-";
  if (val >= 100_000_000) return `${krw.format(val / 100_000_000)}억`;
  if (val >= 10_000) return `${krw.format(val / 10_000)}만`;
  return `${krw.format(val)}원`;
}
// 보험료: 원 단위 정확 표기. 미상은 '-'.
function fmtPrem(val: number | null): string {
  if (val === null) return "-";
  return `${krw.format(val)}원`;
}

// 담보 변동 라벨(중립 사실): 추가(신규)/삭제(빠짐)/변경/유지. A안 금액 vs B안 금액 기준.
export function compareDiffText(cur: number | null, prop: number | null): string {
  const c = cur ?? 0, p = prop ?? 0;
  if (c <= 0 && p > 0) return "추가";
  if (c > 0 && p <= 0) return "삭제";
  if (c > 0 && p > 0 && c !== p) return "변경";
  if (c > 0 && p > 0) return "유지";
  return "-";
}

/**
 * 비교 결과 → 고객에게 붙여넣어 보낼 중립 텍스트.
 * labelA/labelB = 각 열 이름(기본 '현재'/'제안', 제안 vs 제안 등 비교엔 'A안'/'B안'을 넘긴다).
 * 담보 금액이 없거나 한쪽이 비면 '-'로 표기한다(호출부에서 양쪽 1개 이상일 때만 노출 권장).
 */
export function buildCompareExportText(d: CompareResponse, labelA: string, labelB: string): string {
  const lines: string[] = ["보장 비교"];
  if (d.rows.length > 0) {
    lines.push("");
    for (const row of d.rows) {
      const diff = compareDiffText(row.current_amount, row.proposed_amount);
      lines.push(
        `${row.coverage}: ${labelA} ${fmtAmount(row.current_amount)} / ${labelB} ${fmtAmount(row.proposed_amount)} (${diff})`
      );
    }
  }
  lines.push("");
  lines.push(`${labelA} 월 ${fmtPrem(d.current.monthly_premiums)} · 총 ${fmtPrem(d.current.total_premiums)}`);
  lines.push(`${labelB} 월 ${fmtPrem(d.proposed.monthly_premiums)} · 총 ${fmtPrem(d.proposed.total_premiums)}`);
  lines.push("");
  lines.push("인파가 등록된 보장 정보를 정리한 참고 자료입니다. 보장 판단과 안내는 담당 설계사님이 합니다.");
  return lines.join("\n");
}
