// 공용 클립보드 헬퍼 — 컴포넌트마다 중복되던 navigator.clipboard 패턴 단일화.
// ★ 정직성 레드라인: 자동발송 없음. 복사 후 설계사가 직접 전달(카톡/문자)까지만.

function fallbackCopy(text: string): boolean {
  if (typeof document === "undefined") return false;
  const execCommand = (
    document as Document & { execCommand?: (command: string) => boolean }
  ).execCommand;
  if (typeof execCommand !== "function") return false;

  const active =
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.readOnly = true;
  textarea.dataset.copyFallback = "true";
  textarea.style.position = "fixed";
  textarea.style.inset = "0 auto auto -9999px";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    return execCommand.call(document, "copy") === true;
  } catch {
    return false;
  } finally {
    textarea.remove();
    if (active?.isConnected) active.focus();
  }
}

/** 텍스트 클립보드 복사. 성공 true / 미지원·거부 false. */
export async function copyText(text: string): Promise<boolean> {
  if (
    typeof navigator !== "undefined" &&
    typeof navigator.clipboard?.writeText === "function"
  ) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return fallbackCopy(text);
    }
  }
  return fallbackCopy(text);
}
