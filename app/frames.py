from __future__ import annotations

import threading

from PIL import Image

class FrameBus:
    """Latest-frame mailbox; stores already-resized thumbs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.bar: Image.Image | None = None
        self.sub: Image.Image | None = None
        self.fps: float = 0.0
        self.seq: int = 0

    def push(self, bar: Image.Image | None, sub: Image.Image | None, fps: float) -> None:
        with self._lock:
            if bar is not None:
                self.bar = bar
            if sub is not None:
                self.sub = sub
            self.fps = fps
            self.seq += 1

    def pull(self) -> tuple[Image.Image | None, Image.Image | None, float, int]:
        with self._lock:
            return self.bar, self.sub, self.fps, self.seq

