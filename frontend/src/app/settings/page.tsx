"use client";

import { useEffect, useState } from "react";
import { CircleAlert, CircleCheck, CircleX, Loader2 } from "lucide-react";
import { api, type SystemCheckItem } from "@/lib/api";
import { usePoll, useSystem } from "@/lib/hooks";
import { bytes, gpuName, mem } from "@/lib/format";
import { Button, Field, Notice, PageHeader, Panel, inputClass } from "@/components/ui";

interface Settings {
  hf_token: string;
  hf_token_set: boolean;
  require_api_key: boolean;
  idle_unload_minutes: number;
  default_context: number;
}

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [token, setToken] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: sys } = useSystem(5000);

  useEffect(() => {
    api.get<Settings>("/api/settings").then(setS).catch((e) => setError(e.message));
  }, []);

  const save = async (patch: Partial<Settings>) => {
    setError(null);
    try {
      setS(await api.put<Settings>("/api/settings", patch));
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <PageHeader title="Settings">{saved && <span className="text-ok font-medium">Saved</span>}</PageHeader>
      {error && <Notice tone="error">{error}</Notice>}
      {s && (
        <div className="grid gap-5 max-w-[760px]">
          <SystemCheck />
          <Panel>
            <h2 className="font-display text-[1.25rem] leading-snug mb-1">Hugging Face account</h2>
            <p className="text-slate text-[15px] mb-4">
              Some models (like FLUX.1) ask you to accept their terms. Create a free &ldquo;read&rdquo; token at{" "}
              <a className="text-accent underline" href="https://huggingface.co/settings/tokens" target="_blank">
                huggingface.co/settings/tokens
              </a>{" "}
              and paste it here.
            </p>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                save({ hf_token: token });
                setToken("");
              }}
            >
              <input
                className={inputClass}
                type="password"
                autoComplete="off"
                placeholder={s.hf_token_set ? `Saved (${s.hf_token})` : "hf_…"}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                aria-label="Hugging Face token"
              />
              <Button type="submit" disabled={!token}>
                Save
              </Button>
              {s.hf_token_set && (
                <Button tone="quiet" type="button" onClick={() => save({ hf_token: "" })}>
                  Remove
                </Button>
              )}
            </form>
          </Panel>

          <Panel>
            <h2 className="font-display text-[1.25rem] leading-snug mb-4">Memory</h2>
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

          <Panel>
            <h2 className="font-display text-[1.25rem] leading-snug mb-1">Security</h2>
            <label className="flex items-start gap-3 mt-3 text-[15px]">
              <input
                type="checkbox"
                checked={s.require_api_key}
                onChange={(e) => save({ require_api_key: e.target.checked })}
                className="mt-1 size-4 accent-[var(--accent)]"
              />
              <span>
                <span className="font-medium">Require API key</span>
                <span className="block text-slate">
                  Apps and other devices must send a key from API &amp; apps. This page on this computer keeps
                  working without one.
                </span>
              </span>
            </label>
          </Panel>

          {sys && (
            <Panel>
              <h2 className="font-display text-[1.25rem] leading-snug mb-3">This computer</h2>
              <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-[15px]">
                {sys.gpus.map((g) => (
                  <Row key={g.index} k={`Graphics card ${g.index + 1}`} v={`${gpuName(g.name)}, ${mem(g.memory_total)}`} />
                ))}
                <Row k="Memory" v={mem(sys.ram_total)} />
                <Row k="Processor threads" v={String(sys.cpu_count)} />
                <Row k="Free disk space" v={bytes(sys.disk_free)} />
                <Row k="Chat engine" v={`llama.cpp, ${sys.engines.llamacpp.status} (${sys.engines.llamacpp.backend})`} />
                {sys.cuda_driver && <Row k="CUDA driver" v={sys.cuda_driver} />}
              </dl>
            </Panel>
          )}
        </div>
      )}
    </>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-slate">{k}</dt>
      <dd>{v}</dd>
    </>
  );
}

/** Is this computer ready? One row per area, checked by the server. */
function SystemCheck() {
  const [refresh, setRefresh] = useState(0);
  const { data, error } = usePoll<SystemCheckItem[]>(`/api/system/check?refresh=${refresh > 0}&n=${refresh}`);
  const icon = (st: SystemCheckItem["status"]) =>
    st === "ok" ? (
      <CircleCheck size={18} className="text-ok shrink-0" aria-label="Ready" />
    ) : st === "warn" ? (
      <CircleAlert size={18} className="text-caution shrink-0" aria-label="Needs attention" />
    ) : (
      <CircleX size={18} className="text-danger shrink-0" aria-label="Not working" />
    );
  const problems = (data ?? []).filter((c) => c.status !== "ok").length;
  return (
    <Panel>
      <div className="flex items-center justify-between gap-3 mb-1">
        <h2 className="font-display text-[1.25rem] leading-snug">System check</h2>
        <button className="text-[14px] underline underline-offset-2 text-slate hover:text-ink" onClick={() => setRefresh((n) => n + 1)}>
          Check again
        </button>
      </div>
      <p className="text-slate text-[15px] mb-4">
        {!data ? "Checking this computer…" : problems ? `${problems} thing${problems > 1 ? "s" : ""} to look at.` : "Everything is ready."}
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      {!data && !error && <Loader2 size={18} className="animate-spin text-slate" aria-hidden />}
      <ul className="flex flex-col divide-y divide-line">
        {(data ?? []).map((c) => (
          <li key={c.id} className="flex gap-3 py-3 first:pt-0">
            {icon(c.status)}
            <div className="min-w-0">
              <div className="font-medium text-[15px]">{c.label}</div>
              <div className="text-[14px] text-slate">{c.detail}</div>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
