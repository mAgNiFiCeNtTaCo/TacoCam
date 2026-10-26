"""Taco Cam PC settings: defaults, load/save of settings.json (CONTRACT section 6).

A corrupt or unreadable file never stops the app: it is renamed to settings.bad.json and the
defaults are used. Values that are the wrong type or out of range are replaced one by one.
"""
import copy
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "settings.json"
BAD_NAME = "settings.bad.json"

OUTPUT_SIZES = ["1280x720", "1920x1080", "3840x2160", "1080x1920", "2160x3840"]

DEFAULTS = {
    "phone": {
        "camera": "back",
        "zoom": 1.0,
        "resolution": "1080p",
        "fps": 30,
        "codec": "h264",
        "bitrate_mbps": 16,
        "focus": {"mode": "auto", "position": 0.5},
        "exposure": {"mode": "auto", "bias": 0.0, "iso": None, "shutter_s": None},
        "white_balance": {"mode": "auto", "temperature": 5000, "tint": 0},
        "torch": 0.0,
        "stabilization": "off",
        "hdr": False,
        "screen": "normal",
    },
    "pc": {
        "connect": "usb",
        "wifi_host": "",
        "rotate": "auto",
        "mirror": False,
        "flip": False,
        "output": "1920x1080",
        "fit": "crop",
        "fps_out": 30,
        "vcam_name": "Taco Cam",
        "when_disconnected": "card",
    },
}

ENUMS = {
    "phone.camera": {"back", "front"},
    "phone.resolution": {"720p", "1080p", "4k"},
    "phone.fps": {24, 25, 30, 60},
    "phone.codec": {"h264", "hevc"},
    "phone.focus.mode": {"auto", "manual"},
    "phone.exposure.mode": {"auto", "manual"},
    "phone.white_balance.mode": {"auto", "manual"},
    "phone.stabilization": {"off", "standard", "cinematic"},
    "phone.screen": {"normal", "dim"},
    "pc.connect": {"usb", "wifi"},
    "pc.rotate": {"auto", 0, 90, 180, 270},
    "pc.output": set(OUTPUT_SIZES),
    "pc.fit": {"crop", "fit", "stretch"},
    "pc.fps_out": {24, 25, 30, 60},
    "pc.when_disconnected": {"card", "last", "black"},
}

RANGES = {
    "phone.zoom": (0.1, 30.0),
    "phone.bitrate_mbps": (2, 80),
    "phone.focus.position": (0.0, 1.0),
    "phone.exposure.bias": (-3.0, 3.0),
    "phone.white_balance.temperature": (2500, 8000),
    "phone.white_balance.tint": (-150, 150),
    "phone.torch": (0.0, 1.0),
}

# Allowed to be null in the file (iso / shutter are only used in manual exposure).
NULLABLE = {"phone.exposure.iso", "phone.exposure.shutter_s"}


def default_settings():
    return copy.deepcopy(DEFAULTS)


def deep_update(dst, src):
    """Merge nested dict src into dst in place; returns dst."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_update(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


def get_path(d, path, default=None):
    """get_path(settings, "phone.focus.mode")."""
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def nest(path, value):
    """nest("phone.focus.mode", "manual") -> {"phone": {"focus": {"mode": "manual"}}}"""
    out = value
    for part in reversed(path.split(".")):
        out = {part: out}
    return out


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _valid(path, default, value):
    if path in ENUMS:
        try:
            return value in ENUMS[path] and not isinstance(value, bool)
        except TypeError:
            return False
    if value is None:
        return path in NULLABLE
    if isinstance(default, bool):
        return isinstance(value, bool)
    if path in NULLABLE:
        return _is_number(value) and value > 0
    if _is_number(default):
        if not _is_number(value) or value != value:
            return False
        lo, hi = RANGES.get(path, (None, None))
        return (lo is None) or (lo <= value <= hi)
    if isinstance(default, str):
        if not isinstance(value, str):
            return False
        return bool(value.strip()) if path == "pc.vcam_name" else len(value) <= 253
    return False


def sanitize(raw):
    """Defaults, overlaid with every value of raw that is the right type and in range."""
    out = default_settings()

    def walk(dflt, src, dst, prefix):
        for key, d in dflt.items():
            path = f"{prefix}.{key}" if prefix else key
            if key not in src:
                continue
            v = src[key]
            if isinstance(d, dict):
                if isinstance(v, dict):
                    walk(d, v, dst[key], path)
            elif _valid(path, d, v):
                dst[key] = v.strip() if isinstance(v, str) else v

    if isinstance(raw, dict):
        walk(DEFAULTS, raw, out, "")
    return out


def load(path=None):
    """Returns (settings, note). note is None, or a plain sentence about a problem that was handled."""
    path = Path(path or SETTINGS_PATH)
    if not path.exists():
        return default_settings(), None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("settings file is not a JSON object")
    except (OSError, ValueError) as e:
        bad = path.with_name(BAD_NAME)
        note = f"Settings file was unreadable ({e}); using defaults."
        try:
            os.replace(path, bad)
            note += f" The old file is kept as {bad.name}."
        except OSError:
            pass
        return default_settings(), note
    return sanitize(raw), None


def save(settings, path=None):
    """Atomic write (temp file + replace). Returns True on success."""
    path = Path(path or SETTINGS_PATH)
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(sanitize(settings), indent=2)
    try:
        tmp.write_text(data, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        return False
    except OSError:
        return False
