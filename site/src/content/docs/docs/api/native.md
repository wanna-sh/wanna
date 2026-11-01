---
title: wanna.sh API
description: The /api endpoints the app uses, for models, downloads, generation jobs and settings.
---

The app itself talks to wanna.sh through `/api`. You can use it too, for things the OpenAI API doesn't cover:
finding and downloading models, starting and stopping them, music, and settings. It's simpler than the OpenAI API but
less stable: it may change between versions. The full list, with request and response shapes, is at
**http://localhost:7860/docs**.

The same [API key rules](/docs/api/#authentication) apply.

## Generate anything

`POST /api/generate/{task}` starts a job for `image`, `video`, `speech`, `sound` (music) or `transcribe`, and returns
straight away. Poll `GET /api/jobs/{id}` until `status` is `completed` or `failed`.

```bash
curl http://localhost:7860/api/generate/sound \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "prompt": "calm lo-fi beat with soft piano", "duration": 10}'
```

```json
{ "id": "...", "task": "sound", "status": "queued", "progress": 0, "result": null, ... }
```

When it's done, `result.files` lists the output files, which you download from `/files/{name}`:

```bash
curl -O http://localhost:7860/files/<name>
```

For transcription, `result` holds `text`, timed `segments` and `duration` instead.

| Task | Main fields |
| --- | --- |
| `image` | `prompt`, `negative_prompt`, `width`, `height`, `n`, `quality` (`fast`, `balanced`, `best`), `steps`, `guidance`, `seed`, `sampler`, `image_upload` and `strength` to start from a picture |
| `video` | `prompt`, `negative_prompt`, `width`, `height`, `num_frames`, `quality`, `seed`, `image_upload` |
| `speech` | `text`, `voice`, `speed`, `format` (`wav`, `mp3`, `flac`, `ogg`) |
| `sound` | `prompt`, `duration` in seconds |
| `transcribe` | `file_upload` (required), `language`, `translate` |

Files go in by id, never by path: upload them first with `POST /api/uploads` (multipart field `file`), which returns
`{"id": ..., "filename": ...}`, then pass that `id` as `image_upload` or `file_upload`.

## Models

| Endpoint | What it does |
| --- | --- |
| `GET /api/models` | Installed models, with whether each is loaded and where. |
| `POST /api/models/{id}/load` | Start a model. Optional body: `{"gpus": [0, 1], "context": 16384, "offload": false}`. |
| `POST /api/models/{id}/unload` | Stop it and free its memory. |
| `DELETE /api/models/{id}` | Delete it from disk. |
| `GET /api/models/{id}/memory` | For chat models: memory options, how each would fit, and the recommended one. |
| `GET /api/models/{id}/log` | The end of the model's engine log, for troubleshooting. |

## Finding and downloading

| Endpoint | What it does |
| --- | --- |
| `GET /api/hub/overview?q=` | The best few models per task for this computer. |
| `GET /api/hub/browse?task=chat&q=&sort=popular&fits=true` | Runnable models for one task, rated for this computer. `sort` is `popular`, `trending`, `newest` or `liked`. |
| `GET /api/hub/model/{repo_id}` | One model's details: versions, sizes and ratings. |
| `POST /api/downloads` | Start a download: `{"repo_id": "...", "variant_id": "..."}`. Leave out `variant_id` for the recommended version. |
| `GET /api/downloads` | Download progress. |
| `DELETE /api/downloads/{id}` | Cancel one. |

## Training

[Training your own picture style](/docs/tutorials/train/) or [chat model](/docs/tutorials/train-chat/) from apps:

| Endpoint | What it does |
| --- | --- |
| `GET /api/training` | Whether this computer can train pictures (`ready`), the picture models it can train (`models`, with a time estimate per step), and every run, pictures and chat (`runs`). |
| `GET /api/training/chat-models` | Whether this computer can train chat models (`ready`), and each installed chat model with the `original` it trains from, its size (`original_bytes`), whether it's `downloaded`, how it would train here (`plan`: `mode` `bf16` or `4bit`, and the `cards`), `seconds_per_example`, or `why_not`. |
| `POST /api/training` | Start training a picture model. Multipart form: `model`, `preset` (`subject` or `style`), `trigger`, `what` (for subjects, such as `dog`), `name`, optional `steps`, and 3 to 50 `files`. |
| `POST /api/training/chat` | Start training a chat model. Multipart form: `model`, `preset` (`voice` or `chats`), `name`, optional `steps`; for `voice`, `files` (text, Markdown or PDF) and/or `text`; for `chats`, `files` (.jsonl, .json or .csv) and/or `examples`, a JSON list of `{"prompt": ..., "reply": ...}`. |
| `GET /api/training/{id}` | One run: its `type` (`picture` or `chat`) and `status` (`stage` is `downloading`, `preparing`, `training`, `saving`, `samples`, `done`, `stopped`, `interrupted` or `error`, with `step`, `steps` and `seconds_left` while training, and `done_bytes` and `total_bytes` while downloading). Picture runs have `samples` and an example `prompt`; chat runs have `replies` (each `prompt` with the reply `after` training and `before`) and `chat_model`, the id of the chat model it became. |
| `PATCH /api/training/{id}` | Rename it: `{"name": "..."}`. |
| `POST /api/training/{id}/stop` | Stop it after the current step. |
| `POST /api/training/{id}/restart` | Train it again from the start, with the same examples. |
| `DELETE /api/training/{id}` | Delete it, with its examples and what it learned. |
| `GET /api/training/{id}/samples/{n}.png` | A sample picture made with a picture run. |

```bash
curl http://localhost:7860/api/training \
  -F model=stable-diffusion-v1-5 -F preset=subject \
  -F trigger=rexzx -F what=dog -F name=Rex \
  -F files=@rex1.jpg -F files=@rex2.jpg -F files=@rex3.jpg
```

To use a trained picture style, pass `"lora": "<id>"` when making a picture, with
[the pictures API](/docs/api/images/#trained-styles) or with `POST /api/generate/image`. A trained chat model is a model
of its own: pass its `chat_model` id as `model` to [chat completions](/docs/api/chat/).

```bash
curl http://localhost:7860/api/training/chat \
  -F model=qwen3-8b-q4-k-m -F preset=chats -F name="Shop helper" \
  -F files=@examples.jsonl
```

## System and settings

| Endpoint | What it does |
| --- | --- |
| `GET /api/system` | Graphics cards, memory, disk, engines and loaded models. |
| `GET /api/system/check` | The [system check](/docs/reference/troubleshooting/#the-system-check) from Settings. |
| `GET /api/settings`, `PUT /api/settings` | Read or change [settings](/docs/reference/settings/). Secrets come back masked. |
| `GET /api/keys`, `POST /api/keys`, `DELETE /api/keys/{id}` | Manage API keys. `POST` takes `{"name": "..."}` and returns the key once. |
| `GET /api/gallery`, `DELETE /api/gallery/{id}` | Everything you've made. |
