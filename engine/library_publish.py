#!/usr/bin/env python3
"""Publish the shareable part of the picture library into this repository (library/).

    ~/.local/share/iwe-imagegen/venv/bin/python library_publish.py [--looks bright,strict,...] [--size 512]

Only the built-in looks are copied: brand looks stay in the local library (their palettes belong
to the brand owner). Rejected pictures are never in the catalog, so they are never copied. Each
picture becomes a WebP of at most --size px (about 30 KB instead of 300 KB of PNG); pictures
already published are kept as they are, so running it after every night adds only the new ones.
Needs Pillow (the image-generation environment).
see docs/service-clause.md
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I leaves the script folder out
import library  # noqa: E402

BUILTIN_LOOKS = ["strict", "bright", "editorial", "blueprint", "night", "watercolor", "sketch", "pop", "steampunk", "fantasy"]
REPO_LIBRARY = Path(__file__).resolve().parent.parent / "library"


def publish(source: Path, dest: Path, looks: list[str], size: int = 512, quality: int = 82) -> tuple[int, int]:
    """Copy catalog rows of the given looks as WebP into dest; returns (added, kept)."""
    unknown = [look for look in looks if look not in BUILTIN_LOOKS]
    if unknown:
        raise SystemExit(f"в открытое хранилище - только встроенные облики, не: {', '.join(unknown)}")
    from PIL import Image  # only the image-generation environment has Pillow

    rows = [r for r in library.read_catalog(source) if r["look"] in looks]
    published = {r["file"]: r for r in library.read_catalog(dest)}
    added = kept = 0
    for r in rows:
        rel = r["file"].rsplit(".", 1)[0] + ".webp"
        out = dest / rel
        if rel in published and out.exists():
            kept += 1
            continue
        src = source / r["file"]
        if not src.exists():
            continue
        img = Image.open(src).convert("RGBA")
        img.thumbnail((size, size))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "WEBP", quality=quality, method=6)
        published[rel] = {**r, "file": rel, "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
        added += 1
    library.write_catalog(dest, sorted(published.values(), key=lambda x: x["file"]))
    library.sheet(dest)
    return added, kept


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--looks", default=",".join(BUILTIN_LOOKS))
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--to", type=Path, default=REPO_LIBRARY)
    args = ap.parse_args()
    added, kept = publish(library.library_root(), args.to, [x for x in args.looks.split(",") if x], args.size)
    print(f"добавлено {added}, уже было {kept}: {args.to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
