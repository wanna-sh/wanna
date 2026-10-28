"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import {
  api,
  type Download,
  type BrowseResult,
  type HubDetails,
  type InstalledModel,
  type Task,
  type Variant,
} from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes, compact } from "@/lib/format";
import { TASKS } from "@/lib/tasks";
import { Button, Notice, Progress, VerdictBadge } from "./ui";

/** Pick the model to use on a task page: remembers the last choice, prefers a running model. */
export function useTaskModel(task: Task, models: InstalledModel[]) {
  const [chosen, setChosen] = useState("");
  let value = chosen;
  if (!models.some((m) => m.id === value) && models.length) {
    let saved = "";
    try {
      saved = localStorage.getItem(`wanna.model.${task}`) ?? "";
    } catch {}
    value = (
      models.find((m) => m.id === saved) ?? models.find((m) => m.loaded?.status === "ready") ?? models[0]
    ).id;
  }
  const set = (id: string) => {
    setChosen(id);
    try {
      localStorage.setItem(`wanna.model.${task}`, id);
    } catch {}
  };
  return [value, set] as const;
}

/** Shown on a task page when no model for it is installed yet. */
export function NoModelYet({ task, onInstalled }: { task: Task; onInstalled: () => void }) {
  const { data, error } = usePoll<BrowseResult>(`/api/hub/browse?task=${task}&fits=true&limit=6`);
  const [open, setOpen] = useState<string | null>(null);
  // Models we've tested with wanna.sh first, then the most popular ones that run well here.
  const picks = [...(data?.results ?? [])].sort((a, b) => Number(!!b.tested) - Number(!!a.tested)).slice(0, 4);
  return (
    <div className="max-w-[720px]">
      <p className="text-[17px] mb-6">
        You don&apos;t have a {TASKS[task].noun} yet. Pick one to download. It stays on your computer and works
        without the internet afterwards.
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      {!data && !error && <p className="text-slate">Finding models that run well on this computer…</p>}
      <ul className="flex flex-col gap-3">
        {picks.map((p) => (
          <li key={p.repo_id} className="rounded-2xl bg-paper border border-line p-4 flex flex-wrap gap-4 items-center">
            <div className="flex-1 min-w-[220px]">
              <div className="font-display text-[1.1rem] leading-snug break-words">{p.title}</div>
              {p.why && <p className="text-slate text-[15px]">{p.why}</p>}
              <div className="flex flex-wrap gap-x-4 mt-1">
                <VerdictBadge verdict={p.verdict} />
                {p.tested && <span className="text-[13px] font-medium text-accent">Tested with wanna.sh</span>}
              </div>
            </div>
            <Button onClick={() => setOpen(p.repo_id)}>Choose</Button>
          </li>
        ))}
      </ul>
      <p className="mt-6 text-[15px] text-slate">
        Looking for something else?{" "}
        <Link href={`/discover/?task=${task}`} className="text-accent underline">
          Browse every {TASKS[task].noun}
        </Link>
      </p>
      {open && <ModelSheet repoId={open} onClose={() => setOpen(null)} onInstalled={onInstalled} />}
    </div>
  );
}

/** Model details + version choice + download, as a dialog. */
export function ModelSheet({
  repoId,
  onClose,
  onInstalled,
}: {
  repoId: string;
  onClose: () => void;
  onInstalled?: () => void;
}) {
  const { data, error } = usePoll<HubDetails>(`/api/hub/model/${repoId}`);
  const [picked, setVariant] = useState<string | null>(null);
  const [dl, setDl] = useState<Download | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const variant = picked ?? data?.recommended ?? null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!dl || ["done", "error", "cancelled"].includes(dl.status)) return;
    const t = setTimeout(async () => {
      const all = await api.get<Download[]>("/api/downloads");
      const cur = all.find((d) => d.id === dl.id);
      if (cur) {
        setDl(cur);
        if (cur.status === "done") onInstalled?.();
      }
    }, 800);
    return () => clearTimeout(t);
  }, [dl, onInstalled]);

  const start = async () => {
    setStartError(null);
    try {
      setDl(await api.post<Download>("/api/downloads", { repo_id: repoId, variant_id: variant }));
    } catch (e) {
      setStartError((e as Error).message);
    }
  };

  const variants = data?.variants ?? [];
  // Many GGUF repos list 20+ versions. Show one per quality level unless asked for all.
  const shown = showAll
    ? variants
    : variants.filter(
        (v) =>
          v.id === variant ||
          v.id === data?.recommended ||
          v === [...variants].filter((x) => x.rank === v.rank).sort((a, b) => quantPref(a) - quantPref(b))[0],
      );

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Model details">
      <button className="absolute inset-0 bg-ink/30" onClick={onClose} aria-label="Close" />
      <div className="relative w-full max-w-[560px] h-full bg-fog border-l border-line overflow-y-auto p-6 sm:p-8">
        <button
          onClick={onClose}
          className="absolute right-4 top-4 size-10 grid place-items-center rounded-full hover:bg-well"
          aria-label="Close"
        >
          <X size={20} />
        </button>
        {error && <Notice tone="error">{error}</Notice>}
        {!data && !error && <p className="text-slate">Looking up this model…</p>}
        {data && (
          <>
            <div className="text-sm text-slate">{data.task_label ?? "Unsupported model"}</div>
            <h2 className="font-display text-[1.25rem] leading-snug mt-1 pr-10 break-words">
              {data.title}
            </h2>
            <p className="text-slate text-sm mt-1 break-all">
              Made by {data.author}, downloaded {compact(data.downloads)} times
              {data.license ? `. Licence: ${data.license}` : ""}
            </p>
            {data.why && <p className="mt-4 text-[17px]">{data.why}</p>}

            {data.supported && data.verdict && (
              <div className="mt-5 rounded-xl bg-paper border border-line p-4">
                <VerdictBadge verdict={data.verdict} detail />
                {data.needs_image && (
                  <p className="text-[13px] mt-2">This model brings a picture to life, so you&apos;ll need a starting picture.</p>
                )}
                <p className="text-[13px] text-slate mt-2">
                  {data.tested
                    ? "Tested with wanna.sh."
                    : "Not tested with wanna.sh yet. Most models like this work, but some need extra setup."}
                </p>
              </div>
            )}

            {!data.supported && (
              <div className="mt-6">
                <Notice tone="error">wanna.sh can&apos;t run this kind of model yet.</Notice>
              </div>
            )}

            {data.gated && (
              <div className="mt-6">
                <Notice>
                  The makers of this model ask you to accept their terms first. Open{" "}
                  <a className="text-accent underline" href={`https://huggingface.co/${data.repo_id}`} target="_blank">
                    its page on Hugging Face
                  </a>
                  , accept, then add your Hugging Face token in{" "}
                  <Link className="text-accent underline" href="/settings/">
                    Settings
                  </Link>
                  .
                </Notice>
              </div>
            )}

            {data.supported && variants.length > 0 && (
              <fieldset className="mt-7">
                <legend className="font-medium mb-1">Choose a version</legend>
                <p className="text-sm text-slate mb-3">
                  Smaller versions download faster and use less memory. Bigger ones are a little smarter.
                </p>
                <div className="flex flex-col gap-2">
                  {shown.map((v) => (
                    <label
                      key={v.id}
                      className={`rounded-xl border p-3.5 cursor-pointer flex gap-3 ${
                        variant === v.id ? "border-accent bg-paper" : "border-line bg-paper/60 hover:bg-paper"
                      }`}
                    >
                      <input
                        type="radio"
                        name="variant"
                        className="mt-1.5 accent-[var(--accent)]"
                        checked={variant === v.id}
                        onChange={() => setVariant(v.id)}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap justify-between gap-x-3">
                          <span className="font-medium">
                            {v.label}
                            {v.id === data.recommended && (
                              <span className="ml-2 text-[13px] font-medium text-accent">Best for you</span>
                            )}
                          </span>
                          <span className="tabular-nums text-slate">{bytes(v.size)}</span>
                        </div>
                        {v.description && <div className="text-sm text-slate">{v.description}</div>}
                        <div className="mt-1">
                          <VerdictBadge verdict={v.verdict} />
                        </div>
                        {v.vision && <div className="text-[13px] text-slate">Can also look at pictures you attach.</div>}
                      </div>
                    </label>
                  ))}
                </div>
                {variants.length > shown.length && (
                  <button className="mt-2 text-sm text-accent underline" onClick={() => setShowAll(true)}>
                    Show all {variants.length} versions
                  </button>
                )}
              </fieldset>
            )}

            <div className="mt-7 flex flex-col gap-3">
              {startError && <Notice tone="error">{startError}</Notice>}
              {data.installed.length > 0 && !dl && (
                <p className="text-sm text-ok">Already installed: {data.installed.join(", ")}</p>
              )}
              {!dl && data.supported && (
                <Button onClick={start} disabled={!variant} className="self-start">
                  Download {bytes(variants.find((v) => v.id === variant)?.size)}
                </Button>
              )}
              {dl && <DownloadRow d={dl} />}
              {dl?.status === "done" && (
                <Link href={TASKS[dl.task].href} className="self-start text-accent underline font-medium">
                  Start using {data.title}
                </Link>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function quantPref(v: Variant): number {
  // Within a quality level, prefer the widely used K-quant "M" builds.
  const q = (v.quant ?? "").toUpperCase();
  if (/^Q\d_K_M$/.test(q)) return 0;
  if (/^Q\d_K$/.test(q) || q === "Q8_0" || q === "F16" || q === "BF16") return 1;
  if (q.startsWith("UD-")) return 3;
  return 2;
}

export function DownloadRow({ d, onCancel }: { d: Download; onCancel?: () => void }) {
  const label =
    d.status === "done"
      ? `${d.title} is ready`
      : d.status === "error"
        ? `${d.title} failed`
        : d.status === "cancelled"
          ? `${d.title} cancelled`
          : `Downloading ${d.title}`;
  return (
    <div className="rounded-xl bg-paper border border-line p-4">
      <Progress value={d.status === "done" ? 1 : d.progress} label={label} />
      <div className="flex justify-between items-center text-[13px] text-slate mt-1.5">
        <span className="tabular-nums">
          {bytes(d.done)} of {bytes(d.total)}
          {d.status === "downloading" && d.speed > 0 ? ` at ${bytes(d.speed)}/s` : ""}
        </span>
        {onCancel && (d.status === "downloading" || d.status === "queued") && (
          <button onClick={onCancel} className="text-danger underline">
            Cancel
          </button>
        )}
      </div>
      {d.error && <p className="text-sm text-danger mt-2">{d.error}</p>}
    </div>
  );
}
