"use client";

import { useState } from "react";
import { ImagePlus } from "lucide-react";
import { api, fileUrl, type Generation } from "@/lib/api";
import { useJob, useModels, usePoll } from "@/lib/hooks";
import { ago } from "@/lib/format";
import { NoModelYet, useTaskModel } from "@/components/models";
import { AttachChip, AttachedPicture, type Upload } from "@/components/generate";
import {
  FeedItem,
  ModelMenu,
  OptionChip,
  PendingItem,
  PromptBar,
  SidePanel,
  StudioEmpty,
  StudioPage,
  modelName,
} from "@/components/studio";
import { Field, Notice, PageHeader, inputClass } from "@/components/ui";

type Shape = "square" | "portrait" | "landscape";
type Quality = "fast" | "balanced" | "best";

const EXAMPLES = [
  "A watercolor painting of a lighthouse on a cliff at sunrise",
  "A cosy reading nook with a cat, warm afternoon light, photo",
  "A tiny astronaut exploring a giant mushroom forest, storybook style",
  "A bowl of ramen on a wooden table, steam rising, food photography",
];

function dims(base: number, shape: Shape) {
  const r = (n: number) => Math.round(n / 64) * 64;
  if (shape === "portrait") return { width: r(base * 0.8), height: r(base * 1.2) };
  if (shape === "landscape") return { width: r(base * 1.2), height: r(base * 0.8) };
  return { width: base, height: base };
}

export default function ImagePage() {
  const { models, loaded, refresh } = useModels("image");
  const [model, setModel] = useTaskModel("image", models);
  const current = models.find((m) => m.id === model);
  const [prompt, setPrompt] = useState("");
  const [shape, setShape] = useState<Shape>("square");
  const [quality, setQuality] = useState<Quality>("balanced");
  const [count, setCount] = useState("1");
  const [start, setStart] = useState<Upload | null>(null);
  const [strength, setStrength] = useState(0.6);
  const [negative, setNegative] = useState("");
  const [seed, setSeed] = useState("");
  const [steps, setSteps] = useState("");
  const [guidance, setGuidance] = useState("");
  const [sampler, setSampler] = useState("");
  const [panel, setPanel] = useState(false);
  const { job, error, busy, start: run } = useJob();
  const gallery = usePoll<Generation[]>("/api/gallery?kind=image&limit=40");

  if (loaded && !models.length) {
    return (
      <>
        <PageHeader title="Make a picture" art="image" />
        <NoModelYet task="image" onInstalled={refresh} />
      </>
    );
  }

  const base = current?.defaults.width ?? 512;
  const samplerChoices = current?.samplers?.samplers ?? [];
  const autoSampler = samplerChoices.find((s) => s.id === current?.samplers?.default);
  const names = new Map(models.map((m) => [m.id, modelName(m)]));
  // Oldest first, so the newest sits just above the prompt bar.
  const items = [...(gallery.data ?? [])].reverse();

  const go = () => {
    if (!prompt.trim()) return;
    run(
      "image",
      {
        model,
        prompt,
        ...dims(base, shape),
        quality,
        n: Number(count),
        image_upload: start?.id,
        strength: start ? strength : undefined,
        negative_prompt: negative || undefined,
        seed: seed ? Number(seed) : undefined,
        steps: steps ? Number(steps) : undefined,
        guidance: guidance ? Number(guidance) : undefined,
        sampler: sampler && samplerChoices.some((s) => s.id === sampler) ? sampler : undefined,
      },
      () => gallery.refresh(),
    );
    setPrompt("");
  };

  return (
    <>
      <StudioPage
        title="Pictures"
        scrollKey={`${items.length}-${job?.id ?? ""}`}
        hasItems={items.length > 0 || !!job}
        empty={<StudioEmpty task="image" headline="What would you like to see?" examples={EXAMPLES} onExample={setPrompt} />}
        feed={
          <>
            {items.map((g) => (
              <FeedItem
                key={g.id}
                prompt={g.prompt}
                meta={`${names.get(g.model_id) ?? g.model_id}, ${ago(g.created_at)}`}
                saveUrl={g.files.length === 1 ? fileUrl(g.files[0]) : undefined}
                onReuse={() => setPrompt(g.prompt)}
                onDelete={() => api.del(`/api/gallery/${g.id}`).then(gallery.refresh)}
              >
                <div className={`grid gap-2 ${g.files.length > 1 ? "grid-cols-2" : "max-w-[520px]"}`}>
                  {g.files.map((f) => (
                    <a key={f} href={fileUrl(f)} target="_blank" rel="noreferrer">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={fileUrl(f)} alt={g.prompt} loading="lazy" className="w-full rounded-xl bg-well" />
                    </a>
                  ))}
                </div>
              </FeedItem>
            ))}
            {job && job.status !== "completed" && job.status !== "failed" && (
              <PendingItem job={job} noun={Number(count) > 1 ? "pictures" : "picture"} />
            )}
          </>
        }
        bar={
          <>
            {error && (
              <div className="mb-3">
                <Notice tone="error">{error}</Notice>
              </div>
            )}
            <PromptBar
              value={prompt}
              onChange={setPrompt}
              placeholder="Describe your picture"
              onSubmit={go}
              submitLabel="Create"
              canSubmit={!!prompt.trim() && !!model}
              busy={busy}
              onMore={() => setPanel(true)}
              top={
                start && (
                  <AttachedPicture
                    upload={start}
                    onRemove={() => setStart(null)}
                    note={`The picture will be reimagined from your description. Change: ${Math.round(strength * 100)}%`}
                  />
                )
              }
              tools={
                <>
                  <ModelMenu models={models} value={model} onChange={setModel} task="image" />
                  <OptionChip
                    label="Shape"
                    value={shape}
                    onChange={setShape}
                    options={[
                      { value: "square", label: "Square" },
                      { value: "portrait", label: "Tall" },
                      { value: "landscape", label: "Wide" },
                    ]}
                  />
                  <OptionChip
                    label="Quality"
                    value={quality}
                    onChange={setQuality}
                    options={[
                      { value: "fast", label: "Quick", hint: "Fewer steps, a rougher result" },
                      { value: "balanced", label: "Balanced", hint: "Good for most pictures" },
                      { value: "best", label: "Best", hint: "More steps, takes longer" },
                    ]}
                  />
                  <OptionChip
                    label="Pictures"
                    value={count}
                    onChange={setCount}
                    options={["1", "2", "4"].map((v) => ({ value: v, label: v }))}
                  />
                  {!start && (
                    <AttachChip
                      accept="image/*"
                      label="Start from a picture"
                      icon={<ImagePlus size={15} aria-hidden />}
                      onAttached={setStart}
                    />
                  )}
                </>
              }
            />
          </>
        }
      />

      <SidePanel title="More settings" open={panel} onClose={() => setPanel(false)}>
        {start && (
          <Field label={`How much to change your picture: ${Math.round(strength * 100)}%`}>
            <input
              type="range"
              min={0.1}
              max={0.95}
              step={0.05}
              value={strength}
              onChange={(e) => setStrength(Number(e.target.value))}
              className="w-full accent-[var(--ink)]"
            />
          </Field>
        )}
        <Field label="Things to avoid" hint="For example: blurry, extra fingers, text">
          <input className={inputClass} value={negative} onChange={(e) => setNegative(e.target.value)} />
        </Field>
        {samplerChoices.length > 0 && (
          <Field label="Sampler" hint="How the picture is drawn step by step. Automatic works well for most pictures.">
            <select className={`${inputClass} h-10 py-0`} value={sampler} onChange={(e) => setSampler(e.target.value)}>
              <option value="">Automatic{autoSampler ? ` (${autoSampler.label})` : ""}</option>
              {samplerChoices.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Seed" hint="The same seed and description give the same picture.">
          <input className={inputClass} inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="Random" />
        </Field>
        <Field label="Steps" hint={`Overrides Quality. This model's default is ${current?.defaults.steps ?? "automatic"}.`}>
          <input className={inputClass} inputMode="numeric" value={steps} onChange={(e) => setSteps(e.target.value)} placeholder="Automatic" />
        </Field>
        <Field label="Prompt strength" hint={`How closely to follow your description. Default ${current?.defaults.guidance ?? "automatic"}.`}>
          <input className={inputClass} inputMode="decimal" value={guidance} onChange={(e) => setGuidance(e.target.value)} placeholder="Automatic" />
        </Field>
      </SidePanel>
    </>
  );
}
