export const FLUSH_MS = 60;
const RELEASE_FRACTION = 0.2;

// How many characters of the buffer one tick lets through: a fifth of what is waiting, at least one,
// so a burst drains in a few ticks and a trickle still moves.
export function releaseCount(buffered: string): number {
  if (buffered.length === 0) return 0;
  let n = Math.max(1, Math.ceil(buffered.length * RELEASE_FRACTION));
  // Never cut an emoji in half; the lone surrogate would render as a replacement character until the next tick.
  const last = buffered.charCodeAt(n - 1);
  if (n < buffered.length && last >= 0xd800 && last <= 0xdbff) n += 1;
  return n;
}

export interface Smoother {
  push: (text: string) => void;
  // Releases everything buffered now, so nothing is lost when the stream ends.
  flush: () => void;
  // Drops the buffer without releasing it.
  cancel: () => void;
}

// Network chunks arrive in clumps; releasing them on a fixed beat makes the text arrive steadily.
// The timer only runs while something is buffered.
export function createSmoother(onRelease: (chunk: string) => void, intervalMs = FLUSH_MS): Smoother {
  let buffer = "";
  let timer: ReturnType<typeof setInterval> | null = null;

  const stop = () => {
    if (timer !== null) clearInterval(timer);
    timer = null;
  };

  return {
    push(text) {
      if (!text) return;
      buffer += text;
      timer ??= setInterval(() => {
        const n = releaseCount(buffer);
        const chunk = buffer.slice(0, n);
        buffer = buffer.slice(n);
        if (!buffer) stop();
        if (chunk) onRelease(chunk);
      }, intervalMs);
    },
    flush() {
      stop();
      if (!buffer) return;
      const all = buffer;
      buffer = "";
      onRelease(all);
    },
    cancel() {
      stop();
      buffer = "";
    },
  };
}
