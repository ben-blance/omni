# OMNI

OMNI is a neural compressor for source code. It beats `tar+xz` on ratio for
Python codebases by combining a trained sequence model with explicit
long-range copy matching and entropy coding, instead of general-purpose
byte-level compression.

```
omni compress my_project/
# -> my_project.satish_andromeda

omni decompress my_project.satish_andromeda
# -> my_project/  (byte-identical to the original)
```

## Install

Real one-line installers (`apt install omni`, `curl ... | sh`) aren't live
yet. For now:

```
git clone <this repo>
cd omni
./install.sh
```

which installs the `omni` CLI in editable mode via pip.

## Usage

```
omni compress <path> [--model NAME] [--out FILE]     # file or directory
omni decompress <file.satish_*> [--out PATH]
omni info <file.satish_*>                              # header only, no model needed
omni models                                             # installed model generations
omni version
```

Model management (no public registry endpoint exists yet — see below):

```
omni model register <name> <year> <model.pt> --so <arithmetic_coder.so> [--default]
omni model default <name>
omni model update                                       # stub until a registry exists
```

`omni compress` always uses the latest installed generation unless you pass
`--model`. `omni decompress` always uses whatever generation the archive's
header says it needs — see [docs/satish-format.md](docs/satish-format.md).

## Try it

[`examples/`](examples/) has a walkthrough against a small sample project.

## Public vs. private

This repository is the **distribution layer only** — the CLI, the SATISH
container format, docs, and install scripts. It does not contain the
compression engine (tokenizer, model architecture, LZ matcher, arithmetic
coder, or trained weights).

```
              this repo (public)
                     │
          ┌──────────┴──────────┐
          │                     │
    CLI (src/omni/)      SATISH format (documented,
          │                docs/satish-format.md)
          ▼
   src/omni/engine.py  ──seam──▶  OMNI engine (private)
                                        │
                                        ▼
                                 model: Andromeda (2026)
```

`src/omni/engine.py` is the only file that talks to the engine, and it does
so dynamically (via `OMNI_ENGINE_SRC`, or a private package once one
exists) — nothing else in this package needs to change when the engine
moves to its own private repo or ships as a compiled binary.

The SATISH *format* is public and documented on purpose (see
[docs/satish-format.md](docs/satish-format.md)) even though the *engine*
isn't: a `.satish_*` file's header should always be inspectable, independent
of whether you have the model or algorithm that produced it.

**License:** not yet decided. Don't treat anything in this repo as
licensed for reuse until a LICENSE file with real terms replaces the
placeholder — see [LICENSE](LICENSE). Whatever's chosen for this repo (the
CLI/format shell) needs to not accidentally extend to the private engine or
model weights, which are meant to stay proprietary.
