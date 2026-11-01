---
title: Chat
description: POST /v1/chat/completions and /v1/completions.
---

## Chat completions

```http
POST /v1/chat/completions
```

Works like OpenAI's endpoint. Requests for GGUF chat models (the usual kind in wanna.sh) are passed through to
[llama.cpp's server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server), so the options it supports work
here too, including:

- `stream: true` for server-sent events, ending with `data: [DONE]`
- `tools` and `tool_choice` for function calling (models whose chat template supports tools)
- `temperature`, `top_p`, `max_tokens`, `stop`, `seed` and the other usual sampling options
- `response_format` for JSON output
- pictures in messages, as `image_url` content parts, for models that can see

```bash
curl http://localhost:7860/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "system", "content": "Answer in one sentence."},
      {"role": "user", "content": "Why is the sky blue?"}
    ]
  }'
```

### Streaming

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:7860/v1", api_key="not-needed")
stream = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a short story."}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

### Pictures

Send a picture as a base64 data URL in an `image_url` part. The model must be able to see pictures; in
**Get models** these say *Can also look at pictures you attach*.

```python
import base64

picture = base64.b64encode(open("photo.jpg", "rb").read()).decode()
reply = client.chat.completions.create(
    model="auto",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "What's in this picture?"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{picture}"}},
        ],
    }],
)
```

### Tools

```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]
reply = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Is it raining in Paris?"}],
    tools=tools,
)
print(reply.choices[0].message.tool_calls)
```

### Running your own tools

wanna.sh can also run [your own tools](/docs/tutorials/tools/) for an app. Add `wanna_tools` to the request: `true` for
every tool that's on, or a list of tool names. The model gets those tools along with any `tools` you send; whenever it
calls one of yours, wanna.sh runs it, gives the model the result, and goes again, until the model answers.

```python
reply = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "What's the weather in Lisbon?"}],
    extra_body={"wanna_tools": ["get_weather"]},
)
print(reply.choices[0].message.content)
```

- The response is an ordinary chat completion. When wanna.sh ran tools on the way, it also has `wanna_messages`: the
  model's tool calls and the results, in order, as `assistant` and `tool` messages. To continue the conversation with
  the model knowing what the tools returned, add them before the reply.
- If the model calls one of **your app's** tools, the response comes back to you as usual (`finish_reason`
  `tool_calls`), with only your app's calls in it. Calls to wanna.sh's tools in that same reply have already run; they're
  in `wanna_messages`.
- With `stream: true`, the answer streams as usual. Tool calls run between rounds, and `wanna_messages` is on the last
  chunk.
- A name that doesn't exist, is turned off, or has a problem gives a `400` error. After 8 rounds of tool calls, the
  model is asked to answer with what it has.
- Needs a GGUF chat model that can use tools.

### Chat models that aren't GGUF

A few chat models run on transformers instead of llama.cpp. For those, wanna.sh supports text messages, with or
without streaming. Tools, pictures and the extra llama.cpp options aren't available.

## Text completions

```http
POST /v1/completions
```

Continue a piece of text without the chat format. Only for GGUF chat models; passed through to llama.cpp.

```bash
curl http://localhost:7860/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "prompt": "Once upon a time", "max_tokens": 40}'
```
