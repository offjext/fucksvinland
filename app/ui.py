from __future__ import annotations

import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import keyboard
from PIL import ImageTk

from .auth import ask_access_password, check_and_apply_update
from .frames import FrameBus
from .paths import CONFIG_PATH, ROOT
from .roi import RegionSelector
from .worker import FishWorker, PreviewWorker, WorkerHooks

class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(" ")
        self.geometry("440x640")
        self.minsize(400, 580)
        self.configure(bg="#1a1a1a")
        self.attributes("-topmost", True)

        self.cfg = self.load_config()
        self.worker: FishWorker | None = None
        self.stop_flag = False
        self.app_alive = True
        self.preview_paused = False
        self.frames = FrameBus()
        self._preview_seq = -1
        self.status_var = tk.StringVar(value="готов")
        self.fps_var = tk.StringVar(value="")
        self._photo_bar = None
        self._photo_sub = None

        self._build_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.preview_worker = PreviewWorker(
            get_cfg=self._live_cfg,
            frames=self.frames,
            alive=lambda: self.app_alive,
            is_paused=lambda: self.preview_paused,
        )
        self.preview_worker.start()
        self.after(80, self._ui_tick)
        self.after(200, self._force_preview_once)
        self.after(400, self._check_update)

        try:
            keyboard.add_hotkey("f4", self.toggle)
        except Exception:
            pass

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#1a1a1a")
        style.configure("TLabel", background="#1a1a1a", foreground="#ddd", font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#1a1a1a", foreground="#9cf", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 9), padding=6)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        btns = ttk.Frame(root)
        btns.pack(fill=tk.X, pady=(0, 6))
        self.btn_start = ttk.Button(btns, text="Старт (F4)", command=self.toggle)
        self.btn_start.pack(side=tk.LEFT)
        ttk.Button(btns, text="Бар", command=lambda: self.pick_zone("bar_roi")).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Текст", command=lambda: self.pick_zone("subtitle_roi")).pack(
            side=tk.LEFT
        )

        self.zone_bar_var = tk.StringVar(value=self._zone_text("bar_roi"))
        self.zone_sub_var = tk.StringVar(value=self._zone_text("subtitle_roi"))
        ttk.Label(root, textvariable=self.zone_bar_var).pack(anchor="w")
        ttk.Label(root, textvariable=self.zone_sub_var).pack(anchor="w", pady=(0, 4))

        status_row = ttk.Frame(root)
        status_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(status_row, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self.fps_var).pack(side=tk.RIGHT)

        # Fixed pixel canvases — Label+char-height was collapsing to a black strip
        prev = ttk.Frame(root)
        prev.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(prev, text="что видит бар").pack(anchor="w")
        self.canvas_bar = tk.Canvas(
            prev, width=400, height=80, bg="#0a0a0a", highlightthickness=1, highlightbackground="#00c8dc"
        )
        self.canvas_bar.pack(pady=(0, 6))
        self.canvas_bar.create_text(200, 40, text="выбери зону: Бар", fill="#555", font=("Segoe UI", 10))
        ttk.Label(prev, text="что видит текст (субтитры)").pack(anchor="w")
        self.canvas_sub = tk.Canvas(
            prev, width=400, height=140, bg="#0a0a0a", highlightthickness=1, highlightbackground="#00c8dc"
        )
        self.canvas_sub.pack(pady=(0, 2))
        self.canvas_sub.create_text(200, 70, text="выбери зону: Текст", fill="#555", font=("Segoe UI", 10))

        self.log_box = tk.Text(
            root,
            height=5,
            bg="#111",
            fg="#aaa",
            insertbackground="#aaa",
            relief=tk.FLAT,
            font=("Consolas", 8),
        )
        self.log_box.pack(fill=tk.BOTH, expand=True)

    def _live_cfg(self) -> dict:
        """Always prefer in-memory cfg (updated on zone pick)."""
        return self.cfg

    def _show_preview(self, which: str, img) -> None:
        photo = ImageTk.PhotoImage(img)
        if which == "bar":
            self._photo_bar = photo
            c = self.canvas_bar
            c.delete("all")
            c.create_image(200, 40, image=photo)
        else:
            self._photo_sub = photo
            c = self.canvas_sub
            c.delete("all")
            c.create_image(200, 70, image=photo)

    def _force_preview_once(self) -> None:
        """Immediate snapshot of saved zones so panes aren't empty on start."""
        try:
            import mss
            import numpy as np
            from .bar import bgr_to_rgb, thumb_bar, thumb_sub
            from .roi import resolve_roi

            with mss.mss() as sct:
                mon = sct.monitors[0]
                bar_roi = self.cfg.get("bar_roi") or {}
                sub_roi = self.cfg.get("subtitle_roi") or {}
                if all(k in bar_roi for k in ("left", "top", "width", "height")):
                    raw = np.asarray(sct.grab(resolve_roi(mon, bar_roi)))
                    self._show_preview("bar", thumb_bar(bgr_to_rgb(raw), None, None, False))
                if all(k in sub_roi for k in ("left", "top", "width", "height")):
                    raw = np.asarray(sct.grab(resolve_roi(mon, sub_roi)))
                    self._show_preview("sub", thumb_sub(bgr_to_rgb(raw)))
        except Exception as e:
            self.append_log(f"превью: {e}")

    def _ui_tick(self) -> None:
        if not self.app_alive:
            return
        bar, sub, fps, seq = self.frames.pull()
        if seq != self._preview_seq:
            self._preview_seq = seq
            self.fps_var.set(f"{fps:.0f} fps")
            if bar is not None:
                self._show_preview("bar", bar)
            if sub is not None:
                self._show_preview("sub", sub)
        self.after(80, self._ui_tick)

    def _check_update(self) -> None:
        def work() -> None:
            try:
                msg = check_and_apply_update(self.cfg)
                if msg:
                    self.after(0, lambda: self.append_log(msg))
            except Exception as e:
                self.after(0, lambda: self.append_log(f"обнова: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def load_config(self) -> dict:
        if not CONFIG_PATH.exists():
            return {"monitor": 1, "language": "en", "fps": 60, "timing": {}, "mouse": {}}
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def save_config(self) -> None:
        CONFIG_PATH.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def _zone_text(self, key: str) -> str:
        name = "бар" if key == "bar_roi" else "текст"
        roi = self.cfg.get(key, {})
        if all(k in roi for k in ("left", "top", "width", "height")):
            return f"{name}: {roi['width']}x{roi['height']}"
        return f"{name}: нет"

    def refresh_zone_labels(self) -> None:
        self.zone_bar_var.set(self._zone_text("bar_roi"))
        self.zone_sub_var.set(self._zone_text("subtitle_roi"))

    def pick_zone(self, key: str) -> None:
        if self.running():
            messagebox.showwarning(" ", "Сначала стоп (F4).")
            return
        title = "Бар" if key == "bar_roi" else "Текст"
        was_paused = self.preview_paused
        self.preview_paused = True
        self.withdraw()
        self.update_idletasks()
        # Give Windows/Minecraft time to redraw before we snapshot
        time.sleep(0.35)
        try:
            box = RegionSelector(self, title).pick()
        finally:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.preview_paused = was_paused
        if not box:
            return
        self.cfg = self.load_config()
        self.cfg[key] = box
        self.cfg["language"] = "en"
        self.save_config()
        self.refresh_zone_labels()
        try:
            import mss
            import numpy as np
            from .bar import bgr_to_rgb, thumb_bar, thumb_sub

            with mss.mss() as sct:
                raw = np.asarray(sct.grab(box))
                rgb = bgr_to_rgb(raw)
                if key == "bar_roi":
                    self._show_preview("bar", thumb_bar(rgb, None, None, False))
                else:
                    self._show_preview("sub", thumb_sub(rgb))
        except Exception as e:
            self.append_log(f"превью: {e}")

    def append_log(self, msg: str) -> None:
        def _do() -> None:
            self.log_box.insert(tk.END, msg + "\n")
            lines = int(self.log_box.index("end-1c").split(".")[0])
            if lines > 120:
                self.log_box.delete("1.0", f"{lines - 80}.0")
            self.log_box.see(tk.END)

        self.after(0, _do)

    def set_status(self, msg: str) -> None:
        self.after(0, lambda: self.status_var.set(msg))

    def running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def toggle(self) -> None:
        if self.running():
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self.running():
            return
        self.cfg = self.load_config()
        self.cfg["language"] = "en"
        self.stop_flag = False
        self.preview_paused = False

        def set_preview_paused(paused: bool) -> None:
            self.preview_paused = paused

        hooks = WorkerHooks(
            on_status=self.set_status,
            on_log=self.append_log,
            frames=self.frames,
            should_stop=lambda: self.stop_flag,
            set_preview_paused=set_preview_paused,
        )
        self.worker = FishWorker(self.cfg, "en", hooks)
        self.worker.start()
        self.btn_start.configure(text="Стоп (F4)")

    def stop(self) -> None:
        self.stop_flag = True
        self.preview_paused = False
        self.btn_start.configure(text="Старт (F4)")
        self.set_status("стоп…")

    def on_close(self) -> None:
        self.app_alive = False
        self.stop_flag = True
        self.destroy()


def main() -> None:
    try:
        from .roi import _ensure_dpi_aware

        _ensure_dpi_aware()
    except Exception:
        pass
    cfg = {}
    try:
        from .paths import CONFIG_PATH
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    if not ask_access_password(cfg):
        return
    app = App()
    app.mainloop()
