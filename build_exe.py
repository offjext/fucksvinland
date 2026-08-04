"""
Build ddjj.exe (no obfuscation) from app/ + ddjj.py, then publish to site.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "ddjj.py"
APP_SRC = ROOT / "app"
BUILD = ROOT / "_build"
DIST = ROOT / "dist"
WORK = BUILD / "pyi"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(">", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(cwd or ROOT))


def clean() -> None:
    for p in (BUILD, DIST):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)


def build_exe() -> Path:
    hidden = [
        "app",
        "app.ui",
        "app.worker",
        "app.ocr",
        "app.bar",
        "app.subtitles",
        "app.auth",
        "app.mouse",
        "app.roi",
        "app.frames",
        "app.paths",
        "keyboard",
        "mss",
        "PIL",
        "numpy",
        "win32api",
        "win32con",
        "ctypes",
    ]
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "ddjj",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(BUILD),
        "--paths",
        str(ROOT),
        "--collect-all",
        "rapidocr_onnxruntime",
        "--collect-all",
        "onnxruntime",
    ]
    for h in hidden:
        cmd += ["--hidden-import", h]
    cmd.append(str(SRC))
    run(cmd)

    exe = DIST / "ddjj.exe"
    if not exe.exists():
        raise SystemExit("Build failed: dist/ddjj.exe missing")
    return exe


def _version() -> str:
    p = ROOT / "VERSION.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip() or "1.0.0"
    return "1.0.0"


def main() -> None:
    if not SRC.exists() or not APP_SRC.exists():
        raise SystemExit("Need ddjj.py and app/ package")
    ver = _version()
    print(f"Source (no obfuscation): {SRC} + {APP_SRC}  v{ver}")
    clean()
    exe = build_exe()
    cfg = ROOT / "config.json"
    if cfg.exists():
        shutil.copy2(cfg, DIST / "config.json")

    releases = ROOT / "site" / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, releases / "app.exe")
    if cfg.exists():
        shutil.copy2(cfg, releases / "config.json")

    raw = (releases / "app.exe").read_bytes()
    meta = {
        "version": ver,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
    }
    (releases / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Published -> site/releases/app.exe ({meta['size']/1024/1024:.1f} MB)")

    try:
        run([sys.executable, str(ROOT / "publish_release.py"), ver])
    except Exception as e:
        print("WARN site upload failed:", e)

    print()
    print("=" * 50)
    print(f"OK  {exe}")
    print(f"    v{ver}  plain (no obf)  {exe.stat().st_size / 1024 / 1024:.1f} MB")
    print("=" * 50)


if __name__ == "__main__":
    main()
