---
title: Knowledge and embeddings
description: POST /v1/embeddings, and the /api/knowledge endpoints for libraries, documents and search.
---

## Embeddings

```http
POST /v1/embeddings
```

OpenAI-compatible vectors from an installed search (embedding) model. Use them to build your own search or RAG.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:7860/v1", api_key="not-needed")
r = client.embeddings.create(model="auto", input=["The cat sat on the mat", "A feline rested on a rug"])
print(len(r.data), "vectors of", len(r.data[0].embedding), "numbers")
```

| Field | Notes |
| --- | --- |
| `input` | A string or a list of strings. |
| `model` | `auto`, a model id or a Hugging Face repo id of an installed search model (Get models, *Document search*). |

Text is embedded exactly as you send it. Some models work best with a label in front: Qwen3 Embedding wants queries
written as `Instruct: <task>\nQuery:<question>`, EmbeddingGemma uses `task: search result | query: ` and
`title: none | text: `, and Nomic Embed uses `search_query: ` and `search_document: `. See each model's card. The
Knowledge endpoints below add these for you.

## Knowledge libraries

The endpoints the [Knowledge](/docs/tutorials/knowledge/) page and Chat use. Like the rest of the
[wanna.sh API](/docs/api/native/), they may change between versions; interactive docs are at `/docs` while wanna.sh
runs.

### Set up

| Endpoint | What it does |
| --- | --- |
| `GET /api/knowledge/status` | Installed search models, the one new libraries use (`default`), suggestions, and downloads in progress. |
| `POST /api/knowledge/setup` | Download a search model: `{"repo_id": "Qwen/Qwen3-Embedding-0.6B-GGUF"}` (the default). |

### Libraries and documents

| Endpoint | What it does |
| --- | --- |
| `GET /api/knowledge/libraries` | Your libraries, with document and passage counts. Add `?hidden=true` to include chats' own. |
| `POST /api/knowledge/libraries` | Create one: `{"name": "Work documents", "description": "..."}`. |
| `GET /api/knowledge/libraries/{id}` | One library, with its documents in `documents_list`. |
| `PATCH /api/knowledge/libraries/{id}` | Rename it or change its description. |
| `DELETE /api/knowledge/libraries/{id}` | Delete it, its documents and their files. |
| `POST /api/knowledge/libraries/{id}/documents` | Add documents: a multipart upload with one or more `files` fields. Returns them with `status: "queued"`; indexing runs in the background. |
| `GET /api/knowledge/libraries/{id}/documents` | Documents and their `status` (`queued`, `indexing`, `ready`, `error`), `progress` (0 to 1) and `error`. |
| `DELETE /api/knowledge/documents/{id}` | Remove a document. |
| `GET /api/knowledge/documents/{id}/file` | Download the original file. |

```bash
LIB=$(curl -s localhost:7860/api/knowledge/libraries -H 'Content-Type: application/json' \
  -d '{"name": "Manuals"}' | jq -r .id)
curl -s localhost:7860/api/knowledge/libraries/$LIB/documents -F files=@router-manual.pdf -F files=@notes.md
```

### Re-index a library

```http
POST /api/knowledge/libraries/{id}/reindex
```

Body: `{"model": "<search model id>"}`. Reads every document again with that search model, for example after
installing a better one.

### Search

```http
POST /api/knowledge/search
```

```bash
curl -s localhost:7860/api/knowledge/search -H 'Content-Type: application/json' \
  -d '{"query": "How do I reset the router?", "libraries": ["'$LIB'"], "k": 5}'
```

| Field | Notes |
| --- | --- |
| `query` | Required. A question or keywords. |
| `libraries` | Required. One or more library ids. |
| `k` | How many passages, 1 to 30. Default 6. |

Each result has the passage `text`, its `document`, `page` (for PDFs), `heading` (the section it's in), `library`, a
`score`, and `matched`: `["meaning"]`, `["words"]` or both. Results are best first.

### Context for a chat

```http
POST /api/knowledge/context
```

Same body as search. Returns `results` and a `prompt`: instructions plus the numbered passages, ready to use as the
system message of a chat request. This is exactly what Chat does:

```python
import httpx
from openai import OpenAI

question = "How do I reset the router?"
ctx = httpx.post("http://localhost:7860/api/knowledge/context",
                 json={"query": question, "libraries": ["manuals-1a2b3c"]}).json()

client = OpenAI(base_url="http://localhost:7860/v1", api_key="not-needed")
reply = client.chat.completions.create(
    model="auto",
    messages=[{"role": "system", "content": ctx["prompt"]}, {"role": "user", "content": question}],
)
print(reply.choices[0].message.content)  # cites passages as [1], [2]...
for n, r in enumerate(ctx["results"], 1):
    print(f"[{n}] {r['document']}, page {r['page']}")
```
