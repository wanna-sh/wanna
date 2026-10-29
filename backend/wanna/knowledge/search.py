"""Hybrid search: meaning (embedding similarity) and words (SQLite full-text, BM25), merged by rank.

Meaning finds passages that say the same thing in other words; words find exact names, codes and numbers that
embeddings can blur. Reciprocal rank fusion combines the two lists without having to compare their scores.
"""

from __future__ import annotations

import re

import numpy as np

from .. import db
from . import store
from .embed import embed

CANDIDATES = 50  # from each method, before merging
RRF_K = 60  # the usual constant for reciprocal rank fusion
PER_DOCUMENT = 2  # passages from one document before others get a turn, so results cover more sources
_cache: dict[str, tuple[float, np.ndarray, np.ndarray]] = {}  # library -> (updated_at, passage ids, vectors)


def _vectors(lib: dict) -> tuple[np.ndarray, np.ndarray]:
    hit = _cache.get(lib["id"])
    if hit and hit[0] == lib["updated_at"]:
        return hit[1], hit[2]
    with db.cursor() as c:
        rows = c.execute("SELECT id, embedding FROM kb_chunks WHERE library_id = ? AND embedding IS NOT NULL",
                         (lib["id"],)).fetchall()
    if rows:  # only vectors of the library's usual size, in case a re-index was interrupted
        size = max({len(r[1]) for r in rows}, key=[len(r[1]) for r in rows].count)
        rows = [r for r in rows if len(r[1]) == size]
    ids = np.array([r[0] for r in rows], dtype=np.int64)
    mat = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows]) if rows else np.zeros((0, 1), np.float32)
    _cache[lib["id"]] = (lib["updated_at"], ids, mat)
    return ids, mat


def _fts_query(query: str) -> str | None:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1][:24]
    return " OR ".join(f'"{w}"' for w in words) or None


def words_only(library_ids: list[str]) -> list[dict]:
    """Libraries whose search model was removed: they can only be searched by words until they're read again."""
    libs = [lib for lib in (store.get_library(i) for i in dict.fromkeys(library_ids)) if lib]
    return [lib for lib in libs if lib["embed_model"] and lib["passages"] and db.get_model(lib["embed_model"]) is None]


async def search(query: str, library_ids: list[str], k: int = 6) -> list[dict]:
    libs = [lib for lib in (store.get_library(i) for i in dict.fromkeys(library_ids)) if lib]
    if not query.strip() or not libs:
        return []
    ranked: dict[int, float] = {}
    how: dict[int, set] = {}

    # Meaning: one query vector per search model (libraries normally share one). A removed model is skipped;
    # those libraries are still searched by words below.
    models = {lib["embed_model"] for lib in libs if lib["embed_model"]}
    for model_id in (m for m in models if db.get_model(m) is not None):
        q = (await embed(model_id, [query], "query"))[0]
        scored = []
        for lib in (lib for lib in libs if lib["embed_model"] == model_id):
            ids, mat = _vectors(lib)
            if len(ids) and mat.shape[1] == q.shape[0]:
                sims = mat @ q
                top = np.argsort(-sims)[:CANDIDATES]
                scored += [(int(ids[i]), float(sims[i])) for i in top]
        for rank, (cid, _) in enumerate(sorted(scored, key=lambda x: -x[1])[:CANDIDATES]):
            ranked[cid] = ranked.get(cid, 0) + 1 / (RRF_K + rank)
            how.setdefault(cid, set()).add("meaning")

    # Words.
    fq = _fts_query(query)
    if fq:
        marks = ",".join("?" * len(libs))
        with db.cursor() as c:
            rows = c.execute(
                f"SELECT k.id FROM kb_fts JOIN kb_chunks k ON k.id = kb_fts.rowid"
                f" WHERE kb_fts MATCH ? AND k.library_id IN ({marks}) ORDER BY bm25(kb_fts) LIMIT {CANDIDATES}",
                (fq, *[lib["id"] for lib in libs])).fetchall()
        for rank, (cid,) in enumerate(rows):
            ranked[cid] = ranked.get(cid, 0) + 1 / (RRF_K + rank)
            how.setdefault(cid, set()).add("words")

    order = sorted(ranked, key=lambda cid: -ranked[cid])
    if not order:
        return []
    with db.cursor() as c:
        rows = {r["id"]: dict(r) for r in c.execute(
            f"SELECT k.id, k.document_id, k.library_id, k.idx, k.page, k.heading, k.text, d.name AS document"
            f" FROM kb_chunks k JOIN kb_documents d ON d.id = k.document_id WHERE k.id IN ({','.join('?' * len(order))})",
            order).fetchall()}
    # Identical passages (repeated boilerplate, the same file added twice) are shown once.
    seen_text: set[str] = set()
    unique = []
    for cid in order:
        if cid in rows:
            key = " ".join(rows[cid]["text"].split()).lower()
            if key not in seen_text:
                seen_text.add(key)
                unique.append(cid)
    order = unique
    best, per_doc = [], {}
    for cid in order:  # the best passages, at most PER_DOCUMENT from each document...
        d = rows[cid]["document_id"]
        if per_doc.get(d, 0) < PER_DOCUMENT:
            best.append(cid)
            per_doc[d] = per_doc.get(d, 0) + 1
        if len(best) == k:
            break
    for cid in order:  # ...then fill up from what's left (a library with one document)
        if len(best) == k:
            break
        if cid not in best:
            best.append(cid)
    best.sort(key=lambda cid: -ranked[cid])
    names = {lib["id"]: lib["name"] for lib in libs}
    return [{**rows[cid], "library": names.get(rows[cid]["library_id"]), "score": round(ranked[cid], 5),
             "matched": sorted(how[cid])} for cid in best]


def search_blocking(query: str, library_ids: list[str], k: int = 6, timeout: float = 180) -> list[dict]:
    """search() for code running in a worker thread (such as Code's tools)."""
    import asyncio

    from .index import loop

    if loop() is None:
        raise RuntimeError("Document search isn't running.")
    return asyncio.run_coroutine_threadsafe(search(query, library_ids, k), loop()).result(timeout)


def context_prompt(results: list[dict]) -> str:
    """Instructions plus numbered passages, for the system prompt of a chat that uses knowledge."""
    if not results:
        return ("The user asked you to use their documents, but nothing relevant was found in them for this message. "
                "Say so, then help as best you can, making clear that your answer doesn't come from their documents.")
    lines = ["Answer using the passages below from the user's documents. After each statement that comes from a passage, "
             "cite it with its number in square brackets, like [1] or [2][3]. If the passages don't contain the answer, "
             "say that the documents don't cover it, and only then answer from general knowledge, saying so.", ""]
    for n, r in enumerate(results, 1):
        where = r["document"] + (f", page {r['page']}" if r.get("page") else "") + (f", {r['heading']}" if r["heading"] else "")
        lines += [f"[{n}] {where}", r["text"].strip(), ""]
    return "\n".join(lines).strip()
