#!/usr/bin/env python3
"""Draw a picture for an infographic with a local image model (mflux, Apple Silicon).

Runs under the python of the image-generation environment, which has mflux and Pillow:

    ~/.local/share/iwe-imagegen/venv/bin/python gen_image.py "two server racks linked by a cable" \
        -o art/servers.png [--look bright] [--style iso|flat|character|scene|backdrop] [--size 768] [--seed 7]
        [--model flux2-klein-4b|z-image-turbo|openrouter-flux2-klein-4b]
    ... gen_image.py --batch prompts.tsv -o "art-{look}" --look bright,night   # a whole table, per palette

The prompt says WHAT to draw; --style and --look add HOW (render, palette). The picture never
carries text: the page sets all text itself, so Cyrillic stays exact and numbers stay editable.
The background is cut away by an object-segmentation model (cutout.py, BiRefNet) when the
environment has it, otherwise by a flood fill of near-white from the edges, which also takes white
parts of the object that touch the background; then the picture is trimmed to its content. Local models: nothing leaves the machine.
--model openrouter-*: the prompt (a generic description plus palette words, never text from the
material) goes to OpenRouter, key in OPENROUTER_API_KEY; for urgent pictures in the daytime.
see docs/service-clause.md
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import deque
from pathlib import Path

STYLES = {
    "iso": "isometric 3D illustration of {what}, soft clay render, rounded shapes, gentle soft shadow, "
    "centered, isolated on a plain pure white background, {palette}, minimal clean detail",
    "flat": "flat vector illustration of {what}, simple geometric shapes, thin dark outline, centered, "
    "isolated on a plain pure white background, {palette}",
    "character": "cute friendly 3D cartoon character, {what}, soft render, expressive eyes, full body, centered, "
    "isolated on a plain pure white background, {palette}",
    "scene": "isometric 3D scene of {what}, clean soft lighting, centered on a plain pure white background, {palette}",
    "backdrop": "wide soft panoramic illustration of {what}, airy and light, pale low-contrast {palette}, gentle haze, lots of empty white space in the middle",
}
NO_TEXT = ", no text, no letters, no numbers, no logo, no watermark"
# Palettes of the bundled looks; a brand look brings its own as "palette" in its look.json.
PALETTES = {
    "bright": "bright blue, orange and green accents with white",
    "night": "cyan and violet accents with dark navy details",
    "blueprint": "blue and light grey technical colours",
    "pop": "saturated yellow, pink and teal colours with black outlines",
    "watercolor": "soft watercolour pastel colours",
    "strict": "black, white and one orange accent",
    "editorial": "charcoal, warm beige and one deep red accent",
    "sketch": "pencil grey and light grey with one blue accent",
    "steampunk": "brass, copper and dark brown colours",
    "fantasy": "parchment, gold and deep green colours",
    "corp-orange": "warm amber and orange colours with light grey and white",
    "corp-green": "teal and turquoise colours with light grey and white",
}
# Near-white is cut away with the background (WHITE_TOLERANCE), so palettes avoid "white" and "cream":
# white parts of an object that touch the background vanish with it (seen 21.10 in the strict look).
DEFAULT_PALETTE = "soft pastel colours"
# Few-step distilled models (mflux 0.22): command and number of steps each one needs.
MODELS = {
    "flux2-klein-4b": ("mflux-generate-flux2", 4),  # FLUX.2 Klein 4B, Apache-2.0, not gated
    "z-image-turbo": ("mflux-generate-z-image-turbo", 8),  # Z-Image Turbo 6B
}
# Online models via OpenRouter: our name -> OpenRouter model slug (same weights as the local default).
REMOTE = {
    "openrouter-flux2-klein-4b": "black-forest-labs/flux.2-klein-4b",
}
OPENROUTER_URL = "https://openrouter.ai/api/v1/images"
QUANTIZE = os.environ.get("IG_IMAGEGEN_QUANTIZE", "4")
# Pre-quantized copies made once with `mflux-save --quantize 4`: they load small, while quantizing
# a full model at every start first loads it whole and pushes a 24 GB Mac into swap.
SAVED = Path(os.environ.get("IG_IMAGEGEN_MODELS", Path.home() / ".local/share/iwe-imagegen/models"))
WHITE_TOLERANCE = 28  # how far from pure white a pixel may be and still count as background


def palette_for(look: str | None) -> str:
    if look in PALETTES:
        return PALETTES[look]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build  # brand folders are found the same way the page builder finds them

    return build.BRAND_PALETTE.get(look or "") or DEFAULT_PALETTE


def prompt_for(what: str, style: str, look: str | None) -> str:
    palette = palette_for(look)
    return STYLES[style].format(what=what, palette=palette) + NO_TEXT


def aspect_ratio(width: int, height: int) -> str:
    g = math.gcd(width, height)
    return f"{width // g}:{height // g}"


def generate_remote(prompt: str, out: Path, width: int, height: int, seed: int, model: str) -> str:
    """Draw through OpenRouter's image API; returns what the call cost, if the answer says."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("нет ключа OpenRouter: задайте переменную окружения OPENROUTER_API_KEY")
    body = {"model": REMOTE[model], "prompt": prompt, "aspect_ratio": aspect_ratio(width, height), "seed": seed}
    req = urllib.request.Request(OPENROUTER_URL, data=json.dumps(body).encode("utf-8"),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        answer = json.load(resp)
    try:
        item = answer["data"][0]
    except (KeyError, IndexError, TypeError):
        raise SystemExit(f"OpenRouter не вернул картинку: {str(answer)[:400]}") from None
    if item.get("b64_json"):
        out.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=180) as pic:
            out.write_bytes(pic.read())
    else:
        raise SystemExit(f"OpenRouter не вернул картинку: {str(item)[:400]}")
    cost = (answer.get("usage") or {}).get("cost")
    return f"{cost} $" if cost is not None else "цена не указана"


def generate(prompt: str, out: Path, width: int, height: int, seed: int, model: str) -> None:
    if model in REMOTE:
        print("OpenRouter:", generate_remote(prompt, out, width, height, seed, model), flush=True)
        return
    command, steps = MODELS[model]
    cli = Path(sys.executable).parent / command
    saved = SAVED / f"{model}-q{QUANTIZE}"
    source = ["--model", str(saved), "--base-model", model] if saved.is_dir() else ["--model", model, "--quantize", QUANTIZE]
    cmd = [str(cli), *source, "--prompt", prompt, "--steps", str(steps), "--seed", str(seed),
           "--width", str(width), "--height", str(height), "--output", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not out.exists():
        raise SystemExit(f"модель не нарисовала картинку: {res.stderr.strip()[-600:]}")


def cut_background(img):
    """Make the near-white region connected to the edges transparent, then trim to the content."""
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    def is_bg(x: int, y: int) -> bool:
        r, g, b, _ = px[x, y]
        return 255 - min(r, g, b) <= WHITE_TOLERANCE

    seen = bytearray(w * h)
    queue = deque((x, y) for x in range(w) for y in (0, h - 1)) + deque((x, y) for y in range(h) for x in (0, w - 1))
    while queue:
        x, y = queue.popleft()
        i = y * w + x
        if seen[i] or not is_bg(x, y):
            continue
        seen[i] = 1
        r, g, b, _ = px[x, y]
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx]:
                queue.append((nx, ny))
    box = img.getbbox()
    return img.crop(box) if box else img


def read_batch(path: Path) -> list[dict]:
    """Rows of a prompts table: name, style, what [, width, height]; tab-separated, '#' comments."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        if len(cells) < 3 or cells[1] not in STYLES:
            raise SystemExit(f"строка таблицы не разобрана (имя, стиль из {sorted(STYLES)}, описание): {line[:80]}")
        if not cells[0] or "/" in cells[0] or cells[0].startswith("."):
            raise SystemExit(f"имя картинки - без «/» и не с точки: {line[:80]}")
        row = {"name": cells[0], "style": cells[1], "what": cells[2]}
        if len(cells) >= 5:
            if not (cells[3].isdigit() and cells[4].isdigit()):
                raise SystemExit(f"ширина и высота - целые числа: {line[:80]}")
            row["width"], row["height"] = int(cells[3]), int(cells[4])
        rows.append(row)
    return rows


def cut(img):
    """Picture without its background: the segmentation model if installed, else the white flood fill."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cutout

    if cutout.available():
        try:
            return cutout.cut_model(img)
        except Exception as exc:  # a failed model must not cost the picture: fall back, but say so
            print(f"модель обрезки не сработала ({exc!r}) - режу по белому", file=sys.stderr)
    return cut_background(img)


def draw(what: str, out: Path, style: str, look: str | None, width: int, height: int, seed: int, model: str, keep_bg: bool) -> str:
    from PIL import Image  # only the image-generation environment has Pillow

    prompt = prompt_for(what, style, look)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.png"
        generate(prompt, raw, width, height, seed, model)
        img = Image.open(raw)
        if not keep_bg and style != "backdrop":  # a backdrop keeps its own background
            img = cut(img)
        img.save(out)
    return f"{out} ({img.size[0]}×{img.size[1]})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", nargs="?", help="what to draw, in English, without any text in the picture")
    ap.add_argument("-o", "--output", type=Path, required=True, help="file; with --batch a folder, '{look}' allowed")
    ap.add_argument("--batch", type=Path, help="prompts table: name, style, what [, width, height]")
    ap.add_argument("--style", choices=sorted(STYLES), default="iso")
    ap.add_argument("--look", default="", help="look whose palette to use; with --batch several, comma-separated")
    ap.add_argument("--size", type=int, default=768, help="square side; --width/--height override it")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--keep-bg", action="store_true", help="keep the white background")
    ap.add_argument("--force", action="store_true", help="with --batch: redraw pictures that already exist")
    ap.add_argument("--model", choices=sorted({**MODELS, **REMOTE}), default=os.environ.get("IG_IMAGEGEN_MODEL", "flux2-klein-4b"))
    args = ap.parse_args()
    width, height = args.width or args.size, args.height or args.size

    if not args.batch:
        if not args.what:
            ap.error("нужно описание картинки или --batch")
        print("картинка:", draw(args.what, args.output, args.style, args.look or None, width, height, args.seed, args.model, args.keep_bg))
        print("описание:", prompt_for(args.what, args.style, args.look or None))
        return 0

    rows = read_batch(args.batch)
    for look in [x.strip() for x in args.look.split(",")] if args.look else [""]:
        folder = Path(str(args.output).replace("{look}", look))
        for row in rows:
            out = folder / f"{row['name']}.png"
            if out.exists() and not args.force:
                print(f"есть: {out}")
                continue
            started = time.time()
            done = draw(row["what"], out, row["style"], look or None, row.get("width", width), row.get("height", height), args.seed, args.model, args.keep_bg)
            print(f"картинка: {done}, {time.time() - started:.0f} с")
    return 0


if __name__ == "__main__":
    sys.exit(main())
