"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { api, fileUrl, type Generation } from "@/lib/api";
import { useModels, usePoll } from "@/lib/hooks";
import { ago, prettyName } from "@/lib/format";
import { PageHeader, Segmented } from "@/components/ui";
import { SaveButton } from "@/components/save";

type Kind = "all" | "image" | "video" | "audio";

export default function GalleryPage() {
  const [kind, setKind] = useState<Kind>("all");
  const { data: models } = useModels(undefined, 0);
  const names = new Map((models ?? []).map((m) => [m.id, prettyName(m.meta.title || m.repo_id)]));
  const { data, refresh } = usePoll<Generation[]>(`/api/gallery?limit=300${kind === "all" ? "" : `&kind=${kind}`}`);

  return (
    <>
      <PageHeader title="Gallery" intro="Everything you've made, newest first. Files are saved on this computer.">
        <Segmented
          label="Show"
          value={kind}
          onChange={setKind}
          options={[
            { value: "all", label: "Everything" },
            { value: "image", label: "Pictures" },
            { value: "video", label: "Videos" },
            { value: "audio", label: "Audio" },
          ]}
        />
      </PageHeader>
      {data && data.length === 0 && <p className="text-slate">Nothing here yet. What you make will show up here.</p>}
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {(data ?? []).flatMap((g) =>
          g.files.map((f) => (
            <li key={f} className="rounded-2xl bg-paper border border-line overflow-hidden flex flex-col">
              {g.kind === "image" && (
                <a href={fileUrl(f)} target="_blank">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={fileUrl(f)} alt={g.prompt} loading="lazy" className="w-full aspect-square object-cover" />
                </a>
              )}
              {g.kind === "video" && <video src={fileUrl(f)} controls loop preload="metadata" className="w-full bg-ink" />}
              {g.kind === "audio" && (
                <div className="p-4 pb-0">
                  <audio src={fileUrl(f)} controls preload="none" className="w-full" />
                </div>
              )}
              <div className="p-4 flex flex-col gap-1 flex-1">
                <p className="text-[15px] line-clamp-3">{g.prompt}</p>
                <div className="mt-auto pt-2 flex items-center justify-between text-[13px] text-slate">
                  <span>
                    {names.get(g.model_id) ?? g.model_id}, {ago(g.created_at)}
                  </span>
                  <span className="flex gap-1">
                    <SaveButton url={fileUrl(f)} icon={false} className="underline px-1 disabled:no-underline" />
                    <button
                      aria-label="Delete"
                      className="px-1 hover:text-danger"
                      onClick={() => confirm("Delete this for good?") && api.del(`/api/gallery/${g.id}`).then(refresh)}
                    >
                      <Trash2 size={15} />
                    </button>
                  </span>
                </div>
              </div>
            </li>
          )),
        )}
      </ul>
    </>
  );
}
