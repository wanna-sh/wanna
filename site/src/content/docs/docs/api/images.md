---
title: Pictures
description: POST /v1/images/generations and /v1/images/edits.
---

## Make a picture

```http
POST /v1/images/generations
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:7860/v1", api_key="not-needed")
result = client.images.generate(prompt="a lighthouse at dawn, watercolour", size="1024x1024")
print(result.data[0].url)
```

The request waits until the picture is finished. By default you get a URL on wanna.sh
(`http://localhost:7860/files/...`); ask for `"response_format": "b64_json"` to get the image inline.

| Field | Notes |
| --- | --- |
| `prompt` | Required. |
| `model` | `auto`, a model id or a Hugging Face repo id. |
| `n` | How many pictures. Default 1. |
| `size` | `"WIDTHxHEIGHT"`, for example `"1024x768"`, or `"auto"` for the model's usual size. |
| `quality` | `low`, `medium`, `high` (OpenAI's names), or wanna.sh's `fast`, `balanced`, `best`. |
| `response_format` | `url` (default) or `b64_json`. |

wanna.sh also accepts these extra fields (with the OpenAI SDKs, pass them in `extra_body`):

| Field | Notes |
| --- | --- |
| `negative_prompt` | What to avoid. |
| `steps` (or `num_inference_steps`) | Number of steps. Overrides `quality`. |
| `guidance_scale` | How closely to follow the prompt. |
| `seed` | Same seed and prompt give the same picture. |
| `sampler` | `dpmpp_2m_karras`, `euler_a`, `euler`, `unipc`, `ddim`, or `builtin` for the model's own. Works with Stable Diffusion style models; a model that can't use the sampler you name (FLUX, for example) returns an error. |

```python
result = client.images.generate(
    prompt="a lighthouse at dawn, watercolour",
    extra_body={"negative_prompt": "text, watermark", "seed": 42, "steps": 30},
)
```

### Trained styles

Use a style you [trained](/docs/tutorials/train/) with these two extra fields:

| Field | Notes |
| --- | --- |
| `lora` | The trained style's id. |
| `lora_strength` | How strongly to use it, from 0 to 1.5. Default 1. |

A trained style only works with the picture model it was trained on, so pass that model as `model` too. Each picture
model in `GET /api/models` lists the finished styles it can use under `styles`, with their `id`, `name`, `trigger`
word and an example `prompt`. `GET /api/training` lists every run. Put the trigger word in your prompt:

```python
result = client.images.generate(
    model="stable-diffusion-v1-5",
    prompt="a photo of rexzx dog wearing a party hat",
    extra_body={"lora": "c43f7898e4b8", "lora_strength": 0.8},
)
```

An unknown id, an unfinished run, or a style trained on a different model returns a 400 error.

## Restyle, change or combine pictures

```http
POST /v1/images/edits
```

Multipart form upload. Starts from your picture and changes it to match the prompt. With an editing model (such as
Qwen-Image 2.1 or Qwen-Image-Edit), the prompt is an instruction, for example *"make it a snowy evening"*, the rest of
the picture stays as it was, the result keeps the picture's shape, and `strength` is ignored.

```bash
curl http://localhost:7860/v1/images/edits \
  -F image=@photo.png \
  -F prompt="make it look like a pencil sketch" \
  -F strength=0.6
```

| Field | Notes |
| --- | --- |
| `image` | Required. The starting picture. Repeat it (or send `image[]`) for several pictures; see below. |
| `prompt` | Required. |
| `model`, `n`, `response_format`, `seed` | As above. |
| `size` | `"WIDTHxHEIGHT"` for the result. With one picture to an editing model, it sets the number of pixels and the result keeps the picture's shape. |
| `strength` | 0 to 1. How far it may move from the original. Default 0.6. |

### Several pictures

Models that combine pictures take several at once: Qwen-Image 2.1 up to 10, Qwen-Image-Edit-2509 and -2511 up to 3.
Send each as its own `image` (or `image[]`, which is what OpenAI's SDKs send for a list) field, in order, and refer
to them by number in the prompt:

```bash
curl http://localhost:7860/v1/images/edits \
  -F "image[]=@person1.png" \
  -F "image[]=@person2.png" \
  -F prompt="the person in picture 1 and the person in picture 2 having coffee together at a café" \
  -F size=1024x768
```

```python
result = client.images.edit(
    model="qwen-image-2-1-uncensored-quantized-q8-0",
    image=[open("person1.png", "rb"), open("person2.png", "rb")],
    prompt="the person in picture 1 and the person in picture 2 having coffee together at a café",
)
```

More pictures than the model takes returns a 400 error naming the installed models that can take them. In
`GET /api/models`, each picture model's `max_images` says how many it takes.

Masks (painting over only part of a picture) aren't supported yet.

Models that only edit (Qwen-Image-Edit) need a picture: `POST /v1/images/generations` with one returns a 400 error.
In `GET /api/models`, a picture model's `meta.edits` is `true` when it edits, and `meta.needs_image` is `true` when it
can't start from a description alone.
