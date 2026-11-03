"use client";

import { useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";

export type Upload = { id: string; preview: string; name: string };

/** A chip that uploads a file (picture or audio) and hands back its upload id. With `max` above 1, several can be
 * chosen at once: up to `max` are uploaded, in order, and `onSkipped` hears how many more were chosen. */
export function AttachChip({
  accept,
  label,
  icon,
  onAttached,
  max = 1,
  onSkipped,
}: {
  accept: string;
  label: string;
  icon: ReactNode;
  onAttached: (u: Upload) => void;
  max?: number;
  onSkipped?: (count: number) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <button
        type="button"
        disabled={busy}
        onClick={() => input.current?.click()}
        className="h-9 px-3 inline-flex items-center gap-1.5 rounded-full border border-line text-[14px] hover:bg-well transition-colors disabled:opacity-50"
      >
        {icon}
        {busy ? "Uploading…" : label}
      </button>
      <input
        ref={input}
        type="file"
        accept={accept}
        multiple={max > 1}
        hidden
        onChange={async (e) => {
          const chosen = Array.from(e.target.files ?? []);
          if (!chosen.length) return;
          const files = chosen.slice(0, Math.max(1, max));
          if (chosen.length > files.length) onSkipped?.(chosen.length - files.length);
          setBusy(true);
          try {
            for (const f of files) {
              const r = await api.upload<{ id: string }>("/api/uploads", f, f.name);
              onAttached({ id: r.id, preview: URL.createObjectURL(f), name: f.name });
            }
          } finally {
            setBusy(false);
            e.target.value = "";
          }
        }}
      />
    </>
  );
}

/** Numbered thumbnails of several attached pictures, each with a remove button. The numbers are how a description
 * refers to them ("the person in picture 1"). */
export function AttachedPictures({
  uploads,
  onRemove,
  note,
}: {
  uploads: Upload[];
  onRemove: (id: string) => void;
  note?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <ol className="flex flex-wrap gap-3" aria-label="Attached pictures">
        {uploads.map((u, i) => (
          <li key={u.id} className="relative">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={u.preview} alt={`Picture ${i + 1}: ${u.name}`} className="size-16 object-cover rounded-xl border border-line" />
            <span className="absolute bottom-1 left-1 min-w-5 h-5 px-1 grid place-items-center rounded-full bg-ink text-fog text-[12px] font-medium">
              {i + 1}
            </span>
            <button
              type="button"
              aria-label={`Remove picture ${i + 1}`}
              onClick={() => onRemove(u.id)}
              className="absolute -top-2 -right-2 size-6 grid place-items-center rounded-full bg-ink text-fog"
            >
              <X size={12} />
            </button>
          </li>
        ))}
      </ol>
      {note && <div className="text-[14px] text-slate basis-full sm:basis-auto sm:flex-1">{note}</div>}
    </div>
  );
}

/** Thumbnail of an attached picture with a remove button. */
export function AttachedPicture({ upload, onRemove, note }: { upload: Upload; onRemove: () => void; note?: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <div className="relative">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={upload.preview} alt="Starting picture" className="size-16 object-cover rounded-xl border border-line" />
        <button
          type="button"
          aria-label="Remove picture"
          onClick={onRemove}
          className="absolute -top-2 -right-2 size-6 grid place-items-center rounded-full bg-ink text-fog"
        >
          <X size={12} />
        </button>
      </div>
      {note && <div className="text-[14px] text-slate">{note}</div>}
    </div>
  );
}
