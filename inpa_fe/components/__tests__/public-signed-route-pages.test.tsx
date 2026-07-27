import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CustomerConsentPage from "@/app/c/[token]/page";
import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  getConsentDisclosure: vi.fn(),
  submitConsent: vi.fn(),
}));
const navigation = vi.hoisted(() => ({ token: "" as string | string[] | undefined }));

vi.mock("next/navigation", () => ({ useParams: () => ({ token: navigation.token }) }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));
vi.mock("@/components/ui", () => ({
  Card: ({ children, className = "" }: { children: React.ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
}));

const SIGNED = "eyJwayI6MTI4fQ:1wo9X8:k8naBaeSr-UhWUIbw-0KvWK1c8";

const consentDisclosure = {
  customer: { name_masked: "김**" },
  planner: { affiliation: "부산지점" },
  items: [{
    scope: "personal_info" as const,
    title: "상담을 위한 개인정보 이용",
    required: true,
    already: false,
    revocable: false,
    lines: ["상담 준비에 필요한 정보를 이용합니다."],
    notice: "동의 내용은 언제든 확인할 수 있어요.",
  }],
  all_required_done: false,
  disclaimer: "동의 내용을 확인해 주세요.",
};

describe("customer consent public signed route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getConsentDisclosure.mockReset();
    api.submitConsent.mockReset();
    api.submitConsent.mockResolvedValue({ results: [], all_required_done: true });
    navigation.token = SIGNED;
  });

  it("loads a once-encoded route token with its normalized raw value", async () => {
    navigation.token = encodeURIComponent(SIGNED);
    api.getConsentDisclosure.mockResolvedValue(consentDisclosure);

    render(<CustomerConsentPage />);

    await waitFor(() => expect(api.getConsentDisclosure).toHaveBeenCalledWith(SIGNED));
  });

  it.each([
    encodeURIComponent(encodeURIComponent(SIGNED)),
    "broken%2",
    "has/slash",
    "has%2Fslash",
    "has space",
    "%00control",
    [SIGNED],
  ])("shows a link-help card without fetching unsafe route input %#", async (token) => {
    navigation.token = token;

    render(<CustomerConsentPage />);

    expect(await screen.findByText("링크를 열 수 없어요")).toBeTruthy();
    expect(api.getConsentDisclosure).not.toHaveBeenCalled();
    expect(api.submitConsent).not.toHaveBeenCalled();
  });

  it.each([
    new ApiError(404, "NOT_FOUND", "담당 설계사에게 새 링크를 요청해 주세요."),
    new ApiError(410, "LINK_EXPIRED", "담당 설계사에게 새 링크를 요청해 주세요."),
  ])("keeps %s as a terminal link-help state", async (error) => {
    api.getConsentDisclosure.mockRejectedValueOnce(error);

    render(<CustomerConsentPage />);

    expect(await screen.findByText("링크를 열 수 없어요")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "다시 불러오기" })).toBeNull();
  });

  it.each([
    new ApiError(429, "THROTTLED", "busy"),
    new ApiError(503, "TEMPORARY", "down"),
    new TypeError("network"),
  ])("retries %s with the same normalized raw token", async (error) => {
    navigation.token = encodeURIComponent(SIGNED);
    api.getConsentDisclosure
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce(consentDisclosure);

    render(<CustomerConsentPage />);

    expect(await screen.findByText("잠시 연결이 원활하지 않아요")).toBeTruthy();
    await userEvent.setup().click(screen.getByRole("button", { name: "다시 불러오기" }));
    expect(await screen.findByText("상담을 위한 개인정보 이용")).toBeTruthy();
    expect(api.getConsentDisclosure).toHaveBeenNthCalledWith(1, SIGNED);
    expect(api.getConsentDisclosure).toHaveBeenNthCalledWith(2, SIGNED);
  });

  it("submits newly checked consent with the normalized raw token", async () => {
    navigation.token = encodeURIComponent(SIGNED);
    api.getConsentDisclosure.mockResolvedValue(consentDisclosure);
    const user = userEvent.setup();

    render(<CustomerConsentPage />);

    await user.click(await screen.findByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "동의합니다" }));

    await waitFor(() => expect(api.submitConsent).toHaveBeenCalledWith(SIGNED, ["personal_info"]));
  });

  it("revokes an existing consent with the normalized raw token", async () => {
    navigation.token = encodeURIComponent(SIGNED);
    api.getConsentDisclosure.mockResolvedValue({
      ...consentDisclosure,
      items: [{ ...consentDisclosure.items[0], already: true, revocable: true }],
      all_required_done: true,
    });
    const user = userEvent.setup();

    render(<CustomerConsentPage />);

    await user.click(await screen.findByRole("button", { name: "동의 철회" }));
    await user.click(screen.getByRole("button", { name: "철회하기" }));

    await waitFor(() => expect(api.submitConsent).toHaveBeenCalledWith(SIGNED, [], ["personal_info"]));
  });
});
