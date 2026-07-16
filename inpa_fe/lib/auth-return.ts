const AUTH_RETURN_STORAGE_KEY = "inpa_auth_return";
const AUTH_RETURN_TTL_MS = 24 * 60 * 60 * 1000;
const AUTH_RETURN_PATH = /^\/recruiting\/join\/([A-Za-z0-9._:-]+)\/?$/;
const ENCODED_NEXT_KEY = /^(?:n|%6[eE])(?:e|%65)(?:x|%78)(?:t|%74)$/;

interface StoredAuthReturn {
  path: string;
  savedAt: number;
}

function getStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function removeStoredReturn(storage: Storage): void {
  try {
    storage.removeItem(AUTH_RETURN_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in privacy-restricted browsers.
  }
}

export function isSafeAuthReturnPath(path: unknown): path is string {
  if (typeof path !== "string") return false;
  const match = AUTH_RETURN_PATH.exec(path);
  return match !== null && match[1] !== "." && match[1] !== "..";
}

export function clearAuthReturn(): void {
  const storage = getStorage();
  if (storage) removeStoredReturn(storage);
}

export function rememberAuthReturn(path: unknown): boolean {
  if (!isSafeAuthReturnPath(path)) return false;
  const storage = getStorage();
  if (!storage) return false;

  const value: StoredAuthReturn = { path, savedAt: Date.now() };
  try {
    storage.setItem(AUTH_RETURN_STORAGE_KEY, JSON.stringify(value));
    return true;
  } catch {
    removeStoredReturn(storage);
    return false;
  }
}

export function peekAuthReturn(): string | null {
  const storage = getStorage();
  if (!storage) return null;

  try {
    const raw = storage.getItem(AUTH_RETURN_STORAGE_KEY);
    if (raw === null) return null;
    const value = JSON.parse(raw) as Partial<StoredAuthReturn> | null;
    const now = Date.now();
    if (
      value === null ||
      typeof value !== "object" ||
      !isSafeAuthReturnPath(value.path) ||
      typeof value.savedAt !== "number" ||
      !Number.isFinite(value.savedAt) ||
      value.savedAt > now ||
      now - value.savedAt >= AUTH_RETURN_TTL_MS
    ) {
      removeStoredReturn(storage);
      return null;
    }
    return value.path;
  } catch {
    removeStoredReturn(storage);
    return null;
  }
}

export function consumeAuthReturn(): string | null {
  const path = peekAuthReturn();
  clearAuthReturn();
  return path;
}

export function processAuthReturnNext(next: unknown): string | null {
  if (next === null || next === undefined) return peekAuthReturn();
  if (!isSafeAuthReturnPath(next)) {
    clearAuthReturn();
    return null;
  }
  return rememberAuthReturn(next) ? next : null;
}

export function processAuthReturnSearch(rawSearch: unknown): string | null {
  if (
    typeof rawSearch !== "string" ||
    (rawSearch !== "" && !rawSearch.startsWith("?"))
  ) {
    clearAuthReturn();
    return null;
  }

  const rawNextValues: string[] = [];
  let hasEncodedNextKey = false;
  const rawQuery = rawSearch.startsWith("?") ? rawSearch.slice(1) : rawSearch;
  for (const pair of rawQuery ? rawQuery.split("&") : []) {
    const separator = pair.indexOf("=");
    const rawKey = separator === -1 ? pair : pair.slice(0, separator);
    if (rawKey === "next") {
      rawNextValues.push(separator === -1 ? "" : pair.slice(separator + 1));
    } else if (ENCODED_NEXT_KEY.test(rawKey)) {
      hasEncodedNextKey = true;
    }
  }

  if (rawNextValues.length === 0 && !hasEncodedNextKey) {
    return peekAuthReturn();
  }
  if (rawNextValues.length !== 1 || hasEncodedNextKey) {
    clearAuthReturn();
    return null;
  }

  const rawNext = rawNextValues[0];
  if (
    rawNext.includes("%") ||
    rawNext.includes("+") ||
    !isSafeAuthReturnPath(rawNext)
  ) {
    clearAuthReturn();
    return null;
  }
  return rememberAuthReturn(rawNext) ? rawNext : null;
}
