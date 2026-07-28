import { afterEach, describe, expect, it, vi } from "vitest";

import { copyText } from "@/lib/clipboard";

const originalExecCommand = Object.getOwnPropertyDescriptor(
  document,
  "execCommand",
);

afterEach(() => {
  vi.unstubAllGlobals();
  if (originalExecCommand) {
    Object.defineProperty(document, "execCommand", originalExecCommand);
  } else {
    Reflect.deleteProperty(document, "execCommand");
  }
});

describe("copyText", () => {
  it("uses the Clipboard API when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    await expect(copyText("복사할 문구")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("복사할 문구");
  });

  it("returns false when Clipboard API and fallback both fail", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: vi.fn().mockReturnValue(false),
    });
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    await expect(copyText("복사할 문구")).resolves.toBe(false);
  });

  it("uses a temporary selectable textarea as a safe fallback", async () => {
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });
    vi.stubGlobal("navigator", {});

    await expect(copyText("대체 복사 문구")).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea[data-copy-fallback]")).toBeNull();
  });
});
