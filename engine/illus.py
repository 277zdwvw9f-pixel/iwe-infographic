#!/usr/bin/env python3
"""Generate the isometric illustrations the infographic pages embed as <i data-illus="name">.

Each picture is drawn from a few primitives (iso box, cylinder, sheet) and flat shapes.
Colours are not baked in: shapes carry classes (f1-f3 = light/mid/dark of the element's
tone, g1-g3 = the second tone, o = outline, ln = line), and looks.css paints them, so one
drawing fits every look. Run after changing a scene; the SVG files are committed.
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parent / "assets" / "illus"
COS30 = math.cos(math.radians(30))


class Scene:
    """Collects SVG elements and their bounding box; the viewBox is fitted at the end."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.xs: list[float] = []
        self.ys: list[float] = []

    def _track(self, points) -> None:
        for x, y in points:
            self.xs.append(x)
            self.ys.append(y)

    def poly(self, points, cls: str) -> None:
        self._track(points)
        self.parts.append(f'<polygon points="{fmt(points)}" class="{cls}"/>')

    def line(self, a, b, cls: str = "ln") -> None:
        self._track([a, b])
        self.parts.append(f'<path d="M{a[0]:.1f} {a[1]:.1f}L{b[0]:.1f} {b[1]:.1f}" class="{cls}"/>')

    def path(self, d: str, cls: str, bounds) -> None:
        self._track(bounds)
        self.parts.append(f'<path d="{d}" class="{cls}"/>')

    def circle(self, c, r: float, cls: str) -> None:
        self._track([(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])
        self.parts.append(f'<circle cx="{c[0]:.1f}" cy="{c[1]:.1f}" r="{r:.1f}" class="{cls}"/>')

    def ellipse(self, c, rx: float, ry: float, cls: str) -> None:
        self._track([(c[0] - rx, c[1] - ry), (c[0] + rx, c[1] + ry)])
        self.parts.append(f'<ellipse cx="{c[0]:.1f}" cy="{c[1]:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" class="{cls}"/>')

    def svg(self, pad: float = 6) -> str:
        x0, y0 = min(self.xs) - pad, min(self.ys) - pad
        w, h = max(self.xs) - x0 + pad, max(self.ys) - y0 + pad
        body = "".join(self.parts)
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {w:.0f} {h:.0f}">{body}</svg>\n'


def fmt(points) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def P(x: float, y: float, z: float) -> tuple[float, float]:
    """Isometric projection: x to the lower right, y to the lower left, z up."""
    return ((x - y) * COS30, (x + y) * 0.5 - z)


def box(s: Scene, x, y, z, w, d, h, tone: str = "f") -> None:
    s.poly([P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)], f"{tone}2 o")
    s.poly([P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)], f"{tone}3 o")
    s.poly([P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)], f"{tone}1 o")


def server(s: Scene, x, y, z, w, d, h, rows: int = 3, tone: str = "f") -> None:
    box(s, x, y, z, w, d, h, tone)
    for k in range(rows):
        zz = z + h * (k + 0.5) / rows
        s.line(P(x + 6, y + d, zz), P(x + w * 0.62, y + d, zz), "ln")
        s.circle(P(x + w - 9, y + d, zz), 2.6, "led")


def cylinder(s: Scene, x, y, z, r, h, tone: str = "f") -> None:
    rx, ry = r * 1.2247, r * 0.7071
    bx, by = P(x, y, z)
    tx, ty = P(x, y, z + h)
    d = f"M{tx - rx:.1f} {ty:.1f}L{bx - rx:.1f} {by:.1f}A{rx:.1f} {ry:.1f} 0 0 0 {bx + rx:.1f} {by:.1f}L{tx + rx:.1f} {ty:.1f}Z"
    s.path(d, f"{tone}2 o", [(bx - rx, by + ry), (tx + rx, ty - ry)])
    s.ellipse((tx, ty), rx, ry, f"{tone}1 o")


def db(s: Scene, x, y, z, r, discs: int = 3, tone: str = "f") -> None:
    for k in range(discs):
        cylinder(s, x, y, z + k * (r * 0.62), r, r * 0.5, tone)


def sheet(s: Scene, x, y, z, w, d, lines: int = 4, tone: str = "f") -> None:
    box(s, x, y, z, w, d, 3, tone)
    for k in range(lines):
        yy = y + d * (k + 1) / (lines + 1)
        s.line(P(x + 8, yy, z + 3), P(x + w * (0.85 if k % 2 else 0.62), yy, z + 3), "ln")


def flat_doc(s: Scene, cx, cy, w=26, h=34, tone: str = "g") -> None:
    f = 7
    pts = [(cx - w / 2, cy - h / 2), (cx + w / 2 - f, cy - h / 2), (cx + w / 2, cy - h / 2 + f), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
    s.poly(pts, f"{tone}1 o")
    for k in range(3):
        yy = cy - h / 2 + 12 + k * 7
        s.line((cx - w / 2 + 5, yy), (cx + w / 2 - 6, yy), "ln")


def arrow(s: Scene, a, b, cls: str = "ln a") -> None:
    s.line(a, b, cls)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for side in (-1, 1):
        t = ang + math.pi + side * 0.5
        s.line(b, (b[0] + 9 * math.cos(t), b[1] + 9 * math.sin(t)), cls)


# ---------- scenes ----------


def scene_servers() -> Scene:
    s = Scene()
    for k in range(3):
        server(s, 0, 0, k * 24, 72, 48, 20)
    db(s, 98, 34, 0, 17, tone="g")
    box(s, -18, 78, 0, 22, 22, 22, "g")
    return s


def scene_server_pair() -> Scene:
    s = Scene()
    server(s, 0, 0, 0, 38, 38, 92, rows=5)
    server(s, 92, 0, 0, 38, 38, 92, rows=5, tone="g")
    a, b = P(40, 30, 58), P(92, 30, 58)
    arrow(s, a, b, "ln a dash")
    return s


def scene_database() -> Scene:
    s = Scene()
    db(s, 0, 0, 0, 36, discs=3)
    return s


def scene_documents() -> Scene:
    s = Scene()
    for k in range(3):
        sheet(s, 0, 0, k * 7, 64, 82, lines=4 if k == 2 else 0)
    cx, cy = P(32, 41, 10)
    for dx, dy in ((-92, -46), (92, -46), (-92, 44), (92, 44)):
        s.line((cx + dx * 0.55, cy + dy * 0.55), (cx + dx * 0.82, cy + dy * 0.82), "ln dash")
        flat_doc(s, cx + dx, cy + dy)
    return s


def scene_hub() -> Scene:
    s = Scene()
    nodes = [(0, 0, 160), (-70, 40, 80), (40, -40, 80), (0, 0, 0)]
    centres = []
    for x, y, z in nodes:
        centres.append(P(x + 18, y + 18, z + 18))
    for i in range(len(centres)):
        for j in range(i + 1, len(centres)):
            s.line(centres[i], centres[j], "ln thick")
    for (x, y, z), tone in zip(nodes, ("f", "g", "f", "g")):
        box(s, x, y, z, 36, 36, 36, tone)
    return s


def scene_chart() -> Scene:
    s = Scene()
    box(s, 0, 0, 0, 110, 70, 6, "g")
    for k, h in enumerate((34, 58, 86, 48)):
        box(s, 10 + k * 24, 28, 6, 16, 16, h, "f" if k % 2 == 0 else "g")
    return s


def scene_cloud() -> Scene:
    s = Scene()
    d = "M30 62C14 62 6 50 10 39C13 30 22 26 30 28C33 15 45 7 59 9C72 11 81 21 82 33C94 32 104 41 103 52C102 59 96 62 89 62Z"
    s.path(d, "f1 o", [(6, 7), (104, 62)])
    s.circle((56, 44), 11, "g2 o")
    arrow(s, (56, 64), (56, 96), "ln a")
    arrow(s, (56, 64), (20, 100), "ln a")
    arrow(s, (56, 64), (92, 100), "ln a")
    for cx in (14, 56, 98):
        s.circle((cx, 110), 12, "g1 o")
    return s


def scene_key_lock() -> Scene:
    s = Scene()
    s.circle((40, 40), 26, "g2 o")
    s.circle((40, 40), 9, "w o")
    s.path("M58 58L104 104L96 112L88 104L82 110L74 102L80 96L50 66Z", "g2 o", [(50, 58), (104, 112)])
    s.path("M118 44v-12a18 18 0 0 1 36 0v12", "ln thick", [(118, 14), (154, 44)])
    s.path("M108 44h56a6 6 0 0 1 6 6v36a6 6 0 0 1 -6 6h-56a6 6 0 0 1 -6 -6v-36a6 6 0 0 1 6 -6Z", "f2 o", [(102, 44), (170, 92)])
    s.circle((136, 63), 6, "k")
    s.line((136, 66), (136, 78), "ln thick")
    return s


def scene_shield() -> Scene:
    s = Scene()
    s.path("M60 6L108 22V58C108 88 86 108 60 118C34 108 12 88 12 58V22Z", "f2 o", [(12, 6), (108, 118)])
    s.path("M60 18L96 30V58C96 81 80 97 60 105Z", "f3", [(60, 18), (96, 105)])
    s.path("M38 60L54 76L84 44", "ln w-stroke", [(38, 44), (84, 76)])
    return s


def scene_people() -> Scene:
    s = Scene()
    for cx, r, tone in ((30, 14, "g"), (110, 14, "g"), (70, 18, "f")):
        top = 40 if r == 18 else 50
        s.circle((cx, top), r, f"{tone}1 o")
        w = r * 2.4
        base = top + r * 3.4
        s.path(
            f"M{cx - w:.1f} {base:.1f}C{cx - w:.1f} {top + r * 1.4:.1f} {cx + w:.1f} {top + r * 1.4:.1f} {cx + w:.1f} {base:.1f}Z",
            f"{tone}2 o",
            [(cx - w, top + r), (cx + w, base)],
        )
    return s


def scene_factory() -> Scene:
    s = Scene()
    cylinder(s, 20, 10, 0, 7, 92, "g")
    cylinder(s, 46, 10, 0, 7, 76, "g")
    box(s, 0, 24, 0, 120, 56, 38)
    for k in range(5):
        x = 10 + k * 22
        s.poly([P(x, 80, 10), P(x + 12, 80, 10), P(x + 12, 80, 24), P(x, 80, 24)], "k")
    sx, sy = P(20, 10, 92)  # top of the taller chimney
    for dx, dy, r in ((0, -12, 8), (10, -26, 11), (26, -36, 8)):
        s.circle((sx + dx, sy + dy), r, "smoke")
    return s


def scene_warning() -> Scene:
    s = Scene()
    box(s, -20, -20, 0, 96, 96, 6, "g")
    s.line(P(0, 76, 6), P(30, 46, 6), "ln a")
    s.line(P(30, 46, 6), P(18, 30, 6), "ln a")
    server(s, 10, 10, 6, 40, 40, 96, rows=5)
    tx, ty = P(62, 70, 10)
    s.path(f"M{tx:.1f} {ty - 46:.1f}L{tx + 28:.1f} {ty:.1f}L{tx - 28:.1f} {ty:.1f}Z", "warn o", [(tx - 28, ty - 46), (tx + 28, ty)])
    s.line((tx, ty - 32), (tx, ty - 16), "ln thick")
    s.circle((tx, ty - 8), 2.6, "k")
    return s


def scene_money() -> Scene:
    s = Scene()
    sheet(s, -10, 40, 0, 96, 56, lines=0, tone="g")
    s.ellipse(P(38, 68, 3), 16, 9, "g2 o")
    for (x, y), n in (((10, 0), 5), ((44, -4), 8), ((78, 6), 3)):
        for k in range(n):
            cylinder(s, x, y, k * 6, 14, 5)
    return s


SCENES = {
    "servers": scene_servers,
    "server-pair": scene_server_pair,
    "database": scene_database,
    "documents": scene_documents,
    "hub": scene_hub,
    "chart": scene_chart,
    "cloud": scene_cloud,
    "key-lock": scene_key_lock,
    "shield": scene_shield,
    "people": scene_people,
    "factory": scene_factory,
    "warning": scene_warning,
    "money": scene_money,
}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in SCENES.items():
        (OUT / f"{name}.svg").write_text(make().svg(), encoding="utf-8")
    print(f"illustrations: {len(SCENES)} -> {OUT}")
