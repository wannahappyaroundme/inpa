import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  createPersonalTalkTemplate,
  deletePersonalTalkTemplate,
  listPersonalTalkTemplates,
  putTalkTemplatePreference,
  updatePersonalTalkTemplate,
  type PersonalTalkTemplatePayload,
} from "@/lib/api";

const payload: PersonalTalkTemplatePayload = {
  source_key: "closing-confirm",
  title: "내 확인 문구",
  body: "{고객명} 고객님, 다음 내용을 확인할까요?",
  category: "closing",
  channel: "message",
  sort_order: 4,
  is_active: true,
};

function jsonResponse(
  data: unknown,
  status = 200,
  statusText = "OK",
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: vi.fn().mockResolvedValue(data),
  } as unknown as Response;
}

describe("talk template API gateway", () => {
  beforeEach(() => {
    localStorage.setItem("inpa_token", "talk-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  it("lists personal templates and hidden default keys through the authenticated gateway", async () => {
    const response = { results: [], hidden_source_keys: ["first-a"] };
    vi.mocked(fetch).mockResolvedValue(jsonResponse(response));

    await expect(listPersonalTalkTemplates()).resolves.toEqual(response);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/talk-templates/",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Authorization: "Token talk-token",
        }),
      }),
    );
  });

  it("creates, patches, deletes, and updates a default preference with exact API contracts", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ id: 12, ...payload }))
      .mockResolvedValueOnce(jsonResponse({ id: 12, ...payload, title: "수정" }))
      .mockResolvedValueOnce({
        ok: true,
        status: 204,
        statusText: "No Content",
        json: vi.fn().mockRejectedValue(new Error("empty")),
      } as unknown as Response)
      .mockResolvedValueOnce(
        jsonResponse({ source_key: "closing-confirm", is_hidden: true }),
      );

    await createPersonalTalkTemplate(payload);
    await updatePersonalTalkTemplate(12, { title: "수정" });
    await deletePersonalTalkTemplate(12);
    await putTalkTemplatePreference({
      source_key: "closing-confirm",
      is_hidden: true,
    });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/api/v1/talk-templates/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/api/v1/talk-templates/12/",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ title: "수정" }),
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/api/v1/talk-templates/12/",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      4,
      "http://localhost:8000/api/v1/talk-template-preferences/",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          source_key: "closing-confirm",
          is_hidden: true,
        }),
      }),
    );
  });

  it("keeps server failures normalized as ApiError", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        { code: "not_found", detail: "화법을 다시 불러와 주세요." },
        404,
        "Not Found",
      ),
    );

    const error = await listPersonalTalkTemplates().catch((caught) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 404,
      code: "not_found",
      message: "화법을 다시 불러와 주세요.",
    });
  });
});
