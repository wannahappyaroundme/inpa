import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import {
  MIB,
  MultipartBuffer,
  selectRecordingMimeType,
  withUploadRetry,
} from "@/components/consultation-recorder/upload-parts";

describe("상담 녹음 분할 업로드", () => {
  it("브라우저가 지원하는 첫 음성 형식을 고른다", () => {
    const supported = (value: string) => value === "audio/mp4";

    expect(selectRecordingMimeType(supported)).toBe("audio/mp4");
  });

  it("8MiB 고정 조각과 마지막 작은 조각으로 나눈다", async () => {
    const upload = vi.fn(async (partNumber: number, blob: Blob) => ({
      part_number: partNumber,
      etag: `"etag-${partNumber}"`,
      byte_size: blob.size,
    }));
    const buffer = new MultipartBuffer(8 * MIB, upload);

    buffer.push(new Blob([new Uint8Array(5 * MIB)]));
    buffer.push(new Blob([new Uint8Array(5 * MIB)]));
    buffer.push(new Blob([new Uint8Array(1 * MIB)]));
    const parts = await buffer.finish();

    expect(parts.map((part) => part.byte_size)).toEqual([8 * MIB, 3 * MIB]);
    expect(parts.map((part) => part.part_number)).toEqual([1, 2]);
  });

  it("업로드 실패를 finish 호출자에게 전달한다", async () => {
    const upload = vi.fn().mockRejectedValue(new Error("network"));
    const buffer = new MultipartBuffer(8, upload);
    buffer.push(new Blob([new Uint8Array(8)]));

    await expect(buffer.finish()).rejects.toThrow("network");
  });

  it("회선 오류는 같은 조각 번호로 1초, 2초, 4초 뒤 재시도한다", async () => {
    const operation = vi.fn()
      .mockRejectedValueOnce(new Error("offline-1"))
      .mockRejectedValueOnce(new Error("offline-2"))
      .mockRejectedValueOnce(new Error("offline-3"))
      .mockResolvedValue({ part_number: 3, etag: '"ok"', byte_size: 12 });
    const delays: number[] = [];

    const result = await withUploadRetry<{
      part_number: number;
      etag: string;
      byte_size: number;
    }>(operation, async (delayMs) => {
      delays.push(delayMs);
    });

    expect(result.part_number).toBe(3);
    expect(operation).toHaveBeenCalledTimes(4);
    expect(delays).toEqual([1000, 2000, 4000]);
  });

  it("권한이나 요청 형식 오류는 재시도하지 않는다", async () => {
    const operation = vi.fn().mockRejectedValue(
      new ApiError(403, "FORBIDDEN", "접근 범위를 확인해 주세요."),
    );
    const wait = vi.fn();

    await expect(withUploadRetry(operation, wait)).rejects.toMatchObject({
      status: 403,
      code: "FORBIDDEN",
    });
    expect(operation).toHaveBeenCalledTimes(1);
    expect(wait).not.toHaveBeenCalled();
  });
});
