"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useSyncExternalStore, type ReactNode } from "react";
import {
  AudioLines,
  BookOpen,
  Boxes,
  Clapperboard,
  Code,
  Download,
  FileText,
  Image as ImageIcon,
  Images,
  Menu,
  MessageSquare,
  Moon,
  Music,
  Settings,
  SquareTerminal,
  Sun,
  X,
  type LucideIcon,
} from "lucide-react";
import type { Download as DownloadT, Task } from "@/lib/api";
import { usePoll, useSystem } from "@/lib/hooks";
import { TASKS, TASK_ORDER } from "@/lib/tasks";
import { gpuName, mem } from "@/lib/format";

const TASK_ICONS: Record<Task, LucideIcon> = {
  chat: MessageSquare,
  image: ImageIcon,
  video: Clapperboard,
  speech: AudioLines,
  transcribe: FileText,
  sound: Music,
  embed: BookOpen,
};
const LIBRARY = [
  { href: "/knowledge/", label: "Knowledge", icon: BookOpen },
  { href: "/discover/", label: "Get models", icon: Download },
  { href: "/models/", label: "My models", icon: Boxes },
  { href: "/gallery/", label: "Gallery", icon: Images },
];
const SYSTEM = [
  { href: "/developers/", label: "API & apps", icon: Code },
  { href: "/settings/", label: "Settings", icon: Settings },
];

export default function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [lastPath, setLastPath] = useState(path);
  if (path !== lastPath) {
    // Close the mobile menu after navigating.
    setLastPath(path);
    setOpen(false);
  }

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[232px_1fr]">
      <div className="lg:hidden flex items-center justify-between px-4 h-14 border-b border-line bg-fog/85 backdrop-blur-lg sticky top-0 z-30">
        <Wordmark />
        <button
          onClick={() => setOpen(!open)}
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          className="size-10 grid place-items-center rounded-full hover:bg-well"
        >
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      <aside
        className={`${open ? "block" : "hidden"} lg:block fixed lg:sticky inset-x-0 top-14 lg:top-0 bottom-0 lg:h-dvh z-20 bg-fog lg:border-r border-line overflow-y-auto`}
      >
        <div className="flex flex-col min-h-full px-3 py-5">
          <div className="hidden lg:block px-2.5 mb-7">
            <Wordmark />
          </div>
          <nav aria-label="Main" className="flex flex-col gap-6">
            <NavGroup title="I wanna">
              {TASK_ORDER.map((t) => (
                <NavItem key={t} href={TASKS[t].href} active={path.startsWith(TASKS[t].href)} icon={TASK_ICONS[t]}>
                  {TASKS[t].label}
                </NavItem>
              ))}
              <NavItem href="/code/" active={path.startsWith("/code")} icon={SquareTerminal}>
                Code
              </NavItem>
            </NavGroup>
            <NavGroup title="Library">
              {LIBRARY.map((l) => (
                <NavItem key={l.href} href={l.href} active={path.startsWith(l.href)} icon={l.icon}>
                  {l.label}
                </NavItem>
              ))}
              <DownloadStatus />
            </NavGroup>
            <NavGroup title="Setup">
              {SYSTEM.map((l) => (
                <NavItem key={l.href} href={l.href} active={path.startsWith(l.href)} icon={l.icon}>
                  {l.label}
                </NavItem>
              ))}
            </NavGroup>
          </nav>
          <div className="mt-auto pt-8 flex flex-col gap-4">
            <GpuMeters />
            <ThemeToggle />
          </div>
        </div>
      </aside>

      {/* The home page is a full-bleed landing page and lays out its own width; app pages share one frame. */}
      {path === "/" ? (
        <main className="min-w-0">{children}</main>
      ) : (
        <main className="min-w-0 px-4 sm:px-8 lg:px-12 pt-6 pb-4 lg:pt-8">
          <div className="mx-auto max-w-[1120px]">{children}</div>
        </main>
      )}
    </div>
  );
}

function Wordmark() {
  return (
    <Link href="/" className="font-display text-[1.6rem] leading-none">
      wanna<span className="text-slate">.sh</span>
    </Link>
  );
}

function NavGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <div className="px-2.5 mb-1 text-[12px] text-slate">{title}</div>
      <ul className="flex flex-col">{children}</ul>
    </div>
  );
}

function NavItem({
  href,
  active,
  icon: Icon,
  children,
}: {
  href: string;
  active: boolean;
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <li>
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        className={`flex items-center gap-2.5 rounded-lg px-2.5 h-9 text-[15px] transition-colors ${
          active ? "bg-well text-ink font-medium" : "text-slate hover:text-ink hover:bg-well/60"
        }`}
      >
        <Icon size={17} strokeWidth={1.75} aria-hidden />
        {children}
      </Link>
    </li>
  );
}

/** Download progress, visible from every page while something is downloading. */
function DownloadStatus() {
  const { data } = usePoll<DownloadT[]>("/api/downloads", 2500);
  const active = (data ?? []).filter((d) => d.status === "downloading" || d.status === "queued");
  if (!active.length) return null;
  const done = active.reduce((a, d) => a + d.done, 0);
  const total = active.reduce((a, d) => a + d.total, 0) || 1;
  return (
    <li className="px-2.5 pt-1.5 pb-1">
      <Link href="/discover/" className="block text-[13px] text-slate hover:text-ink">
        Downloading {active.length === 1 ? active[0].title : `${active.length} models`}, {Math.round((done / total) * 100)}%
        <span className="block h-1 rounded-full bg-well mt-1.5 overflow-hidden" aria-hidden>
          <span className="block h-full bg-ink rounded-full" style={{ width: `${(done / total) * 100}%` }} />
        </span>
      </Link>
    </li>
  );
}

// --- theme ------------------------------------------------------------------

const THEME_EVENT = "wanna-theme";

function readTheme(): "light" | "dark" {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function ThemeToggle() {
  const theme = useSyncExternalStore(
    (cb) => {
      window.addEventListener(THEME_EVENT, cb);
      return () => window.removeEventListener(THEME_EVENT, cb);
    },
    readTheme,
    () => "dark" as const,
  );
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      onClick={() => {
        if (next === "light") document.documentElement.dataset.theme = "light";
        else delete document.documentElement.dataset.theme;
        try {
          localStorage.setItem("wanna.theme", next);
        } catch {}
        window.dispatchEvent(new Event(THEME_EVENT));
      }}
      className="mx-1 flex items-center gap-2 rounded-lg px-1.5 h-8 text-[13px] text-slate hover:text-ink hover:bg-well/60"
    >
      {theme === "dark" ? <Sun size={15} aria-hidden /> : <Moon size={15} aria-hidden />}
      {theme === "dark" ? "Light mode" : "Dark mode"}
    </button>
  );
}

// --- graphics card meters --------------------------------------------------------

function GpuMeters() {
  const { data, error } = useSystem(3000);
  if (error) return <p className="px-2.5 text-[12px] text-danger">Can&apos;t reach the wanna.sh server.</p>;
  if (!data) return null;
  if (!data.gpus.length)
    return <p className="px-2.5 text-[12px] text-slate">No graphics card found. Models run on the processor.</p>;
  return (
    <div className="flex flex-col gap-3 px-2.5">
      {data.gpus.map((g) => {
        const used = g.memory_total - g.memory_free;
        return (
          <div key={g.index}>
            <div className="flex justify-between text-[12px]">
              <span className="text-ink">{gpuName(g.name)}</span>
              <span className="text-slate tabular-nums">
                {mem(used, 1)} / {mem(g.memory_total)}
              </span>
            </div>
            <div className="h-1 rounded-full bg-well mt-1.5 overflow-hidden" aria-hidden>
              <div className="h-full bg-slate rounded-full" style={{ width: `${(used / g.memory_total) * 100}%` }} />
            </div>
            {g.models.length > 0 && (
              <div className="text-[12px] text-slate mt-1 flex items-center gap-1.5">
                <span className="size-1.5 rounded-full bg-marigold shrink-0" aria-hidden />
                <span className="truncate">{g.models.join(", ")}</span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
