import { useEffect, useState } from "react";

const TICK_MS = 500;

// Milliseconds since `startedAt`, re-read twice a second so the whole-second counter and the 3 s / 6 s thresholds
// land on time. It is a local timer, not a request.
export function useElapsed(startedAt: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(id);
  }, [startedAt]);
  return Math.max(0, now - startedAt);
}
