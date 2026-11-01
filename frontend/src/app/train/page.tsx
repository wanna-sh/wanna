"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Download, FilePlus2, ImagePlus, Loader2, MessagesSquare, Palette, PawPrint, PenLine, X } from "lucide-react";
import {
  api,
  dataUrl,
  type TrainChatModel,
  type TrainChatOverview,
  type TrainModel,
  type TrainOverview,
  type TrainRun,
} from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes, duration } from "@/lib/format";
import { Button, Field, Notice, PageHeader, Panel, Progress, Segmented, inputClass } from "@/components/ui";
import { MlAddon } from "@/components/addons";

type Preset = "subject" | "style";
type ChatPreset = "voice" | "chats";
type Kind = "picture" | "chat";
const ACTIVE = ["queued", "downloading", "preparing", "training", "saving", "samples"];

// The same defaults as the server (training.defaults), shown before starting.
function defaultSteps(preset: Preset, pictures: number) {
  return preset === "style" ? Math.min(2000, Math.max(600, 100 * pictures)) : Math.min(1500, Math.max(400, 80 * pictures));
}

// The same as training.chat_defaults: more passes over few examples, four examples a step.
function chatSteps(examples: number) {
  const passes = examples * (examples < 50 ? 5 : examples < 500 ? 3 : 2);
  return Math.max(15, Math.min(2000, Math.ceil(passes / 4)));
}

/** A made-up trigger word from the name: its letters plus "zx", so it isn't a real word the model already knows. */
function suggestTrigger(name: string) {
  const letters = name.toLowerCase().replace(/[^a-z]/g, "").slice(0, 6);
  return letters.length >= 2 ? `${letters}zx` : "zwx";
}

export default function TrainPage() {
  const { data, error, refresh } = usePoll<TrainOverview>("/api/training", 3000);
  const [kind, setKind] = useState<Kind>("picture");
  const active = data?.runs.some((r) => ACTIVE.includes(r.status.stage));
  const runs = data?.runs.filter((r) => (r.type ?? "picture") === kind) ?? [];

  return (
    <div className="max-w-[920px]">
      <PageHeader
        title="Train"
        intro="Teach a model something of your own, on this computer: a picture model your subject or style, from a few pictures, or a chat model your writing voice or how to answer, from your writing or example chats. What you train it on never leaves this computer."
      />
      <div className="mb-6">
        <Segmented
          label="What to train"
          value={kind}
          onChange={setKind}
          options={[
            { value: "picture", label: "Pictures" },
            { value: "chat", label: "Chat" },
          ]}
        />
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {kind === "picture" ? (
        <>
          {data && !data.ready.ok && <NotReady ready={data.ready} path="/api/training" onDone={refresh} />}
          {data?.ready.ok && data.models.length === 0 && (
            <Notice>
              Training needs a Stable Diffusion 1.5 or SDXL picture model.{" "}
              <Link href="/discover/?task=image" className="underline">
                Get one
              </Link>{" "}
              (for example Stable Diffusion 1.5, about 2.6 GB), then come back.
            </Notice>
          )}
          {data?.ready.ok && data.models.length > 0 && <NewRun models={data.models} busy={!!active} onStarted={refresh} />}
        </>
      ) : (
        <ChatTab busy={!!active} onStarted={refresh} />
      )}
      {runs.length > 0 && (
        <section className="mt-10">
          <h2 className="font-display text-[1.25rem] leading-snug mb-3">
            {kind === "picture" ? "Your trained styles" : "Your trained chat models"}
          </h2>
          <ul className="flex flex-col gap-4">
            {runs.map((r) => (
              <RunCard key={r.id} r={r} onChange={refresh} />
            ))}
          </ul>
        </section>
      )}
      {kind === "picture" ? <HowItWorks /> : <HowChatWorks />}
    </div>
  );
}

/** What's missing before this computer can train, and the button that fixes it when it can be fixed here. */
function NotReady({ ready, path, onDone }: { ready: TrainOverview["ready"]; path: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (ready.missing === "ml") return <MlAddon />;
  if (ready.missing === "peft")
    return (
      <Panel className="mb-6">
        <p className="text-[15px]">{ready.reason}</p>
        {problem && (
          <div className="mt-3">
            <Notice tone="error">{problem}</Notice>
          </div>
        )}
        <div className="mt-4">
          <Button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setProblem(null);
              try {
                await api.post("/api/addons/ml/install");
                // The install runs in the background; check back until training is ready.
                const wait = setInterval(async () => {
                  const o = await api.get<{ ready: TrainOverview["ready"] }>(path);
                  if (o.ready.ok || o.ready.missing !== "peft") {
                    clearInterval(wait);
                    setBusy(false);
                    onDone();
                  }
                }, 3000);
              } catch (e) {
                setProblem((e as Error).message);
                setBusy(false);
              }
            }}
          >
            {busy ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Download size={15} aria-hidden />}
            {busy ? "Installing…" : "Install"}
          </Button>
        </div>
      </Panel>
    );
  return <Notice>{ready.reason}</Notice>;
}

function NewRun({ models, busy, onStarted }: { models: TrainModel[]; busy: boolean; onStarted: () => void }) {
  const [preset, setPreset] = useState<Preset>("subject");
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [trigger, setTrigger] = useState("");
  const [triggerTouched, setTriggerTouched] = useState(false);
  const [what, setWhat] = useState("");
  const usable = models.filter((m) => m.card);
  const [model, setModel] = useState(usable.find((m) => m.kind === "sd")?.id ?? usable[0]?.id ?? "");
  const [steps, setSteps] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const add = (more: File[]) => {
    const pics = more.filter((f) => /\.(png|jpe?g|webp|bmp|gif)$/i.test(f.name)).slice(0, 50 - files.length);
    setFiles((fs) => [...fs, ...pics]);
    setPreviews((ps) => [...ps, ...pics.map((f) => URL.createObjectURL(f))]);
  };
  const remove = (i: number) => {
    URL.revokeObjectURL(previews[i]);
    setFiles((fs) => fs.filter((_, j) => j !== i));
    setPreviews((ps) => ps.filter((_, j) => j !== i));
  };
  const chosen = models.find((m) => m.id === model);
  const plannedSteps = Number(steps) || defaultSteps(preset, files.length || 10);
  const minutes = chosen?.seconds_per_step
    ? plannedSteps * chosen.seconds_per_step + (chosen.kind === "sdxl" ? 150 : 60) // plus loading and samples
    : null;
  const word = triggerTouched ? trigger : suggestTrigger(name);
  const ready = files.length >= 3 && word && model && (preset === "style" || what.trim()) && !busy;

  const start = async () => {
    setStarting(true);
    setProblem(null);
    const fd = new FormData();
    fd.append("model", model);
    fd.append("preset", preset);
    fd.append("name", name || word);
    fd.append("trigger", word);
    fd.append("what", preset === "subject" ? what : "");
    if (steps) fd.append("steps", steps);
    files.forEach((f) => fd.append("files", f, f.name));
    try {
      await api.postForm("/api/training", fd);
      previews.forEach((u) => URL.revokeObjectURL(u));
      setFiles([]);
      setPreviews([]);
      setName("");
      setWhat("");
      setTriggerTouched(false);
      onStarted();
    } catch (e) {
      setProblem((e as Error).message);
    }
    setStarting(false);
  };

  return (
    <Panel>
      <h2 className="font-display text-[1.25rem] leading-snug mb-4">Train something new</h2>

      <Step n={1} title="What do you want to teach it?">
        <div className="grid gap-3 sm:grid-cols-2">
          <Choice
            on={preset === "subject"}
            onClick={() => setPreset("subject")}
            icon={<PawPrint size={18} aria-hidden />}
            title="A subject"
            text="A person, a pet or a thing. Then ask for it in any scene: your dog on the moon, your mug on a beach."
          />
          <Choice
            on={preset === "style"}
            onClick={() => setPreset("style")}
            icon={<Palette size={18} aria-hidden />}
            title="A style"
            text="A look: your illustrations, a kind of painting, a photo style. Then draw anything that way."
          />
        </div>
      </Step>

      <Step n={2} title="Add pictures">
        <DropZone
          accept="image/png,image/jpeg,image/webp,image/bmp,image/gif"
          icon={<ImagePlus size={22} className="mx-auto text-slate" aria-hidden />}
          text="Drop pictures here, or"
          button="Choose pictures"
          onFiles={add}
          inputRef={input}
          dragging={dragging}
          setDragging={setDragging}
        />
        {files.length > 0 && (
          <>
            <ul className="mt-3 grid grid-cols-4 sm:grid-cols-6 lg:grid-cols-8 gap-2">
              {previews.map((u, i) => (
                <li key={u} className="relative">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={u} alt={files[i].name} className="aspect-square w-full object-cover rounded-lg border border-line" />
                  <button
                    type="button"
                    onClick={() => remove(i)}
                    aria-label={`Remove ${files[i].name}`}
                    className="absolute -top-1.5 -right-1.5 size-6 grid place-items-center rounded-full bg-ink text-fog"
                  >
                    <X size={12} />
                  </button>
                </li>
              ))}
            </ul>
            <p className={`text-[14px] mt-2 ${files.length < 3 ? "text-danger" : "text-slate"}`}>
              {files.length} picture{files.length === 1 ? "" : "s"}.{" "}
              {files.length < 3 ? "Add at least 3." : files.length < 8 ? "That works; 10 to 20 works best." : ""}
            </p>
          </>
        )}
        <ul className="list-disc pl-5 mt-3 text-[14px] text-slate flex flex-col gap-1">
          {preset === "subject" ? (
            <>
              <li>Only the subject you&apos;re teaching, clearly visible: one person, one pet, one thing.</li>
              <li>Vary everything else: backgrounds, angles, lighting, clothes. What stays the same is what it learns.</li>
              <li>Pictures are cropped to a square around the middle, so keep the subject centred.</li>
            </>
          ) : (
            <>
              <li>Different subjects, all in the same style: what they share is what it learns.</li>
              <li>Pictures are cropped to a square around the middle.</li>
            </>
          )}
        </ul>
      </Step>

      <Step n={3} title="Name it">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Name" hint={preset === "subject" ? "For you, e.g. Rex" : "For you, e.g. My sketches"}>
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field
            label="Trigger word"
            hint="A made-up word you'll put in prompts to call it up. Not a real word, so the model learns it fresh."
          >
            <input
              className={`${inputClass} font-mono`}
              value={word}
              onChange={(e) => {
                setTriggerTouched(true);
                setTrigger(e.target.value.replace(/[^A-Za-z0-9]/g, "").slice(0, 24));
              }}
            />
          </Field>
          {preset === "subject" && (
            <Field label="What is it?" hint="One or two words: dog, woman, mug, car.">
              <input className={inputClass} value={what} onChange={(e) => setWhat(e.target.value)} />
            </Field>
          )}
        </div>
        <p className="text-[14px] text-slate mt-3">
          Later, ask for it like this:{" "}
          <span className="text-ink font-mono">
            {preset === "subject"
              ? `a photo of ${word || "zwx"} ${what || "dog"} on a beach`
              : `a lighthouse at sunset, in the style of ${word || "zwx"}`}
          </span>
        </p>
      </Step>

      <Step n={4} title="Choose the picture model">
        <Field
          label="Picture model"
          hint="The style only works with the model it was trained on. Stable Diffusion 1.5 trains faster; SDXL makes bigger, more detailed pictures."
        >
          <select className={`${inputClass} h-10 py-0`} value={model} onChange={(e) => setModel(e.target.value)}>
            {models.map((m) => (
              <option key={m.id} value={m.id} disabled={!m.card}>
                {m.title} ({m.kind === "sdxl" ? "SDXL" : "SD 1.5"})
                {m.card ? "" : `: needs a ${m.kind === "sdxl" ? 12 : 6} GB graphics card`}
              </option>
            ))}
          </select>
        </Field>
        <Advanced
          open={advanced}
          setOpen={setAdvanced}
          steps={steps}
          setSteps={setSteps}
          hint={`Default ${defaultSteps(preset, files.length || 10)} for ${files.length || 10} pictures. More learns more closely, but can copy the pictures too exactly.`}
        />
      </Step>

      <StartRow
        problem={problem}
        onStart={start}
        disabled={!ready || starting}
        starting={starting}
        note={
          busy
            ? "Another training run is going; wait for it to finish."
            : minutes && chosen?.card
              ? `About ${duration(minutes)} on your ${chosen.card.replace(/^NVIDIA (GeForce )?/, "")}. If that card is short of memory, its models are stopped first.`
              : ""
        }
      />
    </Panel>
  );
}

// --- chat ------------------------------------------------------------------------------------------------------------

function ChatTab({ busy, onStarted }: { busy: boolean; onStarted: () => void }) {
  const { data, error, refresh } = usePoll<TrainChatOverview>("/api/training/chat-models");
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!data)
    return (
      <p className="text-slate flex items-center gap-2">
        <Loader2 size={15} className="animate-spin" aria-hidden /> Looking up your chat models…
      </p>
    );
  if (!data.ready.ok) return <NotReady ready={data.ready} path="/api/training/chat-models" onDone={refresh} />;
  if (data.models.length === 0)
    return (
      <Notice>
        Training needs a chat model.{" "}
        <Link href="/discover/?task=chat" className="underline">
          Get one
        </Link>
        , then come back.
      </Notice>
    );
  return <ChatNewRun models={data.models} busy={busy} onStarted={onStarted} />;
}

type Pair = { prompt: string; reply: string };

/** Roughly how many examples a file holds, counted the way the server reads it (training.read_chats). */
async function countChats(f: File): Promise<number> {
  const text = await f.text();
  const name = f.name.toLowerCase();
  try {
    if (name.endsWith(".jsonl")) return text.split("\n").filter((l) => l.trim()).length;
    if (name.endsWith(".json")) {
      const v = JSON.parse(text);
      return Array.isArray(v) ? v.length : 1;
    }
  } catch {
    return 0;
  }
  const rows = text.split("\n").filter((l) => l.includes(","));
  return Math.max(0, rows.length - (/^\s*"?(prompt|question|input|instruction|user|q)"?\s*,/i.test(rows[0] ?? "") ? 1 : 0));
}

const words = (t: string) => (t.trim() ? t.trim().split(/\s+/).length : 0);

function ChatNewRun({ models, busy, onStarted }: { models: TrainChatModel[]; busy: boolean; onStarted: () => void }) {
  const [preset, setPreset] = useState<ChatPreset>("voice");
  const [files, setFiles] = useState<{ file: File; count: number | null }[]>([]);
  const [pasted, setPasted] = useState("");
  const [pairs, setPairs] = useState<Pair[]>([
    { prompt: "", reply: "" },
    { prompt: "", reply: "" },
  ]);
  const [name, setName] = useState("");
  const usable = models.filter((m) => m.plan);
  const [model, setModel] = useState(usable[0]?.id ?? "");
  const [steps, setSteps] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const accept = preset === "voice" ? /\.(txt|md|markdown|pdf)$/i : /\.(jsonl|json|csv)$/i;
  const add = async (more: File[]) => {
    const picked = more.filter((f) => accept.test(f.name)).slice(0, 50 - files.length);
    const counted = await Promise.all(
      picked.map(async (f) => ({
        file: f,
        // Words in writing (PDFs are read when training starts); examples in chat files.
        count: preset === "voice" ? (/\.pdf$/i.test(f.name) ? null : words(await f.text())) : await countChats(f),
      })),
    );
    setFiles((fs) => [...fs, ...counted]);
  };
  const switchPreset = (p: ChatPreset) => {
    setPreset(p);
    setFiles([]);
  };
  const typed = pairs.filter((p) => p.prompt.trim() && p.reply.trim());
  const fromFiles = files.reduce((n, f) => n + (f.count ?? 0), 0);
  const total = preset === "voice" ? fromFiles + words(pasted) : fromFiles + typed.length;
  const hasPdf = files.some((f) => f.count === null);
  const examples = preset === "voice" ? Math.max(1, Math.floor(total / 180)) : total;
  const chosen = models.find((m) => m.id === model);
  const plannedSteps = Number(steps) || chatSteps(examples);
  const seconds = chosen?.seconds_per_example ? plannedSteps * 4 * chosen.seconds_per_example + 120 : null; // + loading and samples
  const enough = preset === "voice" ? total >= 300 || hasPdf : total >= 10;
  const ready = enough && model && chosen?.plan && !busy;

  const start = async () => {
    setStarting(true);
    setProblem(null);
    const fd = new FormData();
    fd.append("model", model);
    fd.append("preset", preset);
    fd.append("name", name);
    if (preset === "voice") fd.append("text", pasted);
    else fd.append("examples", JSON.stringify(typed));
    if (steps) fd.append("steps", steps);
    files.forEach((f) => fd.append("files", f.file, f.file.name));
    try {
      await api.postForm("/api/training/chat", fd);
      setFiles([]);
      setPasted("");
      setPairs([
        { prompt: "", reply: "" },
        { prompt: "", reply: "" },
      ]);
      setName("");
      onStarted();
    } catch (e) {
      setProblem((e as Error).message);
    }
    setStarting(false);
  };

  return (
    <Panel>
      <h2 className="font-display text-[1.25rem] leading-snug mb-4">Train a chat model</h2>

      <Step n={1} title="What do you want to teach it?">
        <div className="grid gap-3 sm:grid-cols-2">
          <Choice
            on={preset === "voice"}
            onClick={() => switchPreset("voice")}
            icon={<PenLine size={18} aria-hidden />}
            title="Your writing voice"
            text="From things you've written: emails, posts, stories. Then it answers and writes the way you do."
          />
          <Choice
            on={preset === "chats"}
            onClick={() => switchPreset("chats")}
            icon={<MessagesSquare size={18} aria-hidden />}
            title="How to answer"
            text="From example chats: when asked this, answer like this. For a tone, a format or a role, such as your shop's helper."
          />
        </div>
      </Step>

      <Step n={2} title={preset === "voice" ? "Add your writing" : "Add example chats"}>
        <DropZone
          accept={preset === "voice" ? ".txt,.md,.markdown,.pdf" : ".jsonl,.json,.csv"}
          icon={<FilePlus2 size={22} className="mx-auto text-slate" aria-hidden />}
          text={preset === "voice" ? "Drop text, Markdown or PDF files here, or" : "Drop a .jsonl, .json or .csv file here, or"}
          button="Choose files"
          onFiles={add}
          inputRef={input}
          dragging={dragging}
          setDragging={setDragging}
        />
        {files.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-2">
            {files.map((f, i) => (
              <li key={`${f.file.name}-${i}`} className="inline-flex items-center gap-2 rounded-full border border-line px-3 h-8 text-[13px]">
                {f.file.name}
                <span className="text-slate">
                  {f.count === null ? "" : preset === "voice" ? `${f.count.toLocaleString()} words` : `${f.count} chats`}
                </span>
                <button type="button" aria-label={`Remove ${f.file.name}`} onClick={() => setFiles((fs) => fs.filter((_, j) => j !== i))}>
                  <X size={12} />
                </button>
              </li>
            ))}
          </ul>
        )}
        {preset === "voice" ? (
          <div className="mt-4">
            <Field label="Or paste your writing" hint="Separate pieces with a blank line.">
              <textarea className={`${inputClass} min-h-[140px]`} value={pasted} onChange={(e) => setPasted(e.target.value)} />
            </Field>
          </div>
        ) : (
          <div className="mt-4 flex flex-col gap-3">
            <p className="text-[13px] font-medium">Or type some</p>
            {pairs.map((p, i) => (
              <div key={i} className="grid gap-2 sm:grid-cols-2">
                <textarea
                  aria-label={`Question ${i + 1}`}
                  placeholder="When someone asks…"
                  className={`${inputClass} min-h-[64px]`}
                  value={p.prompt}
                  onChange={(e) => setPairs((ps) => ps.map((q, j) => (j === i ? { ...q, prompt: e.target.value } : q)))}
                />
                <textarea
                  aria-label={`Answer ${i + 1}`}
                  placeholder="…answer like this"
                  className={`${inputClass} min-h-[64px]`}
                  value={p.reply}
                  onChange={(e) => setPairs((ps) => ps.map((q, j) => (j === i ? { ...q, reply: e.target.value } : q)))}
                />
              </div>
            ))}
            <div>
              <Button tone="quiet" onClick={() => setPairs((ps) => [...ps, { prompt: "", reply: "" }])}>
                Add another
              </Button>
            </div>
          </div>
        )}
        <p className={`text-[14px] mt-3 ${enough ? "text-slate" : "text-danger"}`}>
          {preset === "voice"
            ? `${total.toLocaleString()} words${hasPdf ? " plus your PDFs" : ""}. ${total < 300 && !hasPdf ? "Add at least 300." : total < 2000 ? "That works; 2,000 or more works best." : ""}`
            : `${total} example chat${total === 1 ? "" : "s"}. ${total < 10 ? "Add at least 10." : total < 50 ? "That works; 50 or more works best." : ""}`}
        </p>
        <ul className="list-disc pl-5 mt-3 text-[14px] text-slate flex flex-col gap-1">
          {preset === "voice" ? (
            <>
              <li>Only your own writing, in the voice you want: what it has in common is what it learns.</li>
              <li>Several pieces on different subjects work better than one long piece on one subject.</li>
            </>
          ) : (
            <>
              <li>Answer every example the way you want it to answer, in the same tone and format.</li>
              <li>
                Files: a <span className="font-mono">.jsonl</span> with OpenAI-style{" "}
                <span className="font-mono">{'{"messages": [...]}'}</span> lines, or with{" "}
                <span className="font-mono">prompt</span> and <span className="font-mono">reply</span> fields; or a{" "}
                <span className="font-mono">.csv</span> with a question column and an answer column.
              </li>
              <li>It learns how to answer, not new facts: for facts from your documents, use Knowledge.</li>
            </>
          )}
        </ul>
      </Step>

      <Step n={3} title="Name it">
        <div className="max-w-[360px]">
          <Field label="Name" hint={preset === "voice" ? "For you, e.g. My voice" : "For you, e.g. Shop helper"}>
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        </div>
        <p className="text-[14px] text-slate mt-3">
          It becomes a chat model of its own, called{" "}
          <span className="text-ink">
            {name || (preset === "voice" ? "My voice" : "My assistant")} ({chosen?.title ?? "the model"})
          </span>
          , in Chat, Code and the API.
        </p>
      </Step>

      <Step n={4} title="Choose the chat model">
        <Field
          label="Chat model"
          hint="Training starts from this model. Bigger models write better but take longer to train."
        >
          <select className={`${inputClass} h-10 py-0`} value={model} onChange={(e) => setModel(e.target.value)}>
            {models.map((m) => (
              <option key={m.id} value={m.id} disabled={!m.plan}>
                {m.title}
                {m.plan ? "" : ": can't be trained here"}
              </option>
            ))}
          </select>
        </Field>
        {chosen && <ModelPlan m={chosen} />}
        <Advanced
          open={advanced}
          setOpen={setAdvanced}
          steps={steps}
          setSteps={setSteps}
          hint={`Default ${chatSteps(examples)} for ${preset === "voice" ? `${total.toLocaleString()} words` : `${examples} examples`}. More learns more closely, but too many make it repeat your examples instead of answering.`}
        />
      </Step>

      <StartRow
        problem={problem}
        onStart={start}
        disabled={!ready || starting}
        starting={starting}
        note={
          busy
            ? "Another training run is going; wait for it to finish."
            : seconds && chosen?.plan
              ? `About ${duration(seconds)} on your ${chosen.plan.card}${chosen.downloaded ? "" : `, plus downloading the original model once (${bytes(chosen.original_bytes)})`}. If that card is short of memory, its models are stopped first.`
              : ""
        }
      />
    </Panel>
  );
}

/** How the chosen chat model would train here, or why it can't. */
function ModelPlan({ m }: { m: TrainChatModel }) {
  if (!m.plan) return <p className="text-[14px] text-danger mt-2">{m.why_not}</p>;
  return (
    <p className="text-[14px] text-slate mt-2">
      Trains from its original, <span className="font-mono text-ink">{m.original}</span>
      {m.downloaded ? " (already downloaded)" : ` (${bytes(m.original_bytes)}, downloaded the first time)`},{" "}
      {m.plan.mode === "4bit" ? "compressed to 4 bits to fit" : "at full precision"} on your {m.plan.card}.
    </p>
  );
}

// --- shared pieces ---------------------------------------------------------------------------------------------------

function DropZone({
  accept,
  icon,
  text,
  button,
  onFiles,
  inputRef,
  dragging,
  setDragging,
}: {
  accept: string;
  icon: ReactNode;
  text: string;
  button: string;
  onFiles: (f: File[]) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
  dragging: boolean;
  setDragging: (d: boolean) => void;
}) {
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        onFiles([...e.dataTransfer.files]);
      }}
      className={`rounded-2xl border border-dashed p-5 text-center transition-colors ${dragging ? "border-ink bg-well" : "border-line"}`}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        accept={accept}
        onChange={(e) => {
          onFiles([...(e.target.files ?? [])]);
          e.target.value = "";
        }}
      />
      {icon}
      <p className="mt-2">{text}</p>
      <div className="mt-3">
        <Button tone="quiet" onClick={() => inputRef.current?.click()}>
          {button}
        </Button>
      </div>
    </div>
  );
}

function Advanced({
  open,
  setOpen,
  steps,
  setSteps,
  hint,
}: {
  open: boolean;
  setOpen: (o: boolean) => void;
  steps: string;
  setSteps: (s: string) => void;
  hint: string;
}) {
  return (
    <>
      <button type="button" className="text-[14px] text-slate underline underline-offset-2 mt-3" onClick={() => setOpen(!open)}>
        {open ? "Hide" : "Show"} advanced settings
      </button>
      {open && (
        <div className="mt-3 max-w-[280px]">
          <Field label="Training steps" hint={hint}>
            <input className={inputClass} inputMode="numeric" value={steps} placeholder="Automatic" onChange={(e) => setSteps(e.target.value.replace(/\D/g, ""))} />
          </Field>
        </div>
      )}
    </>
  );
}

function StartRow({
  problem,
  onStart,
  disabled,
  starting,
  note,
}: {
  problem: string | null;
  onStart: () => void;
  disabled: boolean;
  starting: boolean;
  note: string;
}) {
  return (
    <>
      {problem && (
        <div className="mt-4">
          <Notice tone="error">{problem}</Notice>
        </div>
      )}
      <div className="mt-6 flex flex-wrap items-center gap-4">
        <Button onClick={onStart} disabled={disabled}>
          {starting ? <Loader2 size={15} className="animate-spin" aria-hidden /> : null} Start training
        </Button>
        <span className="text-[14px] text-slate">{note}</span>
      </div>
    </>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="mt-5 first-of-type:mt-0">
      <h3 className="font-medium mb-2.5">
        <span className="text-slate mr-1.5">{n}.</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

function Choice({ on, onClick, icon, title, text }: { on: boolean; onClick: () => void; icon: ReactNode; title: string; text: string }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`text-left rounded-xl border p-4 transition-colors ${on ? "border-accent bg-well/60" : "border-line hover:bg-well/40"}`}
    >
      <span className="flex items-center gap-2 font-medium">
        {icon} {title}
      </span>
      <span className="block text-[14px] text-slate mt-1">{text}</span>
    </button>
  );
}

function stageLabel(s: TrainRun["status"]) {
  if (s.stage === "training")
    return `Training: step ${s.step} of ${s.steps}${s.seconds_left ? `, about ${duration(s.seconds_left)} left` : ""}`;
  if (s.stage === "downloading" && s.total_bytes)
    return `Downloading the original model (once): ${bytes(s.done_bytes ?? 0)} of ${bytes(s.total_bytes)}`;
  return s.message ?? "Starting";
}

function stageProgress(s: TrainRun["status"]) {
  if (s.stage === "training" && s.steps) return (s.step ?? 0) / s.steps;
  if (s.stage === "downloading" && s.total_bytes) return Math.min(1, (s.done_bytes ?? 0) / s.total_bytes);
  return s.stage === "samples" || s.stage === "saving" ? 1 : 0.02;
}

function RunCard({ r, onChange }: { r: TrainRun; onChange: () => void }) {
  const s = r.status;
  const running = ACTIVE.includes(s.stage);
  const chat = r.type === "chat";
  const [problem, setProblem] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    setProblem(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setProblem((e as Error).message);
    }
  };
  const label = r.preset === "subject" ? `${r.trigger} ${r.what}`.trim() : `the style of ${r.trigger}`;
  return (
    <li className="rounded-2xl border border-line bg-paper p-5">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-1">
        <div className="min-w-0 flex-1">
          <div className="font-medium">{r.name}</div>
          <div className="text-[14px] text-slate">
            {chat ? (
              <>
                {r.preset === "voice" ? "Writing voice" : "Example chats"} · {r.model_title ?? r.model} ·{" "}
                {r.preset === "voice" ? `about ${r.examples} pieces` : `${r.examples} examples`} · {r.steps} steps
                {r.mode === "4bit" ? " · in 4 bits" : ""}
              </>
            ) : (
              <>
                {r.preset === "subject" ? "Subject" : "Style"}: <span className="font-mono text-ink">{label}</span> ·{" "}
                {r.model_title ?? r.model} · {r.pictures} pictures · {r.steps} steps
              </>
            )}
          </div>
        </div>
        {r.ready &&
          (chat ? (
            <Link
              href="/chat/"
              onClick={() => {
                try {
                  localStorage.setItem("wanna.model.chat", r.chat_model ?? "");
                } catch {}
              }}
              className="inline-flex items-center rounded-full px-4 h-9 text-[14px] font-medium bg-accent text-accent-ink hover:opacity-85"
            >
              Use it in Chat
            </Link>
          ) : (
            <Link href={`/image/?style=${r.id}`} className="inline-flex items-center rounded-full px-4 h-9 text-[14px] font-medium bg-accent text-accent-ink hover:opacity-85">
              Use it in Pictures
            </Link>
          ))}
      </div>

      {running && (
        <div className="mt-4">
          <Progress value={stageProgress(s)} label={stageLabel(s)} live />
          <button className="text-[14px] text-slate underline underline-offset-2 mt-2" onClick={() => act(() => api.post(`/api/training/${r.id}/stop`))}>
            Stop
          </button>
        </div>
      )}
      {s.stage === "error" && (
        <div className="mt-3">
          <Notice tone="error">{s.message}</Notice>
        </div>
      )}
      {(s.stage === "stopped" || s.stage === "interrupted") && <p className="text-[14px] text-slate mt-3">{s.message}</p>}

      {!chat && (r.samples?.length ?? 0) > 0 && (
        <div className="mt-4">
          <p className="text-[14px] text-slate mb-2">
            Made with it{s.seconds ? ` after ${duration(s.seconds)} of training` : ""}:
          </p>
          <div className="grid grid-cols-3 gap-2 max-w-[600px]">
            {r.samples!.map((u) => (
              <Sample key={u} path={u} />
            ))}
          </div>
          <p className="text-[14px] text-slate mt-3">
            Try: <span className="font-mono text-ink">{r.prompt}</span>. If every picture looks too much like it, lower
            its strength on the Pictures page.
          </p>
        </div>
      )}
      {chat && (r.replies?.length ?? 0) > 0 && (
        <div className="mt-4">
          <p className="text-[14px] text-slate mb-2">
            {s.seconds ? `Done in ${duration(s.seconds)}. ` : ""}Its replies, next to the model&apos;s before training:
          </p>
          <div className="flex flex-col gap-3">
            {r.replies!.map((x) => (
              <div key={x.prompt} className="rounded-xl border border-line p-3">
                <p className="text-[14px] font-medium">{x.prompt}</p>
                <div className="grid gap-3 sm:grid-cols-2 mt-2 text-[14px]">
                  <div>
                    <p className="text-[12px] uppercase tracking-wide text-slate mb-1">Trained</p>
                    <div className="prose-chat">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{x.after}</ReactMarkdown>
                    </div>
                  </div>
                  <div>
                    <p className="text-[12px] uppercase tracking-wide text-slate mb-1">Before</p>
                    <div className="prose-chat text-slate">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{x.before}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
          {s.strength && s.strength < 1 && (
            <p className="text-[14px] text-slate mt-3">
              At full strength its replies started to repeat, so it was turned down to {Math.round(s.strength * 100)}%.
              Training a new one with more, more varied examples helps.
            </p>
          )}
        </div>
      )}

      {problem && (
        <div className="mt-3">
          <Notice tone="error">{problem}</Notice>
        </div>
      )}
      {!running && (
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-[14px]">
          {!r.ready && (
            <button className="underline underline-offset-2" onClick={() => act(() => api.post(`/api/training/${r.id}/restart`))}>
              Train again
            </button>
          )}
          <button
            className="text-danger underline underline-offset-2 ml-auto"
            onClick={() =>
              confirm(
                chat
                  ? `Delete ${r.name}? The trained chat model and its examples are deleted too.`
                  : `Delete ${r.name}? Its pictures and trained style are deleted too.`,
              ) && act(() => api.del(`/api/training/${r.id}`))
            }
          >
            Delete
          </button>
        </div>
      )}
    </li>
  );
}

/** A sample picture, fetched with the app's own header (so it works with API keys on). */
function Sample({ path }: { path: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    dataUrl(path).then((u) => alive && setSrc(u), () => {});
    return () => {
      alive = false;
    };
  }, [path]);
  // eslint-disable-next-line @next/next/no-img-element
  return src ? <img src={src} alt="" className="aspect-square w-full object-cover rounded-lg" /> : <div className="aspect-square rounded-lg bg-well" />;
}

function HowItWorks() {
  return (
    <section className="mt-10 text-[15px]">
      <h2 className="font-display text-[1.25rem] leading-snug mb-2">How it works</h2>
      <ul className="list-disc pl-5 flex flex-col gap-1.5 text-slate">
        <li>
          It trains a <b>LoRA</b>: a small add-on (around 12 MB for Stable Diffusion 1.5) that teaches the picture model
          your subject or style. The model itself doesn&apos;t change.
        </li>
        <li>
          Every picture is labelled with your trigger word, so the model links the word to what your pictures have in
          common. Put the word in a prompt to call it up.
        </li>
        <li>
          Stable Diffusion 1.5 takes a few minutes on a recent graphics card; SDXL takes around half an hour and
          needs a 12 GB card. Training uses one graphics card, and stops models on it first if it needs the room.
        </li>
        <li>
          On the Pictures page, choose it under <b>Style</b>. If pictures copy it too closely (every dog
          becomes your dog), lower its strength.
        </li>
      </ul>
    </section>
  );
}

function HowChatWorks() {
  return (
    <section className="mt-10 text-[15px]">
      <h2 className="font-display text-[1.25rem] leading-snug mb-2">How it works</h2>
      <ul className="list-disc pl-5 flex flex-col gap-1.5 text-slate">
        <li>
          It trains a <b>LoRA</b>: a small add-on that changes how the chat model writes. The model itself doesn&apos;t
          change, and the result runs on top of the copy you already have.
        </li>
        <li>
          Training needs the model&apos;s original version, which wanna.sh downloads once (about 2 GB per billion
          parameters). Models too big for your graphics card are compressed to 4 bits while training, and can use
          several cards.
        </li>
        <li>
          It learns a voice, a tone or a format, not facts. For answers from your own documents, use Knowledge.
        </li>
        <li>
          When it&apos;s done, it&apos;s a chat model of its own in Chat, Code and the API, named after what you
          trained.
        </li>
      </ul>
    </section>
  );
}
