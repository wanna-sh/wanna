"use client";

import { useState, useSyncExternalStore } from "react";
import { api, API_BASE } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { ago } from "@/lib/format";
import { Button, Field, Notice, PageHeader, Panel, Segmented, inputClass } from "@/components/ui";

interface Key {
  id: string;
  name: string;
  prefix: string;
  created_at: number;
  last_used_at: number | null;
}

type Lang = "python" | "javascript" | "curl";

const ENDPOINTS = [
  ["POST", "/v1/chat/completions", "Chat (streaming supported)"],
  ["POST", "/v1/completions", "Raw text completion (GGUF models)"],
  ["POST", "/v1/images/generations", "Make pictures (optional sampler: dpmpp_2m_karras, euler_a, euler, unipc, ddim, builtin)"],
  ["POST", "/v1/images/edits", "Change a picture with a description"],
  ["POST", "/v1/audio/speech", "Text to speech"],
  ["POST", "/v1/audio/transcriptions", "Speech to text (json, text, srt, vtt, verbose_json)"],
  ["POST", "/v1/audio/translations", "Speech in any language to English text"],
  ["POST", "/v1/videos", "Start a video (poll GET /v1/videos/{id}, then /content)"],
  ["GET", "/v1/models", "Installed models and what they do"],
];

export default function DevelopersPage() {
  const keys = usePoll<Key[]>("/api/keys");
  const settings = usePoll<{ require_api_key: boolean }>("/api/settings");
  const [name, setName] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [lang, setLang] = useState<Lang>("python");
  const origin = useSyncExternalStore(
    () => () => {},
    () => API_BASE || window.location.origin,
    () => "http://localhost:7860",
  );

  const base = `${origin}/v1`;
  const key = created ?? (settings.data?.require_api_key ? "YOUR_KEY" : "not-needed");
  const samples: Record<Lang, string> = {
    python: `# pip install openai
from openai import OpenAI

client = OpenAI(base_url="${base}", api_key="${key}")

reply = client.chat.completions.create(
    model="auto",  # or an id from /v1/models
    messages=[{"role": "user", "content": "Write a haiku about GPUs"}],
)
print(reply.choices[0].message.content)

image = client.images.generate(prompt="a cat astronaut", size="512x512")
print(image.data[0].url)

with client.audio.speech.with_streaming_response.create(
    model="auto", voice="default", input="Hello there!"
) as r:
    r.stream_to_file("hello.mp3")`,
    javascript: `// npm install openai
import OpenAI from "openai";

const client = new OpenAI({ baseURL: "${base}", apiKey: "${key}" });

const stream = await client.chat.completions.create({
  model: "auto",
  messages: [{ role: "user", content: "Tell me a short story" }],
  stream: true,
});
for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content ?? "");
}`,
    curl: `curl ${base}/chat/completions \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "auto", "messages": [{"role": "user", "content": "Hi!"}]}'

curl ${base}/audio/transcriptions \\
  -H "Authorization: Bearer ${key}" \\
  -F file=@meeting.mp3 -F response_format=srt`,
  };

  return (
    <>
      <PageHeader
        title="API & apps"
        intro="wanna.sh speaks the OpenAI API, so apps and code that work with OpenAI can use your own models instead."
      />

      <div className="grid gap-5 lg:grid-cols-[1fr_minmax(0,380px)]">
        <div className="flex flex-col gap-5 min-w-0">
          <Panel>
            <h2 className="font-display text-[1.25rem] leading-snug mb-1">Connect an app</h2>
            <p className="text-slate text-[15px] mb-4">
              In any app with an &ldquo;OpenAI-compatible&rdquo; or &ldquo;custom endpoint&rdquo; setting, use this
              address:
            </p>
            <CopyField value={base} />
            <p className="text-slate text-[15px] mt-3">
              Use <code className="font-mono text-[14px]">auto</code> as the model name to use whichever model is
              running, or an exact id from{" "}
              <a className="text-accent underline" href={`${base}/models`} target="_blank">
                the model list
              </a>
              . Full reference:{" "}
              <a className="text-accent underline" href={`${origin}/docs`} target="_blank">
                interactive API docs
              </a>
              .
            </p>
          </Panel>

          <Panel>
            <div className="flex flex-wrap justify-between items-center gap-3 mb-3">
              <h2 className="font-display text-[1.25rem] leading-snug">Example code</h2>
              <Segmented
                label="Language"
                value={lang}
                onChange={setLang}
                options={[
                  { value: "python", label: "Python" },
                  { value: "javascript", label: "JavaScript" },
                  { value: "curl", label: "curl" },
                ]}
              />
            </div>
            <pre className="rounded-xl bg-well p-4 overflow-x-auto text-[13px] leading-relaxed font-mono">
              {samples[lang]}
            </pre>
          </Panel>

          <Panel>
            <h2 className="font-display text-[1.25rem] leading-snug mb-3">Endpoints</h2>
            <table className="w-full text-[15px]">
              <tbody>
                {ENDPOINTS.map(([m, p, d]) => (
                  <tr key={p} className="border-t border-line first:border-0 align-top">
                    <td className="py-2 pr-3 text-slate text-sm w-14">{m}</td>
                    <td className="py-2 pr-3 font-mono text-[13px] break-all">{p}</td>
                    <td className="py-2 text-slate">{d}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>

        <div className="flex flex-col gap-5">
          <Panel>
            <h2 className="font-display text-[1.25rem] leading-snug mb-1">API keys</h2>
            <p className="text-slate text-[15px] mb-4">
              {settings.data?.require_api_key
                ? "Keys are required. Every app needs one."
                : "Keys are optional right now. Turn on “Require API key” in Settings before sharing wanna.sh on your network."}
            </p>
            <form
              className="flex gap-2"
              onSubmit={async (e) => {
                e.preventDefault();
                const k = await api.post<{ key: string }>("/api/keys", { name });
                setCreated(k.key);
                setName("");
                keys.refresh();
              }}
            >
              <input
                className={inputClass}
                placeholder="What is it for? e.g. Home Assistant"
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-label="Key name"
              />
              <Button type="submit">Create</Button>
            </form>
            {created && (
              <div className="mt-4">
                <Notice>
                  Copy this key now. It won&apos;t be shown again.
                  <div className="mt-2">
                    <CopyField value={created} />
                  </div>
                </Notice>
              </div>
            )}
            <ul className="mt-4 flex flex-col">
              {(keys.data ?? []).map((k) => (
                <li key={k.id} className="flex items-center justify-between gap-3 py-2.5 border-t border-line">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{k.name}</div>
                    <div className="text-[13px] text-slate">
                      <span className="font-mono">{k.prefix}…</span>, {k.last_used_at ? `used ${ago(k.last_used_at)}` : "never used"}
                    </div>
                  </div>
                  <button
                    className="text-sm text-danger underline"
                    onClick={() => confirm(`Revoke "${k.name}"? Apps using it will stop working.`) && api.del(`/api/keys/${k.id}`).then(keys.refresh)}
                  >
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </>
  );
}

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Field label="">
      <div className="flex gap-2">
        <input readOnly value={value} className={`${inputClass} font-mono text-[13px]`} onFocus={(e) => e.target.select()} />
        <Button
          tone="quiet"
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </Field>
  );
}
