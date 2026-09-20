"""
OMNI command-line interface.

    omni compress <path>              -> <name>.satish_<generation>
    omni decompress <file.satish_*>   -> reconstructed file(s)
    omni info <file.satish_*>         -> header metadata, no model needed
    omni models                       -> installed model generations
    omni model register/default/update
    omni version

This module only ever talks to the engine through engine.py, and only ever
talks to installed models through registry.py — see those modules' module
docstrings for why.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections import Counter
from pathlib import Path

from . import __version__, codecs, engine, registry, remote, satish

_IGNORE_DIRS = {".git", "__pycache__", "venv", ".venv", "node_modules",
                 ".mypy_cache", ".pytest_cache", "build", "dist", ".tox"}


def _with_progress(label: str, fn, *args, **kwargs):
    """Runs a slow, non-interruptible engine call with a live elapsed-time
    indicator. The engine (compress_files_lz_cost / decompress_files_lz)
    has no internal progress callback — it's one blocking call — so this
    can't show real percentage, only that it's still working, which is
    enough to stop it looking stuck on anything beyond a handful of files."""
    done = threading.Event()
    start = time.time()

    def spin():
        frames = "|/-\\"
        i = 0
        while not done.wait(0.5):
            elapsed = time.time() - start
            sys.stdout.write(f"\r[omni] {label}… {elapsed:.0f}s {frames[i % 4]}")
            sys.stdout.flush()
            i += 1

    t = threading.Thread(target=spin, daemon=True)
    t.start()
    try:
        return fn(*args, **kwargs)
    finally:
        done.set()
        t.join()
        sys.stdout.write("\r" + " " * 40 + "\r")
        sys.stdout.flush()


def _collect_all_files(root: Path) -> list[Path]:
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in _IGNORE_DIRS for part in p.parts):
            continue
        files.append(p)
    return files


def _resolve_model(name: str | None) -> registry.ModelEntry:
    entry = registry.get(name) if name else registry.get_default()
    if entry is None:
        if name:
            print(f"error: no model generation named '{name}' is installed.\n"
                  f"       Run `omni models` to see what's installed.", file=sys.stderr)
        else:
            print("error: no OMNI model installed.\n"
                  "       Run `omni model register <name> <year> <model.pt> "
                  "--so <arithmetic_coder.so>` to add one.", file=sys.stderr)
        sys.exit(1)
    return entry


def cmd_compress(args: argparse.Namespace) -> None:
    src_path = Path(args.path)
    if not src_path.exists():
        print(f"error: {src_path} does not exist", file=sys.stderr)
        sys.exit(1)

    if src_path.is_dir():
        root_name = src_path.name
        found = _collect_all_files(src_path)
        if not found:
            print(f"error: no files found under {src_path}", file=sys.stderr)
            sys.exit(1)
        file_paths = [(f, str(f.relative_to(src_path))) for f in found]
    else:
        root_name = src_path.stem
        file_paths = [(src_path, src_path.name)]

    entry = _resolve_model(args.model)
    print(f"[omni] compressing {len(file_paths)} file(s) with model "
          f"'{entry.name}' ({entry.year}) …")

    # Classify every file up front: Python source shares one combined
    # cross-file-context payload via the neural engine; everything else
    # gets its own independent payload via a generic codec (codecs.py) —
    # this is what guarantees `omni compress` never silently drops a file.
    python_items: list[tuple[str, bytes]] = []
    generic_items: list[tuple[str, str, str, bytes]] = []  # path, type, codec, raw
    for f, rel in file_paths:
        file_type, codec = codecs.classify(f)
        raw = f.read_bytes()
        if codec == codecs.CODEC_OMNI_PYTHON:
            python_items.append((rel, raw))
        else:
            generic_items.append((rel, file_type, codec, raw))

    omni_python_payload = b""
    stats = {"n_copies": 0}
    python_entries: list[satish.FileEntry] = []
    if python_items:
        model = engine.load_model(entry.model_path)
        python_sources = [raw.decode("utf-8", errors="replace") for _, raw in python_items]
        omni_python_payload, stats = _with_progress(
            "compressing", engine.compress_sources, python_sources, model,
            entry.so_path, min_match=args.min_match,
        )
        for (rel, raw), _ in zip(python_items, python_sources):
            python_entries.append(satish.FileEntry(
                path=rel, file_type="python", codec=codecs.CODEC_OMNI_PYTHON,
                codec_version=engine.ENGINE_FORMAT_VERSION,
                original_size=len(raw), checksum=satish.checksum_of(raw),
            ))

    generic_entries: list[satish.FileEntry] = []
    other_payloads: list[bytes] = []
    for rel, file_type, codec, raw in generic_items:
        payload = codecs.encode(codec, raw)
        other_payloads.append(payload)
        generic_entries.append(satish.FileEntry(
            path=rel, file_type=file_type, codec=codec,
            codec_version=codecs.CODEC_VERSION,
            original_size=len(raw), checksum=satish.checksum_of(raw),
        ))

    # Reassemble in the original walk order (not python-then-generic) so
    # `omni info` lists files the way a user would expect to see them.
    by_path = {e.path: e for e in python_entries + generic_entries}
    entries = [by_path[rel] for _, rel in file_paths]

    out_path = (Path(args.out) if args.out
                else Path(f"{root_name}{satish.extension_for(entry.name)}"))
    packed = satish.pack(entry.name, entry.year, engine.ENGINE_FORMAT_VERSION,
                          root_name, entries, omni_python_payload, other_payloads)
    out_path.write_bytes(packed)

    orig_size = sum(e.original_size for e in entries)
    saving = (1 - len(packed) / orig_size) * 100 if orig_size else 0.0
    print(f"[omni] {orig_size:,} B -> {len(packed):,} B  ({saving:.1f}% saved)")
    if python_entries:
        print(f"[omni]   {len(python_entries)} Python file(s) via neural engine "
              f"({stats['n_copies']:,} copies)")
    if generic_entries:
        print(f"[omni]   {len(generic_entries)} other file(s) via generic codecs")
    print(f"[omni] wrote {out_path}")


def cmd_decompress(args: argparse.Namespace) -> None:
    in_path = Path(args.file)
    if not in_path.exists():
        print(f"error: {in_path} does not exist", file=sys.stderr)
        sys.exit(1)

    parsed = satish.parse(in_path.read_bytes())
    if parsed.engine_format_version != engine.ENGINE_FORMAT_VERSION:
        print(f"error: this archive's engine format (v{parsed.engine_format_version}) "
              f"isn't supported by this omni build (v{engine.ENGINE_FORMAT_VERSION}) "
              f"— update omni", file=sys.stderr)
        sys.exit(1)

    python_sources: list[str] = []
    if any(e.codec == codecs.CODEC_OMNI_PYTHON for e in parsed.entries):
        entry = registry.get(parsed.generation)
        if entry is None:
            print(f"error: model generation '{parsed.generation}' is not installed.\n"
                  f"       Run `omni model update`, or register it manually with "
                  f"`omni model register`.", file=sys.stderr)
            sys.exit(1)
        print(f"[omni] decompressing with model '{entry.name}' ({entry.year}) …")
        model = engine.load_model(entry.model_path)
        python_sources = _with_progress(
            "decompressing", engine.decompress_sources,
            parsed.omni_python_payload, model, entry.so_path,
        )

    single_flat_file = len(parsed.entries) == 1 and "/" not in parsed.entries[0].path
    out_dir = None if single_flat_file else (Path(args.out) if args.out else Path(parsed.root))
    resolved_out = out_dir.resolve() if out_dir else None

    py_i = other_i = 0
    mismatches = []
    for e in parsed.entries:
        if e.codec == codecs.CODEC_OMNI_PYTHON:
            content = python_sources[py_i].encode("utf-8")
            py_i += 1
        else:
            content = codecs.decode(e.codec, parsed.other_payloads[other_i])
            other_i += 1

        if satish.checksum_of(content) != e.checksum:
            mismatches.append(e.path)

        if single_flat_file:
            dest = Path(args.out) if args.out else Path(e.path)
        else:
            dest = (out_dir / e.path).resolve()
            if resolved_out not in dest.parents:
                print(f"error: archive entry '{e.path}' escapes the output "
                      f"directory — refusing to write it", file=sys.stderr)
                sys.exit(1)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    if mismatches:
        shown = ", ".join(mismatches[:5]) + ("…" if len(mismatches) > 5 else "")
        print(f"error: checksum mismatch on {len(mismatches)} file(s): {shown}",
              file=sys.stderr)
        sys.exit(1)

    if single_flat_file:
        print(f"[omni] wrote {Path(args.out) if args.out else Path(parsed.entries[0].path)}")
    else:
        print(f"[omni] reconstructed {len(parsed.entries)} file(s) into {out_dir}/")


def cmd_info(args: argparse.Namespace) -> None:
    in_path = Path(args.file)
    parsed = satish.parse(in_path.read_bytes())
    orig_total = sum(e.original_size for e in parsed.entries)

    print(f"SATISH format version : {satish.FORMAT_VERSION}")
    print(f"Model generation      : {parsed.generation} ({parsed.generation_year})")
    print(f"Engine format version : {parsed.engine_format_version}")
    print(f"Root                  : {parsed.root}")
    print(f"Files                 : {len(parsed.entries)}")
    print(f"Original size         : {orig_total:,} B")
    print(f"Archive size          : {in_path.stat().st_size:,} B")

    print("\nCodecs:")
    for codec, count in Counter(e.codec for e in parsed.entries).most_common():
        print(f"  {codec:<15} {count:>5} file(s)")

    print("\nBy type:")
    for t, count in Counter(e.file_type for e in parsed.entries).most_common():
        print(f"  {t:<15} {count:>5}")

    needs_model = any(e.codec == codecs.CODEC_OMNI_PYTHON for e in parsed.entries)
    entry = registry.get(parsed.generation) if needs_model else None
    print(f"\nModel installed       : "
          f"{'not needed' if not needs_model else ('yes' if entry else 'no')}")


def cmd_version(_args: argparse.Namespace) -> None:
    print(f"omni {__version__}  (SATISH format v{satish.FORMAT_VERSION}, "
          f"engine format v{engine.ENGINE_FORMAT_VERSION})")


def cmd_models(_args: argparse.Namespace) -> None:
    models = registry.list_models()
    if not models:
        print("No models installed. Run `omni model register` to add one.")
        return
    print("Installed models:\n")
    default = registry.get_default()
    for m in sorted(models, key=lambda m: -m.year):
        tag = "   latest, default" if default and m.name == default.name else ""
        print(f"  * {m.name.capitalize():<12} {m.year}{tag}")
    if default:
        print(f"\nDefault: {default.name.capitalize()}")


def cmd_model_register(args: argparse.Namespace) -> None:
    try:
        entry = registry.register(args.name, args.year, args.model_path, args.so,
                                   set_default=args.default)
    except FileNotFoundError as e:
        print(f"error: file not found: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"[omni] registered '{entry.name}' ({entry.year})"
          f"{' as default' if entry.is_default else ''}")


def cmd_model_default(args: argparse.Namespace) -> None:
    try:
        registry.set_default(args.name)
    except KeyError:
        print(f"error: no such model '{args.name}'", file=sys.stderr)
        sys.exit(1)
    print(f"[omni] default model set to '{args.name}'")


def cmd_model_update(args: argparse.Namespace) -> None:
    print(f"[omni] checking {remote._repo()} for the latest generation …")
    try:
        entry = remote.update(force=args.force)
    except remote.UpdateError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"[omni] '{entry.name}' ({entry.year}) is installed and set as default")


def cmd_engine_install(args: argparse.Namespace) -> None:
    try:
        result = remote.install_engine(force=args.force)
    except remote.UpdateError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    if result == "already installed":
        print("[omni] engine already installed (use --force to reinstall)")
    else:
        print(f"[omni] engine installed from {result}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omni", description="OMNI — neural source-code compression")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("compress", help="Compress a file or directory")
    c.add_argument("path")
    c.add_argument("--model", default=None, help="Model generation to use (default: latest installed)")
    c.add_argument("--out", default=None, help="Output archive path")
    c.add_argument("--min-match", type=int, default=4, help="LZ minimum match length (advanced)")
    c.set_defaults(func=cmd_compress)

    d = sub.add_parser("decompress", help="Decompress a .satish_* archive")
    d.add_argument("file")
    d.add_argument("--out", default=None, help="Output path/directory")
    d.set_defaults(func=cmd_decompress)

    i = sub.add_parser("info", help="Show metadata about a .satish_* archive (no model needed)")
    i.add_argument("file")
    i.set_defaults(func=cmd_info)

    v = sub.add_parser("version", help="Show CLI/format version")
    v.set_defaults(func=cmd_version)

    m = sub.add_parser("models", help="List installed model generations")
    m.set_defaults(func=cmd_models)

    mg = sub.add_parser("model", help="Manage model generations")
    msub = mg.add_subparsers(dest="model_command", required=True)

    mr = msub.add_parser("register", help="Register a local model as a generation (offline/dev use)")
    mr.add_argument("name", help="Generation name, e.g. andromeda")
    mr.add_argument("year", type=int)
    mr.add_argument("model_path")
    mr.add_argument("--so", default=None, help="Path to the matching arithmetic_coder shared library")
    mr.add_argument("--default", action="store_true")
    mr.set_defaults(func=cmd_model_register)

    md = msub.add_parser("default", help="Set the default model generation")
    md.add_argument("name")
    md.set_defaults(func=cmd_model_default)

    mu = msub.add_parser("update", help="Fetch the latest model generation")
    mu.add_argument("--force", action="store_true", help="Re-download even if already installed")
    mu.set_defaults(func=cmd_model_update)

    eg = sub.add_parser("engine", help="Manage the compression engine")
    esub = eg.add_subparsers(dest="engine_command", required=True)

    ei = esub.add_parser("install", help="Install the compiled engine from the latest GitHub Release")
    ei.add_argument("--force", action="store_true", help="Reinstall even if already installed")
    ei.set_defaults(func=cmd_engine_install)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except engine.EngineUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
