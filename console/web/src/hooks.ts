import { useCallback, useEffect, useState } from "react";
import { ApiError } from "./api";

export interface Loadable<T> { data: T | null; error: string | null; loading: boolean; reload: () => void }

/** Load once (and on reload / dependency change); optionally poll. Errors become readable text, never a blank page. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[], pollMs?: number): Loadable<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    run().then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e: unknown) => { if (alive) setError(e instanceof ApiError ? e.message : String(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [run, tick]);
  useEffect(() => {
    if (!pollMs) return;
    const id = setInterval(() => setTick((t) => t + 1), pollMs);
    return () => clearInterval(id);
  }, [pollMs]);
  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}
