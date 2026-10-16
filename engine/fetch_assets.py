#!/usr/bin/env python3
"""One-off download of the fonts and icons the infographic builder embeds.

Run once (or when the set below changes); the result is committed, so building a
page never needs the network. Fonts are Google Fonts (SIL OFL), only the
cyrillic, latin and latin-ext subsets; icons are Lucide (ISC).
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "assets" / "fonts"
ICON_DIR = HERE / "assets" / "icons"

# A modern UA makes Google Fonts answer with woff2 and unicode-range subsets.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
FONTS = {
    "Onest": "wght@400..800",
    "JetBrains Mono": "wght@400..700",
    "Inter": "wght@400..800",
    "Nunito": "wght@400..800",
    "Caveat": "wght@500..700",
    "Playfair Display": "wght@600..900",
    "Unbounded": "wght@500..800",
    "Old Standard TT": "wght@400;700",
    "PT Serif": "wght@400;700",
    "Ruslan Display": "",
    "Alegreya": "wght@400..800",
    "Neucha": "",
    "Pangolin": "",
}
SUBSETS = ("cyrillic", "latin", "latin-ext")  # latin-ext carries the rouble sign U+20BD
LUCIDE = "https://unpkg.com/lucide-static@0.460.0/icons/{}.svg"
LUCIDE_LICENSE = "https://unpkg.com/lucide-static@0.460.0/LICENSE"
# Every family above is under the SIL Open Font License, kept in the google/fonts repository.
OFL = "https://raw.githubusercontent.com/google/fonts/main/ofl/{}/OFL.txt"
ICONS = [
    "server", "database", "hard-drive", "cpu", "memory-stick", "key-round", "usb",
    "shield-check", "lock", "cloud", "coins", "banknote", "clock", "calendar",
    "triangle-alert", "circle-check", "circle-x", "circle-help", "lightbulb", "target",
    "users", "user", "file-text", "refresh-cw", "arrow-right", "arrow-down", "layers",
    "network", "box", "settings", "wrench", "factory", "trending-up", "trending-down",
    "chart-column", "list-checks", "zap", "archive", "monitor", "git-branch", "workflow",
    "flame", "scale", "rocket", "flag", "puzzle", "sparkles", "hourglass",
    "cog", "compass", "scroll", "castle", "crown", "gem", "map", "swords",
]


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_fonts() -> None:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    out_css = []
    for family, axis in FONTS.items():
        query = family.replace(" ", "+") + (":" + axis if axis else "")
        css = get(f"https://fonts.googleapis.com/css2?family={query}&display=swap").decode()
        # Each block is preceded by a "/* subset */" comment.
        for subset, block in re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{.*?\})", css, re.S):
            if subset not in SUBSETS:
                continue
            url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
            # Static families come as one block per weight, so the weight is part of the name.
            weight = re.search(r"font-weight:\s*([\d ]+);", block).group(1).strip().replace(" ", "-")
            name = f"{family.lower().replace(' ', '-')}-{subset}-{weight}.woff2"
            (FONT_DIR / name).write_bytes(get(url))
            out_css.append(block.replace(url, name))
            print(f"font  {name}")
    (FONT_DIR / "fonts.css").write_text("\n".join(out_css) + "\n", encoding="utf-8")


def fetch_icons() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    missing = []
    for name in ICONS:
        try:
            svg = get(LUCIDE.format(name)).decode()
        except Exception as exc:  # report and keep going: the list is curated by hand
            print(f"icon  {name}: {exc}", file=sys.stderr)
            missing.append(name)
            continue
        svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S).strip()
        (ICON_DIR / f"{name}.svg").write_text(svg + "\n", encoding="utf-8")
    print(f"icons {len(ICONS) - len(missing)} saved, missing: {missing or 'none'}")
    if missing:
        sys.exit(1)


def fetch_licenses() -> None:
    """The OFL and ISC notices must travel with the font and icon files."""
    texts = []
    for family in FONTS:
        text = get(OFL.format(family.lower().replace(" ", ""))).decode()
        texts.append(f"===== {family} =====\n\n{text.strip()}\n")
    (FONT_DIR / "OFL.txt").write_text("\n\n".join(texts), encoding="utf-8")
    (ICON_DIR / "LICENSE.txt").write_bytes(get(LUCIDE_LICENSE))
    print(f"licenses: {len(texts)} font families, Lucide icons")


if __name__ == "__main__":
    fetch_fonts()
    fetch_icons()
    fetch_licenses()
