from __future__ import annotations

import time
import tkinter as tk

import mss
import numpy as np
from PIL import Image, ImageTk


def pct_box(mon: dict, roi: dict) -> dict:
    w, h = mon["width"], mon["height"]
    return {
        "left": mon["left"] + int(w * float(roi["left_pct"])),
        "top": mon["top"] + int(h * float(roi["top_pct"])),
        "width": max(32, int(w * float(roi["width_pct"]))),
        "height": max(16, int(h * float(roi["height_pct"]))),
    }


def resolve_roi(mon: dict, roi: dict) -> dict:
    """Absolute pixels (left/top/width/height) or legacy percent ROI."""
    if all(k in roi for k in ("left", "top", "width", "height")):
        return {
            "left": int(roi["left"]),
            "top": int(roi["top"]),
            "width": max(8, int(roi["width"])),
            "height": max(8, int(roi["height"])),
        }
    return pct_box(mon, roi)


def virtual_screen() -> tuple[int, int, int, int]:
    """left, top, width, height of the virtual desktop."""
    with mss.mss() as sct:
        m = sct.monitors[0]
        return int(m["left"]), int(m["top"]), int(m["width"]), int(m["height"])


class RegionSelector(tk.Toplevel):
    """Fullscreen drag-select over a live screenshot (game stays visible)."""

    def __init__(self, master: tk.Misc, title_hint: str) -> None:
        super().__init__(master)
        self.result: dict | None = None
        self._x0 = self._y0 = 0
        self._rect = None
        self._photo = None

        left, top, width, height = virtual_screen()
        self._vx, self._vy = left, top

        # Capture desktop BEFORE overlay so user sees real game/UI
        try:
            with mss.mss() as sct:
                raw = np.asarray(sct.grab(sct.monitors[0]))
            rgb = raw[:, :, [2, 1, 0]]
            img = Image.fromarray(rgb)
            if img.size != (width, height):
                img = img.resize((width, height), Image.Resampling.BILINEAR)
            self._photo = ImageTk.PhotoImage(img)
        except Exception:
            self._photo = None

        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        # Fully opaque — screenshot is the background (alpha made old dark overlay unreadable)
        try:
            self.attributes("-alpha", 1.0)
        except Exception:
            pass
        self.geometry(f"{width}x{height}+{left}+{top}")
        self.configure(bg="#000000", cursor="crosshair")

        self.canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            highlightthickness=0,
            cursor="crosshair",
            bg="#000000",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        if self._photo is not None:
            self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self.canvas.create_rectangle(0, 0, width, 56, fill="#000000", stipple="gray50", outline="")
        self.canvas.create_text(
            width // 2,
            28,
            text=f"{title_hint}  |  тяни мышью  |  Esc — отмена",
            fill="#ffffff",
            font=("Segoe UI", 16, "bold"),
        )

        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.bind("<Escape>", self._cancel)
        self.canvas.bind("<Escape>", self._cancel)

        self.deiconify()
        self.lift()
        self.focus_force()
        self.grab_set()

    def _down(self, e: tk.Event) -> None:
        self._x0, self._y0 = e.x_root, e.y_root
        if self._rect is not None:
            self.canvas.delete(self._rect)
        x = e.x_root - self._vx
        y = e.y_root - self._vy
        self._rect = self.canvas.create_rectangle(
            x, y, x, y, outline="#00e5ff", width=3, fill=""
        )

    def _drag(self, e: tk.Event) -> None:
        if self._rect is None:
            return
        x0 = self._x0 - self._vx
        y0 = self._y0 - self._vy
        x1 = e.x_root - self._vx
        y1 = e.y_root - self._vy
        self.canvas.coords(self._rect, x0, y0, x1, y1)

    def _up(self, e: tk.Event) -> None:
        x0, x1 = sorted((self._x0, e.x_root))
        y0, y1 = sorted((self._y0, e.y_root))
        w, h = x1 - x0, y1 - y0
        if w < 8 or h < 8:
            self.result = None
        else:
            self.result = {"left": int(x0), "top": int(y0), "width": int(w), "height": int(h)}
        self._finish()

    def _cancel(self, _e=None) -> None:
        self.result = None
        self._finish()

    def _finish(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def pick(self) -> dict | None:
        self.wait_window()
        return self.result
