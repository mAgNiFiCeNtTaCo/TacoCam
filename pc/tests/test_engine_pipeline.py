"""Picture pipeline: rotate / mirror / flip / fit / crop / stretch, the tap_focus inverse, the waiting card."""
import itertools
import os
import random
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tacocam import pipeline  # noqa: E402
from tacocam.pipeline import Transform  # noqa: E402

COMBOS = list(itertools.product([0, 90, 180, 270], [False, True], [False, True], ["crop", "fit", "stretch"]))


def quadrant_image(w=160, h=90):
    """Top-left red, top-right green, bottom-left blue, bottom-right white."""
    img = np.zeros((h, w, 3), np.uint8)
    img[: h // 2, : w // 2] = (255, 0, 0)
    img[: h // 2, w // 2:] = (0, 255, 0)
    img[h // 2:, : w // 2] = (0, 0, 255)
    img[h // 2:, w // 2:] = (255, 255, 255)
    return img


def color_at(img, x, y):
    h, w = img.shape[:2]
    px = img[int(y * (h - 1)), int(x * (w - 1))].astype(int)
    names = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "white": (255, 255, 255),
             "black": (0, 0, 0)}
    return min(names, key=lambda n: sum((a - b) ** 2 for a, b in zip(px, names[n])))


@pytest.mark.parametrize("rotation,expected", [
    (0, ("red", "green", "blue", "white")),
    (90, ("blue", "red", "white", "green")),       # clockwise: bottom-left goes to top-left
    (180, ("white", "blue", "green", "red")),
    (270, ("green", "white", "red", "blue")),
])
def test_rotation_clockwise(rotation, expected):
    src = quadrant_image()
    ow, oh = (90, 160) if rotation in (90, 270) else (160, 90)
    out = Transform(160, 90, ow, oh, rotation, fit="stretch").apply(src)
    assert out.shape == (oh, ow, 3)
    corners = tuple(color_at(out, x, y) for x, y in ((0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9)))
    assert corners == expected


def test_mirror_and_flip():
    src = quadrant_image()
    m = Transform(160, 90, 160, 90, 0, mirror=True).apply(src)
    assert (color_at(m, 0.1, 0.1), color_at(m, 0.9, 0.1)) == ("green", "red")
    f = Transform(160, 90, 160, 90, 0, flip=True).apply(src)
    assert (color_at(f, 0.1, 0.1), color_at(f, 0.1, 0.9)) == ("blue", "red")
    mf = Transform(160, 90, 160, 90, 0, mirror=True, flip=True).apply(src)
    assert color_at(mf, 0.1, 0.1) == "white"
    # mirror applies AFTER rotation: rotate 90 then mirror -> top-left is what was top-right after turning
    rm = Transform(160, 90, 90, 160, 90, mirror=True, fit="stretch").apply(src)
    assert color_at(rm, 0.1, 0.1) == "red"


def test_fit_adds_black_bars():
    src = quadrant_image(160, 90)
    out = Transform(160, 90, 1080, 1920, 0, fit="fit").apply(src)    # landscape into portrait
    assert out.shape == (1920, 1080, 3)
    assert color_at(out, 0.5, 0.05) == "black" and color_at(out, 0.5, 0.95) == "black"
    assert color_at(out, 0.1, 0.4) == "red" and color_at(out, 0.9, 0.6) == "white"


def test_crop_fills_and_cuts():
    src = quadrant_image(160, 90)
    out = Transform(160, 90, 1080, 1920, 0, fit="crop").apply(src)   # only the middle columns remain
    assert out.shape == (1920, 1080, 3)
    assert not (out == 0).all(axis=2).any()
    assert color_at(out, 0.05, 0.05) == "red" and color_at(out, 0.95, 0.05) == "green"


def test_stretch_uses_whole_frame():
    src = quadrant_image(160, 90)
    out = Transform(160, 90, 300, 300, 0, fit="stretch").apply(src)
    assert out.shape == (300, 300, 3)
    assert color_at(out, 0.02, 0.02) == "red" and color_at(out, 0.98, 0.98) == "white"


def test_real_sizes_and_out_buffer():
    src = np.random.randint(0, 255, (2160, 3840, 3), np.uint8)
    for w, h in ((1920, 1080), (1080, 1920), (3840, 2160), (2160, 3840), (1280, 720)):
        for rot in (0, 90):
            out = Transform(3840, 2160, w, h, rot).apply(src)
            assert out.shape == (h, w, 3) and out.flags["C_CONTIGUOUS"]
    buf = np.empty((720, 1280, 3), np.uint8)
    assert Transform(3840, 2160, 1280, 720).apply(src, out=buf) is buf


def test_wrong_frame_size_raises():
    with pytest.raises(ValueError):
        Transform(1920, 1080, 1280, 720).apply(np.zeros((720, 1280, 3), np.uint8))


@pytest.mark.parametrize("rotation,mirror,flip,fit", COMBOS)
def test_tap_inverse_property(rotation, mirror, flip, fit):
    rnd = random.Random(hash((rotation, mirror, flip, fit)) & 0xFFFF)
    for src, out in (((1920, 1080), (1920, 1080)), ((1920, 1080), (1080, 1920)), ((3840, 2160), (1280, 720)),
                     ((1280, 720), (2160, 3840))):
        tr = Transform(*src, *out, rotation, mirror, flip, fit)
        for _ in range(100):
            u, v = rnd.random(), rnd.random()
            x, y = tr.sensor_to_out(u, v)
            if 0 <= x <= 1 and 0 <= y <= 1:          # visible (crop cuts some points off)
                bu, bv = tr.out_to_sensor(x, y)
                assert abs(bu - u) < 1e-9 and abs(bv - v) < 1e-9
            # and the other way round for every output point
            x, y = rnd.random(), rnd.random()
            u2, v2 = tr.out_to_sensor(x, y, clamp=False)
            x2, y2 = tr.sensor_to_out(u2, v2)
            assert abs(x2 - x) < 1e-9 and abs(y2 - y) < 1e-9


@pytest.mark.parametrize("rotation,mirror,flip,fit", COMBOS)
def test_pixels_land_where_the_mapping_says(rotation, mirror, flip, fit):
    """A bright dot drawn at a sensor point appears in the output at sensor_to_out() of that point."""
    sw, sh, ow, oh = 320, 180, 200, 300
    tr = Transform(sw, sh, ow, oh, rotation, mirror, flip, fit)
    for u, v in ((0.3, 0.4), (0.6, 0.7), (0.5, 0.5)):
        src = np.zeros((sh, sw, 3), np.uint8)
        cx, cy = int(u * sw), int(v * sh)
        src[cy - 3:cy + 4, cx - 3:cx + 4] = 255
        out = tr.apply(src)
        x, y = tr.sensor_to_out((cx + 0.5) / sw, (cy + 0.5) / sh)
        if not (0.05 < x < 0.95 and 0.05 < y < 0.95):
            continue
        ys, xs = np.nonzero(out[..., 0] > 100)
        assert len(xs), "dot vanished"
        assert abs(xs.mean() / ow - x) < 0.03 and abs(ys.mean() / oh - y) < 0.03


def test_tap_on_black_bar_clamps_to_picture():
    tr = Transform(1920, 1080, 1080, 1920, 0, fit="fit")
    u, v = tr.out_to_sensor(0.5, 0.01)
    assert v == 0.0 and abs(u - 0.5) < 1e-9


def test_effective_rotation_and_sizes():
    assert pipeline.effective_rotation("auto", 90) == 90
    assert pipeline.effective_rotation("auto", None) == 0
    assert pipeline.effective_rotation(180, 90) == 180
    assert pipeline.effective_rotation("auto", 450) == 90
    assert pipeline.effective_rotation("auto", 45) == 0
    assert pipeline.parse_size("1080x1920") == (1080, 1920)
    assert pipeline.parse_size("bad") == (1920, 1080)


@pytest.mark.parametrize("kind", ["usb", "no_app", "background", "wifi", "wifi_nohost", "error"])
def test_card(kind):
    img = pipeline.make_card(1280, 720, kind, host="192.168.1.20", error="Something broke")
    assert img.shape == (720, 1280, 3) and img.dtype == np.uint8
    assert img.std() > 5                     # not a blank picture
    assert pipeline.make_card(1280, 720, kind, host="192.168.1.20", error="Something broke") is img  # cached
    portrait = pipeline.make_card(1080, 1920, kind, host="x", error="e")
    assert portrait.shape == (1920, 1080, 3)


def test_card_texts():
    title, lines = pipeline.card_lines("background")
    assert "Taco Cam app is in the background - open it on the iPhone." in lines
    title, lines = pipeline.card_lines("usb")
    assert any("USB" in line for line in lines) and any("Open the Taco Cam app" in line for line in lines)
    title, lines = pipeline.card_lines("wifi", host="10.0.0.5")
    assert any("10.0.0.5" in line for line in lines)


def test_scale_to_fit():
    img = np.zeros((1080, 1920, 3), np.uint8)
    assert pipeline.scale_to_fit(img, 640, 640).shape == (360, 640, 3)
    assert pipeline.scale_to_fit(img, 4000, 4000).shape == (1080, 1920, 3)
