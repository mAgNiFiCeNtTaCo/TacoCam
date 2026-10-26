"""Turns decoded phone frames into the virtual camera picture (CONTRACT sections 3 and 6).

Order: rotate (clockwise) -> mirror (left-right) / flip (upside-down) -> fit/crop/stretch to the output size.
All geometry is in normalised coordinates (0..1), so tap_focus can map an output point back to the
sensor frame exactly through the same steps.
"""
import threading

import cv2
import numpy as np

ROTATIONS = (0, 90, 180, 270)
FITS = ("crop", "fit", "stretch")


def parse_size(text, default=(1920, 1080)):
    try:
        w, h = (int(v) for v in str(text).lower().split("x"))
        if 16 <= w <= 8192 and 16 <= h <= 8192:
            return w, h
    except (TypeError, ValueError):
        pass
    return default


def effective_rotation(rotate, rotation_hint):
    """pc.rotate "auto" uses the phone's STATE rotation_hint; otherwise the fixed setting."""
    value = rotation_hint if rotate == "auto" else rotate
    try:
        value = int(value) % 360
    except (TypeError, ValueError):
        return 0
    return value if value in ROTATIONS else 0


# --- normalised point maps -------------------------------------------------------------------------

def rotate_point(u, v, rotation):
    """A point of the frame -> the same point after turning the frame `rotation` degrees clockwise."""
    if rotation == 90:
        return 1.0 - v, u
    if rotation == 180:
        return 1.0 - u, 1.0 - v
    if rotation == 270:
        return v, 1.0 - u
    return u, v


def unrotate_point(u, v, rotation):
    if rotation == 90:
        return v, 1.0 - u
    if rotation == 180:
        return 1.0 - u, 1.0 - v
    if rotation == 270:
        return 1.0 - v, u
    return u, v


class Transform:
    """Geometry from one source size + settings to one output size (immutable)."""

    def __init__(self, src_w, src_h, out_w, out_h, rotation=0, mirror=False, flip=False, fit="crop"):
        self.src_w, self.src_h = int(src_w), int(src_h)
        self.out_w, self.out_h = int(out_w), int(out_h)
        self.rotation = rotation if rotation in ROTATIONS else 0
        self.mirror, self.flip = bool(mirror), bool(flip)
        self.fit = fit if fit in FITS else "crop"
        turned = self.rotation in (90, 270)
        rw, rh = (self.src_h, self.src_w) if turned else (self.src_w, self.src_h)
        self.rot_w, self.rot_h = rw, rh
        ow, oh = self.out_w, self.out_h
        if self.fit == "stretch":
            sw, sh = float(ow), float(oh)
        else:
            s = max(ow / rw, oh / rh) if self.fit == "crop" else min(ow / rw, oh / rh)
            sw, sh = rw * s, rh * s
        # The rotated (and mirrored) picture, scaled to sw x sh, has its top-left corner at (ox, oy).
        self.scaled_w, self.scaled_h = sw, sh
        self.off_x, self.off_y = (ow - sw) / 2.0, (oh - sh) / 2.0

    def key(self):
        return (self.src_w, self.src_h, self.out_w, self.out_h, self.rotation, self.mirror, self.flip, self.fit)

    # sensor (u, v) -> output (x, y), all 0..1
    def sensor_to_out(self, u, v):
        a, b = rotate_point(u, v, self.rotation)
        if self.mirror:
            a = 1.0 - a
        if self.flip:
            b = 1.0 - b
        return ((self.off_x + a * self.scaled_w) / self.out_w,
                (self.off_y + b * self.scaled_h) / self.out_h)

    def out_to_sensor(self, x, y, clamp=True):
        a = (x * self.out_w - self.off_x) / self.scaled_w
        b = (y * self.out_h - self.off_y) / self.scaled_h
        if clamp:  # a tap on a black bar focuses on the nearest edge of the picture
            a, b = min(max(a, 0.0), 1.0), min(max(b, 0.0), 1.0)
        if self.mirror:
            a = 1.0 - a
        if self.flip:
            b = 1.0 - b
        return unrotate_point(a, b, self.rotation)

    def _source_rect(self):
        """Part of the source frame that is visible (pixels: x0, y0, x1, y1) and where it lands
        in the output (pixels: dx0, dy0, dx1, dy1)."""
        # Visible part of the scaled picture, in its own 0..1 coordinates
        a0 = max(0.0, -self.off_x / self.scaled_w)
        a1 = min(1.0, (self.out_w - self.off_x) / self.scaled_w)
        b0 = max(0.0, -self.off_y / self.scaled_h)
        b1 = min(1.0, (self.out_h - self.off_y) / self.scaled_h)
        corners = []
        for a in (a0, a1):
            for b in (b0, b1):
                aa = 1.0 - a if self.mirror else a
                bb = 1.0 - b if self.flip else b
                corners.append(unrotate_point(aa, bb, self.rotation))
        us = [c[0] for c in corners]
        vs = [c[1] for c in corners]
        x0 = int(round(min(us) * self.src_w))
        x1 = int(round(max(us) * self.src_w))
        y0 = int(round(min(vs) * self.src_h))
        y1 = int(round(max(vs) * self.src_h))
        x0, y0 = max(0, min(x0, self.src_w - 1)), max(0, min(y0, self.src_h - 1))
        x1, y1 = max(x0 + 1, min(x1, self.src_w)), max(y0 + 1, min(y1, self.src_h))
        dx0 = int(round(self.off_x + a0 * self.scaled_w))
        dx1 = int(round(self.off_x + a1 * self.scaled_w))
        dy0 = int(round(self.off_y + b0 * self.scaled_h))
        dy1 = int(round(self.off_y + b1 * self.scaled_h))
        dx0, dy0 = max(0, dx0), max(0, dy0)
        dx1, dy1 = min(self.out_w, max(dx0 + 1, dx1)), min(self.out_h, max(dy0 + 1, dy1))
        return (x0, y0, x1, y1), (dx0, dy0, dx1, dy1)

    def apply(self, frame, out=None):
        """frame: HxWx3 uint8 of size src -> new (or `out`) out_h x out_w x 3 uint8."""
        h, w = frame.shape[:2]
        if (w, h) != (self.src_w, self.src_h):
            raise ValueError(f"frame is {w}x{h}, transform expects {self.src_w}x{self.src_h}")
        (x0, y0, x1, y1), (dx0, dy0, dx1, dy1) = self._source_rect()
        dw, dh = dx1 - dx0, dy1 - dy0
        crop = frame[y0:y1, x0:x1]
        # Resize first (in source orientation), then turn the small picture: cheaper than turning 4K.
        pre_w, pre_h = (dh, dw) if self.rotation in (90, 270) else (dw, dh)
        cw, ch = x1 - x0, y1 - y0
        if (cw, ch) != (pre_w, pre_h):
            interp = cv2.INTER_AREA if pre_w * pre_h < cw * ch * 0.7 else cv2.INTER_LINEAR
            crop = cv2.resize(crop, (pre_w, pre_h), interpolation=interp)
        if self.rotation == 90:
            crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation == 180:
            crop = cv2.rotate(crop, cv2.ROTATE_180)
        elif self.rotation == 270:
            crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if self.mirror and self.flip:
            crop = cv2.flip(crop, -1)
        elif self.mirror:
            crop = cv2.flip(crop, 1)
        elif self.flip:
            crop = cv2.flip(crop, 0)
        if (dx0, dy0, dw, dh) == (0, 0, self.out_w, self.out_h):
            if out is not None:
                np.copyto(out, crop)
                return out
            return np.ascontiguousarray(crop)
        if out is None:
            out = np.zeros((self.out_h, self.out_w, 3), np.uint8)
        else:
            out[:] = 0
        out[dy0:dy1, dx0:dx1] = crop
        return out


def scale_to_fit(frame, max_w, max_h):
    """Preview helper: shrink (never enlarge) to fit max_w x max_h, keeping the shape."""
    h, w = frame.shape[:2]
    s = min(max_w / w, max_h / h, 1.0)
    if s >= 1.0:
        return frame.copy()
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    return cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)


# --- "waiting for iPhone" card ---------------------------------------------------------------------

CARD_MESSAGES = {
    "usb": ("Taco Cam: waiting for iPhone",
            ["Plug the iPhone into this PC with its USB cable.",
             "Open the Taco Cam app on the iPhone.",
             "First time? Unlock the iPhone and tap \"Trust\"."]),
    "no_app": ("Taco Cam: iPhone found",
               ["The Taco Cam app is not open on the iPhone.",
                "Open Taco Cam on the iPhone (keep it on screen)."]),
    "background": ("Taco Cam: app in the background",
                   ["Taco Cam app is in the background - open it on the iPhone."]),
    "wifi": ("Taco Cam: waiting for iPhone",
             ["Looking for the iPhone at {host} over Wi-Fi.",
              "Open the Taco Cam app on the iPhone; it shows its address.",
              "The iPhone and this PC must be on the same network."]),
    "wifi_nohost": ("Taco Cam: waiting for iPhone",
                    ["Wi-Fi mode: type the iPhone's address in the Taco Cam window.",
                     "Or switch to USB and plug the iPhone in."]),
    "error": ("Taco Cam: problem",
              ["{error}"]),
}

_card_cache = {}
_card_lock = threading.Lock()
_FONT_FILES = ("segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf")


def _font(size, bold=True):
    from PIL import ImageFont
    names = _FONT_FILES if bold else _FONT_FILES[1:]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def card_lines(kind, **fields):
    title, lines = CARD_MESSAGES.get(kind, CARD_MESSAGES["usb"])
    safe = {k: ("" if v is None else str(v)) for k, v in fields.items()}
    out = []
    for line in lines:
        try:
            out.append(line.format(**safe))
        except (KeyError, IndexError):
            out.append(line)
    return title, out


def make_card(width, height, kind="usb", **fields):
    """The "waiting for iPhone" picture, RGB uint8 HxWx3. Drawn once per size and text, then cached.

    The returned array is shared: do not write into it."""
    title, lines = card_lines(kind, **fields)
    key = (int(width), int(height), title, tuple(lines))
    with _card_lock:
        img = _card_cache.get(key)
    if img is not None:
        return img
    img = _draw_card(int(width), int(height), title, lines)
    img.setflags(write=False)
    with _card_lock:
        if len(_card_cache) > 32:
            _card_cache.clear()
        _card_cache[key] = img
    return img


def _draw_card(w, h, title, lines):
    from PIL import Image, ImageDraw
    # dark blue-grey gradient background
    top = np.array([24, 28, 40], np.float32)
    bottom = np.array([10, 12, 18], np.float32)
    t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    grad = (top * (1 - t) + bottom * t).astype(np.uint8)
    arr = np.repeat(grad[:, None, :], w, axis=1)
    im = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(im)
    unit = min(w, h)
    # taco-yellow camera badge
    r = int(unit * 0.09)
    cx, cy = w // 2, int(h * 0.30)
    d.rounded_rectangle([cx - int(r * 1.5), cy - r, cx + int(r * 1.5), cy + r], radius=int(r * 0.35),
                        fill=(255, 196, 61))
    d.ellipse([cx - int(r * 0.62), cy - int(r * 0.62), cx + int(r * 0.62), cy + int(r * 0.62)], fill=(24, 28, 40))
    d.ellipse([cx - int(r * 0.38), cy - int(r * 0.38), cx + int(r * 0.38), cy + int(r * 0.38)], fill=(255, 196, 61))
    title_font = _font(max(12, int(unit * 0.065)))
    body_font = _font(max(10, int(unit * 0.036)), bold=False)
    y = cy + r + int(unit * 0.07)
    y = _centered(d, w, y, title, title_font, (255, 255, 255)) + int(unit * 0.045)
    for line in lines:
        y = _centered(d, w, y, line, body_font, (200, 206, 220), max_w=int(w * 0.9)) + int(unit * 0.02)
    return np.asarray(im, dtype=np.uint8).copy()


def _centered(draw, w, y, text, font, fill, max_w=None):
    max_w = max_w or int(w * 0.92)
    words = text.split()
    rows, cur = [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if cur and draw.textlength(trial, font=font) > max_w:
            rows.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        rows.append(cur)
    for row in rows or [""]:
        box = draw.textbbox((0, 0), row, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        draw.text(((w - tw) // 2 - box[0], y - box[1]), row, font=font, fill=fill)
        y += int(th * 1.35)
    return y


def black(width, height):
    key = ("black", int(width), int(height))
    with _card_lock:
        img = _card_cache.get(key)
        if img is None:
            img = np.zeros((int(height), int(width), 3), np.uint8)
            img.setflags(write=False)
            _card_cache[key] = img
    return img
