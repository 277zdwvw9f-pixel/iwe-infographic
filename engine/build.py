#!/usr/bin/env python3
"""Build a self-contained infographic page and check it in headless Chrome.

Input is an HTML page written with the components of looks.css and icons as
<i data-icon="name"></i>. Output is one file: fonts, icons, styles and the
watercolor filters are inlined, nothing is fetched at open time.

    build.py page.src.html -o page.html [--look NAME, see LOOK_FONTS]
             [--all-looks] [--shot page.png]

--shot also measures the page: elements whose content is wider than their box,
horizontal scroll at phone width, and Cyrillic faces of the look that did not load.
see docs/service-clause.md
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
LOOK_FONTS = {
    "strict": ["Onest", "JetBrains Mono"],
    "bright": ["Inter"],
    "watercolor": ["Nunito", "Caveat"],
    "blueprint": ["Onest", "JetBrains Mono"],
    "night": ["Inter", "JetBrains Mono"],
    "editorial": ["Inter", "Playfair Display"],
    "pop": ["Onest", "Unbounded"],
    "steampunk": ["Old Standard TT", "PT Serif"],
    "fantasy": ["Ruslan Display", "Alegreya"],
    "sketch": ["Neucha", "Pangolin"],
    "corp-orange": ["Onest"],
    "corp-green": ["Onest"],
}
LOOK_NAMES = {
    "strict": "Строгий",
    "bright": "Яркий",
    "watercolor": "Акварель",
    "blueprint": "Чертёж",
    "night": "Ночной",
    "editorial": "Журнал",
    "pop": "Поп",
    "steampunk": "Стимпанк",
    "fantasy": "Фэнтези",
    "sketch": "Эскиз",
    "corp-orange": "Оранжевый корпоративный",
    "corp-green": "Зелёный корпоративный",
}
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PHONE_WIDTH = 390
MIME = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".woff2": "font/woff2"}
IMAGE_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".webp"}

class BuildError(Exception):
    pass


# Brand looks live outside this repository (licensed fonts, company logos): each brand is a
# folder with look.json, look.css, fonts.css and the files they reference. IG_BRAND_DIRS
# (os.pathsep-separated) overrides the default local folder; an empty value means no brands.
BRANDS: dict[str, Path] = {}
BRAND_USE: dict[str, str] = {}
BRAND_PALETTE: dict[str, str] = {}  # words for the image model (gen_image.py), kept with the brand


def brand_roots() -> list[Path]:
    env = os.environ.get("IG_BRAND_DIRS")
    if env is not None:
        return [Path(part) for part in env.split(os.pathsep) if part]
    workspace = Path(os.environ.get("IWE_WORKSPACE", Path.home() / "IWE"))
    return [workspace / "DS-strategy" / "local" / "infographic-brands"]


def load_brands(roots: list[Path]) -> None:
    for root in roots:
        for meta in sorted(root.glob("*/look.json")) if root.is_dir() else []:
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                name = data["name"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                print(f"облик в «{meta.parent}» пропущен: look.json не прочитан ({exc!r})", file=sys.stderr)
                continue
            BRANDS[name] = meta.parent
            LOOK_FONTS[name] = data.get("fonts", [])
            LOOK_NAMES[name] = data.get("title", name)
            BRAND_USE[name] = data.get("use", "")
            BRAND_PALETTE[name] = data.get("palette", "")


load_brands(brand_roots())
CHROME_MIN_WIDTH = 500  # headless Chrome never makes a narrower window

# Decorative SVG filters: #ig-wc and #ig-wc-s for watercolor washes, #ig-sk for the tremor of sketch lines.
DECOR_FILTERS = """<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<filter id="ig-wc" x="-20%" y="-20%" width="140%" height="140%">
  <feTurbulence type="fractalNoise" baseFrequency="0.022" numOctaves="3" seed="7" result="warp"/>
  <feDisplacementMap in="SourceGraphic" in2="warp" scale="34" xChannelSelector="R" yChannelSelector="G" result="ragged"/>
  <feGaussianBlur in="ragged" stdDeviation="1.4" result="soft"/>
  <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="3" result="grain"/>
  <feColorMatrix in="grain" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -0.9 1.25" result="grainAlpha"/>
  <feComposite in="soft" in2="grainAlpha" operator="in"/>
</filter>
<filter id="ig-wc-s" x="-10%" y="-40%" width="120%" height="180%">
  <feTurbulence type="fractalNoise" baseFrequency="0.06" numOctaves="2" seed="11" result="warp"/>
  <feDisplacementMap in="SourceGraphic" in2="warp" scale="5" xChannelSelector="R" yChannelSelector="G"/>
</filter>
<filter id="ig-sk" x="-5%" y="-5%" width="110%" height="110%">
  <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="5" result="warp"/>
  <feDisplacementMap in="SourceGraphic" in2="warp" scale="2.6" xChannelSelector="R" yChannelSelector="G"/>
</filter>
</svg>"""

# Runs in the built page: records height, overflowing elements and unloaded
# Cyrillic faces on <html> so --shot can read them back from the dumped DOM.
CHECK_SCRIPT = """<script>
(function () {
var d = document.documentElement, fams = (d.dataset.fonts || '').split('|').filter(Boolean);
// A face loads only when some text is set in it: ask for every look font with a Cyrillic letter first,
// otherwise a font the page happens not to use for Cyrillic would be reported as missing.
Promise.all(fams.map(function (f) {
  return document.fonts.load('16px "' + f + '"', '\u0416').catch(function () { return []; });
})).then(function () { return document.fonts.ready; }).then(function () {
  var missing = fams.filter(function (f) {
    var ok = false;
    document.fonts.forEach(function (face) {
      // A face without unicode-range (one file for all scripts, as brand fonts come) covers Cyrillic too.
      var cyr = /U\\+0?400/.test(face.unicodeRange) || /^U\\+0-10FFFF$/i.test(face.unicodeRange);
      if (face.family.replace(/["']/g, '') === f && cyr && face.status === 'loaded') ok = true;
    });
    return !ok;
  });
  // data-limit narrows the check below the window width (phone check in a 500 px window).
  var limit = +(d.dataset.limit || window.innerWidth), maxRight = 0;
  document.querySelectorAll('body *').forEach(function (e) {
    if (e.closest('svg, .ig-switch')) return;
    maxRight = Math.max(maxRight, e.getBoundingClientRect().right);
  });
  // Text lines that leave their block box (decorative pseudo-elements are ignored on purpose).
  var over = [], walker = document.createTreeWalker(document.querySelector('.ig') || document.body, NodeFilter.SHOW_TEXT), node;
  while ((node = walker.nextNode())) {
    if (!node.textContent.trim() || node.parentElement.closest('svg, script, style')) continue;
    var box = node.parentElement;
    while (box.parentElement && getComputedStyle(box).display.indexOf('inline') === 0) box = box.parentElement;
    var b = box.getBoundingClientRect(), range = document.createRange();
    range.selectNodeContents(node);
    var rects = range.getClientRects();
    for (var i = 0; i < rects.length; i++) {
      if (rects[i].right > b.right + 2 || rects[i].left < b.left - 2 || rects[i].right > limit) {
        over.push(box.tagName.toLowerCase() + '.' + String(box.className).split(' ')[0] + ' «' + node.textContent.trim().slice(0, 30) + '»');
        break;
      }
    }
  }
  d.dataset.h = Math.ceil(d.scrollHeight);
  d.dataset.hscroll = maxRight > limit + 1 ? Math.round(maxRight) : '';
  d.dataset.missing = missing.join('|');
  d.dataset.over = over.slice(0, 12).join(' || ');
});
})();
</script>"""

# Draws curved links from the mind map centre to every branch, from the boxes as laid out,
# so the links follow any amount of text; redrawn on resize. Added only to pages with a mind map.
MINDMAP_SCRIPT = """<script>
(function () {
  function draw() {
    document.querySelectorAll('.ig-mindmap').forEach(function (map) {
      var svg = map.querySelector('.ig-mm-links'), centre = map.querySelector('.ig-mm-center');
      if (!svg || !centre || getComputedStyle(svg).display === 'none') return;
      var box = map.getBoundingClientRect(), c = centre.getBoundingClientRect(), parts = [];
      map.querySelectorAll('.ig-mm-node').forEach(function (node) {
        var r = node.getBoundingClientRect(), left = r.left + r.width / 2 < c.left + c.width / 2;
        var x2 = (left ? r.right : r.left) - box.left, y2 = r.top + r.height / 2 - box.top;
        var x1 = (left ? c.left : c.right) - box.left;
        var y1 = Math.min(Math.max(y2, c.top - box.top + 48), c.bottom - box.top - 48);
        var dx = (x2 - x1) * 0.55, colour = getComputedStyle(node).getPropertyValue('--tone').trim() || '#999';
        parts.push('<path d="M' + x1 + ' ' + y1 + ' C' + (x1 + dx) + ' ' + y1 + ' ' + (x2 - dx) + ' ' + y2 + ' ' + x2 + ' ' + y2 + '" stroke="' + colour + '" stroke-width="5" opacity="0.85"/>');
        parts.push('<circle cx="' + x2 + '" cy="' + y2 + '" r="7" fill="' + colour + '"/><circle cx="' + x1 + '" cy="' + y1 + '" r="5" fill="' + colour + '"/>');
      });
      svg.setAttribute('viewBox', '0 0 ' + box.width + ' ' + box.height);
      svg.innerHTML = parts.join('');
    });
  }
  document.fonts.ready.then(draw);
  window.addEventListener('load', draw);
  window.addEventListener('resize', draw);
})();
</script>"""

SWITCH_SCRIPT = """<nav class="ig-switch" aria-label="Облик">%s</nav>
<script>
document.querySelectorAll('.ig-switch button').forEach(function (b) {
  b.addEventListener('click', function () {
    document.documentElement.dataset.look = b.dataset.look;
    document.querySelectorAll('.ig-switch button').forEach(function (x) { x.setAttribute('aria-pressed', x === b); });
    history.replaceState(null, '', '#' + b.dataset.look);
  });
});
var start = location.hash.slice(1);
if (start) { var btn = document.querySelector('.ig-switch [data-look="' + start + '"]'); if (btn) btn.click(); }
</script>"""




def font_css(families: list[str]) -> str:
    out = []
    for folder in [ASSETS / "fonts", *BRANDS.values()]:
        css_file = folder / "fonts.css"
        if not css_file.exists():
            continue
        for block in re.findall(r"@font-face\s*\{.*?\}", css_file.read_text(encoding="utf-8"), re.S):
            family = re.search(r"font-family:\s*['\"]([^'\"]+)['\"]", block)
            if not family or family.group(1) not in families:
                continue
            url = re.search(r"""url\((['"]?)([^)'"]+\.woff2)\1\)""", block)
            if not url or not (folder / url.group(2)).is_file():
                raise BuildError(f"в «{css_file}» у шрифта «{family.group(1)}» нет файла woff2 рядом")
            data = base64.b64encode((folder / url.group(2)).read_bytes()).decode()
            out.append(block.replace(url.group(0), f"url(data:font/woff2;base64,{data})"))
    return "\n".join(out)


def inline_urls(css: str, base: Path) -> str:
    """Turn url(file) relative to a brand folder into a data: URI; anchors and data: stay."""

    def replace(match: re.Match) -> str:
        ref = match.group(2)
        if ref.startswith(("data:", "#")) or "://" in ref:
            return match.group(0)
        path = base / ref
        if not path.exists():
            raise BuildError(f"в облике «{base.name}» нет файла «{ref}»")
        data = base64.b64encode(path.read_bytes()).decode()
        return f"url(data:{MIME.get(path.suffix, 'application/octet-stream')};base64,{data})"

    return re.sub(r"""url\((['"]?)([^)'"]+)\1\)""", replace, css)


def brand_css(looks: list[str]) -> str:
    return "\n".join(inline_urls((BRANDS[name] / "look.css").read_text(encoding="utf-8"), BRANDS[name]) for name in looks if name in BRANDS)


def asset(folder: str, name: str, suffix: str, what: str) -> Path:
    """A bundled asset by name, or a BuildError that lists the names there are."""
    path = ASSETS / folder / f"{name}{suffix}"
    if "/" in name or not path.is_file():
        known = ", ".join(sorted(p.stem for p in (ASSETS / folder).glob(f"*{suffix}")))
        raise BuildError(f"нет {what} «{name}»; есть: {known}")
    return path


def inline_icons(page: str) -> str:
    def replace(match: re.Match) -> str:
        attrs = match.group(1)
        name = re.search(r'data-icon="([^"]+)"', attrs).group(1)
        svg = asset("icons", name, ".svg", "значка").read_text(encoding="utf-8")
        svg = re.sub(r'\sclass="[^"]*"', "", svg, count=1)
        svg = re.sub(r'\s(width|height)="24"', "", svg)
        extra = re.search(r'class="([^"]+)"', attrs)
        cls = "ig-icon" + (" " + extra.group(1) if extra else "")
        return svg.replace("<svg", f'<svg class="{cls}" aria-hidden="true"', 1).replace("\n", " ")

    return re.sub(r"<i\s+([^>]*data-icon=[^>]*)>\s*</i>", replace, page)


def inline_illustrations(page: str) -> str:
    """<i data-illus="name"></i> -> the drawing from assets/illus, painted by looks.css."""

    def replace(match: re.Match) -> str:
        svg = asset("illus", match.group(1), ".svg", "иллюстрации").read_text(encoding="utf-8").strip()
        return svg.replace("<svg", '<svg class="ig-illus" aria-hidden="true"', 1)

    return re.sub(r'<i\s+data-illus="([^"]+)"\s*>\s*</i>', replace, page)


def inline_3d(page: str) -> str:
    """<i data-3d="name"></i> -> a Fluent 3D picture (Microsoft, MIT) from assets/emoji3d as a data: URI."""

    def replace(match: re.Match) -> str:
        data = base64.b64encode(asset("emoji3d", match.group(1), ".png", "объёмной картинки").read_bytes()).decode()
        return f'<img class="ig-3d" src="data:image/png;base64,{data}" alt="">'

    return re.sub(r'<i\s+data-3d="([^"]+)"\s*>\s*</i>', replace, page)


def inline_images(page: str, base: Path, look: str) -> str:
    """<i data-img="art/x.png"></i> -> that file (path relative to the source page) as a data: URI.

    Used for pictures drawn by the local image model (gen_image.py) and kept next to the page.
    "{look}" in the path becomes the look being built, so one source serves several brands
    with their own pictures: data-img="art-{look}/hero.png".
    """

    root = base.resolve()

    def replace(match: re.Match) -> str:
        ref = match.group(1).replace("{look}", look)
        path = (root / ref).resolve()
        if root not in path.parents or path.suffix.lower() not in IMAGE_SUFFIXES:
            raise BuildError(f"картинка «{ref}» должна быть файлом {'/'.join(sorted(IMAGE_SUFFIXES))} в папке страницы ({root})")
        if not path.is_file():
            raise BuildError(f"нет картинки «{ref}» рядом со страницей ({root})")
        data = base64.b64encode(path.read_bytes()).decode()
        return f'<img class="ig-gen" src="data:{MIME[path.suffix.lower()]};base64,{data}" alt="">'

    return re.sub(r'<i\s+data-img="([^"]+)"\s*>\s*</i>', replace, page)


def expand_pictograms(page: str) -> str:
    """<i data-pict="user" data-n="50" data-on="20"></i> -> a row of 50 icons, the first 20 highlighted."""

    def replace(match: re.Match) -> str:
        attrs = dict(re.findall(r'data-(pict|n|on)="([^"]*)"', match.group(0)))
        try:
            total, on = int(attrs.get("n", 10)), int(attrs.get("on", 0))
        except ValueError:
            raise BuildError(f"в ряду пиктограмм data-n и data-on - целые числа: {match.group(0)[:80]}") from None
        lit = ' class="is-on"'
        icons = "".join(f'<i data-icon="{attrs["pict"]}"{lit if k < on else ""}></i>' for k in range(total))
        return f'<span class="ig-pict" role="img" aria-label="{on} из {total}">{icons}</span>'

    return re.sub(r"<i\s+data-pict=[^>]*>\s*</i>", replace, page)


def check_offline(page: str) -> None:
    """Fail on what the browser fetches by itself: src/srcset/poster/data of media and frames,
    href of SVG <image>/<use>, url(), stylesheet links, @import and a refresh to another address.
    Scripts are not parsed: the pages are written by the agent, and fetch() there is not checked."""
    remote = r"""["']?\s*(?:https?:|file:|ftp:)?//"""
    bad = re.findall(rf"""\b(?:src|srcset|poster|data)\s*=\s*{remote}[^"'\s>]*""", page, re.I)
    bad += re.findall(rf"""<(?:image|use|feImage)\b[^>]*?\bhref\s*=\s*{remote}[^"'\s>]*""", page, re.I)
    bad += re.findall(rf"""url\(\s*{remote}[^)]*\)""", page, re.I)
    bad += re.findall(rf"""<link\b[^>]*?\bhref\s*=\s*{remote}[^>]*>""", page, re.I)
    bad += re.findall(r"""@import\b[^;]*;""", page, re.I)
    bad += re.findall(r"""<meta\b[^>]*http-equiv\s*=\s*["']?refresh[^>]*>""", page, re.I)
    if bad:
        raise BuildError("внешние адреса на странице: " + "; ".join(b[:80] for b in bad[:5]))


def build(source: str, look: str | None, all_looks: bool, base: Path | None = None) -> str:
    page = source
    look_attr = re.search(r'<html[^>]*\sdata-look="([^"]+)"', page)
    look = look or (look_attr.group(1) if look_attr else "strict")
    if look not in LOOK_FONTS:
        raise BuildError(f"неизвестный облик «{look}»; есть: {', '.join(LOOK_FONTS)}")
    page = inline_images(page, base or Path.cwd(), look)
    families = sorted({f for fs in LOOK_FONTS.values() for f in fs}) if all_looks else LOOK_FONTS[look]

    if look_attr:
        page = re.sub(r'(<html[^>]*\sdata-look=")[^"]+"', rf'\g<1>{look}"', page, count=1)
    else:
        page = re.sub(r"<html\b", f'<html data-look="{look}"', page, count=1)
    page = re.sub(r"<html\b", f'<html data-fonts="{html.escape("|".join(LOOK_FONTS[look]))}"', page, count=1)

    page = inline_icons(inline_3d(inline_illustrations(expand_pictograms(page))))
    looks_css = (HERE / "looks.css").read_text(encoding="utf-8") + "\n" + brand_css(list(LOOK_FONTS) if all_looks else [look])
    style = "<style>\n" + font_css(families) + "\n" + looks_css + "\n</style>"
    if "</head>" not in page:
        raise BuildError("нет </head> - страница должна быть полным HTML-документом")
    page = page.replace("</head>", style + "\n</head>", 1)

    body_end = DECOR_FILTERS + "\n" + CHECK_SCRIPT
    if "ig-mindmap" in page:
        body_end += "\n" + MINDMAP_SCRIPT
    if all_looks:
        buttons = "".join(
            f'<button type="button" data-look="{html.escape(key)}" aria-pressed="{str(key == look).lower()}">{html.escape(name)}</button>'
            for key, name in LOOK_NAMES.items()
        )
        body_end += "\n" + SWITCH_SCRIPT % buttons
    if "</body>" not in page:
        raise BuildError("нет </body>")
    page = page.replace("</body>", body_end + "\n</body>", 1)
    check_offline(page)
    return page


def chrome(*args: str) -> str:
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=4000", *args]
    with tempfile.TemporaryDirectory() as profile:
        try:
            res = subprocess.run(cmd + [f"--user-data-dir={profile}"], capture_output=True, text=True, timeout=90)
        except FileNotFoundError:
            raise BuildError(f"нет Google Chrome по пути «{CHROME}»; другой путь - переменная CHROME") from None
        except subprocess.TimeoutExpired:
            raise BuildError("Chrome не ответил за 90 с") from None
    if res.returncode != 0:
        raise BuildError(f"Chrome завершился с ошибкой: {res.stderr.strip()[:300]}")
    return res.stdout


def measure(page: Path, width: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        target = page
        if width < CHROME_MIN_WIDTH:
            # Media queries see the 500 px window (already "narrow"); the body is squeezed to the phone width.
            src = page.read_text(encoding="utf-8")
            src = re.sub(r"<html\b", f'<html data-limit="{width}"', src, count=1)
            src = src.replace("</head>", f"<style>body{{width:{width}px}}</style></head>", 1)
            target = Path(tmp) / page.name
            target.write_text(src, encoding="utf-8")
        dom = chrome(f"--window-size={max(width, CHROME_MIN_WIDTH)},1000", "--dump-dom", target.as_uri())
    tag = re.search(r"<html[^>]*>", dom).group(0)
    return {key: html.unescape(val) for key, val in re.findall(r'data-(h|hscroll|missing|over)="([^"]*)"', tag)}


def shoot(page: Path, png: Path, width: int) -> list[str]:
    wide = measure(page, width)
    phone = measure(page, PHONE_WIDTH)
    if "h" not in wide:
        raise BuildError("страница не сообщила свою высоту - проверка в Chrome не отработала")
    chrome(f"--window-size={width},{int(wide['h']) + 8}", f"--screenshot={png}", page.as_uri())
    problems = []
    if wide.get("missing"):
        problems.append(f"не загрузилась кириллица шрифтов: {wide['missing']}")
    if wide.get("over"):
        problems.append(f"вылезает за край при ширине {width}: {wide['over']}")
    if phone.get("hscroll"):
        problems.append(f"горизонтальная прокрутка на телефоне ({PHONE_WIDTH} px): ширина {phone['hscroll']}")
    if phone.get("over"):
        problems.append(f"вылезает за край на телефоне: {phone['over']}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--look", choices=sorted(LOOK_FONTS), help="brand looks are found in IG_BRAND_DIRS")
    ap.add_argument("--all-looks", action="store_true", help="embed every look and add a switcher")
    ap.add_argument("--shot", type=Path, help="save a full-page PNG and report layout problems")
    ap.add_argument("--width", type=int, default=1280)
    args = ap.parse_args()
    try:
        if not args.source.is_file():
            raise BuildError(f"нет исходника «{args.source}»")
        page = build(args.source.read_text(encoding="utf-8"), args.look, args.all_looks, args.source.resolve().parent)
        args.output.write_text(page, encoding="utf-8")
        print(f"страница: {args.output} ({len(page.encode()) // 1024} КБ)")
        if args.shot:
            problems = shoot(args.output.resolve(), args.shot, args.width)
            print(f"снимок: {args.shot}")
            for p in problems:
                print(f"  ! {p}")
            if problems:
                return 2
            print("  проверка: кириллица встроенная, за края ничего не вылезает, на телефоне без прокрутки вбок")
    except BuildError as exc:
        print(f"ошибка сборки: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
