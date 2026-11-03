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
  type SpeedEstimate,
  type Task,
  type Variant,
  type Verdict,
} from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes, compact, duration, tokenSpeed } from "@/lib/format";
import { TASKS } from "@/lib/tasks";
import { Button, Notice, Progress, VerdictBadge } from "./ui";
import { MlAddon } from "./addons";

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
      {task !== "chat" && task !== "embed" && <MlAddon />}
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
              <div className="mt-1">
                <VerdictBadge verdict={p.verdict} />
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
  // Versions that would run from the drive need a deliberate yes before downloading.
  const [estimate, setEstimate] = useState<SpeedEstimate | null>(null);
  const [understood, setUnderstood] = useState(false);

  const variant = picked ?? data?.recommended ?? null;
  const chosen = data?.variants.find((v) => v.id === variant);
  const lowBits = chosen && (chosen.rank <= 1 || (chosen.bits != null && chosen.bits < 3));
  const fromDrive = estimate?.mode === "drive";
  const shownVerdict = (v: Variant) => (v.id === chosen?.id ? fromEstimate(v.verdict, estimate) : v.verdict);

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
                <VerdictBadge verdict={chosen ? shownVerdict(chosen) : data.verdict} detail />
                {data.edits ? (
                  <p className="text-[13px] mt-2">
                    {data.needs_image
                      ? "This model changes pictures you give it, as you describe. It needs a picture to start from."
                      : "This model makes pictures from a description, and can also change a picture you give it."}
                    {(data.max_images ?? 1) > 1 &&
                      ` It can combine up to ${data.max_images} pictures, for example two people in one scene.`}
                  </p>
                ) : (
                  data.needs_image && (
                    <p className="text-[13px] mt-2">This model brings a picture to life, so you&apos;ll need a starting picture.</p>
                  )
                )}
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
                  <Link className="text-accent underline" href="/settings/accounts/">
                    Settings → Accounts
                  </Link>
                  .
                </Notice>
              </div>
            )}

            {data.supported && variants.length > 0 && (
              <fieldset className="mt-7">
                <legend className="font-medium mb-1">Choose a version</legend>
                <p className="text-sm text-slate mb-3">
                  {data.engine === "llamacpp"
                    ? "Each version is the same model compressed by a different amount (quantized). Fewer bits per weight make it smaller and faster but less accurate: about 4 bits or more is close to the original, below 3 the drop is noticeable."
                    : "Smaller versions download faster and use less memory. Bigger ones are a little smarter."}
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
                        onChange={() => {
                          setVariant(v.id);
                          setUnderstood(false);
                        }}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap justify-between gap-x-3">
                          <span className="font-medium">
                            {v.label}
                            {v.id === data.recommended && (
                              <span className="ml-2 text-[13px] font-medium text-accent">Best for you</span>
                            )}
                          </span>
                          <span className="tabular-nums text-slate">
                            {v.bits ? `${v.bits} bits, ` : ""}
                            {bytes(v.size)}
                          </span>
                        </div>
                        {v.description && <div className="text-sm text-slate">{v.description}</div>}
                        <div className="mt-1">
                          <VerdictBadge verdict={shownVerdict(v)} />
                        </div>
                        {v.vision && <div className="text-[13px] text-slate">Can also look at pictures you attach.</div>}
                        {v.fits_disk === false && (
                          <div className="text-[13px] text-danger">
                            Bigger than the {bytes(data.disk_free)} free on the drive models are saved to.
                          </div>
                        )}
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

            {data.supported && data.task === "chat" && chosen && (
              <div className="mt-5 flex flex-col gap-3">
                {lowBits && (
                  <Notice>
                    This version is heavily compressed
                    {chosen.bits ? ` (about ${chosen.bits} bits per weight)` : ""}. It is much smaller, but it makes
                    noticeably more mistakes than the original, especially with facts, maths and code. Pick a version
                    with 4 or more bits if your computer can hold it.
                  </Notice>
                )}
                <SpeedEstimateView
                  key={chosen.id}
                  path={`/api/hub/estimate?repo_id=${encodeURIComponent(repoId)}&variant_id=${encodeURIComponent(chosen.id)}`}
                  onEstimate={setEstimate}
                />
                {fromDrive && (
                  <label className="flex items-start gap-3 text-[15px]">
                    <input
                      type="checkbox"
                      checked={understood}
                      onChange={(e) => setUnderstood(e.target.checked)}
                      className="mt-1 size-4 accent-[var(--accent)]"
                    />
                    <span>I understand this version is bigger than my computer&apos;s memory and will reply very slowly.</span>
                  </label>
                )}
                {fromDrive && !estimate?.setting_on && (
                  <Notice>
                    To run it, turn on &ldquo;Run models bigger than memory&rdquo; in{" "}
                    <Link className="text-accent underline" href="/settings/models/">
                      Settings → Models &amp; memory
                    </Link>
                    . You can download it first.
                  </Notice>
                )}
              </div>
            )}

            <div className="mt-7 flex flex-col gap-3">
              {startError && <Notice tone="error">{startError}</Notice>}
              {data.installed.length > 0 && !dl && (
                <p className="text-sm text-ok">Already installed: {data.installed.join(", ")}</p>
              )}
              {!dl && data.supported && (
                <Button
                  onClick={start}
                  disabled={!variant || (fromDrive && !understood) || chosen?.fits_disk === false}
                  className="self-start"
                >
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

/** How fast a chat model runs here. For one bigger than memory, what reading it from the drive means in practice. */
export function SpeedEstimateView({
  path,
  onEstimate,
}: {
  path: string;
  onEstimate?: (e: SpeedEstimate | null) => void;
}) {
  const { data, error, refresh } = usePoll<SpeedEstimate>(path);
  useEffect(() => {
    // The drive is measured the first time it matters (about ten seconds); check back until it's done.
    if (!data?.measuring_drive) return;
    const t = setTimeout(refresh, 2000);
    return () => clearTimeout(t);
  }, [data, refresh]);
  useEffect(() => onEstimate?.(data), [data, onEstimate]);

  if (error) return <p className="text-[13px] text-slate">Couldn&apos;t estimate its speed here: {error}</p>;
  if (!data) return <p className="text-[13px] text-slate">Working out how fast it runs on this computer…</p>;
  const measured = data.measured_tokens_per_second;
  if (data.mode !== "drive") {
    const tps = measured ?? data.tokens_per_second;
    if (!tps) return null;
    return (
      <p className="text-[14px]">
        {measured ? "Measured here" : "Estimated here"}: {tokenSpeed(tps)}
        {data.mode === "ram" && !measured ? ", with part of it on the processor" : ""}.
      </p>
    );
  }
  const perToken = data.bytes_per_token.drive;
  const spt = data.seconds_per_token;
  return (
    <div className="rounded-xl bg-paper border border-caution/50 p-4 text-[14px] flex flex-col gap-2">
      <div className="font-medium text-[15px]">Runs from your drive</div>
      <p>
        At {bytes(data.model_bytes)} it is bigger than your graphics and system memory, so for each token it reads
        what they can&apos;t hold from your drive.{" "}
        {data.moe
          ? `It is a mixture-of-experts model: each token uses ${data.experts.used} of its ${data.experts.total} experts, so it reads about ${bytes(perToken)} a token rather than the whole model.`
          : `It isn't a mixture-of-experts model, so every token needs all of its weights: about ${bytes(perToken)} a token from the drive. Models like this are impractically slow from a drive.`}
      </p>
      {data.windows_drive_under_wsl && (
        <p>
          Your models are on a Windows drive, which WSL reads through file sharing: starting this one reads the whole
          model that way, which is very slow. From WSL&apos;s own disk it starts much sooner, but may write more slowly.
          Giving WSL more memory (in .wslconfig) helps either way.
        </p>
      )}
      {data.measuring_drive && <p className="text-slate">Measuring your drive&apos;s speed (about ten seconds)…</p>}
      {data.drive_error && !data.measuring_drive && (
        <p className="text-danger">Couldn&apos;t measure your drive: {data.drive_error}</p>
      )}
      {spt != null && (
        <ul className="list-disc pl-5 flex flex-col gap-1">
          {measured ? (
            <li>
              Writing: measured here at {tokenSpeed(measured)}. A 300-token reply (about 225 words) takes about{" "}
              {duration(300 / measured)}.
            </li>
          ) : (
            <li>
              Writing: {speedRange(1 / spt, data.tokens_per_second_fast)}. A 300-token reply (about 225 words) takes{" "}
              {durationRange(300 * spt, data.tokens_per_second_fast ? 300 / data.tokens_per_second_fast : null)}. The
              faster end is for models that keep using the same experts, and conversations that stay on one topic.
            </li>
          )}
          {data.short_prompt_seconds != null && (
            <li>
              Before it replies it reads your message: about {duration(data.short_prompt_seconds)} for a short one
              {data.prompt_seconds != null ? `, about ${duration(data.prompt_seconds)} for every 400 words` : ""}. The
              earlier conversation counts the first time
              {data.first_prompt_seconds != null && data.first_prompt_seconds > data.short_prompt_seconds * 1.25
                ? `, and the first message after it starts takes ${duration(data.first_prompt_seconds)} or more`
                : ""}
              .
            </li>
          )}
          {data.start_seconds != null && data.start_seconds > 30 && <li>Starting: about {duration(data.start_seconds)}.</li>}
        </ul>
      )}
      {data.speeds.drive != null && (
        <p className="text-[13px] text-slate">
          Estimated from this computer: drive {bytes(data.speeds.drive)}/s as a model reads it, memory{" "}
          {bytes(data.speeds.ram)}/s, and {Math.round(data.memory_hit * 100)}% of the experts it needs found in memory
          when it uses them all equally. Reading doesn&apos;t wear out an SSD, but the drive stays busy, so other
          programs may feel slower. A hard disk would be far slower still.
        </p>
      )}
    </div>
  );
}

/** "about 1 to 3 tokens a second", or one figure when the two are close. */
function speedRange(slow: number, fast: number | null): string {
  if (!fast || fast < slow * 1.25) return tokenSpeed(slow);
  if (slow >= 1) return `about ${slow.toFixed(1)} to ${fast >= 10 ? Math.round(fast) : fast.toFixed(1)} tokens a second`;
  return `between ${tokenSpeed(slow).replace("about ", "")} and ${tokenSpeed(fast).replace("about ", "")}`;
}

/** "about 2 to 5 minutes", or one figure when the two round the same. */
function durationRange(long: number, short: number | null): string {
  if (!short || duration(short) === duration(long)) return `about ${duration(long)}`;
  return `about ${duration(short)} to ${duration(long)}`;
}

/**
 * The rating for a version once its file has been read. Ratings in lists go by size alone; the estimate knows what
 * each token really uses, so a model whose size suggests the drive may fit in memory after all, and the other way round.
 */
function fromEstimate(sized: Verdict | null, e: SpeedEstimate | null): Verdict | null {
  if (!sized || !e) return sized;
  const bySize = sized.level === "disk" || sized.level === "no";
  if (e.mode === "drive" && !bySize) {
    return {
      ...sized,
      level: "disk",
      label: "Runs from your drive, very slowly",
      detail: "Each token needs more than your graphics and system memory can hold, so it reads the rest from your drive.",
      drive_possible: !e.setting_on,
    };
  }
  if (e.mode !== "drive" && bySize) {
    return {
      ...sized,
      level: e.mode === "gpu" ? "good" : "slow",
      label: e.mode === "gpu" ? "Runs well here" : "Runs, but slowly",
      detail:
        "It needs less memory than its size suggests: part of the file is only looked up a little at a time, so it fits in your graphics and system memory" +
        (e.mode === "ram" ? ", with part of it on the processor." : "."),
      drive_possible: false,
    };
  }
  return sized;
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
