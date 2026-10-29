---
title: Chat with an assistant
description: Ask questions, attach pictures and documents, dictate messages and give the assistant standing instructions.
---

**Chat** is where you talk to a language model: ask questions, draft and rewrite text, summarise documents or get help
with code.

![The Chat page](../../../../assets/screens/chat.webp)

## Send a message

Type in the box at the bottom and press **Enter**. **Shift+Enter** adds a new line. Replies stream in as they're
written; press **Stop** to cut one short.

Choose the model with the **Model** menu under the message box. If you haven't installed a chat model yet, get one
from [Get models](/docs/guides/models/) first.

## Attach pictures and documents

Press **Attach**, or drop or paste files into the message box.

- **Pictures** work with models that can see, such as Gemma 3 and Gemma 4 or Qwen-VL models. Ask "What's in this
  picture?" or "Turn this whiteboard into notes". If the model can't read pictures, wanna.sh tells you before you send.
- **Documents**: PDFs and text files (Markdown, CSV, JSON, HTML, code files and more). wanna.sh extracts the text and
  adds it to your message. If a document is too long for the model to hold in mind, wanna.sh
  [searches it for each question instead](/docs/tutorials/knowledge/#long-attachments-in-chat), once document search
  is set up. Without document search, only the first part is sent, and the attachment says *first part*.

:::note
Scanned PDFs are pictures of pages with no text inside, so there's nothing to extract. Take a screenshot of the page and
attach it as a picture to a model that can see instead.
:::

## Speak instead of typing

Press the microphone button, speak, and press it again to stop. Your words are turned into text in the message box, so
you can check them before sending. This uses your [transcription model](/docs/tutorials/transcribe/), so install one
first (Whisper models work well). Your browser will ask for permission to use the microphone.

## Ask about your own documents

Press **Knowledge** to pick libraries of your documents. Answers then use the passages that match each question and
cite them, with the sources listed underneath. See [Ask about your documents](/docs/tutorials/knowledge/).

## Search the web

With **Web** on (it is, unless you turn it off), the assistant can search the web and read pages when a question
needs something it doesn't know, like today's news or the latest version of something. You'll see what it's doing
(*Searching the web for…*, *Reading python.org…*), and the pages it read are listed under its answer.

- **It needs a model that can use tools.** Most recent models can, such as Qwen 3 and 3.5, and Llama 3.1 and newer.
  With one that can't, **Web** is greyed out.
- **Bigger models use it better.** In testing, a 9B model read the right pages and answered correctly, while a 4B
  model sometimes answered from search snippets alone and got details wrong. Check important facts in the pages it
  lists.
- **Privacy:** the searches go to a search engine and the pages are fetched from your computer. What's sent is the
  search the model writes, not your conversation. Press **Web** to turn it off and keep a chat entirely on your
  computer; it's remembered for that chat. See [Security and privacy](/docs/reference/security/#privacy).

## Give the assistant instructions

Press **Instructions** to set guidance the assistant follows for the whole conversation, for example *"You are a
patient tutor. Keep answers short."* The button shows **Instructions (on)** while some are set.

## Manage your chats

Press **Chats** at the top to see your conversations. You can search them, open an old one to carry on, and:

- **Archive** a chat to tidy it away without deleting it, or **Archive all**. Find them again under **Archived**.
- **Delete** a single chat, **Delete archived**, or **Delete all chats**.

Press **New chat** to start fresh.

:::caution
Conversations are saved in your browser only. Clearing your browser's site data, or using a different browser,
starts you with an empty list.
:::

## Longer conversations

How much of a conversation a model can keep in mind is its *memory* (also called context). The default is
**Standard (8K)**, about 6,000 words. For long documents, choose a larger size in **Settings → Chat memory**, or per
model under **My models → Options**. See [Graphics cards and memory](/docs/guides/hardware/).
