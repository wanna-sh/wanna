"""Your own AI for a task: give examples of inputs with the answers you want, and wanna.sh trains something that answers
new ones, tests it on examples it didn't learn from, and runs it from its page, on whole files, from the API and in Chat.

What it trains depends on the examples:

    input        answer              method
    table        a label or number   gradient-boosted trees (scikit-learn's HistGradientBoosting), on the processor
    text         a label             the search model's embeddings + logistic regression
    pictures     a label             the search model's picture embeddings + logistic regression
    text         written text        a chat model trained on the examples (training.create_chat), tested on
                                     examples held back from it

With no answers yet, a chat model can draft them (draft()) for the person to check. A trained task can also be a tool
the AI uses in Chat and Code (tool_schemas() and run_tool(), through usertools).

Each task is a folder in ~/.wanna/tasks/<id>: task.json (what it is), examples.jsonl (one {"input", "answer"} per line;
the answer is null until someone, or a chat model, gives one), pictures/, model.joblib (what it learned) and
report.json (how well it did on examples it hadn't seen).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import math
import re
import shutil
import time
import uuid
from pathlib import Path

from .config import HOME

log = logging.getLogger("wanna.tasks")

TASKS_DIR = HOME / "tasks"
MAX_EXAMPLES = 200_000
MIN_PER_LABEL = 2
CV_BELOW = 2000  # fewer examples than this: every one is tested once, by 5-fold cross-validation
ANSWER_NAMES = ("answer", "label", "labels", "class", "category", "target", "output", "outcome", "result", "y",
                "is_fraud", "fraud", "response", "reply", "completion")
INPUT_NAMES = ("input", "text", "prompt", "question", "content", "message", "body")
PICTURE = re.compile(r"\.(png|jpe?g|webp|bmp|gif)$", re.I)

_running: dict[str, asyncio.Task] = {}


class TaskError(Exception):
    """A problem to show the person, with what to do about it."""


# --- storage ---------------------------------------------------------------------------------------------------------

def _folder(tid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", tid or ""):
        raise TaskError("There's no task with that id.")
    return TASKS_DIR / tid


def _read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default


def _write(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def examples(tid: str) -> list[dict]:
    p = _folder(tid) / "examples.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _save_examples(tid: str, rows: list[dict]) -> None:
    p = _folder(tid) / "examples.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def get(tid: str) -> dict:
    task = _read(_folder(tid) / "task.json")
    if not task:
        raise TaskError("There's no task with that id.")
    rows = examples(tid)
    answered = [r for r in rows if r.get("answer") not in (None, "")]
    counts: dict[str, int] = {}
    if task["answer_kind"] == "label":
        for r in answered:
            counts[str(r["answer"])] = counts.get(str(r["answer"]), 0) + 1
    if task.get("status", {}).get("stage") in ("training", "drafting") and tid not in _running:
        task["status"] = {"stage": "interrupted", "message": "Stopped when wanna.sh closed. Start it again."}
    trained = (_folder(tid) / "model.joblib").exists() or bool(task.get("chat_model") and _chat_model(task))
    return {**task, "id": tid, "examples": len(rows), "answered": len(answered), "label_counts": counts,
            "drafted": sum(1 for r in rows if r.get("drafted")), "labels": _labels(task, answered),
            "report": _read(_folder(tid) / "report.json") or None, "tool": tool_name(tid, task),
            "ready": trained and task.get("status", {}).get("stage") == "done"}


def _labels(task: dict, answered: list[dict]) -> list[str]:
    """The answers a label task can give: the ones given so far, and any listed ahead of time."""
    if task["answer_kind"] != "label":
        return []
    out = list(task.get("labels") or [])
    for r in answered:
        if str(r["answer"]) not in out:
            out.append(str(r["answer"]))
    return out


def _chat_model(task: dict) -> dict | None:
    from . import db

    return db.get_model(task["chat_model"]) if task.get("chat_model") else None


def list_tasks() -> list[dict]:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in TASKS_DIR.iterdir():
        if p.is_dir() and (p / "task.json").exists():
            try:
                out.append(get(p.name))
            except TaskError:
                continue
    return sorted(out, key=lambda t: -t["created"])


def delete(tid: str) -> None:
    if tid in _running:
        _running[tid].cancel()
    shutil.rmtree(_folder(tid), ignore_errors=True)


def _status(tid: str, **status) -> None:
    p = _folder(tid) / "task.json"
    task = _read(p)
    task["status"] = {**status, "updated": time.time()}
    _write(p, task)


# --- reading examples ------------------------------------------------------------------------------------------------

def _number(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip().replace(",", "").replace("£", "").replace("$", "").replace("€", "").rstrip("%")
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def read_table(name: str, data: bytes) -> list[dict]:
    """Rows of a CSV, TSV, JSON list or JSONL file, as {column: value}."""
    text = data.decode("utf-8-sig", errors="replace")
    low = name.lower()
    try:
        if low.endswith(".jsonl"):
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        elif low.endswith(".json"):
            rows = json.loads(text)
            rows = rows if isinstance(rows, list) else [rows]
        else:
            dialect = "excel-tab" if low.endswith(".tsv") or text.count("\t") > text.count(",") else "excel"
            rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    except (json.JSONDecodeError, csv.Error) as e:
        raise TaskError(f"Couldn't read {name}: {e}") from None
    return [r for r in rows if isinstance(r, dict)][:MAX_EXAMPLES]


def describe_columns(rows: list[dict]) -> list[dict]:
    """What each column looks like: numbers, a few categories, or free text, with how many different values."""
    cols: list[str] = []
    for r in rows[:2000]:
        for k in r:
            if k not in cols and k is not None:
                cols.append(k)
    out = []
    for c in cols:
        values = [r.get(c) for r in rows if r.get(c) not in (None, "")]
        if values and isinstance(values[0], (dict, list)):
            continue  # nested data (chat messages): handled as example chats
        texts = [str(v) for v in values]
        numeric = sum(_number(v) is not None for v in values)
        distinct = len(set(texts))
        avg = sum(map(len, texts)) / len(texts) if texts else 0
        wordy = sum(" " in t.strip() for t in texts)
        if values and numeric >= 0.95 * len(values):
            kind = "number"
        elif (avg > 40 and distinct > 0.5 * len(values)) or (distinct > 0.8 * len(values) and avg >= 12
                                                             and wordy >= 0.8 * len(values)):
            kind = "text"  # long, or short but nearly all different and several words: sentences, not categories
        else:
            kind = "category"
        common = sorted(set(texts), key=texts.count, reverse=True)[:30] if kind == "category" and distinct <= 30 else []
        out.append({"name": c, "kind": kind, "distinct": distinct, "filled": len(values),
                    "sample": texts[:3], "values": common})
    return out


def _guess_answer(columns: list[dict]) -> str | None:
    by_name = {c["name"].lower().strip(): c["name"] for c in columns}
    for n in ANSWER_NAMES:
        if n in by_name:
            return by_name[n]
    return columns[-1]["name"] if columns else None


def _answer_kind(column: dict, count: int) -> str:
    if column["kind"] == "text":
        return "text"
    if column["kind"] == "number" and column["distinct"] > max(20, 0.05 * count):
        return "number"
    return "label"


def create(name: str, description: str, files: list[tuple[str, bytes]]) -> dict:
    """A new task from uploaded examples: a table (CSV, TSV, JSON, JSONL), example chats (JSONL with "messages"), or
    pictures (their folder names are the answers; pictures without a folder are left to answer later). wanna.sh
    guesses which column is the answer; change it with update() before training."""
    if not files:
        raise TaskError("Add your examples: a table (CSV, TSV, JSON or JSONL), or pictures.")
    tid = uuid.uuid4().hex[:12]
    folder = TASKS_DIR / tid
    pictures = [(n, d) for n, d in files if PICTURE.search(n)]
    tables = [(n, d) for n, d in files if not PICTURE.search(n)]
    if pictures and tables:
        raise TaskError("Add either a table or pictures, not both.")
    folder.mkdir(parents=True)
    try:
        if pictures:
            task, rows = _from_pictures(folder, pictures)
        else:
            task, rows = _from_tables(tables)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    task.update(name=(name or "").strip()[:80] or "My task", description=(description or "").strip()[:2000],
                created=time.time(), status={"stage": "new"})
    _write(folder / "task.json", task)
    _save_examples(tid, rows)
    return get(tid)


def _from_pictures(folder: Path, files: list[tuple[str, bytes]]) -> tuple[dict, list[dict]]:
    (folder / "pictures").mkdir()
    rows = []
    for n, (name, data) in enumerate(files[:MAX_EXAMPLES], 1):
        parts = [p for p in re.split(r"[\\/]", name) if p]
        label = parts[-2] if len(parts) >= 2 else None
        path = f"pictures/{n:05d}{Path(parts[-1]).suffix.lower()}"
        (folder / path).write_bytes(data)
        rows.append({"input": {"picture": path, "name": parts[-1]}, "answer": label})
    return {"input_kind": "picture", "answer_kind": "label", "columns": [], "input_columns": [],
            "answer_column": None}, rows


def _from_tables(files: list[tuple[str, bytes]]) -> tuple[dict, list[dict]]:
    rows: list[dict] = []
    for name, data in files:
        rows += read_table(name, data)
    if not rows:
        raise TaskError("Those files have no rows to learn from.")
    if all(isinstance(r.get("messages"), list) for r in rows[:50]):
        return _from_chats(rows)
    columns = describe_columns(rows)
    if not columns:
        raise TaskError("Those files have no columns to learn from.")
    if len(columns) == 1:  # only what goes in: the answers come later (typed, or drafted by a chat model)
        only = columns[0]
        return ({"columns": columns, "answer_column": None, "input_columns": [only["name"]], "answer_kind": "label",
                 "input_kind": "text" if only["kind"] == "text" else "table"},
                [{"input": r, "answer": None} for r in rows])
    answer = _guess_answer(columns)
    task = {"columns": columns}
    task.update(_choose(columns, rows, answer, [c["name"] for c in columns if c["name"] != answer]))
    return task, [{"input": {k: v for k, v in r.items() if k != answer}, "answer": r.get(answer)} for r in rows]


def _from_chats(rows: list[dict]) -> tuple[dict, list[dict]]:
    out = []
    for r in rows:
        msgs = [m for m in r["messages"] if isinstance(m, dict)]
        last = max((i for i, m in enumerate(msgs) if m.get("role") == "assistant"), default=None)
        if last is None:
            continue
        out.append({"input": {"messages": msgs[:last]}, "answer": str(msgs[last].get("content") or "")})
    return {"input_kind": "text", "answer_kind": "text", "columns": [], "input_columns": [], "answer_column": None,
            "chats": True}, out


def _choose(columns: list[dict], rows: list[dict], answer: str, inputs: list[str]) -> dict:
    """The task's shape from the chosen answer and input columns."""
    by = {c["name"]: c for c in columns}
    if answer not in by:
        raise TaskError(f"There's no column called {answer}.")
    inputs = [c for c in inputs if c in by and c != answer]
    if not inputs:
        raise TaskError("Choose at least one column that goes in.")
    answer_kind = _answer_kind(by[answer], len(rows))
    texts = [c for c in inputs if by[c]["kind"] == "text"]
    input_kind = "text" if len(inputs) == 1 and texts else "table"
    return {"answer_column": answer, "input_columns": inputs, "answer_kind": answer_kind, "input_kind": input_kind}


def update(tid: str, name: str | None = None, description: str | None = None, answer_column: str | None = None,
           input_columns: list[str] | None = None, threshold: float | None = None, labels: list[str] | None = None,
           no_answers: str | None = None, in_chat: bool | None = None) -> dict:
    """Rename it, describe it, set a yes/no task's threshold, list the answers it can give, switch its Chat tool on
    or off, or choose a different answer column or input columns (tables only). no_answers ("label" or "text"): the
    examples have no answers yet (every column goes in), and the answers will be labels or written text."""
    folder = _folder(tid)
    task = _read(folder / "task.json")
    if tid in _running:
        raise TaskError("Wait for it to finish training first.")
    if name is not None:
        task["name"] = name.strip()[:80] or task["name"]
    if description is not None:
        task["description"] = description.strip()[:2000]
    if threshold is not None:
        task["threshold"] = max(0.01, min(0.99, float(threshold)))
    if labels is not None:
        task["labels"] = [str(x).strip()[:80] for x in labels if str(x).strip()][:200]
    if in_chat is not None:
        task["in_chat"] = bool(in_chat)
    if no_answers in ("label", "text") and task.get("columns"):
        rows = [{**r["input"], **({task["answer_column"]: r["answer"]} if task.get("answer_column") else {})}
                for r in examples(tid)]
        inputs = [c["name"] for c in task["columns"]]
        by = {c["name"]: c for c in task["columns"]}
        task.update(answer_column=None, input_columns=inputs, answer_kind=no_answers,
                    input_kind="text" if len(inputs) == 1 and by[inputs[0]]["kind"] == "text" else "table")
        _save_examples(tid, [{"input": r, "answer": None} for r in rows])
        task["status"] = {"stage": "new"}
    elif no_answers in ("label", "text"):
        task["answer_kind"] = no_answers if task["input_kind"] != "picture" else "label"
    if (answer_column or input_columns is not None) and task.get("columns"):
        rows = [{**r["input"], **({task["answer_column"]: r["answer"]} if task.get("answer_column") else {})}
                for r in examples(tid)]
        answer = answer_column or task["answer_column"]
        chosen = input_columns if input_columns is not None else [c["name"] for c in task["columns"]
                                                                  if c["name"] != answer]
        task.update(_choose(task["columns"], rows, answer, chosen))
        _save_examples(tid, [{"input": {k: v for k, v in r.items() if k != answer}, "answer": r.get(answer)}
                             for r in rows])
        (folder / "model.joblib").unlink(missing_ok=True)
        (folder / "report.json").unlink(missing_ok=True)
        task["status"] = {"stage": "new"}
    _write(folder / "task.json", task)
    return get(tid)


def set_answers(tid: str, answers: dict[str, str | None]) -> dict:
    """Give or correct answers by example number (from the examples list): for checking AI-drafted answers."""
    rows = examples(tid)
    for k, v in answers.items():
        i = int(k)
        if 0 <= i < len(rows):
            rows[i]["answer"] = v if v not in ("",) else None
            rows[i].pop("drafted", None)
    _save_examples(tid, rows)
    return get(tid)


# --- training --------------------------------------------------------------------------------------------------------

def start(tid: str, chat_model: str | None = None) -> dict:
    """Train in the background: the method follows from the task's shape (see the module's docstring). Tasks that
    write text train chat_model."""
    task = get(tid)
    if tid in _running:
        raise TaskError("It's busy. Wait for it to finish first.")
    rows = [r for r in examples(tid) if r.get("answer") not in (None, "")]
    if task["answer_kind"] == "text":
        if task["input_kind"] == "picture":
            raise TaskError("Writing text about pictures isn't supported yet.")
        if len(rows) < 13:
            raise TaskError("Give at least 13 examples with answers: 10 to learn from and 3 to test it on.")
        if not chat_model:
            raise TaskError("Choose the chat model to train.")
        job = asyncio.get_running_loop().create_task(_train_text(tid, chat_model))
        _status(tid, stage="training", message="Starting", started=time.time())
        _running[tid] = job
        job.add_done_callback(lambda _: _running.pop(tid, None))
        return get(tid)
    if task["answer_kind"] == "label":
        counts: dict[str, int] = {}
        for r in rows:
            counts[str(r["answer"])] = counts.get(str(r["answer"]), 0) + 1
        if len(counts) < 2:
            raise TaskError("It needs examples of at least two different answers to learn the difference.")
        few = [k for k, n in counts.items() if n < MIN_PER_LABEL]
        if few:
            raise TaskError(f"Give at least {MIN_PER_LABEL} examples of each answer; there's only one of "
                            f"{', '.join(few[:5])}.")
    elif len(rows) < 10:
        raise TaskError("Give at least 10 examples with answers.")
    job = asyncio.get_running_loop().create_task(_train(tid))
    _status(tid, stage="training", message="Starting", started=time.time())
    _running[tid] = job
    _running[tid].add_done_callback(lambda _: _running.pop(tid, None))
    return get(tid)


async def _train(tid: str) -> None:
    started = time.time()
    try:
        task = get(tid)
        rows = [r for r in examples(tid) if r.get("answer") not in (None, "")]
        if task["input_kind"] == "table":
            _status(tid, stage="training", message="Learning from the table", started=started)
            fitted, report = await asyncio.to_thread(_fit_table, task, rows)
        else:
            _status(tid, stage="training", message="Reading the examples with the search model", started=started)
            vectors = await _vectors(task, [r["input"] for r in rows], tid)
            _status(tid, stage="training", message="Learning from them", started=started)
            fitted, report = await asyncio.to_thread(_fit_vectors, task, rows, vectors)
        import joblib

        joblib.dump(fitted, _folder(tid) / "model.joblib")
        report["seconds"] = round(time.time() - started, 1)
        report["unchecked"] = sum(1 for r in rows if r.get("drafted"))
        _write(_folder(tid) / "report.json", report)
        _status(tid, stage="done", message="Done", seconds=report["seconds"])
    except asyncio.CancelledError:
        raise
    except TaskError as e:
        _status(tid, stage="error", message=str(e))
    except Exception as e:
        log.exception("Training task %s failed", tid)
        _status(tid, stage="error", message=f"{type(e).__name__}: {e}"[:600])


# Tables ---------------------------------------------------------------------------------------------------------------

class TableEncoder:
    """Rows ({column: value}) to a numeric matrix: numbers as they are, categories as codes (unseen ones as missing,
    which the trees handle), text columns left out."""

    def __init__(self, columns: list[dict], inputs: list[str]):
        by = {c["name"]: c for c in columns}
        self.columns = [c for c in inputs if by[c]["kind"] != "text"]
        self.kinds = {c: by[c]["kind"] for c in self.columns}
        self.codes: dict[str, dict[str, int]] = {}

    def fit(self, rows: list[dict]) -> TableEncoder:
        for c in self.columns:
            if self.kinds[c] == "category":
                seen: dict[str, int] = {}
                for r in rows:
                    v = r.get(c)
                    if v not in (None, "") and str(v) not in seen and len(seen) < 250:
                        seen[str(v)] = len(seen)
                self.codes[c] = seen
        return self

    def transform(self, rows: list[dict]):
        import numpy as np

        x = np.full((len(rows), len(self.columns)), np.nan, dtype=np.float64)
        for j, c in enumerate(self.columns):
            for i, r in enumerate(rows):
                v = r.get(c)
                if v in (None, ""):
                    continue
                if self.kinds[c] == "number":
                    n = _number(v)
                    x[i, j] = n if n is not None else np.nan
                else:
                    x[i, j] = self.codes[c].get(str(v), np.nan)
        return x

    @property
    def categorical(self) -> list[bool]:
        return [self.kinds[c] == "category" for c in self.columns]


def _fit_table(task: dict, rows: list[dict]) -> tuple[dict, dict]:
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    enc = TableEncoder(task["columns"], task["input_columns"])
    if not enc.columns:
        raise TaskError("All the columns that go in are free text. Use a table with numbers or categories, or choose "
                        "a single text column so it reads the text.")
    inputs = [r["input"] for r in rows]
    x = enc.fit(inputs).transform(inputs)
    label = task["answer_kind"] == "label"
    # Measured on a made-up card-fraud table (6,000 rows, 2% fraud): learning more slowly and stopping when examples
    # held back stop improving ranked the frauds better (cross-validated AUC 0.898) than 300 quick rounds (0.877).
    # Classes aren't reweighted, so its chances stay honest for choosing a threshold.
    settings = {"categorical_features": enc.categorical, "learning_rate": 0.05, "max_iter": 500,
                "early_stopping": len(rows) >= 200, "random_state": 0}
    if label:
        y = np.array([str(r["answer"]) for r in rows])

        def model():
            return HistGradientBoostingClassifier(**settings)
    else:
        y = np.array([_number(r["answer"]) for r in rows], dtype=np.float64)
        keep = ~np.isnan(y)
        x, y, inputs = x[keep], y[keep], [r for r, k in zip(inputs, keep) if k]

        def model():
            return HistGradientBoostingRegressor(**settings)

    tested = _tested(model, x, y, label)
    report, decide = _report(task, inputs, y, tested, label)
    report["uses"] = _importance(model, x, y, enc.columns, label)
    return {"kind": "table", "encoder": enc, "model": model().fit(x, y), **decide}, report


def _importance(model, x, y, names: list[str], label: bool) -> list[dict]:
    """Which columns it relies on: how much worse it gets, on examples it didn't learn from, when one is shuffled."""
    from sklearn.inspection import permutation_importance
    from sklearn.model_selection import train_test_split

    if len(y) < 20 or len(names) < 2:
        return []
    strat = y if label and min(_counts(y).values()) >= 2 else None
    xa, xb, ya, yb = train_test_split(x, y, test_size=0.25, random_state=0, stratify=strat)
    fitted = model().fit(xa, ya)
    # Yes/no: how well it ranks them (what the threshold works from), not right-or-wrong at one threshold.
    scoring = ("roc_auc" if len(set(y)) == 2 else "balanced_accuracy") if label else "neg_mean_absolute_error"
    imp = permutation_importance(fitted, xb, yb, n_repeats=5, random_state=0, scoring=scoring)
    total = sum(max(0.0, m) for m in imp.importances_mean) or 1.0
    ranked = sorted(zip(names, imp.importances_mean), key=lambda t: -t[1])
    return [{"column": n, "share": round(max(0.0, m) / total, 3)} for n, m in ranked[:8] if m > 0]


# Text and pictures, through the search model --------------------------------------------------------------------------

async def _vectors(task: dict, inputs: list, tid: str | None = None):
    """The search model's vectors for text or pictures."""
    from .knowledge import embed

    model = embed.default_model()
    if not model:
        raise TaskError("Reading text or pictures needs a search model. Install one on the Knowledge page (for "
                        "pictures, one that can see them, such as Qwen3 VL Embedding), then train again.")
    items: list = []
    for i in inputs:
        if task["input_kind"] == "picture":
            items.append(embed.picture((_folder(tid) / i["picture"]).read_bytes()) if tid and "picture" in i
                         else embed.picture(i["data"]))
        else:
            items.append(_text_of(task, i))
    try:
        return await embed.embed(model["id"], items, "document")
    except embed.NoPictures as e:
        raise TaskError(str(e)) from None


def _text_of(task: dict, i) -> str:
    if isinstance(i, str):
        return i
    if task.get("input_columns"):
        cols = task["input_columns"]
        return str(i.get(cols[0], "")) if len(cols) == 1 else "\n".join(f"{c}: {i.get(c, '')}" for c in cols)
    return str(i.get("text") or i.get("input") or json.dumps(i, ensure_ascii=False))


def _fit_vectors(task: dict, rows: list[dict], vectors) -> tuple[dict, dict]:
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    y = np.array([str(r["answer"]) for r in rows])

    def model():
        return LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced")

    tested = _tested(model, vectors, y, True)
    report, decide = _report(task, [r["input"] for r in rows], y, tested, True)
    return {"kind": "vectors", "model": model().fit(vectors, y), **decide}, report


# Testing --------------------------------------------------------------------------------------------------------------

def _counts(y) -> dict:
    out: dict = {}
    for v in y:
        out[v] = out.get(v, 0) + 1
    return out


def _tested(model, x, y, label: bool) -> dict:
    """Answers for every example from a model that didn't learn from it: 5-fold cross-validation for fewer than
    CV_BELOW examples, otherwise one held-out fifth. {"tested": which were, "predicted", "chances" (labels: each
    label's chance, columns in "classes" order), "how"}."""
    import numpy as np
    from sklearn.model_selection import KFold, StratifiedKFold, train_test_split

    n = len(y)
    classes = sorted(set(y)) if label else []
    predicted = np.empty(n, dtype=object)
    chances = np.full((n, len(classes)), np.nan)
    tested = np.zeros(n, dtype=bool)
    folds = min(5, min(_counts(y).values())) if label else 5
    if n < CV_BELOW and folds >= 2:
        splitter = StratifiedKFold(folds, shuffle=True, random_state=0) if label else KFold(folds, shuffle=True,
                                                                                            random_state=0)
        splits = list(splitter.split(x, y))
        how = f"each example was tested once, by a version trained on the other {folds - 1} fifths" if folds == 5 \
            else f"each example was tested once, in {folds} rounds, by a version that hadn't seen it"
    else:
        idx = np.arange(n)
        a, b = train_test_split(idx, test_size=0.2, random_state=0, stratify=y if label else None)
        splits = [(a, b)]
        how = f"tested on {len(b):,} examples (a fifth) it didn't learn from"
    for a, b in splits:
        m = model().fit(x[a], y[a])
        predicted[b] = m.predict(x[b])
        if label:
            chances[np.ix_(b, [classes.index(c) for c in m.classes_])] = m.predict_proba(x[b])
        tested[b] = True
    return {"tested": tested, "predicted": predicted, "chances": chances, "classes": classes, "how": how}


THRESHOLDS = (0.02, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def _tradeoffs(is_it, chance) -> list[dict]:
    """For a yes/no task: at each threshold, how many it would flag, how many of the real ones it would catch, and how
    many it would flag wrongly."""
    out = []
    for t in THRESHOLDS:
        flag = chance >= t
        out.append({"threshold": t, "flagged": int(flag.sum()), "caught": int((flag & is_it).sum()),
                    "false_alarms": int((flag & ~is_it).sum())})
    return out


def _best_threshold(rows: list[dict], total: int) -> float:
    """The default: the threshold with the best balance of catching them and being right when it flags (F1)."""
    def f1(r):
        return 2 * r["caught"] / (r["flagged"] + total) if r["flagged"] + total else 0
    return max(rows, key=f1)["threshold"]


def _summary(task: dict, i) -> str:
    """A short form of an input, for lists of mistakes."""
    if isinstance(i, dict) and "picture" in i:
        return i.get("name") or i["picture"]
    if isinstance(i, dict) and "messages" in i:
        return str(i["messages"][-1].get("content", ""))[:200] if i["messages"] else ""
    if isinstance(i, dict):
        return ", ".join(f"{k}: {v}" for k, v in list(i.items())[:8])[:240]
    return str(i)[:240]


def _report(task: dict, inputs: list, y, result: dict, label: bool) -> tuple[dict, dict]:
    """How it did on the examples it was tested on, and how it should decide (for a yes/no task, the threshold on
    the less common answer's chance)."""
    import numpy as np

    tested, predicted, how = result["tested"], result["predicted"].copy(), result["how"]
    out: dict = {"how": how, "tested": int(tested.sum()), "kind": task["answer_kind"]}
    decide: dict = {}
    confidence = np.full(len(y), np.nan)
    if label and result["classes"]:
        confidence[tested] = result["chances"][tested].max(axis=1)
    if label and len(result["classes"]) == 2:
        counts = _counts(y)
        rare = min(result["classes"], key=lambda c: counts[c])
        other = next(c for c in result["classes"] if c != rare)
        chance = result["chances"][:, result["classes"].index(rare)]
        is_it = (y == rare)[tested]
        rows = _tradeoffs(is_it, chance[tested])
        threshold = _best_threshold(rows, int(is_it.sum()))
        predicted[tested] = np.where(chance[tested] >= threshold, rare, other)
        out["tradeoffs"] = {"label": rare, "other": other, "total": int(is_it.sum()), "rows": rows,
                            "threshold": threshold}
        decide = {"rare": rare, "other": other, "threshold": threshold}
    yt, pt = y[tested], predicted[tested]
    if label:
        pt = pt.astype(str)
        labels = sorted(set(yt) | set(pt))
        counts = _counts(yt)
        common = max(counts, key=counts.get)
        out["accuracy"] = round(float((yt == pt).mean()), 4)
        out["baseline"] = {"answer": common, "accuracy": round(counts[common] / len(yt), 4)}
        out["labels"] = []
        for lab in labels:
            actual = yt == lab
            said = pt == lab
            out["labels"].append({
                "label": lab, "examples": int(actual.sum()),
                "found": int((actual & said).sum()),  # of the examples that are this, how many it said were
                "said": int(said.sum()),  # how often it gave this answer; found / said is how often it was right then
            })
        out["confusion"] = {"labels": labels,
                            "counts": [[int(((yt == a) & (pt == b)).sum()) for b in labels] for a in labels]}
        mistakes = [i for i in np.where(tested)[0] if str(predicted[i]) != str(y[i])]
        mistakes.sort(key=lambda i: -(confidence[i] if not np.isnan(confidence[i]) else 0))
        out["mistakes"] = [{"input": _summary(task, inputs[i]), "answer": str(y[i]), "said": str(predicted[i]),
                            "confidence": None if np.isnan(confidence[i]) else round(float(confidence[i]), 3)}
                           for i in mistakes[:25]]
    else:
        pt = pt.astype(float)
        err = np.abs(pt - yt)
        out["mean_error"] = float(err.mean())
        out["median_error"] = float(np.median(err))
        out["within_10_percent"] = round(float((err <= 0.1 * np.abs(yt)).mean()), 4)
        out["baseline"] = {"answer": float(yt.mean()), "mean_error": float(np.abs(yt - yt.mean()).mean())}
        worst = np.argsort(-np.abs(predicted[tested].astype(float) - y[tested]))[:25]
        idx = np.where(tested)[0][worst]
        out["mistakes"] = [{"input": _summary(task, inputs[i]), "answer": float(y[i]), "said": float(predicted[i])}
                           for i in idx]
    return out, decide


# Written answers, by a trained chat model -----------------------------------------------------------------------------

def _messages(task: dict, i) -> list[dict]:
    """The chat for one input: the task's description as the instruction, then the input."""
    system = [{"role": "system", "content": task["description"]}] if task.get("description") else []
    if isinstance(i, dict) and isinstance(i.get("messages"), list):
        given = [m for m in i["messages"] if m.get("role") in ("system", "user", "assistant")]
        return (system if not any(m["role"] == "system" for m in given) else []) + given
    return system + [{"role": "user", "content": _text_of(task, i)}]


async def _train_text(tid: str, chat_model: str) -> None:
    """Hold back a tenth of the examples (3 to 50), train a chat model on the rest, then test it on the held-back
    ones."""
    import random

    from . import training

    started = time.time()
    try:
        task = get(tid)
        rows = [r for r in examples(tid) if r.get("answer") not in (None, "")]
        order = random.Random(tid).sample(range(len(rows)), len(rows))
        n_test = max(3, min(50, len(rows) // 10))
        test, learn = [rows[i] for i in order[:n_test]], [rows[i] for i in order[n_test:]]
        chats = [{"messages": _messages(task, r["input"]) + [{"role": "assistant", "content": str(r["answer"])}]}
                 for r in learn]
        try:
            run = training.create_chat(chat_model, "chats", task["name"], [], typed=chats)
        except training.TrainError as e:
            raise TaskError(str(e)) from None
        _update_task(tid, chat_run=run["id"], chat_model=None, held_back=n_test)
        while True:  # follow the chat training
            await asyncio.sleep(3)
            run = training.get(run["id"])
            st = run["status"]
            if st.get("stage") in ("error", "stopped", "interrupted"):
                raise TaskError(st.get("message") or "Training the chat model stopped.")
            if st.get("stage") == "done" and run.get("chat_model"):
                break
            _status(tid, **{k: v for k, v in st.items() if k in ("stage", "message", "step", "steps",
                                                                 "seconds_left", "done_bytes", "total_bytes")},
                    started=started)
            _status_stage(tid, "training")
        _update_task(tid, chat_model=run["chat_model"])
        task = get(tid)
        _status(tid, stage="training", message=f"Testing it on {n_test} examples it didn't learn from", started=started)
        said = [await _write_answer(task, r["input"]) for r in test]
        report = _text_report(task, test, said)
        report["seconds"] = round(time.time() - started, 1)
        _write(_folder(tid) / "report.json", report)
        _status(tid, stage="done", message="Done", seconds=report["seconds"])
    except asyncio.CancelledError:
        raise
    except TaskError as e:
        _status(tid, stage="error", message=str(e))
    except Exception as e:
        log.exception("Training task %s failed", tid)
        _status(tid, stage="error", message=f"{type(e).__name__}: {e}"[:600])


def _update_task(tid: str, **patch) -> None:
    p = _folder(tid) / "task.json"
    _write(p, {**_read(p), **patch})


def _status_stage(tid: str, stage: str) -> None:
    """Keep the task's own stage while showing the chat training's progress."""
    p = _folder(tid) / "task.json"
    task = _read(p)
    task["status"]["stage"] = stage
    _write(p, task)


async def _chat(model: dict, messages: list[dict], max_tokens: int, think: bool = False) -> str:
    """One reply from a chat model, through the model manager, without randomness. think: let models that can reason
    first do so (the reasoning isn't part of the reply)."""
    import httpx

    from .workers.manager import manager

    worker = await manager.ensure_ready(model)
    worker.last_used = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10), headers=worker.headers) as c:
        r = await c.post(f"{worker.url}/v1/chat/completions", json={
            "messages": messages, "max_tokens": max_tokens, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": think}})
    if r.status_code != 200:
        raise TaskError(f"The chat model returned an error: {r.text[:300]}")
    return (r.json()["choices"][0]["message"].get("content") or "").strip()


async def _write_answer(task: dict, i) -> str:
    model = _chat_model(task)
    if not model:
        raise TaskError("Its trained chat model was deleted. Train it again.")
    return await _chat(model, _messages(task, i), 1024)


def _same(a: str, b: str) -> bool:
    return " ".join(str(a).split()).casefold() == " ".join(str(b).split()).casefold()


def _json_fields(text: str) -> dict | None:
    t = str(text).strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        v = json.loads(t)
    except json.JSONDecodeError:
        return None
    return v if isinstance(v, dict) else None


def _text_report(task: dict, test: list[dict], said: list[str]) -> dict:
    """How the written answers compare with the expected ones. Exact matches always; for answers that are JSON
    objects (pulling fields out of text), how many fields match too. Every pair is listed to judge by eye."""
    expected = [str(r["answer"]) for r in test]
    out: dict = {"kind": "text", "how": f"tested on {len(test)} examples held back from training", "tested": len(test),
                 "exact": round(sum(_same(a, b) for a, b in zip(expected, said)) / len(test), 4)}
    fields = [(_json_fields(a), _json_fields(b)) for a, b in zip(expected, said)]
    if all(e is not None for e, _ in fields):
        total = sum(len(e) for e, _ in fields)
        right = sum(sum(1 for k, v in e.items() if g is not None and _same(json.dumps(g.get(k), sort_keys=True),
                                                                           json.dumps(v, sort_keys=True)))
                    for e, g in fields)
        out["fields"] = {"right": right, "total": total, "valid_json": sum(g is not None for _, g in fields)}
    out["pairs"] = [{"input": _summary(task, r["input"]), "answer": a, "said": b, "same": _same(a, b)}
                    for r, a, b in zip(test, expected, said)]
    return out


# Drafting answers with a chat model ---------------------------------------------------------------------------------

def draft(tid: str, chat_model: str, limit: int = 200, careful: bool = True) -> dict:
    """Have a chat model answer examples that have no answer yet, for the person to check. Label tasks need their
    labels listed (update(labels=...)) or some examples answered already. careful lets models that can reason do so
    before each answer: measured with Qwen3 8B sorting 40 newsgroup posts into 4 topics named by their Usenet codes,
    38 right instead of 29, in 2.7 times as long (plain-word names without reasoning: 36)."""
    from . import db

    task = get(tid)
    if tid in _running:
        raise TaskError("It's busy. Wait for it to finish first.")
    model = db.get_model(chat_model)
    if not model or model["task"] != "chat":
        raise TaskError("Choose a chat model to draft the answers.")
    if task["answer_kind"] == "label" and len(task["labels"]) < 2:
        raise TaskError("List the answers it can give first (at least two), so the drafts use them.")
    if task["input_kind"] == "picture" and not (model.get("meta") or {}).get("mmproj"):
        raise TaskError(f"{(model.get('meta') or {}).get('title') or chat_model} can't see pictures. Choose a chat model "
                        "that can (in Get models these say they can look at pictures).")
    if not any(r.get("answer") in (None, "") for r in examples(tid)):
        raise TaskError("Every example has an answer already.")
    job = asyncio.get_running_loop().create_task(_draft(tid, model, limit, careful))
    _status(tid, stage="drafting", message="Starting", started=time.time())
    _running[tid] = job
    job.add_done_callback(lambda _: _running.pop(tid, None))
    return get(tid)


async def _draft(tid: str, model: dict, limit: int, careful: bool) -> None:
    import base64

    started = time.time()
    try:
        task = get(tid)
        rows = examples(tid)
        todo = [i for i, r in enumerate(rows) if r.get("answer") in (None, "")][:limit]
        answered = [r for r in rows if r.get("answer") not in (None, "")]
        shown = answered[:8] if task["input_kind"] != "picture" else []  # a few examples of what's wanted
        labels = task["labels"]
        rule = {"label": f"Answer with exactly one of these, and nothing else: {', '.join(labels)}.",
                "number": "Answer with just a number, and nothing else.",
                "text": "Answer the way the examples do."}[task["answer_kind"]]
        system = "\n\n".join(x for x in [task.get("description"), rule] if x)
        for n, i in enumerate(todo, 1):
            _status(tid, stage="drafting", message=f"Drafting answer {n} of {len(todo)}", step=n, steps=len(todo),
                    started=started)
            msgs = [{"role": "system", "content": system}]
            for r in shown:
                msgs += [{"role": "user", "content": _text_of(task, r["input"])},
                         {"role": "assistant", "content": str(r["answer"])}]
            inp = rows[i]["input"]
            if task["input_kind"] == "picture":
                data = base64.b64encode((_folder(tid) / inp["picture"]).read_bytes()).decode()
                kind = Path(inp["picture"]).suffix.lstrip(".").replace("jpg", "jpeg")
                msgs.append({"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/{kind};base64,{data}"}},
                    {"type": "text", "text": "Answer for this picture."}]})
            else:
                msgs.append({"role": "user", "content": _text_of(task, inp)})
            short = task["answer_kind"] != "text"
            reply = await _chat(model, msgs, (2048 if careful else 16) if short else (3072 if careful else 1024),
                                think=careful)
            answer = _parse_draft(task, reply, labels)
            if answer is not None:
                rows = examples(tid)  # the person may be checking others meanwhile
                rows[i] = {**rows[i], "answer": answer, "drafted": True}
                _save_examples(tid, rows)
        _status(tid, stage="drafted", message=f"Drafted {len(todo)} answers. Check them, then train.",
                seconds=round(time.time() - started, 1))
    except asyncio.CancelledError:
        raise
    except TaskError as e:
        _status(tid, stage="error", message=str(e))
    except Exception as e:
        log.exception("Drafting for task %s failed", tid)
        _status(tid, stage="error", message=f"{type(e).__name__}: {e}"[:600])


def _parse_draft(task: dict, reply: str, labels: list[str]):
    if task["answer_kind"] == "text":
        return reply or None
    if task["answer_kind"] == "number":
        m = re.search(r"-?\d[\d,]*\.?\d*", reply)
        return _number(m.group(0)) if m else None
    low = reply.strip().strip(".").casefold()
    exact = [x for x in labels if x.casefold() == low]
    if exact:
        return exact[0]
    inside = [x for x in labels if re.search(rf"\b{re.escape(x.casefold())}\b", low)]
    return inside[0] if len(inside) == 1 else None


# Tools for the AI ---------------------------------------------------------------------------------------------------

LOOP: asyncio.AbstractEventLoop | None = None  # the server's event loop, set at start, for tools run from threads


def tool_name(tid: str, task: dict | None = None) -> str:
    task = task or _read(_folder(tid) / "task.json")
    slug = re.sub(r"[^a-z0-9]+", "_", str(task.get("name", "")).lower()).strip("_")[:40] or "task"
    return f"task_{slug}_{tid[:4]}"


def _tool_tasks() -> list[dict]:
    return [t for t in list_tasks() if t["ready"] and t.get("in_chat", True) and t["input_kind"] != "picture"]


def tool_schemas() -> list[dict]:
    """A function the AI can call for each trained task that's switched on for Chat."""
    out = []
    for t in _tool_tasks():
        if t["input_kind"] == "table":
            kinds = {c["name"]: c for c in t["columns"]}
            props = {}
            for c in t["input_columns"]:
                col = kinds[c]
                if col["kind"] == "number":
                    props[c] = {"type": "number", "description": f"For example: {', '.join(col['sample'][:3])}"}
                elif col.get("values"):  # the values it learned; others count as unknown
                    props[c] = {"type": "string", "enum": col["values"]}
                else:
                    props[c] = {"type": "string", "description": f"For example: {', '.join(col['sample'][:3])}"}
            params = {"type": "object", "properties": props, "required": []}
        else:
            params = {"type": "object", "properties": {"text": {"type": "string", "description": "The input"}},
                      "required": ["text"]}
        what = {"label": f"Answers with one of: {', '.join(t['labels'][:20])}, and how sure it is.",
                "number": "Answers with a number.", "text": "Answers in writing."}[t["answer_kind"]]
        desc = f"{t['name']}: a model trained on {t['answered']:,} examples. {what}"
        if t.get("description"):
            desc += f" Task: {t['description'][:400]}"
        out.append({"type": "function", "function": {"name": t["tool"], "description": desc, "parameters": params}})
    return out


def is_tool(name: str) -> bool:
    return name.startswith("task_") and any(t["tool"] == name for t in _tool_tasks())


def run_tool(name: str, arguments: dict) -> dict:
    """Run a task as a tool, from any thread: {"ok", "result" or "error"} like usertools.run."""
    task = next((t for t in _tool_tasks() if t["tool"] == name), None)
    if not task:
        return {"ok": False, "error": f"There's no trained task called {name}."}
    inp = arguments.get("text", "") if task["input_kind"] == "text" else {k: v for k, v in arguments.items()}
    try:
        coro = run(task["id"], [inp])
        if LOOP is not None and LOOP.is_running():
            answer = asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=600)[0]
        else:
            answer = asyncio.run(coro)[0]
    except TaskError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "result": json.dumps(answer, ensure_ascii=False)}


# --- running ---------------------------------------------------------------------------------------------------------

_loaded: dict[str, tuple[float, dict]] = {}


def _model(tid: str) -> dict:
    p = _folder(tid) / "model.joblib"
    if not p.exists():
        raise TaskError("It isn't trained yet.")
    mtime = p.stat().st_mtime
    hit = _loaded.get(tid)
    if not hit or hit[0] != mtime:
        import joblib

        _loaded[tid] = (mtime, joblib.load(p))
    return _loaded[tid][1]


async def run(tid: str, inputs: list) -> list[dict]:
    """Answers for new inputs: {"answer", "confidence" (labels), "scores" (every label's chance)}. For a table, an
    input is {column: value}; for text, a string; for pictures, {"data": bytes}."""
    task = get(tid)
    if not inputs:
        return []
    if task["answer_kind"] == "text":
        if not task["ready"]:
            raise TaskError("It isn't trained yet.")
        return [{"answer": await _write_answer(task, i)} for i in inputs]
    fitted = _model(tid)
    if fitted["kind"] == "table":
        x = fitted["encoder"].transform([i if isinstance(i, dict) else {} for i in inputs])
    else:
        x = await _vectors(task, inputs)
    m = fitted["model"]
    out = []
    predicted = m.predict(x)
    if task["answer_kind"] == "label" and hasattr(m, "predict_proba"):
        probs = m.predict_proba(x)
        threshold = task.get("threshold") or fitted.get("threshold")
        for p, row in zip(predicted, probs):
            scores = {str(c): round(float(s), 4) for c, s in zip(m.classes_, row)}
            if threshold and fitted.get("rare") in scores:  # yes/no: the less common answer past the threshold
                p = fitted["rare"] if scores[fitted["rare"]] >= threshold else fitted["other"]
            out.append({"answer": str(p), "confidence": scores[str(p)], "scores": scores})
    else:
        out = [{"answer": float(p)} for p in predicted]
    return out


async def run_file(tid: str, name: str, data: bytes) -> tuple[str, bytes]:
    """Answer every row of a table file and return it as a CSV, with the answer (and confidence) added to each row."""
    task = get(tid)
    if task["input_kind"] == "picture":
        raise TaskError("For pictures, send them to /run one at a time, or use the page.")
    rows = read_table(name, data)
    if not rows:
        raise TaskError("That file has no rows.")
    if task["input_kind"] == "text" and task.get("input_columns"):
        col = task["input_columns"][0]
        inputs = [str(r.get(col, "")) for r in rows]
    else:
        inputs = rows
    answers = []
    for i in range(0, len(inputs), 512):
        answers += await run(tid, inputs[i:i + 512])
    head = list(rows[0].keys())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head + ["answer", "confidence"] if task["answer_kind"] == "label" else head + ["answer"])
    for r, a in zip(rows, answers):
        w.writerow([r.get(k, "") for k in head] + [a["answer"]] + ([a["confidence"]] if "confidence" in a else []))
    return f"{Path(name).stem}-answered.csv", buf.getvalue().encode("utf-8")
