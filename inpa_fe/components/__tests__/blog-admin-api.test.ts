import { afterEach, expect, it, vi } from "vitest";
import { adminCreateBlogPost, adminRecordBlogLegalReview } from "@/lib/adminApi";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("커버 파일 저장 요청에는 법률 검토 기록을 섞지 않는다", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({}),
  });
  vi.stubGlobal("fetch", fetchMock);

  await adminCreateBlogPost(
    {
      title: "검토 글",
      body: "본문",
      review_gate: "legal",
      is_published: false,
    },
    new File(["image"], "cover.webp", { type: "image/webp" }),
  );

  const init = fetchMock.mock.calls[0][1] as RequestInit;
  const form = init.body as FormData;
  expect(form.get("legal_review")).toBeNull();
  expect(form.get("cover_image")).toBeInstanceOf(File);
});

it("법률 검토 확인은 저장 API와 분리하고 검토 시각을 보내지 않는다", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({}),
  });
  vi.stubGlobal("fetch", fetchMock);

  await adminRecordBlogLegalReview(17, {
    reviewer: "검토 담당자",
    credential: "대한민국 변호사",
    reference: "검토 기록 01",
    content_digest: "a".repeat(64),
    publish: true,
  });

  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toContain("/admin/blog/17/legal-review/");
  expect(JSON.parse(init.body as string)).toEqual({
    reviewer: "검토 담당자",
    credential: "대한민국 변호사",
    reference: "검토 기록 01",
    content_digest: "a".repeat(64),
    publish: true,
  });
  expect(init.body as string).not.toContain("reviewed_at");
});
