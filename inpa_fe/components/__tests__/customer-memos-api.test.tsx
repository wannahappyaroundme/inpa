import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  createCustomerMemo,
  deleteCustomerMemo,
  getCustomerMemo,
  listCustomerMemos,
  tokenStore,
  updateCustomerMemo,
  type CustomerMemo,
} from "@/lib/api";

const memo: CustomerMemo = {
  id: 71,
  source: "manual",
  source_label: "직접 작성",
  body: "계약 내용을 확인했어요.",
  occurred_at: "2026-07-23T01:30:00Z",
  created_at: "2026-07-23T01:30:00Z",
  updated_at: "2026-07-23T01:30:00Z",
  edited_at: null,
  revision: 4,
};

function response(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, statusText: "요청 실패", json: vi.fn().mockResolvedValue(body) } as unknown as Response;
}

describe("상담 메모 API gateway", () => {
  afterEach(() => {
    tokenStore.remove();
    vi.unstubAllGlobals();
  });

  it("목록·작성·수정·삭제는 고객 주소, 인증, 본문과 revision을 정확히 전달한다", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response({ count: 1, next: null, previous: null, results: [memo] }))
      .mockResolvedValueOnce(response(memo, 201))
      .mockResolvedValueOnce(response({ ...memo, body: "수정한 내용", revision: 5 }))
      .mockResolvedValueOnce(response({}, 204));
    vi.stubGlobal("fetch", fetch);
    tokenStore.set("memo-token");

    await listCustomerMemos(31, 2);
    await createCustomerMemo(31, "작성할 내용");
    await updateCustomerMemo(31, memo, "수정한 내용");
    await deleteCustomerMemo(31, 71);

    expect(fetch).toHaveBeenNthCalledWith(1, "http://localhost:8000/api/v1/customers/31/memos/?page=2", expect.objectContaining({ method: "GET", headers: expect.objectContaining({ Authorization: "Token memo-token" }) }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://localhost:8000/api/v1/customers/31/memos/", expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "작성할 내용" }), headers: expect.objectContaining({ Authorization: "Token memo-token" }) }));
    expect(fetch).toHaveBeenNthCalledWith(3, "http://localhost:8000/api/v1/customers/31/memos/71/", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ body: "수정한 내용", revision: 4 }), headers: expect.objectContaining({ Authorization: "Token memo-token" }) }));
    expect(fetch).toHaveBeenNthCalledWith(4, "http://localhost:8000/api/v1/customers/31/memos/71/", expect.objectContaining({ method: "DELETE", headers: expect.objectContaining({ Authorization: "Token memo-token" }) }));
  });

  it("서버 오류는 gateway의 ApiError 형태로 유지한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ code: "MEMO_EDIT_CONFLICT", detail: "최신 내용을 확인해 주세요." }, 409)));

    await expect(updateCustomerMemo(31, memo, "다른 내용")).rejects.toMatchObject<ApiError>({
      name: "ApiError",
      status: 409,
      code: "MEMO_EDIT_CONFLICT",
      message: "최신 내용을 확인해 주세요.",
    });
  });

  it("충돌한 메모 한 건만 최신 내용으로 다시 읽는다", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({ ...memo, revision: 5 }));
    vi.stubGlobal("fetch", fetch);
    tokenStore.set("memo-token");

    await getCustomerMemo(31, 71);

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/customers/31/memos/71/",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({ Authorization: "Token memo-token" }),
      }),
    );
  });
});
