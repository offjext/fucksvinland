"""
Build obfuscated ddjj.exe — keeps source in app/ + ddjj.py.
"""
from __future__ import annotations

import compileall
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "ddjj.py"
APP_SRC = ROOT / "app"
BUILD = ROOT / "_build"
OBF = BUILD / "obf"
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
    OBF.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)


def _minify_tree(src_dir: Path, dst_dir: Path) -> None:
    import python_minifier

    if dst_dir.exists():
        shutil.rmtree(dst_dir, ignore_errors=True)
    dst_dir.mkdir(parents=True, exist_ok=True)
    for path in src_dir.rglob("*.py"):
        rel = path.relative_to(src_dir)
        out = dst_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        code = path.read_text(encoding="utf-8")
        try:
            mini = python_minifier.minify(
                code,
                filename=str(rel),
                remove_annotations=True,
                remove_pass=True,
                remove_literal_statements=True,
                rename_locals=True,
                rename_globals=False,
                hoist_literals=True,
            )
        except Exception:
            mini = code
        out.write_text(mini, encoding="utf-8")


def obfuscate() -> Path:
    if OBF.exists():
        shutil.rmtree(OBF, ignore_errors=True)
    OBF.mkdir(parents=True, exist_ok=True)

    # Minify package + entry (source on disk stays readable)
    _minify_tree(APP_SRC, OBF / "app")
    import python_minifier

    entry_code = SRC.read_text(encoding="utf-8")
    mini = python_minifier.minify(
        entry_code,
        filename="ddjj.py",
        remove_annotations=True,
        remove_pass=True,
        remove_literal_statements=True,
        rename_locals=True,
        rename_globals=False,
        hoist_literals=True,
    )
    out = OBF / "ddjj.py"
    out.write_text(mini, encoding="utf-8")
    compileall.compile_dir(str(OBF), quiet=1)
    print("Obfuscation: python-minifier OK (app/ + ddjj.py)", flush=True)
    return out


def build_exe(entry: Path) -> Path:
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
        str(OBF),
        "--collect-all",
        "rapidocr_onnxruntime",
        "--collect-all",
        "onnxruntime",
    ]
    for h in hidden:
        cmd += ["--hidden-import", h]
    cmd.append(str(entry))
    run(cmd)

    exe = DIST / "ddjj.exe"
    if not exe.exists():
        raise SystemExit("Build failed: dist/ddjj.exe missing")
    return exe


def main() -> None:
    if not SRC.exists() or not APP_SRC.exists():
        raise SystemExit("Need ddjj.py and app/ package")
    print(f"Source: {SRC} + {APP_SRC}")
    clean()
    entry = obfuscate()
    exe = build_exe(entry)
    cfg = ROOT / "config.json"
    if cfg.exists():
        shutil.copy2(cfg, DIST / "config.json")

    # Always publish to site for hosting / downloads
    releases = ROOT / "site" / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, releases / "app.exe")
    if cfg.exists():
        shutil.copy2(cfg, releases / "config.json")
    import hashlib
    import json

    raw = (releases / "app.exe").read_bytes()
    meta = {
        "version": "1.0.1",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
    }
    (releases / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Published -> site/releases/app.exe ({meta['size']/1024/1024:.1f} MB)")

    print()
    print("=" * 50)
    print(f"OK  {exe}")
    print(f"    size {exe.stat().st_size / 1024 / 1024:.1f} MB")
    print("=" * 50)


if __name__ == "__main__":
    main()
