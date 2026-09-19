"""
SATISH — the public, documented container format OMNI writes and reads.

This module is the reference implementation of the spec in
docs/satish-format.md. Keep the two in sync: if you change the byte layout
here, update the doc in the same change.

SATISH deliberately knows nothing about *how* the payload was produced —
that's the engine's job (see engine.py). SATISH only wraps that opaque
payload with a self-describing header, so a `.satish_<generation>` file
always says which model it needs, what shape its engine payload is in, and
what files it reconstructs to, without requiring the caller to guess.
"""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass

MAGIC = b"SATI"
FORMAT_VERSION = 1


@dataclass
class ParsedSatish:
    generation: str
    generation_year: int
    engine_format_version: int
    root: str
    files: list[str]
    payload: bytes
    checksum_ok: bool


def extension_for(generation: str) -> str:
    return f".satish_{generation.lower()}"


def pack(generation: str, generation_year: int, engine_format_version: int,
         root: str, files: list[str], payload: bytes) -> bytes:
    """Wrap an engine-produced payload in a SATISH header."""
    manifest = zlib.compress(
        json.dumps({"root": root, "files": files}).encode("utf-8"), 9
    )
    gen_bytes = generation.lower().encode("utf-8")
    checksum = zlib.crc32(payload) & 0xFFFFFFFF

    out = bytearray()
    out += MAGIC
    out += struct.pack(">B", FORMAT_VERSION)
    out += struct.pack(">B", len(gen_bytes)) + gen_bytes
    out += struct.pack(">H", generation_year)
    out += struct.pack(">B", engine_format_version)
    out += struct.pack(">I", len(manifest)) + manifest
    out += struct.pack(">I", checksum)
    out += struct.pack(">I", len(payload)) + payload
    return bytes(out)


def parse(data: bytes) -> ParsedSatish:
    """Unwrap a SATISH header. Does not touch the engine — the payload is
    returned opaque, ready to hand to engine.decompress_sources()."""
    if data[:4] != MAGIC:
        raise ValueError("not a SATISH file (bad magic bytes)")
    pos = 4

    (fmt_version,) = struct.unpack_from(">B", data, pos); pos += 1
    if fmt_version != FORMAT_VERSION:
        raise ValueError(
            f"unsupported SATISH format version {fmt_version} "
            f"(this omni build supports v{FORMAT_VERSION}) — update omni"
        )

    (gen_len,) = struct.unpack_from(">B", data, pos); pos += 1
    generation = data[pos:pos + gen_len].decode("utf-8"); pos += gen_len

    (gen_year,) = struct.unpack_from(">H", data, pos); pos += 2
    (engine_fmt,) = struct.unpack_from(">B", data, pos); pos += 1

    (manifest_len,) = struct.unpack_from(">I", data, pos); pos += 4
    manifest = json.loads(zlib.decompress(data[pos:pos + manifest_len]))
    pos += manifest_len

    (checksum,) = struct.unpack_from(">I", data, pos); pos += 4
    (payload_len,) = struct.unpack_from(">I", data, pos); pos += 4
    payload = data[pos:pos + payload_len]

    return ParsedSatish(
        generation=generation,
        generation_year=gen_year,
        engine_format_version=engine_fmt,
        root=manifest["root"],
        files=manifest["files"],
        payload=payload,
        checksum_ok=(zlib.crc32(payload) & 0xFFFFFFFF) == checksum,
    )
