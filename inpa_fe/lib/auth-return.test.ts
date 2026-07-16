import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  clearAuthReturn,
  consumeAuthReturn,
  isSafeAuthReturnPath,
  peekAuthReturn,
  processAuthReturnNext,
  rememberAuthReturn,
} from "./auth-return";

const STORAGE_KEY = "inpa_auth_return";
const DAY_MS = 24 * 60 * 60 * 1000;
const realDateNow = Date.now;

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

function useBrowserStorage(): MemoryStorage {
  const storage = new MemoryStorage();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage: storage },
  });
  return storage;
}

afterEach(() => {
  Date.now = realDateNow;
  clearAuthReturn();
  Reflect.deleteProperty(globalThis, "window");
});

test("영입 합류 토큰 한 구간만 안전한 인증 반환 경로로 허용한다", () => {
  assert.equal(isSafeAuthReturnPath("/recruiting/join/abc.DEF_9:-"), true);
  assert.equal(isSafeAuthReturnPath("/recruiting/join/abc.DEF_9:-/"), true);
});

test("외부·불완전·중첩·인코딩 경로를 모두 거부한다", () => {
  const rejected: unknown[] = [
    "/recruiting/join/",
    "/recruiting/join/token/extra",
    "//evil.com",
    "https://evil.com",
    "/\\evil.com",
    "/recruiting/join/token?next=/home",
    "/recruiting/join/token#section",
    "/recruiting/join/token%3Aencoded",
    null,
    undefined,
    123,
    {},
  ];

  for (const value of rejected) {
    assert.equal(isSafeAuthReturnPath(value), false, String(value));
  }
});

test("안전한 경로를 저장하고 만료 전에는 확인할 수 있다", () => {
  useBrowserStorage();
  Date.now = () => 1_000;

  assert.equal(rememberAuthReturn("/recruiting/join/signed:token"), true);
  assert.equal(peekAuthReturn(), "/recruiting/join/signed:token");
});

test("저장된 경로는 한 번 소비한 뒤 바로 지운다", () => {
  const storage = useBrowserStorage();
  assert.equal(rememberAuthReturn("/recruiting/join/once"), true);

  assert.equal(consumeAuthReturn(), "/recruiting/join/once");
  assert.equal(consumeAuthReturn(), null);
  assert.equal(storage.getItem(STORAGE_KEY), null);
});

test("저장 후 24시간이 지나면 만료시키고 지운다", () => {
  const storage = useBrowserStorage();
  Date.now = () => 10_000;
  rememberAuthReturn("/recruiting/join/expires");
  Date.now = () => 10_000 + DAY_MS;

  assert.equal(peekAuthReturn(), null);
  assert.equal(storage.getItem(STORAGE_KEY), null);
});

test("손상된 저장값은 반환하지 않고 지운다", () => {
  const storage = useBrowserStorage();
  storage.setItem(STORAGE_KEY, "{not-json");

  assert.equal(peekAuthReturn(), null);
  assert.equal(storage.getItem(STORAGE_KEY), null);
});

test("next가 없으면 저장된 안전한 경로를 그대로 보존한다", () => {
  useBrowserStorage();
  rememberAuthReturn("/recruiting/join/preserved");

  assert.equal(processAuthReturnNext(null), "/recruiting/join/preserved");
  assert.equal(peekAuthReturn(), "/recruiting/join/preserved");
});

test("안전한 next는 저장하고 위험한 next는 이전 저장값까지 지운다", () => {
  const storage = useBrowserStorage();

  assert.equal(
    processAuthReturnNext("/recruiting/join/from-query"),
    "/recruiting/join/from-query",
  );
  assert.equal(peekAuthReturn(), "/recruiting/join/from-query");

  assert.equal(processAuthReturnNext("https://evil.com"), null);
  assert.equal(storage.getItem(STORAGE_KEY), null);
});
