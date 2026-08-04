from __future__ import annotations

import sys
from pathlib import Path

def _app_root() -> Path:
    """Folder with config.json — next to .exe when frozen, else script dir."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = _app_root()
CONFIG_PATH = ROOT / "config.json"
