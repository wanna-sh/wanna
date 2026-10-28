"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Circle,
  CircleDot,
  Download,
  ExternalLink,
  FilePen,
  FilePlus,
  FileText,
  FolderTree,
  Globe,
  Hand,
  ListTodo,
  Loader2,
  Plus,
  RotateCcw,
  Search,
  Settings,
  SquareTerminal,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  API_BASE,
  api,
  followCode,
  type ApprovalMode,
  type CodeEvent,
  type CodeProject,
  type Todo,
} from "@/lib/api";
import { useModels, usePoll } from "@/lib/hooks";
import { ago, bytes } from "@/lib/format";
import { ModelMenu, OptionChip, PromptBar, SidePanel } from "@/components/studio";
import { Button, Field, Notice, PageHeader, inputClass } from "@/components/ui";

const APPROVAL_OPTIONS: { value: ApprovalMode; label: string; hint: string }[] = [
  { value: "ask_commands", label: "Ask before commands", hint: "Reads and edits happen right away; commands wait for you" },
  { value: "ask_all", label: "Ask before any change", hint: "Edits and commands both wait for you" },
  { value: "auto", label: "Don't ask", hint: "The agent works on its own, inside the sandbox" },
];

const EXAMPLES = [
  "Build a to-do list web app with HTML, CSS and JavaScript, and start it so I can preview it",
  "Create a Python script that renames the photos in a folder by the date they were taken",
  "Set up a small FastAPI server with a /health endpoint and a test that checks it",
  "Look through this project and explain how it's organised",
];

interface DockerStatus {
  docker: boolean;
  image: boolean;
  message: string | null;
}

export default function CodePage() {
  return (
    <Suspense>
      <CodeInner />
    </Suspense>
  );
}

function CodeInner() {
  const pid = useSearchParams().get("p");
  const { data: status } = usePoll<DockerStatus>("/api/code/status", 15000);
  return pid ? <Workspace pid={pid} status={status} /> : <ProjectList status={status} />;
}

function DockerNotice({ status }: { status: DockerStatus | null }) {
  if (!status?.message) return null;
  return (
    <div className="mb-6">
      <Notice tone={status.docker ? "info" : "error"}>
        {status.message} Reading and writing files still works; running commands needs the sandbox.
      </Notice>
    </div>
  );
}

// --- project list --------------------------------------------------------------------------------------------

function ProjectList({ status }: { status: DockerStatus | null }) {
  const router = useRouter();
  const { data: list, error } = usePoll<CodeProject[]>("/api/code/projects", 0);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setProblem(null);
    try {
      const p = await api.post<CodeProject>("/api/code/projects", { name, description: goal });
      if (goal.trim()) await api.post(`/api/code/projects/${p.id}/message`, { text: goal });
      router.push(`/code/?p=${p.id}`);
    } catch (e) {
      setProblem((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="max-w-[920px]">
      <PageHeader
        title="Code"
        intro="Describe what you want to build and an AI agent writes the code, runs it and fixes it, in a safe sandbox on this computer."
      />
      <DockerNotice status={status} />

      <section className="rounded-2xl border border-line bg-paper p-5 mb-10">
        <h2 className="font-display text-[1.1rem] mb-4">New project</h2>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            create();
          }}
        >
          <Field label="Name">
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="My first app" />
          </Field>
          <Field label="What do you want to build? (optional)" hint="This becomes your first request to the agent.">
            <textarea
              className={`${inputClass} min-h-24`}
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="A weather dashboard that shows the next 7 days for my city"
            />
          </Field>
          {problem && <Notice tone="error">{problem}</Notice>}
          <Button type="submit" disabled={!name.trim() || busy} className="justify-self-start">
            <Plus size={16} aria-hidden /> {busy ? "Creating…" : "Create project"}
          </Button>
        </form>
      </section>

      {error && <Notice tone="error">{error}</Notice>}
      {list && list.length > 0 && (
        <section>
          <h2 className="text-[14px] text-slate mb-2">Your projects</h2>
          <ul className="rounded-2xl border border-line bg-paper divide-y divide-line">
            {list.map((p) => (
              <li key={p.id}>
                <Link href={`/code/?p=${p.id}`} className="flex items-center gap-4 px-5 py-4 hover:bg-well/50 transition-colors">
                  <SquareTerminal size={20} className="text-slate shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium truncate">{p.name}</span>
                    <span className="block text-[14px] text-slate truncate">
                      {p.description || "No description"}. {p.files ?? 0} files, updated {ago(p.updated)}
                    </span>
                  </span>
                  <ChevronRight size={18} className="text-slate" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

// --- workspace -------------------------------------------------------------------------------------------------

type Tab = "tasks" | "files" | "preview";

function Workspace({ pid, status }: { pid: string; status: DockerStatus | null }) {
  const router = useRouter();
  const project = usePoll<CodeProject>(`/api/code/projects/${pid}`, 4000);
  const { models } = useModels("chat");
  const [events, setEvents] = useState<CodeEvent[]>([]);
  const [todos, setTodos] = useState<Todo[]>([]);
  const [running, setRunning] = useState(false);
  const [input, setInput] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("tasks");
  const [settings, setSettings] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const p = project.data;

  // Live events: a snapshot first, then updates.
  useEffect(() => {
    const ctrl = new AbortController();
    followCode(
      pid,
      (m) => {
        if (m.type === "snapshot") {
          setEvents(m.events);
          setTodos(m.todos);
          setRunning(m.running);
        } else if (m.type === "upsert") {
          setEvents((es) => {
            const i = es.findIndex((e) => e.id === m.event.id);
            if (i === -1) return [...es, m.event];
            const next = [...es];
            next[i] = m.event;
            return next;
          });
        } else if (m.type === "todos") {
          setTodos(m.todos);
        } else if (m.type === "status") {
          setRunning(m.running);
        }
      },
      ctrl.signal,
    );
    return () => ctrl.abort();
  }, [pid]);

  // Follow the conversation while you're at the bottom; leave it alone if you've scrolled up to read.
  const lastEvent = events[events.length - 1];
  const lastSize = (lastEvent?.text?.length ?? 0) + (lastEvent?.result?.length ?? 0) + (lastEvent?.status?.length ?? 0);
  useEffect(() => {
    const el = scroller.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 240) el.scrollTo({ top: el.scrollHeight });
  }, [events.length, lastSize]);

  if (project.error) {
    return (
      <div className="max-w-[640px]">
        <Notice tone="error">This project couldn&apos;t be found.</Notice>
        <Link href="/code/" className="inline-block mt-4 underline underline-offset-2">
          Back to all projects
        </Link>
      </div>
    );
  }

  const model = p?.model ?? models.find((m) => m.loaded?.status === "ready")?.id ?? models[0]?.id ?? "";
  const patch = async (body: Partial<CodeProject>) => {
    await api.patch(`/api/code/projects/${pid}`, body);
    project.refresh();
  };

  const send = async (text: string) => {
    if (!text.trim() || running) return;
    setProblem(null);
    try {
      if (!p?.model && model) await patch({ model });
      await api.post(`/api/code/projects/${pid}/message`, { text });
      setInput("");
    } catch (e) {
      setProblem((e as Error).message);
    }
  };

  const ports = Object.entries(p?.ports ?? {});

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] h-[calc(100dvh-6rem)] lg:h-[calc(100dvh-3rem)]">
      <section className="flex flex-col min-h-0">
        <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
          <div className="flex items-center gap-2 min-w-0">
            <Link href="/code/" aria-label="All projects" className="size-9 grid place-items-center rounded-full hover:bg-well shrink-0">
              <ArrowLeft size={18} />
            </Link>
            <h1 className="font-display text-[1.25rem] truncate">{p?.name ?? "…"}</h1>
          </div>
          <div className="flex items-center gap-1">
            <IconButton
              icon={RotateCcw}
              label="New conversation"
              disabled={running || !events.length}
              onClick={() =>
                confirm("Start a new conversation? The files stay; the agent forgets this conversation.") &&
                api.post(`/api/code/projects/${pid}/reset`).catch((e) => setProblem(e.message))
              }
            />
            <a
              href={`${API_BASE}/api/code/projects/${pid}/zip`}
              aria-label="Download as zip"
              title="Download as zip"
              className="size-9 grid place-items-center rounded-full text-slate hover:text-ink hover:bg-well"
            >
              <Download size={17} />
            </a>
            <IconButton icon={Settings} label="Project settings" onClick={() => setSettings(true)} />
          </div>
        </div>
        <DockerNotice status={status} />

        <div ref={scroller} className="flex-1 overflow-y-auto min-h-0 pr-1" aria-live="polite">
          {events.length === 0 ? (
            <div className="h-full flex flex-col justify-center max-w-[640px] mx-auto py-8">
              <p className="font-display text-[clamp(1.8rem,3vw,2.4rem)] leading-tight">What should we build?</p>
              <p className="text-slate mt-2">
                The agent can read and write files, run commands, search the web and start servers you can preview.
              </p>
              <div className="grid gap-2 mt-6">
                {EXAMPLES.map((e) => (
                  <button
                    key={e}
                    onClick={() => setInput(e)}
                    className="text-left rounded-xl border border-line px-4 py-3 text-[15px] text-slate hover:text-ink hover:bg-well/60 transition-colors"
                  >
                    {e}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <ol className="flex flex-col gap-3 pb-6 max-w-[820px] mx-auto">
              {events.map((e, i) => (
                <EventView
                  key={e.id}
                  e={e}
                  pid={pid}
                  onOpenFile={setViewing}
                  live={running && i === events.length - 1}
                />
              ))}
              {running && lastEvent?.type !== "assistant" && lastEvent?.status !== "awaiting_approval" && (
                <li className="flex items-center gap-2 text-[14px] text-slate">
                  <Loader2 size={14} className="animate-spin" aria-hidden /> Working…
                </li>
              )}
            </ol>
          )}
        </div>

        <div className="pt-3 max-w-[820px] w-full mx-auto">
          {problem && (
            <div className="mb-3">
              <Notice tone="error">{problem}</Notice>
            </div>
          )}
          <PromptBar
            value={input}
            onChange={setInput}
            placeholder={events.length ? "Ask for a change, or say what to do next" : "Describe what to build"}
            onSubmit={() => send(input)}
            submitLabel="Send"
            canSubmit={!!input.trim() && !!model}
            busy={running}
            onStop={() => api.post(`/api/code/projects/${pid}/stop`)}
            tools={
              <>
                {models.length > 0 && (
                  <ModelMenu models={models} value={model} onChange={(id) => patch({ model: id })} task="chat" />
                )}
                {p && (
                  <OptionChip
                    label="Approval"
                    value={p.approval}
                    onChange={(v) => patch({ approval: v })}
                    options={APPROVAL_OPTIONS}
                  />
                )}
              </>
            }
          />
        </div>
      </section>

      <aside className="hidden lg:flex flex-col min-h-0 rounded-2xl border border-line bg-paper">
        <div role="tablist" aria-label="Project panels" className="flex gap-1 p-1.5 border-b border-line">
          {(
            [
              ["tasks", `Tasks${todos.length ? ` ${todos.filter((t) => t.status === "completed").length}/${todos.length}` : ""}`],
              ["files", "Files"],
              ["preview", `Preview${ports.length && p?.shells?.length ? " (live)" : ""}`],
            ] as [Tab, string][]
          ).map(([t, label]) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={`flex-1 h-8 rounded-lg text-[13px] transition-colors ${tab === t ? "bg-well text-ink" : "text-slate hover:text-ink"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto min-h-0 p-4">
          {tab === "tasks" && <TasksPanel todos={todos} />}
          {tab === "files" && <FilesPanel pid={pid} running={running} onOpen={setViewing} />}
          {tab === "preview" && <PreviewPanel project={p} />}
        </div>
      </aside>

      {viewing && <FileViewer pid={pid} path={viewing} onClose={() => setViewing(null)} />}
      {p && (
        <ProjectSettings
          open={settings}
          onClose={() => setSettings(false)}
          project={p}
          onSave={patch}
          onDelete={async () => {
            if (!confirm(`Delete "${p.name}" and all its files? This can't be undone.`)) return;
            await api.del(`/api/code/projects/${pid}`);
            router.push("/code/");
          }}
        />
      )}
    </div>
  );
}

function IconButton({ icon: Icon, label, onClick, disabled }: { icon: LucideIcon; label: string; onClick: () => void; disabled?: boolean }) {
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

function EventView({
  e,
  pid,
  onOpenFile,
  live,
}: {
  e: CodeEvent;
  pid: string;
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
  if (e.type === "tool") return <ToolCard e={e} pid={pid} onOpenFile={onOpenFile} />;
  if (e.type === "error") {
    return (
      <li>
        <Notice tone="error">{e.text}</Notice>
      </li>
    );
  }
  return <li className="text-[14px] text-slate">{e.text}</li>;
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
    default:
      return e.name ?? "Tool";
  }
}

function ToolCard({ e, pid, onOpenFile }: { e: CodeEvent; pid: string; onOpenFile: (path: string) => void }) {
  const Icon = TOOL_ICONS[e.name ?? ""] ?? SquareTerminal;
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

      {waiting && <Approval e={e} pid={pid} />}

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

function Approval({ e, pid }: { e: CodeEvent; pid: string }) {
  const a = (e.args ?? {}) as Record<string, string>;
  const [sent, setSent] = useState(false);
  const decide = async (decision: "allow" | "deny" | "always") => {
    setSent(true);
    try {
      await api.post(`/api/code/projects/${pid}/approve`, { event_id: e.id, decision });
    } catch {
      setSent(false);
    }
  };
  let preview: string | null = null;
  if (e.name === "bash") preview = `$ ${a.command}`;
  else if (e.name === "write_file") preview = (a.content ?? "").split("\n").slice(0, 30).join("\n");
  else if (e.name === "edit_file") preview = `- ${(a.old_string ?? "").split("\n").join("\n- ")}\n+ ${(a.new_string ?? "").split("\n").join("\n+ ")}`;
  return (
    <div className="border-t border-line px-3 py-3 flex flex-col gap-3">
      <p className="text-[14px]">
        {e.name === "bash" ? "The agent wants to run this command:" : `The agent wants to change ${a.path}:`}
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

function TasksPanel({ todos }: { todos: Todo[] }) {
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

function FilesPanel({ pid, running, onOpen }: { pid: string; running: boolean; onOpen: (path: string) => void }) {
  // Refresh often while the agent works, so new files show up as they're written.
  const { data } = usePoll<{ path: string; size: number }[]>(`/api/code/projects/${pid}/files`, running ? 2500 : 10000);
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

function PreviewPanel({ project }: { project: CodeProject | null }) {
  const ports = Object.entries(project?.ports ?? {});
  const shells = project?.shells ?? [];
  return (
    <div className="flex flex-col gap-4 text-[14px]">
      <p className="text-slate">
        When the agent starts a web server in the sandbox on port 3000, 5173, 8000 or 8080, open it here.
      </p>
      {ports.length === 0 ? (
        <p className="text-slate">The sandbox isn&apos;t running yet. It starts the first time the agent runs a command.</p>
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

function FileViewer({ pid, path, onClose }: { pid: string; path: string; onClose: () => void }) {
  const { data, error } = usePoll<string>(`/api/code/projects/${pid}/file?path=${encodeURIComponent(path)}`, 0);
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

function ProjectSettings({
  open,
  onClose,
  project,
  onSave,
  onDelete,
}: {
  open: boolean;
  onClose: () => void;
  project: CodeProject;
  onSave: (patch: Partial<CodeProject>) => Promise<void>;
  onDelete: () => void;
}) {
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  return (
    <SidePanel title="Project settings" open={open} onClose={onClose}>
      <Field label="Name">
        <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="What it is" hint="The agent sees this at the start of every request.">
        <textarea className={`${inputClass} min-h-20`} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label="Memory for coding" hint="More memory lets the agent keep more of the project in mind, but uses more graphics memory.">
        <select
          className={`${inputClass} h-10 py-0`}
          value={project.context}
          onChange={(e) => onSave({ context: Number(e.target.value) })}
        >
          <option value={8192}>Small (8K)</option>
          <option value={16384}>Standard (16K)</option>
          <option value={32768}>Large (32K)</option>
          <option value={65536}>Very large (64K)</option>
        </select>
      </Field>
      {project.always_allow.length > 0 && (
        <div>
          <span className="block text-[13px] font-medium mb-1.5">Commands you always allow</span>
          <ul className="flex flex-col gap-1">
            {project.always_allow.map((c) => (
              <li key={c} className="font-mono text-[12.5px] rounded-lg bg-well px-2.5 py-1.5 break-all">
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
      <Button className="self-start" onClick={() => onSave({ name, description }).then(onClose)}>
        Save
      </Button>
      <div className="border-t border-line pt-5 mt-2 flex flex-col gap-3">
        <button
          className="self-start text-[14px] underline underline-offset-2 text-slate hover:text-ink"
          onClick={() => api.post(`/api/code/projects/${project.id}/sandbox/stop`)}
        >
          Stop the sandbox
        </button>
        <button className="self-start text-[14px] underline underline-offset-2 text-danger" onClick={onDelete}>
          Delete project
        </button>
      </div>
    </SidePanel>
  );
}
