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
import os
import sys
from pathlib import Path

from . import __version__, engine, registry, satish

_IGNORE_DIRS = {".git", "__pycache__", "venv", ".venv", "node_modules",
                 ".mypy_cache", ".pytest_cache", "build", "dist", ".tox"}


def _collect_py_files(root: Path) -> list[Path]:
    files = []
    for p in sorted(root.rglob("*.py")):
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
        found = _collect_py_files(src_path)
        if not found:
            print(f"error: no .py files found under {src_path}", file=sys.stderr)
            sys.exit(1)
        rel_paths = [str(f.relative_to(src_path)) for f in found]
        sources = [f.read_text(encoding="utf-8", errors="replace") for f in found]
    else:
        root_name = src_path.stem
        rel_paths = [src_path.name]
        sources = [src_path.read_text(encoding="utf-8", errors="replace")]

    entry = _resolve_model(args.model)
    n_files = len(rel_paths)
    print(f"[omni] compressing {n_files} file(s) with model "
          f"'{entry.name}' ({entry.year}) …")

    model = engine.load_model(entry.model_path)
    blob, stats = engine.compress_sources(sources, model, entry.so_path,
                                           min_match=args.min_match)

    out_path = (Path(args.out) if args.out
                else Path(f"{root_name}{satish.extension_for(entry.name)}"))
    packed = satish.pack(entry.name, entry.year, engine.ENGINE_FORMAT_VERSION,
                          root_name, rel_paths, blob)
    out_path.write_bytes(packed)

    orig_size = sum(len(s.encode("utf-8")) for s in sources)
    saving = (1 - len(packed) / orig_size) * 100 if orig_size else 0.0
    print(f"[omni] {orig_size:,} B -> {len(packed):,} B  ({saving:.1f}% saved, "
          f"{stats['n_copies']:,} copies)")
    print(f"[omni] wrote {out_path}")


def cmd_decompress(args: argparse.Namespace) -> None:
    in_path = Path(args.file)
    if not in_path.exists():
        print(f"error: {in_path} does not exist", file=sys.stderr)
        sys.exit(1)

    parsed = satish.parse(in_path.read_bytes())
    if not parsed.checksum_ok:
        print("error: checksum mismatch — file may be corrupted or truncated",
              file=sys.stderr)
        sys.exit(1)
    if parsed.engine_format_version != engine.ENGINE_FORMAT_VERSION:
        print(f"error: this archive's engine format (v{parsed.engine_format_version}) "
              f"isn't supported by this omni build (v{engine.ENGINE_FORMAT_VERSION}) "
              f"— update omni", file=sys.stderr)
        sys.exit(1)

    entry = registry.get(parsed.generation)
    if entry is None:
        print(f"error: model generation '{parsed.generation}' is not installed.\n"
              f"       Run `omni model update`, or register it manually with "
              f"`omni model register`.", file=sys.stderr)
        sys.exit(1)

    print(f"[omni] decompressing with model '{entry.name}' ({entry.year}) …")
    model = engine.load_model(entry.model_path)
    sources = engine.decompress_sources(parsed.payload, model, entry.so_path)

    single_flat_file = len(parsed.files) == 1 and "/" not in parsed.files[0]
    if single_flat_file:
        dest = Path(args.out) if args.out else Path(parsed.files[0])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(sources[0], encoding="utf-8")
        print(f"[omni] wrote {dest}")
        return

    out_dir = Path(args.out) if args.out else Path(parsed.root)
    for rel, content in zip(parsed.files, sources):
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    print(f"[omni] reconstructed {len(parsed.files)} file(s) into {out_dir}/")


def cmd_info(args: argparse.Namespace) -> None:
    in_path = Path(args.file)
    parsed = satish.parse(in_path.read_bytes())
    print(f"SATISH format version : {satish.FORMAT_VERSION}")
    print(f"Model generation      : {parsed.generation} ({parsed.generation_year})")
    print(f"Engine format version : {parsed.engine_format_version}")
    print(f"Root                  : {parsed.root}")
    print(f"Files                 : {len(parsed.files)}")
    for f in parsed.files:
        print(f"  - {f}")
    print(f"Compressed payload    : {len(parsed.payload):,} B")
    print(f"Checksum              : {'OK' if parsed.checksum_ok else 'MISMATCH'}")

    entry = registry.get(parsed.generation)
    print(f"Model installed       : {'yes' if entry else 'no'}")


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


def cmd_model_update(_args: argparse.Namespace) -> None:
    url = os.environ.get("OMNI_MODEL_REGISTRY_URL")
    if not url:
        print("[omni] no model registry endpoint configured yet.\n"
              "       Set OMNI_MODEL_REGISTRY_URL once one exists, or "
              "register a model locally with `omni model register`.")
        return
    print(f"[omni] would check {url} for new generations — not implemented yet.")


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
    mu.set_defaults(func=cmd_model_update)

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
