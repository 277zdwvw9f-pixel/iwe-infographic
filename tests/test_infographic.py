#!/usr/bin/env python3
"""Infographic builder: what ends up inlined, what it refuses, what the Chrome check catches.

The Chrome cases run only where Google Chrome is installed; they guard the layout
check itself, which once measured "phone" at 500 px because headless Chrome
cannot open a narrower window. Test names stay short: the secret scanner of this
workspace takes a long "test_..." name for a payment key.
"""

import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SOURCE))
os.environ["IG_BRAND_DIRS"] = ""  # the tests must not depend on brand folders of this machine

import build  # noqa: E402 — path added above
import gen_image  # noqa: E402 — imports without Pillow; drawing itself needs the image env
import library  # noqa: E402
import sheet  # noqa: E402

PAGE = """<!doctype html>
<html lang="ru" data-look="strict">
<head><meta charset="utf-8"><title>Проба</title></head>
<body>
<main class="ig">
  <header class="ig-hero"><p class="ig-kicker">Проба · 15.10.2026</p>
    <div><h1>Заголовок страницы</h1><p class="ig-lead">Главная мысль.</p></div></header>
  <section class="ig-stats">
    <div class="ig-card ig-stat" data-tone="2"><i data-icon="server"></i><b>2</b><span>сервера</span></div>
  </section>
  <footer class="ig-foot"><p>Источник: <a href="https://example.org/spec">спецификация</a></p></footer>
</main>
</body>
</html>
"""


def families_of(page: str) -> set[str]:
    return set(re.findall(r"font-family: '([^']+)';\s*font-style", page))


class BuildTest(unittest.TestCase):
    def test_icons_inlined(self):
        page = build.build(PAGE, None, False)
        self.assertNotIn("data-icon", page)
        self.assertIn('<svg class="ig-icon" aria-hidden="true"', page)
        self.assertIn('<rect width="20" height="8" x="2" y="2"', page)  # the server glyph itself

    def test_look_fonts_only(self):
        page = build.build(PAGE, None, False)
        self.assertEqual(families_of(page), {"Onest", "JetBrains Mono"})
        self.assertIn("data:font/woff2;base64,", page)
        self.assertIn('data-fonts="Onest|JetBrains Mono"', page)

    def test_look_override(self):
        page = build.build(PAGE, "watercolor", False)
        html_tag = re.search(r"<html[^>]*>", page).group(0)
        self.assertIn('data-look="watercolor"', html_tag)
        self.assertNotIn('data-look="strict"', html_tag)
        self.assertEqual(families_of(page), {"Nunito", "Caveat"})

    def test_all_looks_switcher(self):
        page = build.build(PAGE, "bright", True)
        self.assertEqual(families_of(page), {f for fonts in build.LOOK_FONTS.values() for f in fonts})
        self.assertIn("Playfair Display", families_of(page))
        self.assertEqual(len(re.findall(r'<button type="button" data-look=', page)), len(build.LOOK_NAMES))
        self.assertIn('data-look="bright" aria-pressed="true"', page)

    def test_unknown_icon(self):
        with self.assertRaisesRegex(build.BuildError, "нет значка «no-such-icon»"):
            build.build(PAGE.replace('data-icon="server"', 'data-icon="no-such-icon"'), None, False)

    def test_unknown_look(self):
        with self.assertRaisesRegex(build.BuildError, "неизвестный облик «neon»"):
            build.build(PAGE, "neon", False)

    def test_offline_only(self):
        with_img = PAGE.replace("</main>", '<img src="https://example.org/a.png"></main>')
        with self.assertRaisesRegex(build.BuildError, "внешние адреса"):
            build.build(with_img, None, False)
        with_css = PAGE.replace("</head>", '<link rel="stylesheet" href="https://fonts.example/x.css"></head>')
        with self.assertRaisesRegex(build.BuildError, "внешние адреса"):
            build.build(with_css, None, False)
        # The source link in the footer is a link to follow, not a resource to fetch.
        self.assertIn('href="https://example.org/spec"', build.build(PAGE, None, False))

    def test_offline_more(self):
        fetched = [
            '<img srcset="https://example.org/a.png 2x">',
            '<IMG SRC="//example.org/a.png">',
            '<svg><image href="https://example.org/a.png"/></svg>',
            '<svg><use xlink:href="http://example.org/s.svg#a"/></svg>',
            '<object data="https://example.org/a.pdf"></object>',
            '<div style="background: URL(file:///etc/hosts)"></div>',
        ]
        for tag in fetched:
            with self.subTest(tag=tag), self.assertRaisesRegex(build.BuildError, "внешние адреса"):
                build.build(PAGE.replace("</main>", tag + "</main>"), None, False)
        with self.assertRaisesRegex(build.BuildError, "внешние адреса"):
            build.build(PAGE.replace("</head>", '<meta http-equiv="refresh" content="0; url=https://example.org"></head>'), None, False)
        local = '<svg><use href="#mark"/></svg>'
        self.assertIn(local, build.build(PAGE.replace("</main>", local + "</main>"), None, False))

    def test_pict_not_number(self):
        with self.assertRaisesRegex(build.BuildError, "целые числа"):
            build.build(PAGE.replace("<b>2</b>", '<i data-pict="user" data-n="seven"></i>'), None, False)


class GraphicsTest(unittest.TestCase):
    def test_illus_inlined(self):
        page = build.build(PAGE.replace("<b>2</b>", '<i data-illus="servers"></i><b>2</b>'), None, False)
        self.assertIn('<svg class="ig-illus" aria-hidden="true"', page)
        self.assertNotIn("data-illus", page)
        self.assertIn('class="f1 o"', page)  # painted by looks.css, not by baked colours

    def test_illus_unknown(self):
        with self.assertRaisesRegex(build.BuildError, "нет иллюстрации «unicorn»"):
            build.build(PAGE.replace("<b>2</b>", '<i data-illus="unicorn"></i>'), None, False)

    def test_3d_data_uri(self):
        page = build.build(PAGE.replace("<b>2</b>", '<i data-3d="key"></i>'), None, False)
        self.assertIn('<img class="ig-3d" src="data:image/png;base64,', page)

    def test_pict_counts(self):
        page = build.build(PAGE.replace("<b>2</b>", '<i data-pict="user" data-n="7" data-on="3"></i>'), None, False)
        row = re.search(r'<span class="ig-pict"[^>]*>(.*?)</span>', page, re.S).group(1)
        self.assertEqual(row.count("<svg"), 7)
        self.assertEqual(row.count('class="ig-icon is-on"'), 3)
        self.assertIn('aria-label="3 из 7"', page)


    def test_img_per_look(self):
        with tempfile.TemporaryDirectory() as tmp:
            for look, colour in (("strict", b"S"), ("bright", b"B")):
                (Path(tmp) / f"art-{look}").mkdir()
                (Path(tmp) / f"art-{look}" / "x.png").write_bytes(b"\x89PNG" + colour)
            source = PAGE.replace("<b>2</b>", '<i data-img="art-{look}/x.png"></i>')
            strict = build.build(source, "strict", False, Path(tmp))
            bright = build.build(source, "bright", False, Path(tmp))
        self.assertIn('<img class="ig-gen" src="data:image/png;base64,iVBOR1M=', strict)
        self.assertIn('<img class="ig-gen" src="data:image/png;base64,iVBOR0I=', bright)

    def test_img_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            page_dir = Path(tmp) / "page"
            page_dir.mkdir()
            (Path(tmp) / "secret.png").write_bytes(b"\x89PNG")
            (page_dir / "notes.txt").write_text("x", encoding="utf-8")
            for ref in ("../secret.png", str(Path(tmp) / "secret.png"), "notes.txt"):
                with self.subTest(ref=ref), self.assertRaisesRegex(build.BuildError, "в папке страницы"):
                    build.build(PAGE.replace("<b>2</b>", f'<i data-img="{ref}"></i>'), None, False, page_dir)

    def test_img_missing(self):
        with self.assertRaisesRegex(build.BuildError, "нет картинки «art-strict/none.png»"):
            build.build(PAGE.replace("<b>2</b>", '<i data-img="art-{look}/none.png"></i>'), None, False, Path(tempfile.gettempdir()))


class GenImageTest(unittest.TestCase):
    def test_batch_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / "prompts.tsv"
            table.write_text("# comment\nhero\tiso\ta key ring\n\nbg\tbackdrop\ta plant\t1536\t864\n", encoding="utf-8")
            rows = gen_image.read_batch(table)
        self.assertEqual([r["name"] for r in rows], ["hero", "bg"])
        self.assertEqual((rows[1]["width"], rows[1]["height"]), (1536, 864))
        self.assertNotIn("width", rows[0])

    def test_batch_bad_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / "prompts.tsv"
            table.write_text("hero\tcubist\ta key ring\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                gen_image.read_batch(table)

    def test_prompt_no_text(self):
        prompt = gen_image.prompt_for("a key ring", "iso", "night")
        self.assertIn("cyan and violet", prompt)
        self.assertIn("no text, no letters", prompt)

    def test_openrouter_request_and_saved_picture(self):
        import base64
        import io
        import json
        from unittest import mock

        sent = {}

        def fake_urlopen(req, timeout=0):
            sent["url"], sent["body"] = req.full_url, json.loads(req.data)
            sent["auth"] = req.get_header("Authorization")
            answer = {"data": [{"b64_json": base64.b64encode(b"png-bytes").decode()}], "usage": {"cost": 0.014}}
            return io.BytesIO(json.dumps(answer).encode())

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), \
                mock.patch.object(gen_image.urllib.request, "urlopen", fake_urlopen):
            out = Path(tmp) / "bg.png"
            cost = gen_image.generate_remote("a plant", out, 1536, 864, 11, "openrouter-flux2-klein-4b")
            self.assertEqual(out.read_bytes(), b"png-bytes")
        self.assertEqual(cost, "0.014 $")
        self.assertEqual(sent["url"], gen_image.OPENROUTER_URL)
        self.assertEqual(sent["body"]["model"], "black-forest-labs/flux.2-klein-4b")
        self.assertEqual(sent["body"]["aspect_ratio"], "16:9")
        self.assertEqual(sent["auth"], "Bearer k")

    def test_openrouter_needs_key(self):
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=True), tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, "OPENROUTER_API_KEY"):
                gen_image.generate_remote("a plant", Path(tmp) / "x.png", 768, 768, 1, "openrouter-flux2-klein-4b")

    def test_every_builtin_look_has_its_own_palette(self):
        looks = ["strict", "bright", "editorial", "blueprint", "night", "watercolor", "sketch", "pop", "steampunk", "fantasy"]
        palettes = [gen_image.palette_for(look) for look in looks]
        self.assertEqual(len(set(palettes)), len(looks))
        self.assertNotIn(gen_image.DEFAULT_PALETTE, palettes)

    def test_batch_bad_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / "prompts.tsv"
            table.write_text("../hero\tiso\ta key ring\n", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "без «/»"):
                gen_image.read_batch(table)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow lives in the image-generation environment")
    def test_cut_background(self):
        from PIL import Image

        img = Image.new("RGB", (40, 30), "white")
        img.paste((200, 30, 30), (10, 8, 30, 22))  # a red block on white
        img.paste((255, 255, 255), (18, 13, 22, 17))  # with a white hole inside
        cut = gen_image.cut_background(img)
        self.assertEqual(cut.size, (20, 14))  # trimmed to the block
        self.assertEqual(cut.getpixel((10, 6))[3], 255)  # the hole stays: it does not touch the edge
        self.assertEqual(cut.getpixel((0, 0)), (200, 30, 30, 255))


class BrandTest(unittest.TestCase):
    """A brand look is a folder outside the repo; the builder picks it up and inlines its files."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        brand = self.tmp / "acme"
        brand.mkdir()
        shutil.copy(SOURCE / "assets" / "fonts" / "onest-cyrillic-400-800.woff2", brand / "acme.woff2")
        (brand / "fonts.css").write_text(
            "@font-face {\n  font-family: 'Acme Sans';\n  font-style: normal;\n  src: url(acme.woff2) format('woff2');\n}\n", encoding="utf-8"
        )
        (brand / "mark.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2"><rect width="2" height="2"/></svg>', encoding="utf-8")
        (brand / "look.css").write_text('html[data-look="acme"] .ig-hero::after { content: ""; background: url(mark.svg); }\n', encoding="utf-8")
        (brand / "look.json").write_text(
            '{"name": "acme", "title": "Акме", "use": "проба", "fonts": ["Acme Sans"], "palette": "acme green"}', encoding="utf-8"
        )
        broken = self.tmp / "broken"
        broken.mkdir()
        (broken / "look.json").write_text("{not json", encoding="utf-8")
        build.load_brands([self.tmp])

    def tearDown(self):
        for table in (build.LOOK_FONTS, build.LOOK_NAMES, build.BRANDS, build.BRAND_USE, build.BRAND_PALETTE):
            table.pop("acme", None)
        shutil.rmtree(self.tmp)

    def test_brand_inlined(self):
        page = build.build(PAGE, "acme", False)
        self.assertEqual(build.LOOK_NAMES["acme"], "Акме")
        self.assertIn("font-family: 'Acme Sans'", page)
        self.assertIn("url(data:image/svg+xml;base64,", page)
        self.assertNotIn("url(mark.svg)", page)

    def test_brand_palette(self):
        self.assertIn("acme green", gen_image.prompt_for("a key ring", "iso", "acme"))

    def test_broken_skipped(self):
        self.assertNotIn("broken", build.LOOK_NAMES)
        self.assertIn("acme", build.LOOK_NAMES)  # one bad folder does not hide the others

    def test_brand_isolated(self):
        self.assertNotIn('data-look="acme"', build.build(PAGE, "strict", False))

    def test_brand_missing_file(self):
        (self.tmp / "acme" / "mark.svg").unlink()
        with self.assertRaisesRegex(build.BuildError, "нет файла «mark.svg»"):
            build.build(PAGE, "acme", False)


class SheetTest(unittest.TestCase):
    def test_caption(self):
        source = PAGE.replace("<title>Проба</title>", '<meta name="ig-type" content="Дерево решений"><title>Проба</title>')
        self.assertEqual(sheet.page_caption(source), ("Дерево решений", "Проба · строгий"))

    def test_caption_fallback(self):
        self.assertEqual(sheet.page_caption(PAGE)[0], "Проба")

    def test_sheet_grid(self):
        tiles = [("Строгий", "руководство", b"png1"), ("Эскиз", "замысел", b"png2"), ("Поп", "анонсы", b"png3")]
        page = sheet.sheet_html("Лист", "подзаголовок", tiles, 3, 1500, 600)
        self.assertEqual(page.count("<figure>"), 3)
        self.assertIn("grid-template-columns: repeat(3, 600px)", page)
        self.assertIn('height="703"', page)  # 600 * 1500 / 1280, rounded
        self.assertIn("<b>Эскиз</b><span>замысел</span>", page)

    def test_use_lines(self):
        self.assertEqual(set(sheet.LOOK_USE), set(build.LOOK_NAMES))


@unittest.skipUnless(Path(build.CHROME).exists(), "Google Chrome is not installed")
class ChromeCheckTest(unittest.TestCase):
    def shoot(self, source: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text(build.build(source, None, False), encoding="utf-8")
            problems = build.shoot(page, Path(tmp) / "page.png", 1280)
            self.assertGreater((Path(tmp) / "page.png").stat().st_size, 10_000)
            return problems

    def test_clean_page(self):
        self.assertEqual(self.shoot(PAGE), [])

    def test_latin_page(self):
        # Fonts of the look are checked even when the page sets no Cyrillic in them.
        latin = re.sub("[А-Яа-яЁё]", "x", PAGE)
        self.assertEqual(self.shoot(latin), [])

    def test_phone_overflow(self):
        wide = PAGE.replace("<b>2</b>", '<b style="white-space:nowrap">2 сервера и ещё очень длинная подпись без переносов</b>')
        problems = self.shoot(wide)
        self.assertTrue(any("на телефоне" in p for p in problems), problems)
        self.assertFalse(any("кириллица" in p for p in problems), problems)


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "lib"
        self.page = base / "page"
        self.page.mkdir()
        (self.page / "truck.png").write_bytes(b"truck-bytes")
        (self.page / "keys.png").write_bytes(b"keys-bytes")
        # older table order (name, style, width, height, what) next to the current one
        (self.page / "prompts.tsv").write_text(
            "truck\tiso\t768\t768\ta delivery truck\nkeys\tflat\ta key ring\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_reads_both_table_orders_and_keeps_one_copy(self):
        first = library.add(self.page, "teal", None, "page 19.10", self.root)
        again = library.add(self.page, "teal", None, "page 19.10", self.root)
        rows = {r["file"]: r for r in library.read_catalog(self.root)}
        self.assertEqual(sorted(rows), ["teal/keys.png", "teal/truck.png"])
        self.assertEqual(rows["teal/truck.png"]["what"], "a delivery truck")
        self.assertEqual(rows["teal/keys.png"]["style"], "flat")
        self.assertEqual(len(first), 2)
        self.assertTrue(all(line.startswith("уже есть") for line in again), again)

    def test_same_name_other_picture_gets_new_name(self):
        library.add(self.page, "teal", None, "", self.root)
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        (other / "truck.png").write_bytes(b"another truck")
        library.add(other, "teal", None, "", self.root)
        self.assertTrue((self.root / "teal" / "truck-2.png").exists())
        self.assertEqual((self.root / "teal" / "truck.png").read_bytes(), b"truck-bytes")

    def test_find_by_russian_word_with_other_ending_and_look_first(self):
        library.add(self.page, "teal", None, "", self.root)
        library.add(self.page, "red", None, "", self.root)  # same bytes: skipped, kept once
        library.tag(["teal/truck", "грузовик доставка ЭПД", "teal/keys", "ключи доступ"], self.root)
        hits = library.find(["грузовика"], self.root)
        self.assertEqual([r["file"] for _, r in hits], ["teal/truck.png"])
        self.assertEqual(library.find(["самолёт"], self.root), [])

    def test_take_copies_and_does_not_overwrite(self):
        library.add(self.page, "teal", None, "", self.root)
        dest = Path(self.tmp.name) / "new" / "art-teal" / "hero.png"
        library.take("teal/truck", dest, self.root)
        self.assertEqual(dest.read_bytes(), b"truck-bytes")
        with self.assertRaisesRegex(SystemExit, "не перезаписываю"):
            library.take("teal/keys", dest, self.root)
        with self.assertRaisesRegex(SystemExit, "нет такой картинки"):
            library.take("teal/plane", Path(self.tmp.name) / "x.png", self.root)

    def test_sheet_links_pictures_and_escapes_tags(self):
        library.add(self.page, "teal", None, "", self.root)
        library.tag(["teal/keys", "ключи <доступ>"], self.root)
        page = library.sheet(self.root).read_text(encoding="utf-8")
        self.assertIn('src="teal/keys.png"', page)
        self.assertIn("ключи &lt;доступ&gt;", page)
        self.assertIn("teal · 2", page)


if __name__ == "__main__":
    unittest.main()
