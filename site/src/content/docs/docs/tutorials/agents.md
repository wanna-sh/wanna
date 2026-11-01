---
title: Run an agent around the clock
description: An AI that works on its own toward goals you give it, with a computer of its own, schedules, webhooks and notifications.
---

**Agents** are AIs that keep running. Give one goals and turn it on, and it works toward them by itself, day and night,
on your own chat model. It has a Linux computer of its own (a sandbox, like [Code](/docs/tutorials/code/)), where it can
write and run programs and keep them running. It wakes itself on a schedule, other apps can wake it, and it tells you
when something needs you.

What it does is up to you. For example:

- Watch a website and notify you straight away when it's down or slow.
- Run a Discord bot for your server, and tell you about questions it can't answer.
- Read the news every morning and send you what matters to you.
- Research a topic and keep a report up to date.

## Before you start

- **Docker** must be installed and running. Everything the agent runs happens in its sandbox, never directly on your
  computer. See [What its computer can reach](#what-its-computer-can-reach).
- **A chat model that can use tools.** Bigger models do much better at working on their own: a model of 14B or more
  is a good start.
- **wanna.sh has to keep running.** Agents work while wanna.sh is running. If you close the desktop app, they stop and
  come back on when you open it again. For a true 24/7 agent, run wanna.sh with [Docker](/docs/start/docker/) or on
  Linux, on a computer that stays on. While an agent is on, wanna.sh keeps the computer from going to sleep when it's
  left idle (not in Docker); closing a laptop's lid or choosing Sleep still puts it to sleep.

## Create an agent

1. Open **Agents**.
2. Give it a **Name** and **Goals**: what it should do, for as long as it's on. Be specific about when to tell you
   things. It sees the goals at every step, and you can change them later.
3. Choose **How it works**:
   - **Thinks when needed**: it works, then waits until something happens (a message, a schedule or its own
     programs). Best for most agents.
   - **Always thinking**: it keeps working toward its goals without stopping, resting at most 15 minutes at a time.
     For research and other open-ended goals. It keeps your graphics card busy.
4. Pick a **Model** and press **Create and turn on**.

**Turn off** stops it thinking; programs it keeps running carry on in its sandbox until you **Stop its sandbox and
services** in its settings. Agents that were on come back on when wanna.sh starts.

## Watching it work

Everything it does appears as it happens: what it's thinking, each command and file change, what woke it up and what
it told you. You can message it at any time from the box at the bottom; it reads your message at its next step (or
when you turn it on).

The panels on the right show:

- **Status**: the programs it keeps running (with their logs), its schedules and its notifications.
- **Plan**: its to-do list.
- **Files**: its workspace. `MEMORY.md` holds the notes it keeps for itself.
- **Preview**: web servers it starts on port 3000, 5173, 8000 or 8080, to open in your browser.

## How an agent spends its time

An agent works in steps: each step is one reply from the model, which can use tools. Between steps, things arrive in
its inbox:

| From | What |
| --- | --- |
| **You** | Messages from its page or the API. |
| **Schedule** | Times it set for itself, once or regularly ("check the status page every hour"). |
| **Its programs** | Anything its own programs write to `/workspace/.inbox/` (one file per message, text or JSON). |
| **Webhook** | Text or JSON other apps post to its webhook link. |
| **wanna.sh** | Things wanna.sh tells it, such as a program of its that crashed. |

Local models can't think about every single event around the clock, so a good agent writes programs for the routine
part and only wakes itself for what needs judgement. A site watcher checks the site every minute in a small program,
and wakes the agent only when the site is down. A Discord bot answers simple questions itself and hands the agent the
hard ones.

### Programs that keep running

Programs the agent keeps running are **services**: a bot, a server, a poller. wanna.sh starts them again when they
stop, after a restart of wanna.sh or of the computer, and tells the agent when it had to. A service that stops 5 times in
10 minutes isn't restarted again until the agent fixes it. Each service's output goes to `.agent/logs/<name>.log`
in the workspace (the **Log** link under **Status**).

### Memory

The conversation is the agent's short-term memory. When it fills most of the model's memory, the agent summarises it
for itself and carries on from the summary; you'll see *Summarised its memory to make room*, and can open the summary.
For what it must not forget, it keeps notes in `MEMORY.md`, which it sees at every step. Set **Memory** in its settings
to keep more in mind before it summarises.

## Notifications

When the agent has something for you, it sends a notification. It shows on the agent's page, as a badge next to
**Agents** in the menu, and, if you allow it, as a notification on your computer while wanna.sh is open.

To get them on your phone, put a link in **Send notifications to** in its settings:

| Link | Where it goes |
| --- | --- |
| `https://ntfy.sh/<your-topic>` (or your own ntfy server) | The [ntfy](https://ntfy.sh/) app on your phone. Urgent ones arrive with high priority. Pick a topic name nobody would guess. |
| A Discord webhook (`https://discord.com/api/webhooks/...`) | A Discord channel. |
| A Slack webhook (`https://hooks.slack.com/...`) | A Slack channel. |
| Any other link | A POST with JSON: `agent`, `title`, `message`, `urgent` and `time`. |

## Wake it from other apps

Every agent has a **Webhook** link in its settings. Anything posted to it arrives in the agent's inbox, marked as a
webhook, and wakes it:

```bash
curl -X POST http://localhost:7860/api/agents/<id>/hook/<token> \
  -H "Content-Type: application/json" \
  -d '{"alert": "CPU over 90% on web-1"}'
```

The link works without an API key, so keep it private. **Make a new link** replaces it if it leaks. Bodies can be up to
100 KB.

## Secrets

Programs often need a token or password: a Discord bot token, an API key. Add them under **Secrets** in its settings.
They're given to its services as environment variables (the agent is told their names, not their values), and if a
value shows up in a command's output it's hidden before the model sees it.

The agent's own programs can still read them, so a determined agent could reveal one. Give it tokens that can only do
what it needs, and keep wanna.sh private. Secrets are stored in the agent's settings file on this computer.

## Settings

| Setting | What it does |
| --- | --- |
| **Pace** | Thinks when needed, or always thinking. |
| **Approval** | **Don't ask** (the default) lets it work on its own. **Ask before commands** makes commands and new services wait for you; the agent stops until you answer, so only use it while you're watching. |
| **Knowledge** | Libraries of your documents it can search. See [Ask about your documents](/docs/tutorials/knowledge/). |
| **Most steps an hour** | A limit on how much it works, 120 by default. When it reaches it, it rests until the hour is up. |
| **Memory** | How much it keeps in mind before summarising, as in Code. |

## The agent's tools

It has all of [Code's tools](/docs/tutorials/code/#the-agents-tools), your own [tools](/docs/tutorials/tools/), and:

| Tool | What it does |
| --- | --- |
| `wait` | Pause until something arrives, or for a while. |
| `schedule`, `unschedule` | Wake itself later, once or regularly. |
| `notify` | Send you a notification. |
| `service_start`, `service_stop`, `service_list` | Keep programs running, stop them, and check on them. |

## Keeping it on track

Small models working alone can get stuck. wanna.sh helps:

- If it makes exactly the same call three times in a row, it's asked to step back and try another way.
- If a step fails (the model stopped, it ran out of memory), it tries again after a pause that grows from 15 seconds to
  10 minutes, and notifies you if it keeps failing. A message from you makes it try again straight away.
- **Most steps an hour** caps how much it does.

It treats text from webhooks, websites and other people as information, not instructions: only its goals and your own
messages tell it what to do. That makes it harder, but not impossible, for someone to talk it into something. Don't
give an agent more than its goals need.

## What its computer can reach

An agent's sandbox is the same kind as Code's, with the same firewall: the internet yes; your computer, your local
network and wanna.sh itself no. Its workspace is `~/.wanna/agents/<id>/workspace/`; it can't see your other files.
See [What the sandbox can reach](/docs/tutorials/code/#what-the-sandbox-can-reach) and
[Security](/docs/reference/security/#agents).

:::caution
Anyone who can open wanna.sh can create agents and read their secrets' names and webhook links. Keep wanna.sh private to
your computer, or turn on [Require API key](/docs/guides/network/) before sharing it.
:::

## From the API

Agents are under `/api/agents`: list and create them (`GET`, `POST`), change settings (`PATCH /api/agents/<id>`), turn
them on and off (`POST .../on`, `.../off`), send a message (`POST .../message` with `{"text": "..."}`) and follow what
they do (`GET .../events`, Server-Sent Events). The interactive docs at `/docs` list them all.
