"""Entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _frozen_cwd() -> None:
    """Match run.bat: work next to the exe (config.json, dumps)."""
    if getattr(sys, "frozen", False):
        os.chdir(Path(sys.executable).resolve().parent)


if __name__ == "__main__":
    _frozen_cwd()
    from app.ui import main

    main()
