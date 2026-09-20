"""
Per-file codec selection for the SATISH multi-codec container.

Every file in an archive lands in exactly one of three lanes:
  - "omni_python"  — the trained neural engine (Python source only). All
    files using this codec share ONE combined payload (cross-file
    context), handled entirely by engine.py — this module never touches it.
  - "xz_stream"    — generic lossless compression, for text-like/structured
    files with no dedicated OMNI codec yet (Markdown, YAML, JSON, HTML,
    ...). ALL such files in one archive are concatenated and compressed as
    ONE xz/LZMA stream, not compressed independently — independent per-file
    compression can't see redundancy across files (repeated license
    headers, near-identical config/CI files, shared doc boilerplate), which
    is exactly what a whole-archive classical compressor like tar+xz
    exploits. This mirrors the same "cross-file context" lesson the Python
    codec already learned. xz/LZMA specifically (not zstd) because measuring
    both on real mixed-repo content showed xz meaningfully smaller on this
    kind of text-heavy data at max settings — zstd is the faster choice,
    xz is the smaller one, and ratio is what this container optimizes for.
  - "store"        — no compression at all, for formats that are already
    compressed (images, archives, media) where re-compressing wastes CPU
    and can even grow the file slightly. Deliberately NOT folded into the
    xz stream, even for consistency — there's nothing for it to find.

Adding a new OMNI codec later (JS, YAML, ...) means adding a new codec name
here and a case in cli.py's encode/decode switch — it does not change the
container format itself (see satish.py).
"""

from __future__ import annotations

import lzma
from pathlib import Path

CODEC_OMNI_PYTHON = "omni_python"
CODEC_GENERIC_STREAM = "xz_stream"
CODEC_STORE = "store"

CODEC_VERSION = 1  # versions the xz_stream/store codecs; independent of the engine
_XZ_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}]

_PYTHON_EXTS = {"py", "pyi"}

# Formats that are already compressed (or gain nothing from a generic
# compression pass) — stored as-is rather than wasting CPU / risking
# slight growth, and kept OUT of the shared xz stream for the same reason.
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
    """Returns (file_type, codec) for a file based on its extension alone.
    For extensions in _ALREADY_COMPRESSED_EXTS this is only a tentative
    STORE — see prefer_compression(), which makes the actual call
    empirically rather than trusting the extension: some "already
    compressed" formats (e.g. unoptimized PNG screenshots) still have real
    headroom, and hardcoding an assumption either way is exactly what
    caused that to be missed in the first place."""
    ext = path.suffix.lstrip(".").lower()
    if ext in _PYTHON_EXTS:
        return _TYPE_NAMES.get(ext, ext), CODEC_OMNI_PYTHON
    file_type = _TYPE_NAMES.get(ext, ext if ext else "other")
    if ext in _ALREADY_COMPRESSED_EXTS:
        return file_type, CODEC_STORE
    return file_type, CODEC_GENERIC_STREAM


def prefer_compression(raw: bytes) -> bool:
    """Empirically decide whether compressing this file actually shrinks
    it, rather than trusting classify()'s extension-based guess for STORE
    candidates. Uses the same settings the shared stream itself compresses
    at, since the question is "would this file benefit from the same
    treatment", not some other threshold."""
    return len(lzma.compress(raw, format=lzma.FORMAT_XZ, filters=_XZ_FILTERS)) < len(raw)


def compress_stream(chunks: list[bytes]) -> bytes:
    """Concatenates and compresses every xz_stream file's raw bytes as ONE
    block. Caller tracks each file's (offset, length) into the concatenated
    (pre-compression) bytes to slice it back out later."""
    return lzma.compress(b"".join(chunks), format=lzma.FORMAT_XZ, filters=_XZ_FILTERS)


def decompress_stream(payload: bytes) -> bytes:
    if not payload:
        return b""
    return lzma.decompress(payload, format=lzma.FORMAT_XZ)
