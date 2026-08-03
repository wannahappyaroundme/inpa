import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const adminApi = vi.hoisted(() => ({
  adminGetBlogPost: vi.fn(),
  adminCreateBlogPost: vi.fn(),
  adminUpdateBlogPost: vi.fn(),
  adminRecordBlogLegalReview: vi.fn(),
  uploadBlogCover: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/adminApi", () => adminApi);
vi.mock("@/lib/api", () => ({
  BLOG_CATEGORIES: [{ code: "safety", label: "안심 가이드" }],
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));
vi.mock("@/components/blog-markdown", () => ({
  BlogMarkdown: ({ body }: { body: string }) => <div>{body}</div>,
}));

import { BlogEditor } from "@/components/blog-editor";

const oldDigest = "a".repeat(64);
const savedDigest = "b".repeat(64);

function legalPost(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    title: "검토 글",
    slug: "검토-글",
    body: "기존 본문",
    excerpt: "요약",
    cover_image: null,
    cover_asset_path: "/blog-assets/검토-글/cover.webp",
    category: "safety",
    category_label: "안심 가이드",
    tags: "계약 변경",
    tags_list: ["계약 변경"],
    is_published: true,
    review_gate: "legal",
    legal_review_required: true,
    legal_review: {
      reviewer: "이전 검토자",
      credential: "대한민국 변호사",
      reviewed_at: "2026-08-03T01:00:00Z",
      reference: "이전 기록",
    },
    review_content_digest: oldDigest,
    legal_review_is_current: true,
    published_at: "2026-08-03T01:00:00Z",
    seo_title: "",
    seo_description: "",
    is_noindex: false,
    view_count: 0,
    author_name: "인파 담당자",
    author_email: "admin@inpa.kr",
    created_at: "2026-08-03T01:00:00Z",
    updated_at: "2026-08-03T01:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("confirm", vi.fn(() => true));
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:cover"),
    revokeObjectURL: vi.fn(),
  });
});

it("수정 저장과 새 법률 검토 확인을 서로 다른 행동으로 유지한다", async () => {
  const user = userEvent.setup();
  adminApi.adminGetBlogPost.mockResolvedValue(legalPost());
  adminApi.adminUpdateBlogPost.mockResolvedValue(legalPost({
    body: "새 본문",
    is_published: false,
    legal_review: null,
    review_content_digest: savedDigest,
  }));
  adminApi.adminRecordBlogLegalReview.mockResolvedValue(legalPost({
    body: "새 본문",
    review_content_digest: savedDigest,
    legal_review: {
      reviewer: "새 검토자",
      credential: "대한민국 변호사",
      reviewed_at: "2026-08-03T02:00:00Z",
      reference: "새 기록",
    },
  }));

  render(<BlogEditor postId={7} />);
  const body = await screen.findByPlaceholderText(/마크다운으로 본문을 작성하세요/);
  await user.clear(body);
  await user.type(body, "새 본문");
  await user.click(screen.getByRole("button", { name: "수정 임시저장" }));

  await waitFor(() => expect(adminApi.adminUpdateBlogPost).toHaveBeenCalledTimes(1));
  expect(adminApi.adminRecordBlogLegalReview).not.toHaveBeenCalled();
  expect(screen.getByLabelText("검토 확인 시각")).toHaveValue("");
  expect(screen.getByLabelText("검토 담당자")).toHaveValue("");

  await user.type(screen.getByLabelText("검토 담당자"), "새 검토자");
  await user.type(screen.getByLabelText("검토 자격"), "대한민국 변호사");
  await user.type(screen.getByLabelText("검토 근거"), "새 기록");
  await user.click(screen.getByRole("button", { name: "현재 저장본 검토 확인·게시" }));

  await waitFor(() => expect(adminApi.adminRecordBlogLegalReview).toHaveBeenCalledWith(7, {
    reviewer: "새 검토자",
    credential: "대한민국 변호사",
    reference: "새 기록",
    content_digest: savedDigest,
    publish: true,
  }));
});

it("법률 글의 새 커버 파일을 저장할 때 기존 배포 자산 경로를 비운다", async () => {
  const user = userEvent.setup();
  adminApi.adminGetBlogPost.mockResolvedValue(legalPost({
    is_published: false,
    legal_review: null,
  }));
  adminApi.adminUpdateBlogPost.mockResolvedValue(legalPost({
    is_published: false,
    legal_review: null,
    cover_image: "https://assets.inpa.kr/new.webp",
    cover_asset_path: "",
    review_content_digest: savedDigest,
  }));

  const { container } = render(<BlogEditor postId={7} />);
  await screen.findByRole("button", { name: "임시저장" });
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  const file = new File(["image"], "new.webp", { type: "image/webp" });
  fireEvent.change(input!, { target: { files: [file] } });
  await user.click(screen.getByRole("button", { name: "임시저장" }));

  await waitFor(() => expect(adminApi.adminUpdateBlogPost).toHaveBeenCalled());
  const [, payload, sentFile] = adminApi.adminUpdateBlogPost.mock.calls[0];
  expect(payload.cover_asset_path).toBe("");
  expect(sentFile).toBe(file);
});

it("일반 글을 법률 글로 저장한 뒤 편집 도구를 쓰면 검토 준비를 다시 해제한다", async () => {
  const user = userEvent.setup();
  adminApi.adminGetBlogPost.mockResolvedValue(legalPost({
    is_published: false,
    review_gate: "none",
    legal_review_required: false,
    legal_review: null,
  }));
  adminApi.adminUpdateBlogPost.mockResolvedValue(legalPost({
    is_published: false,
    legal_review: null,
    review_content_digest: savedDigest,
  }));

  render(<BlogEditor postId={7} />);
  await screen.findByLabelText("게시 전 검토");
  await user.selectOptions(screen.getByLabelText("게시 전 검토"), "legal");
  await user.click(screen.getByRole("button", { name: "임시저장" }));
  await waitFor(() => expect(adminApi.adminUpdateBlogPost).toHaveBeenCalledTimes(1));

  await user.type(screen.getByLabelText("검토 담당자"), "새 검토자");
  await user.type(screen.getByLabelText("검토 자격"), "대한민국 변호사");
  await user.type(screen.getByLabelText("검토 근거"), "새 기록");
  expect(screen.getByRole("button", { name: "현재 저장본 검토 확인·게시" })).toBeEnabled();

  await user.click(screen.getByRole("button", { name: "H2" }));

  expect(screen.getByRole("button", { name: "현재 저장본 검토 확인·게시" })).toBeDisabled();
  expect(adminApi.adminRecordBlogLegalReview).not.toHaveBeenCalled();
});

it("검토 응답이 유실되면 상세를 다시 읽어 실제 게시 상태를 표시한다", async () => {
  const user = userEvent.setup();
  const draft = legalPost({ is_published: false, legal_review: null });
  const published = legalPost({
    review_content_digest: savedDigest,
    legal_review: {
      reviewer: "새 검토자",
      credential: "대한민국 변호사",
      reviewed_at: "2026-08-03T02:00:00Z",
      reference: "새 기록",
    },
  });
  adminApi.adminGetBlogPost
    .mockResolvedValueOnce(draft)
    .mockResolvedValueOnce(published);
  adminApi.adminRecordBlogLegalReview.mockRejectedValue(new TypeError("network lost"));

  render(<BlogEditor postId={7} />);
  await screen.findByLabelText("검토 담당자");
  await user.type(screen.getByLabelText("검토 담당자"), "새 검토자");
  await user.type(screen.getByLabelText("검토 자격"), "대한민국 변호사");
  await user.type(screen.getByLabelText("검토 근거"), "새 기록");
  await user.click(screen.getByRole("button", { name: "현재 저장본 검토 확인·게시" }));

  expect(await screen.findByText(/서버에서 게시 상태를 다시 확인했어요/)).toBeInTheDocument();
  expect(screen.getByText("게시됨")).toBeInTheDocument();
  expect(screen.getByLabelText("검토 확인 시각")).not.toHaveValue("");
});

it("검토 응답과 상세 재확인이 모두 끊기면 결과 미확정과 새로고침 행동을 보여준다", async () => {
  const user = userEvent.setup();
  adminApi.adminGetBlogPost
    .mockResolvedValueOnce(legalPost({ is_published: false, legal_review: null }))
    .mockRejectedValueOnce(new TypeError("still offline"));
  adminApi.adminRecordBlogLegalReview.mockRejectedValue(new TypeError("network lost"));

  render(<BlogEditor postId={7} />);
  await screen.findByLabelText("검토 담당자");
  await user.type(screen.getByLabelText("검토 담당자"), "새 검토자");
  await user.type(screen.getByLabelText("검토 자격"), "대한민국 변호사");
  await user.type(screen.getByLabelText("검토 근거"), "새 기록");
  await user.click(screen.getByRole("button", { name: "현재 저장본 검토 확인·게시" }));

  expect(await screen.findByText(/게시 결과를 확인하지 못했어요/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "게시 상태 새로고침" })).toBeInTheDocument();
});
