"""Publish site/releases/app.exe → GitHub Release + live Render host."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GH = ROOT / "tools" / "gh.exe"
EXE = ROOT / "site" / "releases" / "app.exe"
if not EXE.exists():
    EXE = ROOT / "dist" / "ddjj.exe"
REPO = "offjext/fucksvinland"
SITE = "https://fucksvinland.onrender.com"


def version() -> str:
    p = ROOT / "VERSION.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip() or "1.0.0"
    return "1.0.0"


def run(cmd: list[str]) -> None:
    print(">", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


def publish_github(ver: str, exe: Path) -> dict:
    if not GH.exists():
        raise SystemExit("missing tools/gh.exe")
    raw = exe.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    size = len(raw)
    tag = f"v{ver}"
    download = f"https://github.com/{REPO}/releases/download/{tag}/app.exe"
    meta = {
        "version": ver,
        "sha256": sha,
        "size": size,
        "download_url": download,
    }
    pages = ROOT / "site" / "static_pages"
    pages.mkdir(parents=True, exist_ok=True)
    (pages / "version.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    releases = ROOT / "site" / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    (releases / "meta.json").write_text(
        json.dumps({"version": ver, "sha256": sha, "size": size}, indent=2),
        encoding="utf-8",
    )
    print(meta)

    view = subprocess.run(
        [str(GH), "release", "view", tag, "-R", REPO],
        capture_output=True,
        text=True,
    )
    if view.returncode != 0:
        run(
            [
                str(GH),
                "release",
                "create",
                tag,
                "-R",
                REPO,
                "-t",
                tag,
                "-n",
                f"fucksvinland {ver}",
            ]
        )
    subprocess.run(
        [str(GH), "release", "delete-asset", tag, "app.exe", "-R", REPO, "--yes"],
        capture_output=True,
    )
    run([str(GH), "release", "upload", tag, str(exe) + "#app.exe", "-R", REPO, "--clobber"])
    print("OK GitHub release", tag)
    return meta


def publish_render(ver: str, exe: Path) -> None:
    """Push exe to live Render so /issue matches the build."""
    print("Uploading to Render…", SITE)
    curl = [
        "curl",
        "-sS",
        "-X",
        "POST",
        f"{SITE}/api/publish",
        "-F",
        f"version={ver}",
        "-F",
        f"file=@{exe}",
        "--max-time",
        "600",
    ]
    try:
        out = subprocess.check_output(curl, cwd=str(ROOT), stderr=subprocess.STDOUT)
        text = out.decode("utf-8", errors="replace")
        if '"ok": true' in text.replace(" ", "") or '"ok":true' in text:
            print("OK Render", text[:200])
        else:
            # curl may get HTML noise but upload can still succeed — verify
            print("Render response (truncated):", text[:120].replace("\n", " "))
    except subprocess.CalledProcessError as e:
        print("Render upload warning:", e.output[:300] if e.output else e)
    try:
        with urllib.request.urlopen(f"{SITE}/api/version", timeout=60) as r:
            got = json.loads(r.read().decode())
        print("Render /api/version:", got)
        if str(got.get("version")) != str(ver):
            print("WARN: Render still on", got.get("version"), "— retry upload")
            subprocess.check_call(curl, cwd=str(ROOT))
            with urllib.request.urlopen(f"{SITE}/api/version", timeout=60) as r:
                print("Render /api/version:", json.loads(r.read().decode()))
    except Exception as e:
        print("Render verify failed:", e)


def main() -> None:
    if not EXE.exists():
        raise SystemExit(f"missing {EXE} — run build_exe.py first")
    ver = version()
    if len(sys.argv) > 1:
        ver = sys.argv[1].lstrip("v")
    publish_github(ver, EXE)
    publish_render(ver, EXE)
    print("OK site publish", ver)


if __name__ == "__main__":
    main()
