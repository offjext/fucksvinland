from __future__ import annotations

import time
import tkinter as tk

import mss

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
    """Fullscreen drag-select overlay. Returns absolute screen box or None."""

    def __init__(self, master: tk.Misc, title_hint: str) -> None:
        super().__init__(master)
        self.result: dict | None = None
        self._x0 = self._y0 = 0
        self._rect = None

        left, top, width, height = virtual_screen()
        self._vx, self._vy = left, top

        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.28)
        except Exception:
            pass
        self.geometry(f"{width}x{height}+{left}+{top}")
        self.configure(bg="#000000", cursor="crosshair")

        self.canvas = tk.Canvas(
            self,
            bg="#101010",
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_text(
            width // 2,
            40,
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
            x, y, x, y, outline="#5cdbff", width=2, fill="#5cdbff", stipple="gray50"
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
