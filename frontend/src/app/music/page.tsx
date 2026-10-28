"use client";

import { useState } from "react";
import { api, fileUrl, type Generation } from "@/lib/api";
import { useJob, useModels, usePoll } from "@/lib/hooks";
import { ago } from "@/lib/format";
import { NoModelYet, useTaskModel } from "@/components/models";
import {
  FeedItem,
  ModelMenu,
  OptionChip,
  PendingItem,
  PromptBar,
  StudioEmpty,
  StudioPage,
  modelName,
} from "@/components/studio";
import { Notice, PageHeader } from "@/components/ui";

const EXAMPLES = [
  "Calm lo-fi beat with soft piano and vinyl crackle",
  "Epic orchestral trailer music with big drums",
  "Upbeat 80s synth-pop with a catchy bassline",
  "Gentle acoustic guitar by a campfire",
];

export default function MusicPage() {
  const { models, loaded, refresh } = useModels("sound");
  const [model, setModel] = useTaskModel("sound", models);
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState("10");
  const { job, error, busy, start } = useJob();
  const gallery = usePoll<Generation[]>("/api/gallery?kind=audio&limit=40");

  if (loaded && !models.length) {
    return (
      <>
        <PageHeader title="Make music" art="sound" />
        <NoModelYet task="sound" onInstalled={refresh} />
      </>
    );
  }

  const names = new Map(models.map((m) => [m.id, modelName(m)]));
  // Voice recordings share the "audio" gallery, so keep only tracks made by music models.
  const items = [...(gallery.data ?? [])].filter((g) => names.has(g.model_id)).reverse();

  const go = () => {
    start("sound", { model, prompt, duration: Number(duration) }, () => gallery.refresh());
    setPrompt("");
  };

  return (
    <StudioPage
      title="Music"
      scrollKey={`${items.length}-${job?.id ?? ""}`}
      hasItems={items.length > 0 || !!job}
      empty={<StudioEmpty task="sound" headline="What should it sound like?" examples={EXAMPLES} onExample={setPrompt} />}
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
              <audio src={fileUrl(g.files[0])} controls preload="none" className="w-full max-w-[520px]" />
            </FeedItem>
          ))}
          {job && job.status !== "completed" && job.status !== "failed" && <PendingItem job={job} noun="track" />}
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
            placeholder="Describe the genre, mood and instruments"
            onSubmit={go}
            submitLabel="Create"
            canSubmit={!!prompt.trim() && !!model}
            busy={busy}
            tools={
              <>
                <ModelMenu models={models} value={model} onChange={setModel} task="sound" />
              <OptionChip
                label="Length"
                value={duration}
                onChange={setDuration}
                options={["5", "10", "20", "30"].map((d) => ({
                  value: d,
                  label: `${d} seconds`,
                  hint: d === "30" ? "Takes the longest" : undefined,
                }))}
              />
              </>
            }
          />
        </>
      }
    />
  );
}
