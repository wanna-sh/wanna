"use client";

import { useState } from "react";
import { Button, Field, Panel, inputClass } from "@/components/ui";
import { BigModels, SaveStatus, SectionTitle, useSettings, type Settings } from "@/components/settings";
import { bytes } from "@/lib/format";

/** Where new downloads are saved. Models already downloaded stay where they are and keep working. */
function ModelsFolder({ s, save }: { s: Settings; save: (patch: Partial<Settings>) => Promise<void> }) {
  const current = s.models_dir || s.models_dir_default;
  const [folder, setFolder] = useState(current);
  const changed = folder.trim() !== current;
  return (
    <Panel>
      <SectionTitle>Where models are saved</SectionTitle>
      <p className="text-slate text-[15px] mb-4">
        New downloads go to this folder, for example on a bigger drive. Models you already have stay where they are
        and keep working; deleting one frees space on the drive it&apos;s on.
      </p>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          save({ models_dir: folder.trim() });
        }}
      >
        <input
          className={`${inputClass} min-w-0 flex-1 basis-64 font-mono text-[14px]`}
          spellCheck={false}
          autoComplete="off"
          placeholder={s.models_dir_default}
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
          aria-label="Folder for new models"
        />
        <Button type="submit" disabled={!changed || !folder.trim()}>
          Save
        </Button>
        {s.models_dir && (
          <Button
            tone="quiet"
            type="button"
            onClick={() => {
              setFolder(s.models_dir_default);
              save({ models_dir: "" });
            }}
          >
            Use the default
          </Button>
        )}
      </form>
      <p className="text-slate text-[14px] mt-2">
        Paste the folder&apos;s full path, such as <span className="font-mono">D:\Models</span>. It&apos;s created if
        it doesn&apos;t exist. {bytes(s.models_dir_free, 0)} free there.
      </p>
    </Panel>
  );
}

/** Settings → Models & memory: where models are saved and how they use this computer's memory. */
export default function ModelsMemoryPage() {
  const { s, save, saved, error } = useSettings();
  return (
    <>
      <SaveStatus saved={saved} error={error} />
      {s && (
        <>
          {/* Keyed on the saved folder, so the box shows it as the server cleaned it up (quotes, the default). */}
          <ModelsFolder key={s.models_dir || s.models_dir_default} s={s} save={save} />
          <Panel>
            <SectionTitle className="mb-4">Memory</SectionTitle>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Stop idle models after" hint="Frees graphics memory when you're not using a model.">
                <select
                  className={`${inputClass} h-10 py-0`}
                  value={s.idle_unload_minutes}
                  onChange={(e) => save({ idle_unload_minutes: Number(e.target.value) })}
                >
                  <option value={0}>Never</option>
                  <option value={5}>5 minutes</option>
                  <option value={15}>15 minutes</option>
                  <option value={60}>1 hour</option>
                </select>
              </Field>
              <Field label="Chat memory" hint="How much of a conversation chat models can remember.">
                <select
                  className={`${inputClass} h-10 py-0`}
                  value={s.default_context}
                  onChange={(e) => save({ default_context: Number(e.target.value) })}
                >
                  <option value={4096}>Short (4K)</option>
                  <option value={8192}>Standard (8K)</option>
                  <option value={16384}>Long (16K)</option>
                  <option value={32768}>Very long (32K)</option>
                </select>
              </Field>
            </div>
          </Panel>
          <BigModels on={s.stream_from_drive} onChange={(v) => save({ stream_from_drive: v })} />
        </>
      )}
    </>
  );
}
