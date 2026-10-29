"use client";

import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Task, Verdict } from "@/lib/api";

type Tone = "primary" | "quiet" | "danger";

export function Button({
  tone = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone }) {
  const tones: Record<Tone, string> = {
    primary: "bg-accent text-accent-ink hover:opacity-85 disabled:opacity-40",
    quiet: "bg-transparent text-ink border border-line hover:bg-well disabled:opacity-40",
    danger: "bg-transparent text-danger border border-line hover:bg-well disabled:opacity-40",
  };
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-full px-4 h-9 text-[14px] font-medium transition-[opacity,background-color] disabled:cursor-not-allowed ${tones[tone]} ${className}`}
      {...props}
    />
  );
}

// Where each painting's subject sits, so wide banners crop around it rather than through it.
const ART_FOCUS: Partial<Record<Task, string>> = {
  image: "60% 30%",
  chat: "center 65%",
  speech: "40% 50%",
  transcribe: "center 70%",
  sound: "center 75%",
  video: "center 60%",
  embed: "center 55%",
};

/** Page title. With `art`, a task's painting sits behind it as a wide banner. */
export function PageHeader({
  title,
  intro,
  art,
  children,
}: {
  title: string;
  intro?: ReactNode;
  art?: Task;
  children?: ReactNode;
}) {
  return (
    <header className="mb-10">
      {art && (
        <div className="relative mb-7 h-[140px] sm:h-[180px] rounded-2xl overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`/art/${art}.webp`}
            alt=""
            className="absolute inset-0 size-full object-cover"
            style={{ objectPosition: ART_FOCUS[art] ?? "center" }}
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/45 via-black/5 to-transparent" aria-hidden />
        </div>
      )}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-[62ch]">
          <h1 className="font-display text-[1.75rem] leading-tight">{title}</h1>
          {intro && <p className="text-slate mt-2">{intro}</p>}
        </div>
        {children}
      </div>
    </header>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string; hint?: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap rounded-full bg-well p-0.5 gap-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          title={o.hint}
          onClick={() => onChange(o.value)}
          className={`rounded-full px-3.5 h-8 text-[13px] font-medium transition-colors ${
            value === o.value ? "bg-paper text-ink border border-line" : "text-slate hover:text-ink border border-transparent"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[13px] font-medium mb-1.5">{label}</span>
      {children}
      {hint && <span className="block text-[13px] text-slate mt-1">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-xl bg-paper border border-line px-3.5 py-2.5 text-[14px] placeholder:text-slate/70 focus:outline-none focus:border-slate transition-colors";

export function Progress({ value, label, live }: { value: number; label?: string; live?: boolean }) {
  return (
    <div>
      {label && (
        <div className="flex justify-between text-sm mb-1.5">
          <span>{label}</span>
          <span className="text-slate tabular-nums">{Math.round(value * 100)}%</span>
        </div>
      )}
      <div
        className="h-1.5 rounded-full bg-well overflow-hidden"
        role="progressbar"
        aria-valuenow={Math.round(value * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${live ? "bg-marigold" : "bg-accent"}`}
          style={{ width: `${Math.max(2, value * 100)}%` }}
        />
      </div>
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error"; children: ReactNode }) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-xl px-4 py-3 text-[15px] border ${
        tone === "error" ? "border-danger/40 text-danger bg-paper" : "border-line bg-paper text-ink"
      }`}
    >
      {children}
    </div>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl bg-paper border border-line p-5 ${className}`}>{children}</section>;
}

export function LinkButton({ href, children, tone = "primary" }: { href: string; children: ReactNode; tone?: Tone }) {
  const tones: Record<Tone, string> = {
    primary: "bg-accent text-accent-ink hover:opacity-85",
    quiet: "bg-transparent text-ink border border-line hover:bg-well",
    danger: "bg-transparent text-danger border border-line",
  };
  return (
    <Link
      href={href}
      className={`inline-flex items-center gap-2 rounded-full px-4 h-9 text-[14px] font-medium transition-opacity ${tones[tone]}`}
    >
      {children}
    </Link>
  );
}

/** A small dot that marks a model as running. Marigold is reserved for this. */
export function LiveDot({ status }: { status: "loading" | "ready" | "error" | "stopped" | undefined }) {
  if (!status || status === "stopped") return null;
  const cls =
    status === "ready" ? "bg-marigold" : status === "loading" ? "bg-marigold animate-pulse" : "bg-danger";
  return <span className={`inline-block size-2 rounded-full ${cls}`} aria-hidden />;
}

// How well a model fits this computer, as a small gauge: bars filled, and their colour. Colour only warns.
const VERDICT_GAUGE: Record<Verdict["level"], [number, string]> = {
  great: [3, "bg-ink"],
  good: [3, "bg-ink"],
  slow: [2, "bg-caution"],
  no: [1, "bg-danger"],
  unknown: [0, ""],
};

/** "Runs great here" and friends: whether a model will work on this computer. */
export function VerdictBadge({ verdict, detail = false }: { verdict: Verdict | null | undefined; detail?: boolean }) {
  if (!verdict) return null;
  const [filled, fill] = VERDICT_GAUGE[verdict.level];
  return (
    <div>
      <span className="inline-flex items-center gap-2 text-[13px] text-ink">
        <span className="inline-flex items-end gap-[2px]" aria-hidden>
          {[5, 8, 11].map((h, i) => (
            <span key={h} className={`w-[3px] rounded-[1px] ${i < filled ? fill : "bg-line"}`} style={{ height: h }} />
          ))}
        </span>
        {verdict.label}
      </span>
      {detail && <p className="text-[13px] text-slate mt-0.5">{verdict.detail}</p>}
    </div>
  );
}
