---
title: Train a chat model
description: Teach a chat model your writing voice, or how to answer, from your own writing or example chats.
---

**Train** can teach a chat model two things:

- **Your writing voice:** from things you've written (emails, posts, stories). Afterwards it answers and writes the
  way you do.
- **How to answer:** from example chats, *when asked this, answer like this*. For a tone, a format or a role, such
  as a shop's helper that always answers briefly and signs its replies.

It trains on this computer, and your examples never leave it. The result is a chat model of its own, named after
what you trained, in [Chat](/docs/tutorials/chat/), [Code](/docs/tutorials/code/) and the [API](/docs/api/chat/).

It learns a way of writing, not facts. For answers from your own documents, use
[Knowledge](/docs/tutorials/knowledge/) instead.

## What you need

- **An NVIDIA graphics card.** How big depends on the chat model; see [How big a model can train](#how-big-a-model-can-train).
  Training on a Mac or on the processor isn't supported yet.
- **A chat model**, from **Get models → Chat**. Training starts from it.
- **The AI libraries.** If they're missing, the Train page offers to install them. If you installed them before
  wanna.sh 0.7, it asks to add the libraries training needs (PEFT, and bitsandbytes for training in 4 bits).
- **Disk space** for two one-time downloads and copies, described in [What it downloads](#what-it-downloads).

## 1. Choose what to teach

Open **Train** in the sidebar, choose **Chat** at the top, and under **What do you want to teach it?** choose **Your
writing voice** or **How to answer**.

## 2. Add your examples

**For your writing voice**, drop text, Markdown or PDF files onto the page, or paste your writing into the box (with a
blank line between pieces). At least 300 words; 2,000 or more works best. Use only your own writing, in the voice you
want, and several pieces on different subjects rather than one long piece on one subject.

**For how to answer**, add example chats, at least 10; 50 or more works best. Type them on the page (a question and
the answer you want), or drop a file:

- **.jsonl**, one chat per line, in OpenAI's format:
  `{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}`. A `system`
  message and several turns are fine. Lines with `prompt` and `reply` fields work too (also `question` and `answer`,
  or `input` and `output`).
- **.json**, a list of the same.
- **.csv**, with the question in the first column and the answer in the second. A header row is skipped.

Answer every example the way you want it to answer: the same tone, the same format.

## 3. Name it

The name is for you, such as *My voice* or *Shop helper*. The trained model is called after it and the model it came
from, for example *My voice (Qwen3-8B-GGUF)*.

## 4. Choose the chat model and train

Choose the chat model to start from. The page says how it will train on your computer and estimates how long it will
take. Bigger models write better, but take longer to train and need more memory.

Press **Start training**. If the graphics card it uses is short of free memory, wanna.sh stops its own models on
that card first. You can keep using the rest
of wanna.sh meanwhile, and leave the page: progress shows when you come back. **Stop** ends a run early. Closing
wanna.sh stops training; press **Train again** to start it over with the same examples.

As a guide, on an RTX 3060 12 GB:

| Chat model | Examples | Time | Graphics memory |
| --- | --- | --- | --- |
| Llama 3.2 1B | 730 words of writing | under 2 minutes, including its first download | 2.8 GB |
| Qwen3 8B (in 4 bits) | 30 example chats | about 4 minutes, plus about 7 minutes once to make its copy | 7.0 GB |

## 5. Use it

When it's done, the Train page shows its replies to a few questions next to the model's replies before training.
Press **Use it in Chat** to chat with it. Afterwards, choose it from the model list in Chat or Code like any other
model, or pass its id (shown in **My models**) as `model` in the [API](/docs/api/chat/).

If its replies started to repeat themselves at full strength, wanna.sh turns it down until they don't (to 75% or 50%)
and says so on the Train page. Training a new one with more, more varied examples helps.

If it doesn't sound enough like your examples, train a new one with more examples, or with more **Training steps**
(under **Show advanced settings**). Too many steps make it repeat your examples instead of answering.

## How big a model can train

Training holds the chat model's original version in graphics memory. wanna.sh picks the way that fits:

- **At full precision** on one card, when it fits: about 2 GB per billion parameters, plus some room.
- **Compressed to 4 bits** (QLoRA) when it doesn't: about 0.75 GB per billion parameters, plus about 1 GB. An 8B
  model trains on a 12 GB card this way.
- **Across several cards** when one isn't enough, at full precision or in 4 bits.

So the biggest model you can train depends on your graphics memory, added up over your cards. The page says how each
model would train, or why it can't.

## What it downloads

GGUF files, which chat models run from, can't be trained. So the first time you train a model, wanna.sh also:

1. **Downloads the model's original version** from Hugging Face, about 2 GB per billion parameters (16 GB for an 8B
   model), into `~/.wanna/models/originals`. It finds it from the model card of the chat model you have. If the
   original needs permission to download (Meta's Llama models, for example), it uses an identical copy published by
   Unsloth, or the original itself if you've accepted its licence on Hugging Face and added your token in Settings.
2. **Makes a copy of the chat model from that original**, compressed the same way as yours (for example Q4_K_M),
   into `~/.wanna/models/matched`. The trained model runs on this copy, so it runs on exactly the weights it learned
   from. A published GGUF can come from slightly different weights than the original its card names, and what was
   learned on one can fail on the other.
3. **Downloads llama.cpp's converter** (about 40 MB) into `~/.wanna/engines/llama-convert`, to turn what it learned
   into a file llama.cpp reads.

Training the same model again reuses all three. You can delete `~/.wanna/models/originals` to free space; it's
downloaded again if you train that model again.

## Where it's kept

Each trained chat model is a folder in `~/.wanna/training`: your examples, what it learned (`lora.gguf`, a llama.cpp
LoRA adapter: 22 MB for Llama 3.2 1B, 87 MB for Qwen3 8B; and `adapter/`, the same in the format Hugging Face's PEFT reads), and the sample
replies. **Delete** on the Train page, or deleting the trained model in **My models**, removes the folder, and the
copy in `models/matched` once no trained model uses it.

## What doesn't work yet

- Chat models whose model card doesn't name the model they were made from, and ones whose original isn't a set of
  safetensors files, can't be trained. The page says so.
- Models of a kind llama.cpp's converter doesn't support can't be turned into an adapter. Training fails at the end
  with a message saying so.
- Models that also see pictures are trained on their text part only. Whether the trained model still sees pictures
  hasn't been tested yet.
