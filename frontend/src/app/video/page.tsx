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

type Length = "short" | "medium" | "long";
type Quality = "fast" | "balanced" | "best";
const SECONDS: Record<Length, number> = { short: 2, medium: 4, long: 6 };

const EXAMPLES = [
  "A red panda walking along a snowy branch, slow camera pan",
  "Waves rolling onto a beach at sunset, gentle and calm",
  "A paper boat floating down a rainy street, close-up",
  "Time-lapse of clouds drifting over mountains",
];

export default function VideoPage() {
  const { models, loaded, refresh } = useModels("video");
  const [model, setModel] = useTaskModel("video", models);
  const current = models.find((m) => m.id === model);
  const [prompt, setPrompt] = useState("");
  const [length, setLength] = useState<Length>("short");
  const [quality, setQuality] = useState<Quality>("balanced");
  const [wide, setWide] = useState<"wide" | "tall">("wide");
  const [start, setStart] = useState<Upload | null>(null);
  const [negative, setNegative] = useState("");
  const [seed, setSeed] = useState("");
  const [panel, setPanel] = useState(false);
  const { job, error, busy, start: run } = useJob();
  const gallery = usePoll<Generation[]>("/api/gallery?kind=video&limit=20");

  if (loaded && !models.length) {
    return (
      <>
        <PageHeader title="Make a video" art="video" />
        <NoModelYet task="video" onInstalled={refresh} />
      </>
    );
  }

  const needsImage = !!current?.meta.needs_image;
  const fps = current?.defaults.fps ?? 16;
  const w = current?.defaults.width ?? 832;
  const h = current?.defaults.height ?? 480;
  const names = new Map(models.map((m) => [m.id, modelName(m)]));
  const items = [...(gallery.data ?? [])].reverse();

  const go = () => {
    run(
      "video",
      {
        model,
        prompt,
        quality,
        width: wide === "wide" ? w : h,
        height: wide === "wide" ? h : w,
        num_frames: SECONDS[length] * fps + 1,
        fps,
        image_upload: start?.id,
        negative_prompt: negative || undefined,
        seed: seed ? Number(seed) : undefined,
      },
      () => gallery.refresh(),
    );
    setPrompt("");
  };

  return (
    <>
      <StudioPage
        title="Videos"
        scrollKey={`${items.length}-${job?.id ?? ""}`}
        hasItems={items.length > 0 || !!job}
        empty={
          <StudioEmpty task="video" headline="What should happen in your video?" examples={EXAMPLES} onExample={setPrompt}>
            <p className="text-[14px] text-slate mt-5">Videos take a few minutes. Start with a short one.</p>
          </StudioEmpty>
        }
        feed={
          <>
            {items.map((g) => (
              <FeedItem
                key={g.id}
                prompt={g.prompt}
                meta={`${names.get(g.model_id) ?? g.model_id}, ${ago(g.created_at)}`}
                saveUrl={fileUrl(g.files[0])}
                onReuse={() => setPrompt(g.prompt)}
                onDelete={() => api.del(`/api/gallery/${g.id}`).then(gallery.refresh)}
              >
                <video src={fileUrl(g.files[0])} controls loop preload="metadata" className="w-full max-w-[640px] rounded-xl bg-black" />
              </FeedItem>
            ))}
            {job && job.status !== "completed" && job.status !== "failed" && <PendingItem job={job} noun="video" />}
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
              placeholder={needsImage ? "Describe how the picture should move (optional)" : "Describe your video"}
              onSubmit={go}
              submitLabel="Create"
              canSubmit={!!model && (needsImage ? !!start : !!prompt.trim())}
              busy={busy}
              onMore={() => setPanel(true)}
              top={
                start ? (
                  <AttachedPicture upload={start} onRemove={() => setStart(null)} note="The video starts from this picture." />
                ) : (
                  needsImage && (
                    <p className="text-[14px] text-slate px-2">This model brings a picture to life. Add a starting picture to begin.</p>
                  )
                )
              }
              tools={
                <>
                  <ModelMenu models={models} value={model} onChange={setModel} task="video" />
                  <OptionChip
                    label="Length"
                    value={length}
                    onChange={setLength}
                    options={[
                      { value: "short", label: `${SECONDS.short} seconds`, hint: "Fastest to make" },
                      { value: "medium", label: `${SECONDS.medium} seconds` },
                      { value: "long", label: `${SECONDS.long} seconds`, hint: "Takes the longest" },
                    ]}
                  />
                  <OptionChip
                    label="Shape"
                    value={wide}
                    onChange={setWide}
                    options={[
                      { value: "wide", label: "Wide" },
                      { value: "tall", label: "Tall" },
                    ]}
                  />
                  <OptionChip
                    label="Quality"
                    value={quality}
                    onChange={setQuality}
                    options={[
                      { value: "fast", label: "Quick" },
                      { value: "balanced", label: "Balanced" },
                      { value: "best", label: "Best" },
                    ]}
                  />
                  {!start && (
                    <AttachChip
                      accept="image/*"
                      label={needsImage ? "Add starting picture" : "Start from a picture"}
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
        <Field label="Things to avoid" hint="For example: blurry, flickering, text">
          <input className={inputClass} value={negative} onChange={(e) => setNegative(e.target.value)} />
        </Field>
        <Field label="Seed" hint="The same seed and description give the same video.">
          <input className={inputClass} inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="Random" />
        </Field>
      </SidePanel>
    </>
  );
}
