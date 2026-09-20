"""
Fetches model generations from GitHub Releases on the omni repo itself —
the same public repo distributes the CLI (via git clone/pip) and the model
weights (via release assets), so there's no separate registry server to
stand up.

Release convention: tag name is "<generation>-<year>", e.g. "andromeda-2026".
Each release is expected to have one *.pt asset (the model weights), one
*.so asset (the matching arithmetic coder shared library), and optionally
one *.whl asset (the compiled omni-engine package for this platform).

Uses only the standard library (urllib) so the CLI itself stays
dependency-free — this is the one place it talks to the network.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import registry

DEFAULT_REPO = "ben-blance/omni"
_TAG_RE = re.compile(r"^([a-z0-9]+)-(\d{4})$")


class UpdateError(RuntimeError):
    pass


def _repo() -> str:
    return os.environ.get("OMNI_MODEL_REPO", DEFAULT_REPO)


def _api_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise UpdateError(f"GitHub API returned {e.code} for {url}") from e
    except OSError as e:
        raise UpdateError(f"failed to reach GitHub ({url}): {e}") from e


def latest_release() -> dict:
    return _api_get(f"https://api.github.com/repos/{_repo()}/releases/latest")


def _download(url: str, dest: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=180) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    except OSError as e:
        raise UpdateError(f"download failed ({url}): {e}") from e


def update(force: bool = False) -> registry.ModelEntry:
    """Install the latest generation published as a GitHub Release. Returns
    the already-installed entry without downloading anything if that
    generation is already registered, unless force=True."""
    release = latest_release()
    tag = release.get("tag_name", "")
    m = _TAG_RE.match(tag)
    if not m:
        raise UpdateError(
            f"release tag '{tag}' doesn't match the expected "
            f"'<generation>-<year>' convention — can't install it automatically"
        )
    generation, year = m.group(1), int(m.group(2))

    if not force:
        existing = registry.get(generation)
        if existing is not None:
            return existing

    assets = release.get("assets", [])
    pt_asset = next((a for a in assets if a["name"].endswith(".pt")), None)
    so_asset = next((a for a in assets if a["name"].endswith(".so")), None)
    if pt_asset is None:
        raise UpdateError(f"release '{tag}' has no .pt asset to install")

    with tempfile.TemporaryDirectory(prefix="omni-model-") as tmp:
        tmp_path = Path(tmp)

        pt_path = tmp_path / pt_asset["name"]
        print(f"[omni] downloading {pt_asset['name']} "
              f"({pt_asset['size'] / 1e6:.1f} MB) …")
        _download(pt_asset["browser_download_url"], pt_path)

        so_path = None
        if so_asset is not None:
            so_path = tmp_path / so_asset["name"]
            print(f"[omni] downloading {so_asset['name']} "
                  f"({so_asset['size'] / 1e6:.1f} MB) …")
            _download(so_asset["browser_download_url"], so_path)
        else:
            print(f"[omni] warning: release '{tag}' has no .so asset — "
                  f"the engine will need one available another way")

        return registry.register(
            generation, year, str(pt_path),
            str(so_path) if so_path else None,
            set_default=True,
        )


def _engine_importable() -> bool:
    try:
        importlib.import_module("model")
        importlib.import_module("compress")
        return True
    except ImportError:
        return False


def _torch_importable() -> bool:
    try:
        importlib.import_module("torch")
        return True
    except ImportError:
        return False


def install_engine(force: bool = False) -> str:
    """Install the compiled omni-engine wheel from the latest GitHub Release
    into whatever Python environment `omni` itself is running under. Returns
    the wheel filename installed, or 'already installed' if skipped."""
    if not force and _engine_importable():
        return "already installed"

    release = latest_release()
    assets = release.get("assets", [])
    wheel_asset = next((a for a in assets if a["name"].endswith(".whl")), None)
    if wheel_asset is None:
        raise UpdateError(
            f"release '{release.get('tag_name', '?')}' has no .whl engine asset"
        )

    with tempfile.TemporaryDirectory(prefix="omni-engine-") as tmp:
        wheel_path = Path(tmp) / wheel_asset["name"]
        print(f"[omni] downloading {wheel_asset['name']} "
              f"({wheel_asset['size'] / 1e6:.1f} MB) …")
        _download(wheel_asset["browser_download_url"], wheel_path)

        # torch's default PyPI build pulls the full CUDA/GPU toolkit (NVIDIA
        # cuDNN/NCCL/triton/etc, several GB) even on a machine with no GPU.
        # This project only ever runs CPU inference, so pin torch to
        # PyPI's dedicated CPU-only index FIRST -- once it's satisfied
        # there, installing the engine wheel afterward won't touch it
        # again (pip doesn't reinstall an already-satisfied dependency).
        if force or not _torch_importable():
            print("[omni] installing torch (CPU build, ~200 MB) — pip's own "
                  "progress shows below …")
            torch_cmd = [
                sys.executable, "-m", "pip", "install",
                "--index-url", "https://download.pytorch.org/whl/cpu",
                "torch>=2.0",
            ]
            if force:
                torch_cmd.append("--force-reinstall")
            result = subprocess.run(torch_cmd)
            if result.returncode != 0:
                raise UpdateError(
                    "torch install failed — see pip's output above for the reason"
                )

        print(f"[omni] installing {wheel_asset['name']} …")
        cmd = [sys.executable, "-m", "pip", "install", str(wheel_path)]
        if force:
            cmd.append("--force-reinstall")
        # Deliberately NOT capturing output — pip's own download/install
        # progress streams straight to the terminal so this doesn't look
        # stuck during the (often slow) numpy download, if needed.
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise UpdateError(
                "pip install failed — see pip's output above for the reason"
            )

    return wheel_asset["name"]
