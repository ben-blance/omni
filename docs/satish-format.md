# SATISH format specification

SATISH is the container format OMNI writes and reads. It's documented here
even though the compression **engine** behind it is closed source — a
`.satish_*` file should always be inspectable, and its shape shouldn't be a
mystery just because the algorithm that fills in parts of it isn't public.

A file compressed by generation `andromeda` is named `<name>.satish_andromeda`.
The generation is also recorded inside the header, so `omni decompress`
never has to guess — it's not relying on the file extension, it's reading
the actual field.

## Why a container at all

SATISH is a **multi-codec container**: every file gets its own manifest
entry recording which codec compressed it. This is what lets `omni
compress` pack a whole project — source code, docs, configs, images,
whatever — into one archive without silently discarding anything, even
though only Python source has a trained neural codec today.

Files land in one of three payload **lanes**:

- **Python** (`.py`, `.pyi`) — all such files share ONE combined payload,
  encoded by the trained engine with full cross-file context. This is the
  proprietary part, and the only lane that needs a model installed.
- **Generic / compressible** (docs, configs, structured text, source in
  languages without a dedicated codec yet, ...) — ALL such files are
  concatenated and compressed together as ONE xz stream, not compressed
  file-by-file. Independent per-file compression can't see redundancy
  *across* files (repeated license headers, near-identical CI configs,
  shared doc boilerplate) — exactly what a whole-archive tool like
  `tar+xz` exploits, and now SATISH does too.
- **Store** (images, archives, media — already compressed) — each such
  file gets its own independent, uncompressed payload. Deliberately kept
  OUT of the shared stream too: there's no redundancy for it to find in
  already-compressed bytes, only wasted CPU.

A checksum per file catches corruption before it's silently mis-decoded,
independent of which lane produced that file.

## Byte layout

All multi-byte integers are big-endian. Byte offsets below are relative to
the start of the file.

| field | type | size | notes |
|---|---|---|---|
| magic | bytes | 4 | always `b"SATI"` |
| format_version | uint8 | 1 | this document describes version `3` |
| generation_len | uint8 | 1 | length of the generation name in bytes |
| generation | utf-8 bytes | `generation_len` | lowercased model generation name, e.g. `"andromeda"` |
| generation_year | uint16 | 2 | e.g. `2026` |
| engine_format_version | uint8 | 1 | versions the Python payload's internal shape, independent of `generation` |
| manifest_len | uint32 | 4 | length of the compressed manifest that follows |
| manifest | zlib bytes | `manifest_len` | zlib-compressed JSON, see below (the manifest itself is always zlib — this is unrelated to which codec compressed each file) |
| omni_python_payload_len | uint32 | 4 | length of the combined Python payload (0 if no Python files) |
| omni_python_payload | bytes | `omni_python_payload_len` | opaque — produced and consumed only by the engine |
| generic_stream_payload_len | uint32 | 4 | length of the combined xz payload (0 if no generic files) |
| generic_stream_payload | bytes | `generic_stream_payload_len` | one xz frame covering every `xz_stream` file's bytes, concatenated |
| n_store | uint32 | 4 | number of stored (uncompressed) file payloads that follow |
| (repeated `n_store` times) payload_len | uint32 | 4 | length of this payload |
| (repeated `n_store` times) payload | bytes | `payload_len` | this file's own raw bytes |

The `n_store` payloads appear in the **same order** their manifest entries
do, skipping any entry whose codec isn't `store`.

### Manifest JSON shape

```json
{
  "root": "my_project",
  "files": [
    {
      "path": "app.py",
      "type": "python",
      "codec": "omni_python",
      "codec_version": 1,
      "original_size": 2048,
      "checksum": "a1b2c3d4"
    },
    {
      "path": "README.md",
      "type": "markdown",
      "codec": "xz_stream",
      "codec_version": 1,
      "original_size": 512,
      "checksum": "9f8e7d6c",
      "offset": 0
    },
    {
      "path": "logo.png",
      "type": "png",
      "codec": "store",
      "codec_version": 1,
      "original_size": 20480,
      "checksum": "1122aabb"
    }
  ]
}
```

`checksum` is the lowercase-hex CRC32 of the file's **original**
(decompressed) bytes — checked after decoding, regardless of codec.
`offset` only appears on `xz_stream` entries: it's this file's start
position within the *decompressed* generic stream (read `original_size`
bytes from there to recover it).

## Codecs

| codec | meaning | needs a model? |
|---|---|---|
| `omni_python` | trained neural engine, cross-file context | yes |
| `xz_stream` | shared xz/LZMA compression across all such files in the archive | no |
| `store` | no compression — already-compressed formats (images, archives, media) | no |

`codec` + `type` together say why a codec was chosen: `yaml` + `store`
would mean YAML is being treated as an already-compressed format (it
isn't, today), whereas `png` + `store` means PNG is *correctly* being left
alone. Today only Python maps to `omni_python`; everything else maps to
`xz_stream` unless it's a known already-compressed format. This mapping
is expected to grow — a future generation could add a dedicated codec for
YAML, JSON, Markdown, other languages, etc., without changing this
container format at all.

**Old archives never get silently reinterpreted.** An archive written
today with `config.yaml` compressed via `xz_stream` stays exactly that
archive. There is no plan for a newer OMNI generation to change what an
existing archive means — recompressing with a newer generation (once that
exists) would produce a new archive, not mutate the old one.

## Versioning and forward compatibility

Two independent version numbers exist on purpose:

- **`generation`** — which trained model is needed for `omni_python`
  entries. New generations (Andromeda 2026, Kohinoor 2027, ...) are
  expected regularly; an old generation's model must stay installable
  indefinitely so old archives keep decoding.
- **`engine_format_version`** — how the omni_python payload bytes are
  structured internally (independent of which model produced them). This
  changes far less often, and only when that wrapping/encoding scheme
  itself changes.

`omni decompress` reads `generation` first and resolves the matching model
from the local registry (`omni models`) — but only if the archive actually
has any `omni_python` entries; an archive with no Python files needs no
model at all. `omni compress` always uses the latest generation unless
`--model <name>` is passed explicitly.

## What lives outside this spec

The `omni_python` payload's internal byte layout (LZ copy encoding,
arithmetic coding, vocabulary/tokenization details) is intentionally
undocumented here — that's the proprietary part. This document only covers
the public container around it, and the generic codecs, which are public
in full (see `codecs.py`).
