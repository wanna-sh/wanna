// Web search and page reading for chat: the tools the model can call, and running them through wanna.sh.
import { api, type ToolCall } from "./api";

/** A web page the model looked at while answering. */
export interface WebSource {
  url: string;
  title: string;
}

// Pages are cut to this many characters, so a few of them still fit in a chat model's conversation memory.
const PAGE_CHARS = 8000;

export const WEB_TOOLS = [
  {
    type: "function",
    function: {
      name: "web_search",
      description:
        "Search the web. Returns titles, links and short snippets. Use it for current events, facts you're unsure " +
        "of, or anything after your training data. Then read the most useful pages with web_fetch.",
      parameters: {
        type: "object",
        properties: { query: { type: "string", description: "What to search for, as you'd type it into a search engine." } },
        required: ["query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "web_fetch",
      description: "Read a web page or PDF and return its text.",
      parameters: {
        type: "object",
        properties: { url: { type: "string", description: "The page's full address, starting with https://" } },
        required: ["url"],
      },
    },
  },
];

export function webInstructions(): string {
  const today = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  return (
    `Today is ${today}. You can search the web with web_search and read pages with web_fetch. Use them when the ` +
    "question needs current or specific information you don't reliably know; otherwise answer directly. Search " +
    "results are only short snippets: before relying on specific details such as numbers, dates or versions, read the " +
    "most relevant page with web_fetch. If you couldn't find something, say so instead of guessing. When you use the " +
    "web, say which pages your answer comes from, as Markdown links."
  );
}

/** What the chat shows while a tool runs. */
export function describeCall(call: ToolCall): string {
  const args = parseArgs(call);
  if (call.name === "web_search") return `Searching the web for "${args.query ?? ""}"…`;
  if (call.name === "web_fetch") return `Reading ${hostOf(String(args.url ?? ""))}…`;
  return "Working…";
}

/** Run one tool call. Problems go back to the model as text, so it can try something else. */
export async function runCall(call: ToolCall, sources: WebSource[]): Promise<string> {
  const args = parseArgs(call);
  try {
    if (call.name === "web_search") {
      const r = await api.post<{ provider: string; results: { title: string; url: string; snippet: string }[] }>(
        "/api/web/search",
        { query: String(args.query ?? "") },
      );
      if (!r.results.length) return "No results.";
      return r.results.map((x, i) => `${i + 1}. ${x.title}\n${x.url}\n${x.snippet}`.trim()).join("\n\n");
    }
    if (call.name === "web_fetch") {
      const url = String(args.url ?? "");
      const r = await api.post<{ url: string; text: string }>("/api/web/fetch", { url });
      const title = r.text.split("\n").find((l) => l.trim() && !l.startsWith("URL:"))?.trim().slice(0, 120) || hostOf(url);
      if (!sources.some((s) => s.url === url)) sources.push({ url, title });
      return r.text.length > PAGE_CHARS ? `${r.text.slice(0, PAGE_CHARS)}\n\n[page cut off here]` : r.text;
    }
    return `There's no tool called ${call.name}.`;
  } catch (e) {
    return `That didn't work: ${(e as Error).message}`;
  }
}

function parseArgs(call: ToolCall): Record<string, unknown> {
  try {
    return JSON.parse(call.arguments || "{}");
  } catch {
    return {};
  }
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
