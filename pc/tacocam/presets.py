"""Camera presets: named sets of the phone's picture settings (zoom, focus, exposure, colors, light,
anti-flicker), applied with one click, a hotkey (Ctrl+Alt+1..9) or when OBS switches to a linked scene.

Stream settings (resolution, fps, codec, bitrate) are never part of a preset: changing them restarts the
video. Pure functions, no Tk.
"""
import copy

PRESET_KEYS = ("camera", "zoom", "focus", "exposure", "white_balance", "torch", "anti_flicker")
MAX_PRESETS = 9
NAME_MAX = 40


def sanitize_presets(raw):
    """A list of valid presets from whatever was in settings.json (bad entries are dropped)."""
    from . import settings as S
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        phone_raw = item.get("phone")
        if not isinstance(phone_raw, dict):
            continue
        # Run the phone part through the normal settings checks, keep only the preset keys it had.
        clean = S.sanitize({"phone": phone_raw})["phone"]
        phone = {k: clean[k] for k in PRESET_KEYS if k in phone_raw}
        if not phone:
            continue
        scene = item.get("obs_scene")
        out.append({"name": name.strip()[:NAME_MAX],
                    "phone": phone,
                    "obs_scene": scene.strip()[:200] if isinstance(scene, str) else ""})
        if len(out) >= MAX_PRESETS:
            break
    return out


def capture(phone_settings, live=None, lock_focus=False, lock_exposure=False, lock_colors=False):
    """A preset's phone part from the current settings. lock_* turn auto focus / exposure / white balance
    into manual at the values the camera is using right now (STATE `live`), so they stop drifting."""
    p = {k: copy.deepcopy(phone_settings[k]) for k in PRESET_KEYS if k in phone_settings}
    live = live or {}
    if lock_focus and isinstance(live.get("lens_position"), (int, float)):
        p["focus"] = {"mode": "manual", "position": round(float(live["lens_position"]), 3)}
    if lock_exposure and isinstance(live.get("iso"), (int, float)) and isinstance(live.get("shutter_s"), (int, float)) \
            and live["iso"] > 0 and live["shutter_s"] > 0:
        exp = dict(p.get("exposure") or {})
        exp.update(mode="manual", iso=float(live["iso"]), shutter_s=float(live["shutter_s"]))
        p["exposure"] = exp
    if lock_colors and isinstance(live.get("temperature"), (int, float)) and isinstance(live.get("tint"), (int, float)):
        p["white_balance"] = {"mode": "manual", "temperature": int(round(live["temperature"])),
                              "tint": int(round(live["tint"]))}
    return p


def to_partial(preset):
    """The settings change that applies a preset: {"phone": {...}} (nested objects sent whole)."""
    return {"phone": copy.deepcopy(preset["phone"])}


def describe(preset):
    """One short line about what the preset does, for the list."""
    p = preset["phone"]
    bits = []
    if "camera" in p:
        bits.append("front" if p["camera"] == "front" else "back")
    if "zoom" in p:
        z = p["zoom"]
        bits.append(f"{z:g}x")
    for key, label in (("focus", "focus"), ("exposure", "exposure"), ("white_balance", "colors")):
        if isinstance(p.get(key), dict) and p[key].get("mode") == "manual":
            bits.append(f"{label} locked")
    if p.get("torch", 0) and p["torch"] > 0:
        bits.append(f"light {round(p['torch'] * 100)}%")
    if p.get("anti_flicker", "off") != "off":
        bits.append(f"anti-flicker {p['anti_flicker'].replace('hz', ' Hz')}")
    if preset.get("obs_scene"):
        bits.append(f'OBS scene "{preset["obs_scene"]}"')
    return ", ".join(bits)


def for_scene(presets, scene):
    """Index of the first preset linked to this OBS scene, or None."""
    if not scene:
        return None
    for i, p in enumerate(presets):
        if p.get("obs_scene") == scene:
            return i
    return None
