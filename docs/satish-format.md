# SATISH format specification

SATISH is the container format OMNI writes and reads. It's documented here
even though the compression **engine** behind it is closed source — a
`.satish_*` file should always be inspectable, and its shape shouldn't be a
mystery just because the algorithm that fills it in isn't public.

A file compressed by generation `andromeda` is named `<name>.satish_andromeda`.
The generation is also recorded inside the header, so `omni decompress`
never has to guess — it's not relying on the file extension, it's reading
the actual field.

## Why a container at all

The underlying compression engine (tokenizer → neural model → arithmetic
coder + LZ layer) produces one opaque byte blob per compress call. SATISH
wraps that blob with everything needed to reconstruct the original files
*without* the caller already knowing which model produced it:

- which model **generation** to decode with (models aren't forward- or
  backward-compatible with each other — Andromeda can't decode a Kohinoor
  payload and vice versa)
- the **file manifest** — original relative paths, so a directory can be
  compressed to one archive and decompressed back to the same tree
- a **checksum**, so corruption is caught before it's silently mis-decoded
- an **engine format version**, independent of the model generation, in
  case the payload's internal shape ever changes without the model itself
  changing

## Byte layout

All multi-byte integers are big-endian. Byte offsets below are relative to
the start of the file.

| field | type | size | notes |
|---|---|---|---|
| magic | bytes | 4 | always `b"SATI"` |
| format_version | uint8 | 1 | this document describes version `1` |
| generation_len | uint8 | 1 | length of the generation name in bytes |
| generation | utf-8 bytes | `generation_len` | lowercased model generation name, e.g. `"andromeda"` |
| generation_year | uint16 | 2 | e.g. `2026` |
| engine_format_version | uint8 | 1 | versions the *payload's* internal shape, independent of `generation` |
| manifest_len | uint32 | 4 | length of the compressed manifest that follows |
| manifest | zlib bytes | `manifest_len` | zlib-compressed JSON: `{"root": "<dir name>", "files": ["<relpath>", ...]}` |
| checksum | uint32 | 4 | CRC32 of `payload` |
| payload_len | uint32 | 4 | length of `payload` |
| payload | bytes | `payload_len` | opaque — produced and consumed only by the engine matching `generation` |

Everything through `payload_len` is the **header**; `payload` is the
**engine payload**. SATISH never looks inside the payload — it's free to
change shape release over release as long as `engine_format_version` is
bumped when it does, so a decoder can refuse a payload it doesn't
understand instead of silently corrupting it.

## Versioning and forward compatibility

Two independent version numbers exist on purpose:

- **`generation`** — which trained model is needed. New generations
  (Andromeda 2026, Kohinoor 2027, ...) are expected regularly; an old
  generation's model must stay installable indefinitely so old archives
  keep decoding.
- **`engine_format_version`** — how the payload bytes are structured
  internally (independent of which model produced them). This changes far
  less often, and only when the wrapping/encoding scheme itself changes.

`omni decompress` reads `generation` first and resolves the matching model
from the local registry (`omni models`); it does **not** default to
"latest installed" the way `omni compress` does. Compressing always uses
the latest generation unless `--model <name>` is passed explicitly.

## What lives outside this spec

The engine payload's internal byte layout (LZ copy encoding, arithmetic
coding, vocabulary/tokenization details) is intentionally undocumented
here — that's the proprietary part. This document only covers the public
container around it.
