import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, getInsuranceImportSourceUrl: vi.fn() };
});

import { ApiError, getInsuranceImportSourceUrl } from "@/lib/api";
import { InsuranceSourceViewer } from "@/components/insurance-source-viewer";

const JOB_ID = "33333333-3333-4333-8333-333333333333";

async function flush() {
  await act(async () => undefined);
}

describe("증권 원문 보기", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetAllMocks();
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    vi.mocked(getInsuranceImportSourceUrl).mockResolvedValue({
      url: "https://source.example/policy?signature=memory-only",
      expires_in: 300,
    });
  });

  afterEach(() => {
    document.body.style.overflow = "";
    vi.useRealTimers();
  });

  it("현재 page fragment와 접근 가능한 iframe, 새 화면 fallback을 제공한다", async () => {
    render(<InsuranceSourceViewer customerId={31} jobId={JOB_ID} pageCount={3} currentPage={3} availablePages={[2, 3]} onPageChange={vi.fn()} />);
    await flush();

    const iframe = screen.getByTitle("증권 원문, 3페이지") as HTMLIFrameElement;
    expect(iframe.getAttribute("src")).toBe("https://source.example/policy?signature=memory-only#page=3&zoom=page-width");
    expect(iframe.getAttribute("referrerpolicy")).toBe("no-referrer");
    const link = screen.getAllByRole("link", { name: "새 화면에서 보기" })[0];
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("5분 URL을 만료 30초 전에 다시 받고 hidden 동안 멈춘다", async () => {
    render(<InsuranceSourceViewer customerId={31} jobId={JOB_ID} pageCount={3} currentPage={2} availablePages={[2]} onPageChange={vi.fn()} />);
    await flush();
    await act(async () => vi.advanceTimersByTime(269_999));
    expect(getInsuranceImportSourceUrl).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event("focus"));
    await flush();
    expect(getInsuranceImportSourceUrl).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    await act(async () => vi.advanceTimersByTime(60_000));
    expect(getInsuranceImportSourceUrl).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
    await flush();
    expect(getInsuranceImportSourceUrl).toHaveBeenCalledTimes(2);
  });

  it("원문 404와 일시적인 연결 오류를 다른 다음 행동으로 안내한다", async () => {
    vi.mocked(getInsuranceImportSourceUrl).mockRejectedValueOnce(new ApiError(404, "not_found", "missing"));
    const { rerender } = render(<InsuranceSourceViewer customerId={31} jobId={JOB_ID} pageCount={3} currentPage={1} availablePages={[]} onPageChange={vi.fn()} />);
    await flush();
    expect(screen.getByRole("alert").textContent).toContain("같은 증권 파일을 다시 선택하면 이어서 확인할 수 있어요");
    expect(screen.getByRole("link", { name: "고객 분석으로 이동" }).getAttribute("href")).toBe("/customer/31?tab=analysis");

    vi.mocked(getInsuranceImportSourceUrl).mockRejectedValueOnce(new TypeError("network"));
    rerender(<InsuranceSourceViewer customerId={31} jobId="44444444-4444-4444-8444-444444444444" pageCount={3} currentPage={1} availablePages={[]} onPageChange={vi.fn()} />);
    await flush();
    expect(screen.getByRole("button", { name: "원문 다시 불러오기" })).toBeTruthy();
    expect(screen.queryByText("같은 증권 파일을 다시 선택하면 이어서 확인할 수 있어요")).toBeNull();
  });

  it("mobile dialog가 focus를 가두고 Escape 후 opener로 돌려보낸다", async () => {
    const { unmount } = render(<InsuranceSourceViewer customerId={31} jobId={JOB_ID} pageCount={3} currentPage={2} availablePages={[2, 3]} onPageChange={vi.fn()} />);
    await flush();
    const opener = screen.getByRole("button", { name: "원문 보기" });
    fireEvent.click(opener);

    const dialog = screen.getByRole("dialog");
    const close = screen.getByRole("button", { name: "원문 닫기" });
    expect(document.activeElement).toBe(close);
    expect(document.body.style.overflow).toBe("hidden");
    const focusable = dialog.querySelectorAll<HTMLElement>("button, a[href], iframe, [tabindex='0']");
    const last = focusable[focusable.length - 1];
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    close.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
    expect(document.body.style.overflow).toBe("");

    fireEvent.click(opener);
    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("mobile dialog가 열린 채 넓은 화면으로 바뀌면 닫고 body와 focus를 복구한다", async () => {
    let onDesktopChange: ((event: MediaQueryListEvent) => void) | undefined;
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        media: "(min-width: 1024px)",
        onchange: null,
        addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
          onDesktopChange = listener;
        },
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    });
    render(<InsuranceSourceViewer customerId={31} jobId={JOB_ID} pageCount={3} currentPage={1} availablePages={[1]} onPageChange={vi.fn()} />);
    await flush();
    const opener = screen.getByRole("button", { name: "원문 보기" });
    const desktopSource = screen.getByLabelText("증권 원문");
    expect(desktopSource.getAttribute("tabindex")).toBe("-1");
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("overflow-hidden");
    expect(dialog.querySelector(".min-w-0")).toBeTruthy();

    act(() => onDesktopChange?.({ matches: true } as MediaQueryListEvent));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.style.overflow).toBe("");
    expect(document.activeElement).toBe(desktopSource);
  });
});
