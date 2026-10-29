---
title: Video
description: POST /v1/videos, then poll GET /v1/videos/{id} and download GET /v1/videos/{id}/content.
---

Videos take minutes, so this works like OpenAI's video API: create a job, check on it, then download the result.

## 1. Start a video

```http
POST /v1/videos
```

```bash
curl http://localhost:7860/v1/videos \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a paper boat drifting down a rainy street", "seconds": "4", "size": "832x480"}'
```

```json
{ "id": "...", "object": "video", "model": "wan2-1-t2v-1-3b-diffusers", "status": "queued", "progress": 0, "seconds": "4.1", "size": "832x480" }
```

| Field | Notes |
| --- | --- |
| `prompt` | Required. |
| `model` | `auto`, a model id or a Hugging Face repo id. |
| `seconds` | Length of the clip. |
| `size` | `"WIDTHxHEIGHT"`. Leave out for the model's usual size. |
| `negative_prompt`, `seed`, `steps` | Optional extras. |

To animate a picture, send a multipart form instead, with the picture as `input_reference`:

```bash
curl http://localhost:7860/v1/videos -F prompt="the waves start rolling" -F input_reference=@beach.jpg
```

## 2. Wait for it

```http
GET /v1/videos/{id}
```

`status` goes `queued` → `in_progress` → `completed` (or `failed`, with an `error`). `progress` is 0 to 100.

## 3. Download it

```http
GET /v1/videos/{id}/content
```

Returns the MP4 file.

```python
import time, httpx

base = "http://localhost:7860/v1"
job = httpx.post(f"{base}/videos", json={"prompt": "a paper boat drifting down a rainy street", "seconds": "4"}).json()
while job["status"] in ("queued", "in_progress"):
    time.sleep(5)
    job = httpx.get(f"{base}/videos/{job['id']}").json()
    print(job["status"], job["progress"])
if job["status"] == "completed":
    open("boat.mp4", "wb").write(httpx.get(f"{base}/videos/{job['id']}/content").content)
```
