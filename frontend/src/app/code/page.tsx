"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, ChevronRight, Download, Loader2, Plus, RotateCcw, Settings, SquareTerminal } from "lucide-react";
import {
  API_BASE,
  api,
  followCode,
  type ApprovalMode,
  type CodeEvent,
  type CodeProject,
  type InstalledModel,
  type KnowledgeLibrary,
  type KnowledgeStatus,
  type MemoryOptions,
  type Todo,
} from "@/lib/api";
import { useModels, usePoll } from "@/lib/hooks";
import { ago } from "@/lib/format";
import { ModelMenu, OptionChip, PromptBar, SidePanel } from "@/components/studio";
import { KnowledgeMenu } from "@/components/knowledge";
import { EventView, FileViewer, FilesPanel, IconButton, PreviewPanel, TasksPanel } from "@/components/steps";
import { Button, Field, Notice, PageHeader, inputClass } from "@/components/ui";

const APPROVAL_OPTIONS: { value: ApprovalMode; label: string; hint: string }[] = [
  { value: "ask_commands", label: "Ask before commands", hint: "Reads and edits happen right away; commands wait for you" },
  { value: "ask_all", label: "Ask before any change", hint: "Edits and commands both wait for you" },
  { value: "auto", label: "Don't ask", hint: "The agent works on its own: in the sandbox, and with any tools you trust" },
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
  const { data: libraries } = usePoll<KnowledgeLibrary[]>("/api/knowledge/libraries", 15000);
  const { data: kStatus } = usePoll<KnowledgeStatus>("/api/knowledge/status", 15000);
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
  const currentModel = models.find((m) => m.id === model);
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
        {currentModel?.abilities && !currentModel.abilities.tools && (
          <div className="mb-3">
            <Notice tone="error">
              {currentModel.meta.title || currentModel.id} can&apos;t use tools, so it can&apos;t work on code. Pick a model
              marked &ldquo;Can use tools&rdquo; in the model menu below.
            </Notice>
          </div>
        )}

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
                  base={`/api/code/projects/${pid}`}
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
                  <ModelMenu models={models} value={model} onChange={(id) => patch({ model: id })} task="chat" note={codeNote} />
                )}
                {p && (
                  <OptionChip
                    label="Approval"
                    value={p.approval}
                    onChange={(v) => patch({ approval: v })}
                    options={APPROVAL_OPTIONS}
                  />
                )}
                {p && (
                  <KnowledgeMenu
                    libraries={libraries ?? []}
                    value={(p.knowledge ?? []).filter((id) => libraries?.some((l) => l.id === id))}
                    onChange={(ids) => patch({ knowledge: ids })}
                    ready={!!kStatus?.default}
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
          {tab === "files" && <FilesPanel base={`/api/code/projects/${pid}`} running={running} onOpen={setViewing} />}
          {tab === "preview" && <PreviewPanel ports={p?.ports} shells={p?.shells} />}
        </div>
      </aside>

      {viewing && <FileViewer base={`/api/code/projects/${pid}`} path={viewing} onClose={() => setViewing(null)} />}
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
      <MemoryPicker project={project} onSave={onSave} open={open} />
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

/** "Can use tools" and measured speed, shown for each model in Code's model menu. */
function codeNote(m: InstalledModel): string | null {
  if (!m.abilities) return null;
  const parts = [m.abilities.tools ? "Can use tools" : "Can't use tools"];
  if (m.speed) parts.push(`about ${Math.round(m.speed)} tokens a second here`);
  return parts.join(", ");
}

const K = (n: number) => `${Math.round(n / 1024)}K`;

/** Memory sizes rated for this computer by llama.cpp's planner, with "Automatic" as the default. */
function MemoryPicker({
  project,
  onSave,
  open,
}: {
  project: CodeProject;
  onSave: (patch: Partial<CodeProject>) => Promise<void>;
  open: boolean;
}) {
  const { data, error } = usePoll<MemoryOptions & { model: string }>(open ? `/api/code/projects/${project.id}/memory` : null);
  return (
    <Field
      label="Memory for coding"
      hint="More memory lets the agent keep more of the project in mind. Too much for your graphics cards makes it slower."
    >
      <select
        className={`${inputClass} h-10 py-0`}
        value={project.context ?? "auto"}
        onChange={(e) => onSave({ context: e.target.value === "auto" ? null : Number(e.target.value) })}
      >
        <option value="auto">
          Automatic{data ? ` (${K(data.recommended)} on this computer)` : ""}
        </option>
        {(data?.options ?? [8192, 16384, 32768, 65536].map((c) => ({ context: c, label: "", rating: "unknown" as const }))).map((o) => (
          <option key={o.context} value={o.context}>
            {K(o.context)}
            {o.label ? `: ${o.label}` : ""}
          </option>
        ))}
      </select>
      {!data && !error && open && <span className="block text-[13px] text-slate mt-1">Checking what fits on this computer…</span>}
      {data && data.measured_with_loaded.length > 0 && (
        <span className="block text-[13px] text-caution mt-1">
          Measured while other models were running, so these are cautious. Stop them in My models for an exact check.
        </span>
      )}
    </Field>
  );
}
