# Changelog

Each version's section becomes its GitHub release notes (see `.github/workflows/release.yml`).

## 0.1.0 (2026-10-29)

The first release of wanna.sh: run AI models on your own computer, from one app.

### Make things

- **Chat** with GGUF models on llama.cpp: streaming replies, pictures for models that can see, attached documents,
  speaking instead of typing, standing instructions, and chat history with archive.
- **Pictures**, **videos**, **read aloud**, **transcribe** and **music & sound**, with diffusers and transformers.
- **Code**: a coding agent that plans, edits files, runs commands in a locked-down Docker sandbox, searches the web
  through a private SearXNG, and asks before acting (three approval modes).
- **Knowledge** (RAG): libraries of your documents, searched by meaning and by words, with numbered citations in Chat
  and a search tool in Code. Long chat attachments are searched instead of cut off.

### Models and hardware

- **Get models** lists models from Hugging Face rated for your computer, with the version that suits it, and downloads
  that resume.
- Automatic placement on the right graphics card, models shared across several cards, planned memory for chat, a
  system memory guard, and a system check in Settings.

### For developers

- An **OpenAI-compatible API** under `/v1`: chat, completions, images, speech, transcription, translation, video and
  embeddings. Plus the wanna.sh API under `/api`, with interactive docs at `/docs`.
- Optional API keys, and protection from websites (Origin, Host and CORS checks).

### Install

- A **one-line installer** for Linux, macOS and Windows (WSL2), with `--chat-only` and version pinning.
- **Docker images** on GitHub Container Registry, full and chat-only, with Code available as an option.
- Documentation and tutorials at <https://wanna.sh>.
