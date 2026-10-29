"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Check, Search } from "lucide-react";
import Link from "next/link";
import { api, type Budget, type BrowseResult, type Download, type HubResult, type Overview, type Task } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { MODEL_TASKS, TASKS } from "@/lib/tasks";
import { compact, hardwareSummary } from "@/lib/format";
import { DownloadRow, ModelSheet } from "@/components/models";
import { Button, Notice, PageHeader, Segmented, VerdictBadge, inputClass } from "@/components/ui";

type Sort = "popular" | "trending" | "newest" | "liked";
const SORTS: { value: Sort; label: string }[] = [
  { value: "popular", label: "Most downloaded" },
  { value: "trending", label: "Popular this week" },
  { value: "newest", label: "Newest" },
  { value: "liked", label: "Most liked" },
];
const PAGE = 24;

export default function DiscoverPage() {
  return (
    <Suspense>
      <Discover />
    </Suspense>
  );
}

function Discover() {
  const params = useSearchParams();
  const [task, setTask] = useState<Task | "all">((params.get("task") as Task) || "all");
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [sort, setSort] = useState<Sort>("popular");
  const [fitsOnly, setFitsOnly] = useState(true);
  const [open, setOpen] = useState<string | null>(null);

  const downloads = usePoll<Download[]>("/api/downloads", 1500);
  const active = (downloads.data ?? []).filter((d) => d.status !== "cancelled");

  return (
    <>
      <PageHeader
        title="Get models"
        intro="Every model wanna.sh can run, rated for this computer. Downloads run privately here and keep working offline."
      />

      {active.length > 0 && (
        <section aria-label="Downloads" className="mb-8 flex flex-col gap-2">
          {active
            .filter((d) => d.status !== "done")
            .map((d) => (
              <DownloadRow key={d.id} d={d} onCancel={() => api.del(`/api/downloads/${d.id}`).then(downloads.refresh)} />
            ))}
          {active
            .filter((d) => d.status === "done")
            .map((d) => (
              <p key={d.id} className="flex items-center gap-2 text-[15px]">
                <Check size={16} className="text-ok" aria-hidden />
                <span>{d.title} is ready.</span>
                <Link href={TASKS[d.task].href} className="underline underline-offset-2">
                  Start using it
                </Link>
              </p>
            ))}
          {active.some((d) => d.status !== "downloading" && d.status !== "queued") && (
            <button
              className="self-start text-[14px] text-slate underline underline-offset-2"
              onClick={() => api.post("/api/downloads/clear").then(downloads.refresh)}
            >
              Clear finished
            </button>
          )}
        </section>
      )}

      <form
        className="flex gap-2 mb-4"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(query.trim());
        }}
      >
        <div className="relative flex-1">
          <Search size={18} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate" aria-hidden />
          <input
            className={`${inputClass} pl-10 h-11`}
            placeholder="Search by name, for example “qwen”, “flux” or “whisper”"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search models"
          />
        </div>
        <Button type="submit" className="h-11">
          Search
        </Button>
      </form>

      <div className="flex flex-col gap-3 mb-8">
        <Segmented
          label="What the model does"
          value={task}
          onChange={setTask}
          options={[
            { value: "all", label: "Everything" },
            ...MODEL_TASKS.map((t) => ({ value: t, label: TASKS[t].label })),
          ]}
        />
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          {task !== "all" && (
            <label className="flex items-center gap-2 text-[15px]">
              <span className="text-slate">Sort by</span>
              <select
                className={`${inputClass} h-9 py-0 w-auto`}
                value={sort}
                onChange={(e) => setSort(e.target.value as Sort)}
              >
                {SORTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex items-center gap-2 text-[15px]">
            <input
              type="checkbox"
              checked={fitsOnly}
              onChange={(e) => setFitsOnly(e.target.checked)}
              className="size-4 accent-[var(--accent)]"
            />
            Only show models that run well here
          </label>
          {submitted && (
            <button
              className="text-[15px] text-accent underline"
              onClick={() => {
                setSubmitted("");
                setQuery("");
              }}
            >
              Clear search for “{submitted}”
            </button>
          )}
        </div>
      </div>

      {task === "all" ? (
        <OverviewView query={submitted} fitsOnly={fitsOnly} onOpen={setOpen} onSeeAll={setTask} />
      ) : (
        <TaskList
          key={`${task}|${submitted}|${sort}|${fitsOnly}`}
          task={task}
          query={submitted}
          sort={sort}
          fitsOnly={fitsOnly}
          onOpen={setOpen}
        />
      )}

      {open && <ModelSheet repoId={open} onClose={() => setOpen(null)} onInstalled={downloads.refresh} />}
    </>
  );
}

/** One sentence about this computer, plus what the ratings mean. */
function YourComputer({ budget }: { budget: Budget | undefined }) {
  const [open, setOpen] = useState(false);
  if (!budget) return null;
  return (
    <section className="mb-7 text-[15px]">
      <p className="text-slate">
        Rated for this computer: {hardwareSummary(budget.gpus, budget.ram, budget.wsl)}.
        {budget.gpus.length === 0 && " Small models work best."}{" "}
        <button className="underline underline-offset-2 hover:text-ink" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide what the ratings mean" : "What do the ratings mean?"}
        </button>
      </p>
      {open && (
      <dl className="grid sm:grid-cols-2 gap-x-8 gap-y-2 mt-4 text-[14px] rounded-2xl bg-paper border border-line p-5">
        <Legend level="great" label="Runs great here" text="Fits on one graphics card. Fastest." />
        {budget.gpus.length > 1 && (
          <Legend level="good" label="Runs well here" text="Shares the work between your graphics cards." />
        )}
        <Legend level="slow" label="Runs, but slowly" text="Too big for your graphics cards, so it leans on the processor." />
        <Legend level="no" label="Too big for this computer" text="Won't run here. Hidden while the filter is on." />
      </dl>
      )}
    </section>
  );
}

function Legend({ level, label, text }: { level: "great" | "good" | "slow" | "no"; label: string; text: string }) {
  return (
    <div className="flex gap-3">
      <dt className="shrink-0 min-w-[150px]">
        <VerdictBadge verdict={{ level, label, detail: "", need: null }} />
      </dt>
      <dd className="text-slate">{text}</dd>
    </div>
  );
}

function OverviewView({
  query,
  fitsOnly,
  onOpen,
  onSeeAll,
}: {
  query: string;
  fitsOnly: boolean;
  onOpen: (id: string) => void;
  onSeeAll: (t: Task) => void;
}) {
  const { data, error } = usePoll<Overview>(`/api/hub/overview?per_task=4&q=${encodeURIComponent(query)}`);
  return (
    <>
      <YourComputer budget={data?.budget} />
      {error && <Notice tone="error">{error}</Notice>}
      {!data && !error && <p className="text-slate">Finding the best models for this computer…</p>}
      {data?.sections.map((s) => (
        <section key={s.task} className="mb-10">
          <div className="flex flex-wrap items-baseline justify-between gap-3 mb-3">
            <h2 className="font-display text-[1.25rem] leading-snug flex items-center gap-2">
              {TASKS[s.task].label}
            </h2>
            <button className="text-[15px] text-accent underline" onClick={() => onSeeAll(s.task)}>
              See all {TASKS[s.task].noun}s
            </button>
          </div>
          {s.results.length === 0 ? (
            <p className="text-slate text-[15px]">
              {query ? `Nothing called “${query}” runs well here.` : "Nothing found right now."}
            </p>
          ) : (
            <Grid results={s.results} onOpen={onOpen} />
          )}
        </section>
      ))}
      {!fitsOnly && data && (
        <p className="text-slate text-[15px]">
          This overview always shows models that run well here. Pick a category to see bigger ones too.
        </p>
      )}
    </>
  );
}

function TaskList({
  task,
  query,
  sort,
  fitsOnly,
  onOpen,
}: {
  task: Task;
  query: string;
  sort: Sort;
  fitsOnly: boolean;
  onOpen: (id: string) => void;
}) {
  const [results, setResults] = useState<HubResult[]>([]);
  const [budget, setBudget] = useState<Budget>();
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    let alive = true;
    const qs = new URLSearchParams({
      task,
      q: query,
      sort,
      fits: String(fitsOnly),
      limit: String(PAGE),
      offset: String(offset),
    });
    api
      .get<BrowseResult>(`/api/hub/browse?${qs}`)
      .then((r) => {
        if (!alive) return;
        setResults((prev) => (offset === 0 ? r.results : [...prev, ...r.results]));
        setBudget(r.budget);
        setHasMore(r.has_more && r.results.length > 0);
      })
      .catch((e) => alive && setError((e as Error).message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [task, query, sort, fitsOnly, offset]);

  return (
    <>
      <YourComputer budget={budget} />
      {error && <Notice tone="error">{error}</Notice>}
      {!loading && !error && results.length === 0 && (
        <p className="text-[15px]">
          {fitsOnly
            ? "Nothing here runs well on this computer. Turn off “Only show models that run well here” to see bigger models."
            : "No models found. Try a shorter search."}
        </p>
      )}
      <Grid results={results} onOpen={onOpen} />
      <div className="mt-6">
        {loading ? (
          <p className="text-slate">Checking which models run well here…</p>
        ) : (
          hasMore && (
            <Button
              tone="quiet"
              onClick={() => {
                setLoading(true);
                setOffset((o) => o + PAGE);
              }}
            >
              Show more
            </Button>
          )
        )}
      </div>
    </>
  );
}

function Grid({ results, onOpen }: { results: HubResult[]; onOpen: (id: string) => void }) {
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {results.map((r) => (
        <li key={r.repo_id}>
          <button
            onClick={() => onOpen(r.repo_id)}
            className="w-full h-full text-left rounded-2xl bg-paper border border-line p-4 hover:border-accent transition-colors flex flex-col"
          >
            <div className="flex items-center gap-2 text-[13px] text-slate">
              {TASKS[r.task]?.label}
              <span className="ml-auto flex gap-3">
                {r.installed && <span className="text-ok font-medium">Installed</span>}
              </span>
            </div>
            <div className="font-display text-[1.1rem] leading-snug mt-1.5 break-words">{r.title}</div>
            <p className="text-[14px] text-slate mt-0.5 break-words">
              {r.why ?? `By ${r.author}. Downloaded ${compact(r.downloads)} times.`}
            </p>
            <div className="mt-auto pt-3">
              <VerdictBadge verdict={r.verdict} detail />
              {(r.gated || r.vision || r.needs_image) && (
                <p className="text-[13px] text-slate mt-1">
                  {[
                    r.vision && "Can look at pictures.",
                    r.needs_image && "Needs a starting picture.",
                    r.gated && "Needs a free Hugging Face sign-off first.",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                </p>
              )}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}
