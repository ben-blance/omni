"""
Bridge between the public OMNI CLI and the OMNI compression engine.

This module is deliberately the ONLY place the CLI touches engine internals.
The public `omni` package never imports the engine's modules directly —
everything else in this package talks to `load_model` / `compress_sources` /
`decompress_sources` below, and never learns how the engine is packaged.

Today (single-repo development, before the public/private split) the engine
is located on disk next to this checkout and loaded dynamically. Once the
engine ships as its own private artifact (a private Python package, or a
compiled binary invoked via subprocess/FFI), only `_locate_engine_src` /
`_ensure_loaded` need to change — the rest of the CLI is unaffected.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# Bump this if the underlying engine wire format (what compress_sources
# actually writes into a SATISH payload) ever changes shape. Recorded in
# every SATISH header so a future decoder can tell old payloads apart from
# new ones, independent of the model generation.
ENGINE_FORMAT_VERSION = 1

_engine_modules: dict[str, object] = {}


class EngineUnavailable(RuntimeError):
    """Raised when the compression engine can't be found or fails to load."""


def _locate_engine_src() -> Path | None:
    env = os.environ.get("OMNI_ENGINE_SRC")
    if env:
        p = Path(env)
        return p if p.is_dir() else None

    # Dev fallback: this repo currently keeps the private engine at
    # <repo_root>/src/python, as a sibling of this omni/ folder. Once the
    # public omni repo and the private engine repo are split apart, this
    # fallback simply won't find anything and OMNI_ENGINE_SRC becomes
    # required — that's the intended seam, not a bug to fix later.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "src" / "python"
        if (candidate / "compress.py").exists():
            return candidate
    return None


def _ensure_loaded() -> None:
    if _engine_modules:
        return
    src = _locate_engine_src()
    if src is None:
        raise EngineUnavailable(
            "OMNI engine not found. Set OMNI_ENGINE_SRC to the engine's "
            "install location, or install the private omni-engine package."
        )
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        _engine_modules["model"] = importlib.import_module("model")
        _engine_modules["compress"] = importlib.import_module("compress")
    except ImportError as e:
        _engine_modules.clear()
        raise EngineUnavailable(f"failed to load OMNI engine from {src}: {e}") from e


def load_model(path: str):
    _ensure_loaded()
    return _engine_modules["model"].load_model(path)


def load_coder(so_path: str | None):
    _ensure_loaded()
    return _engine_modules["compress"].load_coder(so_path)


def compress_sources(sources: list[str], model, so_path: str | None = None,
                      min_match: int = 4) -> tuple[bytes, dict]:
    _ensure_loaded()
    compress = _engine_modules["compress"]
    if not getattr(model, "stateful", False):
        raise EngineUnavailable(
            "this model generation isn't a stateful engine model — the "
            "installed .pt file may be corrupt or from an incompatible build"
        )
    return compress.compress_files_lz_cost(
        sources, model, so_path, min_match=min_match, return_stats=True,
    )


def decompress_sources(payload: bytes, model, so_path: str | None = None) -> list[str]:
    _ensure_loaded()
    return _engine_modules["compress"].decompress_files_lz(payload, model, so_path)
