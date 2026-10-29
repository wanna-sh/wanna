import type { Task } from "./api";

// Everything the UI says about a task, written as what people want to do rather than what the model is.
export const TASKS: Record<
  Task,
  { verb: string; label: string; href: string; noun: string; help: string }
> = {
  chat: {
    verb: "chat with an assistant",
    label: "Chat",
    href: "/chat/",
    noun: "chat model",
    help: "Ask questions, write, brainstorm and get help with code.",
  },
  image: {
    verb: "make a picture",
    label: "Pictures",
    href: "/image/",
    noun: "picture model",
    help: "Describe a picture and watch it appear.",
  },
  video: {
    verb: "make a video",
    label: "Videos",
    href: "/video/",
    noun: "video model",
    help: "Turn a description, or a starting picture, into a short clip.",
  },
  speech: {
    verb: "hear text read aloud",
    label: "Read aloud",
    href: "/speech/",
    noun: "voice model",
    help: "Paste some text and get a natural sounding recording.",
  },
  transcribe: {
    verb: "turn a recording into text",
    label: "Transcribe",
    href: "/transcribe/",
    noun: "transcription model",
    help: "Upload or record audio and get it written down.",
  },
  sound: {
    verb: "make music",
    label: "Music & sound",
    href: "/music/",
    noun: "music model",
    help: "Describe a style of music or a sound effect.",
  },
  // Not a page of its own: search models power Knowledge (document search) in Chat and Code.
  embed: {
    verb: "search my documents",
    label: "Document search",
    href: "/knowledge/",
    noun: "search model",
    help: "Find the passages in your documents that answer a question.",
  },
};

export const TASK_ORDER: Task[] = ["chat", "image", "video", "speech", "transcribe", "sound"];
/** Every kind of model, for lists of models (Get models, My models). */
export const MODEL_TASKS: Task[] = [...TASK_ORDER, "embed"];
