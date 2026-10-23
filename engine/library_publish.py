#!/usr/bin/env python3
"""Publish the shareable part of the picture library into this repository (library/).

    ~/.local/share/iwe-imagegen/venv/bin/python library_publish.py [--looks bright,strict,...] [--size 512]
    ... library_publish.py --looks LOCAL --as corp-orange      a local look published under a built-in name
    ... library_publish.py --skip unreviewed.txt               leave out pictures not reviewed yet

Only the built-in looks are published. A local look goes out only under a built-in name (--as), and
only when its owner agreed; the mapping stays with the owner, not in this file. Page titles in the
source field are cut to the date. Rejected pictures are never in the catalog, so they are never copied. Each
picture becomes a WebP of at most --size px (about 30 KB instead of 300 KB of PNG); pictures
already published are kept as they are, so running it after every night adds only the new ones.
Needs Pillow (the image-generation environment).
see docs/service-clause.md
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I leaves the script folder out
import library  # noqa: E402

BUILTIN_LOOKS = ["strict", "bright", "editorial", "blueprint", "night", "watercolor", "sketch", "pop", "steampunk",
                 "fantasy", "corp-orange", "corp-green"]
NIGHT_SOURCE = "ночная генерация"
REPO_LIBRARY = Path(__file__).resolve().parent.parent / "library"


def public_source(source: str) -> str:
    """A picture drawn for a page keeps only the date: page titles are the owner's work, not the library's."""
    if source.startswith(NIGHT_SOURCE):
        return source
    date = re.search(r"\d{2}\.\d{2}(\.\d{4})?", source)
    return "страница" + (f", {date.group(0)}" if date else "")


def publish(source: Path, dest: Path, looks: list[str], size: int = 512, quality: int = 82,
            alias: str = "", skip: frozenset[str] = frozenset()) -> tuple[int, int]:
    """Copy catalog rows of the given looks as WebP into dest; returns (added, kept).

    A picture already published is replaced when its library file is newer (re-cut, redrawn).

    alias publishes one local look under a built-in name (its folder and look field are renamed);
    skip lists library files (look/name.png) that must stay local, e.g. pictures not reviewed yet."""
    if alias and len(looks) != 1:
        raise SystemExit("--as - для одного облика за раз")
    unknown = [look for look in ([alias] if alias else looks) if look not in BUILTIN_LOOKS]
    if unknown:
        raise SystemExit(f"в открытое хранилище - только встроенные облики, не: {', '.join(unknown)}")
    from PIL import Image  # only the image-generation environment has Pillow

    rows = [r for r in library.read_catalog(source) if r["look"] in looks and r["file"] not in skip]
    published = {r["file"]: r for r in library.read_catalog(dest)}
    added = kept = 0
    for r in rows:
        look = alias or r["look"]
        rel = look + "/" + r["file"].split("/", 1)[1].rsplit(".", 1)[0] + ".webp"
        out = dest / rel
        src = source / r["file"]
        if not src.exists():
            continue
        if rel in published and out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            kept += 1
            continue
        img = Image.open(src).convert("RGBA")
        img.thumbnail((size, size))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "WEBP", quality=quality, method=6)
        published[rel] = {**r, "file": rel, "look": look, "source": public_source(r["source"]),
                          "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
        added += 1
    library.write_catalog(dest, sorted(published.values(), key=lambda x: x["file"]))
    library.sheet(dest)
    return added, kept


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--looks", default=",".join(BUILTIN_LOOKS))
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--to", type=Path, default=REPO_LIBRARY)
    ap.add_argument("--as", dest="alias", default="", help="built-in name to publish one local look under")
    ap.add_argument("--skip", type=Path, help="file with library paths (look/name.png) to leave out")
    args = ap.parse_args()
    skip = frozenset(args.skip.read_text(encoding="utf-8").split()) if args.skip else frozenset()
    added, kept = publish(library.library_root(), args.to, [x for x in args.looks.split(",") if x], args.size,
                          alias=args.alias, skip=skip)
    print(f"добавлено {added}, уже было {kept}: {args.to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
