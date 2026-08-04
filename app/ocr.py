from __future__ import annotations

import threading
import time

import numpy as np
from PIL import Image

from .subtitles import bite_matched

def preprocess_sub_rgb(rgb: np.ndarray) -> np.ndarray:
    """Fast contrast boost for subtitle OCR (smaller upscale = faster bite)."""
    img = Image.fromarray(rgb)
    img = img.resize(
        (max(8, int(img.width * 1.5)), max(8, int(img.height * 1.5))),
        Image.Resampling.NEAREST,
    )
    arr = np.asarray(img).astype(np.float32)
    gray = arr.mean(axis=2)
    mask = gray > 110
    out = np.zeros_like(arr)
    out[mask] = 255
    out[~mask] = 15
    return out.astype(np.uint8)


class OcrEngine:
    def __init__(self) -> None:
        self._ocr = None
        self._err: str | None = None
        self._lock = threading.Lock()

    def ensure(self) -> bool:
        if self._ocr is not None:
            return True
        if self._err:
            return False
        try:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
            return True
        except Exception as e:
            self._err = str(e)
            return False

    @property
    def error(self) -> str | None:
        return self._err

    def read(self, rgb: np.ndarray) -> str:
        if not self.ensure() or self._ocr is None:
            return ""
        arr = preprocess_sub_rgb(rgb)
        with self._lock:
            try:
                result, _ = self._ocr(arr)
            except Exception:
                return ""
        if not result:
            return ""
        lines = []
        for row in result:
            if len(row) >= 2 and isinstance(row[1], str):
                lines.append(row[1])
        return " ".join(lines)


class AsyncOcr(threading.Thread):
    """OCR never blocks fishing / preview loops."""

    def __init__(self, lang: str, engine: OcrEngine) -> None:
        super().__init__(daemon=True)
        self.lang = lang
        self.engine = engine
        self._lock = threading.Lock()
        self._pending: np.ndarray | None = None
        self._text = ""
        self._bite = False
        self._stop = False
        self._was_bite = False

    def stop(self) -> None:
        self._stop = True

    def submit(self, rgb: np.ndarray) -> None:
        with self._lock:
            self._pending = rgb  # drop older frames

    def consume_bite(self) -> tuple[bool, str]:
        with self._lock:
            if self._bite:
                self._bite = False
                text = self._text
                return True, text
            return False, self._text

    def clear(self) -> None:
        with self._lock:
            self._pending = None
            self._bite = False
            self._text = ""
            self._was_bite = False

    def resync(self) -> None:
        """Set rising-edge baseline to current text without firing a bite."""
        with self._lock:
            matched = bool(self._text) and bite_matched(self._text, self.lang)
            self._was_bite = matched
            self._bite = False

    def soft_reset(self) -> None:
        """Drop pending bite, keep text, treat current as already-seen (stale OK)."""
        with self._lock:
            self._pending = None
            self._bite = False
            if self._text and bite_matched(self._text, self.lang):
                self._was_bite = True

    def peek_text(self) -> str:
        with self._lock:
            return self._text

    def run(self) -> None:
        self.engine.ensure()
        while not self._stop:
            with self._lock:
                frame = self._pending
                self._pending = None
            if frame is None:
                time.sleep(0.008)
                continue
            try:
                text = self.engine.read(frame)
            except Exception:
                text = ""
            matched = bool(text) and bite_matched(text, self.lang)
            with self._lock:
                self._text = text
                # Rising edge only — stale/lingering subtitles never re-fire alone.
                if matched and not self._was_bite:
                    self._bite = True
                if not matched:
                    self._was_bite = False
                else:
                    self._was_bite = True
            time.sleep(0.01)
