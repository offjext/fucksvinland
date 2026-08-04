from __future__ import annotations

import sys
from pathlib import Path


def _app_root() -> Path:
    """Folder with config.json — next to .exe when frozen, else project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # app/paths.py → project root (ddjj.py / config.json)
    return Path(__file__).resolve().parent.parent


ROOT = _app_root()
CONFIG_PATH = ROOT / "config.json"
