"use client";

import { useEffect, useState, type KeyboardEvent } from "react";
import { CircleAlert, Plus, ShieldCheck, Wrench } from "lucide-react";
import {
  api,
  type CustomTool,
  type JsonSchema,
  type SystemCheckItem,
  type ToolList,
  type ToolRun,
} from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { Button, Field, Notice, PageHeader, Panel, inputClass } from "@/components/ui";

const TRUST_WARNING =
  "Trusted tools run directly on this computer, not in the sandbox: they can read and change your files, reach " +
  "your network and do anything you can. Only trust a tool you wrote yourself, or whose code you have read and " +
  "understood. Editing it later takes the trust away.";

export default function ToolsPage() {
  const { data, error, refresh } = usePoll<ToolList>("/api/tools");
  const { data: checks } = usePoll<SystemCheckItem[]>("/api/system/check");
  const [editing, setEditing] = useState<string | null>(null); // a tool's name, "" for a new one
  const docker = checks?.find((c) => c.id === "docker");
  const sandboxed = (data?.tools ?? []).filter((t) => !t.trusted && t.enabled && !t.error);

  return (
    <div className="max-w-[920px]">
      <PageHeader
        title="Tools"
        intro={
          <>
            Python functions the AI can use, in Chat, in Code and from apps through the API. Each tool is a file in{" "}
            <span className="font-mono text-[14px] break-all">{data?.folder ?? "your tools folder"}</span>, so you can
            also write them in your own editor or share them.
          </>
        }
      >
        <Button onClick={() => setEditing("")}>
          <Plus size={16} aria-hidden /> New tool
        </Button>
      </PageHeader>

      {error && <Notice tone="error">{error}</Notice>}
      {docker && docker.status !== "ok" && sandboxed.length > 0 && (
        <div className="mb-6">
          <Notice>
            Tools run in a sandbox, which needs Docker: {docker.detail} Until then, they can only run if you trust
            them to run on this computer.
          </Notice>
        </div>
      )}

      {editing !== null && data && (
        <Editor
          key={editing || "new"}
          name={editing}
          template={data.template}
          onClose={() => setEditing(null)}
          onSaved={(name) => {
            setEditing(name);
            refresh();
          }}
          onDeleted={() => {
            setEditing(null);
            refresh();
          }}
        />
      )}

      {data && data.tools.length === 0 && editing === null && (
        <Panel>
          <p className="text-[15px]">
            No tools yet. A tool is a Python function called <code>run</code>: its docstring tells the AI what it does,
            and its type hints say what to give it. Press <b>New tool</b> to start from an example.
          </p>
        </Panel>
      )}

      {data && data.tools.length > 0 && (
        <ul className="mt-2 rounded-2xl border border-line bg-paper divide-y divide-line">
          {data.tools.map((t) => (
            <ToolRow key={t.name} t={t} active={editing === t.name} onEdit={() => setEditing(t.name)} />
          ))}
        </ul>
      )}

      <HowTo />
    </div>
  );
}

function ToolRow({ t, active, onEdit }: { t: CustomTool; active: boolean; onEdit: () => void }) {
  return (
    <li className={`px-4 sm:px-5 py-3.5 flex flex-wrap items-center gap-x-4 gap-y-2 ${active ? "bg-well/60" : ""}`}>
      <Wrench size={16} className="text-slate shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2">
          <span className="font-mono text-[14px]">{t.name}</span>
          {!t.enabled && <span className="text-[13px] text-slate">Off</span>}
          {t.trusted && (
            <span className="inline-flex items-center gap-1 text-[13px] text-caution">
              <ShieldCheck size={13} aria-hidden /> Runs on this computer
            </span>
          )}
          {t.trust_lost && <span className="text-[13px] text-slate">Changed since you trusted it: back in the sandbox</span>}
        </div>
        {t.error ? (
          <p className="text-[14px] text-danger flex items-start gap-1.5">
            <CircleAlert size={14} className="mt-[3px] shrink-0" aria-hidden /> {t.error}
          </p>
        ) : (
          <p className="text-[14px] text-slate line-clamp-2">{t.description}</p>
        )}
      </div>
      <Button tone="quiet" onClick={onEdit} disabled={active}>
        Edit
      </Button>
    </li>
  );
}

function Editor({
  name,
  template,
  onClose,
  onSaved,
  onDeleted,
}: {
  name: string;
  template: string;
  onClose: () => void;
  onSaved: (name: string) => void;
  onDeleted: () => void;
}) {
  const isNew = name === "";
  const [tool, setTool] = useState<CustomTool | null>(null);
  const [newName, setNewName] = useState(isNew ? "count_words" : name);
  const [source, setSource] = useState(isNew ? template : "");
  const [saved, setSaved] = useState<string | null>(isNew ? "" : null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (isNew) return;
    api
      .get<CustomTool>(`/api/tools/${name}`)
      .then((t) => {
        setTool(t);
        setSource(t.source ?? "");
        setSaved(t.source ?? "");
      })
      .catch((e) => setProblem((e as Error).message));
  }, [name, isNew]);

  const dirty = source !== saved || (!isNew && newName !== name) || isNew;

  const save = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const t = await api.put<CustomTool>(`/api/tools/${newName}`, {
        source,
        old_name: isNew ? null : name,
      });
      setTool(t);
      setSaved(t.source ?? source);
      onSaved(t.name);
    } catch (e) {
      setProblem((e as Error).message);
    }
    setBusy(false);
  };

  const configure = async (patch: { enabled?: boolean; trusted?: boolean }) => {
    if (patch.trusted && !confirm(`${TRUST_WARNING}\n\nTrust ${name} to run on this computer?`)) return;
    try {
      setTool(await api.post<CustomTool>(`/api/tools/${name}/settings`, patch));
      onSaved(name);
    } catch (e) {
      setProblem((e as Error).message);
    }
  };

  // Tab indents (four spaces) instead of leaving the editor.
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Tab" || e.shiftKey) return;
    e.preventDefault();
    const el = e.currentTarget;
    const { selectionStart: a, selectionEnd: b } = el;
    const next = source.slice(0, a) + "    " + source.slice(b);
    setSource(next);
    requestAnimationFrame(() => el.setSelectionRange(a + 4, a + 4));
  };

  return (
    <Panel className="mb-6">
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <div className="flex-1 min-w-[220px]">
          <Field label="Name" hint="What the AI calls it. Lowercase letters, digits and underscores.">
            <input
              className={`${inputClass} font-mono`}
              value={newName}
              onChange={(e) => setNewName(e.target.value.trim())}
              spellCheck={false}
              aria-label="Tool name"
            />
          </Field>
        </div>
        <div className="flex gap-2 pb-6">
          <Button onClick={save} disabled={busy || !dirty || !newName}>
            {isNew ? "Create" : "Save"}
          </Button>
          <Button tone="quiet" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>

      <textarea
        className={`${inputClass} font-mono text-[13px] leading-relaxed min-h-[340px] resize-y`}
        value={source}
        onChange={(e) => setSource(e.target.value)}
        onKeyDown={onKey}
        spellCheck={false}
        aria-label="Tool code"
      />
      {problem && (
        <div className="mt-3">
          <Notice tone="error">{problem}</Notice>
        </div>
      )}
      {tool?.error && !dirty && (
        <div className="mt-3">
          <Notice tone="error">The AI can&apos;t use this tool yet: {tool.error}</Notice>
        </div>
      )}
      {dirty && !isNew && <p className="text-[13px] text-slate mt-2">Unsaved changes.</p>}

      {tool && !isNew && (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <label className="flex items-start gap-3 text-[15px]">
              <input
                type="checkbox"
                checked={tool.enabled}
                onChange={(e) => configure({ enabled: e.target.checked })}
                className="mt-1 size-4 accent-[var(--accent)]"
              />
              <span>
                <span className="font-medium">On</span>
                <span className="block text-[14px] text-slate">The AI can use it in Chat, Code and the API.</span>
              </span>
            </label>
            <label className="flex items-start gap-3 text-[15px]">
              <input
                type="checkbox"
                checked={tool.trusted}
                onChange={(e) => configure({ trusted: e.target.checked })}
                className="mt-1 size-4 accent-[var(--accent)]"
              />
              <span>
                <span className="font-medium">Trust it to run on this computer</span>
                <span className="block text-[14px] text-slate">
                  {tool.trusted
                    ? "It runs directly on this computer, with access to your files and network. In Code, the agent asks before using it."
                    : tool.trust_lost
                      ? "It changed since you trusted it, so it runs in the sandbox again."
                      : "Off: it runs in a sandbox that can reach the internet, but not your files or local network."}
                </span>
              </span>
            </label>
          </div>
          {!!tool.dependencies.length && (
            <p className="text-[14px] text-slate mt-3">
              Packages: {tool.dependencies.join(", ")}. They&apos;re installed the first time it runs.
            </p>
          )}
          {tool.schema && <Seen tool={tool} />}
          {tool.schema && !dirty && <Tester tool={tool} />}
          <div className="mt-6 pt-4 border-t border-line flex flex-wrap items-center gap-3 text-[14px] text-slate">
            <span className="font-mono break-all">{tool.path}</span>
            <button
              className="ml-auto text-danger underline underline-offset-2"
              onClick={async () => {
                if (!confirm(`Delete ${name}? Its file is deleted too.`)) return;
                await api.del(`/api/tools/${name}`);
                onDeleted();
              }}
            >
              Delete tool
            </button>
          </div>
        </>
      )}
    </Panel>
  );
}

/** What the AI is told about the tool. */
function Seen({ tool }: { tool: CustomTool }) {
  const fn = tool.schema!.function;
  const props = Object.entries(fn.parameters.properties);
  return (
    <div className="mt-5 rounded-xl bg-well/60 p-4 text-[14px]">
      <div className="font-medium mb-1">What the AI sees</div>
      <p className="whitespace-pre-wrap">{fn.description}</p>
      {props.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1">
          {props.map(([k, s]) => (
            <li key={k}>
              <span className="font-mono">{k}</span>{" "}
              <span className="text-slate">
                ({typeLabel(s)}
                {fn.parameters.required.includes(k) ? ", required" : ""})
                {s.description ? `: ${s.description}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function typeLabel(s: JsonSchema): string {
  if (s.enum) return `one of ${s.enum.map((v) => JSON.stringify(v)).join(", ")}`;
  if (s.type === "array") return `list${s.items?.type ? ` of ${s.items.type}` : ""}`;
  return s.type ?? "any";
}

/** Run the tool with inputs you choose, the way the AI would. */
function Tester({ tool }: { tool: CustomTool }) {
  const fn = tool.schema!.function;
  const props = Object.entries(fn.parameters.properties);
  const [values, setValues] = useState<Record<string, string>>(() =>
    // Choices are kept as JSON, so text and numbers stay what they are; other inputs as typed.
    Object.fromEntries(
      props.map(([k, s]) => [k, s.default === undefined ? "" : s.enum ? JSON.stringify(s.default) : toText(s.default)]),
    ),
  );
  const [result, setResult] = useState<ToolRun | null>(null);
  const [running, setRunning] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const run = async () => {
    setProblem(null);
    const args: Record<string, unknown> = {};
    for (const [k, s] of props) {
      const v = values[k];
      if (v === "" && !fn.parameters.required.includes(k)) continue;
      try {
        args[k] = s.enum ? JSON.parse(v) : s.type === "string" || !s.type ? v : JSON.parse(v);
      } catch {
        setProblem(`${k} should be ${typeLabel(s)}, written as JSON (for example ${s.type === "array" ? '["a", "b"]' : s.type === "object" ? '{"key": "value"}' : "42"}).`);
        return;
      }
    }
    setRunning(true);
    setResult(null);
    try {
      setResult(await api.post<ToolRun>(`/api/tools/${tool.name}/run`, { arguments: args, test: true }));
    } catch (e) {
      setProblem((e as Error).message);
    }
    setRunning(false);
  };

  return (
    <div className="mt-5">
      <div className="font-medium text-[15px] mb-2">Test it</div>
      <div className="grid gap-3 sm:grid-cols-2">
        {props.map(([k, s]) => (
          <Field key={k} label={k} hint={s.description}>
            {s.enum ? (
              <select
                className={`${inputClass} h-10 py-0`}
                value={values[k]}
                onChange={(e) => setValues({ ...values, [k]: e.target.value })}
              >
                {!fn.parameters.required.includes(k) && <option value="">(leave out)</option>}
                {s.enum.map((v) => (
                  <option key={String(v)} value={JSON.stringify(v)}>
                    {String(v)}
                  </option>
                ))}
              </select>
            ) : s.type === "boolean" ? (
              <select
                className={`${inputClass} h-10 py-0`}
                value={values[k]}
                onChange={(e) => setValues({ ...values, [k]: e.target.value })}
              >
                {!fn.parameters.required.includes(k) && <option value="">(leave out)</option>}
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : (
              <input
                className={`${inputClass} ${s.type === "string" ? "" : "font-mono"}`}
                value={values[k]}
                onChange={(e) => setValues({ ...values, [k]: e.target.value })}
                placeholder={s.type === "string" ? "" : s.type === "array" ? '["a", "b"]' : s.type === "object" ? '{"key": "value"}' : "0"}
              />
            )}
          </Field>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <Button tone="quiet" onClick={run} disabled={running}>
          {running ? "Running…" : "Run"}
        </Button>
        {!tool.enabled && <span className="text-[13px] text-slate">It&apos;s off, but you can still test it.</span>}
      </div>
      {problem && (
        <div className="mt-3">
          <Notice tone="error">{problem}</Notice>
        </div>
      )}
      {result && (
        <div className="mt-3 rounded-xl border border-line p-3 text-[14px]">
          <div className="text-[13px] text-slate mb-1.5">
            {result.ok ? "Returned" : "Failed"}
            {result.where ? ` in ${result.where === "sandbox" ? "the sandbox" : "this computer"}` : ""}, {result.seconds} s.
            {result.ok ? " The AI gets this:" : ""}
          </div>
          <pre className={`whitespace-pre-wrap break-words font-mono text-[13px] ${result.ok ? "" : "text-danger"}`}>
            {result.ok ? result.result || "(nothing)" : result.error}
          </pre>
          {result.printed && (
            <>
              <div className="text-[13px] text-slate mt-2 mb-1">It printed (the AI doesn&apos;t see this):</div>
              <pre className="whitespace-pre-wrap break-words font-mono text-[12.5px] text-slate">{result.printed}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function toText(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v);
}

function HowTo() {
  return (
    <section className="mt-10 text-[15px]">
      <h2 className="font-display text-[1.25rem] leading-snug mb-2">Writing a tool</h2>
      <ul className="list-disc pl-5 flex flex-col gap-1.5 text-slate">
        <li>
          Define <code className="text-ink">run</code>. Its docstring&apos;s first part is what the AI reads to decide when
          to use the tool; describe each input under <code className="text-ink">Args:</code>.
        </li>
        <li>
          Type hints become the inputs: <code className="text-ink">str</code>, <code className="text-ink">int</code>,{" "}
          <code className="text-ink">float</code>, <code className="text-ink">bool</code>,{" "}
          <code className="text-ink">list[str]</code>, <code className="text-ink">dict</code> and{" "}
          <code className="text-ink">Literal[&quot;a&quot;, &quot;b&quot;]</code> for a fixed choice. Inputs with a default
          are optional.
        </li>
        <li>Return text, or anything JSON can hold. What the tool prints is shown to you when testing, not to the AI.</li>
        <li>
          Need a package? Add a <code className="text-ink"># /// script</code> block at the top with{" "}
          <code className="text-ink">dependencies = [&quot;requests&quot;]</code>, as for{" "}
          <code className="text-ink">uv run</code>.
        </li>
        <li>
          Tools run in a sandbox: they can reach the internet, but not your files or local network, and have a minute
          to finish. Trust one you wrote yourself to run directly on this computer.
        </li>
      </ul>
    </section>
  );
}
