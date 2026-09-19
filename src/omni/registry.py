"""
Local model registry — tracks which model generations (Andromeda, Kohinoor,
...) are installed on this machine, and which one is the default.

There's no real download server yet, so `omni model register` (pointing at
a local .pt/.so pair) is the only way to install a generation today.
`omni model update` is a stub wired to hit OMNI_MODEL_REGISTRY_URL once
that exists — see cli.py.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

OMNI_HOME = Path(os.environ.get("OMNI_HOME", str(Path.home() / ".omni")))
REGISTRY_FILE = OMNI_HOME / "models.json"
MODELS_DIR = OMNI_HOME / "models"


@dataclass
class ModelEntry:
    name: str
    year: int
    model_path: str
    so_path: str | None = None
    is_default: bool = False


def _load() -> list[dict]:
    if not REGISTRY_FILE.exists():
        return []
    return json.loads(REGISTRY_FILE.read_text())["models"]


def _save(models: list[dict]) -> None:
    OMNI_HOME.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps({"models": models}, indent=2))


def list_models() -> list[ModelEntry]:
    return [ModelEntry(**m) for m in _load()]


def get(name: str) -> ModelEntry | None:
    name = name.lower()
    for m in list_models():
        if m.name == name:
            return m
    return None


def get_default() -> ModelEntry | None:
    models = list_models()
    for m in models:
        if m.is_default:
            return m
    return models[0] if models else None


def register(name: str, year: int, model_path: str, so_path: str | None = None,
             set_default: bool = False, copy: bool = True) -> ModelEntry:
    name = name.lower()
    if not Path(model_path).exists():
        raise FileNotFoundError(model_path)
    if so_path and not Path(so_path).exists():
        raise FileNotFoundError(so_path)

    if copy:
        dest_dir = MODELS_DIR / name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_model = dest_dir / Path(model_path).name
        shutil.copy2(model_path, dest_model)
        model_path = str(dest_model)
        if so_path:
            dest_so = dest_dir / Path(so_path).name
            shutil.copy2(so_path, dest_so)
            so_path = str(dest_so)

    models = [m for m in _load() if m["name"] != name]
    entry = ModelEntry(name=name, year=year, model_path=model_path,
                        so_path=so_path, is_default=set_default or not models)
    models.append(asdict(entry))

    if entry.is_default:
        for m in models:
            m["is_default"] = (m["name"] == name)

    _save(models)
    return entry


def set_default(name: str) -> None:
    name = name.lower()
    models = _load()
    if not any(m["name"] == name for m in models):
        raise KeyError(name)
    for m in models:
        m["is_default"] = (m["name"] == name)
    _save(models)
