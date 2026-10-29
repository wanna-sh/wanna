"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy, Download } from "lucide-react";

const QUIET =
  "h-8 px-2.5 inline-flex items-center gap-1.5 rounded-full text-[13px] text-slate hover:text-ink hover:bg-well disabled:hover:bg-transparent";

/** True for a few seconds after something worked. Clicks meanwhile are ignored, so one click makes one copy. */
function useDone(ms = 4000) {
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const mark = () => {
    setDone(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setDone(false), ms);
  };
  return [done, mark] as const;
}

function download(href: string, name = "") {
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** Save a file the server made, or some text, and say so. */
export function SaveButton({
  url,
  text,
  name,
  label = "Save",
  icon = true,
  className = QUIET,
}: {
  url?: string;
  text?: string;
  name?: string;
  label?: ReactNode;
  icon?: boolean;
  className?: string;
}) {
  const [done, mark] = useDone();
  const [saved, setSaved] = useState(false);
  return (
    <button
      type="button"
      className={className}
      disabled={done}
      onClick={() => {
        if (text !== undefined) {
          const href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
          download(href, name);
          setTimeout(() => URL.revokeObjectURL(href), 10_000);
        } else if (url) {
          download(url, name);
        }
        setSaved(true);
        mark();
      }}
    >
      {done ? <Check size={14} aria-hidden /> : icon && <Download size={14} aria-hidden />}
      <span aria-live="polite">{done ? "Saved" : saved ? "Save again" : label}</span>
    </button>
  );
}

/** Copy text, falling back to the old way where the clipboard API isn't allowed (an address other than localhost). */
export function CopyButton({ text, label = "Copy", className = QUIET }: { text: string; label?: ReactNode; className?: string }) {
  const [done, mark] = useDone(2500);
  return (
    <button
      type="button"
      className={className}
      disabled={done}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          const area = document.createElement("textarea");
          area.value = text;
          area.style.position = "fixed";
          area.style.opacity = "0";
          document.body.appendChild(area);
          area.select();
          document.execCommand("copy");
          area.remove();
        }
        mark();
      }}
    >
      {done ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
      <span aria-live="polite">{done ? "Copied" : label}</span>
    </button>
  );
}
