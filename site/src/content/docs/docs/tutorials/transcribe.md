---
title: Transcribe recordings
description: Turn a recording into text with timestamps, translate it to English, or save subtitles.
---

**Transcribe** writes down what's said in a recording.

1. Install a transcription model from **Get models → Transcribe**. Whisper models are a good choice: the small ones are
   fast, the large ones are more accurate.
2. Open **Transcribe** and either upload an audio file or record from your microphone.
3. Press **Write it down**.

## Options

| Option | What it does |
| --- | --- |
| **Language** | **Detect automatically**, or pick the spoken language for better accuracy. |
| **Translate to English** | Writes the transcript in English, whatever language is spoken. Supported by Whisper models. |

## Using the transcript

- **Copy** puts the text on your clipboard.
- **Save as text** downloads `transcript.txt`.
- **Save as subtitles** downloads `subtitles.srt`, ready for video players and editors. This appears when the model
  provides timestamps, which Whisper models do.

The same transcription model powers the microphone button in [Chat](/docs/tutorials/chat/#speak-instead-of-typing).
