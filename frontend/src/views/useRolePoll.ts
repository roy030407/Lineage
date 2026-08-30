// Role views hit GET /api/view/{role} directly rather than subscribing to
// the Mirror's WebSocket, so each one needs to re-poll to stay live. Shared
// here since the polling views do the exact same fetch-poll-cleanup dance.

import { useEffect, useState } from "react";

const POLL_INTERVAL_MS = 2000;

export interface RolePollResult<T> {
  data: T | null;
  error: string | null;
}

export function useRolePoll<T>(fetcher: () => Promise<T>, deps: unknown[]): RolePollResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);

    async function poll() {
      try {
        const result = await fetcher();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        // Surfaced so a view can show "backend unreachable" instead of an
        // eternal Loading state; the interval keeps running so it self-heals
        // the moment the backend answers again. Any last good data stays.
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    }

    void poll();
    const timer = setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, deps);

  return { data, error };
}
