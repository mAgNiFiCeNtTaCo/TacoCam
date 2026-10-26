"""Draws the Taco Cam PC icon (the iPhone app's orange camera on a rounded tile) into pc/tacocam/assets/.

Writes taco-cam.ico (16-256 px, small sizes drawn with a bigger, simpler camera so they stay readable).
Run from anywhere: python pc/tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "tacocam" / "assets"
SS = 8  # supersampling for smooth edges

ORANGE = (255, 148, 32)
DEEP = (214, 96, 10)
WHITE = (255, 255, 255)
CREAM = (255, 226, 160)

ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def draw(size):
    s = size * SS
    small = size <= 32
    # Tile: orange, darker toward the bottom, rounded corners, transparent outside.
    tile = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    shade = Image.new("RGBA", (s, s))
    sd = ImageDraw.Draw(shade)
    for y in range(s):
        t = y / s
        sd.line([(0, y), (s, y)], fill=tuple(int(ORANGE[i] * (1 - 0.25 * t) + DEEP[i] * 0.25 * t) for i in range(3)) + (255,))
    mask = Image.new("L", (s, s), 0)
    margin = 0 if small else s * 0.03
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, s - margin, s - margin], radius=s * 0.2, fill=255)
    tile.paste(shade, (0, 0), mask)

    d = ImageDraw.Draw(tile)
    # Same camera as ios/tools/make_icon.py, in 1024 units; small icons zoom the camera to fill more of the tile.
    zoom = 1.28 if small else 1.08

    def p(x, y):
        return (512 + (x - 512) * zoom) * s / 1024, (540 + (y - 540) * zoom) * s / 1024

    def r(v):
        return v * zoom * s / 1024

    x0, y0 = p(170, 330)
    x1, y1 = p(854, 780)
    d.rounded_rectangle([x0, y0, x1, y1], radius=r(90), fill=WHITE)
    x0, y0 = p(360, 245)
    x1, y1 = p(600, 360)
    d.rounded_rectangle([x0, y0, x1, y1], radius=r(40), fill=WHITE)
    cx, cy = p(512, 555)
    rings = ((185, ORANGE), (150, DEEP), (118, CREAM), (70, ORANGE)) if not small else ((185, ORANGE), (130, CREAM), (70, ORANGE))
    for rad, col in rings:
        d.ellipse([cx - r(rad), cy - r(rad), cx + r(rad), cy + r(rad)], fill=col)
    if size >= 24:
        gx, gy = p(472, 500)
        d.ellipse([gx - r(20), gy - r(20), gx + r(20), gy + r(20)], fill=WHITE)
    if size >= 40:
        lx, ly = p(750, 420)
        d.ellipse([lx - r(30), ly - r(30), lx + r(30), ly + r(30)], fill=ORANGE)
    return tile.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    images = [draw(n) for n in ICO_SIZES]
    big = images[-1]
    big.save(OUT / "taco-cam.ico", sizes=[(n, n) for n in ICO_SIZES], append_images=images[:-1])
    print("icon written to", OUT)


if __name__ == "__main__":
    main()
