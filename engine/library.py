#!/usr/bin/env python3
"""Picture library: images already drawn by the local model, reused instead of drawn again.

    library.py add DIR --look L [--prompts prompts.tsv] [--source "page"]   put a folder's pictures in
    library.py tag LOOK/NAME "слова" [LOOK/NAME "слова" ...]                  Russian words to find them by
    library.py find WORD... [--look L] [--top 12]                             what fits, best first
    library.py take LOOK/NAME --to PAGE_DIR/art-L/name.png                    copy into a page folder
    library.py sheet [-o FILE]                                                one page to look through

The library lives outside this repository: IG_LIBRARY_DIR, by default
$IWE_WORKSPACE/DS-strategy/local/infographic-library. Pictures drawn in a brand palette belong
to the brand's owner, so they never go into a public repository. Layout: <look>/<name>.png and
catalog.tsv (file, look, style, what, tags, source, added, sha256). A picture already in the
library (same sha256) is kept once.
see docs/service-clause.md
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import os
import re
import shutil
import sys
from pathlib import Path

FIELDS = ["file", "look", "style", "what", "tags", "source", "added", "sha256"]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def library_root() -> Path:
    env = os.environ.get("IG_LIBRARY_DIR")
    if env:
        return Path(env)
    workspace = Path(os.environ.get("IWE_WORKSPACE", Path.home() / "IWE"))
    return workspace / "DS-strategy" / "local" / "infographic-library"


def read_catalog(root: Path) -> list[dict]:
    path = root / "catalog.tsv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f, delimiter="\t")]


def write_catalog(root: Path, rows: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / "catalog.tsv.tmp"
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in FIELDS})
    tmp.replace(root / "catalog.tsv")


def read_prompts(path: Path | None) -> dict[str, dict]:
    """name -> {style, what}; reads both 'name style what [w h]' and the older 'name style w h what'."""
    if not path or not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        if len(cells) < 3:
            continue
        what = cells[2]
        if len(cells) >= 5 and cells[2].isdigit() and cells[3].isdigit():
            what = cells[4]
        out[cells[0]] = {"style": cells[1], "what": what}
    return out


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add(folder: Path, look: str, prompts: Path | None, source: str, root: Path) -> list[str]:
    if not NAME_OK.match(look):
        raise SystemExit(f"облик - латинскими буквами без «/»: {look}")
    if not folder.is_dir():
        raise SystemExit(f"нет папки с картинками: {folder}")
    rows = read_catalog(root)
    known = {r["sha256"]: r["file"] for r in rows}
    table = read_prompts(prompts or folder / "prompts.tsv")
    today = dt.date.today().isoformat()
    report = []
    for pic in sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES):
        digest = sha256_of(pic)
        if digest in known:
            report.append(f"уже есть: {known[digest]}")
            continue
        stem = re.sub(r"[^A-Za-z0-9_-]", "-", pic.stem) or "pic"
        name, n = stem, 2
        while (root / look / f"{name}{pic.suffix.lower()}").exists():
            name, n = f"{stem}-{n}", n + 1
        rel = f"{look}/{name}{pic.suffix.lower()}"
        (root / look).mkdir(parents=True, exist_ok=True)
        shutil.copy2(pic, root / rel)
        info = table.get(pic.stem, {})
        rows.append({"file": rel, "look": look, "style": info.get("style", ""), "what": info.get("what", ""),
                     "tags": "", "source": source, "added": today, "sha256": digest})
        known[digest] = rel
        report.append(f"добавлена: {rel}")
    write_catalog(root, rows)
    return report


def tag(pairs: list[str], root: Path) -> list[str]:
    if len(pairs) % 2:
        raise SystemExit("теги - парами: ОБЛИК/ИМЯ «слова»")
    rows = read_catalog(root)
    by_key = {r["file"].rsplit(".", 1)[0]: r for r in rows}
    report = []
    for key, words in zip(pairs[::2], pairs[1::2]):
        key = key.rsplit(".", 1)[0] if key.lower().endswith(tuple(IMAGE_SUFFIXES)) else key
        if key not in by_key:
            raise SystemExit(f"нет такой картинки в каталоге: {key}")
        by_key[key]["tags"] = " ".join(words.split())
        report.append(f"{key}: {by_key[key]['tags']}")
    write_catalog(root, rows)
    return report


def _stem(word: str) -> str:
    word = word.lower()
    return word[: max(4, len(word) - 2)] if len(word) > 5 else word  # tolerate Russian endings


def find(words: list[str], root: Path, look: str | None = None, top: int = 12) -> list[tuple[int, dict]]:
    stems = [_stem(w) for w in words if w.strip()]
    scored = []
    for row in read_catalog(root):
        text = " ".join([row["file"], row["what"], row["tags"]]).lower()
        score = sum(1 for s in stems if s in text)
        if score and look and row["look"] == look:
            score += len(stems)  # the page's own palette first
        if score:
            scored.append((score, row))
    scored.sort(key=lambda x: (-x[0], x[1]["file"]))
    return scored[:top]


def take(key: str, dest: Path, root: Path, force: bool = False) -> Path:
    rows = {r["file"].rsplit(".", 1)[0]: r for r in read_catalog(root)}
    key = key.rsplit(".", 1)[0] if key.lower().endswith(tuple(IMAGE_SUFFIXES)) else key
    if key not in rows:
        raise SystemExit(f"нет такой картинки в каталоге: {key}")
    if dest.exists() and not force:
        raise SystemExit(f"файл уже есть, не перезаписываю (--force): {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / rows[key]["file"], dest)
    return dest


SHEET_CSS = """
body { margin: 0; font: 15px/1.4 -apple-system, "Segoe UI", sans-serif; color: #1f2933; background: #f6f7f8; }
main { max-width: 1280px; margin: 0 auto; padding: 32px 24px 64px; }
h1 { font-size: 30px; margin: 0 0 4px; } h2 { font-size: 22px; margin: 36px 0 14px; }
.lead { color: #5b6670; margin: 0 0 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
figure { margin: 0; background: #fff; border: 1px solid #e3e6e8; border-radius: 12px; padding: 12px; }
figure img { display: block; width: 100%; height: 180px; object-fit: contain; }
figcaption b { display: block; font-family: ui-monospace, Menlo, monospace; font-size: 13px; margin-top: 8px; }
figcaption span { display: block; color: #3d4852; } figcaption small { display: block; color: #8a949c; font-size: 12px; }
"""


def sheet(root: Path, out: Path | None = None) -> Path:
    rows = read_catalog(root)
    out = out or root / "index.html"
    looks = sorted({r["look"] for r in rows})
    parts = [f"<h1>Библиотека картинок</h1><p class=\"lead\">{len(rows)} картинок, обликов: {len(looks)}. "
             "Подобрать: <code>library.py find слова --look облик</code>, взять: <code>library.py take облик/имя --to …</code>.</p>"]
    for look in looks:
        items = [r for r in rows if r["look"] == look]
        parts.append(f"<h2>{html.escape(look)} · {len(items)}</h2><div class=\"grid\">")
        for r in items:
            src = os.path.relpath(root / r["file"], out.parent)
            parts.append(
                f"<figure><img src=\"{html.escape(src)}\" alt=\"\" loading=\"lazy\"><figcaption>"
                f"<b>{html.escape(r['file'].rsplit('.', 1)[0])}</b><span>{html.escape(r['tags'] or '—')}</span>"
                f"<small>{html.escape(r['what'])}</small><small>{html.escape(r['source'])} · {html.escape(r['added'])}</small>"
                "</figcaption></figure>")
        parts.append("</div>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
                   "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                   f"<title>Библиотека картинок</title><style>{SHEET_CSS}</style></head><body><main>"
                   + "\n".join(parts) + "</main></body></html>\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="put a folder's pictures into the library")
    a.add_argument("folder", type=Path)
    a.add_argument("--look", required=True)
    a.add_argument("--prompts", type=Path)
    a.add_argument("--source", default="")
    t = sub.add_parser("tag", help="Russian words to find pictures by")
    t.add_argument("pairs", nargs="+")
    f = sub.add_parser("find", help="pictures that fit, best first")
    f.add_argument("words", nargs="+")
    f.add_argument("--look")
    f.add_argument("--top", type=int, default=12)
    k = sub.add_parser("take", help="copy a picture into a page folder")
    k.add_argument("key")
    k.add_argument("--to", type=Path, required=True)
    k.add_argument("--force", action="store_true")
    s = sub.add_parser("sheet", help="one HTML page to look through the library")
    s.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()
    root = library_root()

    if args.cmd == "add":
        lines = add(args.folder, args.look, args.prompts, args.source, root)
    elif args.cmd == "tag":
        lines = tag(args.pairs, root)
    elif args.cmd == "find":
        hits = find(args.words, root, args.look, args.top)
        lines = [f"{r['file'].rsplit('.', 1)[0]}  ·  {r['tags'] or '—'}  ·  {r['what']}" for _, r in hits] or ["ничего не нашлось"]
    elif args.cmd == "take":
        lines = [f"взята: {take(args.key, args.to, root, args.force)}"]
    else:
        lines = [f"страница библиотеки: {sheet(root, args.output)}"]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
