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

- **Python files** (`.py`, `.pyi`) all share ONE combined payload, encoded
  by the trained engine with full cross-file context — this is the
  proprietary part, and the only thing that actually needs a model
  installed.
- **Everything else** gets its own independent payload, compressed with a
  small set of built-in generic codecs (`zlib` for compressible text/data,
  `store` for formats that are already compressed, like images or
  archives) — no model required.

A checksum per file catches corruption before it's silently mis-decoded,
independent of which codec produced that file.

## Byte layout

All multi-byte integers are big-endian. Byte offsets below are relative to
the start of the file.

| field | type | size | notes |
|---|---|---|---|
| magic | bytes | 4 | always `b"SATI"` |
| format_version | uint8 | 1 | this document describes version `2` |
| generation_len | uint8 | 1 | length of the generation name in bytes |
| generation | utf-8 bytes | `generation_len` | lowercased model generation name, e.g. `"andromeda"` |
| generation_year | uint16 | 2 | e.g. `2026` |
| engine_format_version | uint8 | 1 | versions the omni_python payload's internal shape, independent of `generation` |
| manifest_len | uint32 | 4 | length of the compressed manifest that follows |
| manifest | zlib bytes | `manifest_len` | zlib-compressed JSON, see below |
| omni_python_payload_len | uint32 | 4 | length of the combined Python payload (0 if no Python files) |
| omni_python_payload | bytes | `omni_python_payload_len` | opaque — produced and consumed only by the engine |
| n_other | uint32 | 4 | number of non-Python file payloads that follow |
| (repeated `n_other` times) payload_len | uint32 | 4 | length of this payload |
| (repeated `n_other` times) payload | bytes | `payload_len` | this file's own compressed (or stored) bytes |

The per-file payloads after `omni_python_payload` appear in the **same
order** their manifest entries do, skipping any entry whose codec is
`omni_python` (those are all inside the one combined payload instead).

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
      "codec": "zlib",
      "codec_version": 1,
      "original_size": 512,
      "checksum": "9f8e7d6c"
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

## Codecs

| codec | meaning | needs a model? |
|---|---|---|
| `omni_python` | trained neural engine, cross-file context | yes |
| `zlib` | generic lossless compression | no |
| `store` | no compression — already-compressed formats (images, archives, media) | no |

`codec` + `type` together say why a codec was chosen: `yaml` + `store`
would mean YAML is being treated as an already-compressed format (it
isn't, today), whereas `png` + `store` means PNG is *correctly* being left
alone. Today only Python maps to `omni_python`; `type` classification for
everything else maps to `zlib` unless it's a known already-compressed
format. This mapping is expected to grow — a future generation could add
a dedicated codec for YAML, JSON, Markdown, other languages, etc., without
changing this container format at all.

**Old archives never get silently reinterpreted.** An archive written
today with `config.yaml` stored via `zlib` stays exactly that archive.
There is no plan for a newer OMNI generation to change what an existing
archive means — recompressing with a newer generation (once that exists)
would produce a new archive, not mutate the old one.

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
