import { useCallback, useEffect, useState } from "react";
import type { Runtime } from "../lib/runner/languages";
import { atCap, buildStdin } from "../lib/runner/replay";
import { runInSandbox, type SandboxHandle } from "../lib/runner/sandbox";
import type { RunEvent } from "../lib/runner/protocol";
import { canReplay, idleState, isBusy, reduceRun, startState, type RunState } from "../lib/runner/state";

type Session = { code: string };

// One sandbox at a time per code block. Leaving the page (or switching chats) kills a run in flight.
export function useCodeRunner(runtime: Runtime | null) {
  const [state, setState] = useState<RunState>(idleState);
  // Latest state for submitAnswer, which must decide synchronously whether a replay may start.
  const [latest] = useState<{ current: RunState }>(() => ({ current: idleState }));
  const [handle] = useState<{ current: SandboxHandle | undefined }>(() => ({ current: undefined }));
  const [session] = useState<{ current: Session | undefined }>(() => ({ current: undefined }));

  const commit = useCallback(
    (next: RunState) => {
      latest.current = next;
      setState(next);
    },
    [latest],
  );

  const start = useCallback(
    (rt: Runtime, code: string, stdin: string) => {
      handle.current = runInSandbox({ runtime: rt, code, stdin }, (event: RunEvent) => {
        latest.current = reduceRun(latest.current, event);
        setState(latest.current);
      });
    },
    [handle, latest],
  );

  useEffect(() => () => handle.current?.stop(), [handle]);

  const stop = useCallback(() => {
    handle.current?.stop();
    handle.current = undefined;
    commit(reduceRun(latest.current, { type: "stopped" }));
  }, [handle, latest, commit]);

  // Starts a fresh session: answers typed before are dropped.
  const run = useCallback(
    (code: string) => {
      if (!runtime) return;
      handle.current?.stop();
      session.current = { code };
      commit(startState(runtime));
      start(runtime, code, "");
    },
    [runtime, handle, session, commit, start],
  );

  const submitAnswer = useCallback(
    (line: string) => {
      const s = session.current;
      const cur = latest.current;
      if (!runtime || !s || !canReplay(cur, runtime) || atCap(cur.answers.length)) return;
      const answer = line.replace(/[\r\n]+/g, " ");
      const next = reduceRun(cur, { type: "replay", answer });
      if (next === cur) return;
      handle.current?.stop();
      commit(next);
      start(runtime, s.code, buildStdin(next.answers));
    },
    [runtime, handle, session, latest, commit, start],
  );

  const clear = useCallback(() => {
    handle.current?.stop();
    handle.current = undefined;
    session.current = undefined;
    commit(idleState);
  }, [handle, session, commit]);

  return { state, busy: isBusy(state), run, stop, clear, submitAnswer };
}
