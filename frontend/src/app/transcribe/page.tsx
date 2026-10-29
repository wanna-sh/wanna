"use client";

import { useRef, useState } from "react";
import { FileAudio, Mic, Square, Upload, X } from "lucide-react";
import { api, type Job, type Segment } from "@/lib/api";
import { useJob, useModels, useStored } from "@/lib/hooks";
import { ago, seconds } from "@/lib/format";
import { NoModelYet, useTaskModel } from "@/components/models";
import {
  ChipButton,
  FeedItem,
  ModelMenu,
  OptionChip,
  PendingItem,
  PromptBar,
  StudioEmpty,
  StudioPage,
  ToggleChip,
  modelName,
} from "@/components/studio";
import { Notice, PageHeader } from "@/components/ui";
import { CopyButton, SaveButton } from "@/components/save";

const LANGUAGES = [
  { value: "", label: "Detect automatically" },
  { value: "english", label: "English" },
  { value: "spanish", label: "Spanish" },
  { value: "french", label: "French" },
  { value: "german", label: "German" },
  { value: "hindi", label: "Hindi" },
  { value: "italian", label: "Italian" },
  { value: "japanese", label: "Japanese" },
  { value: "chinese", label: "Chinese" },
  { value: "portuguese", label: "Portuguese" },
  { value: "arabic", label: "Arabic" },
];

// Transcripts aren't files, so they're kept in this browser like chats.
interface Transcript {
  id: string;
  name: string;
  model: string;
  text: string;
  segments: Segment[];
  created: number;
}

function srt(segs: Segment[]) {
  const ts = (t: number) => new Date(t * 1000).toISOString().slice(11, 23).replace(".", ",");
  return segs.map((s, i) => `${i + 1}\n${ts(s.start)} --> ${ts(s.end ?? s.start)}\n${s.text}\n`).join("\n");
}

export default function TranscribePage() {
  const { models, loaded, refresh } = useModels("transcribe");
  const [model, setModel] = useTaskModel("transcribe", models);
  const [file, setFile] = useState<{ id: string; name: string } | null>(null);
  const [language, setLanguage] = useState("");
  const [translate, setTranslate] = useState(false);
  const [recording, setRecording] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [history, setHistory] = useStored<Transcript[]>("wanna.transcripts", []);
  const recorder = useRef<MediaRecorder | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const { job, error, busy, start } = useJob();

  if (loaded && !models.length) {
    return (
      <>
        <PageHeader title="Turn a recording into text" art="transcribe" />
        <NoModelYet task="transcribe" onInstalled={refresh} />
      </>
    );
  }

  const names = new Map(models.map((m) => [m.id, modelName(m)]));

  const upload = async (blob: Blob, name: string) => {
    setUploading(true);
    try {
      const r = await api.upload<{ id: string }>("/api/uploads", blob, name);
      setFile({ id: r.id, name });
    } finally {
      setUploading(false);
    }
  };

  const record = async () => {
    setMicError(null);
    if (recording) {
      recorder.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        upload(new Blob(chunks, { type: rec.mimeType }), `Recording at ${new Date().toLocaleTimeString()}`);
      };
      rec.start();
      recorder.current = rec;
      setRecording(true);
    } catch {
      setMicError("Couldn't use the microphone. Allow microphone access in your browser and try again.");
    }
  };

  const go = () => {
    if (!file) return;
    const name = file.name;
    start("transcribe", { model, file_upload: file.id, language: language || undefined, translate }, (j: Job) => {
      if (j.status === "completed" && j.result?.text !== undefined) {
        setHistory((h) => [
          ...h,
          { id: j.id, name, model, text: j.result!.text ?? "", segments: j.result!.segments ?? [], created: Date.now() / 1000 },
        ]);
      }
    });
    setFile(null);
  };

  return (
    <StudioPage
      title="Transcribe"
      scrollKey={`${history.length}-${job?.id ?? ""}`}
      hasItems={history.length > 0 || !!job}
      empty={
        <StudioEmpty task="transcribe" headline="What should I write down?">
          <p className="text-[14px] text-slate mt-4">
            Choose an audio or video file below, or record with your microphone. Transcripts are kept in this browser.
          </p>
        </StudioEmpty>
      }
      feed={
        <>
          {history.map((t) => (
            <FeedItem
              key={t.id}
              prompt={t.name}
              meta={`${names.get(t.model) ?? t.model}, ${ago(t.created)}`}
              onDelete={() => setHistory((h) => h.filter((x) => x.id !== t.id))}
            >
              <div className="rounded-xl bg-paper border border-line p-4">
                {t.segments.length ? (
                  <ol className="flex flex-col gap-1.5">
                    {t.segments.map((s, i) => (
                      <li key={i} className="grid grid-cols-[48px_1fr] gap-3">
                        <span className="text-slate tabular-nums text-[13px] pt-0.5">{seconds(s.start)}</span>
                        <span>{s.text}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="whitespace-pre-wrap">{t.text}</p>
                )}
              </div>
              <div className="flex flex-wrap gap-1 mt-2 -ml-2">
                <CopyButton text={t.text} />
                <SaveButton text={t.text} name="transcript.txt" label="Save as text" />
                {t.segments.length > 0 && (
                  <SaveButton text={srt(t.segments)} name="subtitles.srt" label="Save as subtitles" />
                )}
              </div>
            </FeedItem>
          ))}
          {job && job.status !== "completed" && job.status !== "failed" && <PendingItem job={job} noun="transcript" />}
        </>
      }
      bar={
        <>
          {(error || micError) && (
            <div className="mb-3">
              <Notice tone="error">{micError ?? error}</Notice>
            </div>
          )}
          <input
            ref={input}
            type="file"
            accept="audio/*,video/*"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload(f, f.name);
              e.target.value = "";
            }}
          />
          <PromptBar
            onSubmit={go}
            submitLabel="Write it down"
            canSubmit={!!file && !!model}
            busy={busy}
            tools={
              <>
                <ModelMenu models={models} value={model} onChange={setModel} task="transcribe" />
                <ChipButton onClick={() => input.current?.click()}>
                  <Upload size={15} aria-hidden /> Choose a file
                </ChipButton>
                <ChipButton onClick={record}>
                  {recording ? <Square size={13} fill="currentColor" aria-hidden /> : <Mic size={15} aria-hidden />}
                  {recording ? "Stop recording" : "Record"}
                </ChipButton>
                <OptionChip label="Language" value={language} onChange={setLanguage} options={LANGUAGES} />
                <ToggleChip on={translate} onChange={setTranslate}>
                  Translate to English
                </ToggleChip>
              </>
            }
          >
            {recording ? (
              <p className="flex items-center gap-2 text-[16px]">
                <span className="size-2 rounded-full bg-danger animate-pulse" aria-hidden /> Recording. Press Stop when you&apos;re done.
              </p>
            ) : uploading ? (
              <p className="text-slate text-[16px]">Uploading…</p>
            ) : file ? (
              <div className="flex items-center gap-2 text-[16px]">
                <FileAudio size={18} className="text-slate" aria-hidden />
                <span className="truncate">{file.name}</span>
                <button onClick={() => setFile(null)} aria-label="Remove file" className="ml-1 text-slate hover:text-ink">
                  <X size={16} />
                </button>
              </div>
            ) : (
              <p className="text-slate text-[16px]">Choose a file or record to get started.</p>
            )}
          </PromptBar>
        </>
      }
    />
  );
}
