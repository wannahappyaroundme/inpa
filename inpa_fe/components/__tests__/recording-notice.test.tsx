import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RecordingNotice } from "@/components/consultation-recorder/recording-notice";
import {
  createRecordingUpload,
  getRecordingDownloadUrl,
  tokenStore,
} from "@/lib/api";

const NOTICE_TEXT = "본 상담은 상담 내용을 정확히 기록하고, 향후 상담 내용과 보험금 청구 관련 안내를 확인하는 참고자료로 활용하기 위해 녹음합니다. 원본은 인파에 30일 동안 보관된 뒤 자동 삭제됩니다. 녹음에 동의하시나요?";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 201,
    headers: { "Content-Type": "application/json" },
  });
}

function NoticeHarness({
  onDecline = () => undefined,
  onStart = () => undefined,
}: {
  onDecline?: () => void;
  onStart?: () => void;
}) {
  const [checked, setChecked] = useState(false);
  return (
    <RecordingNotice
      noticeText={NOTICE_TEXT}
      checked={checked}
      onCheckedChange={setChecked}
      onDecline={onDecline}
      onStart={onStart}
      startBlocked={false}
    />
  );
}

describe("설계사용 녹음 고지", () => {
  afterEach(() => {
    tokenStore.remove();
    vi.unstubAllGlobals();
  });

  it("설계사가 직접 읽을 정확한 고지와 색 외의 중요도 단서를 제공한다", () => {
    render(<NoticeHarness />);

    const note = screen.getByRole("note", { name: "설계사용 녹음 필수 안내" });
    expect(note).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "중요 안내" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "녹음 전 필수 안내" })).toBeInTheDocument();
    expect(screen.getByText("설계사 직접 안내")).toBeInTheDocument();
    expect(screen.getByText(
      "보험 가입 희망자에게 아래 문구를 직접 읽고 동의를 확인해 주세요.",
    )).toBeInTheDocument();
    expect(screen.getByText(NOTICE_TEXT)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", {
      name: "보험 가입 희망자에게 위 내용을 안내했고, 녹음 동의를 확인했습니다.",
    })).not.toBeChecked();
  });

  it("매 녹음 확인 전에는 시작을 막고 확인 뒤 시작과 메모 이동을 제공한다", async () => {
    const user = userEvent.setup();
    const onDecline = vi.fn();
    const onStart = vi.fn();
    render(<NoticeHarness onDecline={onDecline} onStart={onStart} />);

    const start = screen.getByRole("button", { name: "녹음 시작" });
    expect(start).toBeDisabled();

    await user.click(screen.getByRole("checkbox"));
    expect(start).toBeEnabled();
    await user.click(start);
    expect(onStart).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: "상담 메모로 기록하기" }));
    expect(onDecline).toHaveBeenCalledOnce();
  });

  it("360px에서는 한 열, 1440px에서는 가로 행동 영역이 되는 의미 클래스를 유지한다", () => {
    render(<NoticeHarness />);

    const actions = screen.getByTestId("recording-notice-actions");
    expect(actions).toHaveClass("flex-col");
    expect(actions).toHaveClass("sm:flex-row");
    expect(screen.getByRole("button", { name: "녹음 시작" })).toHaveClass("w-full");
    expect(screen.getByRole("button", { name: "상담 메모로 기록하기" })).toHaveClass("w-full");
  });

  it("업로드 세션에는 확인 사실과 버전만 보내고 고지 원문은 보내지 않는다", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({
      id: "recording-31",
      part_bytes: 8,
      max_part_number: 13,
    }));
    vi.stubGlobal("fetch", fetch);
    tokenStore.set("recording-token");

    await createRecordingUpload(
      31,
      "00000000-0000-4000-8000-000000000031",
      "audio/webm;codecs=opus",
      "2026-07-28T01:00:00.000Z",
      "consultation-notice-v2-2026-07-28",
    );

    const request = fetch.mock.calls[0]?.[1] as RequestInit;
    expect(fetch.mock.calls[0]?.[0]).toBe(
      "http://localhost:8000/api/v1/customers/31/recordings/upload-sessions/",
    );
    expect(JSON.parse(String(request.body))).toEqual({
      client_session_id: "00000000-0000-4000-8000-000000000031",
      mime_type: "audio/webm;codecs=opus",
      started_at: "2026-07-28T01:00:00.000Z",
      notice_attested: true,
      notice_version: "consultation-notice-v2-2026-07-28",
    });
    expect(String(request.body)).not.toContain(NOTICE_TEXT);
  });

  it("다운로드 주소는 녹음 전용 POST 계약으로 그때마다 새로 요청한다", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({
      url: "https://private.example/signed-recording",
      expires_in_seconds: 300,
    }));
    vi.stubGlobal("fetch", fetch);
    tokenStore.set("recording-token");

    await expect(getRecordingDownloadUrl(31, "recording-31")).resolves.toEqual({
      url: "https://private.example/signed-recording",
      expires_in_seconds: 300,
    });

    const request = fetch.mock.calls[0]?.[1] as RequestInit;
    expect(fetch.mock.calls[0]?.[0]).toBe(
      "http://localhost:8000/api/v1/customers/31/recordings/recording-31/download-url/",
    );
    expect(request.method).toBe("POST");
    expect(JSON.parse(String(request.body))).toEqual({});
    expect(request.headers).toMatchObject({
      Authorization: "Token recording-token",
    });
  });
});
