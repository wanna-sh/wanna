"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Check, Download, FilePlus2, FolderOpen, Loader2, Sparkles, Trash2 } from "lucide-react";
import {
  api,
  dataUrl,
  type InstalledModel,
  type UserTask,
  type TaskAnswer,
  type TaskExample,
  type TaskReport,
} from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { duration } from "@/lib/format";
import { Button, Field, Notice, PageHeader, Panel, Progress, inputClass } from "@/components/ui";

const BUSY = ["training", "drafting"];
const pct = (x: number) => `${Math.round(x * 1000) / 10}%`;

export default function TasksPage() {
  return (
    <Suspense>
      <Tasks />
    </Suspense>
  );
}

function Tasks() {
  const tid = useSearchParams().get("t");
  return tid ? <TaskView id={tid} /> : <TaskList />;
}

// --- the list, and a new task ------------------------------------------------------------------------------------

function TaskList() {
  const { data, error, refresh } = usePoll<{ tasks: UserTask[]; search_model: boolean }>("/api/tasks", 3000);
  return (
    <div className="max-w-[920px]">
      <PageHeader
        title="Tasks"
        intro="Teach the AI a task of your own from examples: sort things, flag them, score them, pull details out, or answer in a set way. wanna.sh picks how to train it, tests it on examples it didn't learn from, and you can use it here, on whole files, from the API and in Chat."
      />
      {error && <Notice tone="error">{error}</Notice>}
      <NewTask onCreated={refresh} />
      {data && data.tasks.length > 0 && (
        <section className="mt-10">
          <h2 className="font-display text-[1.25rem] leading-snug mb-3">Your tasks</h2>
          <ul className="flex flex-col gap-3">
            {data.tasks.map((t) => (
              <li key={t.id}>
                <Link href={`/tasks/?t=${t.id}`} className="block rounded-2xl border border-line bg-paper p-4 hover:bg-well/40">
                  <div className="font-medium">{t.name}</div>
                  <div className="text-[14px] text-slate">
                    {shape(t)} · {t.answered.toLocaleString()} of {t.examples.toLocaleString()} examples answered ·{" "}
                    {BUSY.includes(t.status.stage) ? (t.status.message ?? "Working") : t.ready ? headline(t.report) : t.status.stage === "error" ? "Training failed" : "Not trained yet"}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="mt-10 text-[15px]">
        <h2 className="font-display text-[1.25rem] leading-snug mb-2">What it can learn</h2>
        <ul className="list-disc pl-5 flex flex-col gap-1.5 text-slate">
          <li>
            <b className="text-ink">From a table</b> (numbers and categories) to a label or a number: fraud or not,
            which team, a price. Trains on the processor in seconds.
          </li>
          <li>
            <b className="text-ink">From text</b> to a label: emails, tickets, reviews sorted your way. Uses your
            search model from Knowledge.
          </li>
          <li>
            <b className="text-ink">From pictures</b> to a label: one folder of pictures per answer. Uses a search
            model that can see pictures.
          </li>
          <li>
            <b className="text-ink">From text to writing</b>: answers in your format, or details pulled out as JSON.
            Trains a chat model on your graphics card.
          </li>
          <li>No answers yet? A chat model can draft them for you to check.</li>
        </ul>
      </section>
    </div>
  );
}

function shape(t: UserTask) {
  const from = t.input_kind === "picture" ? "pictures" : t.input_kind === "text" ? "text" : "a table";
  const to = t.answer_kind === "label" ? "a label" : t.answer_kind === "number" ? "a number" : "writing";
  return `From ${from} to ${to}`;
}

function headline(r: TaskReport | null) {
  if (!r) return "Trained";
  if (r.kind === "label" && r.accuracy !== undefined) {
    if (r.tradeoffs) {
      const at = r.tradeoffs.rows.find((x) => x.threshold === r.tradeoffs!.threshold);
      if (at) return `Catches ${at.caught} of ${r.tradeoffs.total} "${r.tradeoffs.label}", ${at.false_alarms} false alarms`;
    }
    return `Right ${pct(r.accuracy)} of the time`;
  }
  if (r.kind === "number" && r.mean_error !== undefined) return `Off by ${round(r.mean_error)} on average`;
  if (r.kind === "text" && r.pairs) return `Tested on ${r.pairs.length} examples`;
  return "Trained";
}

function round(x: number) {
  return Math.abs(x) >= 100 ? Math.round(x).toLocaleString() : (Math.round(x * 100) / 100).toString();
}

function NewTask({ onCreated }: { onCreated: () => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const pick = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const pictures = files.filter((f) => /\.(png|jpe?g|webp|bmp|gif)$/i.test(f.name)).length;

  const create = async () => {
    setBusy(true);
    setProblem(null);
    const fd = new FormData();
    fd.append("name", name);
    fd.append("description", description);
    // A picture from a chosen folder keeps its folder in its name: the folder is its answer.
    files.forEach((f) => fd.append("files", f, f.webkitRelativePath || f.name));
    try {
      const t = await api.postForm<UserTask>("/api/tasks", fd);
      onCreated();
      router.push(`/tasks/?t=${t.id}`);
    } catch (e) {
      setProblem((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <Panel>
      <h2 className="font-display text-[1.25rem] leading-snug mb-4">New task</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" hint="For you, e.g. Fraud check, Ticket sorter">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="What should it do?" hint="In a sentence. Also tells a chat model what to do when it drafts answers or writes them.">
          <input className={inputClass} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
      </div>
      <div className="mt-4">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const dropped = [...e.dataTransfer.files];
            setFiles((fs) => [...fs, ...dropped]);
          }}
          className={`rounded-2xl border border-dashed p-5 text-center transition-colors ${dragging ? "border-ink bg-well" : "border-line"}`}
        >
          {/* Copy the chosen files before clearing the input: its list is live, and empties with it. */}
          <input ref={pick} type="file" multiple hidden accept=".csv,.tsv,.json,.jsonl,image/*" onChange={(e) => {
            const chosen = [...(e.target.files ?? [])];
            setFiles((fs) => [...fs, ...chosen]);
            e.target.value = "";
          }} />
          <input ref={folder} type="file" multiple hidden {...({ webkitdirectory: "" } as object)} onChange={(e) => {
            const chosen = [...(e.target.files ?? [])].filter((f) => /\.(png|jpe?g|webp|bmp|gif)$/i.test(f.name));
            setFiles((fs) => [...fs, ...chosen]);
            e.target.value = "";
          }} />
          <FilePlus2 size={22} className="mx-auto text-slate" aria-hidden />
          <p className="mt-2">Drop your examples here: a table (CSV, TSV, JSON or JSONL), or pictures</p>
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            <Button tone="quiet" onClick={() => pick.current?.click()}>
              Choose files
            </Button>
            <Button tone="quiet" onClick={() => folder.current?.click()}>
              <FolderOpen size={15} aria-hidden /> Choose a folder of pictures
            </Button>
          </div>
        </div>
        {files.length > 0 && (
          <p className="text-[14px] text-slate mt-2 flex items-center gap-2">
            {pictures ? `${pictures} pictures` : files.map((f) => f.name).join(", ")}
            <button className="underline underline-offset-2" onClick={() => setFiles([])}>
              Clear
            </button>
          </p>
        )}
        <ul className="list-disc pl-5 mt-3 text-[14px] text-slate flex flex-col gap-1">
          <li>A table: one row per example, a column with the answer (it guesses which; you can change it), and the columns that go in.</li>
          <li>Pictures: a folder with one folder inside per answer (damaged/, fine/), or pictures without answers yet.</li>
          <li>No answers yet? Use a table with just what goes in; a chat model can draft the answers for you to check.</li>
        </ul>
      </div>
      {problem && (
        <div className="mt-4">
          <Notice tone="error">{problem}</Notice>
        </div>
      )}
      <div className="mt-5">
        <Button onClick={create} disabled={!files.length || busy}>
          {busy && <Loader2 size={15} className="animate-spin" aria-hidden />} Create
        </Button>
      </div>
    </Panel>
  );
}

// --- one task -----------------------------------------------------------------------------------------------------

function TaskView({ id }: { id: string }) {
  const router = useRouter();
  const { data: t, error, refresh } = usePoll<UserTask>(`/api/tasks/${id}`, 2500);
  const { data: models } = usePoll<InstalledModel[]>("/api/models");
  const [problem, setProblem] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    setProblem(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setProblem((e as Error).message);
    }
  };
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!t) return null;
  const busy = BUSY.includes(t.status.stage);
  const chatModels = (models ?? []).filter((m) => m.task === "chat" && m.engine === "llamacpp");

  return (
    <div className="max-w-[980px]">
      <Link href="/tasks/" className="text-[14px] text-slate underline underline-offset-2">
        All tasks
      </Link>
      <PageHeader title={t.name} intro={t.description || shape(t)} />
      {problem && (
        <div className="mb-4">
          <Notice tone="error">{problem}</Notice>
        </div>
      )}

      <Section n={1} title="Your examples">
        <ExamplesShape t={t} act={act} busy={busy} />
        <ExamplesTable t={t} onChange={refresh} />
      </Section>

      {t.answered < t.examples && (
        <Section n={2} title="Draft the missing answers">
          <Draft t={t} models={chatModels} act={act} busy={busy} />
        </Section>
      )}

      <Section n={t.answered < t.examples ? 3 : 2} title="Train and test it">
        <Train t={t} models={chatModels.filter((m) => !m.meta?.trained)} act={act} busy={busy} />
        {t.report && !busy && <Report t={t} act={act} />}
      </Section>

      {t.ready && (
        <Section n={t.answered < t.examples ? 4 : 3} title="Use it">
          <Use t={t} act={act} />
        </Section>
      )}

      <div className="mt-10">
        <button
          className="text-danger text-[14px] underline underline-offset-2 inline-flex items-center gap-1"
          onClick={() =>
            confirm(`Delete ${t.name}, with its examples and what it learned?`) &&
            act(async () => {
              await api.del(`/api/tasks/${t.id}`);
              router.push("/tasks/");
            })
          }
        >
          <Trash2 size={14} aria-hidden /> Delete this task
        </button>
      </div>
    </div>
  );
}

function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <Panel className="mt-6">
      <h2 className="font-display text-[1.2rem] leading-snug mb-4">
        <span className="text-slate mr-2">{n}.</span>
        {title}
      </h2>
      {children}
    </Panel>
  );
}

type Act = (fn: () => Promise<unknown>) => Promise<void>;

/** What wanna.sh read from the examples, and the choices that change it. */
function ExamplesShape({ t, act, busy }: { t: UserTask; act: Act; busy: boolean }) {
  const [labels, setLabels] = useState("");
  const table = t.columns.length > 0;
  return (
    <div className="text-[15px]">
      <p>
        {t.examples.toLocaleString()} examples, {t.answered.toLocaleString()} with answers. {shape(t)}
        {t.answer_kind === "label" && t.labels.length > 0 && (
          <>
            :{" "}
            {t.labels.map((l) => (
              <span key={l} className="inline-block rounded-full bg-well px-2.5 py-0.5 text-[13px] mr-1.5 mb-1">
                {l} {t.label_counts[l] ? <span className="text-slate">{t.label_counts[l]}</span> : null}
              </span>
            ))}
          </>
        )}
      </p>
      {table && !t.chats && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="The answer is in" hint="The column it learns to fill in.">
            <select
              className={`${inputClass} h-10 py-0`}
              disabled={busy}
              value={t.answer_column ?? ""}
              onChange={(e) =>
                act(() =>
                  e.target.value
                    ? api.patch(`/api/tasks/${t.id}`, { answer_column: e.target.value })
                    : api.patch(`/api/tasks/${t.id}`, { no_answers: "label" }),
                )
              }
            >
              {t.columns.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
              <option value="">No answers yet</option>
            </select>
          </Field>
          {!t.answer_column && (
            <Field label="Its answers will be" hint="Labels from a list, or written text.">
              <select
                className={`${inputClass} h-10 py-0`}
                value={t.answer_kind}
                disabled={busy}
                onChange={(e) => act(() => api.patch(`/api/tasks/${t.id}`, { no_answers: e.target.value }))}
              >
                <option value="label">A label</option>
                <option value="text">Writing</option>
              </select>
            </Field>
          )}
        </div>
      )}
      {table && !t.chats && (
        <div className="mt-4">
          <p className="text-[13px] font-medium mb-1.5">What goes in</p>
          <div className="flex flex-wrap gap-1.5">
            {t.columns
              .filter((c) => c.name !== t.answer_column)
              .map((c) => {
                const on = t.input_columns.includes(c.name);
                return (
                  <button
                    key={c.name}
                    type="button"
                    disabled={busy}
                    aria-pressed={on}
                    title={`${c.kind}: ${c.sample.join(", ")}`}
                    onClick={() =>
                      act(() =>
                        api.patch(`/api/tasks/${t.id}`, {
                          input_columns: on ? t.input_columns.filter((x) => x !== c.name) : [...t.input_columns, c.name],
                        }),
                      )
                    }
                    className={`rounded-full border px-3 h-8 text-[13px] ${on ? "border-accent bg-well/60" : "border-line text-slate line-through"}`}
                  >
                    {c.name} <span className="text-slate">({c.kind})</span>
                  </button>
                );
              })}
          </div>
          {t.input_kind === "table" && t.input_columns.some((c) => t.columns.find((x) => x.name === c)?.kind === "text") && (
            <p className="text-[13px] text-slate mt-2">Free-text columns aren&apos;t used when learning from a table. To learn from text, choose just that one column.</p>
          )}
        </div>
      )}
      {t.answer_kind === "label" && (
        <div className="mt-4 max-w-[560px]">
          <Field label="Answers it can give" hint="Comma-separated. Use plain words: chat models draft better with 'cars' than 'rec.autos'. Answers in your examples are added by themselves.">
            <div className="flex gap-2">
              <input className={inputClass} placeholder={t.labels.join(", ") || "yes, no"} value={labels} onChange={(e) => setLabels(e.target.value)} />
              <Button
                tone="quiet"
                disabled={!labels.trim()}
                onClick={() =>
                  act(async () => {
                    await api.patch(`/api/tasks/${t.id}`, { labels: [...t.labels, ...labels.split(",").map((x) => x.trim())] });
                    setLabels("");
                  })
                }
              >
                Add
              </Button>
            </div>
          </Field>
        </div>
      )}
    </div>
  );
}

function inputText(t: UserTask, i: TaskExample["input"]) {
  if (typeof i === "string") return i;
  if (Array.isArray((i as { messages?: unknown }).messages)) {
    const msgs = (i as { messages: { content: string }[] }).messages;
    return String(msgs[msgs.length - 1]?.content ?? "");
  }
  const cols = t.input_columns.length ? t.input_columns : Object.keys(i);
  return cols.length === 1 ? String(i[cols[0]] ?? "") : cols.map((c) => `${c}: ${i[c] ?? ""}`).join(" · ");
}

function ExamplesTable({ t, onChange }: { t: UserTask; onChange: () => void }) {
  const [show, setShow] = useState<"all" | "unanswered" | "drafted">("all");
  const [offset, setOffset] = useState(0);
  const { data, refresh } = usePoll<{ total: number; rows: TaskExample[] }>(
    `/api/tasks/${t.id}/examples?show=${show}&offset=${offset}&limit=25&v=${t.answered}-${t.drafted}`,
  );
  const save = async (answers: Record<string, string | null>) => {
    await api.put(`/api/tasks/${t.id}/answers`, { answers });
    refresh();
    onChange();
  };
  const filters: [typeof show, string][] = [
    ["all", "All"],
    ["unanswered", `No answer (${t.examples - t.answered})`],
    ["drafted", `AI drafts to check (${t.drafted})`],
  ];
  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        {filters.map(([v, label]) => (
          <button
            key={v}
            onClick={() => {
              setShow(v);
              setOffset(0);
            }}
            className={`rounded-full px-3 h-8 text-[13px] border ${show === v ? "border-accent bg-well/60" : "border-line text-slate"}`}
          >
            {label}
          </button>
        ))}
        {show === "drafted" && data && data.rows.length > 0 && (
          <Button tone="quiet" onClick={() => save(Object.fromEntries(data.rows.map((r) => [String(r.n), r.answer === null ? null : String(r.answer)])))}>
            <Check size={14} aria-hidden /> These {data.rows.length} look right
          </Button>
        )}
      </div>
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-[14px]">
          <thead className="text-left text-slate bg-well/50">
            <tr>
              <th className="px-3 py-2 font-medium w-12">#</th>
              <th className="px-3 py-2 font-medium">Goes in</th>
              <th className="px-3 py-2 font-medium w-[34%]">Answer</th>
            </tr>
          </thead>
          <tbody>
            {data?.rows.map((r) => (
              <tr key={r.n} className="border-t border-line align-top">
                <td className="px-3 py-2 text-slate">{r.n + 1}</td>
                <td className="px-3 py-2">
                  {t.input_kind === "picture" && typeof r.input === "object" && "picture" in r.input ? (
                    <Thumb path={`/api/tasks/${t.id}/${String(r.input.picture)}`} />
                  ) : (
                    <span className="line-clamp-3 whitespace-pre-wrap">{inputText(t, r.input)}</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <AnswerCell t={t} row={r} onSave={(v) => save({ [String(r.n)]: v })} />
                </td>
              </tr>
            ))}
            {data && data.rows.length === 0 && (
              <tr>
                <td colSpan={3} className="px-3 py-4 text-slate">
                  Nothing here.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {data && data.total > 25 && (
        <div className="mt-2 flex items-center gap-3 text-[14px] text-slate">
          <button disabled={offset === 0} className="underline disabled:no-underline disabled:opacity-50" onClick={() => setOffset(Math.max(0, offset - 25))}>
            Previous
          </button>
          <span>
            {offset + 1} to {Math.min(offset + 25, data.total)} of {data.total.toLocaleString()}
          </span>
          <button disabled={offset + 25 >= data.total} className="underline disabled:no-underline disabled:opacity-50" onClick={() => setOffset(offset + 25)}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function AnswerCell({ t, row, onSave }: { t: UserTask; row: TaskExample; onSave: (v: string | null) => void }) {
  const [text, setText] = useState(row.answer === null ? "" : String(row.answer));
  const draft = row.drafted ? (
    <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-well px-2 py-0.5 text-[12px] text-slate">
      <Sparkles size={11} aria-hidden /> AI draft
    </span>
  ) : null;
  if (t.answer_kind === "label")
    return (
      <span className="inline-flex items-center flex-wrap gap-1">
        <select
          aria-label={`Answer for example ${row.n + 1}`}
          className="rounded-lg bg-paper border border-line px-2 h-8 text-[14px] focus:outline-none focus:border-slate"
          value={row.answer === null ? "" : String(row.answer)}
          onChange={(e) => onSave(e.target.value || null)}
        >
          <option value="">No answer</option>
          {t.labels.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
        {draft}
        {row.drafted && (
          <button aria-label="Looks right" title="Looks right" onClick={() => onSave(String(row.answer))} className="ml-1 text-slate hover:text-ink">
            <Check size={15} />
          </button>
        )}
      </span>
    );
  return (
    <span className="block">
      <textarea
        aria-label={`Answer for example ${row.n + 1}`}
        rows={3}
        className={`${inputClass} py-1.5`}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => text !== (row.answer === null ? "" : String(row.answer)) && onSave(text || null)}
      />
      {draft}
      {row.drafted && (
        <button className="ml-2 text-[13px] underline underline-offset-2" onClick={() => onSave(text)}>
          Looks right
        </button>
      )}
    </span>
  );
}

function Thumb({ path }: { path: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    dataUrl(path).then((u) => alive && setSrc(u), () => {});
    return () => {
      alive = false;
    };
  }, [path]);
  // eslint-disable-next-line @next/next/no-img-element
  return src ? <img src={src} alt="" className="size-16 object-cover rounded-lg" /> : <div className="size-16 rounded-lg bg-well" />;
}

function Draft({ t, models, act, busy }: { t: UserTask; models: InstalledModel[]; act: Act; busy: boolean }) {
  const usable = t.input_kind === "picture" ? models.filter((m) => m.meta?.mmproj) : models;
  const [model, setModel] = useState("");
  const [careful, setCareful] = useState(true);
  const chosen = model || usable[0]?.id || "";
  const missing = t.examples - t.answered;
  if (t.status.stage === "drafting")
    return <Progress value={t.status.steps ? (t.status.step ?? 0) / t.status.steps : 0.02} label={t.status.message ?? "Drafting"} live />;
  return (
    <div className="text-[15px]">
      <p>
        {missing.toLocaleString()} examples have no answer. A chat model can draft them{t.labels.length && t.answer_kind === "label" ? `, choosing from ${t.labels.join(", ")}` : ""}; then check them in the table above, under <b>AI drafts to check</b>.
      </p>
      {t.answer_kind === "label" && t.labels.length < 2 && <p className="text-danger text-[14px] mt-2">First list at least two answers it can give, above.</p>}
      {usable.length === 0 ? (
        <p className="text-[14px] text-slate mt-3">
          {t.input_kind === "picture" ? "Drafting answers for pictures needs a chat model that can see them. " : "Drafting needs a chat model. "}
          <Link href="/discover/?task=chat" className="underline">
            Get one
          </Link>
          .
        </p>
      ) : (
        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div className="min-w-[260px]">
            <Field label="Chat model">
              <select className={`${inputClass} h-10 py-0`} value={chosen} onChange={(e) => setModel(e.target.value)}>
                {usable.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.meta?.title ?? m.id}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <label className="flex items-center gap-2 text-[14px] h-10">
            <input type="checkbox" checked={careful} onChange={(e) => setCareful(e.target.checked)} />
            Think before each answer (slower, more often right)
          </label>
          <Button
            disabled={busy || !chosen || (t.answer_kind === "label" && t.labels.length < 2)}
            onClick={() => act(() => api.post(`/api/tasks/${t.id}/draft`, { chat_model: chosen, careful, limit: 200 }))}
          >
            <Sparkles size={15} aria-hidden /> Draft {Math.min(200, missing)} answers
          </Button>
        </div>
      )}
    </div>
  );
}

function Train({ t, models, act, busy }: { t: UserTask; models: InstalledModel[]; act: Act; busy: boolean }) {
  const [model, setModel] = useState("");
  const chosen = model || models[0]?.id || "";
  const s = t.status;
  if (s.stage === "training") {
    const value = s.steps ? (s.step ?? 0) / s.steps : s.total_bytes ? (s.done_bytes ?? 0) / s.total_bytes : 0.02;
    const label = s.steps && s.step ? `Training: step ${s.step} of ${s.steps}${s.seconds_left ? `, about ${duration(s.seconds_left)} left` : ""}` : (s.message ?? "Training");
    return <Progress value={value} label={label} live />;
  }
  const method =
    t.answer_kind === "text"
      ? "It trains a chat model on your examples (on your graphics card), holding back a tenth to test it on."
      : t.input_kind === "table"
        ? "It learns with gradient-boosted trees, on the processor: usually seconds."
        : t.input_kind === "text"
          ? "It reads each example with your search model from Knowledge, then learns from what it read: usually under a minute."
          : "It looks at each picture with your search model (one that can see pictures), then learns from what it saw.";
  return (
    <div className="text-[15px]">
      <p className="text-slate">{method} Every example is then tested by a version that didn&apos;t learn from it, so the results below are what to expect on new ones.</p>
      {t.drafted > 0 && <p className="text-[14px] mt-2">{t.drafted} answers are AI drafts you haven&apos;t checked; they&apos;re used as they are.</p>}
      {s.stage === "error" && (
        <div className="mt-3">
          <Notice tone="error">{s.message}</Notice>
        </div>
      )}
      {s.stage === "interrupted" && <p className="text-[14px] text-slate mt-3">{s.message}</p>}
      <div className="mt-4 flex flex-wrap items-end gap-4">
        {t.answer_kind === "text" && (
          <div className="min-w-[260px]">
            <Field label="Chat model to train">
              <select className={`${inputClass} h-10 py-0`} value={chosen} onChange={(e) => setModel(e.target.value)}>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.meta?.title ?? m.id}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        )}
        <Button
          disabled={busy || t.answered < 2 || (t.answer_kind === "text" && !chosen)}
          onClick={() => act(() => api.post(`/api/tasks/${t.id}/train`, t.answer_kind === "text" ? { chat_model: chosen } : {}))}
        >
          {t.ready ? "Train again" : "Train"}
        </Button>
      </div>
    </div>
  );
}

// --- results ------------------------------------------------------------------------------------------------------

function Report({ t, act }: { t: UserTask; act: Act }) {
  const r = t.report!;
  return (
    <div className="mt-6 border-t border-line pt-5 text-[15px]">
      <h3 className="font-medium mb-2">How it did</h3>
      <p className="text-slate text-[14px] mb-3">
        On examples it hadn&apos;t seen: {r.how}
        {r.seconds ? `. Took ${duration(r.seconds)}` : ""}.{r.unchecked ? ` ${r.unchecked} of its answers were unchecked AI drafts.` : ""}
      </p>
      {r.kind === "label" && <LabelReport t={t} r={r} act={act} />}
      {r.kind === "number" && r.mean_error !== undefined && (
        <p>
          Off by <b>{round(r.mean_error)}</b> on average (half the time by less than {round(r.median_error ?? 0)}), and within 10% {pct(r.within_10_percent ?? 0)} of the
          time. Always guessing the average ({round(Number(r.baseline?.answer))}) would be off by {round(r.baseline?.mean_error ?? 0)}.
        </p>
      )}
      {r.kind === "text" && <TextReport r={r} />}
      {r.uses && r.uses.length > 0 && (
        <div className="mt-5">
          <h4 className="font-medium text-[14px] mb-2">What it looks at most</h4>
          <ul className="flex flex-col gap-1.5 max-w-[520px]">
            {r.uses.map((u) => (
              <li key={u.column} className="grid grid-cols-[160px_1fr_48px] items-center gap-2 text-[14px]">
                <span className="truncate">{u.column}</span>
                <span className="h-2 rounded-full bg-well overflow-hidden">
                  <span className="block h-full bg-accent" style={{ width: `${Math.round(u.share * 100)}%` }} />
                </span>
                <span className="text-slate text-right">{Math.round(u.share * 100)}%</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {r.mistakes && r.mistakes.length > 0 && (
        <details className="mt-5">
          <summary className="cursor-pointer font-medium text-[14px]">Examples it got wrong ({r.mistakes.length}{r.mistakes.length === 25 ? "+" : ""})</summary>
          <ul className="mt-2 flex flex-col gap-2 text-[14px]">
            {r.mistakes.map((m, i) => (
              <li key={i} className="rounded-xl border border-line p-3">
                <div className="line-clamp-3">{m.input}</div>
                <div className="text-slate mt-1">
                  Answer: <b className="text-ink">{String(m.answer)}</b> · It said: <b className="text-ink">{typeof m.said === "number" ? round(m.said) : m.said}</b>
                  {m.confidence ? ` (${pct(m.confidence)} sure)` : ""}
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function LabelReport({ t, r, act }: { t: UserTask; r: TaskReport; act: Act }) {
  const tr = r.tradeoffs;
  const chosen = t.threshold ?? tr?.threshold;
  return (
    <>
      <p>
        Right <b>{pct(r.accuracy ?? 0)}</b> of the time. Always answering &ldquo;{String(r.baseline?.answer)}&rdquo; would be right {pct(r.baseline?.accuracy ?? 0)}
        {(r.accuracy ?? 0) <= (r.baseline?.accuracy ?? 0) + 0.01 ? ", so look at what it catches below rather than this." : "."}
      </p>
      <ul className="mt-3 flex flex-col gap-1 text-[14px]">
        {r.labels?.map((l) => (
          <li key={l.label}>
            <b>{l.label}</b>: found {l.found} of {l.examples}
            {l.said ? `; when it said ${l.label}, it was right ${l.found} of ${l.said} times` : "; it never said this"}.
          </li>
        ))}
      </ul>
      {tr && (
        <div className="mt-5">
          <h4 className="font-medium text-[14px] mb-1">How sure before it says &ldquo;{tr.label}&rdquo;</h4>
          <p className="text-[14px] text-slate mb-2">
            Lower catches more of them but flags more wrongly; higher flags fewer, more surely. Chosen for the best balance; pick another to suit you.
          </p>
          <div className="overflow-x-auto rounded-xl border border-line max-w-[640px]">
            <table className="w-full text-[14px]">
              <thead className="text-left text-slate bg-well/50">
                <tr>
                  <th className="px-3 py-2 font-medium">When its chance is at least</th>
                  <th className="px-3 py-2 font-medium">Catches</th>
                  <th className="px-3 py-2 font-medium">False alarms</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {tr.rows.map((x) => (
                  <tr key={x.threshold} className={`border-t border-line ${x.threshold === chosen ? "bg-well/60" : ""}`}>
                    <td className="px-3 py-1.5">{Math.round(x.threshold * 100)}%</td>
                    <td className="px-3 py-1.5">
                      {x.caught} of {tr.total}
                    </td>
                    <td className="px-3 py-1.5">{x.false_alarms}</td>
                    <td className="px-3 py-1.5 text-right">
                      {x.threshold === chosen ? (
                        <span className="text-slate">In use</span>
                      ) : (
                        <button className="underline underline-offset-2" onClick={() => act(() => api.patch(`/api/tasks/${t.id}`, { threshold: x.threshold }))}>
                          Use this
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

function TextReport({ r }: { r: TaskReport }) {
  const short = (r.pairs ?? []).every((p) => p.answer.split(/\s+/).length <= 5);
  return (
    <>
      {r.fields ? (
        <p>
          It got <b>{r.fields.right} of {r.fields.total}</b> fields right, and wrote valid JSON {r.fields.valid_json} of {r.tested} times.
        </p>
      ) : short ? (
        <p>
          Exactly right <b>{pct(r.exact ?? 0)}</b> of the time.
        </p>
      ) : (
        <p>Written answers rarely match word for word, so compare them yourself:</p>
      )}
      <ul className="mt-3 flex flex-col gap-3">
        {r.pairs?.map((p, i) => (
          <li key={i} className="rounded-xl border border-line p-3 text-[14px]">
            <p className="font-medium line-clamp-2">{p.input}</p>
            <div className="grid gap-3 sm:grid-cols-2 mt-2">
              <div>
                <p className="text-[12px] uppercase tracking-wide text-slate mb-1">Expected</p>
                <p className="whitespace-pre-wrap text-slate">{p.answer}</p>
              </div>
              <div>
                <p className="text-[12px] uppercase tracking-wide text-slate mb-1">It wrote</p>
                <p className="whitespace-pre-wrap">{p.said}</p>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

// --- using it -----------------------------------------------------------------------------------------------------

function Use({ t, act }: { t: UserTask; act: Act }) {
  return (
    <div className="flex flex-col gap-6 text-[15px]">
      <TryIt t={t} />
      {t.input_kind !== "picture" && <RunFile t={t} />}
      <div>
        <h3 className="font-medium mb-1">In Chat and Code</h3>
        {t.input_kind === "picture" ? (
          <p className="text-[14px] text-slate">Picture tasks can&apos;t be used as a tool yet.</p>
        ) : (
          <label className="flex items-start gap-2 text-[14px]">
            <input type="checkbox" className="mt-1" checked={t.in_chat !== false} onChange={(e) => act(() => api.patch(`/api/tasks/${t.id}`, { in_chat: e.target.checked }))} />
            <span>
              Let the AI use it, as the tool <span className="font-mono">{t.tool}</span>, when <b>Tools</b> is on in Chat (and in Code).
            </span>
          </label>
        )}
      </div>
      <div>
        <h3 className="font-medium mb-1">From apps</h3>
        <pre className="rounded-xl bg-well p-3 text-[13px] overflow-x-auto">
          {t.input_kind === "picture"
            ? `curl http://localhost:7860/api/tasks/${t.id}/run-picture -F file=@picture.jpg`
            : `curl http://localhost:7860/api/tasks/${t.id}/run \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify({ input: sampleInput(t) })}'`}
        </pre>
      </div>
    </div>
  );
}

function sampleInput(t: UserTask): Record<string, string> | string {
  if (t.input_kind === "text" && t.input_columns.length <= 1) return "...";
  return Object.fromEntries(t.input_columns.map((c) => [c, t.columns.find((x) => x.name === c)?.sample[0] ?? ""]));
}

function TryIt({ t }: { t: UserTask }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [answer, setAnswer] = useState<TaskAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const table = t.input_kind === "table" && !t.chats;
  const go = async () => {
    setBusy(true);
    setProblem(null);
    setAnswer(null);
    try {
      if (t.input_kind === "picture") {
        setAnswer(await api.upload<TaskAnswer>(`/api/tasks/${t.id}/run-picture`, file!, file!.name));
      } else {
        const input = table ? values : t.input_columns.length === 1 ? { [t.input_columns[0]]: text } : text;
        setAnswer(await api.post<TaskAnswer>(`/api/tasks/${t.id}/run`, { input: t.input_kind === "text" && !t.input_columns.length ? text : input }));
      }
    } catch (e) {
      setProblem((e as Error).message);
    }
    setBusy(false);
  };
  return (
    <div>
      <h3 className="font-medium mb-2">Try it</h3>
      {t.input_kind === "picture" ? (
        <input type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      ) : table ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {t.input_columns.map((c) => {
            const col = t.columns.find((x) => x.name === c);
            return (
              <Field key={c} label={c}>
                {col?.values?.length ? (
                  <select className={`${inputClass} h-10 py-0`} value={values[c] ?? ""} onChange={(e) => setValues({ ...values, [c]: e.target.value })}>
                    <option value="">Unknown</option>
                    {col.values.map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                ) : (
                  <input className={inputClass} placeholder={col?.sample[0]} value={values[c] ?? ""} onChange={(e) => setValues({ ...values, [c]: e.target.value })} />
                )}
              </Field>
            );
          })}
        </div>
      ) : (
        <textarea className={`${inputClass} min-h-[90px]`} value={text} onChange={(e) => setText(e.target.value)} placeholder="Something to answer" />
      )}
      <div className="mt-3 flex items-center gap-3">
        <Button onClick={go} disabled={busy || (t.input_kind === "picture" ? !file : table ? false : !text.trim())}>
          {busy && <Loader2 size={15} className="animate-spin" aria-hidden />} Answer it
        </Button>
        {answer && (
          <span>
            <b>{typeof answer.answer === "number" ? round(answer.answer) : String(answer.answer).length < 80 ? answer.answer : ""}</b>
            {answer.confidence !== undefined && <span className="text-slate"> ({pct(answer.confidence)} sure)</span>}
          </span>
        )}
      </div>
      {answer && typeof answer.answer === "string" && answer.answer.length >= 80 && <p className="mt-3 whitespace-pre-wrap rounded-xl border border-line p-3">{answer.answer}</p>}
      {answer?.scores && Object.keys(answer.scores).length > 2 && (
        <ul className="mt-3 flex flex-col gap-1 max-w-[420px] text-[14px]">
          {Object.entries(answer.scores)
            .sort((a, b) => b[1] - a[1])
            .map(([k, v]) => (
              <li key={k} className="grid grid-cols-[140px_1fr_48px] items-center gap-2">
                <span className="truncate">{k}</span>
                <span className="h-2 rounded-full bg-well overflow-hidden">
                  <span className="block h-full bg-accent" style={{ width: `${Math.round(v * 100)}%` }} />
                </span>
                <span className="text-slate text-right">{Math.round(v * 100)}%</span>
              </li>
            ))}
        </ul>
      )}
      {problem && (
        <div className="mt-3">
          <Notice tone="error">{problem}</Notice>
        </div>
      )}
    </div>
  );
}

function RunFile({ t }: { t: UserTask }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const run = async (f: File) => {
    setBusy(true);
    setProblem(null);
    const fd = new FormData();
    fd.append("file", f, f.name);
    try {
      const { blob, name } = await api.postFormFile(`/api/tasks/${t.id}/run-file`, fd);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setProblem((e as Error).message);
    }
    setBusy(false);
  };
  return (
    <div>
      <h3 className="font-medium mb-1">Answer a whole file</h3>
      <p className="text-[14px] text-slate mb-2">
        A table with the same columns{t.answer_kind === "text" ? " (each row takes a few seconds)" : ""}. You get it back as a CSV with an answer column added.
      </p>
      <input ref={input} type="file" hidden accept=".csv,.tsv,.json,.jsonl" onChange={(e) => e.target.files?.[0] && run(e.target.files[0])} />
      <Button tone="quiet" disabled={busy} onClick={() => input.current?.click()}>
        {busy ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Download size={15} aria-hidden />} Choose a file
      </Button>
      {problem && (
        <div className="mt-3">
          <Notice tone="error">{problem}</Notice>
        </div>
      )}
    </div>
  );
}
