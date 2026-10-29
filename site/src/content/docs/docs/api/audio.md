---
title: Voice and transcription
description: POST /v1/audio/speech, /v1/audio/transcriptions and /v1/audio/translations.
---

## Text to speech

```http
POST /v1/audio/speech
```

Returns the audio file directly.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:7860/v1", api_key="not-needed")
with client.audio.speech.with_streaming_response.create(
    model="auto", voice="default", input="Hello there! This was made on my own computer."
) as response:
    response.stream_to_file("hello.mp3")
```

| Field | Notes |
| --- | --- |
| `input` | Required. The text to read. |
| `model` | `auto`, a model id or a Hugging Face repo id. |
| `voice` | For Bark models, a speaker preset such as `v2/en_speaker_6`. Other voice models have a single voice and ignore it. The OpenAI SDK requires the field, so send any value, such as `default`. |
| `response_format` | `mp3` (default), `wav`, `flac` or `ogg`. Other formats fall back to `mp3`. |
| `speed` | Default `1.0`. |

## Transcription

```http
POST /v1/audio/transcriptions
```

Multipart form upload.

```python
result = client.audio.transcriptions.create(model="whisper-1", file=open("meeting.mp3", "rb"))
print(result.text)
```

`whisper-1` (OpenAI's model name) is treated like `auto`, so existing code works unchanged.

| Field | Notes |
| --- | --- |
| `file` | Required. The recording. |
| `model` | `auto`, `whisper-1`, a model id or a Hugging Face repo id. |
| `language` | Optional language code, such as `en` or `fr`. Detected automatically if left out. |
| `response_format` | `json` (default, `{"text": ...}`), `text`, `verbose_json` (with timed segments), `srt` or `vtt`. |

Timed segments, and so `srt` and `vtt`, come from Whisper models.

## Translation

```http
POST /v1/audio/translations
```

Same as transcription, but the text comes out in English whatever language is spoken. Use a Whisper model.

```bash
curl http://localhost:7860/v1/audio/translations -F file=@interview-es.mp3 -F response_format=text
```
