// Thin client for the wanna.sh backend. Same origin in production, NEXT_PUBLIC_API_BASE in development.

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const HEADERS = { "X-Wanna-UI": "1" };

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let message = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      message = typeof body.detail === "string" ? body.detail : body.error?.message ?? message;
    } catch {}
    throw new ApiError(message, r.status);
  }
  const type = r.headers.get("content-type") ?? "";
  return (type.includes("json") ? r.json() : r.text()) as Promise<T>;
}

/** A file from the API as a data URL: for pictures, which an <img> can't fetch with the UI's header. */
export async function dataUrl(path: string): Promise<string> {
  const r = await fetch(API_BASE + path, { headers: HEADERS });
  if (!r.ok) throw new ApiError(`${r.status} ${r.statusText}`, r.status);
  const blob = await r.blob();
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export const api = {
  get: <T>(path: string) => fetch(API_BASE + path, { headers: HEADERS }).then(handle<T>),
  post: <T>(path: string, body?: unknown) =>
    fetch(API_BASE + path, {
      method: "POST",
      headers: { ...HEADERS, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(handle<T>),
  put: <T>(path: string, body: unknown) =>
    fetch(API_BASE + path, {
      method: "PUT",
      headers: { ...HEADERS, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(handle<T>),
  patch: <T>(path: string, body: unknown) =>
    fetch(API_BASE + path, {
      method: "PATCH",
      headers: { ...HEADERS, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(handle<T>),
  del: <T>(path: string) => fetch(API_BASE + path, { method: "DELETE", headers: HEADERS }).then(handle<T>),
  upload: <T>(path: string, file: Blob, filename = "upload") => {
    const fd = new FormData();
    fd.append("file", file, filename);
    return fetch(API_BASE + path, { method: "POST", headers: HEADERS, body: fd }).then(handle<T>);
  },
  /** A multipart form you built yourself (fields and files), such as a training run. */
  postForm: <T>(path: string, form: FormData) =>
    fetch(API_BASE + path, { method: "POST", headers: HEADERS, body: form }).then(handle<T>),
  /** A form whose answer is a file (a table with answers added): the file and its name. */
  postFormFile: async (path: string, form: FormData) => {
    const r = await fetch(API_BASE + path, { method: "POST", headers: HEADERS, body: form });
    if (!r.ok) await handle(r);
    const name = /filename="([^"]+)"/.exec(r.headers.get("content-disposition") ?? "")?.[1] ?? "answers.csv";
    return { blob: await r.blob(), name };
  },
  /** Several files in one request, as the "files" field (Knowledge). */
  uploadFiles: <T>(path: string, files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f, f.name);
    return fetch(API_BASE + path, { method: "POST", headers: HEADERS, body: fd }).then(handle<T>);
  },
};

export const fileUrl = (name: string) => `${API_BASE}/files/${name}`;

/** Stream an OpenAI-style chat completion, calling onDelta with each visible text piece.
 *  Reasoning models stream hidden "thinking" first (reasoning_content); it isn't shown, but it counts
 *  towards the token total, so `firstTokenAt` marks the first token of either kind for speed figures. */
/** A tool the model asked to use, with its arguments as JSON text. */
export interface ToolCall {
  id: string;
  name: string;
  arguments: string;
}

/** A model-facing tool definition (OpenAI's function format). */
export interface ToolSchema {
  type: "function";
  function: { name: string; description: string; parameters: { type: "object"; properties: Record<string, JsonSchema>; required: string[] } };
}

export interface JsonSchema {
  type?: string;
  description?: string;
  enum?: (string | number | boolean)[];
  items?: JsonSchema;
  default?: unknown;
}

/** One of the person's own tools: a Python file in ~/.wanna/tools. */
export interface CustomTool {
  name: string;
  path: string;
  /** Given to the AI (when there's no problem with it). */
  enabled: boolean;
  /** Runs directly on this computer rather than in the sandbox: trusted as the file is now. */
  trusted: boolean;
  /** It was trusted, but the file has changed since. */
  trust_lost: boolean;
  schema: ToolSchema | null;
  description: string;
  /** Packages from its "# /// script" block. */
  dependencies: string[];
  /** Why the AI can't be given it (bad code, missing docstring, ...). */
  error: string | null;
  source?: string;
}

export interface ToolList {
  folder: string;
  tools: CustomTool[];
  template: string;
}

export interface ToolRun {
  ok: boolean;
  result?: string;
  error?: string;
  /** What the tool printed while it ran. */
  printed: string;
  seconds: number;
  where: "sandbox" | "computer" | null;
}

export async function streamChat(
  body: Record<string, unknown>,
  onDelta: (text: string) => void,
  signal?: AbortSignal,
): Promise<{ usage?: { completion_tokens?: number }; firstTokenAt?: number; thought: boolean; toolCalls: ToolCall[] }> {
  const r = await fetch(API_BASE + "/v1/chat/completions", {
    method: "POST",
    headers: { ...HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, stream: true, stream_options: { include_usage: true } }),
    signal,
  });
  if (!r.ok || !r.body) await handle(r);
  const reader = r.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let usage;
  let firstTokenAt: number | undefined;
  let thought = false;
  // Tool calls arrive in pieces: the first piece of each has its id and name, the rest add to its arguments.
  const toolCalls: ToolCall[] = [];
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      const t = line.trim();
      if (!t.startsWith("data:")) continue;
      const data = t.slice(5).trim();
      if (data === "[DONE]") continue;
      try {
        const j = JSON.parse(data);
        if (j.error) throw new ApiError(j.error.message ?? "The model stopped with an error", 500);
        const delta = j.choices?.[0]?.delta ?? {};
        if (delta.reasoning_content) thought = true;
        if ((delta.content || delta.reasoning_content) && firstTokenAt === undefined) firstTokenAt = performance.now();
        if (delta.content) onDelta(delta.content);
        for (const tc of delta.tool_calls ?? []) {
          const i = tc.index ?? toolCalls.length;
          toolCalls[i] ??= { id: tc.id ?? `call_${i}`, name: "", arguments: "" };
          if (tc.id) toolCalls[i].id = tc.id;
          if (tc.function?.name) toolCalls[i].name += tc.function.name;
          if (tc.function?.arguments) toolCalls[i].arguments += tc.function.arguments;
        }
        if (j.usage) usage = j.usage;
      } catch (e) {
        if (e instanceof ApiError) throw e;
      }
    }
  }
  return { usage, firstTokenAt, thought, toolCalls: toolCalls.filter(Boolean) };
}

// --- types -------------------------------------------------------------------

export type Task = "chat" | "image" | "video" | "speech" | "transcribe" | "sound" | "embed";

export interface Gpu {
  index: number;
  name: string;
  memory_total: number;
  memory_used: number;
  memory_free: number;
  utilization: number | null;
  temperature: number | null;
  models: string[];
}

export interface Worker {
  id: string;
  task: Task;
  engine: string;
  status: "loading" | "ready" | "error" | "stopped";
  error: string | null;
  gpus: number[];
  split: number[] | null;
  offload: boolean;
  /** Chat models bigger than memory: read from the drive as they write. */
  from_drive?: boolean;
  /** Chat models: conversation memory in tokens (null = the default from Settings). */
  context: number | null;
  /** Chat models placed by llama.cpp's planner: layers on the graphics cards / in total. */
  gpu_layers?: number | null;
  total_layers?: number | null;
  title: string;
}

export interface SystemInfo {
  cpu_count: number;
  ram_total: number;
  ram_available: number;
  wsl?: boolean;
  cuda_driver: string | null;
  gpus: Gpu[];
  engines: { llamacpp: { status: string; progress: number; message: string; error: string | null; backend: string } };
  loaded: Worker[];
  events: { time: number; message: string }[];
  disk_free: number;
}

export interface InstalledModel {
  id: string;
  repo_id: string;
  task: Task;
  task_label: string;
  engine: string;
  size_bytes: number;
  meta: {
    title?: string; quant?: string; mmproj?: string | null; vram_bytes?: number; pipeline_tag?: string; needs_image?: boolean;
    /** A chat model trained here: its training run. */
    trained?: string;
  };
  loaded: Worker | null;
  last_error: string | null;
  defaults: Record<string, number>;
  /** Chat models: what the model file says it can do. */
  abilities?: { tools: boolean; thinks: boolean; vision: boolean; trained_context: number | null; layers: number | null };
  /** Chat models: measured tokens per second on this computer, once it has run. */
  speed?: number | null;
  /** Picture models only: samplers this model can switch between (empty when it can't). */
  samplers?: { samplers: { id: string; label: string }[]; default: string | null };
  /** Picture models only: your trained styles (LoRAs) that work with it. */
  styles?: TrainedStyle[];
  created_at: number;
}

export type VerdictLevel = "great" | "good" | "slow" | "disk" | "no" | "unknown";

/** How well a model will run on this computer, in plain words. */
export interface Verdict {
  level: VerdictLevel;
  label: string;
  detail: string;
  need: number | null;
  /** "Too big" chat models that could run from the drive if "Run models bigger than memory" were on. */
  drive_possible?: boolean;
}

export interface HubResult {
  repo_id: string;
  author: string;
  name: string;
  title: string;
  why?: string | null;
  task: Task;
  task_label: string;
  downloads?: number;
  likes?: number;
  gated?: boolean;
  params?: number | null;
  weights?: number | null;
  verdict: Verdict | null;
  vision?: boolean;
  tested?: boolean;
  /** Video models that animate a starting picture and can't work from text alone. */
  needs_image?: boolean;
  installed: boolean;
}

export interface Budget {
  gpus: { name: string; memory: number }[];
  all_gpus: number;
  best_gpu: number;
  ram: number;
  /** Inside WSL2: ram is WSL's share of the PC's memory. */
  wsl?: boolean;
}

export interface BrowseResult {
  results: HubResult[];
  has_more: boolean;
  budget: Budget;
}

export interface Overview {
  sections: { task: Task; results: HubResult[]; error?: string }[];
  budget: Budget;
}

export interface Variant {
  id: string;
  label: string;
  description: string;
  size: number;
  weights: number;
  rank: number;
  quant?: string;
  /** GGUF versions: bits per weight, from the file size and the model's parameter count. */
  bits?: number | null;
  vision?: boolean;
  verdict: Verdict | null;
  /** Whether it fits in the free space on the drive models are saved to. */
  fits_disk?: boolean;
}

export interface HubDetails extends Omit<HubResult, "installed"> {
  /** "llamacpp" for GGUF chat and search models, "diffusers" or "transformers" for the rest. */
  engine: string | null;
  supported: boolean;
  license?: string;
  tags: string[];
  variants: Variant[];
  recommended: string | null;
  /** Local ids of versions of this model already installed. */
  installed: string[];
  disk_free?: number;
}

/** How fast a chat model runs here, worked out from its file and this computer's measured speeds. */
export interface SpeedEstimate {
  /** Where each token's weights come from at worst: all on graphics cards, partly system memory, or partly the drive. */
  mode: "gpu" | "ram" | "drive";
  bytes_per_token: { gpu: number; ram: number; drive: number };
  model_bytes: number;
  moe: boolean;
  experts: { total: number; used: number };
  /** Share of the experts the processor needs that are found in memory rather than read from the drive. */
  memory_hit: number;
  /** The same for a model that keeps using a few experts more than the rest. */
  memory_hit_fast: number;
  context: number;
  speeds: { drive: number | null; drive_direct: number | null; drive_copy: number | null; ram: number; gpu: number };
  measuring_drive: boolean;
  /** WSL with the models on a Windows drive, read through WSL's file sharing: much slower. */
  windows_drive_under_wsl: boolean;
  drive_error: string | null;
  /** Whether "Run models bigger than memory" is on. */
  setting_on: boolean;
  seconds_per_token: number | null;
  tokens_per_second: number | null;
  /** Reading the drive: the fast end, for models that favour some experts. */
  tokens_per_second_fast: number | null;
  /** Reading the drive: seconds to read each 512 tokens of a message before replying. */
  prompt_seconds: number | null;
  /** Reading the drive: seconds to read a short message (about 20 tokens). */
  short_prompt_seconds: number | null;
  /** Reading the drive: the same for the first message after starting, with nothing in memory yet (a minimum). */
  first_prompt_seconds: number | null;
  /** Reading the drive: seconds to start. */
  start_seconds: number | null;
  /** Installed models: tokens a second measured on this computer, once it has run. */
  measured_tokens_per_second?: number | null;
}

export interface Download {
  id: string;
  repo_id: string;
  model_id: string;
  title: string;
  task: Task;
  variant: string;
  total: number;
  done: number;
  progress: number;
  speed: number;
  status: "queued" | "downloading" | "done" | "error" | "cancelled";
  error: string | null;
}

export interface Job {
  id: string;
  task: Task;
  model: string;
  status: "queued" | "loading" | "running" | "completed" | "failed";
  error: string | null;
  progress: number;
  step: number;
  total_steps: number;
  prompt: string;
  result: { files?: string[]; seed?: number; text?: string; segments?: Segment[]; duration?: number } | null;
}

export interface Segment {
  start: number;
  end: number | null;
  text: string;
}

export interface Generation {
  id: string;
  kind: "image" | "video" | "audio" | "text";
  model_id: string;
  prompt: string;
  params: Record<string, unknown>;
  files: string[];
  created_at: number;
}

// --- Code projects ------------------------------------------------------------------------------

export type ApprovalMode = "ask_commands" | "ask_all" | "auto";

export interface CodeProject {
  id: string;
  name: string;
  description: string;
  created: number;
  updated: number;
  approval: ApprovalMode;
  model: string | null;
  /** Conversation memory in tokens; null = automatic. */
  context: number | null;
  always_allow: string[];
  /** Knowledge libraries the agent can search with its search_knowledge tool. */
  knowledge?: string[];
  files?: number;
  running?: boolean;
  /** Sandbox port -> port on this computer, for previews. */
  ports?: Record<string, number>;
  shells?: { shell_id: string; command: string }[];
}

export interface CodeEvent {
  id: string;
  /** inbox and notify come from agents only. */
  type: "user" | "assistant" | "tool" | "notice" | "error" | "inbox" | "notify";
  time: number;
  text?: string;
  /** An agent's inbox: where it came from (webhook, program, schedule, wanna.sh) and who sent it. */
  source?: string;
  by?: string;
  /** A notification an agent sent. */
  title?: string;
  urgent?: boolean;
  /** More to show on request, e.g. the summary an agent wrote of its memory. */
  detail?: string;
  thinking?: string;
  name?: string;
  args?: Record<string, unknown>;
  status?: "running" | "awaiting_approval" | "done" | "error" | "denied" | "stopped";
  result?: string;
  diff?: string;
  ports?: Record<string, number>;
}

export interface Todo {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export type CodeStreamMessage =
  | { type: "snapshot"; events: CodeEvent[]; todos: Todo[]; running: boolean }
  | { type: "upsert"; event: CodeEvent }
  | { type: "todos"; todos: Todo[] }
  | { type: "status"; running: boolean };

/** Follow a project's agent events (Server-Sent Events over fetch, so the UI header is sent). */
export function followCode(pid: string, onMessage: (m: CodeStreamMessage) => void, signal: AbortSignal) {
  followEvents(`/api/code/projects/${pid}/events`, onMessage, signal);
}

/** Follow an agent's events, as followCode does a project's. */
export function followAgent(id: string, onMessage: (m: AgentStreamMessage) => void, signal: AbortSignal) {
  followEvents(`/api/agents/${id}/events`, onMessage, signal);
}

function followEvents<M>(path: string, onMessage: (m: M) => void, signal: AbortSignal) {
  const connect = async () => {
    while (!signal.aborted) {
      try {
        const r = await fetch(`${API_BASE}${path}`, { headers: HEADERS, signal });
        if (!r.ok || !r.body) throw new Error(String(r.status));
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const parts = buf.split("\n\n");
          buf = parts.pop() ?? "";
          for (const part of parts) {
            const line = part.split("\n").find((l) => l.startsWith("data:"));
            if (line) onMessage(JSON.parse(line.slice(5)));
          }
        }
      } catch {
        if (signal.aborted) return;
      }
      // The connection dropped (e.g. the server restarted): try again shortly.
      await new Promise((res) => setTimeout(res, 1500));
    }
  };
  connect();
}

// --- agents ---------------------------------------------------------------------------------------

export type AgentPace = "when_needed" | "always";

export interface AgentNotification {
  id: string;
  time: number;
  title: string;
  message: string;
  urgent: boolean;
  read: boolean;
}

export interface AgentService {
  name: string;
  command: string;
  running: boolean;
  /** Times it was restarted in the last 10 minutes. */
  restarts: number[];
  /** Why it isn't restarted any more ("gave up" after crashing repeatedly), or null. */
  stopped: string | null;
  started: number | null;
}

export interface AgentStatus {
  state: "off" | "starting" | "working" | "waiting" | "resting" | "failed";
  note: string;
  wait_until: number | null;
  inbox: number;
  schedules: { id: string; note: string; next: number; every: number | null }[];
  compactions: number;
  services: AgentService[];
  notifications: AgentNotification[];
}

export interface Agent {
  id: string;
  name: string;
  goals: string;
  created: number;
  updated: number;
  on: boolean;
  model: string | null;
  context: number | null;
  pace: AgentPace;
  approval: "auto" | "ask_commands";
  always_allow: string[];
  max_steps_per_hour: number;
  notify_url: string;
  /** Secret names; values are never sent to the page (null keeps the stored value). */
  secrets: Record<string, string | null>;
  knowledge: string[];
  hook_token: string;
}

/** The list: state is just its name there, with how many notifications are unread. */
export type AgentSummary = Agent & { state: AgentStatus["state"]; unread: number; latest: AgentNotification | null };
export type AgentDetail = Agent & { state: AgentStatus; running: boolean; ports?: Record<string, number> };

export type AgentStreamMessage =
  | { type: "snapshot"; events: CodeEvent[]; todos: Todo[]; running: boolean; state: AgentStatus }
  | { type: "upsert"; event: CodeEvent }
  | { type: "todos"; todos: Todo[] }
  | { type: "status"; running: boolean }
  | { type: "state"; state: AgentStatus; running: boolean };

// --- readiness ------------------------------------------------------------------------------------

export interface SystemCheckItem {
  id: string;
  label: string;
  status: "ok" | "warn" | "fail";
  detail: string;
}

export interface MemoryOption {
  context: number;
  rating: "fast" | "ok" | "slow" | "unknown";
  label: string;
}

export interface MemoryOptions {
  options: MemoryOption[];
  recommended: number;
  trained_context: number | null;
  /** Models that were loaded while measuring; live figures then understate what this computer can do. */
  measured_with_loaded: string[];
}

// --- knowledge (document search) ---------------------------------------------------

export interface KnowledgeLibrary {
  id: string;
  name: string;
  description: string;
  embed_model: string | null;
  hidden: boolean;
  created_at: number;
  updated_at: number;
  documents: number;
  passages: number;
  size_bytes: number;
}

export interface KnowledgeDoc {
  id: string;
  library_id: string;
  name: string;
  size_bytes: number;
  pages: number | null;
  chunks: number;
  status: "queued" | "indexing" | "ready" | "error";
  error: string | null;
  progress: number;
  truncated: number;
  created_at: number;
}

/** A passage found by search. */
export interface KnowledgeResult {
  id: number;
  document_id: string;
  library_id: string;
  document: string;
  library: string | null;
  page: number | null;
  heading: string;
  text: string;
  score: number;
  matched: ("meaning" | "words")[];
  /** A passage that is a picture (a picture file, or a page of a scanned PDF): where to get the picture. */
  picture?: string | null;
}

export interface KnowledgeStatus {
  /** pictures: it can search pictures as well as text. */
  search_models: { id: string; repo_id: string; size_bytes: number; pictures: boolean }[];
  default: string | null;
  suggested: { repo_id: string; title: string; why: string; installed: boolean; pictures: boolean }[];
  downloading: Download[];
}

// --- training your own picture styles and chat models (LoRA) ----------------------------------------------------

export interface TrainedStyle {
  id: string;
  name: string;
  trigger: string;
  /** A prompt that uses it, to start from. */
  prompt: string;
}

export interface TrainModel {
  id: string;
  repo_id: string;
  title: string;
  kind: "sd" | "sdxl";
  /** Bytes of graphics memory training it needs. */
  needs: number;
  resolution: number;
  /** The card it would train on, or null when no card here is big enough. */
  card: string | null;
  seconds_per_step: number | null;
}

export type TrainStage =
  | "queued" | "downloading" | "preparing" | "training" | "saving" | "samples" | "done" | "error" | "stopped"
  | "interrupted";

export interface TrainRun {
  id: string;
  type: "picture" | "chat";
  name: string;
  /** subject and style train picture models; voice (your writing) and chats (example chats) train chat models. */
  preset: "subject" | "style" | "voice" | "chats";
  trigger: string;
  what: string;
  model: string;
  model_title: string | null;
  kind: "sd" | "sdxl" | "chat";
  steps: number;
  created: number;
  status: {
    stage: TrainStage; message?: string; step?: number; steps?: number; loss?: number; seconds_left?: number;
    seconds?: number; done_bytes?: number; total_bytes?: number;
    /** Chat runs: the strength it was saved at (lower than 1 when full strength made replies repeat). */
    strength?: number;
  };
  /** Finished, with a trained style or chat model ready to use. */
  ready: boolean;
  // Picture runs:
  pictures?: number;
  samples?: string[];
  prompt?: string;
  // Chat runs:
  examples?: number;
  /** How the original was held while training: at full precision, or in 4 bits. */
  mode?: "bf16" | "4bit";
  original?: string;
  /** The installed chat model it became. */
  chat_model?: string | null;
  replies?: { prompt: string; before: string; after: string }[];
}

export interface TrainChatModel {
  id: string;
  repo_id: string;
  title: string;
  /** The original (trainable) weights, downloaded once the first time it's trained. */
  original: string | null;
  original_bytes: number | null;
  downloaded: boolean;
  /** How it would train here; null when it can't. */
  plan: { mode: "bf16" | "4bit"; cards: number[]; needs: number; card: string } | null;
  seconds_per_example: number | null;
  why_not: string | null;
}

export interface TrainChatOverview {
  ready: TrainOverview["ready"];
  models: TrainChatModel[];
}

export interface TrainOverview {
  /** Whether this computer can train; missing says what to install ("ml", "peft") or that a card is needed ("gpu"). */
  ready: { ok: boolean; missing: "ml" | "peft" | "gpu" | null; reason: string | null };
  models: TrainModel[];
  runs: TrainRun[];
}

// --- your own AI for a task --------------------------------------------------------------------------------------

export interface TaskColumn {
  name: string;
  kind: "number" | "category" | "text";
  distinct: number;
  filled: number;
  sample: string[];
  values?: string[];
}

export interface TaskLabelResult {
  label: string;
  /** Examples that really are this. */
  examples: number;
  /** Of those, how many it said were. */
  found: number;
  /** How often it gave this answer. */
  said: number;
}

export interface TaskReport {
  kind: "label" | "number" | "text";
  how: string;
  tested: number;
  seconds?: number;
  unchecked?: number;
  // Labels:
  accuracy?: number;
  baseline?: { answer: string | number; accuracy?: number; mean_error?: number };
  labels?: TaskLabelResult[];
  confusion?: { labels: string[]; counts: number[][] };
  tradeoffs?: {
    label: string;
    other: string;
    total: number;
    threshold: number;
    rows: { threshold: number; flagged: number; caught: number; false_alarms: number }[];
  };
  uses?: { column: string; share: number }[];
  mistakes?: { input: string; answer: string | number; said: string | number; confidence?: number | null }[];
  // Numbers:
  mean_error?: number;
  median_error?: number;
  within_10_percent?: number;
  // Written answers:
  exact?: number;
  fields?: { right: number; total: number; valid_json: number };
  pairs?: { input: string; answer: string; said: string; same: boolean }[];
}

export type TaskStage = "new" | "training" | "drafting" | "drafted" | "done" | "error" | "interrupted";

export interface UserTask {
  id: string;
  name: string;
  description: string;
  created: number;
  input_kind: "table" | "text" | "picture";
  answer_kind: "label" | "number" | "text";
  columns: TaskColumn[];
  input_columns: string[];
  answer_column: string | null;
  chats?: boolean;
  examples: number;
  answered: number;
  drafted: number;
  labels: string[];
  label_counts: Record<string, number>;
  threshold?: number;
  in_chat?: boolean;
  chat_model?: string | null;
  tool: string;
  ready: boolean;
  report: TaskReport | null;
  status: {
    stage: TaskStage;
    message?: string;
    step?: number;
    steps?: number;
    seconds_left?: number;
    seconds?: number;
    done_bytes?: number;
    total_bytes?: number;
  };
}

export interface TaskExample {
  n: number;
  input: Record<string, unknown> | string;
  answer: string | number | null;
  drafted?: boolean;
}

export interface TaskAnswer {
  answer: string | number;
  confidence?: number;
  scores?: Record<string, number>;
}
