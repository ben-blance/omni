# OMNI

OMNI is a neural compressor for Python source code. It combines a trained
sequence model with explicit long-range copy matching and entropy coding to
beat general-purpose compressors on ratio.

```
omni compress my_project/
# -> my_project.satish_andromeda

omni decompress my_project.satish_andromeda
# -> my_project/  (byte-identical to the original)
```

## Benchmark

Compression saving vs. original size, measured on 9 real-world Python
repositories OMNI was never trained on, compared against `tar+xz` (the
standard general-purpose baseline):

| repo | OMNI | tar+xz | margin |
|---|---|---|---|
| flask | 82.9% | 79.7% | +3.2pp |
| pytest | 79.9% | 73.7% | +6.2pp |
| click | 82.2% | 79.2% | +3.0pp |
| rich | 72.9% | 70.5% | +2.4pp |
| attrs | 83.6% | 81.1% | +2.5pp |
| httpx | 86.1% | 84.1% | +2.0pp |
| starlette | 84.1% | 80.9% | +3.2pp |
| alembic | 85.8% | 84.7% | +1.1pp |
| pydantic | 83.6% | 81.6% | +2.0pp |

**9 out of 9 unseen repos beat tar+xz**, by 1.1 to 6.2 percentage points.
Every result above is a full round-trip: decompressed output verified
byte-identical to the original source across all files in every repo.

## Install

```
pipx install omni-compress
omni model update
```

(`pip install omni-compress` works too if you don't use `pipx`.) `omni model
update` downloads the current model generation — needed before `compress`/
`decompress` will do anything.

## Quickstart

```
omni model update                    # one-time: install the latest model
omni compress my_project/            # -> my_project.satish_andromeda
omni decompress my_project.satish_andromeda
```

## Commands

```
omni compress <path> [--model NAME] [--out FILE]
```
Compress a single file or a whole directory. Directories are walked for
`.py` files (skipping `.git`, `__pycache__`, `venv`, `node_modules`, etc.)
and packed into one archive. Uses the latest installed model generation
unless `--model` is given. Writes `<name>.satish_<generation>` unless
`--out` is given.

```
omni decompress <file.satish_*> [--out PATH]
```
Reconstructs the original file or directory tree. Always uses whichever
model generation the archive itself says it needs, regardless of what's
set as default — run `omni model update` first if that generation isn't
installed yet. Without `--out`, a directory archive restores into a folder
named after the original; a single-file archive restores as that file in
the current directory.

```
omni info <file.satish_*>
```
Prints an archive's metadata — model generation, file list, compressed
size, checksum status — without needing any model installed.

```
omni models
```
Lists installed model generations and which one is the default.

```
omni model update [--force]
```
Installs or refreshes the latest model generation. `--force` re-downloads
even if that generation is already installed.

```
omni model register <name> <year> <model.pt> --so <arithmetic_coder.so> [--default]
```
Registers a local model file as a named generation, for offline use.

```
omni model default <name>
```
Sets which installed generation `omni compress` uses by default.

```
omni version
```
Prints the CLI and format versions.

## The `.satish_<generation>` file

Every OMNI archive's extension names the model generation that produced it
— `andromeda-2026` compresses to `.satish_andromeda`, a later generation to
its own extension, and so on. That name isn't cosmetic: it's read from the
archive's own header, so `omni decompress` always knows exactly which model
to use, even years later or on a machine with several generations
installed. New generations are additive — decompressing an old archive
never requires upgrading anything, only having that generation's model
available (`omni model update` fetches whichever is current; older
generations can still be installed manually via `omni model register` if
needed).

## Try it

[`examples/`](examples/) has a walkthrough against a small sample project.

## License

MIT — see [LICENSE](LICENSE).
