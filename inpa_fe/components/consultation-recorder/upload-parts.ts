import {
  ApiError,
  getRecordingPartUrl,
  type CompletedRecordingPart,
} from "@/lib/api";

import type { UploadPart } from "./recorder-types";

export const MIB = 1024 * 1024;

const CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/mp4;codecs=mp4a.40.2",
  "audio/mp4",
  "audio/ogg;codecs=opus",
  "audio/webm",
  "audio/ogg",
] as const;

export function selectRecordingMimeType(
  isSupported: (value: string) => boolean = (value) => (
    typeof MediaRecorder !== "undefined"
    && MediaRecorder.isTypeSupported(value)
  ),
): string | null {
  return CANDIDATES.find((value) => isSupported(value)) ?? null;
}

const DEFAULT_RETRY_DELAYS = [1000, 2000, 4000] as const;

function sleep(delayMs: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs));
}

export async function withUploadRetry<T>(
  operation: () => Promise<T>,
  wait: (delayMs: number) => Promise<void> = sleep,
): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      if (
        error instanceof DOMException
        && error.name === "AbortError"
      ) {
        throw error;
      }
      if (
        error instanceof ApiError
        && error.status !== 408
        && error.status !== 429
        && error.status < 500
      ) {
        throw error;
      }
      const delay = DEFAULT_RETRY_DELAYS[attempt];
      if (delay === undefined) throw error;
      await wait(delay);
    }
  }
}

export function createRecordingPartUploader(
  customerId: number,
  recordingId: string,
  onUploaded?: (byteSize: number) => void,
): UploadPart {
  return async (partNumber, blob) => withUploadRetry(async () => {
    const signed = await getRecordingPartUrl(
      customerId,
      recordingId,
      partNumber,
    );
    const response = await fetch(signed.url, {
      method: "PUT",
      body: blob,
    });
    if (!response.ok) {
      throw new Error(`RECORDING_PART_UPLOAD_${response.status}`);
    }
    const etag = response.headers.get("ETag") ?? response.headers.get("etag");
    if (!etag) {
      throw new Error("RECORDING_PART_ETAG_MISSING");
    }
    onUploaded?.(blob.size);
    return {
      part_number: partNumber,
      etag,
      byte_size: blob.size,
    };
  });
}

export class MultipartBuffer {
  private pending = new Blob();
  private nextPart = 1;
  private completed: CompletedRecordingPart[] = [];
  private queue: Promise<void> = Promise.resolve();
  private finishPromise: Promise<CompletedRecordingPart[]> | null = null;

  constructor(
    private readonly partBytes: number,
    private readonly upload: UploadPart,
  ) {
    if (!Number.isInteger(partBytes) || partBytes <= 0) {
      throw new Error("INVALID_RECORDING_PART_BYTES");
    }
  }

  push(chunk: Blob): void {
    if (this.finishPromise) {
      throw new Error("RECORDING_BUFFER_ALREADY_FINISHED");
    }
    if (chunk.size <= 0) return;
    this.pending = new Blob([this.pending, chunk], { type: chunk.type });
    while (this.pending.size >= this.partBytes) {
      const part = this.pending.slice(0, this.partBytes);
      this.pending = this.pending.slice(this.partBytes);
      this.enqueue(part);
    }
  }

  private enqueue(part: Blob): void {
    const partNumber = this.nextPart;
    this.nextPart += 1;
    this.queue = this.queue.then(async () => {
      const completed = await this.upload(partNumber, part);
      if (
        completed.part_number !== partNumber
        || completed.byte_size !== part.size
      ) {
        throw new Error("RECORDING_PART_RESPONSE_MISMATCH");
      }
      this.completed.push(completed);
    });
  }

  finish(): Promise<CompletedRecordingPart[]> {
    if (this.finishPromise) return this.finishPromise;
    if (this.pending.size > 0) {
      const finalPart = this.pending;
      this.pending = new Blob();
      this.enqueue(finalPart);
    }
    this.finishPromise = this.queue.then(() => [...this.completed]);
    return this.finishPromise;
  }

  clear(): void {
    this.pending = new Blob();
  }
}
