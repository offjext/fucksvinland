from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

import mss
import numpy as np

from .bar import (
    bgr_to_rgb,
    bright_stick_in_zone,
    detect_bar,
    detect_bar_fast,
    should_hit,
    thumb_bar,
    thumb_bar_fast,
    thumb_sub,
)
from .frames import FrameBus
from .mouse import click, splash_reel_rmb
from .ocr import AsyncOcr, OcrEngine
from .paths import ROOT
from .roi import resolve_roi
from .subtitles import bite_matched, has_splash_word, sanitize_sub


@dataclass
class WorkerHooks:
    on_status: Callable[[str], None]
    on_log: Callable[[str], None]
    frames: FrameBus
    should_stop: Callable[[], bool]
    set_preview_paused: Callable[[bool], None] | None = None


class PreviewWorker(threading.Thread):
    """Light preview. Pauses during minigame so bar loop gets max FPS."""

    def __init__(
        self,
        get_cfg: Callable[[], dict],
        frames: FrameBus,
        alive: Callable[[], bool],
        is_paused: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.get_cfg = get_cfg
        self.frames = frames
        self.alive = alive
        self.is_paused = is_paused or (lambda: False)

    def run(self) -> None:
        target = 1.0 / 8.0
        fps_ema = 8.0
        with mss.mss() as sct:
            while self.alive():
                if self.is_paused():
                    time.sleep(0.05)
                    continue
                t0 = time.perf_counter()
                bar_img = sub_img = None
                cfg = self.get_cfg()
                bar_roi = cfg.get("bar_roi", {})
                sub_roi = cfg.get("subtitle_roi", {})
                if all(k in bar_roi for k in ("left", "top", "width", "height")):
                    try:
                        box = resolve_roi(sct.monitors[0], bar_roi)
                        raw = np.asarray(sct.grab(box))
                        bar_rgb = bgr_to_rgb(raw)
                        try:
                            vis, _, wx, zone = detect_bar(bar_rgb, cfg.get("colors", {}))
                            hit = bool(vis and should_hit(wx, zone, None, 4, 0))
                        except Exception:
                            wx, zone, hit = None, None, False
                        bar_img = thumb_bar(bar_rgb, wx, zone, hit)
                    except Exception:
                        bar_img = None
                if all(k in sub_roi for k in ("left", "top", "width", "height")):
                    try:
                        box = resolve_roi(sct.monitors[0], sub_roi)
                        raw = np.asarray(sct.grab(box))
                        sub_img = thumb_sub(bgr_to_rgb(raw))
                    except Exception:
                        sub_img = None
                dt = max(1e-6, time.perf_counter() - t0)
                # Show capture rate, not inverse of one frame (was ~168 and useless)
                fps_ema = fps_ema * 0.85 + min(60.0, 1.0 / dt) * 0.15
                if bar_img is not None or sub_img is not None:
                    self.frames.push(bar_img, sub_img, fps_ema)
                sleep = target - (time.perf_counter() - t0)
                if sleep > 0:
                    time.sleep(sleep)


class FishWorker(threading.Thread):
    def __init__(self, cfg: dict, lang: str, hooks: WorkerHooks) -> None:
        super().__init__(daemon=True)
        self.cfg = cfg
        self.lang = lang
        self.hooks = hooks
        self.ocr = OcrEngine()

    def log(self, msg: str) -> None:
        self.hooks.on_log(msg)

    def status(self, msg: str) -> None:
        self.hooks.on_status(msg)

    def run(self) -> None:
        cfg = self.cfg
        t = cfg["timing"]
        fps = 60
        target = 1.0 / fps
        pad = int(t.get("hit_pad_px", 8))
        predict = int(t.get("predict_frames", 4))
        # 0 / missing wait_bite = wait forever for Fishing Bobber splashes
        ocr_every = max(0.04, int(t.get("ocr_ms", 50)) / 1000.0)
        grace_ms = int(t.get("cast_grace_ms", 800))
        # Minecraft keeps sound subtitles on screen a long time — must stay CLEAR
        # this long before a new "Fishing Bobber" can count as a bite.
        # Longer = fewer false bites from OCR flicker on stale text.
        subtitle_clear_ms = int(t.get("subtitle_clear_ms", 900))
        # after cast: must see ambient Splashing within this window, else autofix
        ambient_fail_ms = int(t.get("ambient_fail_ms", t.get("no_splash_recast_ms", 1500)))
        # optional: 0=off. If >0 and ambient was OK then silent this long → autofix
        ambient_gone_ms = int(t.get("ambient_gone_ms", 0))
        recast_pause = max(0.45, int(t.get("recast_delay_ms", 450)) / 1000.0)
        click_cd = max(5, int(t.get("click_cooldown_ms", 90)))
        mon_i = int(cfg.get("monitor", 1))
        mini_btn = str((cfg.get("mouse") or {}).get("minigame_button", "right")).lower()
        if mini_btn not in ("left", "right"):
            mini_btn = "right"

        if not self.ocr.ensure():
            self.log(f"OCR fail: {self.ocr.error}")
            self.status("OCR error")
            return

        async_ocr = AsyncOcr("en", self.ocr)
        async_ocr.start()
        self.log("старт")

        last_click = 0.0
        last_ocr_submit = 0.0
        cast_at = 0.0
        mini_at = 0.0
        pull_at = 0.0
        ignore_bite_until = 0.0
        bar_missing_since = 0.0
        state = "wait"
        line_out = False
        rare = False
        prev_x: int | None = None
        last_log_sub = ""
        was_in_zone = False
        splash_armed = False
        no_bite_since = 0.0  # when bite text last disappeared
        ambient_ok = False  # saw Splashing after cast → line in water
        ambient_lost_at = 0.0
        touch_at = 0.0  # when stick first touched blue/yellow
        pending_hit = False
        last_zone: tuple[int, int] | None = None
        last_zone_t = 0.0
        last_yellow = False
        stall_fixes = 0
        bar_gone_s = max(0.45, float(t.get("bar_gone_ms", 500)) / 1000.0)
        pull_wait_s = max(1.2, float(t.get("bar_wait_ms", 2500)) / 1000.0)
        cast_gap = max(0.5, recast_pause)
        # see real touch on blue/yellow → wait 20ms → 1× RMB per pass
        hit_cooldown = max(0.05, click_cd / 1000.0)
        touch_delay = max(0.0, float(t.get("touch_delay_ms", 20)) / 1000.0)
        rare_pad = max(pad, int(t.get("rare_hit_pad_px", pad)))
        fps_ema = 60.0
        ui_n = 0

        def rmb() -> None:
            click("right", fast=False)

        def rmb_fast() -> None:
            click("right", fast=True)

        def mini_click() -> None:
            click(mini_btn, fast=True)

        def _valid_roi(roi: dict) -> bool:
            return all(k in roi for k in ("left", "top", "width", "height")) and int(
                roi.get("width", 0)
            ) >= 40 and int(roi.get("height", 0)) >= 16

        def full_crops(mon: dict) -> tuple[dict, dict]:
            """Prefer saved bar ROI (wide auto crop false-triggers on water/sky)."""
            w, h = int(mon["width"]), int(mon["height"])
            bar = {
                "left": int(mon["left"]) + int(w * 0.28),
                "top": int(mon["top"]) + int(h * 0.01),
                "width": max(120, int(w * 0.44)),
                "height": max(48, int(h * 0.08)),
            }
            sub = {
                "left": int(mon["left"]) + int(w * 0.72),
                "top": int(mon["top"]) + int(h * 0.74),
                "width": max(80, int(w * 0.26)),
                "height": max(80, int(h * 0.20)),
            }
            saved_bar = cfg.get("bar_roi") or {}
            saved_sub = cfg.get("subtitle_roi") or {}
            if _valid_roi(saved_bar):
                bar = resolve_roi(mon, saved_bar)
            if _valid_roi(saved_sub):
                sub = resolve_roi(mon, saved_sub)
            return bar, sub

        def reset_bite_edge(reason: str = "") -> None:
            """Disarm bite; treat any current Fishing Bobber as stale."""
            nonlocal splash_armed, no_bite_since
            splash_armed = False
            no_bite_since = 0.0
            async_ocr.soft_reset()
            if reason:
                self.log(f"bite edge reset: {reason}")

        def cast_once(reason: str) -> None:
            nonlocal cast_at, state, rare, prev_x, ignore_bite_until, line_out
            nonlocal bar_missing_since, was_in_zone, last_zone, last_zone_t, last_yellow
            nonlocal touch_at, pending_hit, splash_armed, ambient_ok, ambient_lost_at
            nonlocal no_bite_since
            if line_out:
                self.log(f"skip cast (line out): {reason}")
                state = "wait"
                return
            self.log(f"заброс: {reason}")
            self.status("заброс")
            # soft_reset: do NOT wipe OCR to "" — that makes old subtitle look "new"
            async_ocr.soft_reset()
            rmb()
            time.sleep(cast_gap)
            line_out = True
            cast_at = time.perf_counter()
            ignore_bite_until = cast_at + grace_ms / 1000.0
            state = "wait"
            rare = False
            prev_x = None
            was_in_zone = False
            touch_at = 0.0
            pending_hit = False
            splash_armed = False
            no_bite_since = 0.0
            ambient_ok = False
            ambient_lost_at = 0.0
            last_zone = None
            last_zone_t = 0.0
            last_yellow = False
            bar_missing_since = 0.0
            self.status("ожидание…")

        def reel_once(reason: str) -> None:
            nonlocal line_out
            if not line_out:
                return
            self.log(f"REEL: {reason}")
            async_ocr.soft_reset()
            rmb()
            time.sleep(cast_gap)
            line_out = False

        def autofix(reason: str) -> None:
            """Cast failed / no water splash / stuck state → reel if needed, recast."""
            nonlocal line_out, stall_fixes, ambient_ok, ambient_lost_at, splash_armed
            nonlocal no_bite_since
            stall_fixes += 1
            self.log(f"фикс #{stall_fixes}: {reason}")
            self.status("фикс")
            async_ocr.soft_reset()
            if line_out:
                rmb()
                time.sleep(cast_gap)
                line_out = False
            ambient_ok = False
            ambient_lost_at = 0.0
            splash_armed = False
            no_bite_since = 0.0
            time.sleep(0.12)
            cast_once(f"autofix/{reason}")

        try:
            with mss.mss() as sct:
                mon_i = min(max(mon_i, 1), len(sct.monitors) - 1)
                mon = sct.monitors[mon_i]
                bar_box, sub_box = full_crops(mon)
                self.log(f"monitor={mon_i} full={mon['width']}x{mon['height']}")
                self.log(f"bar={bar_box}")
                self.log(f"sub={sub_box}")

                if self.hooks.set_preview_paused:
                    self.hooks.set_preview_paused(True)

                cast_once("start")

                while not self.hooks.should_stop():
                    frame_t0 = time.perf_counter()
                    now = frame_t0

                    try:
                        bar_raw = np.asarray(sct.grab(bar_box))
                    except Exception as e:
                        self.log(f"grab err: {e}")
                        time.sleep(0.02)
                        continue

                    # 60fps bar — hit only when stick is on the block
                    visible, is_yellow, white_x, zone = detect_bar_fast(bar_raw)
                    # keep last zone briefly while blue→yellow transition flickers
                    if zone is not None:
                        last_zone = zone
                        last_zone_t = now
                        last_yellow = bool(is_yellow)
                    elif state == "mini" and last_zone is not None and (now - last_zone_t) < 0.45:
                        zone = last_zone
                        is_yellow = last_yellow or rare
                        visible = True

                    use_pad = rare_pad if (rare or is_yellow) else pad
                    # During mini: only REAL overlap (predict burned the one-click budget early)
                    if state == "mini":
                        in_zone = should_hit(white_x, zone, prev_x, use_pad, 0)
                        if not in_zone and zone is not None:
                            in_zone = bright_stick_in_zone(bar_raw, zone)
                    else:
                        use_predict = max(1, predict)
                        in_zone = should_hit(white_x, zone, prev_x, use_pad, use_predict)

                    # OCR as often as possible while waiting for splash
                    if state == "wait" and (now - last_ocr_submit) >= ocr_every:
                        last_ocr_submit = now
                        try:
                            sub_raw = np.asarray(sct.grab(sub_box))
                            async_ocr.submit(bgr_to_rgb(sub_raw))
                        except Exception:
                            pass

                    bite, text = async_ocr.consume_bite()
                    # Never trust AsyncOcr edge alone — OCR flicker on stale
                    # "Fishing Bobber" looks like a new bite. Main loop uses clear→appear.
                    bite = False
                    # less OCR spam in log
                    if state == "wait" and text and text != last_log_sub:
                        last_log_sub = text

                    if state == "wait" and line_out:
                        peek = text or async_ocr.peek_text()
                        # Ambient cast confirm: water Splashing, not stale Fishing Bobber bite
                        bite_now = bite_matched(peek)
                        ambient = has_splash_word(peek) and not bite_now

                        if ambient and not ambient_ok:
                            ambient_ok = True
                            ambient_lost_at = 0.0
                            self.log("ок — ждём клёв")
                        elif ambient_ok and ambient_gone_ms > 0:
                            if ambient or bite_now:
                                ambient_lost_at = 0.0
                            elif ambient_lost_at <= 0:
                                ambient_lost_at = now

                        # Stale Minecraft subtitles linger — arm only after CLEAR for N ms
                        if now < ignore_bite_until:
                            async_ocr.resync()
                            bite = False
                            splash_armed = False
                            no_bite_since = 0.0 if bite_now else (no_bite_since or now)
                        elif bite_now:
                            no_bite_since = 0.0
                            if splash_armed:
                                bite = True
                                splash_armed = False
                                self.log("клёв")
                        else:
                            if no_bite_since <= 0:
                                no_bite_since = now
                            elif (now - no_bite_since) * 1000.0 >= subtitle_clear_ms:
                                if not splash_armed:
                                    splash_armed = True
                                    async_ocr.resync()

                    if bite and (now < ignore_bite_until or not line_out):
                        bite = False

                    if state == "wait":
                        if bite and line_out:
                            self.log("клёв → RMB")
                            self.status("клёв")
                            reset_bite_edge("after reel")
                            splash_reel_rmb()
                            line_out = False
                            state = "pull"
                            pull_at = time.perf_counter()
                            ignore_bite_until = pull_at + 1.0
                            prev_x = None
                            was_in_zone = False
                            splash_armed = False
                            no_bite_since = 0.0
                            ambient_ok = False
                            ambient_lost_at = 0.0
                            bar_missing_since = 0.0
                        elif line_out and not ambient_ok and (now - cast_at) * 1000.0 >= ambient_fail_ms:
                            if bite_matched(text or async_ocr.peek_text()) and not splash_armed:
                                self.status("старый субтитр…")
                            else:
                                autofix("нет splash после заброса")
                        elif (
                            ambient_gone_ms > 0
                            and line_out
                            and ambient_ok
                            and ambient_lost_at > 0
                            and (now - ambient_lost_at) * 1000.0 >= ambient_gone_ms
                        ):
                            autofix("splash пропал")
                        elif line_out:
                            if bite_matched(text or async_ocr.peek_text()) and not splash_armed:
                                self.status("старый субтитр…")
                            elif not ambient_ok:
                                self.status("проверка заброса…")
                            elif splash_armed:
                                self.status("ожидание клёва")
                            else:
                                self.status("очистка субтитра…")
                        else:
                            autofix("леска не в воде")

                    elif state == "pull":
                        self.status("полоска…")
                        if visible and zone is not None:
                            state = "mini"
                            mini_at = now
                            bar_missing_since = 0.0
                            rare = bool(is_yellow)
                            prev_x = white_x
                            was_in_zone = False
                            touch_at = 0.0
                            pending_hit = False
                            last_click = 0.0
                            self.status("мини")
                        elif (now - pull_at) >= pull_wait_s:
                            autofix("нет полоски")

                    elif state == "mini":
                        # Blue or rare yellow block: 1 RMB per time the tick enters the block
                        if visible and zone is not None:
                            bar_missing_since = 0.0
                            if is_yellow:
                                rare = True
                            do_click = False
                            if in_zone and not was_in_zone:
                                touch_at = now
                                pending_hit = True
                            if not in_zone:
                                pending_hit = False
                                touch_at = 0.0
                            elif (
                                pending_hit
                                and touch_at > 0
                                and (now - touch_at) >= touch_delay
                                and (now - last_click) >= hit_cooldown
                            ):
                                do_click = True
                                pending_hit = False
                            if do_click:
                                mini_click()
                                last_click = now
                                self.status("клик" + (" ★" if rare else ""))
                            elif pending_hit and touch_at > 0:
                                left = max(0.0, touch_delay - (now - touch_at))
                                self.status(f"мини {left*1000:.0f}мс")
                            else:
                                self.status("мини" + (" ·" if in_zone else ""))
                            was_in_zone = in_zone
                        else:
                            was_in_zone = False
                            pending_hit = False
                            touch_at = 0.0
                            if bar_missing_since <= 0:
                                bar_missing_since = now
                            else:
                                limit = bar_gone_s * (2.5 if rare else 1.0)
                                if (now - bar_missing_since) >= limit:
                                    autofix("полоска пропала")
                        if state == "mini" and (now - mini_at) * 1000.0 >= t["minigame_timeout_ms"]:
                            autofix("таймаут мини")

                    if white_x is not None:
                        prev_x = white_x

                    # Preview: cheap/rare during mini so bar loop stays ~60fps
                    ui_n += 1
                    ui_every = 12 if state == "mini" else 6
                    if ui_n >= ui_every:
                        ui_n = 0
                        rgb = bar_raw[:, :, [2, 1, 0]]
                        thumb = (
                            thumb_bar_fast(rgb, white_x, zone, bool(in_zone and visible))
                            if state == "mini"
                            else thumb_bar(rgb, white_x, zone, bool(in_zone and visible))
                        )
                        self.hooks.frames.push(thumb, None, fps_ema)

                    dt = max(1e-6, time.perf_counter() - frame_t0)
                    inst = 1.0 / dt
                    fps_ema = fps_ema * 0.9 + inst * 0.1
                    # Don't sleep in mini if already behind — chase tick
                    if state != "mini":
                        sleep = target - (time.perf_counter() - frame_t0)
                        if sleep > 0:
                            time.sleep(sleep)
                    else:
                        sleep = target - (time.perf_counter() - frame_t0)
                        if sleep > 0.002:
                            time.sleep(sleep)
        finally:
            async_ocr.stop()
            if self.hooks.set_preview_paused:
                self.hooks.set_preview_paused(False)

        self.status("стоп")
        self.log("стоп")

