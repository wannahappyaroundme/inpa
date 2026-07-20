import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getInsuranceImportConfig: vi.fn(),
    createInsuranceImport: vi.fn(),
    uploadInsuranceOcr: vi.fn(),
    createConsentRequest: vi.fn(),
    getConsentTexts: vi.fn(),
  };
});

import {
  ApiError,
  type ConsentRequestResponse,
  createConsentRequest,
  createInsuranceImport,
  getConsentTexts,
  getInsuranceImportConfig,
  uploadInsuranceOcr,
} from "@/lib/api";
import {
  InsuranceDuplicateChoice,
  ConsentModal,
  OcrStatusBanner,
  OcrUploadButton,
  useOcrUpload,
} from "@/components/ocr-upload";

function pdf() {
  return new File([new TextEncoder().encode("%PDF-1.7\nbody")], "policy.pdf", {
    type: "application/pdf",
  });
}

function Harness({ portfolioType = 1 }: { portfolioType?: 1 | 2 }) {
  const upload = useOcrUpload(undefined, portfolioType, 31);
  return (
    <>
      <OcrUploadButton
        customerId={31}
        phase={upload.phase}
        onFileChange={upload.onFileChange}
      />
      <span data-testid="phase">{upload.phase}</span>
      <OcrStatusBanner
        phase={upload.phase}
        errorMsg={upload.error}
        onDismiss={upload.clearError}
        onRetry={upload.retryUpload}
      />
      <InsuranceDuplicateChoice
        info={upload.duplicateInfo}
        onOpenExisting={upload.openDuplicateInsurance}
        onReplace={upload.resolveDuplicateReplace}
      />
    </>
  );
}

function ConsentHarness({ customerId }: { customerId: number }) {
  const upload = useOcrUpload(undefined, 1, customerId);
  return (
    <>
      <button type="button" onClick={() => void upload.generateConsentLink(customerId)}>
        링크 요청
      </button>
      <span data-testid="consent-loading">{String(upload.consentLoading)}</span>
      <span data-testid="consent-url">{upload.consentUrl ?? ""}</span>
    </>
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => { resolve = nextResolve; });
  return { promise, resolve };
}

describe("증권 업로드 분기", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getInsuranceImportConfig).mockResolvedValue({
      review_workflow_enabled: true,
      accepted_input: "digital_pdf",
      max_file_bytes: 50 * 1024 * 1024,
    });
    vi.mocked(createInsuranceImport).mockResolvedValue({
      job_id: "33333333-3333-4333-8333-333333333333",
      status: "queued",
    });
    vi.mocked(uploadInsuranceOcr).mockResolvedValue({
      code: "ok",
      parsing_method: "legacy",
      created_cases: 1,
      insurance: {},
    });
    vi.mocked(createConsentRequest).mockResolvedValue({
      token: "consent-token",
      consent_url: "https://example.test/c/consent",
      already_consented: false,
    });
    vi.mocked(getConsentTexts).mockResolvedValue({
      version: "v2",
      texts: {},
    });
  });

  it("스위치가 켜지면 202 작업을 만들고 고객별 확인 화면으로 이동한다", async () => {
    const user = userEvent.setup();
    render(<Harness portfolioType={2} />);

    const input = screen.getByLabelText("증권 PDF 업로드") as HTMLInputElement;
    await user.upload(input, pdf());

    await waitFor(() => expect(createInsuranceImport).toHaveBeenCalledOnce());
    expect(createInsuranceImport).toHaveBeenCalledWith(
      31,
      expect.any(File),
      expect.objectContaining({ intent: "add", portfolioType: 2 })
    );
    expect(push).toHaveBeenCalledWith(
      "/customer/31/insurance-imports/33333333-3333-4333-8333-333333333333"
    );
    expect(input.value).toBe("");
    expect(uploadInsuranceOcr).not.toHaveBeenCalled();
  });

  it("스위치가 꺼진 동안만 기존 즉시 등록 흐름을 유지한다", async () => {
    vi.mocked(getInsuranceImportConfig).mockResolvedValue({
      review_workflow_enabled: false,
      accepted_input: "digital_pdf",
      max_file_bytes: 50 * 1024 * 1024,
    });
    render(<Harness />);

    fireEvent.change(screen.getByLabelText("증권 PDF 업로드"), {
      target: { files: [pdf()] },
    });

    await waitFor(() => expect(uploadInsuranceOcr).toHaveBeenCalledOnce());
    expect(createInsuranceImport).not.toHaveBeenCalled();
  });

  it("설정을 불러오지 못하면 기존 흐름으로 조용히 바꾸지 않고 재시도를 안내한다", async () => {
    vi.mocked(getInsuranceImportConfig).mockRejectedValue(new Error("network"));
    const user = userEvent.setup();
    render(<Harness />);

    await user.upload(screen.getByLabelText("증권 PDF 업로드"), pdf());

    expect(await screen.findByText("증권 등록 방식을 확인하지 못했어요. 다시 시도해 주세요.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
    expect(createInsuranceImport).not.toHaveBeenCalled();
    expect(uploadInsuranceOcr).not.toHaveBeenCalled();
  });

  it.each([
    [412, "CONSENT_OVERSEAS_REQUIRED", "consent_required"],
    [402, "credit_exhausted", "limit_exceeded"],
  ] as const)("%s 응답을 기존 안내 흐름으로 연결한다", async (status, code, phase) => {
    vi.mocked(createInsuranceImport).mockRejectedValueOnce(
      new ApiError(status, code, "확인이 필요해요", status === 402 ? { kind: "ocr" } : undefined)
    );
    const user = userEvent.setup();
    render(<Harness />);

    await user.upload(screen.getByLabelText("증권 PDF 업로드"), pdf());

    await waitFor(() => expect(screen.getByTestId("phase").textContent).toBe(phase));
  });

  it("이미 확인한 증권이면 기존 보험 보기와 다음 등록 방식을 고르게 한다", async () => {
    vi.mocked(createInsuranceImport).mockRejectedValueOnce(
      new ApiError(409, "DUPLICATE_CONFIRMED", "이미 확인한 증권이에요", undefined, undefined, {
        insurance_id: 9,
        insurance_version: 7,
        allowed_intents: ["add", "replace"],
        duplicate_resolution_token: "server-signed-token",
      })
    );
    const user = userEvent.setup();
    render(<Harness />);
    await user.upload(screen.getByLabelText("증권 PDF 업로드"), pdf());

    expect(await screen.findByText("이미 확인한 증권이에요")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "새 보험 추가" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "새 증권으로 교체" }));

    await waitFor(() => expect(createInsuranceImport).toHaveBeenCalledTimes(2));
    expect(createInsuranceImport).toHaveBeenLastCalledWith(
      31,
      expect.any(File),
      expect.objectContaining({
        intent: "replace",
        targetInsuranceId: 9,
        duplicateResolutionToken: "server-signed-token",
      })
    );
  });

  it("서버가 접수하기 전에는 내용 인식이나 분석 단계가 진행된 것처럼 표시하지 않는다", async () => {
    const pending = deferred<{ job_id: string; status: "queued" }>();
    vi.mocked(createInsuranceImport).mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<Harness />);

    await user.upload(screen.getByLabelText("증권 PDF 업로드"), pdf());
    expect(await screen.findByText("증권 접수 중…")).toBeTruthy();
    expect(screen.queryByText("내용 인식 중…")).toBeNull();
    expect(screen.queryByText("보장 분석 중…")).toBeNull();

    await act(async () => pending.resolve({
      job_id: "33333333-3333-4333-8333-333333333333",
      status: "queued",
    }));
  });

  it("동의 링크는 현재 고객의 가장 최근 요청만 화면에 반영한다", async () => {
    const first = deferred<ConsentRequestResponse>();
    const second = deferred<ConsentRequestResponse>();
    vi.mocked(createConsentRequest)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const view = render(<ConsentHarness customerId={31} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "링크 요청" }));
    view.rerender(<ConsentHarness customerId={32} />);
    await user.click(screen.getByRole("button", { name: "링크 요청" }));
    await act(async () => second.resolve({
      token: "customer-32-token",
      consent_url: "https://example.test/c/customer-32",
      already_consented: false,
    }));
    expect(screen.getByTestId("consent-url").textContent).toContain("customer-32");

    await act(async () => first.resolve({
      token: "customer-31-token",
      consent_url: "https://example.test/c/customer-31",
      already_consented: false,
    }));
    expect(screen.getByTestId("consent-url").textContent).toContain("customer-32");
    expect(screen.getByTestId("consent-loading").textContent).toBe("false");
  });

  it("동의 링크 요청 중 화면을 닫아도 늦은 응답을 반영하지 않는다", async () => {
    const pending = deferred<ConsentRequestResponse>();
    vi.mocked(createConsentRequest).mockReturnValueOnce(pending.promise);
    const view = render(<ConsentHarness customerId={31} />);
    fireEvent.click(screen.getByRole("button", { name: "링크 요청" }));
    expect(screen.getByTestId("consent-loading").textContent).toBe("true");

    view.unmount();
    await act(async () => pending.resolve({
      token: "late-token",
      consent_url: "https://example.test/c/late",
      already_consented: false,
    }));
    expect(screen.queryByText("https://example.test/c/late")).toBeNull();
  });

  it("같은 고객이 링크를 다시 만들면 가장 최근 요청만 반영한다", async () => {
    const first = deferred<ConsentRequestResponse>();
    const second = deferred<ConsentRequestResponse>();
    vi.mocked(createConsentRequest)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    render(<ConsentHarness customerId={31} />);

    fireEvent.click(screen.getByRole("button", { name: "링크 요청" }));
    fireEvent.click(screen.getByRole("button", { name: "링크 요청" }));
    await act(async () => second.resolve({
      token: "latest-token",
      consent_url: "https://example.test/c/latest",
      already_consented: false,
    }));
    await act(async () => first.resolve({
      token: "older-token",
      consent_url: "https://example.test/c/older",
      already_consented: false,
    }));

    expect(screen.getByTestId("consent-url").textContent).toBe("https://example.test/c/latest");
    expect(screen.getByTestId("consent-loading").textContent).toBe("false");
  });

  it("동의 모달은 첫 동작으로 이동하고 키보드 순환, Escape, 복귀, 스크롤 잠금을 지원한다", async () => {
    const onDismiss = vi.fn();
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const view = render(
      <ConsentModal
        onGenerate={vi.fn()}
        consentUrl={null}
        consentCopied={false}
        onCopy={vi.fn()}
        onDismiss={onDismiss}
        loading={false}
        error="링크를 다시 만들어 주세요."
      />
    );
    const user = userEvent.setup();
    const firstAction = screen.getByRole("button", { name: "다시 시도하기" });
    const close = screen.getByRole("button", { name: "닫기" });

    expect(document.activeElement).toBe(firstAction);
    expect(document.body.style.overflow).toBe("hidden");
    expect(screen.getByRole("alert").textContent).toContain("링크를 다시 만들어 주세요.");
    close.focus();
    await user.tab();
    expect(document.activeElement).toBe(firstAction);
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(close);
    await user.keyboard("{Escape}");
    expect(onDismiss).toHaveBeenCalledOnce();

    view.unmount();
    expect(document.body.style.overflow).toBe("");
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("동의 링크 생성 중에는 대화상자 자체가 포커스를 지키고 배경을 잠근다", async () => {
    const onDismiss = vi.fn();
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const view = render(
      <ConsentModal
        onGenerate={vi.fn()}
        consentUrl={null}
        consentCopied={false}
        onCopy={vi.fn()}
        onDismiss={onDismiss}
        loading
        error={null}
      />
    );
    const user = userEvent.setup();
    const dialog = screen.getByRole("dialog");

    expect(dialog.tabIndex).toBe(-1);
    expect(document.activeElement).toBe(dialog);
    expect(opener.inert).toBe(true);

    await user.tab();
    expect(document.activeElement).toBe(dialog);
    await user.keyboard("{Escape}");
    expect(onDismiss).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(dialog);

    view.rerender(
      <ConsentModal
        onGenerate={vi.fn()}
        consentUrl={null}
        consentCopied={false}
        onCopy={vi.fn()}
        onDismiss={onDismiss}
        loading={false}
        error={null}
      />
    );
    await user.keyboard("{Escape}");
    expect(onDismiss).toHaveBeenCalledOnce();

    view.unmount();
    expect(opener.inert).toBe(false);
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});
