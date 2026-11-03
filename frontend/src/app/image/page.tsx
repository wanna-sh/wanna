"use client";

import { useEffect, useState } from "react";
import { ImagePlus } from "lucide-react";
import { api, fileUrl, type Generation } from "@/lib/api";
import { useJob, useModels, usePoll, useSystem } from "@/lib/hooks";
import { ago } from "@/lib/format";
import { NoModelYet, useTaskModel } from "@/components/models";
import { AttachChip, AttachedPictures, type Upload } from "@/components/generate";
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
import { Button, Field, Notice, PageHeader, inputClass } from "@/components/ui";
import type { InstalledModel } from "@/lib/api";

// "match": the shape of picture 1 (when combining several pictures).
type Shape = "square" | "portrait" | "landscape" | "match";
type Quality = "fast" | "balanced" | "best";

const EXAMPLES = [
  "A watercolor painting of a lighthouse on a cliff at sunrise",
  "A cosy reading nook with a cat, warm afternoon light, photo",
  "A tiny astronaut exploring a giant mushroom forest, storybook style",
  "A bowl of ramen on a wooden table, steam rising, food photography",
];

/** How many pictures a model takes at once, in words. */
function takes(n: number) {
  return n === 1 ? "one picture" : `up to ${n} pictures`;
}

/** What a picture model can do with pictures you attach, for the model menu. */
function pictureNote(m: InstalledModel): string | null {
  const n = m.max_images ?? 1;
  if (n > 1) return `Combines up to ${n} pictures`;
  if (m.meta.needs_image) return "Changes a picture you give it";
  if (m.meta.edits) return "Can change a picture you give it";
  return null;
}

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
  const [shapeChosen, setShapeChosen] = useState(false); // picked by hand, so combining pictures keeps it
  const [quality, setQuality] = useState<Quality>("balanced");
  const [count, setCount] = useState("1");
  // Pictures to start from, in order: "picture 1", "picture 2"... Models that combine pictures take several.
  const [pictures, setPictures] = useState<Upload[]>([]);
  const [skipped, setSkipped] = useState<string | null>(null);
  const [strength, setStrength] = useState(0.6);
  const [negative, setNegative] = useState("");
  const [seed, setSeed] = useState("");
  const [steps, setSteps] = useState("");
  const [guidance, setGuidance] = useState("");
  const [sampler, setSampler] = useState("");
  const [panel, setPanel] = useState(false);
  const [style, setStyle] = useState(""); // a trained style (LoRA) from the Train page
  const [styleStrength, setStyleStrength] = useState(1);
  const { job, error, busy, start: run, resume } = useJob();
  // Arriving from Train ("Use it in Pictures", ?style=<id>): pick that style, the model it was trained on, and a prompt.
  const styleModel = models.find((m) => m.styles?.some((s) => s.id === new URLSearchParams(globalThis.location?.search).get("style")));
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("style");
    const found = styleModel?.styles?.find((s) => s.id === id);
    if (!styleModel || !found) return;
    /* eslint-disable react-hooks/set-state-in-effect */
    setModel(styleModel.id);
    setStyle(found.id);
    setPrompt((p) => p || found.prompt);
    /* eslint-enable react-hooks/set-state-in-effect */
    window.history.replaceState(null, "", window.location.pathname);
  }, [styleModel, setModel]);
  const gallery = usePoll<Generation[]>("/api/gallery?kind=image&limit=40");
  const refreshGallery = gallery.refresh;
  useEffect(() => {
    resume("image", () => refreshGallery());
  }, [resume, refreshGallery]);
  const { data: sys } = useSystem(15000);

  if (loaded && !models.length) {
    return (
      <>
        <PageHeader title="Make a picture" art="image" />
        <NoModelYet task="image" onInstalled={refresh} />
      </>
    );
  }

  const base = current?.defaults.width ?? 512;
  // Models that edit change an attached picture as described; some only edit, so they need a picture.
  const edits = !!current?.meta.edits;
  const needsImage = !!current?.meta.needs_image;
  const limit = current?.max_images ?? 1;
  const start = pictures[0] ?? null;
  const editing = edits && pictures.length > 0;
  const several = pictures.length > 1;
  // More pictures than the chosen model takes (after switching models): say so, and offer the ways out.
  const over = pictures.length > limit;
  const roomier = over ? models.find((m) => (m.max_images ?? 1) >= pictures.length) : undefined;
  // Combining pictures: the result takes picture 1's shape unless a shape was picked by hand.
  const shown: Shape = several ? (shapeChosen ? shape : "match") : shape === "match" ? "square" : shape;
  const attach = (u: Upload) => {
    setSkipped(null);
    setPictures((ps) => [...ps, u]);
  };
  const remove = (id: string) => {
    setSkipped(null);
    setPictures((ps) => ps.filter((p) => p.id !== id));
  };
  const gpuHelp = current?.engine === "sdcpp" ? sys?.engines.sdcpp?.gpu_help : null;
  const gpuHelpUrl = sys?.engines.sdcpp?.gpu_help_url;
  const styles = current?.styles ?? [];
  const chosenStyle = styles.find((s) => s.id === style);
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
        ...dims(base, shown),
        keep_shape: several && shown === "match" ? true : undefined,
        quality,
        n: Number(count),
        image_uploads: pictures.length ? pictures.map((p) => p.id) : undefined,
        strength: start && !edits ? strength : undefined,
        negative_prompt: negative || undefined,
        seed: seed ? Number(seed) : undefined,
        steps: steps ? Number(steps) : undefined,
        guidance: guidance ? Number(guidance) : undefined,
        sampler: sampler && samplerChoices.some((s) => s.id === sampler) ? sampler : undefined,
        lora: chosenStyle?.id,
        lora_strength: chosenStyle ? styleStrength : undefined,
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
            {gpuHelp && (
              <div className="mb-3">
                <Notice>
                  {gpuHelp}{" "}
                  {gpuHelpUrl && (
                    <a className="text-accent underline" href={gpuHelpUrl} target="_blank" rel="noreferrer">
                      Step-by-step instructions
                    </a>
                  )}
                </Notice>
              </div>
            )}
            <PromptBar
              value={prompt}
              onChange={setPrompt}
              placeholder={
                several
                  ? "Describe how to combine them, for example: the person in picture 1 and the person in picture 2 at a café"
                  : editing
                  ? "Describe the change, for example: make it a snowy evening"
                  : needsImage
                    ? "Add a picture, then describe the change"
                    : "Describe your picture"
              }
              onSubmit={go}
              submitLabel={editing ? "Change" : "Create"}
              canSubmit={!!prompt.trim() && !!model && (!needsImage || !!start) && !over}
              busy={busy}
              onMore={() => setPanel(true)}
              top={
                pictures.length ? (
                  <div className="space-y-3">
                    <AttachedPictures
                      uploads={pictures}
                      onRemove={remove}
                      note={
                        over
                          ? null
                          : several
                            ? "Refer to them by number in your description: picture 1, picture 2…"
                            : edits
                              ? "Your picture will be changed as you describe. Its shape stays the same."
                              : `The picture will be reimagined from your description. Change: ${Math.round(strength * 100)}%`
                      }
                    />
                    {over && (
                      <Notice>
                        {current ? modelName(current) : "This model"} takes {takes(limit)} at once, and{" "}
                        {pictures.length} are attached.
                        <span className="flex flex-wrap gap-2 mt-2">
                          {roomier && (
                            <Button onClick={() => setModel(roomier.id)}>
                              Use {modelName(roomier)} ({takes(roomier.max_images ?? 1)})
                            </Button>
                          )}
                          <Button tone="quiet" onClick={() => setPictures((ps) => ps.slice(0, limit))}>
                            Keep {limit === 1 ? "picture 1" : `pictures 1 to ${limit}`}
                          </Button>
                        </span>
                      </Notice>
                    )}
                    {skipped && <p className="text-[14px] text-slate px-2">{skipped}</p>}
                  </div>
                ) : (
                  needsImage && (
                    <p className="text-[14px] text-slate px-2">
                      This model changes pictures you give it. Add a picture, then describe what to change.
                    </p>
                  )
                )
              }
              tools={
                <>
                  <ModelMenu models={models} value={model} onChange={setModel} task="image" note={pictureNote} />
                  {(!editing || several) && (
                    <OptionChip
                      label="Shape"
                      value={shown}
                      onChange={(s) => {
                        setShape(s);
                        setShapeChosen(true);
                      }}
                      options={[
                        ...(several ? [{ value: "match" as Shape, label: "Like picture 1" }] : []),
                        { value: "square", label: "Square" },
                        { value: "portrait", label: "Tall" },
                        { value: "landscape", label: "Wide" },
                      ]}
                    />
                  )}
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
                  {styles.length > 0 && (
                    <OptionChip
                      label="Style"
                      value={chosenStyle?.id ?? ""}
                      onChange={setStyle}
                      options={[
                        { value: "", label: "None", hint: "The model as it is" },
                        ...styles.map((s) => ({ value: s.id, label: s.name, hint: `Trained: say "${s.trigger}" in your description` })),
                      ]}
                    />
                  )}
                  <OptionChip
                    label="Pictures"
                    value={count}
                    onChange={setCount}
                    options={["1", "2", "4"].map((v) => ({ value: v, label: v }))}
                  />
                  {pictures.length < limit && (
                    <AttachChip
                      accept="image/*"
                      label={
                        pictures.length
                          ? `Add another picture (${pictures.length} of ${limit})`
                          : limit > 1
                            ? "Add pictures"
                            : needsImage
                              ? "Add the picture to change"
                              : edits
                                ? "Change a picture"
                                : "Start from a picture"
                      }
                      icon={<ImagePlus size={15} aria-hidden />}
                      max={limit - pictures.length}
                      onAttached={attach}
                      onSkipped={(n) =>
                        setSkipped(
                          `${current ? modelName(current) : "This model"} takes ${takes(limit)} at once, so ${n} ${
                            n === 1 ? "picture wasn't" : "pictures weren't"
                          } added.`,
                        )
                      }
                    />
                  )}
                </>
              }
            />
          </>
        }
      />

      <SidePanel title="More settings" open={panel} onClose={() => setPanel(false)}>
        {start && !edits && (
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
        {chosenStyle && (
          <Field
            label={`How strongly to use ${chosenStyle.name}: ${Math.round(styleStrength * 100)}%`}
            hint={`Lower it if every picture copies it too closely. Say "${chosenStyle.trigger}" in your description to call it up.`}
          >
            <input
              type="range"
              min={0.1}
              max={1.5}
              step={0.05}
              value={styleStrength}
              onChange={(e) => setStyleStrength(Number(e.target.value))}
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
