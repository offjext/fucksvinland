from __future__ import annotations

import numpy as np
from PIL import Image

def bgr_to_rgb(frame: np.ndarray) -> np.ndarray:
    return frame[:, :, [2, 1, 0]]


def in_range(rgb: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    return np.all((rgb >= low) & (rgb <= high), axis=2)


def find_white_x(rgb: np.ndarray, white_min: np.ndarray) -> int | None:
    """Thin gray/white vertical tick on dark track (often ~170, not pure 255)."""
    h, w, _ = rgb.shape
    track_w = max(8, int(w * 0.78))  # exclude mouse icon panel on the right
    r = rgb[:, :track_w, 0].astype(np.int16)
    g = rgb[:, :track_w, 1].astype(np.int16)
    b = rgb[:, :track_w, 2].astype(np.int16)
    lum = (r + g + b) // 3
    near_white = (np.abs(r - g) <= 30) & (np.abs(g - b) <= 30) & (np.abs(r - b) <= 30)
    left = np.pad(lum, ((0, 0), (2, 0)), mode="edge")[:, :-2]
    right = np.pad(lum, ((0, 0), (0, 2)), mode="edge")[:, 2:]
    peak = (lum >= left + 30) & (lum >= right + 30) & (lum >= 115) & near_white
    soft = (lum >= 150) & near_white
    score = peak.sum(axis=0).astype(np.float64) * 4.0 + soft.sum(axis=0).astype(np.float64)
    if float(score.max()) < 1.0:
        return None
    kernel = np.array([0.25, 0.7, 1.0, 0.7, 0.25])
    smooth = np.convolve(np.pad(score, 2, mode="edge"), kernel, mode="valid")
    x = int(np.argmax(smooth))
    if smooth[x] < 1.0:
        return None
    return x


def has_dark_hud(rgb: np.ndarray) -> bool:
    """Fishing UI frame is dark gray; sky is bright — reject sky ROI."""
    mean = rgb.astype(np.float32).mean(axis=2)
    dark = mean < 90
    return int(dark.sum()) >= max(20, int(rgb.shape[0] * rgb.shape[1] * 0.05))


def find_zone(
    mask: np.ndarray,
    max_width_frac: float = 0.65,
    min_col: int = 2,
    min_width: int = 8,
) -> tuple[int, int] | None:
    """Solid colored block — ignores thin 1px border / dash lines."""
    if mask.size == 0:
        return None
    h = mask.shape[0]
    need = max(min_col, int(h * 0.04))
    col = mask.sum(axis=0) >= need
    if not col.any():
        return None
    idx = np.where(col)[0]
    groups: list[tuple[int, int]] = []
    start = prev = int(idx[0])
    for x in idx[1:]:
        x = int(x)
        if x - prev <= 8:
            prev = x
            continue
        groups.append((start, prev + 1))
        start = prev = x
    groups.append((start, prev + 1))
    x0, x1 = max(groups, key=lambda g: g[1] - g[0])
    w = mask.shape[1]
    zw = x1 - x0
    if zw < min_width or zw > max(24, int(w * max_width_frac)):
        return None
    return x0, x1


def zone_column_height(mask: np.ndarray, zone: tuple[int, int]) -> int:
    x0, x1 = zone
    if x1 <= x0:
        return 0
    return int(mask[:, x0:x1].sum(axis=0).max()) if mask.size else 0


def zone_fill_score(mask: np.ndarray, zone: tuple[int, int]) -> float:
    """How solid a block is (0..1). Thin dashes score very low."""
    x0, x1 = zone
    if x1 <= x0 or mask.size == 0:
        return 0.0
    slab = mask[:, x0:x1]
    # normalize by the occupied vertical span, not full ROI padding
    rows = np.where(slab.any(axis=1))[0]
    if len(rows) == 0:
        return 0.0
    band = slab[int(rows[0]) : int(rows[-1]) + 1]
    h = band.shape[0]
    if h <= 0:
        return 0.0
    return float(band.sum(axis=0).mean() / h)


def cyan_mask(rgb: np.ndarray) -> np.ndarray:
    """Blue hit-zone — e.g. (47,101,130) / (70,150,192)."""
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    return (
        (b > 90)
        & (b < 240)
        & (g > 50)
        & (g < 210)
        & (r < 130)
        & (b > r + 20)
        & (b >= g - 8)
        & (g > r + 8)
    )


def yellow_mask(rgb: np.ndarray) -> np.ndarray:
    """Rare yellow / gold hit-zone (same shape as blue, different color)."""
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    return (
        (r > 130)
        & (g > 100)
        & (b < 140)
        & (r >= g - 25)
        & (r > b + 25)
        & (g > b + 15)
        & ((r.astype(np.int32) + g) > 240)
        & (r + g > 2 * b + 40)
    )


def detect_bar(rgb: np.ndarray, colors: dict) -> tuple[bool, bool, int | None, tuple[int, int] | None]:
    white_min = np.array(colors["white_min"], dtype=np.uint8)

    if not has_dark_hud(rgb):
        return False, False, None, None

    blue = cyan_mask(rgb)
    yellow = yellow_mask(rgb)
    y_zone = find_zone(yellow, 0.55, min_width=12)
    b_zone = find_zone(blue, 0.55, min_width=12)

    # reject thin yellow marker dashes (above/below blue)
    if y_zone is not None and zone_column_height(yellow, y_zone) < 10:
        y_zone = None
    if b_zone is not None and zone_column_height(blue, b_zone) < 8:
        b_zone = None

    is_yellow = False
    zone = None
    if y_zone is not None and zone_fill_score(yellow, y_zone) >= 0.45:
        if b_zone is None or zone_fill_score(yellow, y_zone) >= zone_fill_score(blue, b_zone) * 0.75:
            is_yellow = True
            zone = y_zone
    if zone is None:
        zone = b_zone

    white_x = find_white_x(rgb, white_min)
    bar_visible = zone is not None and (
        white_x is not None or int(blue.sum()) + int(yellow.sum()) > 40
    )
    return bar_visible, bool(is_yellow and zone is not None), white_x, zone


def detect_bar_fast(bgra: np.ndarray) -> tuple[bool, bool, int | None, tuple[int, int] | None]:
    """Detect fishing minigame: white tick + blue OR rare yellow target block."""
    h, w = bgra.shape[:2]
    b = bgra[:, :, 0].astype(np.int16)
    g = bgra[:, :, 1].astype(np.int16)
    r = bgra[:, :, 2].astype(np.int16)

    dark = (r + g + b) < 300
    if int(dark.sum()) < max(10, (h * w) // 16):
        return False, False, None, None

    # Full width — blue target is often on the RIGHT; never crop it to 75%.
    cyan = (
        (b > 90)
        & (b < 240)
        & (g > 50)
        & (g < 210)
        & (r < 130)
        & (b > r + 20)
        & (b >= g - 8)
        & (g > r + 8)
    )
    # Rare yellow = solid block like blue. Thin dashes / mouse frame excluded later.
    yel = (
        (r > 130)
        & (g > 100)
        & (b < 140)
        & (r >= g - 25)
        & (r > b + 25)
        & (g > b + 15)
        & ((r.astype(np.int32) + g) > 240)
        & (r + g > 2 * b + 40)
    )

    # Low min_col vs full ROI height (padding is black); validate solid height after.
    b_zone = find_zone(cyan, 0.60, min_col=max(3, h // 40), min_width=12)
    y_zone = find_zone(yel, 0.60, min_col=max(3, h // 40), min_width=12)

    if b_zone is not None and zone_column_height(cyan, b_zone) < 8:
        b_zone = None
    # Real rare block is tall like blue (~track height). Dashes are 1–4px.
    if y_zone is not None and zone_column_height(yel, y_zone) < 10:
        y_zone = None
    # Mouse / UI yellow on far right is not the hit zone
    if y_zone is not None and y_zone[0] > int(w * 0.82):
        y_zone = None

    is_yellow = False
    zone = None
    if y_zone is not None:
        y_score = zone_fill_score(yel, y_zone)
        b_score = zone_fill_score(cyan, b_zone) if b_zone is not None else 0.0
        yw = y_zone[1] - y_zone[0]
        if y_score >= 0.45 and yw >= 12 and (b_zone is None or y_score >= b_score * 0.70):
            is_yellow = True
            zone = y_zone
        else:
            zone = b_zone
    elif b_zone is not None:
        zone = b_zone

    if zone is not None:
        zw = zone[1] - zone[0]
        if zw < 10 or zw > max(80, int(w * 0.60)):
            zone = None
            is_yellow = False

    # White tick across almost full bar (leave a sliver for mouse chrome)
    tick_w = max(8, int(w * 0.95))
    rt, gt, bt = r[:, :tick_w], g[:, :tick_w], b[:, :tick_w]
    lum_t = (rt + gt + bt) // 3
    near_w = (np.abs(rt - gt) <= 30) & (np.abs(gt - bt) <= 30)
    left = np.pad(lum_t, ((0, 0), (2, 0)), mode="edge")[:, :-2]
    right = np.pad(lum_t, ((0, 0), (0, 2)), mode="edge")[:, 2:]
    peak = (lum_t >= left + 28) & (lum_t >= right + 28) & (lum_t >= 140) & near_w
    soft = (lum_t >= 165) & near_w
    score = peak.sum(axis=0).astype(np.float64) * 4.0 + soft.sum(axis=0).astype(np.float64)
    white_x = None
    if float(score.max()) >= 1.5:
        x = int(np.argmax(score))
        left_s = float(score[x - 6]) if x >= 6 else 0.0
        right_s = float(score[x + 6]) if x + 6 < tick_w else 0.0
        if score[x] >= max(left_s, right_s, 1.0) * 1.05:
            white_x = x

    visible = zone is not None
    return visible, bool(is_yellow and zone is not None), white_x, zone


def should_hit(
    white_x: int | None,
    zone: tuple[int, int] | None,
    prev_x: int | None,
    pad: int,
    predict_frames: int,
) -> bool:
    """True if tick is on the block now, or will reach it (for early 30ms arm)."""
    if white_x is None or zone is None:
        return False
    x0, x1 = zone
    lo, hi = x0 - pad, x1 + pad - 1
    if lo <= white_x <= hi:
        return True
    if prev_x is None or predict_frames <= 0:
        return False
    vx = white_x - prev_x
    if vx == 0:
        return False
    mid = 0.5 * (x0 + x1)
    # Arm early only when moving toward the block
    steps = max(1, min(int(predict_frames), 6))
    for step in range(1, steps + 1):
        px = white_x + vx * step
        if lo <= px <= hi and abs(px - mid) <= abs(white_x - mid) + abs(vx):
            return True
    return False


def bright_stick_in_zone(bgra: np.ndarray, zone: tuple[int, int] | None) -> bool:
    """Fallback: white tick visible as bright neutral pixels inside the block."""
    if zone is None or bgra is None or bgra.size == 0:
        return False
    h, w = bgra.shape[:2]
    y0, y1 = max(0, h // 8), min(h, (7 * h) // 8)
    strip = bgra[y0:y1]
    x0, x1 = max(0, zone[0]), min(strip.shape[1], zone[1])
    if x1 - x0 < 4:
        return False
    b = strip[:, x0:x1, 0].astype(np.int16)
    g = strip[:, x0:x1, 1].astype(np.int16)
    r = strip[:, x0:x1, 2].astype(np.int16)
    lum = (r + g + b) // 3
    near = (np.abs(r - g) <= 40) & (np.abs(g - b) <= 40)
    bright = (lum >= 150) & near
    return int(bright.sum(axis=0).max()) >= max(1, strip.shape[0] // 25)


def annotate_bar(rgb: np.ndarray, white_x: int | None, zone: tuple[int, int] | None, hit: bool) -> Image.Image:
    arr = np.array(rgb, copy=True)
    h, w, _ = arr.shape
    if zone is not None:
        x0, x1 = zone
        x0 = max(0, min(w - 1, x0))
        x1 = max(0, min(w, x1))
        color = (0, 255, 80) if hit else (255, 220, 40)
        arr[0:2, x0:x1] = color
        arr[h - 2 : h, x0:x1] = color
    if white_x is not None and 0 <= white_x < w:
        arr[:, max(0, white_x) : min(w, white_x + 1)] = (255, 80, 80)
    return Image.fromarray(arr)


def thumb_bar(rgb: np.ndarray, white_x: int | None, zone: tuple[int, int] | None, hit: bool) -> Image.Image:
    """Preview for UI."""
    img = annotate_bar(rgb, white_x, zone, hit)
    img.thumbnail((360, 90), Image.Resampling.BILINEAR)
    return img


def thumb_sub(rgb: np.ndarray) -> Image.Image:
    img = Image.fromarray(rgb)
    img.thumbnail((360, 160), Image.Resampling.BILINEAR)
    return img
