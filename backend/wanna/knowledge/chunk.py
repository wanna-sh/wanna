"""Split documents into passages of a few hundred words, keeping the heading each one sits under.

Passages are what search finds and what the model reads, so they should be big enough to answer a question on their
own and small enough that several fit in the model's memory.
"""

from __future__ import annotations

import re

TARGET = 1400  # characters, about 300 to 400 tokens
OVERLAP = 200  # carried over from the end of the previous passage, so ideas split across a boundary are still found
CODE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs",
            ".rb", ".php", ".swift", ".sh", ".ps1", ".sql", ".css", ".scss")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)


def _front_matter(text: str) -> tuple[str | None, str]:
    """Markdown front matter (YAML between --- lines): use its title and description, drop the rest."""
    m = _FRONT_MATTER.match(text)
    if not m:
        return None, text
    fields = dict(re.findall(r"^(title|description):\s*[\"']?(.*?)[\"']?\s*$", m.group(1), re.M))
    body = text[m.end():]
    if fields.get("description"):
        body = fields["description"] + "\n\n" + body
    return fields.get("title"), body


def chunks(pages: list[tuple[int | None, str]], name: str) -> list[dict]:
    """[{"text", "page", "heading"}, ...] for a document's pages."""
    code = name.lower().endswith(CODE_EXT)
    out: list[dict] = []
    path: list[tuple[int, str]] = []  # Markdown heading trail as (level, title), e.g. [(1, "Install"), (2, "Windows")]
    for n, (page, text) in enumerate(pages):
        if n == 0 and not code:
            title, text = _front_matter(text)
            if title:
                path = [(0, title)]  # above any heading level, so it stays at the top of the trail
        blocks = _code_blocks(text) if code else _blocks(text)
        buf, heading = "", " > ".join(t for _, t in path)
        for block in blocks:
            m = None if code else _HEADING.match(block)
            if m:
                if buf.strip():
                    out.append({"text": buf.strip(), "page": page, "heading": heading})
                    buf = ""
                level = len(m.group(1))
                while path and path[-1][0] >= level:
                    path.pop()
                path.append((level, m.group(2)))
                heading = " > ".join(t for _, t in path)
                buf = block + "\n\n"
                continue
            for piece in _split_long(block):
                if buf and len(buf) + len(piece) > TARGET:
                    out.append({"text": buf.strip(), "page": page, "heading": heading})
                    buf = _tail(buf)
                buf += piece + ("\n" if code else "\n\n")
        if buf.strip() and not _HEADING.match(buf.strip()):
            out.append({"text": buf.strip(), "page": page, "heading": heading})
    return [c for c in out if len(c["text"]) >= 20 or len(out) == 1]


def _blocks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n")
    blocks, fence = [], None
    for part in re.split(r"\n\s*\n", text):
        part = part.strip("\n")
        if not part.strip():
            continue
        # Keep fenced code blocks whole, even when they contain blank lines.
        if fence is not None:
            fence += "\n\n" + part
            if part.rstrip().endswith("```"):
                blocks.append(fence)
                fence = None
            continue
        if part.lstrip().startswith("```") and part.count("```") % 2 == 1:
            fence = part
            continue
        # A heading glued to its first paragraph: separate them.
        lines = part.split("\n")
        if _HEADING.match(lines[0]) and len(lines) > 1:
            blocks += [lines[0], "\n".join(lines[1:])]
        else:
            blocks.append(part)
    if fence:
        blocks.append(fence)
    return blocks


def _code_blocks(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").split("\n")
    return ["\n".join(lines[i:i + 40]) for i in range(0, len(lines), 40)]


def _split_long(block: str) -> list[str]:
    if len(block) <= TARGET:
        return [block]
    parts = re.split(r"(?<=[.!?])\s+|\n", block)
    out, buf = [], ""
    for p in parts:
        if buf and len(buf) + len(p) > TARGET:
            out.append(buf.strip())
            buf = ""
        while len(p) > TARGET:  # one enormous sentence or line
            out.append(p[:TARGET])
            p = p[TARGET:]
        buf += p + " "
    if buf.strip():
        out.append(buf.strip())
    return out


def _tail(buf: str) -> str:
    tail = buf[-OVERLAP:]
    cut = tail.find(" ")
    return (tail[cut + 1:] if cut >= 0 else tail) + " "
