"""How each embedding model family wants its text. Searches work best when queries and documents are phrased the
way the model was trained: some models want an instruction before queries, some a label before documents.
Sources: each model's card on Hugging Face (checked 2026-10-29)."""

from __future__ import annotations

import re

FAMILIES = [
    # Qwen/Qwen3-VL-Embedding-*: pictures as well as text. Every input goes in Qwen3-VL's chat format, with an
    # instruction as the system message ("Represent the user's input." is the model's default); last-token pooling.
    # Its GGUFs don't say how to pool, so wanna.sh says so. Checked against llama.cpp b11963 on 2026-11-01: photos of a
    # cat, a dog and a bee each came out nearest their own description.
    (re.compile(r"qwen3-vl-embedding", re.I), {
        "pooling": "last", "pictures": True,
        "query": "Find pictures and passages from the user's documents that match the query.",
        "document": "Represent the user's input.",
    }),
    # Qwen/Qwen3-Embedding-*: instruction-aware queries, plain documents, last-token pooling.
    (re.compile(r"qwen3-embedding", re.I), {
        "pooling": "last",
        "query": "Instruct: Given a question, retrieve passages from the user's documents that answer it\nQuery:",
        "document": "",
    }),
    # google/embeddinggemma-300m (prompts from its sentence-transformers config).
    (re.compile(r"embeddinggemma", re.I), {
        "pooling": None, "query": "task: search result | query: ", "document": "title: none | text: ",
    }),
    # nomic-ai/nomic-embed-text-v1.5.
    (re.compile(r"nomic-embed-text", re.I), {
        "pooling": None, "query": "search_query: ", "document": "search_document: ",
    }),
]
PLAIN = {"pooling": None, "query": "", "document": ""}


def family(repo_id: str) -> dict:
    for pattern, spec in FAMILIES:
        if pattern.search(repo_id or ""):
            return spec
    return PLAIN


def sees_pictures(model: dict) -> bool:
    """A search model that can embed pictures: of a family that does, installed with its vision part."""
    return bool(family(model.get("repo_id", "")).get("pictures")) and bool((model.get("meta") or {}).get("mmproj"))


def chat_prompt(instruction: str, text: str, marker: str | None) -> str:
    """One input in Qwen3-VL's chat format: the instruction, then the picture (as llama.cpp's media marker) and text,
    ending where the model's reply would start, where its last token is pooled."""
    return (f"<|im_start|>system\n{instruction}<|im_end|>\n<|im_start|>user\n"
            f"{marker or ''}{text}<|im_end|>\n<|im_start|>assistant\n")
