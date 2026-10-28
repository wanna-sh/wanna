"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Archive, ArchiveRestore, FileText, History, Loader2, Mic, Paperclip, Plus, Search, Square, Trash2, X } from "lucide-react";
import Link from "next/link";
import { api, streamChat } from "@/lib/api";
import { useDictation } from "@/lib/dictation";
import { useModels, usePoll, useStored } from "@/lib/hooks";
import { NoModelYet, useTaskModel } from "@/components/models";
import { ChipButton, ModelMenu, PromptBar, ToggleChip, modelName } from "@/components/studio";
import { Notice, PageHeader, Segmented, inputClass } from "@/components/ui";
import { ago } from "@/lib/format";

type Part = { type: "text"; text: string } | { type: "image_url"; image_url: { url: string } };
/** A document attached to a message. Its text is sent to the model; the bubble shows a chip. */
interface Doc {
  name: string;
  text: string;
  pages?: number | null;
  /** True when only the first part fit in the model's conversation memory. */
  trimmed?: boolean;
}
interface Message {
  role: "user" | "assistant" | "system";
  content: string | Part[];
  docs?: Doc[];
  stats?: string;
}
interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  updated: number;
  /** Archived chats are hidden from Recent but kept; sending a new message brings one back. */
  archived?: boolean;
}

const SUGGESTIONS = [
  "Explain how a rainbow forms, like I'm ten",
  "Write a friendly email asking to reschedule a meeting",
  "Give me a 3-day meal plan with simple recipes",
  "Help me write a Python script that renames photos by date",
];

const textOf = (c: Message["content"]) =>
  typeof c === "string" ? c : c.map((p) => (p.type === "text" ? p.text : "")).join("");
// Timing lives outside the component so the React compiler doesn't treat it as render work.
const now = () => performance.now();

const imagesOf = (c: Message["content"]) =>
  typeof c === "string" ? [] : c.flatMap((p) => (p.type === "image_url" ? [p.image_url.url] : []));

// Documents we can read: PDFs (on the server) and anything that's plain text.
const DOC_EXT = /\.(pdf|txt|md|markdown|csv|tsv|json|jsonl|xml|html?|ya?ml|toml|ini|log|py|js|jsx|ts|tsx|java|kt|c|cc|cpp|h|hpp|cs|go|rs|rb|php|swift|sh|ps1|sql|css|scss|tex|rst)$/i;
const MAX_IMAGES = 4;
const MAX_IMAGE_SIDE = 1536;
const MAX_DOCS = 5;

/** What the model receives for a message: attached documents' text goes ahead of what you typed. */
function apiContent(m: Message): Message["content"] {
  if (!m.docs?.length) return m.content;
  const files = m.docs.map((d) => `<file name="${d.name}">\n${d.text}\n</file>`).join("\n\n");
  const intro = `I've attached ${m.docs.length === 1 ? "a file" : `${m.docs.length} files`}:\n\n${files}\n\n`;
  if (typeof m.content === "string") return intro + m.content;
  const images = m.content.filter((p) => p.type === "image_url");
  return [...images, { type: "text", text: intro + textOf(m.content) }];
}

export default function ChatPage() {
  const { models, loaded, refresh } = useModels("chat");
  const [model, setModel] = useTaskModel("chat", models);
  const [convos, setConvos] = useStored<Conversation[]>("wanna.chats", []);
  const [activeId, setActiveId] = useStored<string>("wanna.chat.active", "");
  const [system, setSystem] = useStored<string>("wanna.chat.system", "");
  const [input, setInput] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [reading, setReading] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const convo = convos.find((c) => c.id === activeId);
  const messages = convo?.messages ?? [];
  const current = models.find((m) => m.id === model);
  const canSee = !!current?.meta.mmproj;
  const seeing = models.filter((m) => m.meta.mmproj);
  const blockedByPictures = images.length > 0 && !canSee;
  const { data: settings } = usePoll<{ default_context: number }>("/api/settings");
  const { models: transcribers } = useModels("transcribe");
  // Roughly 3.5 characters per token, leaving room for the conversation and the reply.
  const contextTokens = current?.loaded?.context ?? settings?.default_context ?? 8192;
  const docBudget = Math.floor(contextTokens * 0.6 * 3.5);
  const dictation = useDictation((t) => setInput((prev) => (prev.trim() ? `${prev.trimEnd()} ${t}` : t)));

  const lastText = messages.length ? textOf(messages[messages.length - 1].content) : "";
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages.length, lastText]);

  const update = (id: string, fn: (c: Conversation) => Conversation) =>
    setConvos((cs) => cs.map((c) => (c.id === id ? fn(c) : c)));

  const send = async (text: string) => {
    if ((!text.trim() && !images.length && !docs.length) || busy || !model || blockedByPictures || reading) return;
    setError(null);
    let id = activeId;
    if (!convo) {
      id = crypto.randomUUID();
      const title = text.slice(0, 60) || docs[0]?.name || "Picture chat";
      setConvos((cs) => [{ id, title, messages: [], updated: Date.now() }, ...cs]);
      setActiveId(id);
    }
    const content: Message["content"] = images.length
      ? [...images.map((url) => ({ type: "image_url" as const, image_url: { url } })), { type: "text", text }]
      : text;
    const userMsg: Message = { role: "user", content, ...(docs.length ? { docs } : {}) };
    const history = [...messages, userMsg];
    update(id, (c) => ({
      ...c,
      archived: false,
      messages: [...history, { role: "assistant", content: "" }],
      updated: Date.now(),
    }));
    setInput("");
    setImages([]);
    setDocs([]);
    setNotice(null);
    setBusy(true);

    const ctrl = new AbortController();
    abort.current = ctrl;
    const t0 = now();
    let out = "";
    try {
      const payload = [
        ...(system.trim() ? [{ role: "system", content: system }] : []),
        ...history.map((m) => ({ role: m.role, content: apiContent(m) })),
      ];
      const { usage, firstTokenAt, thought } = await streamChat(
        { model, messages: payload },
        (piece) => {
          out += piece;
          update(id, (c) => {
            const ms = [...c.messages];
            ms[ms.length - 1] = { role: "assistant", content: out };
            return { ...c, messages: ms };
          });
        },
        ctrl.signal,
      );
      const secs = (now() - (firstTokenAt ?? t0)) / 1000;
      const tokens = usage?.completion_tokens;
      const stats =
        tokens && secs > 0
          ? `${tokens} tokens${thought ? " including thinking" : ""}, ${(tokens / secs).toFixed(1)} per second`
          : undefined;
      update(id, (c) => {
        const ms = [...c.messages];
        ms[ms.length - 1] = { role: "assistant", content: out, stats };
        return { ...c, messages: ms };
      });
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
      if (!out) update(id, (c) => ({ ...c, messages: c.messages.slice(0, -1) }));
    } finally {
      setBusy(false);
      abort.current = null;
    }
  };

  /**
   * Pictures go to the model as PNG or JPEG: llama.cpp can't decode formats like WebP. Large photos are
   * scaled down too, since vision models shrink them anyway and full-size photos bloat saved chats.
   */
  const readImage = async (f: File): Promise<string> => {
    let bitmap: ImageBitmap;
    try {
      bitmap = await createImageBitmap(f);
    } catch {
      throw new Error(`Couldn't open ${f.name}. Try a PNG or JPEG picture.`);
    }
    const scale = Math.min(1, MAX_IMAGE_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    // PNG keeps screenshots and diagrams crisp; photos are much smaller as JPEG.
    const png = canvas.toDataURL("image/png");
    return png.length < 1_500_000 ? png : canvas.toDataURL("image/jpeg", 0.9);
  };

  const readDoc = async (f: File): Promise<Doc> => {
    const isPdf = /\.pdf$/i.test(f.name) || f.type === "application/pdf";
    let text: string;
    let pages: number | null = null;
    if (isPdf) {
      const r = await api.upload<{ text: string; pages: number | null }>("/api/extract-text", f, f.name);
      text = r.text;
      pages = r.pages;
    } else {
      text = await f.text();
    }
    return { name: f.name, text, pages };
  };

  /** Attach pictures and documents from the file picker, a paste, or a drop. */
  const addFiles = async (files: File[]) => {
    setError(null);
    setNotice(null);
    const pics = files.filter((f) => f.type.startsWith("image/"));
    const papers = files.filter((f) => !f.type.startsWith("image/"));
    const unknown = papers.filter((f) => !DOC_EXT.test(f.name) && !f.type.startsWith("text/"));
    if (unknown.length) {
      setNotice(`Can't read ${unknown.map((f) => f.name).join(", ")}. Attach pictures, PDFs, or text, Markdown, CSV or code files.`);
    }
    for (const f of pics) {
      try {
        const url = await readImage(f);
        setImages((im) => [...im, url].slice(0, MAX_IMAGES));
      } catch (e) {
        setError((e as Error).message);
      }
    }
    const readable = papers.filter((f) => !unknown.includes(f)).slice(0, MAX_DOCS - docs.length);
    if (!readable.length) return;
    setReading((n) => n + readable.length);
    for (const f of readable) {
      try {
        const d = await readDoc(f);
        setDocs((ds) => {
          // Share the model's memory between all attached documents.
          const all = [...ds, d];
          const total = all.reduce((a, x) => a + x.text.length, 0);
          if (total <= docBudget) return all;
          return all.map((x) => {
            const share = Math.floor(docBudget * (x.text.length / total));
            return x.text.length > share ? { ...x, text: x.text.slice(0, share), trimmed: true } : x;
          });
        });
      } catch (e) {
        setError(`${f.name}: ${(e as Error).message}`);
      } finally {
        setReading((n) => n - 1);
      }
    }
  };

  if (loaded && !models.length) {
    return (
      <>
        <PageHeader title="Chat with an assistant" art="chat" />
        <NoModelYet task="chat" onInstalled={refresh} />
      </>
    );
  }

  const recentCount = convos.filter((c) => !c.archived).length;
  const newChat = () => {
    setActiveId("");
    setError(null);
  };

  return (
    <>
      <section className="flex flex-col h-[calc(100dvh-6rem)] lg:h-[calc(100dvh-3rem)] w-full max-w-[800px] mx-auto">
        <div className="flex items-center justify-between gap-3 pb-3">
          <h1 className="font-display text-[1.25rem] truncate min-w-0">{convo?.title ?? "New chat"}</h1>
          <div className="flex items-center gap-2 shrink-0">
            <ChipButton onClick={() => setHistoryOpen(true)}>
              <History size={15} aria-hidden /> Chats{recentCount > 0 ? ` (${recentCount})` : ""}
            </ChipButton>
            <ChipButton onClick={newChat}>
              <Plus size={15} aria-hidden /> New chat
            </ChipButton>
          </div>
        </div>
        {convo?.archived && (
          <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-line px-4 py-2.5 text-[14px] text-slate">
            <Archive size={15} aria-hidden /> This chat is archived. Sending a message brings it back to Recent.
            <button className="underline underline-offset-2 hover:text-ink" onClick={() => update(convo.id, (c) => ({ ...c, archived: false }))}>
              Unarchive now
            </button>
          </div>
        )}

        <div ref={scroller} className="flex-1 overflow-y-auto min-h-0 pr-1" aria-live="polite">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col justify-center items-center text-center py-10">
              <p className="font-display text-[clamp(2.2rem,4vw,3rem)] leading-tight mb-6">What&apos;s on your mind?</p>
              <div className="grid sm:grid-cols-2 gap-2 w-full text-left">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="text-left rounded-xl border border-line px-4 py-3 text-[14px] text-slate hover:text-ink hover:bg-well/60 transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <ol className="flex flex-col gap-6 pb-6 pt-2">
              {messages.map((m, i) => (
                <li key={i} className={m.role === "user" ? "self-end max-w-[85%]" : "w-full"}>
                  {m.role === "user" ? (
                    <div className="rounded-3xl bg-well text-ink px-4 py-2.5 whitespace-pre-wrap text-[15px]">
                      {!!m.docs?.length && (
                        <div className="flex flex-wrap gap-1.5 mb-2">
                          {m.docs.map((d, j) => (
                            <DocChip key={j} doc={d} />
                          ))}
                        </div>
                      )}
                      {imagesOf(m.content).map((u, j) => (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img key={j} src={u} alt="Attached" className="max-h-48 rounded-lg mb-2" />
                      ))}
                      {textOf(m.content)}
                    </div>
                  ) : (
                    <div>
                      <div className="prose-chat text-[15.5px] leading-relaxed">
                        {textOf(m.content) ? (
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{textOf(m.content)}</ReactMarkdown>
                        ) : (
                          <span className="text-slate">
                            {busy && current?.loaded?.status !== "ready" ? "Starting the model…" : "Thinking…"}
                          </span>
                        )}
                      </div>
                      {m.stats && <div className="text-[12px] text-slate mt-1">{m.stats}</div>}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>

        {error && (
          <div className="mb-3">
            <Notice tone="error">{error}</Notice>
          </div>
        )}

        {showSettings && (
          <label className="block mb-3">
            <span className="block text-[14px] font-medium mb-1.5">How should the assistant behave?</span>
            <textarea
              className={`${inputClass} min-h-20`}
              placeholder="For example: You are a patient tutor. Keep answers short."
              value={system}
              onChange={(e) => setSystem(e.target.value)}
            />
          </label>
        )}
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          accept="image/*,.pdf,.txt,.md,.markdown,.csv,.tsv,.json,.jsonl,.xml,.html,.htm,.yaml,.yml,.toml,.ini,.log,.py,.js,.jsx,.ts,.tsx,.java,.kt,.c,.cc,.cpp,.h,.hpp,.cs,.go,.rs,.rb,.php,.swift,.sh,.ps1,.sql,.css,.scss,.tex,.rst"
          onChange={(e) => {
            addFiles([...(e.target.files ?? [])]);
            e.target.value = "";
          }}
        />
        {(notice || dictation.error || blockedByPictures) && (
          <div className="mb-3 flex flex-col gap-2">
            {blockedByPictures && (
              <Notice>
                {current ? modelName(current) : "This model"} can&apos;t see pictures.{" "}
                {seeing.length ? (
                  <button className="underline underline-offset-2" onClick={() => setModel(seeing[0].id)}>
                    Switch to {modelName(seeing[0])}
                  </button>
                ) : (
                  <>
                    <Link href="/discover/?task=chat" className="underline underline-offset-2">
                      Get a model that can
                    </Link>
                    , such as Gemma 4,
                  </>
                )}{" "}
                or remove the picture.
              </Notice>
            )}
            {notice && <Notice>{notice}</Notice>}
            {dictation.error && <Notice tone="error">{dictation.error}</Notice>}
          </div>
        )}
        <PromptBar
          value={input}
          onChange={setInput}
          placeholder="Message the assistant"
          onSubmit={() => send(input)}
          submitLabel="Send"
          canSubmit={(!!input.trim() || images.length > 0 || docs.length > 0) && !!model && !blockedByPictures && !reading}
          busy={busy}
          onStop={() => abort.current?.abort()}
          onFiles={addFiles}
          actions={
            <MicButton
              state={dictation.state}
              seconds={dictation.seconds}
              available={transcribers.length > 0}
              onStart={dictation.start}
              onStop={dictation.stop}
              onCancel={dictation.cancel}
              onUnavailable={() =>
                dictation.setError(
                  "To speak instead of typing, get a transcription model such as Whisper from Get models, under Transcribe.",
                )
              }
            />
          }
          top={
            (images.length > 0 || docs.length > 0 || reading > 0) && (
              <div className="flex flex-wrap items-center gap-2">
                {docs.map((d, i) => (
                  <DocChip key={i} doc={d} onRemove={() => setDocs((ds) => ds.filter((_, j) => j !== i))} />
                ))}
                {reading > 0 && (
                  <span className="inline-flex items-center gap-2 h-9 px-3 rounded-xl border border-line text-[13px] text-slate">
                    <Loader2 size={14} className="animate-spin" aria-hidden /> Reading…
                  </span>
                )}
                {images.map((u, i) => (
                  <div key={i} className="relative">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={u} alt="To send" className="size-16 object-cover rounded-xl border border-line" />
                    <button
                      type="button"
                      aria-label="Remove picture"
                      onClick={() => setImages((im) => im.filter((_, j) => j !== i))}
                      className="absolute -top-2 -right-2 size-6 grid place-items-center rounded-full bg-ink text-fog"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )
          }
          tools={
            <>
              <ModelMenu models={models} value={model} onChange={setModel} task="chat" />
              <ChipButton onClick={() => fileInput.current?.click()} label="Attach pictures or documents">
                <Paperclip size={15} aria-hidden /> Attach
              </ChipButton>
              <ToggleChip on={showSettings} onChange={setShowSettings}>
                Instructions{system.trim() && !showSettings ? " (on)" : ""}
              </ToggleChip>
            </>
          }
        />
        <p className="text-[12px] text-slate mt-2 text-center">
          Conversations are saved in this browser only. Enter sends, Shift+Enter adds a new line. Drop or paste files to attach them.
        </p>
      </section>

      <ChatHistory
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        convos={convos}
        activeId={activeId}
        onOpen={(id) => {
          setActiveId(id);
          setError(null);
          setHistoryOpen(false);
        }}
        onChange={(next) => {
          setConvos(next);
          if (!next.some((c) => c.id === activeId)) setActiveId("");
        }}
      />
    </>
  );
}

/** Slide-in list of chats with Recent / Archived tabs, search, and bulk actions. */
function ChatHistory({
  open,
  onClose,
  convos,
  activeId,
  onOpen,
  onChange,
}: {
  open: boolean;
  onClose: () => void;
  convos: Conversation[];
  activeId: string;
  onOpen: (id: string) => void;
  onChange: (next: Conversation[]) => void;
}) {
  const [tab, setTab] = useState<"recent" | "archived">("recent");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const archived = convos.filter((c) => c.archived);
  const recent = convos.filter((c) => !c.archived);
  const q = query.trim().toLowerCase();
  const shown = (tab === "recent" ? recent : archived)
    .filter((c) => !q || c.title.toLowerCase().includes(q))
    .sort((a, b) => b.updated - a.updated);
  const setArchived = (ids: Set<string>, value: boolean) =>
    onChange(convos.map((c) => (ids.has(c.id) ? { ...c, archived: value } : c)));
  const plural = (n: number) => `${n} chat${n === 1 ? "" : "s"}`;

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Chats">
      <button className="absolute inset-0 bg-black/40" onClick={onClose} aria-label="Close chats" />
      {/* Opens beside the main sidebar on wide screens, from the left edge on phones. */}
      <div className="absolute inset-y-0 left-0 lg:left-[232px] w-full max-w-[360px] bg-fog border-r border-line flex flex-col">
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <h2 className="font-display text-[1.15rem]">Chats</h2>
          <button onClick={onClose} className="size-9 grid place-items-center rounded-full hover:bg-well" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="px-5 flex flex-col gap-3">
          <Segmented
            label="Which chats"
            value={tab}
            onChange={setTab}
            options={[
              { value: "recent", label: `Recent (${recent.length})` },
              { value: "archived", label: `Archived (${archived.length})` },
            ]}
          />
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate" aria-hidden />
            <input
              className={`${inputClass} pl-9 h-10 py-0`}
              placeholder="Search chats"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search chats"
            />
          </div>
        </div>

        <ul className="flex-1 overflow-y-auto px-3 py-3">
          {shown.length === 0 && (
            <li className="px-2.5 py-6 text-[14px] text-slate">
              {q
                ? "No chats match your search."
                : tab === "recent"
                  ? "No chats yet. Start one with New chat."
                  : "Nothing archived. Archive a chat to tidy it away without deleting it."}
            </li>
          )}
          {shown.map((c) => (
            <li key={c.id} className="group flex items-center rounded-lg hover:bg-well/60">
              <button
                onClick={() => onOpen(c.id)}
                className={`flex-1 min-w-0 text-left rounded-lg px-2.5 py-2 ${c.id === activeId ? "bg-well" : ""}`}
              >
                <span className="block truncate text-[14px]">{c.title}</span>
                <span className="block text-[12px] text-slate">{ago(c.updated / 1000)}</span>
              </button>
              <div className="flex shrink-0 pr-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100">
                <button
                  aria-label={c.archived ? `Unarchive ${c.title}` : `Archive ${c.title}`}
                  title={c.archived ? "Unarchive" : "Archive"}
                  onClick={() => setArchived(new Set([c.id]), !c.archived)}
                  className="size-8 grid place-items-center rounded-lg text-slate hover:text-ink"
                >
                  {c.archived ? <ArchiveRestore size={15} /> : <Archive size={15} />}
                </button>
                <button
                  aria-label={`Delete ${c.title}`}
                  title="Delete"
                  onClick={() => confirm(`Delete "${c.title}"? This can't be undone.`) && onChange(convos.filter((x) => x.id !== c.id))}
                  className="size-8 grid place-items-center rounded-lg text-slate hover:text-danger"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </li>
          ))}
        </ul>

        <div className="border-t border-line px-5 py-4 flex flex-wrap gap-x-4 gap-y-2 text-[14px]">
          {tab === "recent" && recent.length > 0 && (
            <button
              className="text-slate underline underline-offset-2 hover:text-ink"
              onClick={() =>
                confirm(`Archive ${plural(recent.length)}? You can find them under Archived.`) &&
                setArchived(new Set(recent.map((c) => c.id)), true)
              }
            >
              Archive all
            </button>
          )}
          {tab === "archived" && archived.length > 0 && (
            <>
              <button
                className="text-slate underline underline-offset-2 hover:text-ink"
                onClick={() => setArchived(new Set(archived.map((c) => c.id)), false)}
              >
                Unarchive all
              </button>
              <button
                className="text-danger underline underline-offset-2"
                onClick={() =>
                  confirm(`Delete ${plural(archived.length)} from Archived? This can't be undone.`) &&
                  onChange(convos.filter((c) => !c.archived))
                }
              >
                Delete archived
              </button>
            </>
          )}
          {convos.length > 0 && (
            <button
              className="text-danger underline underline-offset-2 ml-auto"
              onClick={() =>
                confirm(`Delete all ${plural(convos.length)}, including archived ones? This can't be undone.`) && onChange([])
              }
            >
              Delete all chats
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** An attached document: name, size, and a note when only part of it fits. */
function DocChip({ doc, onRemove }: { doc: Doc; onRemove?: () => void }) {
  const n = doc.text.length;
  const size = doc.pages
    ? `${doc.pages} page${doc.pages === 1 ? "" : "s"}`
    : n < 1000
      ? `${n} characters`
      : `${Math.round(n / 1000)}k characters`;
  return (
    <span
      className="inline-flex items-center gap-2 max-w-[260px] h-9 pl-2.5 pr-2 rounded-xl border border-line bg-paper text-[13px]"
      title={doc.trimmed ? "Only the first part fits in this model's conversation memory. Raise it in My models to read more." : doc.name}
    >
      <FileText size={15} className="text-slate shrink-0" aria-hidden />
      <span className="truncate text-ink">{doc.name}</span>
      <span className="text-slate shrink-0">{doc.trimmed ? "first part" : size}</span>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={`Remove ${doc.name}`} className="text-slate hover:text-ink">
          <X size={13} />
        </button>
      )}
    </span>
  );
}

/** Speak instead of typing. Shows a timer while recording and a spinner while writing it down. */
function MicButton({
  state,
  seconds,
  available,
  onStart,
  onStop,
  onCancel,
  onUnavailable,
}: {
  state: "idle" | "recording" | "transcribing";
  seconds: number;
  available: boolean;
  onStart: () => void;
  onStop: () => void;
  onCancel: () => void;
  onUnavailable: () => void;
}) {
  if (state === "recording") {
    return (
      <span className="inline-flex items-center gap-1">
        <button
          type="button"
          onClick={onCancel}
          aria-label="Cancel recording"
          className="size-9 grid place-items-center rounded-full text-slate hover:text-ink hover:bg-well"
        >
          <X size={16} />
        </button>
        <button
          type="button"
          onClick={onStop}
          aria-label="Stop and turn into text"
          className="h-9 pl-3 pr-3.5 inline-flex items-center gap-2 rounded-full bg-well text-[14px] tabular-nums"
        >
          <span className="size-2 rounded-full bg-danger animate-pulse" aria-hidden />
          {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
          <Square size={11} fill="currentColor" aria-hidden />
        </button>
      </span>
    );
  }
  if (state === "transcribing") {
    return (
      <span className="h-9 px-3 inline-flex items-center gap-2 rounded-full text-[14px] text-slate" role="status">
        <Loader2 size={15} className="animate-spin" aria-hidden /> Writing it down…
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={available ? onStart : onUnavailable}
      aria-label="Speak instead of typing"
      title="Speak instead of typing"
      className="size-9 grid place-items-center rounded-full text-slate hover:text-ink hover:bg-well"
    >
      <Mic size={18} />
    </button>
  );
}
