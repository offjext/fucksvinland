"""Publish app.exe to GitHub Release + refresh Pages version.json"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GH = ROOT / "tools" / "gh.exe"
EXE = ROOT / "site" / "releases" / "app.exe"
if not EXE.exists():
    EXE = ROOT / "dist" / "ddjj.exe"
VER = "1.0.1"
TAG = f"v{VER}"
REPO = "offjext/fucksvinland"


def run(cmd: list[str]) -> None:
    print(">", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


def main() -> None:
    if not EXE.exists():
        raise SystemExit(f"missing {EXE} — run build_exe.py first")
    if not GH.exists():
        raise SystemExit("missing tools/gh.exe")

    raw = EXE.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    size = len(raw)
    download = f"https://github.com/{REPO}/releases/download/{TAG}/app.exe"

    meta = {
        "version": VER,
        "sha256": sha,
        "size": size,
        "download_url": download,
    }
    pages = ROOT / "site" / "static_pages"
    pages.mkdir(parents=True, exist_ok=True)
    (pages / "version.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(meta)

    # ensure release exists, upload asset
    view = subprocess.run(
        [str(GH), "release", "view", TAG, "-R", REPO],
        capture_output=True,
        text=True,
    )
    if view.returncode != 0:
        run(
            [
                str(GH),
                "release",
                "create",
                TAG,
                "-R",
                REPO,
                "-t",
                TAG,
                "-n",
                f"fucksvinland {VER}",
            ]
        )
    # replace asset
    subprocess.run(
        [str(GH), "release", "delete-asset", TAG, "app.exe", "-R", REPO, "--yes"],
        capture_output=True,
    )
    run([str(GH), "release", "upload", TAG, str(EXE) + "#app.exe", "-R", REPO, "--clobber"])
    print("OK release + version.json")


if __name__ == "__main__":
    main()
