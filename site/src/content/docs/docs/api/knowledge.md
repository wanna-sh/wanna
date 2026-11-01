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

### Pictures

A search model that can see pictures, such as
[Qwen3 VL Embedding](https://huggingface.co/mradermacher/Qwen3-VL-Embedding-2B-GGUF), embeds pictures as well as text,
into the same space: a photo of a dog comes out near the words "a dog". Send a picture as an `image_url` part with a
data URL (or an object with `image`, plain base64), alone or in a list with text about it:

```python
import base64

dog = "data:image/jpeg;base64," + base64.b64encode(open("dog.jpg", "rb").read()).decode()
r = client.embeddings.create(model="auto", input=[
    "a dog playing in the snow",                                    # text
    {"type": "image_url", "image_url": {"url": dog}},                # a picture
    [{"type": "text", "text": "our dog"}, {"type": "image_url", "image_url": {"url": dog}}],  # both together
])
```

- With such a model, every input, text included, is put in the model's own format, so text and pictures can be
  compared. Add `"input_type": "query"` when embedding what someone searches for (the default is `"document"`).
- Pictures can be PNG, JPEG, GIF or BMP, up to 20 MB; WebP and other formats work once the
  [AI libraries](/docs/tutorials/pictures/) are installed. Send the picture itself: web addresses aren't fetched.
- With a search model that reads text only, a picture gives a `400` error.
- `encoding_format: "base64"` is supported.

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
| `POST /api/knowledge/documents/{id}/retry` | Read a document that failed again. |
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
installing a better one, or after removing the one the library used. The library's old vectors are dropped first
(vectors from two models can't be compared); until each document is done it's searched by words only.

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
| `query` | A question or keywords. |
| `image` | A picture to search with, as a data URL or base64: finds pictures and passages like it. Needs a library read with a search model that can see pictures; can be combined with `query`. Send `query`, `image` or both. |
| `libraries` | Required. One or more library ids. |
| `k` | How many passages, 1 to 30. Default 6. |

Each result has the passage `text`, its `document`, `page` (for PDFs), `heading` (the section it's in), `library`, a
`score`, and `matched`: `["meaning"]`, `["words"]` or both. Results are best first. A passage that is a picture (a
picture you added, or a page of a scanned PDF) also has `picture`: the path to get it from, such as
`/api/knowledge/passages/42/picture`.

The response also has `warnings`: a list of messages, for example when a library's search model was removed and it
could only be searched by words.

### Context for a chat

```http
POST /api/knowledge/context
```

Same body as search. Returns `results`, `warnings` and a `prompt`: instructions plus the numbered passages, ready to
use as the system message of a chat request. This is exactly what Chat does:

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
