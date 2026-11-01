"""Pictures for search models that can see them: what counts as a picture, and getting it into a form llama.cpp reads."""

from __future__ import annotations

import base64
import io
import re

# llama.cpp decodes these itself (stb_image).
READABLE = {"png": b"\x89PNG", "jpeg": b"\xff\xd8\xff", "gif": b"GIF8", "bmp": b"BM"}
PICTURE_NAME = re.compile(r"\.(png|jpe?g|gif|bmp|webp|tiff?|heic|heif|avif)$", re.I)
MAX_BYTES = 20 * 1024 * 1024


class PictureError(Exception):
    """A picture that can't be used, with what to do about it."""


def kind(data: bytes) -> str | None:
    """"png", "jpeg", "gif", "bmp", "webp" or other picture formats Pillow knows; None if it isn't a picture."""
    for name, magic in READABLE.items():
        if data.startswith(magic):
            return name
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypavif"):
        return "heic"
    return None


def is_picture(data: bytes, name: str = "") -> bool:
    return kind(data) is not None or bool(PICTURE_NAME.search(name))


def readable(data: bytes) -> bytes:
    """The picture as PNG, JPEG, GIF or BMP. Other formats are converted with Pillow when it's installed (it comes with
    the AI libraries for pictures and video)."""
    if len(data) > MAX_BYTES:
        raise PictureError("This picture is over 20 MB. Save a smaller copy and try again.")
    k = kind(data)
    if k in READABLE:
        return data
    try:
        from PIL import Image
    except ImportError:
        raise PictureError("Use a PNG, JPEG, GIF or BMP picture. Other formats (such as WebP or HEIC) can be read "
                           "once the AI libraries for pictures are installed.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            out = io.BytesIO()
            im.convert("RGB").save(out, "PNG")
            return out.getvalue()
    except Exception as e:  # Pillow raises many kinds of errors for files it can't read
        raise PictureError(f"Couldn't read this picture: {e}")


def from_data_url(url: str) -> bytes:
    """Bytes from a data URL ("data:image/png;base64,...") or plain base64."""
    payload = url.split(",", 1)[1] if url.startswith("data:") else url
    try:
        return base64.b64decode(payload, validate=False)
    except (ValueError, TypeError):
        raise PictureError("The picture isn't valid base64.")
