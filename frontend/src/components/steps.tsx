"use client";

// The steps an agent takes, as Code and Agents show them: messages, tool cards with approvals and diffs, the plan,
// files and previews. `base` is the API path of the project or agent, e.g. /api/code/projects/<id>.

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Bell,
  BookOpen,
  CalendarClock,
  CalendarX,
  Check,
  ChevronRight,
  Circle,
  CircleDot,
  ExternalLink,
  FilePen,
  FilePlus,
  FileText,
  FolderTree,
  Globe,
  Hand,
  Hourglass,
  Inbox,
  ListTodo,
  Loader2,
  Play,
  Search,
  Server,
  Square,
  SquareTerminal,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { api, type CodeEvent, type Todo } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes } from "@/lib/format";
import { Button, Notice } from "@/components/ui";

export function IconButton({ icon: Icon, label, onClick, disabled }: { icon: LucideIcon; label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="size-9 grid place-items-center rounded-full text-slate hover:text-ink hover:bg-well disabled:opacity-35 disabled:hover:bg-transparent"
    >
      <Icon size={17} />
    </button>
  );
}

// --- events ------------------------------------------------------------------------------------------------------

export function EventView({
  e,
  base,
  onOpenFile,
  live,
}: {
  e: CodeEvent;
  base: string;
  onOpenFile: (path: string) => void;
  /** The newest event while the agent is working. */
  live: boolean;
}) {
  if (e.type === "user") {
    return (
      <li className="self-end max-w-[85%] mt-3 rounded-3xl bg-well px-4 py-2.5 whitespace-pre-wrap text-[15px]">{e.text}</li>
    );
  }
  if (e.type === "assistant") {
    if (!e.text && !e.thinking) return null;
    return (
      <li>
        {e.thinking && (
          <details className="group mb-1">
            <summary className="cursor-pointer text-[13px] text-slate select-none list-none inline-flex items-center gap-1">
              <ChevronRight size={13} className="group-open:rotate-90 transition-transform" aria-hidden />
              {live && !e.text ? "Thinking…" : "Thought"}
            </summary>
            <p className="mt-1 ml-4 text-[13px] text-slate whitespace-pre-wrap max-h-60 overflow-y-auto">{e.thinking}</p>
          </details>
        )}
        {e.text && (
          <div className="prose-chat text-[15.5px] leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{e.text}</ReactMarkdown>
          </div>
        )}
      </li>
    );
  }
  if (e.type === "tool") return <ToolCard e={e} base={base} onOpenFile={onOpenFile} />;
  if (e.type === "error") {
    return (
      <li>
        <Notice tone="error">{e.text}</Notice>
      </li>
    );
  }
  if (e.type === "inbox") return <InboxItem e={e} />;
  if (e.type === "notify") {
    return (
      <li className={`rounded-xl border px-3 py-2.5 text-[14px] ${e.urgent ? "border-caution/60" : "border-line"} bg-paper`}>
        <span className="flex items-center gap-2 font-medium">
          <Bell size={15} className={e.urgent ? "text-caution" : "text-slate"} aria-hidden />
          {e.title}
        </span>
        <p className="mt-1 whitespace-pre-wrap">{e.text}</p>
      </li>
    );
  }
  if (e.detail) {
    return (
      <li className="text-[14px] text-slate">
        <details className="group">
          <summary className="cursor-pointer select-none list-none inline-flex items-center gap-1">
            <ChevronRight size={13} className="group-open:rotate-90 transition-transform" aria-hidden />
            {e.text}
          </summary>
          <p className="mt-1 ml-4 text-[13px] whitespace-pre-wrap max-h-60 overflow-y-auto">{e.detail}</p>
        </details>
      </li>
    );
  }
  return <li className="text-[14px] text-slate">{e.text}</li>;
}

const INBOX_LABELS: Record<string, string> = {
  webhook: "Webhook",
  program: "From its programs",
  schedule: "Schedule",
  "wanna.sh": "wanna.sh",
};

/** Something that arrived in an agent's inbox, other than your own messages. */
function InboxItem({ e }: { e: CodeEvent }) {
  const long = (e.text ?? "").length > 280 || (e.text ?? "").split("\n").length > 5;
  const [open, setOpen] = useState(false);
  return (
    <li className="mt-2 rounded-xl border border-dashed border-line px-3 py-2 text-[14px]">
      <span className="flex items-center gap-2 text-[13px] text-slate">
        <Inbox size={14} aria-hidden />
        {INBOX_LABELS[e.source ?? ""] ?? e.source}
        {e.by ? <span className="truncate">· {e.by}</span> : null}
      </span>
      <p className={`mt-1 whitespace-pre-wrap break-words ${long && !open ? "line-clamp-4" : ""}`}>{e.text}</p>
      {long && (
        <button className="mt-1 text-[13px] underline underline-offset-2 text-slate hover:text-ink" onClick={() => setOpen(!open)}>
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </li>
  );
}

const TOOL_ICONS: Record<string, LucideIcon> = {
  read_file: FileText,
  write_file: FilePlus,
  edit_file: FilePen,
  multi_edit: FilePen,
  list_files: FolderTree,
  glob: Search,
  grep: Search,
  bash: SquareTerminal,
  bash_output: SquareTerminal,
  kill_shell: SquareTerminal,
  todo_write: ListTodo,
  web_fetch: Globe,
  web_search: Globe,
  search_knowledge: BookOpen,
  wait: Hourglass,
  schedule: CalendarClock,
  unschedule: CalendarX,
  notify: Bell,
  service_start: Play,
  service_stop: Square,
  service_list: Server,
};

/** A plain-words label for what a tool call did. */
function summary(e: CodeEvent): string {
  const a = (e.args ?? {}) as Record<string, string>;
  switch (e.name) {
    case "read_file":
      return `Read ${a.path}`;
    case "write_file":
      return `Wrote ${a.path}`;
    case "edit_file":
    case "multi_edit":
      return `Edited ${a.path}`;
    case "list_files":
      return `Listed ${a.path || "the project"}`;
    case "glob":
      return `Found files matching ${a.pattern}`;
    case "grep":
      return `Searched the code for "${a.pattern}"`;
    case "bash":
      return a.description ? `${a.description}` : `Ran ${a.command}`;
    case "bash_output":
      return "Checked a background command";
    case "kill_shell":
      return "Stopped a background command";
    case "todo_write":
      return "Updated the task list";
    case "web_fetch":
      return `Read ${a.url}`;
    case "web_search":
      return `Searched the web for "${a.query}"`;
    case "search_knowledge":
      return `Searched your documents for "${a.query}"`;
    case "wait":
      return a.minutes ? `Waiting up to ${a.minutes} minutes${a.reason ? `: ${a.reason}` : ""}` : `Waiting${a.reason ? `: ${a.reason}` : " for something to happen"}`;
    case "schedule":
      return `Scheduled: ${a.note}`;
    case "unschedule":
      return `Removed schedule ${a.id}`;
    case "notify":
      return `Notified you${a.title ? `: ${a.title}` : ""}`;
    case "service_start":
      return `Started the service ${a.name}`;
    case "service_stop":
      return `Stopped the service ${a.name}`;
    case "service_list":
      return "Checked its services";
    default:
      return `Used your tool ${e.name ?? ""}`;
  }
}

function ToolCard({ e, base, onOpenFile }: { e: CodeEvent; base: string; onOpenFile: (path: string) => void }) {
  const Icon = TOOL_ICONS[e.name ?? ""] ?? Wrench; // the person's own tools
  const a = (e.args ?? {}) as Record<string, unknown>;
  const waiting = e.status === "awaiting_approval";
  const [open, setOpen] = useState(false);
  const path = typeof a.path === "string" ? a.path : null;
  const statusIcon =
    e.status === "running" ? (
      <Loader2 size={14} className="animate-spin text-slate" aria-label="Running" />
    ) : e.status === "done" ? (
      <Check size={14} className="text-ok" aria-label="Done" />
    ) : e.status === "error" ? (
      <X size={14} className="text-danger" aria-label="Failed" />
    ) : e.status === "denied" || e.status === "stopped" ? (
      <X size={14} className="text-slate" aria-label={e.status} />
    ) : (
      <Hand size={14} className="text-caution" aria-label="Waiting for you" />
    );

  return (
    <li className={`rounded-xl border ${waiting ? "border-caution/60 bg-paper" : "border-line"} text-[14px]`}>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center gap-2.5 px-3 py-2 text-left"
      >
        <Icon size={15} className="text-slate shrink-0" aria-hidden />
        <span className={`min-w-0 flex-1 truncate ${e.name === "bash" && !a.description ? "font-mono text-[13px]" : ""}`}>
          {summary(e)}
        </span>
        {statusIcon}
        <ChevronRight size={14} className={`text-slate transition-transform ${open ? "rotate-90" : ""}`} aria-hidden />
      </button>

      {waiting && <Approval e={e} base={base} />}

      {open && (
        <div className="border-t border-line px-3 py-2.5 flex flex-col gap-2">
          {e.name === "bash" && typeof a.command === "string" && (
            <pre className="rounded-lg bg-well p-2.5 text-[12.5px] font-mono whitespace-pre-wrap break-all">$ {a.command}</pre>
          )}
          {e.diff ? (
            <Diff text={e.diff} />
          ) : (
            e.result && (
              <pre className="rounded-lg bg-well p-2.5 text-[12.5px] font-mono whitespace-pre-wrap max-h-80 overflow-auto">{e.result}</pre>
            )
          )}
          {path && e.status === "done" && e.name !== "read_file" && (
            <button className="self-start text-[13px] underline underline-offset-2 text-slate hover:text-ink" onClick={() => onOpenFile(path)}>
              Open {path}
            </button>
          )}
          {e.ports && Object.keys(e.ports).length > 0 && (
            <p className="text-[13px] text-slate">If this started a server, open it from the Preview tab.</p>
          )}
        </div>
      )}
    </li>
  );
}

function Approval({ e, base }: { e: CodeEvent; base: string }) {
  const a = (e.args ?? {}) as Record<string, string>;
  const [sent, setSent] = useState(false);
  const decide = async (decision: "allow" | "deny" | "always") => {
    setSent(true);
    try {
      await api.post(`${base}/approve`, { event_id: e.id, decision });
    } catch {
      setSent(false);
    }
  };
  let preview: string | null = null;
  if (e.name === "bash" || e.name === "service_start") preview = `$ ${a.command}`;
  else if (e.name === "write_file") preview = (a.content ?? "").split("\n").slice(0, 30).join("\n");
  else if (e.name === "edit_file") preview = `- ${(a.old_string ?? "").split("\n").join("\n- ")}\n+ ${(a.new_string ?? "").split("\n").join("\n+ ")}`;
  const custom = !e.name || !(e.name in TOOL_ICONS);
  if (custom) preview = JSON.stringify(e.args ?? {}, null, 2);
  return (
    <div className="border-t border-line px-3 py-3 flex flex-col gap-3">
      <p className="text-[14px]">
        {e.name === "bash"
          ? "The agent wants to run this command:"
          : e.name === "service_start"
            ? `The agent wants to keep this running as the service ${a.name}:`
          : custom
            ? `The agent wants to run your tool ${e.name}, which you trust to run on this computer, with:`
            : `The agent wants to change ${a.path}:`}
      </p>
      {preview && (
        <pre className="rounded-lg bg-well p-2.5 text-[12.5px] font-mono whitespace-pre-wrap break-all max-h-60 overflow-auto">{preview}</pre>
      )}
      <div className="flex flex-wrap gap-2">
        <Button disabled={sent} onClick={() => decide("allow")}>
          Allow
        </Button>
        {e.name === "bash" && (
          <Button tone="quiet" disabled={sent} onClick={() => decide("always")} title="Don't ask again for exactly this command">
            Always allow this command
          </Button>
        )}
        <Button tone="quiet" disabled={sent} onClick={() => decide("deny")}>
          Deny
        </Button>
      </div>
    </div>
  );
}

function Diff({ text }: { text: string }) {
  return (
    <pre className="rounded-lg bg-well p-2.5 text-[12.5px] font-mono overflow-auto max-h-96">
      {text.split("\n").map((line, i) => {
        const cls = line.startsWith("+++") || line.startsWith("---")
          ? "text-slate"
          : line.startsWith("+")
            ? "text-ok"
            : line.startsWith("-")
              ? "text-danger"
              : line.startsWith("@@")
                ? "text-slate"
                : "";
        return (
          <div key={i} className={`whitespace-pre ${cls}`}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

// --- side panels ---------------------------------------------------------------------------------------------------

export function TasksPanel({ todos }: { todos: Todo[] }) {
  if (!todos.length) {
    return <p className="text-[14px] text-slate">The agent lists its plan here when a request has several steps.</p>;
  }
  return (
    <ul className="flex flex-col gap-2.5 text-[14px]">
      {todos.map((t, i) => (
        <li key={i} className="flex gap-2.5">
          {t.status === "completed" ? (
            <Check size={16} className="text-ok shrink-0 mt-0.5" aria-label="Done" />
          ) : t.status === "in_progress" ? (
            <CircleDot size={16} className="text-caution shrink-0 mt-0.5" aria-label="In progress" />
          ) : (
            <Circle size={16} className="text-slate shrink-0 mt-0.5" aria-label="To do" />
          )}
          <span className={t.status === "completed" ? "text-slate line-through" : ""}>{t.content}</span>
        </li>
      ))}
    </ul>
  );
}

export function FilesPanel({ base, running, onOpen }: { base: string; running: boolean; onOpen: (path: string) => void }) {
  // Refresh often while the agent works, so new files show up as they're written.
  const { data } = usePoll<{ path: string; size: number }[]>(`${base}/files`, running ? 2500 : 10000);
  if (!data) return <p className="text-[14px] text-slate">Loading…</p>;
  if (!data.length) return <p className="text-[14px] text-slate">No files yet.</p>;
  return (
    <ul className="flex flex-col text-[13px] font-mono">
      {data.map((f) => {
        const depth = f.path.split("/").length - 1;
        return (
          <li key={f.path}>
            <button
              onClick={() => onOpen(f.path)}
              className="w-full flex justify-between gap-2 rounded-md px-2 py-1 text-left hover:bg-well"
              style={{ paddingLeft: 8 + depth * 12 }}
              title={f.path}
            >
              <span className="truncate">{f.path.split("/").pop()}</span>
              <span className="text-slate shrink-0">{bytes(f.size)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function PreviewPanel({
  ports: published,
  shells = [],
  who = "the agent",
}: {
  ports?: Record<string, number>;
  shells?: { shell_id: string; command: string }[];
  who?: string;
}) {
  const ports = Object.entries(published ?? {});
  return (
    <div className="flex flex-col gap-4 text-[14px]">
      <p className="text-slate">
        When {who} starts a web server in the sandbox on port 3000, 5173, 8000 or 8080, open it here.
      </p>
      {ports.length === 0 ? (
        <p className="text-slate">The sandbox isn&apos;t running yet. It starts the first time {who} runs a command.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {ports.map(([inside, outside]) => (
            <li key={inside}>
              <a
                href={`http://localhost:${outside}/`}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-between gap-2 rounded-xl border border-line px-3 py-2 hover:bg-well"
              >
                <span>
                  Port {inside}
                  <span className="block text-[12px] text-slate">localhost:{outside}</span>
                </span>
                <ExternalLink size={15} className="text-slate" aria-hidden />
              </a>
            </li>
          ))}
        </ul>
      )}
      {shells.length > 0 && (
        <div>
          <h3 className="text-[13px] text-slate mb-1.5">Running in the background</h3>
          <ul className="flex flex-col gap-1.5">
            {shells.map((s) => (
              <li key={s.shell_id} className="font-mono text-[12.5px] rounded-lg bg-well px-2.5 py-1.5 break-all">
                {s.command}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function FileViewer({ base, path, onClose }: { base: string; path: string; onClose: () => void }) {
  const { data, error } = usePoll<string>(`${base}/file?path=${encodeURIComponent(path)}`, 0);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const lines = typeof data === "string" ? data.split("\n") : [];
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true" aria-label={path}>
      <button className="absolute inset-0 bg-black/50" onClick={onClose} aria-label="Close" />
      <div className="relative w-full max-w-[960px] max-h-[85dvh] flex flex-col rounded-2xl border border-line bg-fog">
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-line">
          <span className="font-mono text-[13px] truncate">{path}</span>
          <button onClick={onClose} className="size-8 grid place-items-center rounded-full hover:bg-well" aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="overflow-auto">
          {error && <p className="p-4 text-danger text-[14px]">{error}</p>}
          <pre className="text-[12.5px] font-mono py-3">
            {lines.map((l, i) => (
              <div key={i} className="flex">
                <span className="w-12 shrink-0 pr-3 text-right text-slate select-none">{i + 1}</span>
                <span className="whitespace-pre pr-4">{l || " "}</span>
              </div>
            ))}
          </pre>
        </div>
      </div>
    </div>
  );
}
