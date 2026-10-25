"""Draws the Taco Cam app icon (taco-orange background, white camera glyph) into the asset catalog.

Run from anywhere: python ios/tools/make_icon.py
"""
import json
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "TacoCam", "Assets.xcassets", "AppIcon.appiconset")
SIZE = 1024
SS = 4  # supersampling for smooth edges

ORANGE = (255, 148, 32)
DEEP = (214, 96, 10)
WHITE = (255, 255, 255)
CREAM = (255, 226, 160)


def draw(size):
    s = size * SS
    img = Image.new("RGB", (s, s), ORANGE)
    d = ImageDraw.Draw(img)

    # Soft diagonal shade: darker toward the bottom.
    for y in range(s):
        t = y / s
        c = tuple(int(ORANGE[i] * (1 - 0.25 * t) + DEEP[i] * 0.25 * t) for i in range(3))
        d.line([(0, y), (s, y)], fill=c)

    u = s / 1024.0
    # Camera body.
    body = [170 * u, 330 * u, 854 * u, 780 * u]
    d.rounded_rectangle(body, radius=90 * u, fill=WHITE)
    # Viewfinder bump.
    d.rounded_rectangle([360 * u, 245 * u, 600 * u, 360 * u], radius=40 * u, fill=WHITE)
    # Lens: orange ring, cream glass, white glint.
    cx, cy = 512 * u, 555 * u
    for r, col in ((185, ORANGE), (150, DEEP), (118, CREAM), (70, ORANGE)):
        d.ellipse([cx - r * u, cy - r * u, cx + r * u, cy + r * u], fill=col)
    d.ellipse([cx - 60 * u, cy - 75 * u, cx - 20 * u, cy - 35 * u], fill=WHITE)
    # Little light.
    d.ellipse([720 * u, 390 * u, 780 * u, 450 * u], fill=ORANGE)

    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    draw(SIZE).save(os.path.join(OUT, "icon-1024.png"), optimize=True)
    contents = {
        "images": [
            {"filename": "icon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}
        ],
        "info": {"author": "xcode", "version": 1},
    }
    with open(os.path.join(OUT, "Contents.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(contents, f, indent=2)
        f.write("\n")
    with open(os.path.join(OUT, "..", "Contents.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"info": {"author": "xcode", "version": 1}}, f, indent=2)
        f.write("\n")
    print("icon written to", os.path.normpath(OUT))


if __name__ == "__main__":
    main()
