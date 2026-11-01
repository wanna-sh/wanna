---
title: Make your own tools
description: Write a Python function and let the AI use it, in Chat, in Code and from apps through the API.
---

A **tool** is something the AI can do besides writing text: look up the weather, query a database, convert a file. You
write it as a Python function; wanna.sh tells the model what it does, and when the model decides to use it, wanna.sh
runs it and gives the model the result.

You need a chat model that can use tools: in the model menu, models are marked **Can use tools** or **Can't use tools**.

## Write a tool

Open **Tools** in the sidebar and press **New tool**. Each tool is one Python file with a function called `run`:

```python
def run(city: str, units: str = "metric") -> str:
    """Get today's weather for a city. Use it whenever someone asks about the weather.

    Args:
        city: The city, e.g. "Paris".
        units: "metric" or "imperial".
    """
    ...
    return f"{city}: 17 °C, light rain"
```

- **The tool's name** is the file's name: lowercase letters, digits and underscores, like `get_weather`.
- **The docstring** is what the model reads to decide when to use the tool, so say clearly what it does and when it
  helps. Describe each input under `Args:`.
- **Type hints** say what the model must give: `str`, `int`, `float`, `bool`, `list[str]`, `dict`, or
  `Literal["a", "b"]` for a fixed choice. Inputs with a default value are optional.
- **Return** text, or anything JSON can hold (a dictionary, a list, a number). Results are cut off after 20,000
  characters.
- **Printing** is for you: what a tool prints shows up when you test it, but the model doesn't see it.

Below the editor, **What the AI sees** shows the description and inputs the model gets. If something's wrong (no `run`
function, no docstring, a syntax error), the page says what, and the model isn't given the tool until it's fixed.
wanna.sh reads tools without running them, so opening a tool someone sent you is safe.

### Packages

A tool can use packages from PyPI. List them at the top of the file, in the standard
[inline script metadata](https://packaging.python.org/en/latest/specifications/inline-script-metadata/) block (the same
one `uv run` reads):

```python
# /// script
# dependencies = ["requests"]
# ///
import requests

def run(url: str) -> str:
    """Get the HTTP status of a web page."""
    return str(requests.get(url, timeout=10).status_code)
```

They're installed the first time the tool runs.

### Test it

Fill in the inputs under **Test it** and press **Run** to see exactly what the model would get back, how long it took,
and anything the tool printed. Testing works even while a tool is turned off.

## Where tools run

By default a tool runs in a **sandbox**: a Docker container like [Code's](/docs/reference/security/#codes-sandbox).
It can reach the internet, but not your files, your local network or wanna.sh itself, and it can't change the tools
folder. A tool has a minute to finish. The sandbox needs [Docker](/docs/tutorials/code/#before-you-start).

A tool that needs your files or a service on your network can be **trusted to run on this computer**: tick it on the
tool's page. A trusted tool can do anything you can, so only trust one you wrote, or whose code you've read and
understood. Trust belongs to the file exactly as it was when you ticked it: if the file changes, even from outside
wanna.sh, the tool goes back to the sandbox until you trust it again.

## Use tools

- **Chat:** when you have tools that are on, a **Tools** switch appears next to **Web**. With it on, the model uses your
  tools when they help, and the answer says which it used.
- **Code:** the agent can use every tool that's on, alongside its own. With *Ask before commands* (the default), it asks
  before using a trusted tool, as it does before running a command.
- **Apps:** add `"wanna_tools": true` to a chat request and wanna.sh runs your tools for the app. See
  [Chat API: running your own tools](/docs/api/chat/#running-your-own-tools).

Turn a tool off on its page to keep it from the model everywhere.

## Share tools

Tools are plain files in `~/.wanna/tools` (on Windows, `C:\Users\<you>\.wanna\tools`). Write them in your own editor,
keep them in git, or send them to someone: a file put in that folder shows up on the Tools page. Whether a tool is on
or trusted is kept by wanna.sh, not in the file, so a shared tool always arrives on, in the sandbox.
