"""
Fetches model generations from GitHub Releases on the omni repo itself —
the same public repo distributes the CLI (via git clone/pip) and the model
weights (via release assets), so there's no separate registry server to
stand up.

Release convention: tag name is "<generation>-<year>", e.g. "andromeda-2026".
Each release is expected to have one *.pt asset (the model weights) and one
*.so asset (the matching arithmetic coder shared library).

Uses only the standard library (urllib) so the CLI itself stays
dependency-free — this is the one place it talks to the network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
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
