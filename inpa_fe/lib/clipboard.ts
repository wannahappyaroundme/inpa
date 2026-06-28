// 공용 클립보드 헬퍼 — 컴포넌트마다 중복되던 navigator.clipboard 패턴 단일화.
// ★ 정직성 레드라인: 자동발송 없음. 복사 후 설계사가 직접 전달(카톡/문자)까지만.

/** 텍스트 클립보드 복사. 성공 true / 미지원·거부 false. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
