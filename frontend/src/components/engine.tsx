"use client";

import { Button, Notice, Progress } from "./ui";

export type EngineState = {
  status: string;
  progress: number;
  message: string;
  error: string | null;
};

/**
 * The picture engine (stable-diffusion.cpp) being set up for GGUF picture models: a progress bar with what it's doing
 * (downloading, or building on some Linux computers), or what went wrong with a way to try again. Nothing once it's
 * ready.
 */
export function PictureEngineSetup({ engine, onRetry }: { engine: EngineState; onRetry: () => void }) {
  if (engine.status === "ready") return null;
  if (engine.status === "error") {
    return (
      <Notice tone="error">
        <p>The picture engine couldn&apos;t be set up: {engine.error}</p>
        <Button tone="quiet" className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      </Notice>
    );
  }
  return (
    <div className="rounded-xl border border-line bg-paper p-4" aria-live="polite">
      <Progress
        value={engine.status === "installing" ? Math.max(0.02, engine.progress) : 0.02}
        label={`Setting up the picture engine for your computer${engine.message ? `: ${engine.message}` : ""}`}
        live
      />
      <p className="text-[13px] text-slate mt-2">
        This happens once, the first time you use a GGUF picture model. You can write your description meanwhile.
      </p>
    </div>
  );
}
