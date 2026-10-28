"use client";

import { useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";

export type Upload = { id: string; preview: string; name: string };

/** A chip that uploads a file (picture or audio) and hands back its upload id. */
export function AttachChip({
  accept,
  label,
  icon,
  onAttached,
}: {
  accept: string;
  label: string;
  icon: ReactNode;
  onAttached: (u: Upload) => void;
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
        hidden
        onChange={async (e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          setBusy(true);
          try {
            const r = await api.upload<{ id: string }>("/api/uploads", f, f.name);
            onAttached({ id: r.id, preview: URL.createObjectURL(f), name: f.name });
          } finally {
            setBusy(false);
            e.target.value = "";
          }
        }}
      />
    </>
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
