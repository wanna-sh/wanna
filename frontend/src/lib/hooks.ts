"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type InstalledModel, type Job, type SystemInfo, type Task } from "./api";

/** Fetch a JSON endpoint and refresh it every `interval` ms (0 = once). */
export function usePoll<T>(path: string | null, interval = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const d = await api.get<T>(path);
        if (alive) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
      if (alive && interval) timer = setTimeout(load, interval);
    };
    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [path, interval, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, refresh, setData };
}

export function useSystem(interval = 3000) {
  return usePoll<SystemInfo>("/api/system", interval);
}

export function useModels(task?: Task, interval = 4000) {
  const r = usePoll<InstalledModel[]>("/api/models", interval);
  const models = task ? (r.data ?? []).filter((m) => m.task === task) : (r.data ?? []);
  return { ...r, models, loaded: r.data !== null };
}

/** Submit a generation job and follow it until it finishes. */
export function useJob() {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const follow = useCallback((id: string, onDone?: (j: Job) => void) => {
    const tick = async () => {
      try {
        const j = await api.get<Job>(`/api/jobs/${id}`);
        setJob(j);
        if (j.status === "completed" || j.status === "failed") {
          if (j.status === "failed") setError(j.error ?? "Something went wrong");
          onDone?.(j);
          return;
        }
      } catch (e) {
        setError((e as Error).message);
        return;
      }
      timer.current = setTimeout(tick, 700);
    };
    tick();
  }, []);

  const start = useCallback(
    async (task: Task, params: Record<string, unknown>, onDone?: (j: Job) => void) => {
      setError(null);
      try {
        const j = await api.post<Job>(`/api/generate/${task}`, params);
        setJob(j);
        follow(j.id, onDone);
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [follow],
  );

  const busy = !!job && !["completed", "failed"].includes(job.status);
  return { job, error, busy, start, setError };
}

/** localStorage-backed state, safe during static prerender. */
export function useStored<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(key);
      // Hydrate after mount: the page is prerendered, so storage can't be read during the first render.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (raw) setValue(JSON.parse(raw));
    } catch {}
  }, [key]);
  const set = useCallback(
    (next: T | ((prev: T) => T)) =>
      setValue((prev) => {
        const v = typeof next === "function" ? (next as (p: T) => T)(prev) : next;
        try {
          localStorage.setItem(key, JSON.stringify(v));
        } catch {}
        return v;
      }),
    [key],
  );
  return [value, set] as const;
}
