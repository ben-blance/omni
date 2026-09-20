"""
SATISH — the public, documented container format OMNI writes and reads.

This module is the reference implementation of the spec in
docs/satish-format.md. Keep the two in sync: if you change the byte layout
here, update the doc in the same change.

Format v3 is a three-lane multi-codec container. Every file gets its own
manifest entry recording which codec compressed it, and lands in one of
three payload lanes:
  - omni_python payload  — ONE combined payload for all Python files,
    encoded by the trained engine with full cross-file context. SATISH
    never looks inside it, that's engine.py's job.
  - generic stream payload — ONE combined zstd payload for all other
    compressible files (docs, configs, structured text, ...), so the
    generic codec can also see redundancy *across* files instead of
    compressing each one in isolation (see codecs.py's module docstring
    for why this matters).
  - store payloads — one independent, uncompressed payload per file for
    formats that are already compressed (images, archives, media).

A checksum per file catches corruption before it's silently mis-decoded,
independent of which lane produced that file.
"""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass

MAGIC = b"SATI"
FORMAT_VERSION = 3


@dataclass
class FileEntry:
    path: str
    file_type: str
    codec: str
    codec_version: int
    original_size: int
    checksum: str  # hex CRC32 of the original (decompressed) file bytes
    offset: int | None = None  # zstd_stream entries only: start within the
                                # decompressed generic stream


@dataclass
class ParsedSatish:
    generation: str
    generation_year: int
    engine_format_version: int
    root: str
    entries: list[FileEntry]
    omni_python_payload: bytes
    generic_stream_payload: bytes
    store_payloads: list[bytes]  # aligned, in order, with codec=="store" entries


def extension_for(generation: str) -> str:
    return f".satish_{generation.lower()}"


def checksum_of(data: bytes) -> str:
    return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


def pack(generation: str, generation_year: int, engine_format_version: int,
         root: str, entries: list[FileEntry], omni_python_payload: bytes,
         generic_stream_payload: bytes, store_payloads: list[bytes]) -> bytes:
    manifest = zlib.compress(
        json.dumps({
            "root": root,
            "files": [
                {
                    "path": e.path, "type": e.file_type, "codec": e.codec,
                    "codec_version": e.codec_version,
                    "original_size": e.original_size, "checksum": e.checksum,
                    **({"offset": e.offset} if e.offset is not None else {}),
                }
                for e in entries
            ],
        }).encode("utf-8"), 9,
    )
    gen_bytes = generation.lower().encode("utf-8")

    out = bytearray()
    out += MAGIC
    out += struct.pack(">B", FORMAT_VERSION)
    out += struct.pack(">B", len(gen_bytes)) + gen_bytes
    out += struct.pack(">H", generation_year)
    out += struct.pack(">B", engine_format_version)
    out += struct.pack(">I", len(manifest)) + manifest
    out += struct.pack(">I", len(omni_python_payload)) + omni_python_payload
    out += struct.pack(">I", len(generic_stream_payload)) + generic_stream_payload
    out += struct.pack(">I", len(store_payloads))
    for payload in store_payloads:
        out += struct.pack(">I", len(payload)) + payload
    return bytes(out)


def parse(data: bytes) -> ParsedSatish:
    """Unwrap a SATISH header. Does not touch the engine or the generic
    codecs — payloads are returned opaque/still-encoded."""
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

    entries = [
        FileEntry(
            path=f["path"], file_type=f["type"], codec=f["codec"],
            codec_version=f["codec_version"], original_size=f["original_size"],
            checksum=f["checksum"], offset=f.get("offset"),
        )
        for f in manifest["files"]
    ]

    (omni_len,) = struct.unpack_from(">I", data, pos); pos += 4
    omni_python_payload = data[pos:pos + omni_len]
    pos += omni_len

    (stream_len,) = struct.unpack_from(">I", data, pos); pos += 4
    generic_stream_payload = data[pos:pos + stream_len]
    pos += stream_len

    (n_store,) = struct.unpack_from(">I", data, pos); pos += 4
    store_payloads = []
    for _ in range(n_store):
        (plen,) = struct.unpack_from(">I", data, pos); pos += 4
        store_payloads.append(data[pos:pos + plen])
        pos += plen

    return ParsedSatish(
        generation=generation,
        generation_year=gen_year,
        engine_format_version=engine_fmt,
        root=manifest["root"],
        entries=entries,
        omni_python_payload=omni_python_payload,
        generic_stream_payload=generic_stream_payload,
        store_payloads=store_payloads,
    )
