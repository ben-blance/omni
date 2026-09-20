"""
Per-file codec selection for the SATISH multi-codec container.

Every file in an archive gets exactly one codec:
  - "omni_python" — the trained neural engine (Python source only). All
    files using this codec share ONE combined payload (cross-file context),
    handled entirely by engine.py — this module never touches it.
  - "zlib"         — generic lossless compression, for text-like/structured
    files with no dedicated OMNI codec yet (Markdown, YAML, JSON, HTML, ...).
  - "store"         — no compression at all, for formats that are already
    compressed (images, archives, media) where re-compressing wastes CPU
    and can even grow the file slightly.

Adding a new OMNI codec later (JS, YAML, ...) means adding a new codec name
here and a case in cli.py's encode/decode switch — it does not change the
container format itself (see satish.py).
"""

from __future__ import annotations

import zlib
from pathlib import Path

CODEC_OMNI_PYTHON = "omni_python"
CODEC_ZLIB = "zlib"
CODEC_STORE = "store"

CODEC_VERSION = 1  # versions the store/zlib codecs; independent of the engine

_PYTHON_EXTS = {"py", "pyi"}

# Formats that are already compressed (or gain nothing from a generic zlib
# pass) — stored as-is rather than wasting CPU / risking slight growth.
_ALREADY_COMPRESSED_EXTS = {
    "png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "avif", "heic",
    "zip", "gz", "tgz", "xz", "bz2", "7z", "rar", "whl", "jar",
    "mp3", "mp4", "mov", "avi", "mkv", "flac", "ogg", "webm", "m4a",
    "pdf", "woff", "woff2", "ttf", "otf", "eot",
    "pyc", "so", "dylib", "dll", "exe", "o", "a",
}

# Extension -> human-readable file_type label, for `omni info`'s breakdown.
# Anything not listed falls back to its bare extension, or "other" if none.
_TYPE_NAMES = {
    "py": "python", "pyi": "python",
    "md": "markdown", "rst": "text", "txt": "text", "adoc": "text",
    "yaml": "yaml", "yml": "yaml",
    "json": "json", "toml": "toml", "ini": "config", "cfg": "config",
    "html": "html", "htm": "html", "css": "css", "scss": "css",
    "js": "javascript", "jsx": "javascript", "ts": "typescript", "tsx": "typescript",
    "xml": "xml", "svg": "svg", "sh": "shell", "bash": "shell",
    "png": "png", "jpg": "jpeg", "jpeg": "jpeg", "gif": "gif", "webp": "webp",
    "zip": "archive", "whl": "archive", "tar": "archive", "gz": "archive",
    "pdf": "pdf",
}


def classify(path: Path) -> tuple[str, str]:
    """Returns (file_type, codec) for a file based on its extension."""
    ext = path.suffix.lstrip(".").lower()
    if ext in _PYTHON_EXTS:
        return _TYPE_NAMES.get(ext, ext), CODEC_OMNI_PYTHON
    file_type = _TYPE_NAMES.get(ext, ext if ext else "other")
    if ext in _ALREADY_COMPRESSED_EXTS:
        return file_type, CODEC_STORE
    return file_type, CODEC_ZLIB


def encode(codec: str, data: bytes) -> bytes:
    if codec == CODEC_STORE:
        return data
    if codec == CODEC_ZLIB:
        return zlib.compress(data, 9)
    raise ValueError(f"unknown generic codec: {codec}")


def decode(codec: str, data: bytes) -> bytes:
    if codec == CODEC_STORE:
        return data
    if codec == CODEC_ZLIB:
        return zlib.decompress(data)
    raise ValueError(f"unknown generic codec: {codec}")
