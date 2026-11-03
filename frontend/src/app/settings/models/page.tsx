"use client";

import { Field, Panel, inputClass } from "@/components/ui";
import { BigModels, SaveStatus, SectionTitle, useSettings } from "@/components/settings";

/** Settings → Models & memory: how models use this computer's memory. */
export default function ModelsMemoryPage() {
  const { s, save, saved, error } = useSettings();
  return (
    <>
      <SaveStatus saved={saved} error={error} />
      {s && (
        <>
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
