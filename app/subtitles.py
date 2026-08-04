from __future__ import annotations

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

def normalize_ocr(text: str) -> str:
    t = text.lower()
    # Cyrillic lookalikes OCR sometimes mixes in
    for a, b in (
        ("о", "o"),
        ("а", "a"),
        ("е", "e"),
        ("р", "p"),
        ("с", "c"),
        ("у", "y"),
        ("х", "x"),
        ("в", "b"),
        ("к", "k"),
        ("м", "m"),
        ("н", "h"),
        ("т", "t"),
        ("і", "i"),
        ("ї", "i"),
        ("ё", "e"),
    ):
        t = t.replace(a, b)
    for ch in ".,!?:;\"'`“”«»()[]{}|/_\\-+=~*<>0123456789":
        t = t.replace(ch, " ")
    # whole-token fixes only (substring replace turns "splashing" → "splashingg")
    fix = {
        "throwr": "thrown",
        "throun": "thrown",
        "retrievec": "retrieved",
        "sptashins": "splashes",
        "splashins": "splashes",
        "sptashes": "splashes",
        "spiashes": "splashes",
        "spiashe": "splashes",
        "splashe": "splashes",
        "splashess": "splashes",
        "sptashing": "splashing",
        "sptashin": "splashing",
        "splashin": "splashing",
        "sptash": "splash",
        "splah": "splash",
        "tishing": "fishing",
        "fshing": "fishing",
        "flshing": "fishing",
        "fisning": "fishing",
        "fisbing": "fishing",
        "fishng": "fishing",
        "fishin": "fishing",
        "bobbet": "bobber",
        "bober": "bobber",
        "bobbcr": "bobber",
        "bobher": "bobber",
        "bobbr": "bobber",
        "bobbe": "bobber",
        "bohber": "bobber",
    }
    return " ".join(fix.get(tok, tok) for tok in t.split())


def is_ignore_subtitle(n: str) -> bool:
    return any(s in n for s in IGNORE_SUB_SNIPPETS)


def sanitize_sub(ocr_text: str) -> str:
    """Remove cast/retrieve noise so Splashing in the same OCR blob still counts."""
    n = normalize_ocr(ocr_text)
    if not n:
        return ""
    for junk in (
        "bobber thrown",
        "bobber retrieved",
        "bobber throwr",
        "bobber retrievec",
        "bobber throun",
        "thrown",
        "retrieved",
        "retrievec",
        "throwr",
        "throun",
    ):
        n = n.replace(junk, " ")
    return " ".join(n.split())


def _edit_dist1(a: str, b: str) -> bool:
    """True if equal or one OCR edit apart."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    if la + 1 == lb:
        i = j = 0
        skip = 0
        while i < la and j < lb:
            if a[i] == b[j]:
                i += 1
                j += 1
            else:
                skip += 1
                if skip > 1:
                    return False
                j += 1
        return True
    return sum(x != y for x, y in zip(a, b)) <= 1


def _token_close(tokens: list[str], target: str) -> bool:
    if target in tokens:
        return True
    for t in tokens:
        if abs(len(t) - len(target)) <= 2 and _edit_dist1(t, target):
            return True
        if target in t and len(t) <= len(target) + 8:
            return True
    return False


def has_splash_word(ocr_text: str) -> bool:
    """Ambient water subtitle (Splashing). Present while bobber is in water."""
    n = sanitize_sub(ocr_text)
    if not n:
        return False
    tokens = n.split()
    compact = n.replace(" ", "")
    return (
        "splashes" in n
        or "splashing" in n
        or "splash" in tokens
        or "splash" in compact
        or any(t.startswith("splas") for t in tokens)
        or _token_close(tokens, "splashes")
        or _token_close(tokens, "splashing")
    )


def bite_matched(ocr_text: str, lang: str = "en") -> bool:
    """
    Bite = Fishing Bobber splashes (EN). Case-insensitive + OCR-tolerant.
    Ambient 'Splashing' alone is NOT a bite.
    """
    n = sanitize_sub(ocr_text)
    if not n:
        return False
    compact = n.replace(" ", "")
    tokens = n.split()

    if BITE_EXACT in n or "fishingbobbersplashes" in compact:
        return True
    if "fishingbobber" in compact and "splash" in compact:
        return True
    if "fishingbobbersplash" in compact:
        return True

    has_fish = "fishing" in n or _token_close(tokens, "fishing")
    has_bob = "bobber" in n or _token_close(tokens, "bobber")
    has_splash = (
        "splashes" in n
        or ("splash" in tokens)
        or any(t.startswith("splas") and t != "splashing" for t in tokens)
        or _token_close(tokens, "splashes")
        or ("splash" in compact and "splashing" not in compact)
    )

    if has_fish and has_bob:
        return True
    if has_bob and has_splash:
        return True
    if has_fish and has_splash:
        return True
    return False
