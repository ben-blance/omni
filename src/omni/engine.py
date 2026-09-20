"""
Bridge between the public OMNI CLI and the OMNI compression engine.

This module is deliberately the ONLY place the CLI touches engine internals.
The public `omni` package never imports the engine's modules directly —
everything else in this package talks to `load_model` / `compress_sources` /
`decompress_sources` below, and never learns how the engine is packaged.

Two ways the engine can be found, tried in order:
  1. Already pip-installed as the (Cython-compiled, source-free) omni-engine
     package -- model/compress import directly, same as any other installed
     package. This is the real production path.
  2. OMNI_ENGINE_SRC (or, in this monorepo during development, a sibling
     src/python directory) -- plain .py source on disk, injected onto
     sys.path. Dev-only.
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

    # 1. Real production path: omni-engine pip-installed, model/compress
    # importable directly like any other installed package.
    try:
        _engine_modules["model"] = importlib.import_module("model")
        _engine_modules["compress"] = importlib.import_module("compress")
        return
    except ImportError:
        _engine_modules.clear()

    # 2. Dev fallback: raw .py source on disk.
    src = _locate_engine_src()
    if src is None:
        raise EngineUnavailable(
            "OMNI engine not found. Run `omni engine install`, or set "
            "OMNI_ENGINE_SRC to the engine's source location for local "
            "development."
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
