from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import messagebox, simpledialog

from .paths import ROOT

# silent master (never shown in UI)
_MASTER = "бурмалда"
APP_VERSION = "1.0.1"
_LICENSE_SECRET = os.environ.get("LICENSE_SECRET", "ddjj-license-v1-change-in-prod").encode()


def _normalize_license(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _license_ok_local(key: str) -> bool:
    n = _normalize_license(key)
    if len(n) != 24:
        return False
    raw, sig = n[:16].lower(), n[16:].lower()
    expect = hmac.new(_LICENSE_SECRET, raw.encode(), hashlib.sha256).hexdigest()[:8]
    return hmac.compare_digest(sig, expect)


def _license_ok_remote(cfg: dict, key: str) -> bool:
    base = str(cfg.get("update_url") or "").rstrip("/")
    if not base:
        return False
    try:
        req = urllib.request.Request(
            f"{base}/api/license/verify",
            data=json.dumps({"key": key}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        return bool(data.get("ok"))
    except Exception:
        return False


def ask_access_password(cfg: dict | None = None) -> bool:
    cfg = cfg or {}
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        while True:
            pwd = simpledialog.askstring(
                " ",
                "Лицензия:",
                show="*",
                parent=root,
            )
            if pwd is None:
                return False
            if pwd == _MASTER:
                return True
            if _license_ok_local(pwd) or _license_ok_remote(cfg, pwd):
                return True
            messagebox.showerror(" ", "Неверная лицензия", parent=root)
    finally:
        root.destroy()


def check_and_apply_update(cfg: dict) -> str | None:
    """Download newer build from update_url (/api/version or /version.json)."""
    import urllib.request

    base = str(cfg.get("update_url") or "").rstrip("/")
    if not base:
        return None
    if not getattr(sys, "frozen", False):
        return None

    info = None
    dl = ""
    for path in ("/api/version", "/version.json"):
        try:
            with urllib.request.urlopen(base + path, timeout=8) as r:
                info = json.loads(r.read().decode("utf-8"))
            break
        except Exception:
            continue
    if not info:
        return None
    remote = str(info.get("version") or "")
    if not remote or remote == APP_VERSION:
        return None

    dl = str(info.get("download_url") or "")
    if not dl:
        dl = f"{base}/api/update"
    data = urllib.request.urlopen(dl, timeout=180).read()
    expect = str(info.get("sha256") or "")
    if expect:
        got = hashlib.sha256(data).hexdigest()
        if got.lower() != expect.lower():
            return "обнова: хеш не совпал"

    exe = Path(sys.executable).resolve()
    tmp = Path(tempfile.gettempdir()) / f"upd_{os.getpid()}.exe"
    tmp.write_bytes(data)
    bat = Path(tempfile.gettempdir()) / f"upd_{os.getpid()}.bat"
    bat.write_text(
        "\n".join(
            [
                "@echo off",
                "timeout /t 2 /nobreak >nul",
                f'copy /y "{tmp}" "{exe}" >nul',
                f'start "" "{exe}"',
                f'del "{tmp}" >nul 2>&1',
                f'del "%~f0"',
            ]
        ),
        encoding="utf-8",
    )
    subprocess.Popen(["cmd", "/c", str(bat)], close_fds=True)
    os._exit(0)
    return None
