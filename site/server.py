"""
Сайт раздачи: рандомное имя/размер, пароли, API обновлений.
Прод: gunicorn -b 0.0.0.0:$PORT server:app
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import secrets
import string
import time
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template_string, request, send_file, url_for

ROOT = Path(__file__).resolve().parent
RELEASES = ROOT / "releases"
BASE_EXE = RELEASES / "app.exe"
META = RELEASES / "meta.json"
LICENSES = RELEASES / "licenses.json"

LICENSE_SECRET = os.environ.get("LICENSE_SECRET", "ddjj-license-v1-change-in-prod").encode()

app = Flask(__name__)

PAGE = """
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>fucksvinland</title>
<style>
  :root{color-scheme:dark}
  body{margin:0;min-height:100vh;display:grid;place-items:center;
       background:#0c0c0e;color:#e8e8e8;font:15px/1.45 system-ui,sans-serif}
  .box{width:min(420px,92vw);text-align:center}
  h1{font-size:22px;font-weight:700;margin:0 0 18px;letter-spacing:.02em}
  a.btn,button{display:inline-block;padding:14px 28px;border:0;border-radius:10px;
    background:#2a6df4;color:#fff;text-decoration:none;font-weight:600;cursor:pointer;font:inherit}
  a.btn:hover,button:hover{background:#1f57c8}
  .lic{margin:18px 0;padding:14px;border-radius:10px;background:#17171b;font-family:ui-monospace,Consolas,monospace;
       font-size:18px;letter-spacing:.04em;user-select:all;word-break:break-all}
  p{opacity:.6;margin:10px 0 0;font-size:13px}
  .ok{opacity:.85;margin-top:8px}
</style>
</head>
<body>
  <div class="box">
    <h1>fucksvinland</h1>
    {% if license %}
      <p class="ok">Твой пароль — сохрани и вводи при запуске:</p>
      <div class="lic">{{ license }}</div>
      <a class="btn" href="{{ download_url }}">Скачать файл</a>
      <p>v{{ version }}</p>
    {% else %}
      <a class="btn" href="{{ url_for('issue') }}">Получить</a>
      <p>v{{ version }}</p>
    {% endif %}
  </div>
</body>
</html>
"""


def load_meta() -> dict:
    if META.exists():
        return json.loads(META.read_text(encoding="utf-8"))
    return {"version": "1.0.1"}


def save_meta(meta: dict) -> None:
    RELEASES.mkdir(parents=True, exist_ok=True)
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def refresh_hash() -> dict:
    meta = load_meta()
    if BASE_EXE.exists():
        meta["sha256"] = file_sha256(BASE_EXE)
        meta["size"] = BASE_EXE.stat().st_size
    save_meta(meta)
    return meta


def _load_licenses() -> dict:
    if LICENSES.exists():
        try:
            return json.loads(LICENSES.read_text(encoding="utf-8"))
        except Exception:
            return {"keys": {}}
    return {"keys": {}}


def _save_licenses(data: dict) -> None:
    RELEASES.mkdir(parents=True, exist_ok=True)
    LICENSES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_license() -> str:
    raw = secrets.token_hex(8)  # 16 hex chars
    sig = hmac.new(LICENSE_SECRET, raw.encode(), hashlib.sha256).hexdigest()[:8]
    body = (raw + sig).upper()
    return "-".join(body[i : i + 4] for i in range(0, 24, 4))


def normalize_license(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalnum())


def verify_license_key(key: str) -> bool:
    n = normalize_license(key)
    if len(n) != 24:
        return False
    raw, sig = n[:16].lower(), n[16:].lower()
    expect = hmac.new(LICENSE_SECRET, raw.encode(), hashlib.sha256).hexdigest()[:8]
    if not hmac.compare_digest(sig, expect):
        return False
    # accept even if not in DB (signed key) — also record if missing
    data = _load_licenses()
    if n not in data.get("keys", {}):
        data.setdefault("keys", {})[n] = {"created": int(time.time()), "via": "verify"}
        _save_licenses(data)
    return True


def random_name() -> str:
    n = random.randint(8, 14)
    body = "".join(random.choices(string.ascii_lowercase + string.digits, k=n))
    return f"{body}.exe"


def stream_padded():
    pad = random.randint(48 * 1024, 1800 * 1024)
    with BASE_EXE.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            yield chunk
    yield os.urandom(pad)


@app.get("/")
def index():
    meta = load_meta()
    return render_template_string(PAGE, version=meta.get("version", "?"), license=None)


@app.get("/issue")
def issue():
    if not BASE_EXE.exists():
        return "Нет файла releases/app.exe", 404
    key = make_license()
    data = _load_licenses()
    data.setdefault("keys", {})[normalize_license(key)] = {
        "created": int(time.time()),
        "display": key,
    }
    _save_licenses(data)
    meta = load_meta()
    token = secrets.token_urlsafe(12)
    # one-time download token mapped in memory + file
    tokens = data.setdefault("tokens", {})
    tokens[token] = {"exp": int(time.time()) + 3600, "lic": key}
    _save_licenses(data)
    return render_template_string(
        PAGE,
        version=meta.get("version", "?"),
        license=key,
        download_url=url_for("download", t=token),
    )


@app.get("/download")
def download():
    if not BASE_EXE.exists():
        return "Нет файла releases/app.exe", 404
    token = request.args.get("t", "")
    data = _load_licenses()
    tok = (data.get("tokens") or {}).get(token)
    if not tok or int(tok.get("exp", 0)) < int(time.time()):
        return redirect(url_for("issue"))
    # Random filename only — do NOT append junk bytes (broke some Windows/exe loads)
    name = random_name()
    return send_file(
        BASE_EXE,
        as_attachment=True,
        download_name=name,
        mimetype="application/octet-stream",
        max_age=0,
    )


@app.get("/api/version")
def api_version():
    meta = refresh_hash() if request.args.get("refresh") else load_meta()
    if BASE_EXE.exists() and "sha256" not in meta:
        meta = refresh_hash()
    return jsonify(
        {
            "version": meta.get("version", "1.0.1"),
            "sha256": meta.get("sha256", ""),
            "size": meta.get("size", 0),
        }
    )


@app.get("/api/update")
def api_update():
    if not BASE_EXE.exists():
        return "missing", 404
    return send_file(BASE_EXE, as_attachment=True, download_name="update.exe")


@app.post("/api/license/verify")
def api_license_verify():
    body = request.get_json(silent=True) or {}
    key = str(body.get("key") or request.form.get("key") or "")
    ok = verify_license_key(key)
    return jsonify({"ok": ok})


@app.get("/health")
def health():
    return jsonify({"ok": True, "exe": BASE_EXE.exists()})


@app.post("/api/publish")
def api_publish():
    ver = request.form.get("version") or load_meta().get("version", "1.0.1")
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "file required"}), 400
    RELEASES.mkdir(parents=True, exist_ok=True)
    f.save(BASE_EXE)
    meta = {"version": ver, "sha256": file_sha256(BASE_EXE), "size": BASE_EXE.stat().st_size}
    save_meta(meta)
    return jsonify({"ok": True, **meta})


RELEASES.mkdir(parents=True, exist_ok=True)


def ensure_exe() -> None:
    """Pull app.exe from GitHub Release when missing or version outdated."""
    want = (os.environ.get("EXE_VERSION") or "1.0.6").strip()
    default_url = (
        f"https://github.com/offjext/fucksvinland/releases/download/v{want}/app.exe"
    )
    url = os.environ.get("EXE_URL") or default_url
    # Old Render env may still point at v1.0.1 — force URL to match wanted version
    if f"/v{want}/" not in url.replace("\\", "/"):
        url = default_url
    meta = load_meta() if META.exists() else {}
    have = str(meta.get("version", "")).strip()
    ok_file = BASE_EXE.exists() and BASE_EXE.stat().st_size > 1_000_000
    if ok_file and have == want:
        return
    try:
        import urllib.request

        print("Downloading app.exe…", url, "want", want, "have", have)
        RELEASES.mkdir(parents=True, exist_ok=True)
        tmp = BASE_EXE.with_suffix(".tmp")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(BASE_EXE)
        meta = refresh_hash()
        meta["version"] = want
        save_meta(meta)
        print("app.exe ready", BASE_EXE.stat().st_size, "v" + want)
    except Exception as e:
        print("exe download failed:", e)


ensure_exe()
if BASE_EXE.exists() and not META.exists():
    refresh_hash()


if __name__ == "__main__":
    if BASE_EXE.exists():
        refresh_hash()
    else:
        print("Положи exe сюда:", BASE_EXE)
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    print(f"http://127.0.0.1:{port}")
    app.run(host=host, port=port, threaded=True)
