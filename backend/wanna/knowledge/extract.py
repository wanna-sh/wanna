"""Text from documents: PDFs page by page, and anything that is plain text (Markdown, CSV, code...)."""

from __future__ import annotations

import io


class ExtractError(Exception):
    """A problem the person can fix (wrong kind of file, password protected...)."""


def extract(data: bytes, name: str, max_chars: int) -> tuple[list[tuple[int | None, str]], int | None, bool]:
    """Return ([(page number or None, text), ...], page count, truncated). Stops once max_chars is reached."""
    if name.lower().endswith(".pdf") or data[:5] == b"%PDF-":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ExtractError("This PDF is password protected. Unlock it and add it again.")
            parts, total = [], 0
            for i, page in enumerate(reader.pages, 1):
                t = page.extract_text() or ""
                parts.append((i, t))
                total += len(t)
                if total > max_chars:
                    break
        except PdfReadError as e:
            raise ExtractError(f"Couldn't read this PDF: {e}")
        if not any(t.strip() for _, t in parts):
            raise ExtractError(
                "This PDF has no selectable text (it may be scanned pictures of pages), so there's nothing to read.")
        return _cap(parts, max_chars) + (len(reader.pages), total > max_chars)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    if "\x00" in text[:4096]:
        raise ExtractError("This doesn't look like a text document. Use a PDF, text, Markdown, CSV or code file.")
    return _cap([(None, text)], max_chars) + (None, len(text) > max_chars)


def _cap(parts: list[tuple[int | None, str]], max_chars: int) -> tuple[list[tuple[int | None, str]]]:
    out, left = [], max_chars
    for page, text in parts:
        if left <= 0:
            break
        out.append((page, text[:left]))
        left -= len(text)
    return (out,)
