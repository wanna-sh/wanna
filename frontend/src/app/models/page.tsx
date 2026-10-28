"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { api, type Gpu, type InstalledModel, type MemoryOptions } from "@/lib/api";
import { useModels, usePoll, useSystem } from "@/lib/hooks";
import { TASKS, TASK_ORDER } from "@/lib/tasks";
import { ago, bytes, gpuName, prettyName } from "@/lib/format";
import { Button, Field, LinkButton, LiveDot, Notice, PageHeader, inputClass } from "@/components/ui";

export default function ModelsPage() {
  const { data, refresh } = useModels(undefined, 2500);
  const { data: sys } = useSystem(3000);
  const gpus = sys?.gpus ?? [];

  return (
    <div className="max-w-[880px]">
      <PageHeader title="My models" intro="Models start by themselves when you use them. Start or stop them here, or choose where they run.">
        <LinkButton href="/discover/">Get more models</LinkButton>
      </PageHeader>

      {sys?.engines.llamacpp.status === "installing" && (
        <div className="mb-6">
          <Notice>
            Setting up the chat engine for your computer ({Math.round(sys.engines.llamacpp.progress * 100)}%). This
            happens once.
          </Notice>
        </div>
      )}

      {(sys?.loaded.length ?? 0) > 0 && (
        <div className="mb-7 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line px-4 py-3 text-[15px]">
          <span className="flex items-center gap-2">
            <LiveDot status="ready" />
            {sys!.loaded.length} running, using graphics memory
          </span>
          <button
            className="ml-auto text-[14px] underline underline-offset-2 text-slate hover:text-ink"
            onClick={async () => {
              await Promise.all(sys!.loaded.map((w) => api.post(`/api/models/${w.id}/unload`)));
              refresh();
            }}
          >
            Stop all and free memory
          </button>
        </div>
      )}

      {data && data.length === 0 && (
        <p>
          No models yet.{" "}
          <Link href="/discover/" className="underline underline-offset-2">
            Get your first one
          </Link>
          .
        </p>
      )}

      {TASK_ORDER.map((t) => {
        const ms = (data ?? []).filter((m) => m.task === t);
        if (!ms.length) return null;
        return (
          <section key={t} className="mb-9">
            <h2 className="text-[14px] text-slate mb-2">{TASKS[t].label}</h2>
            <ul className="rounded-2xl border border-line bg-paper divide-y divide-line">
              {ms.map((m) => (
                <ModelRow key={m.id} m={m} gpus={gpus} onChange={refresh} />
              ))}
            </ul>
          </section>
        );
      })}

      {(sys?.events.length ?? 0) > 0 && (
        <section className="mt-12">
          <h2 className="text-[14px] text-slate mb-2">Recent activity</h2>
          <ul className="rounded-2xl border border-line divide-y divide-line text-[14px]">
            {sys!.events.slice(0, 10).map((e, i) => (
              <li key={i} className="flex justify-between gap-4 px-4 py-2.5">
                <span className="min-w-0">{e.message}</span>
                <span className="text-slate text-[13px] shrink-0">{ago(e.time)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function placementOptions(gpus: Gpu[]) {
  const opts = [{ value: "auto", label: "Automatic (recommended)" }];
  gpus.forEach((g) => opts.push({ value: String(g.index), label: `${gpuName(g.name)} only` }));
  if (gpus.length > 1) opts.push({ value: gpus.map((g) => g.index).join(","), label: "Share across all graphics cards" });
  opts.push({ value: "cpu", label: "Processor only (slow)" });
  return opts;
}

const CONTEXTS = [
  { value: 4096, label: "Short conversations (4K)" },
  { value: 8192, label: "Standard (8K)" },
  { value: 16384, label: "Long (16K)" },
  { value: 32768, label: "Very long documents (32K)" },
];

function ModelRow({ m, gpus, onChange }: { m: InstalledModel; gpus: Gpu[]; onChange: () => void }) {
  const w = m.loaded;
  const [open, setOpen] = useState(false);
  const [where, setWhere] = useState("auto");
  const [context, setContext] = useState(8192);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<string | null>(null);
  const name = prettyName(m.meta.title || m.repo_id);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
    onChange();
  };

  const start = () =>
    act(() =>
      api.post(`/api/models/${m.id}/load`, {
        gpus: where === "auto" ? null : where === "cpu" ? [] : where.split(",").map(Number),
        context: m.task === "chat" ? context : null,
      }),
    );

  const on = w?.gpus.length
    ? w.gpus.map((i) => gpuName(gpus.find((g) => g.index === i)?.name ?? `GPU ${i}`)).join(" + ")
    : "the processor";
  const spill = w?.gpu_layers != null && w?.total_layers ? w.total_layers - w.gpu_layers : 0;
  const status = w
    ? `${w.status === "loading" ? "Starting on" : "Running on"} ${on}${w.offload ? ", memory saver on" : ""}` +
      (spill > 0 ? `, ${spill} of ${w.total_layers} layers on the processor (slower)` : "")
    : "Not running";
  const speed = m.speed ? `About ${Math.round(m.speed)} tokens a second here. ` : "";
  // How each memory size would run here, from llama.cpp's planner (fetched when Options opens).
  const memory = usePoll<MemoryOptions>(open && m.task === "chat" ? `/api/models/${m.id}/memory` : null);
  const problem = error ?? w?.error ?? m.last_error;

  return (
    <li className="px-4 sm:px-5 py-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <LiveDot status={w?.status} />
            <span className="font-medium truncate">{name}</span>
            {m.meta.quant && <span className="text-[13px] text-slate">{m.meta.quant}</span>}
          </div>
          <div className="text-[14px] text-slate mt-0.5">
            {status}. {speed}{bytes(m.size_bytes)}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="h-9 px-3 inline-flex items-center gap-1 rounded-full text-[14px] text-slate hover:text-ink hover:bg-well"
          >
            Options <ChevronDown size={14} className={`transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
          </button>
          {w ? (
            <Button tone="quiet" disabled={busy} onClick={() => act(() => api.post(`/api/models/${m.id}/unload`))}>
              Stop
            </Button>
          ) : (
            <Button disabled={busy} onClick={start}>
              Start
            </Button>
          )}
        </div>
      </div>

      {open && (
        <div className="mt-4 pt-4 border-t border-line grid gap-4 sm:grid-cols-2">
          <Field label="Where to run it" hint={w ? "Applies the next time it starts." : undefined}>
            <select className={`${inputClass} h-10 py-0`} value={where} onChange={(e) => setWhere(e.target.value)}>
              {placementOptions(gpus).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>
          {m.task === "chat" && (
            <Field
              label="Memory for conversation"
              hint={
                memory.data
                  ? `Recommended here: ${Math.round(memory.data.recommended / 1024)}K, the most that fits fully on your graphics cards.`
                  : "Checking what fits on this computer…"
              }
            >
              <select
                className={`${inputClass} h-10 py-0`}
                value={context}
                onChange={(e) => setContext(Number(e.target.value))}
              >
                {(memory.data?.options ?? CONTEXTS.map((c) => ({ context: c.value, label: c.label, rating: "unknown" }))).map((o) => (
                  <option key={o.context} value={o.context}>
                    {Math.round(o.context / 1024)}K{o.rating !== "unknown" ? `: ${o.label}` : ""}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <div className="sm:col-span-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-[14px] text-slate">
            <span className="break-all">From {m.repo_id}</span>
            <button className="underline underline-offset-2 hover:text-ink" onClick={async () => setLog(await api.get<string>(`/api/models/${m.id}/log`))}>
              Show log
            </button>
            <button
              className="text-danger underline underline-offset-2 ml-auto"
              disabled={busy}
              onClick={() => {
                if (confirm(`Delete ${name}? This frees ${bytes(m.size_bytes)} and can't be undone.`))
                  act(() => api.del(`/api/models/${m.id}`));
              }}
            >
              Delete model
            </button>
          </div>
        </div>
      )}

      {problem && (
        <div className="mt-3">
          <Notice tone="error">
            {problem}{" "}
            <button className="underline" onClick={async () => setLog(await api.get<string>(`/api/models/${m.id}/log`))}>
              Show details
            </button>
          </Notice>
        </div>
      )}
      {log !== null && (
        <pre className="mt-3 max-h-72 overflow-auto rounded-xl bg-well p-3 text-[12px] font-mono whitespace-pre-wrap">
          {log || "No log yet."}
        </pre>
      )}
    </li>
  );
}
