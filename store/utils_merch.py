from __future__ import annotations

import re
from django.utils.text import slugify


def normalize_merch_category(label: str) -> tuple[str, str]:
    """
    Normalize a raw merch category label into (slug_key, display_label).
    """
    clean = " ".join(str(label or "").strip().split())[:80]
    if not clean:
        return "", ""

    low = clean.lower()
    # Common, high-signal groupings (ordered).
    rules: list[tuple[tuple[str, ...], str]] = [
        (("hoodie", "sweatshirt", "crewneck"), "Hoodies"),
        (("sticker", "decal"), "Stickers"),
        (("hat", "cap", "snapback", "trucker"), "Hats"),
        (("beanie",), "Beanies"),
        (("mug", "cup"), "Mugs"),
        (("shirt", "tee", "t-shirt", "tshirt"), "Tees"),
        (("tank",), "Tanks"),
        (("poster", "print"), "Posters"),
        (("bag", "tote", "backpack"), "Bags"),
        (("case",), "Cases"),
        (("sock",), "Socks"),
    ]
    for needles, normalized in rules:
        if any(needle in low for needle in needles):
            key = slugify(normalized)[:64]
            return key or (slugify(clean)[:64] or "merch"), normalized

    # Fallback: pick a meaningful word from the label.
    stopwords = {
        "unisex",
        "men",
        "mens",
        "women",
        "womens",
        "kids",
        "youth",
        "adult",
        "basic",
        "classic",
        "premium",
        "and",
        "the",
        "for",
        "with",
        "of",
    }
    words = [w for w in re.split(r"[^a-z0-9]+", low) if w]
    chosen = ""
    for word in words:
        if word in stopwords:
            continue
        if len(word) < 3:
            continue
        chosen = word
        break
    if not chosen and words:
        chosen = words[0]

    if not chosen:
        key = slugify(clean)[:64] or "merch"
        return key, clean

    normalized_label = chosen.upper() if chosen in {"pf"} else chosen.title()
    # Light pluralization so categories feel natural.
    if not normalized_label.endswith("s") and normalized_label.lower() not in {"merch"}:
        normalized_label = f"{normalized_label}s"
    key = slugify(normalized_label)[:64] or (slugify(clean)[:64] or "merch")
    return key, normalized_label
