import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ScriptsPage from "@/app/scripts/page";
import {
  ApiError,
  createPersonalTalkTemplate,
  deletePersonalTalkTemplate,
  getProfile,
  listPersonalTalkTemplates,
  putTalkTemplatePreference,
  updatePersonalTalkTemplate,
  type PersonalTalkTemplate,
  type PersonalTalkTemplatePayload,
  type ProfileResponse,
} from "@/lib/api";

vi.mock("@/lib/useAuthGuard", () => ({
  useAuthGuard: () => true,
}));

vi.mock("@/components/app-nav", () => ({
  AppNav: () => <nav aria-label="앱 메뉴" />,
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getProfile: vi.fn(),
  listPersonalTalkTemplates: vi.fn(),
  createPersonalTalkTemplate: vi.fn(),
  updatePersonalTalkTemplate: vi.fn(),
  deletePersonalTalkTemplate: vi.fn(),
  putTalkTemplatePreference: vi.fn(),
}));

const mockedGetProfile = vi.mocked(getProfile);
const mockedList = vi.mocked(listPersonalTalkTemplates);
const mockedCreate = vi.mocked(createPersonalTalkTemplate);
const mockedUpdate = vi.mocked(updatePersonalTalkTemplate);
const mockedDelete = vi.mocked(deletePersonalTalkTemplate);
const mockedPreference = vi.mocked(putTalkTemplatePreference);

const profile = {
  name: "황예진",
  affiliation: "인파지점",
  title: "팀장",
  phone: "010-9876-5432",
} as ProfileResponse;

function personal(
  id = 7,
  overrides: Partial<PersonalTalkTemplate> = {},
): PersonalTalkTemplate {
  return {
    id,
    owner: 1,
    source_key: null,
    title: "내 후속 문구",
    body: "{고객명} 고객님, 내 문구를 확인할까요?",
    category: "referral",
    channel: "message",
    sort_order: 1,
    is_active: true,
    is_deleted: false,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
    ...overrides,
  };
}

function articleFor(title: string): HTMLElement {
  const heading = screen.getByRole("heading", { name: title });
  const article = heading.closest("article");
  if (!article) throw new Error(`${title} card is not an article`);
  return article;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

beforeEach(() => {
  window.history.replaceState({}, "", "/scripts");
  mockedGetProfile.mockReset();
  mockedList.mockReset();
  mockedCreate.mockReset();
  mockedUpdate.mockReset();
  mockedDelete.mockReset();
  mockedPreference.mockReset();
  mockedGetProfile.mockResolvedValue(profile);
  mockedList.mockResolvedValue({
    results: [personal()],
    hidden_source_keys: [],
  });
  mockedPreference.mockImplementation(async (payload) => payload);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  Object.defineProperty(navigator, "share", {
    configurable: true,
    value: undefined,
  });
});

describe("/scripts page state", () => {
  it("loads defaults and personal rows while keeping profile fields read-only and customer local", async () => {
    render(<ScriptsPage />);

    expect(
      await screen.findByRole("heading", { name: "내 후속 문구" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "관리 후 소개 부탁" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("내 이름")).toHaveValue("황예진");
    expect(screen.getByLabelText("내 이름")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("내 전화번호")).toHaveValue(
      "010-9876-5432",
    );
    expect(screen.getByLabelText("내 전화번호")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("고객 이름 (이 화면에서만)"))
      .not.toHaveAttribute("readonly");
    expect(screen.getByRole("link", { name: "계정 설정에서 바꾸기" }))
      .toHaveAttribute("href", "/settings/account");
  });

  it("does not subtract unknown hidden keys from the visible default count", async () => {
    mockedList.mockResolvedValue({
      results: [personal()],
      hidden_source_keys: ["retired-default-key"],
    });

    render(<ScriptsPage />);

    await screen.findByRole("heading", { name: "내 후속 문구" });
    expect(
      screen.getByText(
        "기본 화법 30개와 나만의 화법 1개를 함께 볼 수 있어요.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "숨긴 기본 화법" }),
    ).not.toBeInTheDocument();
  });

  it("keeps defaults usable when personal loading fails and retries without losing them", async () => {
    mockedList
      .mockRejectedValueOnce(new ApiError(503, "unavailable", "잠시 연결이 끊겼어요."))
      .mockResolvedValueOnce({
        results: [personal()],
        hidden_source_keys: [],
      });
    const user = userEvent.setup();
    render(<ScriptsPage />);

    expect(
      await screen.findByRole("heading", { name: "관리 후 소개 부탁" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "나만의 화법 연결이 잠시 끊겼어요",
    );

    await user.click(screen.getByRole("button", { name: "나만의 화법 다시 불러오기" }));

    expect(
      await screen.findByRole("heading", { name: "내 후속 문구" }),
    ).toBeInTheDocument();
    expect(mockedList).toHaveBeenCalledTimes(2);
  });

  it("filters all, personal, and default templates with accessible selected state", async () => {
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "내 후속 문구" });

    const personalFilter = screen.getByRole("button", { name: "나만의 화법" });
    await user.click(personalFilter);
    expect(personalFilter).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "내 후속 문구" }))
      .toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "관리 후 소개 부탁" }))
      .not.toBeInTheDocument();

    const defaultFilter = screen.getByRole("button", { name: "기본 화법" });
    await user.click(defaultFilter);
    expect(defaultFilter).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("heading", { name: "내 후속 문구" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "관리 후 소개 부탁" }))
      .toBeInTheDocument();
  });

  it("hides a default only after success and restores it from the visible recovery area", async () => {
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "내 후속 문구" });

    await user.click(
      within(articleFor("관리 후 소개 부탁")).getByRole("button", {
        name: "관리 후 소개 부탁 관리 메뉴",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: "내 목록에서 숨기기" }));

    expect(mockedPreference).toHaveBeenCalledWith({
      source_key: "referral-thanks",
      is_hidden: true,
    });
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "관리 후 소개 부탁" }))
        .not.toBeInTheDocument(),
    );
    const recovery = screen.getByRole("region", { name: "숨긴 기본 화법" });
    expect(within(recovery).getByText("관리 후 소개 부탁")).toBeInTheDocument();

    await user.click(
      within(recovery).getByRole("button", { name: "기본값으로 되돌리기" }),
    );

    expect(mockedPreference).toHaveBeenLastCalledWith({
      source_key: "referral-thanks",
      is_hidden: false,
    });
    expect(
      await screen.findByRole("heading", { name: "관리 후 소개 부탁" }),
    ).toBeInTheDocument();
  });

  it("creates, edits, and duplicates personal templates through the editor", async () => {
    mockedCreate.mockImplementation(async (payload: PersonalTalkTemplatePayload) =>
      personal(21, { ...payload }),
    );
    mockedUpdate.mockImplementation(async (id, payload) =>
      personal(id, { ...payload }),
    );
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "내 후속 문구" });

    await user.click(screen.getByRole("button", { name: "나만의 화법 추가" }));
    await user.type(screen.getByLabelText("제목"), "새 문구");
    fireEvent.change(screen.getByLabelText("본문"), {
      target: { value: "{고객명} 고객님, 새 문구를 확인할까요?" },
    });
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(
      await screen.findByRole("heading", { name: "새 문구" }),
    ).toBeInTheDocument();

    await user.click(
      within(articleFor("내 후속 문구")).getByRole("button", {
        name: "내 후속 문구 관리 메뉴",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: "수정" }));
    await user.clear(screen.getByLabelText("제목"));
    await user.type(screen.getByLabelText("제목"), "수정한 문구");
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(mockedUpdate).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ title: "수정한 문구" }),
    );
    expect(
      await screen.findByRole("heading", { name: "수정한 문구" }),
    ).toBeInTheDocument();

    await user.click(
      within(articleFor("수정한 문구")).getByRole("button", {
        name: "수정한 문구 관리 메뉴",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: "복제" }));
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(mockedCreate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        title: "수정한 문구 복사본",
        source_key: null,
      }),
    );
  });

  it("returns focus to the real card management button after closing an editor opened from its menu", async () => {
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "내 후속 문구" });
    const managementButton = within(articleFor("내 후속 문구")).getByRole(
      "button",
      { name: "내 후속 문구 관리 메뉴" },
    );

    await user.click(managementButton);
    await user.click(screen.getByRole("menuitem", { name: "수정" }));
    expect(
      await screen.findByRole("dialog", { name: "나만의 화법 수정" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "취소" }));

    await waitFor(() => expect(managementButton).toHaveFocus());
  });

  it("supports arrow, Home, End, and Escape keys in the card management menu", async () => {
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "내 후속 문구" });
    const managementButton = within(articleFor("내 후속 문구")).getByRole(
      "button",
      { name: "내 후속 문구 관리 메뉴" },
    );
    managementButton.focus();

    fireEvent.keyDown(managementButton, { key: "ArrowDown" });
    const edit = await screen.findByRole("menuitem", { name: "수정" });
    const duplicate = screen.getByRole("menuitem", { name: "복제" });
    const remove = screen.getByRole("menuitem", { name: "삭제" });
    await waitFor(() => expect(edit).toHaveFocus());

    fireEvent.keyDown(edit, { key: "ArrowDown" });
    expect(duplicate).toHaveFocus();
    fireEvent.keyDown(duplicate, { key: "End" });
    expect(remove).toHaveFocus();
    fireEvent.keyDown(remove, { key: "Home" });
    expect(edit).toHaveFocus();
    fireEvent.keyDown(edit, { key: "ArrowUp" });
    expect(remove).toHaveFocus();
    fireEvent.keyDown(remove, { key: "Escape" });

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(managementButton).toHaveFocus();
  });

  it("does not let an older initial list response remove a newly created personal template", async () => {
    const initialList = deferred<{
      results: PersonalTalkTemplate[];
      hidden_source_keys: string[];
    }>();
    mockedList.mockReturnValue(initialList.promise);
    mockedCreate.mockImplementation(async (payload) =>
      personal(41, { ...payload, title: "방금 만든 화법" }),
    );
    const user = userEvent.setup();
    render(<ScriptsPage />);

    await user.click(screen.getByRole("button", { name: "나만의 화법 추가" }));
    await user.type(screen.getByLabelText("제목"), "방금 만든 화법");
    fireEvent.change(screen.getByLabelText("본문"), {
      target: { value: "{고객명} 고객님, 다음 내용을 확인할까요?" },
    });
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(
      await screen.findByRole("heading", { name: "방금 만든 화법" }),
    ).toBeInTheDocument();

    await act(async () => {
      initialList.resolve({ results: [], hidden_source_keys: [] });
    });

    expect(
      screen.getByRole("heading", { name: "방금 만든 화법" }),
    ).toBeInTheDocument();
  });

  it("does not let an older list response undo a successful default hide preference", async () => {
    const initialList = deferred<{
      results: PersonalTalkTemplate[];
      hidden_source_keys: string[];
    }>();
    mockedList.mockReturnValue(initialList.promise);
    const user = userEvent.setup();
    render(<ScriptsPage />);

    await user.click(
      within(articleFor("관리 후 소개 부탁")).getByRole("button", {
        name: "관리 후 소개 부탁 관리 메뉴",
      }),
    );
    await user.click(
      screen.getByRole("menuitem", { name: "내 목록에서 숨기기" }),
    );
    expect(
      await screen.findByRole("region", { name: "숨긴 기본 화법" }),
    ).toBeInTheDocument();

    await act(async () => {
      initialList.resolve({ results: [], hidden_source_keys: [] });
    });

    expect(screen.queryByRole("heading", { name: "관리 후 소개 부탁" }))
      .not.toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "숨긴 기본 화법" }),
    ).toBeInTheDocument();
  });

  it("keeps a personal template visible when deletion fails", async () => {
    mockedDelete.mockRejectedValue(
      new ApiError(500, "server_error", "삭제 요청을 마치지 못했어요."),
    );
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "내 후속 문구" });

    await user.click(
      within(articleFor("내 후속 문구")).getByRole("button", {
        name: "내 후속 문구 관리 메뉴",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: "삭제" }));

    expect(window.confirm).toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "삭제 요청이 중단됐어요. 내 문구는 그대로 남아 있어요.",
    );
    expect(screen.getByRole("heading", { name: "내 후속 문구" }))
      .toBeInTheDocument();
  });

  it("disables only the personal template whose delete is pending", async () => {
    mockedList.mockResolvedValue({
      results: [
        personal(2, { title: "두 번째 문구" }),
        personal(12, { title: "열두 번째 문구" }),
      ],
      hidden_source_keys: [],
    });
    mockedDelete.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "열두 번째 문구" });

    await user.click(
      within(articleFor("열두 번째 문구")).getByRole("button", {
        name: "열두 번째 문구 관리 메뉴",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: "삭제" }));
    expect(mockedDelete).toHaveBeenCalledWith(12);

    await user.click(
      within(articleFor("두 번째 문구")).getByRole("button", {
        name: "두 번째 문구 관리 메뉴",
      }),
    );
    expect(screen.getByRole("menuitem", { name: "삭제" })).toBeEnabled();
  });

  it("refreshes personal data when another tab already removed a row", async () => {
    mockedList
      .mockResolvedValueOnce({
        results: [personal()],
        hidden_source_keys: [],
      })
      .mockResolvedValueOnce({
        results: [],
        hidden_source_keys: [],
      });
    mockedDelete.mockRejectedValue(
      new ApiError(404, "not_found", "이미 삭제된 화법입니다."),
    );
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "내 후속 문구" });

    await user.click(
      within(articleFor("내 후속 문구")).getByRole("button", {
        name: "내 후속 문구 관리 메뉴",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: "삭제" }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "내 후속 문구" }))
        .not.toBeInTheDocument(),
    );
    expect(mockedList).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status")).toHaveTextContent(
      "최신 나만의 화법 목록을 불러왔어요.",
    );
  });

  it("keeps the editor and draft open when a 404 refresh also fails", async () => {
    mockedList
      .mockResolvedValueOnce({
        results: [personal()],
        hidden_source_keys: [],
      })
      .mockRejectedValueOnce(
        new ApiError(503, "unavailable", "목록 연결이 중단됐어요."),
      );
    mockedUpdate.mockRejectedValue(
      new ApiError(404, "not_found", "다른 탭에서 삭제된 화법입니다."),
    );
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "내 후속 문구" });
    await user.click(
      within(articleFor("내 후속 문구")).getByRole("button", {
        name: "내 후속 문구 관리 메뉴",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: "수정" }));
    await user.clear(screen.getByLabelText("제목"));
    await user.type(screen.getByLabelText("제목"), "보존할 수정 문구");

    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(
      await screen.findByRole("dialog", { name: "나만의 화법 수정" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("제목")).toHaveValue("보존할 수정 문구");
    expect(screen.getByText(
      "최신 목록 연결이 중단됐어요. 입력한 내용은 그대로 두었으니 다시 불러온 뒤 저장해 주세요.",
    )).toBeInTheDocument();
    expect(screen.getByRole("status")).not.toHaveTextContent(
      "최신 나만의 화법 목록을 불러왔어요.",
    );
  });

  it("keeps a stale personal row and reports refresh failure after delete returns 404", async () => {
    mockedList
      .mockResolvedValueOnce({
        results: [personal()],
        hidden_source_keys: [],
      })
      .mockRejectedValueOnce(
        new ApiError(503, "unavailable", "목록 연결이 중단됐어요."),
      );
    mockedDelete.mockRejectedValue(
      new ApiError(404, "not_found", "다른 탭에서 삭제된 화법입니다."),
    );
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "내 후속 문구" });
    await user.click(
      within(articleFor("내 후속 문구")).getByRole("button", {
        name: "내 후속 문구 관리 메뉴",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: "삭제" }));

    expect(await screen.findByText(
      "최신 목록 연결이 중단됐어요. 내 화법은 목록에 그대로 있어요. 다시 불러와 확인해 주세요.",
    )).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "내 후속 문구" }))
      .toBeInTheDocument();
    expect(screen.getByRole("status")).not.toHaveTextContent(
      "최신 나만의 화법 목록을 불러왔어요.",
    );
  });

  it("gates advertising share until profile phone and local opt-out information exist", async () => {
    mockedGetProfile.mockResolvedValue({ ...profile, phone: "" });
    mockedList.mockResolvedValue({ results: [], hidden_source_keys: [] });
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "보장 정리 안내 문자" });
    const adCard = articleFor("보장 정리 안내 문자");

    await user.click(within(adCard).getByRole("button", { name: "공유" }));

    expect(screen.getByRole("button", { name: "문구 복사" })).toBeDisabled();
    expect(screen.getByText(/내 전화번호를 저장하고/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "계정 설정 열기" }))
      .toHaveAttribute("href", "/settings/account");
  });

  it("enables advertising copy after real profile phone and local opt-out input are present", async () => {
    mockedList.mockResolvedValue({ results: [], hidden_source_keys: [] });
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "보장 정리 안내 문자" });

    await user.type(
      screen.getByLabelText("수신거부 안내 (광고 문구에만)"),
      "이 번호로 거부 의사를 알려 주세요",
    );
    await user.click(
      within(articleFor("보장 정리 안내 문자")).getByRole("button", {
        name: "공유",
      }),
    );

    expect(screen.getByRole("button", { name: "문구 복사" })).toBeEnabled();
    const finalMessage = (
      screen.getByLabelText("최종 공유 문구") as HTMLTextAreaElement
    ).value;
    expect(finalMessage).toContain("문의: 010-9876-5432");
    expect(finalMessage).toContain(
      "수신거부: 이 번호로 거부 의사를 알려 주세요",
    );
  });

  it("blocks a personal advertising-source template whose body lost required variables", async () => {
    mockedList.mockResolvedValue({
      results: [
        personal(31, {
          source_key: "as-event-sms",
          title: "내 광고 안내",
          body: "{고객명} 고객님, 새 소식을 확인할까요?",
          category: "aftercare",
        }),
      ],
      hidden_source_keys: [],
    });
    const user = userEvent.setup();
    render(<ScriptsPage />);
    await screen.findByRole("heading", { name: "내 광고 안내" });
    await user.type(
      screen.getByLabelText("수신거부 안내 (광고 문구에만)"),
      "이 번호로 거부 의사를 알려 주세요",
    );

    await user.click(
      within(articleFor("내 광고 안내")).getByRole("button", {
        name: "공유",
      }),
    );

    expect(screen.getByRole("button", { name: "문구 복사" })).toBeDisabled();
    expect(screen.getByText(
      "광고 화법 본문에 {설계사연락처}, {수신거부안내} 변수를 다시 넣어 주세요.",
    )).toBeInTheDocument();
  });
});
