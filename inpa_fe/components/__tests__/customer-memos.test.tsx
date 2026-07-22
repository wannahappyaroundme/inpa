import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => {
  let entries = ["/customer/31"];
  let index = 0;
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((listener) => listener());
  const searchFrom = (href: string) => href.split("?")[1]?.split("#")[0] ?? "";
  const push = vi.fn((href: string) => {
    entries = [...entries.slice(0, index + 1), href];
    index += 1;
    notify();
  });
  const replace = vi.fn((href: string) => {
    entries[index] = href;
    notify();
  });
  return {
    push,
    replace,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    snapshot: () => searchFrom(entries[index]),
    reset(search = "") {
      entries = [`/customer/31${search ? `?${search}` : ""}`];
      index = 0;
      push.mockClear();
      replace.mockClear();
      notify();
    },
    back() {
      if (index > 0) {
        index -= 1;
        notify();
      }
    },
    forward() {
      if (index < entries.length - 1) {
        index += 1;
        notify();
      }
    },
    current: () => entries[index],
  };
});

vi.mock("next/navigation", async () => {
  const React = await import("react");
  return {
    useParams: () => ({ id: "31" }),
    useRouter: () => ({ push: navigation.push, replace: navigation.replace }),
    useSearchParams: () => {
      const search = React.useSyncExternalStore(
        navigation.subscribe,
        navigation.snapshot,
        navigation.snapshot,
      );
      return React.useMemo(() => new URLSearchParams(search), [search]);
    },
  };
});

vi.mock("next/link", async () => {
  const React = await import("react");
  return {
    default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }>(
      function TestLink({ href, children, ...props }, ref) {
        return <a ref={ref} href={href} {...props}>{children}</a>;
      },
    ),
  };
});

vi.mock("@/lib/useAuthGuard", () => ({ useAuthGuard: () => true }));
vi.mock("@/components/app-nav", () => ({ AppNav: () => <nav aria-label="앱 메뉴" /> }));
vi.mock("@/components/ocr-upload", () => ({
  useOcrUpload: () => ({ phase: "idle" }),
  OcrUploadButton: () => null,
  OcrStatusBanner: () => null,
  ConsentModal: () => null,
  InsuranceDuplicateChoice: () => null,
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getCustomer: vi.fn(),
    getCustomerHistory: vi.fn(),
    getProfile: vi.fn(),
    listContactLogs: vi.fn(),
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
  getCustomer,
  getCustomerHistory,
  getProfile,
  listContactLogs,
  listCustomerMemos,
  updateCustomerMemo,
  type CustomerDetail,
  type CustomerMemo,
  type ProfileResponse,
  type PaginatedResult,
} from "@/lib/api";
import { CustomerMemos } from "@/components/customer-memos";
import CustomerDetailPage from "@/app/customer/[id]/page";

const customerId = 31;

function memo(overrides: Partial<CustomerMemo> = {}): CustomerMemo {
  return {
    id: 71,
    source: "manual",
    source_label: "직접 작성",
    body: "첫 상담 내용을 정리했어요.",
    occurred_at: "2026-07-23T01:30:00Z",
    created_at: "2026-07-23T01:30:00Z",
    updated_at: "2026-07-23T02:30:00Z",
    edited_at: "2026-07-23T02:30:00Z",
    revision: 2,
    ...overrides,
  };
}

function page(
  results: CustomerMemo[] = [memo()],
  overrides: Partial<PaginatedResult<CustomerMemo>> = {},
): PaginatedResult<CustomerMemo> {
  return { count: results.length, next: null, previous: null, results, ...overrides };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => { resolve = nextResolve; });
  return { promise, resolve };
}

function customer(overrides: Partial<CustomerDetail> = {}): CustomerDetail {
  return {
    id: customerId,
    name: "김인파",
    gender: "1",
    birth_day: "1990-01-01",
    mobile_phone_number: "010-1234-5678",
    consent_overseas_at: null,
    color: null,
    avatar_label: "김",
    tags: [],
    family_count: 0,
    memo_count: 2,
    sales_stage: "meeting",
    status: "active",
    share_token: null,
    created_at: "2026-07-20T00:00:00Z",
    lead_source: "direct",
    last_contacted_at: "2026-07-22T00:00:00Z",
    is_favorite: false,
    is_pinned: false,
    insurance_age: 36,
    job_risk_grade: null,
    marketing_consent: "none",
    personal_info_consent: "none",
    job_code: null,
    job_name: null,
    memo: "호환용 기존 메모",
    is_agree_term: false,
    share_expires_at: null,
    share_sent_at: null,
    user_view_at: null,
    business_card: null,
    updated_at: "2026-07-22T00:00:00Z",
    family_members: [],
    medical_histories: [],
    consents: {
      marketing: { status: "none", subject: null, agreed_at: null },
      personal_info: { status: "none", subject: null, agreed_at: null },
    },
    ...overrides,
  };
}

function profile(): ProfileResponse {
  return {
    email: "planner@inpa.test",
    name: "인파 설계사",
    phone: "010-0000-0000",
    affiliation: "인파 GA",
    agent_type: 1,
    affiliation_type: 2,
    cohort_opt_in: false,
    manager_share_opt_in: false,
    manager_share_level: "none",
    manager_email: null,
    is_manager: false,
    manager_promoted_at: null,
    manager_promotion_seen_at: null,
    managed_agents_count: 0,
    recruiting_enabled: true,
    license_self_declared: true,
    license_no: null,
    career_years: null,
    booking_msg_template: "",
    booking_location: "",
    booking_default_duration: 60,
    booking_buffer_min: 60,
    title: "설계사",
    intro_text: "",
    profile_image: null,
    google_calendar_connected: false,
    google_calendar_mask_name: false,
    has_usable_password: true,
    onboarding_completed_at: "2026-07-01T00:00:00Z",
    marketing_agreed_at: null,
    ref_code: null,
    email_verified_at: "2026-07-01T00:00:00Z",
    is_admin: false,
    is_dormant: false,
  };
}

describe("상담 메모", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCustomerMemos).mockResolvedValue(page());
  });

  it("불러오는 동안 스켈레톤을 보여준 뒤 원본과 시각, 수정 표시를 보여준다", async () => {
    const first = deferred<PaginatedResult<CustomerMemo>>();
    vi.mocked(listCustomerMemos).mockReturnValueOnce(first.promise);
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);

    expect(screen.getAllByLabelText("상담 메모를 불러오는 중").filter((item) => item.tagName === "DIV")).toHaveLength(3);
    first.resolve(page([memo({ source: "legacy_migrated", source_label: "기존 메모", occurred_at: null })]));

    expect(await screen.findByRole("heading", { name: "상담 메모 1개" })).toBeTruthy();
    expect(screen.getByText("기존 메모")).toBeTruthy();
    expect(screen.getByText(/옮긴 시각/)).toBeTruthy();
    expect(screen.getByText(/마지막 수정/)).toBeTruthy();
    expect(screen.getByText(/수정됨/)).toBeTruthy();
  });

  it("빈 목록에는 첫 메모를 남기는 다음 행동을 보여준다", async () => {
    vi.mocked(listCustomerMemos).mockResolvedValue(page([]));
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);

    expect(await screen.findByText("첫 상담 메모를 남겨보세요.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "메모 작성" })).toBeTruthy();
  });

  it("직접·요약·기존 메모의 출처와 Asia/Seoul 시각을 정확히 보여 주고 없는 수정 표시는 숨긴다", async () => {
    vi.mocked(listCustomerMemos).mockResolvedValue(page([
      memo({ id: 73, source: "manual", source_label: "직접 작성", body: "직접", edited_at: null }),
      memo({ id: 72, source: "ai_summary", source_label: "녹음 요약", body: "요약", edited_at: null }),
      memo({ id: 71, source: "legacy_migrated", source_label: "기존 메모", body: "기존", occurred_at: null, created_at: "not-a-date", edited_at: null }),
    ]));
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);

    expect(await screen.findByText("직접 작성")).toBeTruthy();
    expect(screen.getByText("녹음 요약")).toBeTruthy();
    expect(screen.getByText("기존 메모")).toBeTruthy();
    expect(screen.getByText("작성 시각 2026. 7. 23. 오전 10:30")).toBeTruthy();
    expect(screen.getByText("상담 시각 2026. 7. 23. 오전 10:30")).toBeTruthy();
    expect(screen.getByText("옮긴 시각 -")).toBeTruthy();
    expect(screen.queryByText(/수정됨/)).toBeNull();
  });

  it("처음 불러오기에 실패하면 목록 대신 재시도 행동을 보여준다", async () => {
    const user = userEvent.setup();
    vi.mocked(listCustomerMemos)
      .mockRejectedValueOnce(new ApiError(500, "LOAD_FAILED", "메모를 불러오지 못했어요."))
      .mockResolvedValueOnce(page([]));
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "다시 불러오기" }));
    expect(await screen.findByText("첫 상담 메모를 남겨보세요.")).toBeTruthy();
    expect(listCustomerMemos).toHaveBeenCalledTimes(2);
  });

  it("서버의 정확한 전체 개수를 최초 불러오기, 생성, 삭제 때 전달한다", async () => {
    const user = userEvent.setup();
    const onCountChange = vi.fn();
    const existing = memo();
    vi.mocked(listCustomerMemos).mockResolvedValue(page([existing], { count: 4 }));
    vi.mocked(createCustomerMemo).mockResolvedValue(memo({ id: 72, body: "새 메모" }));
    vi.mocked(deleteCustomerMemo).mockResolvedValue(undefined);
    render(<CustomerMemos customerId={customerId} onCountChange={onCountChange} />);

    await screen.findByRole("heading", { name: "상담 메모 4개" });
    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.type(screen.getByLabelText("새 메모"), "새 메모");
    await user.click(screen.getByRole("button", { name: "메모 저장" }));
    await screen.findByText("새 메모");
    await user.click(screen.getByRole("button", { name: "메모 삭제: 첫 상담 내용을 정리했어요." }));
    await user.click(screen.getByRole("button", { name: "삭제할게요" }));

    await waitFor(() => expect(onCountChange.mock.calls.map(([count]) => count)).toEqual([4, 5, 4]));
  });

  it("새 메모는 빈 내용과 1만 자 초과를 저장하지 않고 안내한다", async () => {
    const user = userEvent.setup();
    vi.mocked(listCustomerMemos).mockResolvedValue(page([]));
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);
    await screen.findByText("첫 상담 메모를 남겨보세요.");
    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.click(screen.getByRole("button", { name: "메모 저장" }));
    expect(await screen.findByText("메모 내용을 입력해 주세요.")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("새 메모"), { target: { value: "가".repeat(10_001) } });
    expect(screen.getByText("10,001 / 10,000자")).toBeTruthy();
    expect(screen.getByRole("button", { name: "다시 저장" })).toBeDisabled();
    expect(createCustomerMemo).not.toHaveBeenCalled();
  });

  it("새 메모 저장 실패 뒤 작성 중인 내용을 보존하고 다시 저장할 수 있다", async () => {
    const user = userEvent.setup();
    vi.mocked(listCustomerMemos).mockResolvedValue(page([]));
    vi.mocked(createCustomerMemo)
      .mockRejectedValueOnce(new ApiError(500, "SAVE_FAILED", "저장에 실패했어요."))
      .mockResolvedValueOnce(memo({ id: 72, body: "저장할 내용" }));
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);
    await screen.findByText("첫 상담 메모를 남겨보세요.");
    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.type(screen.getByLabelText("새 메모"), "저장할 내용");
    await user.click(screen.getByRole("button", { name: "메모 저장" }));

    expect(await screen.findByText("저장에 실패했어요.")).toBeTruthy();
    expect(screen.getByLabelText("새 메모")).toHaveValue("저장할 내용");
    await user.click(screen.getByRole("button", { name: "다시 저장" }));
    expect(await screen.findByText("저장할 내용")).toBeTruthy();
  });

  it("저장 중에는 새 메모를 한 번만 요청하고 접근 가능한 상태를 알린다", async () => {
    const user = userEvent.setup();
    const saving = deferred<CustomerMemo>();
    vi.mocked(listCustomerMemos).mockResolvedValue(page([]));
    vi.mocked(createCustomerMemo).mockReturnValueOnce(saving.promise);
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);
    await screen.findByText("첫 상담 메모를 남겨보세요.");
    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.type(screen.getByLabelText("새 메모"), "중복 저장 방지");
    await user.dblClick(screen.getByRole("button", { name: "메모 저장" }));

    expect(createCustomerMemo).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("메모를 저장하고 있어요"));
    saving.resolve(memo({ id: 73, body: "중복 저장 방지" }));
    expect(await screen.findByText("중복 저장 방지")).toBeTruthy();
  });

  it("수정하지 않은 메모는 요청하지 않고, 변경 저장은 카드에 반영한다", async () => {
    const user = userEvent.setup();
    const original = memo();
    vi.mocked(updateCustomerMemo).mockResolvedValue(memo({ body: "수정한 상담 내용", revision: 3 }));
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);
    await screen.findByText(original.body);
    await user.click(screen.getByRole("button", { name: "메모 수정: 첫 상담 내용을 정리했어요." }));
    await user.click(screen.getByRole("button", { name: "수정 저장" }));
    expect(updateCustomerMemo).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "메모 수정: 첫 상담 내용을 정리했어요." }));
    await user.clear(screen.getByLabelText("메모 수정"));
    await user.type(screen.getByLabelText("메모 수정"), "수정한 상담 내용");
    await user.click(screen.getByRole("button", { name: "수정 저장" }));
    expect(await screen.findByText("수정한 상담 내용")).toBeTruthy();
    expect(updateCustomerMemo).toHaveBeenCalledWith(customerId, original, "수정한 상담 내용");
  });

  it("수정 저장 실패에도 입력한 초안을 보존한다", async () => {
    const user = userEvent.setup();
    vi.mocked(updateCustomerMemo).mockRejectedValue(new ApiError(500, "SAVE_FAILED", "수정 저장에 실패했어요."));
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);
    await screen.findByText("첫 상담 내용을 정리했어요.");
    await user.click(screen.getByRole("button", { name: "메모 수정: 첫 상담 내용을 정리했어요." }));
    await user.clear(screen.getByLabelText("메모 수정"));
    await user.type(screen.getByLabelText("메모 수정"), "남겨 둘 초안");
    await user.click(screen.getByRole("button", { name: "수정 저장" }));

    expect(await screen.findByText("수정 저장에 실패했어요.")).toBeTruthy();
    expect(screen.getByLabelText("메모 수정")).toHaveValue("남겨 둘 초안");
  });

  it("다른 화면의 수정이 있으면 최신 메모를 다시 읽고 내 초안을 보존한다", async () => {
    const user = userEvent.setup();
    const oldMemo = memo({ body: "이전 내용", revision: 2 });
    const latestMemo = memo({ body: "다른 화면의 최신 내용", revision: 3 });
    vi.mocked(listCustomerMemos)
      .mockResolvedValueOnce(page([oldMemo]))
      .mockResolvedValueOnce(page([latestMemo]));
    vi.mocked(updateCustomerMemo).mockRejectedValue(
      new ApiError(409, "MEMO_EDIT_CONFLICT", "다른 화면에서 수정된 메모예요. 최신 내용을 확인해 주세요."),
    );
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);
    await screen.findByText("이전 내용");
    await user.click(screen.getByRole("button", { name: "메모 수정: 이전 내용" }));
    await user.clear(screen.getByLabelText("메모 수정"));
    await user.type(screen.getByLabelText("메모 수정"), "내가 남긴 초안");
    await user.click(screen.getByRole("button", { name: "수정 저장" }));

    expect(await screen.findByText(/다른 화면의 최신 내용/)).toBeTruthy();
    expect(screen.getByLabelText("메모 수정")).toHaveValue("내가 남긴 초안");
    expect(screen.getByText("내가 작성한 내용은 그대로 남아 있어요. 최신 내용을 확인한 뒤 다시 저장해 주세요.")).toBeTruthy();
  });

  it("삭제 확인을 취소하면 카드를 유지하고, 실패해도 다시 시도할 수 있게 한다", async () => {
    const user = userEvent.setup();
    vi.mocked(deleteCustomerMemo).mockRejectedValueOnce(new ApiError(500, "DELETE_FAILED", "삭제에 실패했어요."));
    render(<CustomerMemos customerId={customerId} onCountChange={vi.fn()} />);
    await screen.findByText("첫 상담 내용을 정리했어요.");
    const deleteButton = screen.getByRole("button", { name: "메모 삭제: 첫 상담 내용을 정리했어요." });
    await user.click(deleteButton);
    await user.click(screen.getByRole("button", { name: "그대로 둘게요" }));
    expect(deleteCustomerMemo).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(deleteButton);

    await user.click(deleteButton);
    await user.click(screen.getByRole("button", { name: "삭제할게요" }));
    expect(await screen.findByText("삭제에 실패했어요.")).toBeTruthy();
    expect(screen.getByText("첫 상담 내용을 정리했어요.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "삭제 다시 시도" }));
    expect(deleteCustomerMemo).toHaveBeenCalledTimes(2);
  });

  it("다음 페이지는 서버 순서대로 한 번만 합치고 전체 개수는 유지한다", async () => {
    const user = userEvent.setup();
    const first = page([memo({ id: 3, body: "세 번째" }), memo({ id: 2, body: "두 번째" })], { count: 3, next: "https://api.example/memos/?page=2" });
    const secondRequest = deferred<PaginatedResult<CustomerMemo>>();
    vi.mocked(listCustomerMemos)
      .mockResolvedValueOnce(first)
      .mockReturnValueOnce(secondRequest.promise);
    const onCountChange = vi.fn();
    render(<CustomerMemos customerId={customerId} onCountChange={onCountChange} />);
    await screen.findByText("세 번째");
    const more = screen.getByRole("button", { name: "이전 메모 더 보기" });
    await user.dblClick(more);
    expect(listCustomerMemos).toHaveBeenCalledTimes(2);
    secondRequest.resolve(page([memo({ id: 1, body: "첫 번째" })], { count: 3, previous: "https://api.example/memos/?page=1" }));

    expect(await screen.findByText("첫 번째")).toBeTruthy();
    expect(screen.getAllByRole("article").map((item) => item.textContent).join(" ")).toMatch(/세 번째.*두 번째.*첫 번째/);
    expect(onCountChange.mock.calls.map(([count]) => count)).toEqual([3, 3]);
  });

  it("고객이나 요청 세대가 바뀐 뒤 늦게 온 목록을 반영하지 않고, 콜백 변경만으로 다시 읽지 않는다", async () => {
    const first = deferred<PaginatedResult<CustomerMemo>>();
    vi.mocked(listCustomerMemos)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(page([memo({ id: 72, body: "새 고객 메모" })]));
    const firstCallback = vi.fn();
    const view = render(<CustomerMemos customerId={customerId} onCountChange={firstCallback} />);
    view.rerender(<CustomerMemos customerId={32} onCountChange={vi.fn()} />);
    expect(await screen.findByText("새 고객 메모")).toBeTruthy();
    view.rerender(<CustomerMemos customerId={32} onCountChange={vi.fn()} />);
    expect(listCustomerMemos).toHaveBeenCalledTimes(2);

    first.resolve(page([memo({ body: "늦은 이전 고객 메모" })]));
    await waitFor(() => expect(screen.queryByText("늦은 이전 고객 메모")).toBeNull());
  });
});

describe("고객 상세 기록 통합", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigation.reset();
    vi.mocked(getCustomer).mockResolvedValue(customer());
    vi.mocked(getProfile).mockResolvedValue(profile());
    vi.mocked(listContactLogs).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    vi.mocked(listCustomerMemos).mockResolvedValue(page([
      memo({ id: 72, body: "두 번째 상담" }),
      memo({ id: 71, body: "첫 번째 상담" }),
    ], { count: 2 }));
    vi.mocked(getCustomerHistory).mockResolvedValue({
      events: [
        { type: "created", label: "고객 등록", at: "2026-07-20T00:00:00Z", meta: {} },
        { type: "share_view", label: "공유 화면 열람", at: "2026-07-21T00:00:00Z", meta: {} },
      ],
    });
    vi.mocked(createCustomerMemo).mockResolvedValue(memo({ id: 73, body: "새 상담 메모" }));
    vi.mocked(deleteCustomerMemo).mockResolvedValue(undefined);
  });

  it("정보 화면의 단일 메모 편집기를 없애고 기록 탭과 정확한 요약 링크를 제공한다", async () => {
    render(<CustomerDetailPage />);

    expect(await screen.findByText("김인파")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "기록" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "메모 저장" })).toBeNull();
    expect(screen.queryByPlaceholderText("상담 내용·특이사항·다음 액션을 적어두세요.")).toBeNull();
    expect(screen.getByRole("link", { name: "메모 2개" })).toHaveAttribute(
      "href",
      "/customer/31?tab=history&view=memos",
    );
    expect(screen.getByRole("heading", { name: "상세정보" }).parentElement?.parentElement)
      .toHaveClass("p-4");
  });

  it("내부 보기를 URL과 키보드로 바꾸고 뒤로 가기 뒤에도 메모 초안과 활동 상태를 보존한다", async () => {
    const user = userEvent.setup();
    navigation.reset("tab=history&view=memos&campaign=summer");
    render(<CustomerDetailPage />);

    await screen.findByRole("heading", { name: "상담 메모 2개" });
    const memoTab = screen.getByRole("tab", { name: "메모 2개" });
    const activityTab = screen.getByRole("tab", { name: "활동" });
    expect(memoTab).toHaveAttribute("aria-controls", "customer-history-panel-memos");
    expect(document.getElementById("customer-history-panel-memos")).not.toBeNull();
    expect(document.getElementById("customer-history-panel-activity")).not.toBeNull();
    expect(document.getElementById("customer-history-panel-activity")).toHaveAttribute("hidden");
    expect(activityTab).toHaveAttribute("tabindex", "-1");
    expect(getCustomerHistory).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.type(screen.getByLabelText("새 메모"), "작성 중인 초안");
    memoTab.focus();
    await user.keyboard("{ArrowRight}");

    await screen.findByRole("heading", { name: "접점 이력 2건" });
    expect(document.activeElement).toBe(activityTab);
    expect(navigation.current()).toBe("/customer/31?tab=history&view=activity&campaign=summer");
    expect(getCustomerHistory).toHaveBeenCalledOnce();

    act(() => navigation.back());
    await waitFor(() => expect(screen.getByRole("tab", { name: "메모 2개" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByLabelText("새 메모")).toHaveValue("작성 중인 초안");
    expect(listCustomerMemos).toHaveBeenCalledOnce();
    expect(getCustomerHistory).toHaveBeenCalledOnce();
  });

  it("잘못된 보기 값은 메모 0건으로 열고 뒤로·앞으로 가도 초안과 방문별 요청을 보존한다", async () => {
    const user = userEvent.setup();
    navigation.reset("tab=history&view=invalid&campaign=winter");
    vi.mocked(getCustomer).mockResolvedValue(customer({ memo_count: 0 }));
    vi.mocked(listCustomerMemos).mockResolvedValue(page([], { count: 0 }));
    render(<CustomerDetailPage />);

    await screen.findByRole("heading", { name: "상담 메모 0개" });
    expect(screen.getByRole("link", { name: "메모 0개" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "메모 0개" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "활동" })).toHaveAttribute("aria-selected", "false");

    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.type(screen.getByLabelText("새 메모"), "0건에서 작성 중");
    await user.click(screen.getByRole("tab", { name: "활동" }));
    await screen.findByRole("heading", { name: "접점 이력 2건" });

    act(() => navigation.back());
    await waitFor(() => expect(screen.getByRole("tab", { name: "메모 0개" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByLabelText("새 메모")).toHaveValue("0건에서 작성 중");

    act(() => navigation.forward());
    await waitFor(() => expect(screen.getByRole("tab", { name: "활동" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByLabelText("새 메모")).toHaveValue("0건에서 작성 중");
    expect(navigation.current()).toBe("/customer/31?tab=history&view=activity&campaign=winter");
    expect(listCustomerMemos).toHaveBeenCalledOnce();
    expect(getCustomerHistory).toHaveBeenCalledOnce();
  });

  it("서버 최초 개수와 생성·삭제 결과를 요약과 내부 탭에 함께 반영한다", async () => {
    const user = userEvent.setup();
    navigation.reset("tab=history&view=memos");
    vi.mocked(listCustomerMemos).mockResolvedValue(page([
      memo({ id: 72, body: "두 번째 상담" }),
      memo({ id: 71, body: "첫 번째 상담" }),
    ], { count: 4 }));
    render(<CustomerDetailPage />);

    await screen.findByRole("heading", { name: "상담 메모 4개" });
    expect(screen.getByRole("tab", { name: "메모 4개" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "메모 4개" })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "메모 작성" }));
    await user.type(screen.getByLabelText("새 메모"), "새 상담 메모");
    await user.click(screen.getByRole("button", { name: "메모 저장" }));
    expect(await screen.findByRole("tab", { name: "메모 5개" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "메모 5개" })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "메모 삭제: 새 상담 메모" }));
    await user.click(screen.getByRole("button", { name: "삭제할게요" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "메모 4개" })).toBeTruthy());
    expect(screen.getByRole("link", { name: "메모 4개" })).toBeTruthy();
    expect(listCustomerMemos).toHaveBeenCalledOnce();
  });

  it("활동 이력의 순서와 표시를 유지하고 다른 보기 왕복에도 다시 요청하지 않는다", async () => {
    const user = userEvent.setup();
    navigation.reset("tab=history&view=activity");
    render(<CustomerDetailPage />);

    const activityPanel = await screen.findByRole("tabpanel", { name: "활동" });
    expect(within(activityPanel).getAllByRole("listitem").map((item) => item.textContent))
      .toEqual([expect.stringContaining("고객 등록"), expect.stringContaining("공유 화면 열람")]);
    expect(getCustomerHistory).toHaveBeenCalledOnce();
    expect(listCustomerMemos).not.toHaveBeenCalled();

    await user.click(screen.getByRole("tab", { name: "메모 2개" }));
    await screen.findByRole("heading", { name: "상담 메모 2개" });
    await user.click(screen.getByRole("tab", { name: "활동" }));
    expect(await screen.findByRole("heading", { name: "접점 이력 2건" })).toBeTruthy();
    expect(getCustomerHistory).toHaveBeenCalledOnce();
    expect(listCustomerMemos).toHaveBeenCalledOnce();
  });
});
