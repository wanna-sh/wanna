---
title: API overview
description: wanna.sh's OpenAI-compatible API, authentication, model selection and errors.
---

wanna.sh has two APIs, both served on the same address as the app (by default `http://localhost:7860`):

- **The OpenAI-compatible API** under `/v1`. Use it from OpenAI SDKs and any app that supports a custom OpenAI address.
  This is the one to build on.
- **The wanna.sh API** under `/api`, used by the app itself: models, downloads, jobs, settings. See
  [wanna.sh API](/docs/api/native/).

Interactive documentation for every endpoint, generated from the code, is at **http://localhost:7860/docs** while
wanna.sh is running.

## Endpoints

| Endpoint | What it does | Reference |
| --- | --- | --- |
| `GET /v1/models` | List installed models | [below](#list-models) |
| `POST /v1/chat/completions` | Chat, with streaming, tools and pictures | [Chat](/docs/api/chat/) |
| `POST /v1/completions` | Plain text completion (GGUF models) | [Chat](/docs/api/chat/#text-completions) |
| `POST /v1/images/generations` | Make pictures | [Pictures](/docs/api/images/) |
| `POST /v1/images/edits` | Restyle a picture | [Pictures](/docs/api/images/#restyle-a-picture) |
| `POST /v1/audio/speech` | Text to speech | [Voice and transcription](/docs/api/audio/) |
| `POST /v1/audio/transcriptions` | Speech to text | [Voice and transcription](/docs/api/audio/#transcription) |
| `POST /v1/audio/translations` | Speech to English text | [Voice and transcription](/docs/api/audio/#translation) |
| `POST /v1/videos`, `GET /v1/videos/{id}`, `GET /v1/videos/{id}/content` | Make videos (asynchronous) | [Video](/docs/api/video/) |

`POST /v1/embeddings` exists but returns `501 Not Implemented`: embeddings aren't supported yet.

Music has no OpenAI equivalent; use the [wanna.sh API](/docs/api/native/#generate-anything).

## Authentication

Off by default. When **Require API key** is on in Settings, send a key from **API & apps** with every request:

```http
Authorization: Bearer wanna-...
```

`X-API-Key: wanna-...` also works. See [Share wanna.sh on your network](/docs/guides/network/).

## Choosing a model

Every endpoint takes a `model`:

- `"auto"` (or leaving it out) uses the most recently used model of the right kind that is running, or else the one
  you installed most recently.
- A wanna.sh model id, such as `llama-3-2-3b-instruct-q8-0`, from `GET /v1/models`.
- A Hugging Face repository id, such as `openai/whisper-small`, if it's installed.

Models start by themselves on the first request, so the first call can take a while. If the model you name is installed
but for a different task (for example a picture model on `/v1/chat/completions`), you get a `404` explaining why.

## List models

```bash
curl http://localhost:7860/v1/models
```

```json
{
  "object": "list",
  "data": [
    {
      "id": "llama-3-2-3b-instruct-q8-0",
      "object": "model",
      "created": 1793204019,
      "owned_by": "bartowski",
      "wanna": { "task": "chat", "repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF", "engine": "llamacpp", "loaded": true }
    }
  ]
}
```

The extra `wanna` object tells you each model's task (`chat`, `image`, `video`, `speech`, `transcribe` or `sound`),
where it came from, which engine runs it, and whether it's loaded.

## Errors

Errors use OpenAI's shape:

```json
{ "error": { "message": "No chat model installed yet. Download one from the Discover page.", "type": "model_not_found", "code": "model_not_found" } }
```

| Status | When |
| --- | --- |
| `401` | API keys are required and the key is missing or wrong (`invalid_api_key`). |
| `403` | The request came from a web page on another site, or used a host name wanna.sh doesn't answer to. The message says which setting allows it (`WANNA_CORS` or `WANNA_ALLOWED_HOSTS`); see [Security](/docs/reference/security/#protection-from-websites). |
| `404` | The model isn't installed, or is for a different task (`model_not_found`). |
| `500` | Generation failed (`generation_failed`, `transcription_failed`). |
| `503` | The model couldn't start, for example not enough memory (`model_load_failed`). |
