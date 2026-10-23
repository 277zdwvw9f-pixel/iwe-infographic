#!/usr/bin/env python3
"""Cut the background off a drawn picture with an object-segmentation model (BiRefNet, MIT).

Runs under the python of the image-generation environment, which needs, besides mflux and Pillow:

    ~/.local/share/iwe-imagegen/venv/bin/pip install torch torchvision transformers timm kornia einops opencv-python-headless

    ... cutout.py recut [--looks bright,strict] [--limit N]    re-cut the library's pictures in place

The model looks at the shape of the object, not at its colour, so white and pale parts of the object
survive (a cut by "near-white touching the edge" ate sheets, cups and whole watercolour gears, 23.10).
The model in turn takes a big light plane inside a rim (the face of a tile, a phone screen, a dial)
for background seen through a hole; such enclosed planes get their alpha back unless they are plain
background white (fill_planes).
Weights come once from Hugging Face (~900 MB, pinned revision), then everything runs on the Mac.
Without the model the caller falls back to the white flood fill (gen_image.cut_background).

Every cut changes alpha only: the colour under a cut stays in the file, so a picture can be re-cut
later. Before the first re-cut the library copy goes to <library>/_backups/orig/ (outside the
full archive, like other _backups) and the re-cut always starts from that copy.
see docs/service-clause.md
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I leaves the script folder out
import library  # noqa: E402

MODEL_ID = "ZhengPeng7/BiRefNet"
MODEL_REVISION = "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4"  # remote code runs from this exact revision
NEEDS = ("torch", "torchvision", "transformers", "timm", "kornia", "einops", "cv2", "numpy")
SIDE = 1024  # the model's input size
PAD = 0.12  # white margin around the picture: an object touching the border is cut cleaner with room
ALPHA_MIN = 8  # alpha at or below this does not count when trimming to the content
# An enclosed transparent region is a real hole (the middle of a gear, a gap in a crane) when most of
# it is the plain white of the background; a shaded or tinted one is a plane of the object, and so is
# any region bigger than BIG_PLANE of the picture. Tuned on the 3 628 pictures of the library, 23.10.
PLAIN_WHITE = 248  # min(R, G, B) of the background white
PLAIN_SHARE = 0.6
BIG_PLANE = 0.06
BACKUP = Path("_backups") / "orig"

_model = None
_device = "cpu"


def available() -> bool:
    """True when the segmentation model can be loaded in this python."""
    return all(importlib.util.find_spec(m) for m in NEEDS)


def _load():
    global _model, _device
    if _model is None:
        import torch
        from transformers import AutoModelForImageSegmentation

        _device = "mps" if torch.backends.mps.is_available() else "cpu"
        model = AutoModelForImageSegmentation.from_pretrained(MODEL_ID, revision=MODEL_REVISION, trust_remote_code=True)
        model = model.to(_device).eval()
        _model = model.half() if _device == "mps" else model.float()
    return _model


def mask_for(rgb):
    """Object mask (mode L, same size as rgb) of an RGB picture on a white background."""
    import torch
    from PIL import Image
    from torchvision import transforms

    model = _load()
    w, h = rgb.size
    pad = int(max(w, h) * PAD)
    canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad), (255, 255, 255))
    canvas.paste(rgb, (pad, pad))
    prep = transforms.Compose([transforms.Resize((SIDE, SIDE)), transforms.ToTensor(),
                               transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    x = prep(canvas).unsqueeze(0).to(_device)
    with torch.no_grad():
        pred = model(x.half() if _device == "mps" else x)[-1].sigmoid().float().cpu()[0].squeeze()
    mask = transforms.functional.to_pil_image(pred).resize(canvas.size, Image.BILINEAR)
    return mask.crop((pad, pad, pad + w, pad + h))


def fill_planes(img):
    """Give alpha back to transparent regions enclosed by the object that are not plain background."""
    import cv2
    import numpy as np
    from PIL import Image

    a = np.array(img.convert("RGBA"))
    alpha = a[..., 3]
    h, w = alpha.shape
    count, labels, stats, _ = cv2.connectedComponentsWithStats((alpha <= 128).astype(np.uint8), connectivity=4)
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if x == 0 or y == 0 or x + bw == w or y + bh == h:
            continue  # reaches the border: outside the object
        region = labels == i
        plain = float((a[..., :3][region].min(axis=1) >= PLAIN_WHITE).mean())
        if plain < PLAIN_SHARE or area / (w * h) > BIG_PLANE:
            alpha[cv2.dilate(region.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)] = 255
    return Image.fromarray(a)


def cut_model(img):
    """RGBA picture: the colour of img untouched, alpha from the model, trimmed to the content."""
    rgb = img.convert("RGB")  # drops alpha without blending: a cut picture gets its colour back
    out = rgb.copy()
    out.putalpha(mask_for(rgb))
    out = fill_planes(out)
    box = out.getchannel("A").point(lambda a: 255 if a > ALPHA_MIN else 0).getbbox()
    return out.crop(box) if box else out


def heat_warning() -> str | None:
    """The pmset line that shows macOS is limiting for heat, or None while it is calm (as night.py)."""
    try:
        out = subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        low = line.lower()
        number = re.search(r"(\d+)\s*$", line.strip())
        if not number or "recorded" in low:
            continue
        value = int(number.group(1))
        if ("speed_limit" in low and value < 100) or ("warning" in low and value > 0):
            return line.strip()
    return None


def recut(root: Path, looks: list[str] | None, limit: int = 0) -> tuple[int, int]:
    """Re-cut library pictures in place from their first copy; returns (cut, already done)."""
    from PIL import Image

    rows = library.read_catalog(root)
    done_list = root / BACKUP / "recut-done.txt"
    done = set(done_list.read_text(encoding="utf-8").split()) if done_list.exists() else set()
    cut = skipped = 0
    for row in rows:
        if looks and row["look"] not in looks:
            continue
        if row.get("style") == "backdrop":
            continue  # a backdrop keeps its own background (as in gen_image.draw)
        if row["file"] in done:
            skipped += 1
            continue
        src = root / row["file"]
        if not src.exists():
            continue
        orig = root / BACKUP / row["file"]
        if not orig.exists():
            orig.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, orig)
        if cut and cut % 25 == 0:
            while (warn := heat_warning()):
                print(f"Мак греется ({warn}) - жду 10 минут", flush=True)
                time.sleep(600)
        cut_model(Image.open(orig)).save(src)
        row["sha256"] = hashlib.sha256(src.read_bytes()).hexdigest()
        with done_list.open("a", encoding="utf-8") as f:
            f.write(row["file"] + "\n")
        cut += 1
        if cut % 100 == 0:
            library.write_catalog(root, rows)
            print(f"перерезано {cut}", flush=True)
        if limit and cut >= limit:
            break
    library.write_catalog(root, rows)
    return cut, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("recut", help="re-cut the library's pictures in place")
    r.add_argument("--looks", default="", help="looks to re-cut, comma-separated; all by default")
    r.add_argument("--limit", type=int, default=0, help="stop after N pictures (a trial run)")
    args = ap.parse_args()
    if not available():
        raise SystemExit("модели обрезки нет в этом окружении: " + ", ".join(m for m in NEEDS if not importlib.util.find_spec(m)))
    root = library.library_root()
    started = time.time()
    cut, skipped = recut(root, [x for x in args.looks.split(",") if x] or None, args.limit)
    print(f"перерезано {cut}, уже было {skipped}, {time.time() - started:.0f} с; исходники - {root / BACKUP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
