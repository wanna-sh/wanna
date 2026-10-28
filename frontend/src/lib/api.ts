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
};

export const fileUrl = (name: string) => `${API_BASE}/files/${name}`;

/** Stream an OpenAI-style chat completion, calling onDelta with each visible text piece.
 *  Reasoning models stream hidden "thinking" first (reasoning_content); it isn't shown, but it counts
 *  towards the token total, so `firstTokenAt` marks the first token of either kind for speed figures. */
export async function streamChat(
  body: Record<string, unknown>,
  onDelta: (text: string) => void,
  signal?: AbortSignal,
): Promise<{ usage?: { completion_tokens?: number }; firstTokenAt?: number; thought: boolean }> {
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
        if (j.usage) usage = j.usage;
      } catch (e) {
        if (e instanceof ApiError) throw e;
      }
    }
  }
  return { usage, firstTokenAt, thought };
}

// --- types -------------------------------------------------------------------

export type Task = "chat" | "image" | "video" | "speech" | "transcribe" | "sound";

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
  meta: { title?: string; quant?: string; mmproj?: string | null; vram_bytes?: number; pipeline_tag?: string; needs_image?: boolean };
  loaded: Worker | null;
  last_error: string | null;
  defaults: Record<string, number>;
  /** Chat models: what the model file says it can do. */
  abilities?: { tools: boolean; thinks: boolean; vision: boolean; trained_context: number | null; layers: number | null };
  /** Chat models: measured tokens per second on this computer, once it has run. */
  speed?: number | null;
  /** Picture models only: samplers this model can switch between (empty when it can't). */
  samplers?: { samplers: { id: string; label: string }[]; default: string | null };
  created_at: number;
}

export type VerdictLevel = "great" | "good" | "slow" | "no" | "unknown";

/** How well a model will run on this computer, in plain words. */
export interface Verdict {
  level: VerdictLevel;
  label: string;
  detail: string;
  need: number | null;
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
  vision?: boolean;
  verdict: Verdict | null;
}

export interface HubDetails extends Omit<HubResult, "installed"> {
  supported: boolean;
  license?: string;
  tags: string[];
  variants: Variant[];
  recommended: string | null;
  /** Local ids of versions of this model already installed. */
  installed: string[];
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
  files?: number;
  running?: boolean;
  /** Sandbox port -> port on this computer, for previews. */
  ports?: Record<string, number>;
  shells?: { shell_id: string; command: string }[];
}

export interface CodeEvent {
  id: string;
  type: "user" | "assistant" | "tool" | "notice" | "error";
  time: number;
  text?: string;
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
  const connect = async () => {
    while (!signal.aborted) {
      try {
        const r = await fetch(`${API_BASE}/api/code/projects/${pid}/events`, { headers: HEADERS, signal });
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
