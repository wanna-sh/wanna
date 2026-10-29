"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { Button, Notice, Progress } from "./ui";

interface AddonState {
  installed: boolean;
  can_install: boolean;
  reason: string | null;
  size: string;
  status: "idle" | "installing" | "done" | "error";
  message: string;
  error: string | null;
  downloaded: number;
  to_download: number;
}

/**
 * Installs that start with chat only (the desktop app, install.sh --chat-only) add the AI libraries for pictures,
 * video, voices and music the first time they're needed. Shows nothing once they're installed.
 */
export function MlAddon() {
  const { data, refresh } = usePoll<{ ml: AddonState }>("/api/addons", 2000);
  const [error, setError] = useState<string | null>(null);
  const ml = data?.ml;
  if (!ml || ml.installed) return null;

  const install = async () => {
    setError(null);
    try {
      await api.post("/api/addons/ml/install");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="mb-6 rounded-2xl border border-line bg-paper p-5" aria-live="polite">
      <h2 className="font-medium">One more step: picture, video, voice and music support</h2>
      {ml.status === "installing" ? (
        <div className="mt-3">
          <Progress
            value={ml.to_download ? ml.downloaded / ml.to_download : 0.02}
            label={ml.message || "Downloading"}
            live
          />
          <p className="text-[13px] text-slate mt-2">
            This is a one-time download of {ml.size}. You can keep using Chat meanwhile.
          </p>
        </div>
      ) : ml.status === "done" ? (
        <p className="text-[15px] text-slate mt-1.5">
          <Loader2 size={14} className="inline animate-spin mr-1.5" aria-hidden />
          Installed. Getting ready…
        </p>
      ) : ml.can_install ? (
        <>
          <p className="text-[15px] text-slate mt-1.5">
            These need extra AI libraries that aren&apos;t installed yet. It&apos;s a one-time download of {ml.size},
            matched to your graphics card.
          </p>
          {(error || ml.error) && (
            <div className="mt-3">
              <Notice tone="error">Installing didn&apos;t work: {error || ml.error}</Notice>
            </div>
          )}
          <div className="mt-4">
            <Button onClick={install}>
              <Download size={15} aria-hidden /> {ml.status === "error" ? "Try again" : "Install"}
            </Button>
          </div>
        </>
      ) : (
        <p className="text-[15px] text-slate mt-1.5">{ml.reason}</p>
      )}
    </section>
  );
}
