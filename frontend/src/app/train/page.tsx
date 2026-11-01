"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Download, ImagePlus, Loader2, Palette, PawPrint, X } from "lucide-react";
import { api, dataUrl, type TrainModel, type TrainOverview, type TrainRun } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { duration } from "@/lib/format";
import { Button, Field, Notice, PageHeader, Panel, Progress, inputClass } from "@/components/ui";
import { MlAddon } from "@/components/addons";

type Preset = "subject" | "style";
const ACTIVE = ["queued", "preparing", "training", "saving", "samples"];

// The same defaults as the server (training.defaults), shown before starting.
function defaultSteps(preset: Preset, pictures: number) {
  return preset === "style" ? Math.min(2000, Math.max(600, 100 * pictures)) : Math.min(1500, Math.max(400, 80 * pictures));
}

/** A made-up trigger word from the name: its letters plus "zx", so it isn't a real word the model already knows. */
function suggestTrigger(name: string) {
  const letters = name.toLowerCase().replace(/[^a-z]/g, "").slice(0, 6);
  return letters.length >= 2 ? `${letters}zx` : "zwx";
}

export default function TrainPage() {
  const { data, error, refresh } = usePoll<TrainOverview>("/api/training", 3000);
  const active = data?.runs.some((r) => ACTIVE.includes(r.status.stage));

  return (
    <div className="max-w-[920px]">
      <PageHeader
        title="Train"
        intro="Teach a picture model your own subject (a person, a pet, a product) or a style, from a few pictures. It trains on this computer, and your pictures never leave it. Then use it on the Pictures page."
      />
      {error && <Notice tone="error">{error}</Notice>}
      {data && !data.ready.ok && <NotReady overview={data} onDone={refresh} />}
      {data?.ready.ok && data.models.length === 0 && (
        <Notice>
          Training needs a Stable Diffusion 1.5 or SDXL picture model.{" "}
          <Link href="/discover/?task=image" className="underline">
            Get one
          </Link>{" "}
          (for example Stable Diffusion 1.5, about 2 GB), then come back.
        </Notice>
      )}
      {data?.ready.ok && data.models.length > 0 && <NewRun models={data.models} busy={!!active} onStarted={refresh} />}
      {data && data.runs.length > 0 && (
        <section className="mt-10">
          <h2 className="font-display text-[1.25rem] leading-snug mb-3">Your trained styles</h2>
          <ul className="flex flex-col gap-4">
            {data.runs.map((r) => (
              <RunCard key={r.id} r={r} onChange={refresh} />
            ))}
          </ul>
        </section>
      )}
      <HowItWorks />
    </div>
  );
}

/** What's missing before this computer can train, and the button that fixes it when it can be fixed here. */
function NotReady({ overview, onDone }: { overview: TrainOverview; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (overview.ready.missing === "ml") return <MlAddon />;
  if (overview.ready.missing === "peft")
    return (
      <Panel className="mb-6">
        <p className="text-[15px]">{overview.ready.reason}</p>
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
                  const o = await api.get<TrainOverview>("/api/training");
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
  return <Notice>{overview.ready.reason}</Notice>;
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
          className={`rounded-2xl border border-dashed p-5 text-center transition-colors ${dragging ? "border-ink bg-well" : "border-line"}`}
        >
          <input
            ref={input}
            type="file"
            multiple
            hidden
            accept="image/png,image/jpeg,image/webp,image/bmp,image/gif"
            onChange={(e) => {
              add([...(e.target.files ?? [])]);
              e.target.value = "";
            }}
          />
          <ImagePlus size={22} className="mx-auto text-slate" aria-hidden />
          <p className="mt-2">Drop pictures here, or</p>
          <div className="mt-3">
            <Button tone="quiet" onClick={() => input.current?.click()}>
              Choose pictures
            </Button>
          </div>
        </div>
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
        <button type="button" className="text-[14px] text-slate underline underline-offset-2 mt-3" onClick={() => setAdvanced(!advanced)}>
          {advanced ? "Hide" : "Show"} advanced settings
        </button>
        {advanced && (
          <div className="mt-3 max-w-[280px]">
            <Field
              label="Training steps"
              hint={`Default ${defaultSteps(preset, files.length || 10)} for ${files.length || 10} pictures. More learns more closely, but can copy the pictures too exactly.`}
            >
              <input className={inputClass} inputMode="numeric" value={steps} placeholder="Automatic" onChange={(e) => setSteps(e.target.value.replace(/\D/g, ""))} />
            </Field>
          </div>
        )}
      </Step>

      {problem && (
        <div className="mt-4">
          <Notice tone="error">{problem}</Notice>
        </div>
      )}
      <div className="mt-6 flex flex-wrap items-center gap-4">
        <Button onClick={start} disabled={!ready || starting}>
          {starting ? <Loader2 size={15} className="animate-spin" aria-hidden /> : null} Start training
        </Button>
        <span className="text-[14px] text-slate">
          {busy
            ? "Another training run is going; wait for it to finish."
            : minutes && chosen?.card
              ? `About ${duration(minutes)} on your ${chosen.card.replace(/^NVIDIA (GeForce )?/, "")}. Other models on that card are stopped first.`
              : ""}
        </span>
      </div>
    </Panel>
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

function RunCard({ r, onChange }: { r: TrainRun; onChange: () => void }) {
  const s = r.status;
  const running = ACTIVE.includes(s.stage);
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
            {r.preset === "subject" ? "Subject" : "Style"}: <span className="font-mono text-ink">{label}</span> · {r.model_title ?? r.model} ·{" "}
            {r.pictures} pictures · {r.steps} steps
          </div>
        </div>
        {r.ready && (
          <Link href={`/image/?style=${r.id}`} className="inline-flex items-center rounded-full px-4 h-9 text-[14px] font-medium bg-accent text-accent-ink hover:opacity-85">
            Use it in Pictures
          </Link>
        )}
      </div>

      {running && (
        <div className="mt-4">
          <Progress
            value={s.stage === "training" && s.steps ? (s.step ?? 0) / s.steps : s.stage === "samples" || s.stage === "saving" ? 1 : 0.02}
            label={
              s.stage === "training"
                ? `Training: step ${s.step} of ${s.steps}${s.seconds_left ? `, about ${duration(s.seconds_left)} left` : ""}`
                : (s.message ?? "Starting")
            }
            live
          />
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

      {r.samples.length > 0 && (
        <div className="mt-4">
          <p className="text-[14px] text-slate mb-2">
            Made with it{s.seconds ? ` after ${duration(s.seconds)} of training` : ""}:
          </p>
          <div className="grid grid-cols-3 gap-2 max-w-[600px]">
            {r.samples.map((u) => (
              <Sample key={u} path={u} />
            ))}
          </div>
          <p className="text-[14px] text-slate mt-3">
            Try: <span className="font-mono text-ink">{r.prompt}</span>. If every picture looks too much like it, lower
            its strength on the Pictures page.
          </p>
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
            onClick={() => confirm(`Delete ${r.name}? Its pictures and trained style are deleted too.`) && act(() => api.del(`/api/training/${r.id}`))}
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
          needs a 12 GB card. Training uses one graphics card and stops other models on it first.
        </li>
        <li>
          On the Pictures page, choose it under <b>Style</b>. If pictures copy it too closely (every dog
          becomes your dog), lower its strength.
        </li>
      </ul>
    </section>
  );
}
