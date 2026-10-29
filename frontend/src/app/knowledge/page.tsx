"use client";

import { Suspense, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, BookOpen, Download, FileText, Loader2, Search, Trash2, Upload } from "lucide-react";
import {
  API_BASE,
  api,
  type KnowledgeDoc,
  type KnowledgeLibrary,
  type KnowledgeResult,
  type KnowledgeStatus,
} from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes, prettyName } from "@/lib/format";
import { Button, Field, Notice, PageHeader, Panel, Progress, inputClass } from "@/components/ui";
import { sourceLabel } from "@/components/knowledge";

// The same kinds of files Chat can read.
const ACCEPT =
  ".pdf,.txt,.md,.markdown,.csv,.tsv,.json,.jsonl,.xml,.html,.htm,.yaml,.yml,.toml,.ini,.log,.py,.js,.jsx,.ts,.tsx,.java,.kt,.c,.cc,.cpp,.h,.hpp,.cs,.go,.rs,.rb,.php,.swift,.sh,.ps1,.sql,.css,.scss,.tex,.rst";

export default function KnowledgePage() {
  return (
    <Suspense>
      <Knowledge />
    </Suspense>
  );
}

function Knowledge() {
  const lid = useSearchParams().get("l");
  const { data: status, refresh: refreshStatus } = usePoll<KnowledgeStatus>("/api/knowledge/status", 3000);
  const ready = !!status?.default;
  return (
    <>
      <PageHeader
        title="Knowledge"
        art="embed"
        intro="Put your documents in a library, then ask about them in Chat or Code. Answers use the passages that match your question and say where each fact came from. Everything stays on this computer."
      />
      {status && !ready && <Setup status={status} onStarted={refreshStatus} />}
      {ready && (lid ? <LibraryView lid={lid} searchModels={status.search_models} /> : <Libraries />)}
    </>
  );
}

/** First run: download a search model. */
function Setup({ status, onStarted }: { status: KnowledgeStatus; onStarted: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const downloading = status.downloading[0];
  const start = async (repo_id: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/knowledge/setup", { repo_id });
      onStarted();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const [first, ...others] = status.suggested;
  return (
    <Panel className="max-w-[760px]">
      <h2 className="font-display text-[1.25rem] leading-snug mb-1">Set up document search</h2>
      <p className="text-slate text-[15px] mb-5">
        Searching your documents needs a small search model. It reads each passage once and records what it means, so
        questions find the right passages even when they use different words.
      </p>
      {error && (
        <div className="mb-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {downloading ? (
        <Progress
          value={downloading.progress}
          label={`Downloading ${downloading.title ?? "the search model"} (${bytes(downloading.total)})`}
          live
        />
      ) : (
        <>
          {first && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
              <div className="min-w-0">
                <p className="font-medium">
                  {first.title} <span className="text-[13px] text-accent ml-1">Recommended</span>
                </p>
                <p className="text-[14px] text-slate">{first.why}</p>
              </div>
              <Button disabled={busy} onClick={() => start(first.repo_id)}>
                <Download size={15} aria-hidden /> Download
              </Button>
            </div>
          )}
          {others.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-[14px] text-slate">Other search models</summary>
              <ul className="mt-2 flex flex-col gap-2">
                {others.map((m) => (
                  <li key={m.repo_id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-3">
                    <div className="min-w-0">
                      <p className="font-medium text-[15px]">{m.title}</p>
                      <p className="text-[14px] text-slate">{m.why}</p>
                    </div>
                    <Button tone="quiet" disabled={busy} onClick={() => start(m.repo_id)}>
                      Download
                    </Button>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </Panel>
  );
}

function Libraries() {
  const router = useRouter();
  const { data: libs, refresh } = usePoll<KnowledgeLibrary[]>("/api/knowledge/libraries", 5000);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    setError(null);
    try {
      const lib = await api.post<KnowledgeLibrary>("/api/knowledge/libraries", { name, description });
      refresh();
      router.push(`/knowledge/?l=${lib.id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className="grid gap-8">
      {libs && libs.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {libs.map((l) => (
            <li key={l.id}>
              <Link
                href={`/knowledge/?l=${l.id}`}
                className="block h-full rounded-2xl border border-line bg-paper p-5 hover:border-slate/50 transition-colors"
              >
                <BookOpen size={20} className="text-slate" aria-hidden />
                <h2 className="font-medium mt-3 truncate">{l.name}</h2>
                {l.description && <p className="text-[14px] text-slate mt-1 line-clamp-2">{l.description}</p>}
                <p className="text-[13px] text-slate mt-3">
                  {l.documents} document{l.documents === 1 ? "" : "s"}, {l.passages} passages, {bytes(l.size_bytes)}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Panel className="max-w-[760px]">
        <h2 className="font-display text-[1.25rem] leading-snug mb-4">
          {libs?.length ? "New library" : "Create your first library"}
        </h2>
        {error && (
          <div className="mb-4">
            <Notice tone="error">{error}</Notice>
          </div>
        )}
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            create();
          }}
        >
          <Field label="Name">
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="Work documents" />
          </Field>
          <Field label="What's in it (optional)">
            <input
              className={inputClass}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Contracts, policies and meeting notes"
            />
          </Field>
          <div>
            <Button type="submit" disabled={!name.trim()}>
              Create library
            </Button>
          </div>
        </form>
      </Panel>
      <ChatAttachments />
    </div>
  );
}

/** Long documents attached in Chat are kept in hidden libraries. Deleting a chat removes its own; this clears the rest. */
function ChatAttachments() {
  const { data: all, refresh } = usePoll<KnowledgeLibrary[]>("/api/knowledge/libraries?hidden=true", 0);
  const hidden = (all ?? []).filter((l) => l.hidden);
  if (!hidden.length) return null;
  const size = hidden.reduce((a, l) => a + l.size_bytes, 0);
  const files = hidden.reduce((a, l) => a + l.documents, 0);
  const clear = async () => {
    if (!confirm("Remove all long documents attached in chats? Those chats will no longer be able to search them.")) return;
    for (const l of hidden) await api.del(`/api/knowledge/libraries/${l.id}`);
    refresh();
  };
  return (
    <p className="text-[14px] text-slate">
      Long documents attached in chats: {files} file{files === 1 ? "" : "s"}, {bytes(size)}. Deleting a chat removes its
      own.{" "}
      <button type="button" onClick={clear} className="underline underline-offset-2 hover:text-ink">
        Remove all
      </button>
    </p>
  );
}

function LibraryView({ lid, searchModels }: { lid: string; searchModels: KnowledgeStatus["search_models"] }) {
  const router = useRouter();
  const { data: lib, error, refresh } = usePoll<KnowledgeLibrary & { documents_list: KnowledgeDoc[] }>(
    `/api/knowledge/libraries/${lid}`,
    2000,
  );
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const add = async (files: File[]) => {
    if (!files.length) return;
    setProblem(null);
    setUploading(true);
    try {
      await api.uploadFiles(`/api/knowledge/libraries/${lid}/documents`, files);
      refresh();
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setUploading(false);
    }
  };
  const remove = async (d: KnowledgeDoc) => {
    if (!confirm(`Remove ${d.name} from this library?`)) return;
    await api.del(`/api/knowledge/documents/${d.id}`);
    refresh();
  };
  const removeLibrary = async () => {
    if (!lib || !confirm(`Delete the library "${lib.name}" and its ${lib.documents} documents? This can't be undone.`)) return;
    await api.del(`/api/knowledge/libraries/${lid}`);
    router.push("/knowledge/");
  };

  if (error) return <Notice tone="error">{error}</Notice>;
  if (!lib) return null;
  const docs = lib.documents_list;
  const modelGone = !!lib.embed_model && lib.documents > 0 && !searchModels.some((m) => m.id === lib.embed_model);
  return (
    <div className="grid gap-6 max-w-[900px]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href="/knowledge/" className="inline-flex items-center gap-1.5 text-[14px] text-slate hover:text-ink">
            <ArrowLeft size={15} aria-hidden /> All libraries
          </Link>
          <h2 className="font-display text-[1.5rem] leading-tight mt-2">{lib.name}</h2>
          {lib.description && <p className="text-slate mt-1">{lib.description}</p>}
          <p className="text-[13px] text-slate mt-2">
            {lib.documents} document{lib.documents === 1 ? "" : "s"}, {lib.passages} passages. Use it in Chat with the{" "}
            <span className="text-ink">Knowledge</span> button under the message box.
          </p>
          {!modelGone && lib.documents > 0 && <SearchModel lib={lib} searchModels={searchModels} onDone={refresh} />}
        </div>
        <Button tone="quiet" onClick={removeLibrary}>
          <Trash2 size={15} aria-hidden /> Delete library
        </Button>
      </div>

      {modelGone && (
        <Notice>
          <p>
            This library was read with a search model that has been removed, so for now it can only be searched by exact
            words. Read it again with an installed search model to search it by meaning too.
          </p>
          <div className="mt-3">
            <SearchModel lib={lib} searchModels={searchModels} onDone={refresh} open />
          </div>
        </Notice>
      )}

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          add([...e.dataTransfer.files]);
        }}
        className={`rounded-2xl border border-dashed p-6 text-center transition-colors ${dragging ? "border-ink bg-well" : "border-line"}`}
      >
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept={ACCEPT}
          onChange={(e) => {
            add([...(e.target.files ?? [])]);
            e.target.value = "";
          }}
        />
        <Upload size={22} className="mx-auto text-slate" aria-hidden />
        <p className="mt-2">Drop documents here, or</p>
        <div className="mt-3">
          <Button onClick={() => input.current?.click()} disabled={uploading}>
            {uploading ? <Loader2 size={15} className="animate-spin" aria-hidden /> : null} Choose files
          </Button>
        </div>
        <p className="text-[13px] text-slate mt-3">PDFs, text, Markdown, CSV, HTML and code files, up to 100 MB each.</p>
      </div>
      {problem && <Notice tone="error">{problem}</Notice>}

      {docs.length > 0 && (
        <ul className="rounded-2xl border border-line bg-paper divide-y divide-line">
          {docs.map((d) => (
            <li key={d.id} className="flex items-center gap-3 px-4 py-3">
              <FileText size={18} className="text-slate shrink-0" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate">{d.name}</p>
                <DocStatus
                  d={d}
                  onRetry={() => api.post(`/api/knowledge/documents/${d.id}/retry`).then(refresh, (e) => setProblem((e as Error).message))}
                />
              </div>
              <button
                type="button"
                onClick={() => openDocument(d)}
                className="text-[13px] text-slate hover:text-ink underline underline-offset-2"
              >
                Open
              </button>
              <button
                type="button"
                onClick={() => remove(d)}
                aria-label={`Remove ${d.name}`}
                className="size-8 grid place-items-center rounded-lg text-slate hover:text-danger"
              >
                <Trash2 size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {lib.passages > 0 && <TrySearch lid={lid} />}
    </div>
  );
}

const modelLabel = (m: { repo_id: string }) => prettyName(m.repo_id);

/** Which search model a library was read with, and a way to read it again (with that model or another). */
function SearchModel({
  lib,
  searchModels,
  onDone,
  open: startOpen = false,
}: {
  lib: KnowledgeLibrary;
  searchModels: KnowledgeStatus["search_models"];
  onDone: () => void;
  open?: boolean;
}) {
  const current = searchModels.find((m) => m.id === lib.embed_model);
  const [open, setOpen] = useState(startOpen);
  const [choice, setChoice] = useState(current?.id ?? searchModels[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reread = async () => {
    const m = searchModels.find((x) => x.id === choice);
    if (!m) return;
    const same = m.id === lib.embed_model;
    const msg = same
      ? `Read all ${lib.documents} documents again with ${modelLabel(m)}? This picks up improvements in how documents are split.`
      : `Read all ${lib.documents} documents again with ${modelLabel(m)}? Until each one is done, it's found by exact words only.`;
    if (!confirm(msg)) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/knowledge/libraries/${lib.id}/reindex`, { model: m.id });
      setOpen(startOpen);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-2 text-[13px] text-slate">
      {!startOpen && (
        <p>
          Search model: <span className="text-ink">{current ? modelLabel(current) : "not set yet"}</span>.{" "}
          <button type="button" onClick={() => setOpen(!open)} className="underline underline-offset-2 hover:text-ink">
            {open ? "Cancel" : "Change or read again"}
          </button>
        </p>
      )}
      {open && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select
            className={`${inputClass} h-10 py-0 max-w-[280px]`}
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
            aria-label="Search model"
          >
            {searchModels.map((m) => (
              <option key={m.id} value={m.id}>
                {modelLabel(m)}
                {m.id === lib.embed_model ? " (current)" : ""}
              </option>
            ))}
          </select>
          <Button onClick={reread} disabled={busy || !choice}>
            {busy ? <Loader2 size={15} className="animate-spin" aria-hidden /> : null} Read documents again
          </Button>
          <Link href="/discover/?task=embed" className="underline underline-offset-2 hover:text-ink">
            Get other search models
          </Link>
        </div>
      )}
      {error && <p className="text-danger mt-2">{error}</p>}
    </div>
  );
}

/** Fetched rather than linked, so it works when API keys are required (links can't send the interface's header). */
async function openDocument(d: KnowledgeDoc) {
  const r = await fetch(`${API_BASE}/api/knowledge/documents/${d.id}/file`, { headers: { "X-Wanna-UI": "1" } });
  if (!r.ok) return alert(`Couldn't open ${d.name}.`);
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: d.name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function DocStatus({ d, onRetry }: { d: KnowledgeDoc; onRetry: () => void }) {
  if (d.status === "error")
    return (
      <p className="text-[13px] text-danger">
        {d.error}{" "}
        <button type="button" onClick={onRetry} className="underline underline-offset-2 text-ink">
          Try again
        </button>
      </p>
    );
  if (d.status === "queued") return <p className="text-[13px] text-slate">Waiting to be read…</p>;
  if (d.status === "indexing")
    return (
      <div className="max-w-[260px] mt-1">
        <Progress value={d.progress} live />
      </div>
    );
  const parts = [d.pages ? `${d.pages} pages` : null, `${d.chunks} passages`, bytes(d.size_bytes)].filter(Boolean);
  return (
    <p className="text-[13px] text-slate">
      {parts.join(", ")}
      {d.truncated ? ". Very long: only the first part was indexed." : ""}
    </p>
  );
}

/** Check a library finds what you expect before using it in Chat. */
function TrySearch({ lid }: { lid: string }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<KnowledgeResult[] | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    if (!q.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ results: KnowledgeResult[]; warnings?: string[] }>("/api/knowledge/search", {
        query: q,
        libraries: [lid],
        k: 5,
      });
      setResults(r.results);
      setWarnings(r.warnings ?? []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel>
      <h3 className="font-medium mb-1">Try a search</h3>
      <p className="text-[14px] text-slate mb-3">See which passages a question finds. Chat gives the best of these to the model.</p>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          run();
        }}
      >
        <input className={inputClass} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a question" />
        <Button type="submit" disabled={!q.trim() || busy}>
          {busy ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Search size={15} aria-hidden />} Search
        </Button>
      </form>
      {error && (
        <div className="mt-3">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {warnings.length > 0 && <p className="mt-3 text-[13px] text-slate">Searched by exact words only (see above).</p>}
      {results && (
        <ol className="mt-4 grid gap-3">
          {results.length === 0 && <li className="text-[14px] text-slate">Nothing found.</li>}
          {results.map((r, i) => (
            <li key={r.id} className="rounded-xl border border-line p-3.5">
              <p className="text-[13px] text-slate">
                <span className="text-ink font-medium">{i + 1}.</span> {sourceLabel(r)}
                <span className="ml-2">Matched by {r.matched.join(" and ")}</span>
              </p>
              <p className="text-[14px] mt-1.5 whitespace-pre-wrap line-clamp-6">{r.text}</p>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
