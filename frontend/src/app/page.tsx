"use client";

import Link from "next/link";
import { useState, useSyncExternalStore, type ReactNode } from "react";
import { ArrowRight, Cpu, Lock, WifiOff } from "lucide-react";
import { API_BASE, type Task } from "@/lib/api";
import { useModels, useSystem } from "@/lib/hooks";
import { TASKS, TASK_ORDER } from "@/lib/tasks";
import { gpuName, hardwareSummary, mem } from "@/lib/format";
import { GitHubMark, REPO_URL } from "@/components/github";

const ART: ("home" | Task)[] = ["home", ...TASK_ORDER];
// The landing page lays out its own width so the hero can run edge to edge.
const WRAP = "mx-auto w-full max-w-[1120px] px-4 sm:px-8 lg:px-12";

// What each tool is for, in a sentence people can picture.
const PITCH: Record<Task, string> = {
  chat: "Ask questions, draft emails, summarise documents and get help with code, with assistants like Qwen, Llama and Gemma.",
  image: "Describe a picture and watch it appear. Start from your own photo to restyle it.",
  video: "Turn a description, or a starting picture, into a short clip.",
  speech: "Paste any text and hear it read aloud in a natural voice, then save the recording.",
  transcribe: "Upload a recording or use your microphone. Get a transcript with timestamps, or subtitles.",
  sound: "Describe a mood, genre or instruments and get an original piece of music.",
  embed: "Ask questions about your own documents and get answers that cite them.",
};

const WHY: { icon: ReactNode; title: string; body: ReactNode }[] = [
  {
    icon: <Lock size={22} strokeWidth={1.75} aria-hidden />,
    title: "Private by design",
    body: "Your prompts, chats and creations stay on this computer. The internet is only used to find and download models.",
  },
  {
    icon: <WifiOff size={22} strokeWidth={1.75} aria-hidden />,
    title: "Works offline",
    body: "Once a model is downloaded it keeps working without a connection, on a plane or behind a firewall.",
  },
  {
    icon: <GitHubMark size={22} />,
    title: "Free and open source",
    body: (
      <>
        MIT licensed and{" "}
        <a href={REPO_URL} className="underline underline-offset-2 hover:text-ink" target="_blank" rel="noreferrer">
          developed in the open on GitHub
        </a>
        . No accounts, no subscriptions and no per-use limits.
      </>
    ),
  },
  {
    icon: <Cpu size={22} strokeWidth={1.75} aria-hidden />,
    title: "Uses all your hardware",
    body: "Models are placed on the right graphics card automatically, and big ones are shared across several cards.",
  },
];

const STEPS = [
  {
    title: "Pick a model",
    body: "Browse thousands of models from Hugging Face. Each one is rated for your computer, so you know it will run before you download.",
  },
  {
    title: "It downloads once",
    body: "wanna.sh fetches only the files it needs and sets everything up. No terminals, no installers, no configuration.",
  },
  {
    title: "Say what you want",
    body: "Type a request, choose a few simple options and press Create. The model starts by itself the first time you use it.",
  },
];

export default function Home() {
  const { data: models } = useModels(undefined, 8000);
  const { data: sys } = useSystem(10000);
  const [hover, setHover] = useState<Task | null>(null);
  const origin = useSyncExternalStore(
    () => () => {},
    () => API_BASE || window.location.origin,
    () => "http://localhost:7860",
  );

  const count = (t: Task) => (models ?? []).filter((m) => m.task === t).length;
  const installed = (models ?? []).length;
  const shown = hover ?? "home";
  const cards = (sys?.gpus ?? []).map((g) => `${gpuName(g.name)} (${mem(g.memory_total)})`);

  return (
    <>
      {/* Hero: the painting fills the top of the page and follows the verb you point at. */}
      <section
        aria-labelledby="wanna"
        className="relative isolate overflow-hidden flex items-end min-h-[min(94vh,900px)] text-white"
      >
        {ART.map((a) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={a}
            src={`/art/${a}.webp`}
            alt=""
            className="art-fade absolute inset-0 -z-10 size-full object-cover"
            style={{ opacity: shown === a ? 1 : 0 }}
          />
        ))}
        {/* Darken the left and the bottom so white text stays readable on any painting, in either theme. */}
        <div className="absolute inset-0 -z-10 bg-gradient-to-r from-black/80 via-black/45 to-black/5" aria-hidden />
        <div className="absolute inset-x-0 bottom-0 h-2/3 -z-10 bg-gradient-to-t from-black/75 to-transparent" aria-hidden />

        <div className={`${WRAP} pt-20 lg:pt-24 pb-14 lg:pb-20`}>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-full border border-white/25 bg-white/10 backdrop-blur-md px-3.5 h-8 text-[13px] hover:bg-white/20 transition-colors"
          >
            <GitHubMark size={14} />
            Free and open source, MIT licensed
          </a>

          <h1 id="wanna" className="mt-6 font-medium tracking-[-0.03em] text-white/65 text-[clamp(2.2rem,4.4vw,3.6rem)] leading-none">
            I wanna
          </h1>
          <ul className="mt-2">
            {TASK_ORDER.map((t) => {
              const active = hover === t;
              const dimmed = hover !== null && !active;
              return (
                <li key={t}>
                  <Link
                    href={TASKS[t].href}
                    onMouseEnter={() => setHover(t)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(t)}
                    onBlur={() => setHover(null)}
                    className={`inline-block font-medium tracking-[-0.03em] text-[clamp(2.2rem,4.4vw,3.6rem)] leading-[1.12] transition-opacity duration-300 focus-visible:outline-white ${
                      dimmed ? "opacity-35" : "opacity-100"
                    }`}
                  >
                    {TASKS[t].verb}
                    {active && <span className="wanna-caret" aria-hidden />}
                  </Link>
                </li>
              );
            })}
          </ul>

          <p className="mt-7 text-[18px] text-white/80 max-w-[54ch]">
            wanna.sh runs AI on your own computer. Chat, pictures, video, voices, transcription and music in one
            app, private and working offline once a model is downloaded.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link
              href={installed ? "/chat/" : "/discover/"}
              className="inline-flex items-center gap-2 rounded-full bg-white text-black px-5 h-11 text-[15px] font-medium hover:opacity-90 transition-opacity"
            >
              {installed ? "Start chatting" : "Get started"} <ArrowRight size={16} aria-hidden />
            </Link>
            <a
              href={REPO_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-full border border-white/30 bg-black/20 backdrop-blur-md px-5 h-11 text-[15px] hover:bg-white/10 transition-colors"
            >
              <GitHubMark size={16} /> View on GitHub
            </a>
          </div>
          {cards.length > 0 && (
            <p className="mt-6 text-[14px] text-white/65">
              Ready on this computer:{" "}
              {hardwareSummary(
                (sys?.gpus ?? []).map((g) => ({ name: g.name, memory: g.memory_total })),
                sys?.ram_total ?? 0,
                sys?.wsl,
              )}
              .
            </p>
          )}
        </div>
      </section>

      <div className={WRAP}>
        {/* What you can do */}
        <section className="py-16" aria-labelledby="tools">
          <div className="max-w-[60ch] mb-9">
            <h2 id="tools" className="font-display text-[1.9rem] leading-tight">
              Six AI tools, one app
            </h2>
            <p className="text-slate mt-2">
              Instead of a separate app for each kind of AI, wanna.sh brings popular open models together, with the
              same simple controls everywhere.
            </p>
          </div>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {TASK_ORDER.map((t) => {
              const n = count(t);
              return (
                <li key={t}>
                  <Link
                    href={TASKS[t].href}
                    className="group block h-full rounded-2xl border border-line bg-paper overflow-hidden hover:border-slate/50 transition-colors"
                  >
                    <div className="aspect-[16/8] overflow-hidden">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={`/art/${t}.webp`}
                        alt=""
                        loading="lazy"
                        className="size-full object-cover group-hover:scale-[1.03] transition-transform duration-500"
                      />
                    </div>
                    <div className="p-5">
                      <h3 className="font-display text-[1.1rem]">{TASKS[t].label}</h3>
                      <p className="text-[15px] text-slate mt-1.5">{PITCH[t]}</p>
                      <p className="text-[14px] mt-4 inline-flex items-center gap-1.5">
                        {models === null ? "" : n ? `Open (${n} model${n > 1 ? "s" : ""} ready)` : "Choose a model to start"}
                        <ArrowRight size={14} className="group-hover:translate-x-0.5 transition-transform" aria-hidden />
                      </p>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>

        {/* Why local */}
        <section className="py-16 border-t border-line" aria-labelledby="why">
          <h2 id="why" className="font-display text-[1.9rem] leading-tight max-w-[60ch] mb-9">
            Why run AI on your own computer?
          </h2>
          <ul className="grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
            {WHY.map(({ icon, title, body }) => (
              <li key={title}>
                {icon}
                <h3 className="font-medium mt-3">{title}</h3>
                <p className="text-[15px] text-slate mt-1.5">{body}</p>
              </li>
            ))}
          </ul>
        </section>

        {/* How it works: a genuine sequence, so it's numbered */}
        <section className="py-16 border-t border-line" aria-labelledby="how">
          <h2 id="how" className="font-display text-[1.9rem] leading-tight mb-9">
            How it works
          </h2>
          <ol className="grid gap-6 lg:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="rounded-2xl border border-line p-6">
                <span className="inline-grid place-items-center size-8 rounded-full bg-well text-[14px] font-medium" aria-hidden>
                  {i + 1}
                </span>
                <h3 className="font-medium mt-4">{s.title}</h3>
                <p className="text-[15px] text-slate mt-1.5">{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* Developers */}
        <section
          className="py-16 border-t border-line grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] items-start"
          aria-labelledby="dev"
        >
          <div className="max-w-[52ch]">
            <h2 id="dev" className="font-display text-[1.9rem] leading-tight">
              Built for your other apps too
            </h2>
            <p className="text-slate mt-2">
              wanna.sh speaks the OpenAI API. Point any app, script or plugin that supports a custom OpenAI address
              at wanna.sh, and it uses your own models for chat, pictures, speech and transcription.
            </p>
            <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-[15px]">
              <Link href="/developers/" className="inline-flex items-center gap-1.5 underline underline-offset-4">
                Connect an app <ArrowRight size={15} aria-hidden />
              </Link>
              <a href={REPO_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 underline underline-offset-4">
                <GitHubMark size={15} /> Read the source
              </a>
            </div>
          </div>
          <pre className="rounded-2xl bg-paper border border-line p-5 overflow-x-auto text-[13px] leading-relaxed font-mono">
            {`from openai import OpenAI

client = OpenAI(
    base_url="${origin}/v1",
    api_key="not-needed",
)

reply = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(reply.choices[0].message.content)`}
          </pre>
        </section>

        {/* Closing call to action */}
        <section className="mt-4 rounded-2xl overflow-hidden relative isolate text-white" aria-labelledby="cta">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/art/sound.webp" alt="" className="absolute inset-0 -z-10 size-full object-cover" />
          <div className="absolute inset-0 -z-10 bg-gradient-to-r from-black/80 to-black/30" aria-hidden />
          <div className="px-6 sm:px-10 py-16">
            <h2 id="cta" className="font-display text-[1.9rem] leading-tight max-w-[24ch]">
              Your computer is more capable than you think.
            </h2>
            <p className="mt-2 text-white/80 max-w-[52ch]">
              Find a model that suits it, download it once, and start making things.
            </p>
            <Link
              href="/discover/"
              className="mt-6 inline-flex items-center gap-2 rounded-full bg-white text-black px-5 h-11 text-[15px] font-medium hover:opacity-90 transition-opacity"
            >
              Find a model <ArrowRight size={16} aria-hidden />
            </Link>
          </div>
        </section>
      </div>

      <Footer />
    </>
  );
}

const FOOTER_LINKS: { title: string; links: { label: string; href: string; external?: boolean }[] }[] = [
  {
    title: "Make",
    links: TASK_ORDER.map((t) => ({ label: TASKS[t].label, href: TASKS[t].href })),
  },
  {
    title: "Library",
    links: [
      { label: "Get models", href: "/discover/" },
      { label: "My models", href: "/models/" },
      { label: "Gallery", href: "/gallery/" },
      { label: "Settings", href: "/settings/" },
    ],
  },
  {
    title: "Developers",
    links: [
      { label: "API & apps", href: "/developers/" },
      { label: "API reference", href: "/docs", external: true },
      { label: "Source code", href: REPO_URL, external: true },
      { label: "Report a problem", href: `${REPO_URL}/issues`, external: true },
    ],
  },
];

function Footer() {
  return (
    <footer className="mt-20 border-t border-line">
      <div className={`${WRAP} py-14 grid gap-10 sm:grid-cols-2 lg:grid-cols-[1.5fr_1fr_1fr_1fr]`}>
        <div className="max-w-[34ch]">
          <Link href="/" className="font-display text-[1.25rem]">
            wanna<span className="text-slate">.sh</span>
          </Link>
          <p className="text-[14px] text-slate mt-2">
            Every kind of AI in one app, running privately on your own computer.
          </p>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="wanna.sh on GitHub"
            className="mt-5 inline-grid place-items-center size-10 rounded-full border border-line hover:bg-well transition-colors"
          >
            <GitHubMark size={18} />
          </a>
        </div>
        {FOOTER_LINKS.map((col) => (
          <nav key={col.title} aria-label={col.title}>
            <h2 className="text-[13px] text-slate mb-3">{col.title}</h2>
            <ul className="flex flex-col gap-2 text-[14px]">
              {col.links.map((l) => (
                <li key={l.label}>
                  {l.external ? (
                    <a href={l.href.startsWith("/") ? `${API_BASE}${l.href}` : l.href} target="_blank" rel="noreferrer" className="hover:underline underline-offset-2">
                      {l.label}
                    </a>
                  ) : (
                    <Link href={l.href} className="hover:underline underline-offset-2">
                      {l.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div className="border-t border-line">
        <div className={`${WRAP} py-6 flex flex-wrap items-center justify-between gap-4 text-[13px] text-slate`}>
          <p>
            © 2026{" "}
            <a href="https://wannaverse.com" target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-ink">
              Wannaverse
            </a>
            . Open source under the{" "}
            <a href={`${REPO_URL}/blob/main/LICENSE`} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-ink">
              MIT licence
            </a>
            .
          </p>
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 hover:text-ink">
            <GitHubMark size={15} /> wanna-sh/wanna
          </a>
        </div>
      </div>
    </footer>
  );
}
