export interface LatestRequestGuard {
  begin: () => () => boolean;
  supersede: () => void;
  dispose: () => void;
}

export interface LatestRequestHandlers<T> {
  onStart: () => void;
  onSuccess: (value: T) => void;
  onError: (error: unknown) => void;
  onFinish: () => void;
}

/** Lets only the newest request update state, including after unmount. */
export function createLatestRequestGuard(): LatestRequestGuard {
  let generation = 0;

  return {
    begin() {
      const requestGeneration = ++generation;
      return () => requestGeneration === generation;
    },
    supersede() {
      generation += 1;
    },
    dispose() {
      generation += 1;
    },
  };
}

/** Runs a request while preventing stale completion from mutating UI state. */
export async function runLatestRequest<T>(
  guard: LatestRequestGuard,
  request: () => Promise<T>,
  handlers: LatestRequestHandlers<T>,
): Promise<void> {
  const mayCommit = guard.begin();
  handlers.onStart();
  try {
    const value = await request();
    if (mayCommit()) handlers.onSuccess(value);
  } catch (error) {
    if (mayCommit()) handlers.onError(error);
  } finally {
    if (mayCommit()) handlers.onFinish();
  }
}
