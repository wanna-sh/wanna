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

// Bark ships these speaker presets; other voice models have a single voice.
const BARK_VOICES = [
  { value: "", label: "Surprise me" },
  { value: "v2/en_speaker_0", label: "English, voice 1" },
  { value: "v2/en_speaker_3", label: "English, voice 2" },
  { value: "v2/en_speaker_6", label: "English, voice 3" },
  { value: "v2/en_speaker_9", label: "English, voice 4" },
  { value: "v2/de_speaker_1", label: "German" },
  { value: "v2/es_speaker_1", label: "Spanish" },
  { value: "v2/fr_speaker_1", label: "French" },
  { value: "v2/hi_speaker_1", label: "Hindi" },
  { value: "v2/ja_speaker_1", label: "Japanese" },
];

const EXAMPLES = [
  "Welcome to the show. Tonight we're talking about the night sky.",
  "Your package has arrived. Have a wonderful day!",
  "Once upon a time, in a village by the sea, there lived a curious fox.",
  "Remember to drink water and take a short break.",
];

export default function SpeechPage() {
  const { models, loaded, refresh } = useModels("speech");
  const [model, setModel] = useTaskModel("speech", models);
  const current = models.find((m) => m.id === model);
  const isBark = current?.repo_id.toLowerCase().includes("bark");
  const [text, setText] = useState("");
  const [voice, setVoice] = useState("");
  const [speed, setSpeed] = useState("1");
  const { job, error, busy, start } = useJob();
  const gallery = usePoll<Generation[]>("/api/gallery?kind=audio&limit=40");

  if (loaded && !models.length) {
    return (
      <>
        <PageHeader title="Hear text read aloud" art="speech" />
        <NoModelYet task="speech" onInstalled={refresh} />
      </>
    );
  }

  const names = new Map(models.map((m) => [m.id, modelName(m)]));
  // Music lives in the same "audio" gallery, so keep only recordings made by voice models.
  const items = [...(gallery.data ?? [])].filter((g) => names.has(g.model_id)).reverse();

  const go = () => {
    start("speech", { model, text, voice: voice || undefined, speed: Number(speed), format: "wav" }, () =>
      gallery.refresh(),
    );
    setText("");
  };

  return (
    <StudioPage
      title="Read aloud"
      scrollKey={`${items.length}-${job?.id ?? ""}`}
      hasItems={items.length > 0 || !!job}
      empty={<StudioEmpty task="speech" headline="What should I say?" examples={EXAMPLES} onExample={setText} />}
      feed={
        <>
          {items.map((g) => (
            <FeedItem
              key={g.id}
              prompt={g.prompt}
              meta={`${names.get(g.model_id) ?? g.model_id}, ${ago(g.created_at)}`}
              saveUrl={fileUrl(g.files[0])}
              onReuse={() => setText(g.prompt)}
              onDelete={() => api.del(`/api/gallery/${g.id}`).then(gallery.refresh)}
            >
              <audio src={fileUrl(g.files[0])} controls preload="none" className="w-full max-w-[520px]" />
            </FeedItem>
          ))}
          {job && job.status !== "completed" && job.status !== "failed" && <PendingItem job={job} noun="recording" />}
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
            value={text}
            onChange={setText}
            placeholder={isBark ? "Type what to say. Try [laughs] or [sighs]" : "Type or paste what to say"}
            onSubmit={go}
            submitLabel="Read aloud"
            canSubmit={!!text.trim() && !!model}
            busy={busy}
            tools={
              <>
                <ModelMenu models={models} value={model} onChange={setModel} task="speech" />
                {isBark && <OptionChip label="Voice" value={voice} onChange={setVoice} options={BARK_VOICES} />}
                <OptionChip
                  label="Speed"
                  value={speed}
                  onChange={setSpeed}
                  options={[
                    { value: "0.85", label: "Slower" },
                    { value: "1", label: "Normal" },
                    { value: "1.2", label: "Faster" },
                  ]}
                />
              </>
            }
          />
        </>
      }
    />
  );
}
