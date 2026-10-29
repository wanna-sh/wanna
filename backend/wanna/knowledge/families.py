"""How each embedding model family wants its text. Searches work best when queries and documents are phrased the
way the model was trained: some models want an instruction before queries, some a label before documents.
Sources: each model's card on Hugging Face (checked 2026-10-29)."""

from __future__ import annotations

import re

FAMILIES = [
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
