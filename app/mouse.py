from __future__ import annotations

import time

try:
    import ctypes
except ImportError:
    ctypes = None  # type: ignore

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
INPUT_MOUSE = 0


class _MOUSEINPUT(ctypes.Structure if ctypes else object):
    if ctypes:
        _fields_ = (
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        )


class _INPUT(ctypes.Structure if ctypes else object):
    if ctypes:

        class _U(ctypes.Union):
            _fields_ = (("mi", _MOUSEINPUT),)

        _anonymous_ = ("u",)
        _fields_ = (("type", ctypes.c_ulong), ("u", _U))

# English bite subtitle (Minecraft). Ignore ambient water "Splashing".
BITE_EXACT = "fishing bobber splashes"
IGNORE_SUB_SNIPPETS = [
    "bobber thrown",
    "bobber retrieved",
    "bobber throwr",
    "bobber retrievec",
    "bobber throun",
    "thrown",
    "retrieved",
    "retrievec",
    "throwr",
]


def click(button: str = "right", *, fast: bool = False) -> None:
    """Mouse click. Always keep a short down→up gap so Minecraft registers it."""
    flags_down = MOUSEEVENTF_RIGHTDOWN if button == "right" else MOUSEEVENTF_LEFTDOWN
    flags_up = MOUSEEVENTF_RIGHTUP if button == "right" else MOUSEEVENTF_LEFTUP
    # Frozen exe + Minecraft needs a slightly longer hold than raw Python sometimes
    hold = 0.028 if fast else 0.055
    sent = False
    try:
        import win32api

        win32api.mouse_event(flags_down, 0, 0, 0, 0)
        time.sleep(hold)
        win32api.mouse_event(flags_up, 0, 0, 0, 0)
        sent = True
    except Exception:
        pass
    if sent:
        return
    if ctypes is None:
        return
    extra = ctypes.c_ulong(0)
    for i, fl in enumerate((flags_down, flags_up)):
        inp = _INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = _MOUSEINPUT(0, 0, 0, fl, 0, ctypes.pointer(extra))
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if i == 0:
            time.sleep(hold)


def splash_reel_rmb() -> None:
    """Single RMB on bite — no double click."""
    click("right", fast=True)
