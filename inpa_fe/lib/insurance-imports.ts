import type { InsuranceImportDraft, InsuranceImportStatus } from "@/lib/api";

export const MAX_INSURANCE_IMPORT_BYTES = 50 * 1024 * 1024;

export const IMPORT_STATUS_COPY: Record<InsuranceImportStatus, string> = {
  queued: "분석 순서를 기다리고 있어요",
  extracting: "증권 내용을 읽고 있어요",
  validating: "읽은 내용을 확인하고 있어요",
  review_required: "직접 확인할 내용이 준비됐어요",
  confirmed: "확인한 내용이 분석에 반영됐어요",
  failed: "증권 원문을 다시 선택해 주세요",
  canceled: "선택한 증권 작업을 정리했어요",
  superseded: "새로 확인한 자료가 반영됐어요",
};

export type InsuranceImportPreflight =
  | { ok: true }
  | { ok: false; code: "FILE_TOO_LARGE" | "INVALID_PDF_MIME" | "INVALID_PDF"; message: string };

export async function preflightInsuranceImport(file: File): Promise<InsuranceImportPreflight> {
  if (file.size > MAX_INSURANCE_IMPORT_BYTES) {
    return { ok: false, code: "FILE_TOO_LARGE", message: "50MB 이하의 전자 PDF를 선택해 주세요." };
  }
  if (!["", "application/pdf", "application/octet-stream"].includes(file.type.toLowerCase())) {
    return { ok: false, code: "INVALID_PDF_MIME", message: "전자 PDF 파일을 선택해 주세요." };
  }
  const magic = new TextDecoder("ascii").decode(await file.slice(0, 5).arrayBuffer());
  if (magic !== "%PDF-") {
    return { ok: false, code: "INVALID_PDF", message: "전자 PDF 파일을 선택해 주세요." };
  }
  return { ok: true };
}

export function createIdempotencyKey(): string {
  return crypto.randomUUID();
}

export function countUnresolved(
  draft: Pick<InsuranceImportDraft, "validation"> | { validation?: { unresolved_count?: number } }
): number {
  const value = draft.validation?.unresolved_count;
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : 0;
}
