"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Bell,
  Bot,
  CalendarClock,
  ChevronRight,
  Copy,
  Loader2,
  Plus,
  Power,
  RotateCcw,
  Server,
  Settings,
  Trash2,
} from "lucide-react";
import {
  API_BASE,
  api,
  followAgent,
  type AgentDetail,
  type AgentPace,
  type AgentStatus,
  type AgentSummary,
  type CodeEvent,
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
import { Button, Field, Notice, PageHeader, Segmented, inputClass } from "@/components/ui";

const PACE_OPTIONS: { value: AgentPace; label: string; hint: string }[] = [
  { value: "when_needed", label: "Thinks when needed", hint: "Works, then waits for a message, a schedule or its programs" },
  { value: "always", label: "Always thinking", hint: "Keeps working toward its goals; rests at most 15 minutes" },
];

const APPROVAL_OPTIONS: { value: "auto" | "ask_commands"; label: string; hint: string }[] = [
  { value: "auto", label: "Don't ask", hint: "It works on its own, in its sandbox and with any tools you trust" },
  { value: "ask_commands", label: "Ask before commands", hint: "Commands and new services wait for you (it stops until you answer)" },
];

const EXAMPLES = [
  "Every morning at 8, read the front page of Hacker News and notify me about anything on local AI.",
  "Run a Discord bot for my server (token in the secret DISCORD_TOKEN) that answers questions about my project, and tell me about anything it can't answer.",
  "Check https://example.com every 5 minutes and notify me straight away if it's down or slow.",
  "Research small, fast chat models that run on 8 GB graphics cards, and keep a report up to date in report.md.",
];

const STATE_LABELS: Record<AgentStatus["state"], string> = {
  off: "Off",
  starting: "Starting",
  working: "Working",
  waiting: "Waiting",
  resting: "Resting",
  failed: "Having trouble",
};

interface DockerStatus {
  docker: boolean;
  image: boolean;
  message: string | null;
}

export default function AgentsPage() {
  return (
    <Suspense>
      <AgentsInner />
    </Suspense>
  );
}

function AgentsInner() {
  const id = useSearchParams().get("a");
  const { data: status } = usePoll<DockerStatus>("/api/code/status", 15000);
  return id ? <Workspace id={id} status={status} /> : <AgentList status={status} />;
}

function DockerNotice({ status }: { status: DockerStatus | null }) {
  if (!status?.message) return null;
  return (
    <div className="mb-6">
      <Notice tone={status.docker ? "info" : "error"}>
        {status.message} Agents need it for their own computer: commands, services and files they run.
      </Notice>
    </div>
  );
}

function StateDot({ state }: { state: AgentStatus["state"] }) {
  const color =
    state === "working" || state === "starting"
      ? "bg-ok animate-pulse"
      : state === "waiting" || state === "resting"
        ? "bg-ok"
        : state === "failed"
          ? "bg-caution"
          : "bg-line";
  return <span className={`inline-block size-2 rounded-full shrink-0 ${color}`} aria-hidden />;
}

// --- list ------------------------------------------------------------------------------------------------------

function AgentList({ status }: { status: DockerStatus | null }) {
  const router = useRouter();
  const { data: list, error } = usePoll<AgentSummary[]>("/api/agents", 5000);
  const { models } = useModels("chat");
  const [name, setName] = useState("");
  const [goals, setGoals] = useState("");
  const [pace, setPace] = useState<AgentPace>("when_needed");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const toolModels = models.filter((m) => m.abilities?.tools !== false);
  const chosen = model || toolModels.find((m) => m.loaded?.status === "ready")?.id || toolModels[0]?.id || "";

  const create = async () => {
    if (!name.trim() || !goals.trim()) return;
    setBusy(true);
    setProblem(null);
    try {
      const a = await api.post<AgentSummary>("/api/agents", { name, goals, pace, model: chosen || null, start: true });
      router.push(`/agents/?a=${a.id}`);
    } catch (e) {
      setProblem((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="max-w-[920px]">
      <PageHeader
        title="Agents"
        intro="An AI that runs on its own, around the clock. Give it goals and it works toward them with a computer of its own: it runs programs, watches things, wakes itself on a schedule and tells you when something needs you."
      />
      <DockerNotice status={status} />
      <NotifyPermission />

      <section className="rounded-2xl border border-line bg-paper p-5 mb-10">
        <h2 className="font-display text-[1.1rem] mb-4">New agent</h2>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            create();
          }}
        >
          <Field label="Name">
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="Site watcher" />
          </Field>
          <Field label="Goals" hint="What it should do, for as long as it's on. It sees this at every step; you can change it later.">
            <textarea
              className={`${inputClass} min-h-28`}
              value={goals}
              onChange={(e) => setGoals(e.target.value)}
              placeholder="Check my website every 10 minutes and notify me if it's down."
            />
          </Field>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => setGoals(e)}
                className="text-left rounded-xl border border-line px-3 py-2 text-[13px] text-slate hover:text-ink hover:bg-well/60 transition-colors max-w-[420px]"
              >
                {e}
              </button>
            ))}
          </div>
          <Field label="How it works">
            <Segmented label="How it works" value={pace} onChange={setPace} options={PACE_OPTIONS} />
            <span className="block text-[13px] text-slate mt-1.5">{PACE_OPTIONS.find((o) => o.value === pace)?.hint}.</span>
          </Field>
          <Field label="Model" hint="A chat model that can use tools. It stays loaded while the agent is on.">
            <select className={`${inputClass} h-10 py-0`} value={chosen} onChange={(e) => setModel(e.target.value)}>
              {toolModels.length === 0 && <option value="">No chat model that can use tools yet</option>}
              {toolModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.meta.title || m.id}
                </option>
              ))}
            </select>
          </Field>
          {problem && <Notice tone="error">{problem}</Notice>}
          <Button type="submit" disabled={!name.trim() || !goals.trim() || !chosen || busy} className="justify-self-start">
            <Plus size={16} aria-hidden /> {busy ? "Creating…" : "Create and turn on"}
          </Button>
        </form>
      </section>

      {error && <Notice tone="error">{error}</Notice>}
      {list && list.length > 0 && (
        <section>
          <h2 className="text-[14px] text-slate mb-2">Your agents</h2>
          <ul className="rounded-2xl border border-line bg-paper divide-y divide-line">
            {list.map((a) => (
              <li key={a.id}>
                <Link href={`/agents/?a=${a.id}`} className="flex items-center gap-4 px-5 py-4 hover:bg-well/50 transition-colors">
                  <Bot size={20} className="text-slate shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 font-medium">
                      <span className="truncate">{a.name}</span>
                      <StateDot state={a.state} />
                      <span className="text-[13px] text-slate font-normal">{STATE_LABELS[a.state]}</span>
                    </span>
                    <span className="block text-[14px] text-slate truncate">
                      {a.goals || "No goals yet"}. Updated {ago(a.updated)}
                    </span>
                  </span>
                  {a.unread > 0 && (
                    <span className="flex items-center gap-1 rounded-full bg-accent text-accent-ink px-2 h-6 text-[12px] font-medium">
                      <Bell size={12} aria-hidden /> {a.unread}
                    </span>
                  )}
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

/** Ask once for permission to show agents' notifications on this computer (while wanna.sh is open). */
function NotifyPermission() {
  const [perm, setPerm] = useState<NotificationPermission | "unsupported">("unsupported");
  useEffect(() => {
    // Read after mounting: the page is prerendered without a window.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPerm(typeof window !== "undefined" && "Notification" in window ? Notification.permission : "unsupported");
  }, []);
  if (perm !== "default") return null;
  return (
    <div className="mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-line bg-paper px-4 py-3 text-[15px]">
      <Bell size={16} className="text-slate" aria-hidden />
      <span className="flex-1 min-w-[200px]">Get agents&apos; notifications on this computer while wanna.sh is open.</span>
      <Button tone="quiet" onClick={() => Notification.requestPermission().then(setPerm)}>
        Turn on notifications
      </Button>
    </div>
  );
}

// --- one agent -------------------------------------------------------------------------------------------------

type Tab = "status" | "plan" | "files" | "preview";

function Workspace({ id, status }: { id: string; status: DockerStatus | null }) {
  const router = useRouter();
  const agent = usePoll<AgentDetail>(`/api/agents/${id}`, 5000);
  const { models } = useModels("chat");
  const { data: libraries } = usePoll<KnowledgeLibrary[]>("/api/knowledge/libraries", 15000);
  const { data: kStatus } = usePoll<KnowledgeStatus>("/api/knowledge/status", 15000);
  const [events, setEvents] = useState<CodeEvent[]>([]);
  const [todos, setTodos] = useState<Todo[]>([]);
  const [state, setState] = useState<AgentStatus | null>(null);
  const [input, setInput] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("status");
  const [settings, setSettings] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const a = agent.data;
  const base = `/api/agents/${id}`;

  useEffect(() => {
    const ctrl = new AbortController();
    followAgent(
      id,
      (m) => {
        if (m.type === "snapshot") {
          setEvents(m.events);
          setTodos(m.todos);
          setState(m.state);
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
        } else if (m.type === "state") {
          setState(m.state);
        }
      },
      ctrl.signal,
    );
    return () => ctrl.abort();
  }, [id]);

  // You're looking at it, so its notifications count as read.
  const unread = state?.notifications.filter((n) => !n.read).length ?? 0;
  useEffect(() => {
    if (unread) api.post(`${base}/read`).catch(() => {});
  }, [unread, base]);

  const lastEvent = events[events.length - 1];
  const lastSize = (lastEvent?.text?.length ?? 0) + (lastEvent?.result?.length ?? 0) + (lastEvent?.status?.length ?? 0);
  // Open at the newest step (an agent's history can be long), then follow it while you're at the bottom.
  const opened = useRef(false);
  useEffect(() => {
    const el = scroller.current;
    if (!el || !events.length) return;
    if (!opened.current || el.scrollHeight - el.scrollTop - el.clientHeight < 240) el.scrollTo({ top: el.scrollHeight });
    opened.current = true;
  }, [events.length, lastSize]);

  if (agent.error) {
    return (
      <div className="max-w-[640px]">
        <Notice tone="error">This agent couldn&apos;t be found.</Notice>
        <Link href="/agents/" className="inline-block mt-4 underline underline-offset-2">
          Back to all agents
        </Link>
      </div>
    );
  }

  const on = !!state && state.state !== "off";
  const working = state?.state === "working" || state?.state === "starting";
  const model = a?.model ?? models.find((m) => m.loaded?.status === "ready")?.id ?? models[0]?.id ?? "";
  const currentModel = models.find((m) => m.id === model);
  const patch = async (body: Partial<AgentDetail>) => {
    try {
      await api.patch(base, body);
      agent.refresh();
    } catch (e) {
      setProblem((e as Error).message);
    }
  };
  const toggle = async () => {
    setProblem(null);
    try {
      if (!on && !a?.model && model) await api.patch(base, { model });
      await api.post(`${base}/${on ? "off" : "on"}`);
    } catch (e) {
      setProblem((e as Error).message);
    }
  };
  const send = async () => {
    if (!input.trim()) return;
    setProblem(null);
    try {
      await api.post(`${base}/message`, { text: input });
      setInput("");
    } catch (e) {
      setProblem((e as Error).message);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] h-[calc(100dvh-6rem)] lg:h-[calc(100dvh-3rem)]">
      <section className="flex flex-col min-h-0">
        <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
          <div className="flex items-center gap-2 min-w-0">
            <Link href="/agents/" aria-label="All agents" className="size-9 grid place-items-center rounded-full hover:bg-well shrink-0">
              <ArrowLeft size={18} />
            </Link>
            <h1 className="font-display text-[1.25rem] truncate">{a?.name ?? "…"}</h1>
            {state && (
              <span className="flex items-center gap-1.5 text-[13px] text-slate shrink-0">
                <StateDot state={state.state} />
                {STATE_LABELS[state.state]}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button tone={on ? "quiet" : "primary"} onClick={toggle} disabled={!state}>
              <Power size={15} aria-hidden /> {on ? "Turn off" : "Turn on"}
            </Button>
            <IconButton
              icon={RotateCcw}
              label="Clear conversation"
              disabled={on || !events.length}
              onClick={() =>
                confirm("Clear the conversation? Its files, MEMORY.md, schedules and services stay.") &&
                api.post(`${base}/reset`).catch((e) => setProblem(e.message))
              }
            />
            <IconButton icon={Settings} label="Agent settings" onClick={() => setSettings(true)} />
          </div>
        </div>
        <DockerNotice status={status} />
        {currentModel?.abilities && !currentModel.abilities.tools && (
          <div className="mb-3">
            <Notice tone="error">
              {currentModel.meta.title || currentModel.id} can&apos;t use tools, so it can&apos;t work as an agent. Pick a
              model marked &ldquo;Can use tools&rdquo; in the model menu below.
            </Notice>
          </div>
        )}
        {state?.state === "failed" && state.note && (
          <div className="mb-3">
            <Notice tone="error">{state.note}</Notice>
          </div>
        )}

        <div ref={scroller} className="flex-1 overflow-y-auto min-h-0 pr-1" aria-live="polite">
          {events.length === 0 ? (
            <div className="h-full flex flex-col justify-center max-w-[640px] mx-auto py-8">
              <p className="font-display text-[clamp(1.6rem,3vw,2.2rem)] leading-tight">
                {on ? "Getting started…" : "Turn it on to start"}
              </p>
              <p className="text-slate mt-2">
                Everything it does shows up here as it happens: what it thinks, the commands it runs, what wakes it up and
                what it tells you.
              </p>
            </div>
          ) : (
            <ol className="flex flex-col gap-3 pb-6 max-w-[820px] mx-auto">
              {events.map((e, i) => (
                <EventView key={e.id} e={e} base={base} onOpenFile={setViewing} live={working && i === events.length - 1} />
              ))}
              {working && lastEvent?.type !== "assistant" && lastEvent?.status !== "awaiting_approval" && (
                <li className="flex items-center gap-2 text-[14px] text-slate">
                  <Loader2 size={14} className="animate-spin" aria-hidden /> {state?.note || "Working…"}
                </li>
              )}
              {state?.state === "waiting" && (
                <li className="text-[14px] text-slate">
                  Waiting
                  {state.wait_until ? ` until ${new Date(state.wait_until * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}
                  {" "}for a message, a schedule or its programs.
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
            placeholder={on ? "Message the agent: it reads this at its next step" : "Message the agent: it reads this when it's on"}
            onSubmit={send}
            submitLabel="Send"
            canSubmit={!!input.trim()}
            tools={
              <>
                {models.length > 0 && (
                  <ModelMenu models={models} value={model} onChange={(m) => patch({ model: m })} task="chat" />
                )}
                {a && <OptionChip label="Pace" value={a.pace} onChange={(v) => patch({ pace: v })} options={PACE_OPTIONS} />}
                {a && (
                  <OptionChip label="Approval" value={a.approval} onChange={(v) => patch({ approval: v })} options={APPROVAL_OPTIONS} />
                )}
                {a && (
                  <KnowledgeMenu
                    libraries={libraries ?? []}
                    value={(a.knowledge ?? []).filter((k) => libraries?.some((l) => l.id === k))}
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
        <div role="tablist" aria-label="Agent panels" className="flex gap-1 p-1.5 border-b border-line">
          {(
            [
              ["status", "Status"],
              ["plan", `Plan${todos.length ? ` ${todos.filter((t) => t.status === "completed").length}/${todos.length}` : ""}`],
              ["files", "Files"],
              ["preview", "Preview"],
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
          {tab === "status" && <StatusPanel state={state} onOpen={setViewing} />}
          {tab === "plan" && <TasksPanel todos={todos} />}
          {tab === "files" && <FilesPanel base={base} running={working} onOpen={setViewing} />}
          {tab === "preview" && <PreviewPanel ports={a?.ports} who="the agent" />}
        </div>
      </aside>

      {viewing && <FileViewer base={base} path={viewing} onClose={() => setViewing(null)} />}
      {a && (
        <AgentSettings
          key={a.updated}
          open={settings}
          onClose={() => setSettings(false)}
          agent={a}
          on={on}
          onSave={patch}
          onDelete={async () => {
            if (!confirm(`Delete "${a.name}"? It stops, and its workspace, services and conversation are deleted. This can't be undone.`)) return;
            await api.del(base);
            router.push("/agents/");
          }}
        />
      )}
    </div>
  );
}

function StatusPanel({ state, onOpen }: { state: AgentStatus | null; onOpen: (path: string) => void }) {
  if (!state) return <p className="text-[14px] text-slate">Loading…</p>;
  const notes = [...state.notifications].reverse();
  return (
    <div className="flex flex-col gap-5 text-[14px]">
      <section>
        <h3 className="flex items-center gap-1.5 text-[13px] text-slate mb-1.5">
          <Server size={14} aria-hidden /> Services
        </h3>
        {state.services.length === 0 ? (
          <p className="text-slate">Programs it keeps running (a bot, a server, a poller) appear here.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {state.services.map((s) => (
              <li key={s.name} className="rounded-lg bg-well px-2.5 py-1.5">
                <span className="flex items-center gap-2">
                  <span className={`inline-block size-2 rounded-full ${s.running ? "bg-ok" : "bg-caution"}`} aria-hidden />
                  <span className="font-medium">{s.name}</span>
                  <span className="text-slate text-[12px]">
                    {s.running ? "running" : s.stopped === "gave up" ? "kept crashing, stopped" : "stopped"}
                  </span>
                  <button
                    className="ml-auto text-[12px] underline underline-offset-2 text-slate hover:text-ink"
                    onClick={() => onOpen(`.agent/logs/${s.name}.log`)}
                  >
                    Log
                  </button>
                </span>
                <span className="block font-mono text-[12px] text-slate break-all mt-0.5">{s.command}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h3 className="flex items-center gap-1.5 text-[13px] text-slate mb-1.5">
          <CalendarClock size={14} aria-hidden /> Schedules
        </h3>
        {state.schedules.length === 0 ? (
          <p className="text-slate">Times it set to wake itself up appear here.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {state.schedules.map((s) => (
              <li key={s.id} className="rounded-lg bg-well px-2.5 py-1.5">
                {s.note}
                <span className="block text-[12px] text-slate">
                  Next {new Date(s.next * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}
                  {s.every ? `, every ${everyText(s.every)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h3 className="flex items-center gap-1.5 text-[13px] text-slate mb-1.5">
          <Bell size={14} aria-hidden /> Notifications
        </h3>
        {notes.length === 0 ? (
          <p className="text-slate">What it tells you appears here, and on your phone if you set that up in settings.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {notes.map((n) => (
              <li key={n.id} className={`rounded-lg px-2.5 py-1.5 ${n.urgent ? "border border-caution/60" : "bg-well"}`}>
                <span className="font-medium">{n.title}</span>
                <span className="text-[12px] text-slate"> · {ago(n.time)}</span>
                <span className="block whitespace-pre-wrap">{n.message}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <p className="text-[13px] text-slate">
        {state.inbox > 0 ? `${state.inbox} message${state.inbox === 1 ? "" : "s"} waiting for it. ` : ""}
        {state.compactions > 0
          ? `It has summarised its memory ${state.compactions} time${state.compactions === 1 ? "" : "s"}. `
          : ""}
        It keeps notes for itself in{" "}
        <button className="underline underline-offset-2 hover:text-ink" onClick={() => onOpen("MEMORY.md")}>
          MEMORY.md
        </button>
        .
      </p>
    </div>
  );
}

function everyText(minutes: number): string {
  if (minutes >= 1440 && minutes % 1440 === 0) return minutes === 1440 ? "day" : `${minutes / 1440} days`;
  if (minutes >= 60 && minutes % 60 === 0) return minutes === 60 ? "hour" : `${minutes / 60} hours`;
  return `${minutes} minutes`;
}

function AgentSettings({
  open,
  onClose,
  agent,
  on,
  onSave,
  onDelete,
}: {
  open: boolean;
  onClose: () => void;
  agent: AgentDetail;
  on: boolean;
  onSave: (patch: Partial<AgentDetail>) => Promise<void>;
  onDelete: () => void;
}) {
  const [name, setName] = useState(agent.name);
  const [goals, setGoals] = useState(agent.goals);
  const [steps, setSteps] = useState(String(agent.max_steps_per_hour));
  const [notifyUrl, setNotifyUrl] = useState(agent.notify_url);
  const [secrets, setSecrets] = useState<[string, string | null][]>(Object.entries(agent.secrets));
  const [token, setToken] = useState(agent.hook_token);
  const [copied, setCopied] = useState(false);
  const origin = API_BASE || (typeof window !== "undefined" ? window.location.origin : "");
  const hook = `${origin}/api/agents/${agent.id}/hook/${token}`;

  return (
    <SidePanel title="Agent settings" open={open} onClose={onClose}>
      <Field label="Name">
        <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Goals" hint="It sees these at every step.">
        <textarea className={`${inputClass} min-h-32`} value={goals} onChange={(e) => setGoals(e.target.value)} />
      </Field>
      <Field label="Most steps an hour" hint="A step is one reply from the model. When it reaches this, it rests until the hour is up.">
        <input className={inputClass} type="number" min={5} max={3600} value={steps} onChange={(e) => setSteps(e.target.value)} />
      </Field>
      <Field
        label="Send notifications to (optional)"
        hint="An ntfy.sh topic link for your phone, a Discord or Slack webhook, or any link that accepts JSON."
      >
        <input
          className={inputClass}
          value={notifyUrl}
          onChange={(e) => setNotifyUrl(e.target.value)}
          placeholder="https://ntfy.sh/my-secret-topic"
        />
      </Field>
      <div>
        <span className="block text-[13px] font-medium mb-1">Secrets</span>
        <span className="block text-[13px] text-slate mb-2">
          Tokens and passwords its services need, as environment variables. They&apos;re kept out of its conversation, but
          its own programs can read them, so give it tokens that can only do what it needs.
        </span>
        <div className="flex flex-col gap-2">
          {secrets.map(([k, v], i) => (
            <div key={i} className="flex gap-2">
              <input
                className={`${inputClass} font-mono text-[13px]`}
                value={k}
                placeholder="BOT_TOKEN"
                aria-label="Secret name"
                onChange={(e) => setSecrets(secrets.map((s, j) => (j === i ? [e.target.value.toUpperCase(), s[1]] : s)))}
              />
              <input
                className={`${inputClass} font-mono text-[13px]`}
                type="password"
                value={v ?? ""}
                placeholder={v === null ? "Saved (type to replace)" : "Value"}
                aria-label={`Value of ${k || "secret"}`}
                onChange={(e) => setSecrets(secrets.map((s, j) => (j === i ? [s[0], e.target.value] : s)))}
              />
              <button
                className="size-10 shrink-0 grid place-items-center rounded-full text-slate hover:text-ink hover:bg-well"
                aria-label={`Remove ${k || "secret"}`}
                onClick={() => setSecrets(secrets.filter((_, j) => j !== i))}
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
          <button
            className="self-start text-[14px] underline underline-offset-2 text-slate hover:text-ink"
            onClick={() => setSecrets([...secrets, ["", ""]])}
          >
            Add a secret
          </button>
        </div>
      </div>
      <MemoryPicker agent={agent} onSave={onSave} open={open} />
      <Button
        className="self-start"
        onClick={() =>
          onSave({
            name,
            goals,
            max_steps_per_hour: Number(steps) || 120,
            notify_url: notifyUrl,
            secrets: Object.fromEntries(secrets.filter(([k]) => k.trim())),
          }).then(onClose)
        }
      >
        Save
      </Button>

      <div className="border-t border-line pt-5 mt-2 flex flex-col gap-2">
        <span className="block text-[13px] font-medium">Webhook</span>
        <span className="block text-[13px] text-slate">
          Other apps can wake the agent by posting text or JSON to this link. It arrives in its inbox as a webhook. Anyone
          with the link can do this, so keep it private.
        </span>
        <div className="flex gap-2">
          <input className={`${inputClass} font-mono text-[12px]`} readOnly value={hook} aria-label="Webhook link" />
          <button
            className="size-10 shrink-0 grid place-items-center rounded-full text-slate hover:text-ink hover:bg-well"
            aria-label="Copy the webhook link"
            onClick={() => navigator.clipboard.writeText(hook).then(() => setCopied(true))}
          >
            <Copy size={15} />
          </button>
        </div>
        {copied && <span className="text-[13px] text-slate">Copied.</span>}
        <button
          className="self-start text-[14px] underline underline-offset-2 text-slate hover:text-ink"
          onClick={() =>
            api.post<{ hook_token: string }>(`/api/agents/${agent.id}/hook/new`).then((r) => {
              setToken(r.hook_token);
              setCopied(false);
            })
          }
        >
          Make a new link (the old one stops working)
        </button>
      </div>

      <div className="border-t border-line pt-5 mt-2 flex flex-col gap-3">
        <button
          className="self-start text-[14px] underline underline-offset-2 text-slate hover:text-ink disabled:opacity-40 disabled:no-underline"
          disabled={on}
          title={on ? "Turn the agent off first" : undefined}
          onClick={() => api.post(`/api/agents/${agent.id}/sandbox/stop`)}
        >
          Stop its sandbox and services
        </button>
        <button className="self-start text-[14px] underline underline-offset-2 text-danger" onClick={onDelete}>
          Delete agent
        </button>
      </div>
    </SidePanel>
  );
}

const K = (n: number) => `${Math.round(n / 1024)}K`;

/** Memory sizes rated for this computer, as in Code. More memory means it summarises less often. */
function MemoryPicker({
  agent,
  onSave,
  open,
}: {
  agent: AgentDetail;
  onSave: (patch: Partial<AgentDetail>) => Promise<void>;
  open: boolean;
}) {
  const { data, error } = usePoll<MemoryOptions & { model: string }>(open ? `/api/agents/${agent.id}/memory` : null);
  return (
    <Field label="Memory" hint="More memory lets it keep more in mind before it summarises. Too much for your graphics cards makes it slower.">
      <select
        className={`${inputClass} h-10 py-0`}
        value={agent.context ?? "auto"}
        onChange={(e) => onSave({ context: e.target.value === "auto" ? null : Number(e.target.value) })}
      >
        <option value="auto">Automatic{data ? ` (${K(data.recommended)} on this computer)` : ""}</option>
        {(data?.options ?? [8192, 16384, 32768, 65536].map((c) => ({ context: c, label: "", rating: "unknown" as const }))).map((o) => (
          <option key={o.context} value={o.context}>
            {K(o.context)}
            {o.label ? `: ${o.label}` : ""}
          </option>
        ))}
      </select>
      {!data && !error && open && <span className="block text-[13px] text-slate mt-1">Checking what fits on this computer…</span>}
    </Field>
  );
}
