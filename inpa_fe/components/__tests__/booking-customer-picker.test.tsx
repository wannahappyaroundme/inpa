import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CustomerListItem } from "@/lib/api";
import { listCustomers } from "@/lib/api";
import { BookingCustomerPicker } from "@/components/booking-customer-picker";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  listCustomers: vi.fn(),
}));

const mockedListCustomers = vi.mocked(listCustomers);

function customer(overrides: Partial<CustomerListItem> = {}): CustomerListItem {
  return {
    id: 31,
    name: "김보장",
    gender: null,
    birth_day: null,
    mobile_phone_number: "010-1234-5678",
    consent_overseas_at: null,
    color: null,
    avatar_label: "김",
    tags: [],
    family_count: 0,
    memo_count: 0,
    sales_stage: "meeting",
    status: "active",
    share_token: null,
    created_at: "2026-07-27T00:00:00Z",
    lead_source: null,
    last_contacted_at: null,
    is_favorite: false,
    is_pinned: false,
    insurance_age: null,
    job_risk_grade: null,
    marketing_consent: "none",
    personal_info_consent: "none",
    ...overrides,
  };
}

function page(results: CustomerListItem[]) {
  return { count: results.length, next: null, previous: null, results };
}

afterEach(() => {
  vi.useRealTimers();
});

beforeEach(() => {
  mockedListCustomers.mockReset();
});

describe("예약 고객 검색 선택기", () => {
  it("고객명을 300ms 뒤 검색하고 선택을 상위에 알린다", async () => {
    vi.useFakeTimers();
    mockedListCustomers.mockResolvedValue(page([customer()]));
    const onChange = vi.fn();

    render(<BookingCustomerPicker value={null} onChange={onChange} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    fireEvent.change(screen.getByRole("combobox", { name: "고객 선택" }), { target: { value: "김보" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    expect(mockedListCustomers).toHaveBeenLastCalledWith({ page: 1, search: "김보" });
    fireEvent.click(screen.getByRole("option", { name: /김보장/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ id: 31 }));
    expect(screen.getByRole("combobox", { name: "고객 선택" })).toHaveValue("김보장");
  });

  it("늦게 끝난 이전 검색 결과를 보이지 않는다", async () => {
    vi.useFakeTimers();
    let resolveOld: ((value: ReturnType<typeof page>) => void) | undefined;
    const oldSearch = new Promise<ReturnType<typeof page>>((resolve) => { resolveOld = resolve; });
    mockedListCustomers
      .mockResolvedValueOnce(page([]))
      .mockImplementationOnce(() => oldSearch)
      .mockResolvedValueOnce(page([customer()]));

    render(<BookingCustomerPicker value={null} onChange={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    const input = screen.getByRole("combobox", { name: "고객 선택" });
    fireEvent.change(input, { target: { value: "김" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    fireEvent.change(input, { target: { value: "김보" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    expect(screen.getByRole("option", { name: /김보장/ })).toBeTruthy();
    await act(async () => resolveOld?.(page([customer({ id: 30, name: "김이전" })])));
    expect(screen.queryByRole("option", { name: /김이전/ })).toBeNull();
  });

  it("빈 결과에서 고객 추가를 안내한다", async () => {
    vi.useFakeTimers();
    mockedListCustomers.mockResolvedValue(page([]));

    render(<BookingCustomerPicker value={null} onChange={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    expect(screen.getByText("고객을 먼저 추가하면 바로 예약 안내를 만들 수 있어요.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "고객 추가하기" })).toHaveAttribute("href", "/customers");
  });

  it("실패한 검색은 다시 불러올 수 있다", async () => {
    vi.useFakeTimers();
    mockedListCustomers.mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(page([customer()]));

    render(<BookingCustomerPicker value={null} onChange={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    expect(screen.getByRole("alert")).toHaveTextContent("고객 목록을 다시 불러올 수 있어요.");
    fireEvent.click(screen.getByRole("button", { name: "다시 불러오기" }));
    await act(async () => {});
    expect(screen.getByRole("option", { name: /김보장/ })).toBeTruthy();
  });

  it("화살표와 Enter로 고객을 선택하고 Escape로 목록을 닫는다", async () => {
    vi.useFakeTimers();
    mockedListCustomers.mockResolvedValue(page([
      customer({ id: 31, name: "김보장" }),
      customer({ id: 32, name: "이보장", sales_stage: "contract" }),
    ]));
    const onChange = vi.fn();

    render(<BookingCustomerPicker value={null} onChange={onChange} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    const input = screen.getByRole("combobox", { name: "고객 선택" });
    expect(screen.getByRole("option", { name: /김보장/ })).toBeTruthy();
    fireEvent.click(input);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toBe(screen.getAllByRole("option")[1].id);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ id: 32 }));
    fireEvent.click(input);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).toHaveAttribute("aria-expanded", "false");
  });

  it("검색 결과에 마스킹한 전화번호와 공용 영업 단계를 보인다", async () => {
    vi.useFakeTimers();
    mockedListCustomers.mockResolvedValue(page([customer({ sales_stage: "meeting" })]));

    render(<BookingCustomerPicker value={null} onChange={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    expect(screen.getByRole("option", { name: /김보장/ })).toHaveTextContent("010-****-5678");
    expect(screen.getByRole("option", { name: /김보장/ })).toHaveTextContent("FA");
    expect(screen.queryByText("010-1234-5678")).toBeNull();
  });

  it("외부 고객 변경은 입력에 반영하고, 새 검색이 null을 알린 뒤에는 입력을 지우지 않는다", async () => {
    vi.useFakeTimers();
    mockedListCustomers.mockResolvedValue(page([]));
    const first = customer({ id: 1, name: "김첫번째" });
    const second = customer({ id: 2, name: "이두번째" });
    const { rerender, unmount } = render(<BookingCustomerPicker value={first} onChange={vi.fn()} />);
    const input = screen.getByRole("combobox", { name: "고객 선택" });

    rerender(<BookingCustomerPicker value={second} onChange={vi.fn()} />);
    expect(input).toHaveValue("이두번째");
    rerender(<BookingCustomerPicker value={null} onChange={vi.fn()} />);
    expect(input).toHaveValue("");
    unmount();

    function ControlledPicker() {
      const [selected, setSelected] = useState<CustomerListItem | null>(first);
      return <BookingCustomerPicker value={selected} onChange={setSelected} />;
    }
    const controlled = render(<ControlledPicker />);
    const controlledInput = controlled.getByRole("combobox", { name: "고객 선택" });
    fireEvent.change(controlledInput, { target: { value: "새 검색" } });
    expect(controlledInput).toHaveValue("새 검색");
  });

  it("두 선택기의 ARIA ID가 겹치지 않고 각 결과만 가리킨다", async () => {
    vi.useFakeTimers();
    mockedListCustomers.mockResolvedValue(page([customer()]));

    render(<><BookingCustomerPicker value={null} onChange={vi.fn()} /><BookingCustomerPicker value={null} onChange={vi.fn()} /></>);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    const inputs = screen.getAllByRole("combobox", { name: "고객 선택" });
    const listboxes = screen.getAllByRole("listbox", { name: "고객 검색 결과" });
    const options = screen.getAllByRole("option", { name: /김보장/ });
    expect(new Set([...inputs, ...listboxes, ...options].map((element) => element.id)).size).toBe(6);
    inputs.forEach((input, index) => expect(input.getAttribute("aria-controls")).toBe(listboxes[index].id));
  });

  it("짧은 연락처는 원문 조각 대신 숨김 안내만 보인다", async () => {
    vi.useFakeTimers();
    mockedListCustomers.mockResolvedValue(page([
      customer({ id: 11, name: "열한자리", mobile_phone_number: "010-1234-5678" }),
      customer({ id: 12, name: "여덟자리", mobile_phone_number: "010-12345" }),
      customer({ id: 13, name: "일곱자리", mobile_phone_number: "123-4567" }),
    ]));

    render(<BookingCustomerPicker value={null} onChange={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    expect(screen.getByRole("option", { name: /열한자리/ })).toHaveTextContent("010-****-5678");
    expect(screen.getByRole("option", { name: /여덟자리/ })).toHaveTextContent("010-****-2345");
    expect(screen.getByRole("option", { name: /일곱자리/ })).toHaveTextContent("연락처 일부 숨김");
    expect(screen.queryByText("123-4567")).toBeNull();
  });

  it("빈 결과에서는 화살표로 활성 항목을 만들지 않고 목록 참조를 비운다", async () => {
    vi.useFakeTimers();
    mockedListCustomers.mockResolvedValue(page([]));

    render(<BookingCustomerPicker value={null} onChange={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    const input = screen.getByRole("combobox", { name: "고객 선택" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowUp" });

    expect(input).not.toHaveAttribute("aria-activedescendant");
    expect(input).not.toHaveAttribute("aria-controls");
  });
});
