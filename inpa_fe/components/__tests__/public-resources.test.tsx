import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const analytics = vi.hoisted(() => ({ track: vi.fn() }));
vi.mock("@vercel/analytics", () => ({ track: analytics.track }));

import { metadata as insuranceAgeMetadata } from "@/app/tools/insurance-age/page";
import { metadata as customerSheetMetadata } from "@/app/resources/customer-management-sheet/page";
import { metadata as checklistMetadata } from "@/app/resources/consultation-checklist/page";
import { ConsultationChecklist } from "@/components/consultation-checklist";
import {
  CUSTOMER_MANAGEMENT_CSV,
  CustomerManagementSheet,
} from "@/components/customer-management-sheet";
import { InsuranceAgeCalculator } from "@/components/insurance-age-calculator";
import { trackPublicResourceUse } from "@/lib/public-resource-events";
import { PUBLIC_INDEX_ROBOTS } from "@/lib/search-policy";

beforeEach(() => {
  analytics.track.mockReset();
});

describe("보험나이 계산기", () => {
  it("계산 전 안내, 날짜 입력, 결과 기준, 오류와 초기화를 완성한다", () => {
    render(<InsuranceAgeCalculator />);

    expect(screen.getByText(/생년월일과 기준일을 입력하면/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("생년월일"), { target: { value: "2000-01-31" } });
    fireEvent.change(screen.getByLabelText("기준일"), { target: { value: "2026-07-31" } });
    fireEvent.click(screen.getByRole("button", { name: "보험나이 계산하기" }));
    expect(screen.getByText("27세")).toBeInTheDocument();
    expect(screen.getByText(/마지막 생일부터 6개월/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("생년월일"), { target: { value: "2027-01-01" } });
    fireEvent.click(screen.getByRole("button", { name: "보험나이 계산하기" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/날짜를 확인하면/);

    fireEvent.click(screen.getByRole("button", { name: "입력 초기화" }));
    expect(screen.getByLabelText("생년월일")).toHaveValue("");
    expect(screen.getByText(/생년월일과 기준일을 입력하면/)).toBeInTheDocument();
  });
});

describe("고객 관리 CSV", () => {
  it("UTF-8 BOM과 7개 한글 헤더만 제공하고 샘플 개인정보를 넣지 않는다", () => {
    expect(CUSTOMER_MANAGEMENT_CSV.charCodeAt(0)).toBe(0xfeff);
    expect(CUSTOMER_MANAGEMENT_CSV).toBe(
      "\ufeff고객명,연락처,영업 단계,진행 상태,마지막 연락일,다음 행동,메모\r\n",
    );
    expect(CUSTOMER_MANAGEMENT_CSV.trim().split(/\r?\n/)).toHaveLength(1);
    expect(CUSTOMER_MANAGEMENT_CSV).not.toMatch(/010-|김인파|홍길동/);
  });

  it("클릭 때 브라우저 파일을 만들고 주소를 바로 정리한다", () => {
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:customer-sheet");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<CustomerManagementSheet />);
    fireEvent.click(screen.getByRole("button", { name: "빈 고객 관리표 내려받기" }));

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:customer-sheet");
    expect(screen.getByRole("status")).toHaveTextContent("내려받았어요");
  });
});

describe("첫 상담 체크리스트", () => {
  it("준비·상담·후속 구간을 브라우저에서 체크하고 초기화·인쇄한다", () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    render(<ConsultationChecklist />);

    for (const title of ["상담 전 준비", "상담 중 확인", "상담 후 정리"]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }
    const checklist = screen.getByRole("group", { name: "첫 상담 체크 항목" });
    const boxes = within(checklist).getAllByRole("checkbox");
    expect(boxes.length).toBeGreaterThanOrEqual(12);
    fireEvent.click(boxes[0]);
    expect(screen.getByText(/1개 확인/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "전체 초기화" }));
    expect(boxes[0]).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "인쇄하기" }));
    expect(print).toHaveBeenCalledOnce();
  });

  it("입력과 체크 상태를 저장하거나 서버로 보내지 않는다", () => {
    const localSet = vi.spyOn(Storage.prototype, "setItem");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response());
    render(<ConsultationChecklist />);

    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByRole("button", { name: "전체 초기화" }));

    expect(localSet).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("공개 자료 개인정보 안전 이벤트", () => {
  it("resource, action, page_kind enum만 전송한다", () => {
    trackPublicResourceUse("insurance_age", "calculate", "tool");

    expect(analytics.track).toHaveBeenCalledWith("public_resource_use", {
      resource: "insurance_age",
      action: "calculate",
      page_kind: "tool",
    });
    const payload = analytics.track.mock.calls[0][1];
    expect(Object.keys(payload).sort()).toEqual(["action", "page_kind", "resource"]);
    expect(JSON.stringify(payload)).not.toMatch(/birth|date|check|referrer|query|url/i);
  });
});

describe("공개 자료 route 메타데이터", () => {
  it.each([
    [insuranceAgeMetadata, "/tools/insurance-age"],
    [customerSheetMetadata, "/resources/customer-management-sheet"],
    [checklistMetadata, "/resources/consultation-checklist"],
  ] as const)("%s는 고유 canonical과 공개 색인 정책을 쓴다", (metadata, canonical) => {
    expect(metadata.alternates).toEqual({ canonical });
    expect(metadata.robots).toEqual(PUBLIC_INDEX_ROBOTS);
    expect(metadata.title).toBeTruthy();
    expect(metadata.description).toBeTruthy();
    expect(metadata.openGraph).toMatchObject({ url: canonical });
  });
});
