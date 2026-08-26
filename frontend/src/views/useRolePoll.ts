// Role views hit GET /api/view/{role} directly rather than subscribing to
// the Mirror's WebSocket, so each one needs to re-poll to stay live. Shared
// here since all four views do the exact same fetch-poll-cleanup dance.

import { useEffect, useState } from "react";

const POLL_INTERVAL_MS = 2000;

export function useRolePoll<T>(fetcher: () => Promise<T>, deps: unknown[]): T | null {
  const [data, setData] = useState<T | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);

    async function poll() {
      try {
        const result = await fetcher();
        if (!cancelled) setData(result);
      } catch {
        // A transient fetch failure just keeps showing the last good value.
      }
    }

    void poll();
    const timer = setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, deps);

  return data;
}
