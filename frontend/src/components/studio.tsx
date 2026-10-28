"use client";

/*
  The shared layout for every creation page (pictures, video, voice, transcription, music):
  a feed of results that grows upwards, and one prompt bar pinned to the bottom with the
  main options as small chips. Rare settings live in a side panel.
*/

import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ArrowUp, Check, ChevronDown, Download, RotateCcw, SlidersHorizontal, Square, Trash2, X } from "lucide-react";
import type { InstalledModel, Job, Task } from "@/lib/api";
import { useSystem } from "@/lib/hooks";
import { gpuName, prettyName } from "@/lib/format";
import { TASKS } from "@/lib/tasks";
import { LiveDot, Progress } from "./ui";

// --- page frame -----------------------------------------------------------------

export function StudioPage({
  title,
  hasItems,
  empty,
  feed,
  bar,
  scrollKey,
}: {
  title: string;
  hasItems: boolean;
  /** Changes when a new item or job appears; the page then scrolls to the newest. */
  scrollKey: string | number;
  empty: ReactNode;
  feed: ReactNode;
  bar: ReactNode;
}) {
  // Bring the newest result into view, like a chat. Only when something new arrives, not on every poll.
  // Scrolling the page to its very bottom leaves the pinned prompt bar below the last item, not over it.
  useEffect(() => {
    window.scrollTo({ top: document.documentElement.scrollHeight });
  }, [scrollKey]);
  return (
    <div className="flex flex-col min-h-[calc(100dvh-5.5rem)] lg:min-h-[calc(100dvh-4rem)] max-w-[880px] mx-auto">
      <header className="sticky top-14 lg:top-0 z-20 -mx-1 px-1 flex flex-wrap items-center justify-between gap-3 py-3 bg-fog/90 backdrop-blur-md">
        <h1 className="font-display text-[1.25rem]">{title}</h1>
      </header>
      <div className="flex-1">{hasItems ? feed : empty}</div>
      <div className="sticky bottom-0 z-10 pt-6 pb-3 lg:pb-5 bg-gradient-to-t from-fog from-70% to-transparent">
        {bar}
      </div>
    </div>
  );
}

/** What a page shows before you've made anything: its painting, a sentence, and example prompts. */
export function StudioEmpty({
  task,
  headline,
  examples = [],
  onExample,
  children,
}: {
  task: Task;
  headline: string;
  examples?: string[];
  onExample?: (text: string) => void;
  children?: ReactNode;
}) {
  return (
    <div className="max-w-[620px] mx-auto text-center pt-2 pb-6">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`/art/${task}.webp`} alt="" className="w-full aspect-[1344/768] object-cover rounded-2xl" />
      <h2 className="font-display text-[1.5rem] mt-7">{headline}</h2>
      <p className="text-slate mt-1.5">{TASKS[task].help}</p>
      {examples.length > 0 && (
        <div className="mt-6 grid gap-2 sm:grid-cols-2 text-left">
          {examples.map((e) => (
            <button
              key={e}
              type="button"
              onClick={() => onExample?.(e)}
              className="rounded-xl border border-line px-4 py-3 text-[15px] text-slate hover:text-ink hover:bg-well/60 transition-colors"
            >
              {e}
            </button>
          ))}
        </div>
      )}
      {children}
    </div>
  );
}

// --- prompt bar -------------------------------------------------------------------

export function PromptBar({
  value,
  onChange,
  placeholder,
  onSubmit,
  submitLabel,
  canSubmit,
  busy,
  top,
  tools,
  onMore,
  onStop,
  actions,
  onFiles,
  children,
}: {
  /** Omit value/onChange for bars without a text box (e.g. transcription), and pass children instead. */
  value?: string;
  onChange?: (v: string) => void;
  placeholder?: string;
  onSubmit: () => void;
  submitLabel: string;
  canSubmit: boolean;
  busy?: boolean;
  /** Shown above the text box, e.g. an attached picture. */
  top?: ReactNode;
  /** Chips and buttons in the bottom row. */
  tools?: ReactNode;
  onMore?: () => void;
  /** While busy, show a Stop button that calls this (e.g. to stop a chat reply). */
  onStop?: () => void;
  /** Buttons shown just before the submit button, e.g. a microphone. */
  actions?: ReactNode;
  /** Receives files pasted into the text box or dropped onto the bar. */
  onFiles?: (files: File[]) => void;
  children?: ReactNode;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  const [dragging, setDragging] = useState(false);
  useLayoutEffect(() => {
    // Grow with the text, up to about eight lines.
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [value]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit && !busy) onSubmit();
      }}
      onDragOver={(e) => {
        if (!onFiles || !e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false);
      }}
      onDrop={(e) => {
        if (!onFiles) return;
        e.preventDefault();
        setDragging(false);
        const files = [...e.dataTransfer.files];
        if (files.length) onFiles(files);
      }}
      className={`relative rounded-[1.6rem] bg-paper border transition-colors shadow-[0_8px_30px_rgba(0,0,0,0.25)] ${
        dragging ? "border-ink border-dashed" : "border-line focus-within:border-slate/60"
      }`}
    >
      {dragging && (
        <div className="absolute inset-0 z-10 grid place-items-center rounded-[1.6rem] bg-paper/90 text-[15px] pointer-events-none">
          Drop to attach
        </div>
      )}
      {top && <div className="px-3 pt-3">{top}</div>}
      {onChange ? (
        <textarea
          ref={area}
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onPaste={(e) => {
            const files = [...e.clipboardData.files];
            if (onFiles && files.length) {
              e.preventDefault();
              onFiles(files);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (canSubmit && !busy) onSubmit();
            }
          }}
          placeholder={placeholder}
          aria-label={placeholder}
          className="block w-full resize-none bg-transparent px-5 pt-4 pb-2 text-[16px] placeholder:text-slate/80 focus:outline-none focus-visible:outline-none"
        />
      ) : (
        <div className="px-4 pt-4 pb-2">{children}</div>
      )}
      <div className="flex items-center gap-1.5 px-2.5 pb-2.5 flex-wrap">
        {tools}
        <div className="ml-auto flex items-center gap-1.5">
          {onMore && (
            <button
              type="button"
              onClick={onMore}
              className="h-9 px-3 inline-flex items-center gap-1.5 rounded-full text-[14px] text-slate hover:text-ink hover:bg-well transition-colors"
            >
              <SlidersHorizontal size={15} aria-hidden /> <span className="max-sm:sr-only">More settings</span>
            </button>
          )}
          {actions}
          {busy && onStop ? (
            <button
              type="button"
              onClick={onStop}
              className="h-9 pl-3 pr-4 inline-flex items-center gap-2 rounded-full bg-well text-ink text-[14px] font-medium hover:opacity-80"
            >
              <Square size={12} fill="currentColor" aria-hidden /> Stop
            </button>
          ) : (
          <button
            type="submit"
            disabled={!canSubmit || busy}
            className="h-9 pl-4 pr-3 inline-flex items-center gap-1.5 rounded-full bg-accent text-accent-ink text-[14px] font-medium hover:opacity-85 disabled:opacity-35 disabled:cursor-not-allowed transition-opacity"
          >
            {busy ? "Working…" : submitLabel}
            <ArrowUp size={16} aria-hidden />
          </button>
          )}
        </div>
      </div>
    </form>
  );
}

// --- chips --------------------------------------------------------------------------

function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return ref;
}

const chipClass =
  "h-9 px-3 inline-flex items-center gap-1.5 rounded-full border border-line text-[14px] hover:bg-well transition-colors";

/** "Shape  Square ▾": a small button that opens a menu of choices. */
export function OptionChip<T extends string>({
  label,
  value,
  options,
  onChange,
  icon,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; hint?: string }[];
  onChange: (v: T) => void;
  icon?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const current = options.find((o) => o.value === value);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`${label}: ${current?.label}`}
        className={chipClass}
      >
        {icon}
        <span className="text-slate">{label}</span>
        <span>{current?.label}</span>
        <ChevronDown size={14} className="text-slate" aria-hidden />
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label={label}
          className="absolute bottom-full mb-2 left-0 z-30 min-w-[200px] rounded-xl border border-line bg-paper p-1 shadow-[0_12px_40px_rgba(0,0,0,0.35)]"
        >
          {options.map((o) => (
            <li key={o.value}>
              <button
                type="button"
                role="option"
                aria-selected={o.value === value}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                className="w-full flex items-start gap-2 rounded-lg px-2.5 py-2 text-left text-[14px] hover:bg-well"
              >
                <Check size={15} className={`mt-0.5 shrink-0 ${o.value === value ? "" : "invisible"}`} aria-hidden />
                <span>
                  {o.label}
                  {o.hint && <span className="block text-[13px] text-slate">{o.hint}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** An on/off chip, e.g. "Translate to English". */
export function ToggleChip({ on, onChange, children }: { on: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={() => onChange(!on)}
      className={`${chipClass} ${on ? "bg-well border-slate/50" : ""}`}
    >
      {on && <Check size={14} aria-hidden />}
      {children}
    </button>
  );
}

/** A plain chip-shaped button, e.g. "Attach picture". */
export function ChipButton({ onClick, children, label }: { onClick: () => void; children: ReactNode; label?: string }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} className={chipClass}>
      {children}
    </button>
  );
}

// --- side panel ------------------------------------------------------------------------

export function SidePanel({ title, open, onClose, children }: { title: string; open: boolean; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={title}>
      <button className="absolute inset-0 bg-black/40" onClick={onClose} aria-label="Close" />
      <div className="relative w-full max-w-[400px] h-full bg-fog border-l border-line overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="font-display text-[1.15rem]">{title}</h2>
          <button onClick={onClose} className="size-9 grid place-items-center rounded-full hover:bg-well" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="flex flex-col gap-5">{children}</div>
      </div>
    </div>
  );
}

// --- feed -------------------------------------------------------------------------------

/** One thing you made: your prompt, the result, and what you can do with it. */
export function FeedItem({
  prompt,
  meta,
  children,
  saveUrl,
  onReuse,
  onDelete,
}: {
  prompt: string;
  meta?: string;
  children: ReactNode;
  saveUrl?: string;
  onReuse?: () => void;
  onDelete?: () => void;
}) {
  return (
    <article className="py-5 border-b border-line last:border-0">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-x-4 gap-y-1 mb-3">
        <p className="text-[15px] min-w-0 break-words">{prompt || <span className="text-slate">No description</span>}</p>
        {meta && <span className="text-[13px] text-slate shrink-0">{meta}</span>}
      </div>
      {children}
      {(saveUrl || onReuse || onDelete) && (
        <div className="flex gap-1 mt-2 -ml-2">
          {saveUrl && (
            <a href={saveUrl} download className="h-8 px-2.5 inline-flex items-center gap-1.5 rounded-full text-[13px] text-slate hover:text-ink hover:bg-well">
              <Download size={14} aria-hidden /> Save
            </a>
          )}
          {onReuse && (
            <button onClick={onReuse} className="h-8 px-2.5 inline-flex items-center gap-1.5 rounded-full text-[13px] text-slate hover:text-ink hover:bg-well">
              <RotateCcw size={14} aria-hidden /> Use again
            </button>
          )}
          {onDelete && (
            <button onClick={onDelete} className="h-8 px-2.5 inline-flex items-center gap-1.5 rounded-full text-[13px] text-slate hover:text-danger hover:bg-well">
              <Trash2 size={14} aria-hidden /> Delete
            </button>
          )}
        </div>
      )}
    </article>
  );
}

/** The item for a job that's still running. */
export function PendingItem({ job, noun }: { job: Job; noun: string }) {
  const label =
    job.status === "queued"
      ? "Waiting for a turn…"
      : job.status === "loading"
        ? "Starting the model. The first time takes a little longer…"
        : job.total_steps
          ? `Making your ${noun}, step ${Math.min(job.step, job.total_steps)} of ${job.total_steps}`
          : `Making your ${noun}…`;
  return (
    <article className="py-5" role="status">
      <p className="text-[15px] mb-3 break-words">{job.prompt}</p>
      <div className="rounded-xl bg-paper border border-line p-4">
        <Progress value={job.status === "running" ? Math.max(0.03, job.progress) : 0.02} label={label} live />
      </div>
    </article>
  );
}

// --- model menu --------------------------------------------------------------------------

/** A friendly name for an installed model: its curated title, or a tidied repo name. */
export function modelName(m: InstalledModel): string {
  return prettyName(m.meta.title || m.repo_id);
}

export function ModelMenu({
  models,
  value,
  onChange,
  task,
  note,
}: {
  models: InstalledModel[];
  value: string;
  onChange: (id: string) => void;
  task: Task;
  /** Extra words for each model's status line, e.g. "Can use tools". */
  note?: (m: InstalledModel) => string | null;
}) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const { data: sys } = useSystem(4000);
  const current = models.find((m) => m.id === value);
  const where = (m: InstalledModel) => {
    const w = m.loaded;
    if (!w) return m.last_error ? "Couldn't start last time" : "Starts when you use it";
    const on = w.gpus.length
      ? w.gpus.map((i) => gpuName(sys?.gpus.find((g) => g.index === i)?.name ?? `GPU ${i}`)).join(" + ")
      : "the processor";
    return w.status === "loading" ? `Starting on ${on}…` : `Ready on ${on}`;
  };
  if (!current) return null;
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Model: ${modelName(current)}`}
        className="h-9 pl-3 pr-2.5 inline-flex items-center gap-1.5 rounded-full border border-line text-[14px] hover:bg-well transition-colors max-w-[280px]"
      >
        <LiveDot status={current.loaded?.status} />
        <span className="text-slate">Model</span>
        <span className="truncate">{modelName(current)}</span>
        <ChevronDown size={14} className="text-slate shrink-0" aria-hidden />
      </button>
      {open && (
        <div className="absolute left-0 bottom-full mb-2 z-30 w-[320px] max-w-[calc(100vw-2rem)] rounded-xl border border-line bg-paper p-1 shadow-[0_12px_40px_rgba(0,0,0,0.35)]">
          <ul role="listbox" aria-label="Model">
            {models.map((m) => (
              <li key={m.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={m.id === value}
                  onClick={() => {
                    onChange(m.id);
                    setOpen(false);
                  }}
                  className="w-full flex items-start gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-well"
                >
                  <Check size={15} className={`mt-1 shrink-0 ${m.id === value ? "" : "invisible"}`} aria-hidden />
                  <span className="min-w-0">
                    <span className="block text-[14px] truncate">
                      {modelName(m)}
                      {m.meta.quant && <span className="text-slate"> {m.meta.quant}</span>}
                    </span>
                    <span className="flex items-center gap-1.5 text-[13px] text-slate">
                      <LiveDot status={m.loaded?.status} />
                      {where(m)}
                      {task === "chat" && m.meta.mmproj ? ". Sees pictures" : ""}
                      {note?.(m) ? `. ${note(m)}` : ""}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="border-t border-line mt-1 pt-1">
            <Link
              href={`/discover/?task=${task}`}
              className="block rounded-lg px-2.5 py-2 text-[14px] text-slate hover:text-ink hover:bg-well"
            >
              Get more {TASKS[task].noun}s
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
