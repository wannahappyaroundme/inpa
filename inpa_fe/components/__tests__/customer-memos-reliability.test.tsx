import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listCustomerMemos: vi.fn(),
    createCustomerMemo: vi.fn(),
    updateCustomerMemo: vi.fn(),
    deleteCustomerMemo: vi.fn(),
  };
});

import {
  ApiError,
  createCustomerMemo,
  deleteCustomerMemo,
  listCustomerMemos,
  updateCustomerMemo,
  type CustomerMemo,
  type PaginatedResult,
} from "@/lib/api";
import { CustomerMemos } from "@/components/customer-memos";

function memo(overrides: Partial<CustomerMemo> = {}): CustomerMemo {
  return {
    id: 71,
    source: "manual",
    source_label: "직접 작성",
    body: "기존 메모",
    occurred_at: "2026-07-23T01:30:00Z",
    created_at: "2026-07-23T01:30:00Z",
    updated_at: "2026-07-23T01:30:00Z",
    edited_at: null,
    revision: 1,
    ...overrides,
  };
}

function page(results: CustomerMemo[], overrides: Partial<PaginatedResult<CustomerMemo>> = {}): PaginatedResult<CustomerMemo> {
  return { count: results.length, next: null, previous: null, results, ...overrides };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => { resolve = nextResolve; reject = nextReject; });
  return { promise, resolve, reject };
}

describe("상담 메모 신뢰성", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(listCustomerMemos).mockResolvedValue(page([memo()]));
  });

  it("고객을 바꾼 뒤 늦게 끝난 작성 결과와 busy 해제를 새 고객에 적용하지 않는다", async () => {
    const user = userEvent.setup();
    const create = deferred<CustomerMemo>();
    vi.mocked(createCustomerMemo).mockReturnValueOnce(create.promise);
    vi.mocked(listCustomerMemos)
      .mockResolvedValueOnce(page([memo({ body: "31번 메모" })]))
      .mockResolvedValueOnce(page([memo({ id: 72, body: "32번 메모" })]));
    const firstCount = vi.fn();
    const secondCount = vi.fn();
    const view = render(<CustomerMemos customerId={31} onCountChange={firstCount} />);
    await screen.findByText("31번 메모");
    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.type(screen.getByLabelText("새 메모"), "늦은 작성");
    await user.click(screen.getByRole("button", { name: "메모 저장" }));

    view.rerender(<CustomerMemos customerId={32} onCountChange={secondCount} />);
    expect(await screen.findByText("32번 메모")).toBeTruthy();
    create.resolve(memo({ id: 73, body: "늦은 작성" }));

    await waitFor(() => expect(screen.queryByText("늦은 작성")).toBeNull());
    expect(secondCount.mock.calls.map(([count]) => count)).toEqual([1]);
  });

  it("고객 전환 뒤 새 작성은 독립적으로 잠기며 이전 요청의 finally가 이를 풀지 않는다", async () => {
    const user = userEvent.setup();
    const firstCreate = deferred<CustomerMemo>();
    const secondCreate = deferred<CustomerMemo>();
    vi.mocked(createCustomerMemo)
      .mockReturnValueOnce(firstCreate.promise)
      .mockReturnValueOnce(secondCreate.promise);
    vi.mocked(listCustomerMemos)
      .mockResolvedValueOnce(page([]))
      .mockResolvedValueOnce(page([]));
    const secondCount = vi.fn();
    const view = render(<CustomerMemos customerId={31} onCountChange={vi.fn()} />);
    await screen.findByText("첫 상담 메모를 남겨보세요.");
    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.type(screen.getByLabelText("새 메모"), "31번 저장");
    await user.click(screen.getByRole("button", { name: "메모 저장" }));

    view.rerender(<CustomerMemos customerId={32} onCountChange={secondCount} />);
    expect(await screen.findByText("첫 상담 메모를 남겨보세요.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    const textarea = screen.getByLabelText("새 메모");
    expect(textarea).not.toHaveAttribute("readonly");
    await user.type(textarea, "32번 저장");
    await user.click(screen.getByRole("button", { name: "메모 저장" }));
    expect(textarea).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "저장 중" })).toBeDisabled();

    firstCreate.resolve(memo({ id: 81, body: "31번 저장" }));
    await waitFor(() => expect(screen.getByLabelText("새 메모")).toHaveAttribute("readonly"));
    expect(screen.getByRole("button", { name: "저장 중" })).toBeDisabled();
    expect(screen.queryByText("31번 저장")).toBeNull();
    secondCreate.resolve(memo({ id: 82, body: "32번 저장" }));

    expect(await screen.findByText("32번 저장")).toBeTruthy();
    expect(secondCount.mock.calls.map(([count]) => count)).toEqual([0, 1]);
  });

  it("고객을 바꾼 뒤 늦은 수정 충돌은 이전 고객을 다시 읽거나 새 목록을 바꾸지 않는다", async () => {
    const user = userEvent.setup();
    const update = deferred<CustomerMemo>();
    vi.mocked(updateCustomerMemo).mockReturnValueOnce(update.promise);
    vi.mocked(listCustomerMemos)
      .mockResolvedValueOnce(page([memo({ body: "31번 메모" })]))
      .mockResolvedValueOnce(page([memo({ id: 72, body: "32번 메모" })]));
    const view = render(<CustomerMemos customerId={31} onCountChange={vi.fn()} />);
    await screen.findByText("31번 메모");
    await user.click(screen.getByRole("button", { name: "메모 수정: 31번 메모" }));
    await user.clear(screen.getByLabelText("메모 수정"));
    await user.type(screen.getByLabelText("메모 수정"), "늦은 수정");
    await user.click(screen.getByRole("button", { name: "수정 저장" }));

    view.rerender(<CustomerMemos customerId={32} onCountChange={vi.fn()} />);
    expect(await screen.findByText("32번 메모")).toBeTruthy();
    update.reject(new ApiError(409, "MEMO_EDIT_CONFLICT", "다른 화면에서 수정된 메모예요."));

    await waitFor(() => expect(screen.queryByText("늦은 수정")).toBeNull());
    expect(listCustomerMemos).toHaveBeenCalledTimes(2);
  });

  it("고객을 바꾼 뒤 늦은 삭제 결과는 새 고객의 카드나 개수를 건드리지 않는다", async () => {
    const user = userEvent.setup();
    const removing = deferred<void>();
    vi.mocked(deleteCustomerMemo).mockReturnValueOnce(removing.promise);
    vi.mocked(listCustomerMemos)
      .mockResolvedValueOnce(page([memo({ body: "31번 메모" })]))
      .mockResolvedValueOnce(page([memo({ id: 72, body: "32번 메모" })]));
    const secondCount = vi.fn();
    const view = render(<CustomerMemos customerId={31} onCountChange={vi.fn()} />);
    await screen.findByText("31번 메모");
    await user.click(screen.getByRole("button", { name: "메모 삭제: 31번 메모" }));
    await user.click(screen.getByRole("button", { name: "삭제할게요" }));

    view.rerender(<CustomerMemos customerId={32} onCountChange={secondCount} />);
    expect(await screen.findByText("32번 메모")).toBeTruthy();
    removing.resolve();

    await waitFor(() => expect(screen.getByText("32번 메모")).toBeTruthy());
    expect(secondCount.mock.calls.map(([count]) => count)).toEqual([1]);
  });

  it("변경이 시작되면 이전 페이지 응답이 작성 결과나 전체 개수를 덮어쓰지 않는다", async () => {
    const user = userEvent.setup();
    const more = deferred<PaginatedResult<CustomerMemo>>();
    vi.mocked(listCustomerMemos)
      .mockResolvedValueOnce(page([memo({ id: 3, body: "첫 페이지" })], { count: 2, next: "https://api.example/memos/?page=2" }))
      .mockReturnValueOnce(more.promise);
    vi.mocked(createCustomerMemo).mockResolvedValueOnce(memo({ id: 4, body: "작성 결과" }));
    const onCountChange = vi.fn();
    render(<CustomerMemos customerId={31} onCountChange={onCountChange} />);
    await screen.findByText("첫 페이지");
    await user.click(screen.getByRole("button", { name: "이전 메모 더 보기" }));
    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.type(screen.getByLabelText("새 메모"), "작성 결과");
    await user.click(screen.getByRole("button", { name: "메모 저장" }));
    more.resolve(page([memo({ id: 2, body: "늦은 두 번째 페이지" })], { count: 2 }));

    expect(await screen.findByText("작성 결과")).toBeTruthy();
    expect(screen.queryByText("늦은 두 번째 페이지")).toBeNull();
    expect(onCountChange.mock.calls.map(([count]) => count)).toEqual([2, 3]);
  });

  it("작성 저장 중에는 그 textarea를 읽기 전용으로 두고 성공 결과에 입력되지 않은 글을 섞지 않는다", async () => {
    const user = userEvent.setup();
    const saving = deferred<CustomerMemo>();
    vi.mocked(listCustomerMemos).mockResolvedValueOnce(page([]));
    vi.mocked(createCustomerMemo).mockReturnValueOnce(saving.promise);
    render(<CustomerMemos customerId={31} onCountChange={vi.fn()} />);
    await screen.findByText("첫 상담 메모를 남겨보세요.");
    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.type(screen.getByLabelText("새 메모"), "보낼 내용");
    await user.click(screen.getByRole("button", { name: "메모 저장" }));
    await user.type(screen.getByLabelText("새 메모"), " 잃으면 안 되는 글");
    expect(screen.getByLabelText("새 메모")).toHaveValue("보낼 내용");
    saving.resolve(memo({ id: 72, body: "보낼 내용" }));
    expect(await screen.findByText("보낼 내용")).toBeTruthy();
    expect(createCustomerMemo).toHaveBeenCalledWith(31, "보낼 내용");
  });

  it("수정 저장 중에도 textarea를 읽기 전용으로 두고 실패한 초안은 그대로 남긴다", async () => {
    const user = userEvent.setup();
    const saving = deferred<CustomerMemo>();
    vi.mocked(updateCustomerMemo).mockReturnValueOnce(saving.promise);
    render(<CustomerMemos customerId={31} onCountChange={vi.fn()} />);
    await screen.findByText("기존 메모");
    await user.click(screen.getByRole("button", { name: "메모 수정: 기존 메모" }));
    await user.clear(screen.getByLabelText("메모 수정"));
    await user.type(screen.getByLabelText("메모 수정"), "보낼 수정");
    await user.click(screen.getByRole("button", { name: "수정 저장" }));
    await user.type(screen.getByLabelText("메모 수정"), " 잃으면 안 되는 글");
    expect(screen.getByLabelText("메모 수정")).toHaveValue("보낼 수정");
    saving.reject(new ApiError(500, "SAVE_FAILED", "수정 저장에 실패했어요."));
    expect(await screen.findByText("수정 저장에 실패했어요.")).toBeTruthy();
    expect(screen.getByLabelText("메모 수정")).toHaveValue("보낼 수정");
  });

  it("충돌 뒤 최신 내용을 못 읽으면 초안을 지키고 재시도로 최신 내용을 받은 뒤에만 다시 저장할 수 있다", async () => {
    const user = userEvent.setup();
    const old = memo({ body: "이전 내용", revision: 1 });
    const latest = memo({ body: "새 최신 내용", revision: 2 });
    vi.mocked(listCustomerMemos)
      .mockResolvedValueOnce(page([old]))
      .mockRejectedValueOnce(new ApiError(500, "LOAD_FAILED", "최신 메모를 불러오지 못했어요."))
      .mockResolvedValueOnce(page([latest]));
    vi.mocked(updateCustomerMemo).mockRejectedValueOnce(new ApiError(409, "MEMO_EDIT_CONFLICT", "다른 화면에서 수정된 메모예요."));
    render(<CustomerMemos customerId={31} onCountChange={vi.fn()} />);
    await screen.findByText("이전 내용");
    await user.click(screen.getByRole("button", { name: "메모 수정: 이전 내용" }));
    await user.clear(screen.getByLabelText("메모 수정"));
    await user.type(screen.getByLabelText("메모 수정"), "내 초안");
    await user.click(screen.getByRole("button", { name: "수정 저장" }));

    expect(await screen.findByText("최신 내용을 다시 불러오면 작성한 내용을 이어서 저장할 수 있어요.")).toBeTruthy();
    expect(screen.queryByText(/최신 메모:/)).toBeNull();
    expect(screen.queryByRole("button", { name: "수정 저장" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "최신 내용 다시 불러오기" }));
    expect(await screen.findByText(/새 최신 내용/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "수정 저장" })).not.toBeDisabled();
    expect(updateCustomerMemo).toHaveBeenCalledOnce();
  });

  it("키보드 진입과 Escape 취소, 의미 있는 목록, 삭제 성공 뒤의 안전한 포커스를 제공한다", async () => {
    const user = userEvent.setup();
    vi.mocked(deleteCustomerMemo).mockResolvedValueOnce(undefined);
    render(<CustomerMemos customerId={31} onCountChange={vi.fn()} />);
    await screen.findByText("기존 메모");
    const create = screen.getByRole("button", { name: "메모 작성" });
    await user.click(create);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("새 메모")));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "메모 작성" })));
    expect(screen.getByRole("list")).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getAllByRole("article")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "메모 삭제: 기존 메모" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "그대로 둘게요" })));
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "삭제할게요" }));
    await user.click(screen.getByRole("button", { name: "삭제할게요" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "메모 작성" })));
  });

  it("작성과 수정 성공 뒤에도 다음 행동으로 포커스를 돌려준다", async () => {
    const user = userEvent.setup();
    const created = memo({ id: 72, body: "새 메모" });
    vi.mocked(listCustomerMemos).mockResolvedValueOnce(page([]));
    vi.mocked(createCustomerMemo).mockResolvedValueOnce(created);
    vi.mocked(updateCustomerMemo).mockResolvedValueOnce(memo({ id: 72, body: "수정 메모", revision: 2 }));
    render(<CustomerMemos customerId={31} onCountChange={vi.fn()} />);
    await screen.findByText("첫 상담 메모를 남겨보세요.");
    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("새 메모")));
    await user.type(screen.getByLabelText("새 메모"), "새 메모");
    await user.click(screen.getByRole("button", { name: "메모 저장" }));
    expect(await screen.findByText("새 메모")).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "메모 작성" })));

    await user.click(screen.getByRole("button", { name: "메모 수정: 새 메모" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("메모 수정")));
    await user.clear(screen.getByLabelText("메모 수정"));
    await user.type(screen.getByLabelText("메모 수정"), "수정 메모");
    await user.click(screen.getByRole("button", { name: "수정 저장" }));
    expect(await screen.findByText("수정 메모")).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "메모 수정: 수정 메모" })));
  });

  it("빠른 수정과 삭제 확인은 각각 한 번만 전송한다", async () => {
    const user = userEvent.setup();
    const updating = deferred<CustomerMemo>();
    const deleting = deferred<void>();
    vi.mocked(updateCustomerMemo).mockReturnValueOnce(updating.promise);
    vi.mocked(deleteCustomerMemo).mockReturnValueOnce(deleting.promise);
    render(<CustomerMemos customerId={31} onCountChange={vi.fn()} />);
    await screen.findByText("기존 메모");
    await user.click(screen.getByRole("button", { name: "메모 수정: 기존 메모" }));
    await user.clear(screen.getByLabelText("메모 수정"));
    await user.type(screen.getByLabelText("메모 수정"), "수정함");
    await user.dblClick(screen.getByRole("button", { name: "수정 저장" }));
    expect(updateCustomerMemo).toHaveBeenCalledOnce();
    updating.resolve(memo({ body: "수정함", revision: 2 }));
    expect(await screen.findByText("수정함")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "메모 삭제: 수정함" }));
    await user.dblClick(screen.getByRole("button", { name: "삭제할게요" }));
    expect(deleteCustomerMemo).toHaveBeenCalledOnce();
    deleting.resolve();
  });
});
