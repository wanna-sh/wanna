"use client";

import { useState } from "react";
import Link from "next/link";
import { BookOpen, Check, ChevronDown, ChevronRight } from "lucide-react";
import type { KnowledgeLibrary, KnowledgeResult } from "@/lib/api";
import { chipClass, useDismiss } from "@/components/studio";

/** "Knowledge  Work docs ▾": choose which libraries a chat (or project) searches. */
export function KnowledgeMenu({
  libraries,
  value,
  onChange,
  ready,
}: {
  libraries: KnowledgeLibrary[];
  value: string[];
  onChange: (ids: string[]) => void;
  /** False until a search model is installed. */
  ready: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const chosen = libraries.filter((l) => value.includes(l.id));
  const label = chosen.length === 0 ? "Off" : chosen.length === 1 ? chosen[0].name : `${chosen.length} libraries`;
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={`Knowledge: ${label}`}
        className={`${chipClass} ${chosen.length ? "bg-well border-slate/50" : ""}`}
      >
        <BookOpen size={15} aria-hidden />
        <span className="text-slate">Knowledge</span>
        <span className="max-w-[160px] truncate">{label}</span>
        <ChevronDown size={14} className="text-slate" aria-hidden />
      </button>
      {open && (
        <div className="absolute bottom-full mb-2 left-0 z-30 w-[300px] rounded-xl border border-line bg-paper p-1 shadow-[0_12px_40px_rgba(0,0,0,0.35)]">
          <p className="px-2.5 pt-2 pb-1.5 text-[13px] text-slate">
            Answers use passages from the libraries you tick, and say where each fact came from.
          </p>
          {!ready ? (
            <Link href="/knowledge/" className="block rounded-lg px-2.5 py-2 text-[14px] underline underline-offset-2 hover:bg-well">
              Set up document search first
            </Link>
          ) : libraries.length === 0 ? (
            <Link href="/knowledge/" className="block rounded-lg px-2.5 py-2 text-[14px] underline underline-offset-2 hover:bg-well">
              Create your first library
            </Link>
          ) : (
            <ul role="group" aria-label="Libraries">
              {libraries.map((l) => (
                <li key={l.id}>
                  <button
                    type="button"
                    role="menuitemcheckbox"
                    aria-checked={value.includes(l.id)}
                    onClick={() => toggle(l.id)}
                    className="w-full flex items-start gap-2 rounded-lg px-2.5 py-2 text-left text-[14px] hover:bg-well"
                  >
                    <Check size={15} className={`mt-0.5 shrink-0 ${value.includes(l.id) ? "" : "invisible"}`} aria-hidden />
                    <span className="min-w-0">
                      <span className="block truncate">{l.name}</span>
                      <span className="block text-[13px] text-slate">
                        {l.documents} document{l.documents === 1 ? "" : "s"}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {ready && libraries.length > 0 && (
            <Link href="/knowledge/" className="block rounded-lg px-2.5 py-2 text-[13px] text-slate hover:text-ink hover:bg-well">
              Manage libraries
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

/** Where a passage comes from: "report.pdf, page 4, Results". */
export function sourceLabel(r: KnowledgeResult): string {
  return [r.document, r.page ? `page ${r.page}` : null, r.heading || null].filter(Boolean).join(", ");
}

/** The passages an answer was given, numbered like the [1] citations in the answer. Cited ones come first. */
export function Sources({ sources, answer }: { sources: KnowledgeResult[]; answer: string }) {
  const [open, setOpen] = useState<number | null>(null);
  const cited = new Set([...answer.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])));
  const numbered = sources.map((s, i) => ({ s, n: i + 1 }));
  const shown = [...numbered.filter((x) => cited.has(x.n)), ...numbered.filter((x) => !cited.has(x.n))];
  return (
    <div className="mt-3 rounded-xl border border-line">
      <p className="px-3.5 pt-2.5 pb-1 text-[13px] text-slate">
        {cited.size ? "Sources" : "Searched these passages; none were cited"}
      </p>
      <ol className="pb-1.5">
        {shown.map(({ s, n }) => (
          <li key={n}>
            <button
              type="button"
              onClick={() => setOpen(open === n ? null : n)}
              aria-expanded={open === n}
              className={`w-full flex items-start gap-2 px-3.5 py-1.5 text-left text-[13.5px] hover:bg-well/60 ${cited.has(n) ? "" : "text-slate"}`}
            >
              <span className="tabular-nums shrink-0 font-medium">[{n}]</span>
              <span className="min-w-0 flex-1 truncate">{sourceLabel(s)}</span>
              <ChevronRight size={14} className={`mt-0.5 shrink-0 transition-transform ${open === n ? "rotate-90" : ""}`} aria-hidden />
            </button>
            {open === n && (
              <blockquote className="mx-3.5 mb-2 mt-0.5 border-l-2 border-line pl-3 text-[13.5px] text-slate whitespace-pre-wrap max-h-64 overflow-y-auto">
                {s.text}
              </blockquote>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
