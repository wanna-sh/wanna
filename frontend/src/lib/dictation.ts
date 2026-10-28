"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "./api";

export type DictationState = "idle" | "recording" | "transcribing";

/**
 * Speak instead of typing: records from the microphone, sends the audio to the transcription
 * endpoint (which uses whichever transcription model is installed) and hands back the text.
 */
export function useDictation(onText: (text: string) => void) {
  const [state, setState] = useState<DictationState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelled = useRef(false);

  const stopTimer = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  };

  useEffect(
    () => () => {
      stopTimer();
      cancelled.current = true;
      recorder.current?.stream.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  const transcribe = useCallback(
    async (blob: Blob) => {
      setState("transcribing");
      try {
        const fd = new FormData();
        fd.append("file", blob, "dictation.webm");
        fd.append("response_format", "json");
        const r = await fetch(`${API_BASE}/v1/audio/transcriptions`, {
          method: "POST",
          headers: { "X-Wanna-UI": "1" },
          body: fd,
        });
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(body.detail ?? body.error?.message ?? "Couldn't turn your recording into text.");
        const text = (body.text ?? "").trim();
        if (text) onText(text);
        else setError("I didn't catch anything. Try speaking a little closer to the microphone.");
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setState("idle");
      }
    },
    [onText],
  );

  const start = useCallback(async () => {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Couldn't use the microphone. Allow microphone access in your browser and try again.");
      return;
    }
    const rec = new MediaRecorder(stream);
    const chunks: Blob[] = [];
    cancelled.current = false;
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      stopTimer();
      if (cancelled.current) {
        setState("idle");
        return;
      }
      transcribe(new Blob(chunks, { type: rec.mimeType }));
    };
    rec.start();
    recorder.current = rec;
    setSeconds(0);
    timer.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    setState("recording");
  }, [transcribe]);

  const stop = useCallback(() => recorder.current?.stop(), []);

  /** Stop recording and throw the audio away. */
  const cancel = useCallback(() => {
    cancelled.current = true;
    recorder.current?.stop();
  }, []);

  return { state, seconds, error, setError, start, stop, cancel };
}
