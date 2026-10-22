#!/usr/bin/env python3
"""Contact sheet: one picture with several infographics side by side.

    sheet.py page.src.html -o sheet.png [--looks strict,bright,...]     one page in many looks
    sheet.py a.src.html b.src.html ... -o sheet.png                      many pages, each in its own look
             [--cols 5] [--crop 1700] [--tile 520] [--title "..."] [--subtitle "..."]

Every tile is the top --crop pixels of a page built at 1280 px width. Under a look tile go the
look's name and what it is for (LOOK_USE); under a page tile go its <meta name="ig-type">
(the structure) and its title with the look.
see docs/service-clause.md
"""

from __future__ import annotations

import argparse
import base64
import html
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I leaves the script folder out
import build  # noqa: E402

PAGE_WIDTH = 1280
GAP = 28
PAD = 56
LOOK_USE = {
    "strict": "руководство, деньги, официальные документы",
    "bright": "команда, обучение, сводка «как у Джемини»",
    "watercolor": "идея «на пальцах», сообщество",
    "blueprint": "ИТ-архитектура, схемы серверов и интеграций",
    "night": "показатели, мониторинг, показ на проекторе",
    "editorial": "аналитика и обзоры для руководителя",
    "pop": "анонсы, команда, «чтобы запомнили»",
    "steampunk": "производство, механика, тема «как устроено»",
    "fantasy": "история, легенда проекта, игровая подача",
    "sketch": "замысел и черновик решения, разбор у доски",
    "corp-orange": "деловой материал в тёплом корпоративном тоне, без логотипа",
    "corp-green": "деловой материал в спокойном бирюзово-зелёном корпоративном тоне, без логотипа",
}


DEFAULTS = {
    "looks": ("Одна страница - разные облики",
              "Содержание везде одно и то же, меняется только облик. Форма подбирается под устройство материала, облик - под читателя."),
    "pages": ("Инфографика разного устройства",
              "Форма подбирается под то, как устроен материал: шаги, выбор по вопросам, цикл, слои, две оси. Облик у каждой свой."),
}


def tile_png(source: str, look: str | None, png: Path, crop: int, base: Path) -> bytes:
    page = png.with_suffix(".html")
    page.write_text(build.build(source, look, False, base), encoding="utf-8")
    build.chrome(f"--window-size={PAGE_WIDTH},{crop}", f"--screenshot={png}", page.as_uri())
    return png.read_bytes()


def page_caption(source: str) -> tuple[str, str]:
    """(structure, "title · look") for a page tile."""
    kind = re.search(r'<meta name="ig-type" content="([^"]*)"', source)
    title = re.search(r"<title>(.*?)</title>", source, re.S)
    look = re.search(r'<html[^>]*\sdata-look="([^"]+)"', source)
    name = build.LOOK_NAMES.get(look.group(1), "") if look else ""
    title_text = html.unescape(title.group(1).strip()) if title else ""
    return (html.unescape(kind.group(1)) if kind else title_text, " · ".join(x for x in (title_text, name.lower()) if x))


def sheet_width(cols: int, tile: int) -> int:
    return PAD * 2 + cols * tile + (cols - 1) * GAP


def sheet_html(title: str, subtitle: str, tiles: list[tuple[str, str, bytes]], cols: int, crop: int, tile: int) -> str:
    tile_height = round(tile * crop / PAGE_WIDTH)
    figures = []
    for heading, note, png in tiles:
        data = base64.b64encode(png).decode()
        figures.append(
            f'<figure><img src="data:image/png;base64,{data}" width="{tile}" height="{tile_height}" alt="">'
            f"<figcaption><b>{html.escape(heading)}</b><span>{html.escape(note)}</span></figcaption></figure>"
        )
    width = sheet_width(cols, tile)
    return f"""<!doctype html>
<html lang="ru" data-fonts="Onest"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
{build.font_css(["Onest"])}
* {{ box-sizing: border-box; }}
body {{ margin: 0; width: {width}px; padding: {PAD}px; background: #ecebe6; color: #16161a; font-family: "Onest", sans-serif; }}
header {{ margin-bottom: 36px; }}
h1 {{ margin: 0; font-size: 44px; font-weight: 800; letter-spacing: -0.02em; }}
header p {{ margin: 10px 0 0; font-size: 21px; color: #55555c; max-width: 80ch; }}
main {{ display: grid; grid-template-columns: repeat({cols}, {tile}px); gap: {GAP}px; }}
figure {{ margin: 0; display: flex; flex-direction: column; gap: 12px; }}
img {{ display: block; border-radius: 12px; box-shadow: 0 1px 2px rgba(0,0,0,.08), 0 10px 26px rgba(0,0,0,.12); background: #fff; }}
figcaption {{ display: flex; flex-direction: column; gap: 2px; padding: 0 4px; }}
figcaption b {{ font-size: 21px; }}
figcaption span {{ font-size: 16px; color: #55555c; }}
</style></head>
<body class="ig">
<header><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></header>
<main>{"".join(figures)}</main>
{build.CHECK_SCRIPT}
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sources", type=Path, nargs="+")
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--looks", default=",".join(build.LOOK_NAMES), help="one page only: comma-separated, in sheet order")
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--crop", type=int, default=1700, help="page height shown in each tile, px at 1280 width")
    ap.add_argument("--tile", type=int, default=520, help="tile width on the sheet, px")
    ap.add_argument("--title")
    ap.add_argument("--subtitle")
    args = ap.parse_args()
    mode = "looks" if len(args.sources) == 1 else "pages"
    looks = [name.strip() for name in args.looks.split(",") if name.strip()]
    unknown = [name for name in looks if name not in build.LOOK_NAMES]
    if mode == "looks" and unknown:
        print(f"ошибка: неизвестные облики {unknown}; есть: {', '.join(build.LOOK_NAMES)}", file=sys.stderr)
        return 1
    title = args.title or DEFAULTS[mode][0]
    subtitle = args.subtitle or DEFAULTS[mode][1]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            if mode == "looks":
                source = args.sources[0].read_text(encoding="utf-8")
                tiles = [
                    (build.LOOK_NAMES[look], LOOK_USE.get(look) or build.BRAND_USE.get(look, ""), tile_png(source, look, Path(tmp) / f"{look}.png", args.crop, args.sources[0].resolve().parent))
                    for look in looks
                ]
            else:
                tiles = []
                for n, path in enumerate(args.sources):
                    source = path.read_text(encoding="utf-8")
                    tiles.append((*page_caption(source), tile_png(source, None, Path(tmp) / f"page{n}.png", args.crop, path.resolve().parent)))
            sheet = Path(tmp) / "sheet.html"
            sheet.write_text(sheet_html(title, subtitle, tiles, args.cols, args.crop, args.tile), encoding="utf-8")
            width = sheet_width(args.cols, args.tile)
            height = int(build.measure(sheet, width)["h"])
            build.chrome(f"--window-size={width},{height}", f"--screenshot={args.output.resolve()}", sheet.as_uri())
    except build.BuildError as exc:
        print(f"ошибка сборки: {exc}", file=sys.stderr)
        return 1
    print(f"лист: {args.output} ({width}×{height}, плиток: {len(tiles)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
