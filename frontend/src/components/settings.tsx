"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { CircleAlert, CircleCheck, CircleX, KeyRound, Loader2, MemoryStick, Monitor, ShieldCheck } from "lucide-react";
import { api, type SystemCheckItem } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { ago, bytes } from "@/lib/format";
import { Button, Notice, Panel, inputClass } from "./ui";

export interface Settings {
  hf_token: string;
  hf_token_set: boolean;
  brave_api_key: string;
  brave_api_key_set: boolean;
  require_api_key: boolean;
  allowed_hosts: string[];
  allowed_hosts_env: string[];
  idle_unload_minutes: number;
  default_context: number;
  stream_from_drive: boolean;
}

interface DriveSpeed {
  drive: { mapped?: number; direct?: number; error?: string; at: number } | null;
  measuring: boolean;
  windows_drive_under_wsl: boolean;
}

/** The sub-pages of Settings, in menu order. Docs refer to them by these names ("Settings → Security"). */
export const SETTINGS_PAGES = [
  { href: "/settings/", label: "This computer", icon: Monitor, blurb: "System check, graphics cards and engines" },
  { href: "/settings/accounts/", label: "Accounts", icon: KeyRound, blurb: "Hugging Face, web search" },
  { href: "/settings/models/", label: "Models & memory", icon: MemoryStick, blurb: "Idle models, chat memory, big models" },
  { href: "/settings/security/", label: "Security", icon: ShieldCheck, blurb: "API key, allowed host names" },
] as const;

/** The Settings menu: a list down the side on wide screens, a row of tabs on narrow ones. */
export function SettingsNav() {
  const path = usePathname();
  const here = (href: string) => (href === "/settings/" ? path === "/settings/" || path === "/settings" : path.startsWith(href));
  return (
    <nav aria-label="Settings" className="lg:sticky lg:top-6 self-start">
      <ul className="flex lg:flex-col gap-1 overflow-x-auto -mx-1 px-1 pb-1 lg:pb-0">
        {SETTINGS_PAGES.map(({ href, label, icon: Icon, blurb }) => (
          <li key={href} className="shrink-0">
            <Link
              href={href}
              aria-current={here(href) ? "page" : undefined}
              className={`flex items-start gap-2.5 rounded-xl px-3 py-2 text-[15px] transition-colors ${
                here(href) ? "bg-well text-ink font-medium" : "text-slate hover:bg-well hover:text-ink"
              }`}
            >
              <Icon size={17} className="mt-0.5 shrink-0" aria-hidden />
              <span>
                {label}
                <span className="hidden lg:block text-[13px] font-normal text-slate">{blurb}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** Settings from the server, a way to save changes, and whether the last change was saved. */
export function useSettings() {
  const [s, setS] = useState<Settings | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Settings>("/api/settings").then(setS).catch((e) => setError(e.message));
  }, []);

  const save = async (patch: Partial<Settings>) => {
    setError(null);
    try {
      setS(await api.put<Settings>("/api/settings", patch));
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return { s, save, saved, error };
}

/** "Saved" after a change, or what went wrong. */
export function SaveStatus({ saved, error }: { saved: boolean; error: string | null }) {
  return (
    <div aria-live="polite" className="min-h-0">
      {error && <Notice tone="error">{error}</Notice>}
      {saved && <p className="text-ok font-medium text-[15px]">Saved</p>}
    </div>
  );
}

export function SectionTitle({ children, className = "mb-1" }: { children: React.ReactNode; className?: string }) {
  return <h2 className={`font-display text-[1.25rem] leading-snug ${className}`}>{children}</h2>;
}

/** Chat models bigger than graphics and system memory together: off unless the person chooses it. */
export function BigModels({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  const { data, refresh } = usePoll<DriveSpeed>("/api/hardware/drive");
  useEffect(() => {
    if (!data?.measuring) return;
    const t = setTimeout(refresh, 2000);
    return () => clearTimeout(t);
  }, [data, refresh]);
  const d = data?.drive;
  return (
    <Panel>
      <SectionTitle>Models bigger than memory</SectionTitle>
      <p className="text-slate text-[15px]">
        A chat model bigger than your graphics and system memory together can still run: it reads what doesn&apos;t
        fit from your drive while it writes. That is very slow, from a few tokens a second to one every few seconds or
        more, and best for mixture-of-experts models, which use only part of themselves for each token. Before you
        download one, wanna.sh estimates its speed on this computer.
      </p>
      <label className="flex items-start gap-3 mt-4 text-[15px]">
        <input
          type="checkbox"
          checked={on}
          onChange={(e) => onChange(e.target.checked)}
          className="mt-1 size-4 accent-[var(--accent)]"
        />
        <span>
          <span className="font-medium">Run models bigger than memory</span>
          <span className="block text-slate">
            Your drive stays busy while they run, so other programs may feel slower. Reading doesn&apos;t wear out an
            SSD. On a hard disk it is far too slow to be useful.
          </span>
        </span>
      </label>
      {data?.windows_drive_under_wsl && (
        <p className="mt-4 text-[14px]">
          Your models are on a Windows drive, which WSL reads through file sharing. A model bigger than memory can take
          a quarter of an hour or more to start from there; from WSL&apos;s own disk (move wanna.sh&apos;s data folder
          there with WANNA_HOME) it starts much sooner, but may write more slowly. Giving WSL more memory (in
          .wslconfig) helps either way.
        </p>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-[14px] text-slate">
        <span>
          {data?.measuring
            ? "Measuring the drive models are saved on (about ten seconds)…"
            : d?.mapped
              ? `The drive models are saved on reads ${bytes(d.mapped)}/s the way a model reads it (${bytes(d.direct)}/s at best), measured ${ago(d.at)}.`
              : d?.error
                ? `Couldn't measure the drive models are saved on: ${d.error}`
                : "The drive models are saved on hasn't been measured yet."}
        </span>
        {!data?.measuring && (
          <button
            className="underline underline-offset-2 hover:text-ink"
            onClick={() => api.post("/api/hardware/drive/measure").then(refresh)}
          >
            {d ? "Measure again" : "Measure it"}
          </button>
        )}
      </div>
    </Panel>
  );
}

/** Host names with a dot in them (mypc.local, a reverse proxy's domain) that wanna.sh answers to. */
export function AllowedHosts({
  saved,
  fromEnv,
  onSave,
}: {
  saved: string[];
  fromEnv: string[];
  onSave: (hosts: string[]) => void;
}) {
  const [draft, setDraft] = useState(saved.join(", ")); // the parent remounts this (key) when the saved list changes
  const hosts = draft
    .split(",")
    .map((h) => h.trim())
    .filter(Boolean);
  const changed = hosts.join(",").toLowerCase() !== saved.join(",");
  return (
    <div className="text-[15px]">
      <span className="font-medium">Allowed host names</span>
      <span className="block text-slate mb-2">
        Names with a dot in them that you open wanna.sh by, such as mypc.local or a reverse proxy&apos;s domain.
        Separate several with commas. localhost, IP addresses and single-word names always work.
      </span>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          onSave(hosts);
        }}
      >
        <input
          className={inputClass}
          autoComplete="off"
          spellCheck={false}
          placeholder="mypc.local, wanna.example.com"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="Allowed host names"
        />
        <Button type="submit" disabled={!changed}>
          Save
        </Button>
      </form>
      {fromEnv.length > 0 && (
        <span className="block text-slate text-[14px] mt-2">
          Also allowed by WANNA_ALLOWED_HOSTS: {fromEnv.join(", ")}
        </span>
      )}
    </div>
  );
}

export function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-slate">{k}</dt>
      <dd>{v}</dd>
    </>
  );
}

/** Is this computer ready? One row per area, checked by the server. */
export function SystemCheck() {
  const [refresh, setRefresh] = useState(0);
  const { data, error } = usePoll<SystemCheckItem[]>(`/api/system/check?refresh=${refresh > 0}&n=${refresh}`);
  const icon = (st: SystemCheckItem["status"]) =>
    st === "ok" ? (
      <CircleCheck size={18} className="text-ok shrink-0" aria-label="Ready" />
    ) : st === "warn" ? (
      <CircleAlert size={18} className="text-caution shrink-0" aria-label="Needs attention" />
    ) : (
      <CircleX size={18} className="text-danger shrink-0" aria-label="Not working" />
    );
  const problems = (data ?? []).filter((c) => c.status !== "ok").length;
  return (
    <Panel>
      <div className="flex items-center justify-between gap-3 mb-1">
        <SectionTitle className="">System check</SectionTitle>
        <button className="text-[14px] underline underline-offset-2 text-slate hover:text-ink" onClick={() => setRefresh((n) => n + 1)}>
          Check again
        </button>
      </div>
      <p className="text-slate text-[15px] mb-4">
        {!data ? "Checking this computer…" : problems ? `${problems} thing${problems > 1 ? "s" : ""} to look at.` : "Everything is ready."}
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      {!data && !error && <Loader2 size={18} className="animate-spin text-slate" aria-hidden />}
      <ul className="flex flex-col divide-y divide-line">
        {(data ?? []).map((c) => (
          <li key={c.id} className="flex gap-3 py-3 first:pt-0">
            {icon(c.status)}
            <div className="min-w-0">
              <div className="font-medium text-[15px]">{c.label}</div>
              <div className="text-[14px] text-slate">{c.detail}</div>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
