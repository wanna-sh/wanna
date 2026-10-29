---
title: FAQ
description: Common questions about wanna.sh.
---

### Is it really free?

Yes. wanna.sh is open source under the MIT licence: no accounts, subscriptions or usage limits. The models are made by
others and have their own licences, shown on their Hugging Face pages. Check them before using a model commercially.

### Does anything I type leave my computer?

No. Prompts, chats, documents and everything you make stay on your computer. wanna.sh connects to the internet to find
and download models and the chat engine, and Code's web tools fetch the pages and searches the agent asks for.

### Does it work offline?

Yes, once the models you want are downloaded. Finding and downloading new models needs a connection.

### How is it different from Ollama, LM Studio or Open WebUI?

Those focus on chat. wanna.sh covers chat, pictures, video, voices, transcription, music and coding in one app, rates
models for your hardware before you download them, and spreads models across several graphics cards automatically. It
also offers OpenAI-compatible endpoints for images, audio and video, not just chat.

### Can I use models I already downloaded elsewhere?

Not yet: wanna.sh downloads models through **Get models** so it knows how to run them.

### Can I use it with AMD or Intel graphics?

Not yet. Without an NVIDIA card, models run on the processor. On a Mac, chat models use Apple's Metal graphics.

### Which chat model should I start with?

The best one marked **Runs great here** that has a version of reasonable size. For most computers, a Qwen or Llama
model of 3B to 8B parameters is a good balance of speed and quality. For [Code](/docs/tutorials/code/), use the biggest
model that runs well.

### Can several people use it at once?

Yes, through the API or from other devices on your network. See [Share on your network](/docs/guides/network/).

### How do I contribute?

The code is on [GitHub](https://github.com/surajkumar/wanna.sh). Issues and pull requests are welcome.
