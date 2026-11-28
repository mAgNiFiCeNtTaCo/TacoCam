"""One-click OBS setup for a Whatnot stream with Taco Cam (for a friend's PC): a profile and a scene collection
like the ones Taco Cam was built with, and OBS switched to them.

What it writes (OBS must be closed: it rewrites its files when it exits):
  - profile "Taco Cam Whatnot": portrait 1080x1920 canvas, Whatnot's stream output (CBR 3500 kbps, keyframe
    2 s, no B-frames, Opus audio) on x264 (veryfast + zerolatency, any PC) or NVIDIA NVENC (the user's choice, only
    offered on an NVIDIA PC) and a WHIP stream service with no server or key in it (Whatnot's Show Tools fills those
    in for every show: "Update Profile"). apply_encoder() puts the NVENC settings back on whatever profile OBS opens
    on, after Whatnot's "Update Profile" made its own x264 one.
  - scene collection "Taco Cam Whatnot": scene "Live" with the "Taco Cam" camera turned 90 degrees to fill the
    canvas (Taco Cam sends 1920x1080, rotate 0) and the default microphone.
  - OBS's settings (user.ini / global.ini [Basic]): open on that profile and collection.
  - obs-websocket switched on with a new password when it was off (Whatnot's Show Tools connects to OBS through
    it and asks for that password). When it was on already, it is left as it is.
Every file it replaces is copied to <name>.bak-tacocam first. Nothing of an existing profile or collection with
another name is changed.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import uuid
from pathlib import Path

NAME = "Taco Cam Whatnot"
DIR_NAME = "Taco_Cam_Whatnot"
W, H, FPS = 1080, 1920, 30
MAIN_CANVAS = "6c69626f-6273-4c00-9d88-c5136d61696e"   # libobs' fixed id for the main canvas
# Unity Capture's DirectShow camera as OBS names it (Taco Cam's driver registers it as "Taco Cam")
TACO_CAM_DEVICE = "Taco Cam:foo#3Abar"
STREAM_ENCODER = {"rate_control": "CBR", "bitrate": 3500, "keyint_sec": 2, "preset": "veryfast",
                  "tune": "zerolatency", "x264opts": "bframes=0"}
# The same Whatnot limits (CBR 3500, keyframe 2 s, no B-frames) on an NVIDIA card's encoder chip, which frees the
# processor. Values from the user's own Whatnot_New_NVENC profile (2026-11-12). No AV1: RTX 30 and older have no
# AV1 encoder, and OBS's other AV1 encoders run on the processor and are too heavy.
NVENC_ENCODER = {"rate_control": "CBR", "bitrate": 3500, "keyint_sec": 2, "preset2": "p5", "tune": "hq",
                 "multipass": "qres", "profile": "main", "bf": 0, "lookahead": False, "psycho_aq": True}
ENCODERS = {"x264": ("obs_x264", STREAM_ENCODER), "nvenc": ("obs_nvenc_h264_tex", NVENC_ENCODER)}
ENCODER_NAMES = {"x264": "Standard (x264)", "nvenc": "NVIDIA (NVENC)"}
DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


class SetupProblem(Exception):
    """Something the user has to do first (the text says what)."""


def obs_dir():
    return Path(os.environ.get("APPDATA", "")) / "obs-studio"


def obs_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH"], capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except OSError:
        return False
    return "obs64.exe" in out


def gpu_names():
    """The graphics cards Windows has drivers for (their names from the registry; no programs started)."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DISPLAY_CLASS)
    except (ImportError, OSError):
        return []
    names, i = [], 0
    with key:
        while True:
            try:
                sub = winreg.EnumKey(key, i)
            except OSError:
                break
            i += 1
            if not sub.isdigit():
                continue
            try:
                with winreg.OpenKey(key, sub) as s:
                    names.append(str(winreg.QueryValueEx(s, "DriverDesc")[0]))
            except OSError:
                pass
    return names


def has_nvidia():
    """An NVIDIA card with its driver's encoder library: OBS can use NVENC."""
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    return any("nvidia" in n.lower() for n in gpu_names()) and (system32 / "nvEncodeAPI64.dll").exists()


def get_ini(path, section, key):
    """The value of key in [section] of an OBS ini file, or None."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    m = re.search(r"(?m)^\[%s\]\r?\n" % re.escape(section), text)
    if not m:
        return None
    end = re.search(r"(?m)^\[", text[m.end():])
    body = text[m.end():m.end() + end.start()] if end else text[m.end():]
    v = re.search(r"(?m)^%s=(.*?)\r?$" % re.escape(key), body)
    return v.group(1) if v else None


def _encoder(encoder):
    if encoder not in ENCODERS:
        raise ValueError(f"unknown encoder {encoder!r}")
    if encoder == "nvenc" and not has_nvidia():
        raise SetupProblem("The NVIDIA setting needs an NVIDIA graphics card: use Standard (x264) on this PC")
    return ENCODERS[encoder]


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_encoder(folder, encoder):
    """Point the profile's stream at the encoder and write its settings (basic.ini and streamEncoder.json are
    backed up first). service.json (the stream key) is never read or changed. -> the stream's bitrate.

    A profile in OBS's Simple output mode (the one Whatnot's "Update Profile" makes) is moved to Advanced: Simple
    mode has no keyframe setting for NVENC (Whatnot's profile sets its 2 s keyframe in the x264-only x264Settings),
    so NVENC there would send a keyframe only every ~8 s. Advanced gets the same stream: Whatnot's video bitrate
    (VBitrate), Opus audio at its ABitrate on track 1, and the service's settings applied (WHIP: no B-frames)."""
    obs_id, values = ENCODERS[encoder]
    values = dict(values)
    ini = folder / "basic.ini"
    adv = {"Encoder": obs_id}
    simple = (get_ini(ini, "Output", "Mode") or "Simple") != "Advanced"
    if simple:
        vbitrate = _int(get_ini(ini, "SimpleOutput", "VBitrate"))
        if vbitrate and 500 <= vbitrate <= 8500:                 # Amazon IVS drops streams over 8.5 Mbps
            values["bitrate"] = vbitrate
        abitrate = _int(get_ini(ini, "SimpleOutput", "ABitrate")) or 160
        adv.update({"AudioEncoder": "ffmpeg_opus", "TrackIndex": 1, "Track1Bitrate": abitrate,
                    "ApplyServiceSettings": "true"})
    _backup(ini)
    if simple:
        set_ini(ini, "Output", {"Mode": "Advanced"})
    set_ini(ini, "AdvOut", adv)
    enc = folder / "streamEncoder.json"
    _backup(enc)
    enc.write_text(json.dumps(values, indent=4), encoding="utf-8", newline="")
    return values["bitrate"]


def _backup(p):
    if p.exists():
        shutil.copy2(p, p.with_name(p.name + ".bak-tacocam"))


def set_ini(path, section, values):
    """Set key=value lines inside [section] of an OBS ini file, keeping everything else as it is."""
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    nl = "\r\n" if "\r\n" in text else "\n"
    m = re.search(r"(?m)^\[%s\]\r?\n" % re.escape(section), text)
    if not m:
        text = (text.rstrip("\r\n") + nl + nl if text.strip() else "") + "[%s]" % section + nl
        m = re.search(r"(?m)^\[%s\]\r?\n" % re.escape(section), text)
    end = re.search(r"(?m)^\[", text[m.end():])
    body_end = m.end() + (end.start() if end else len(text) - m.end())
    body = text[m.end():body_end]
    for k, v in values.items():
        line = "%s=%s" % (k, v)
        if re.search(r"(?m)^%s=" % re.escape(k), body):
            body = re.sub(r"(?m)^%s=.*$" % re.escape(k), lambda _m: line, body)
        else:
            body = body.rstrip("\r\n") + (nl if body.strip() else "") + line + nl
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text[:m.end()] + body + text[body_end:], encoding="utf-8", newline="")


def _source(name, kind, settings, **extra):
    s = {"name": name, "uuid": str(uuid.uuid4()), "id": kind, "versioned_id": kind, "settings": settings,
         "mixers": 255 if kind != "scene" else 0, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5,
         "enabled": True, "muted": False, "push-to-mute": False, "push-to-mute-delay": 0, "push-to-talk": False,
         "push-to-talk-delay": 0, "hotkeys": {}, "deinterlace_mode": 0, "deinterlace_field_order": 0,
         "monitoring_type": 0, "monitoring_enabled": False, "private_settings": {}}
    s.update(extra)
    return s


def _item(src, iid, pos=(0.0, 0.0), rot=0.0, scale=(1.0, 1.0), locked=False):
    # OBS 31+ reads pos_rel / scale_rel (relative to the canvas height); older versions read pos / scale.
    return {"name": src["name"], "source_uuid": src["uuid"], "visible": True, "locked": locked, "rot": rot,
            "scale_ref": {"x": float(W), "y": float(H)}, "align": 5, "bounds_type": 0, "bounds_align": 0,
            "bounds_crop": False, "crop_left": 0, "crop_top": 0, "crop_right": 0, "crop_bottom": 0, "id": iid,
            "group_item_backup": False, "pos": {"x": pos[0], "y": pos[1]},
            "pos_rel": {"x": (pos[0] - W / 2) / (H / 2), "y": (pos[1] - H / 2) / (H / 2)},
            "scale": {"x": scale[0], "y": scale[1]}, "scale_rel": {"x": scale[0], "y": scale[1]},
            "bounds": {"x": 0.0, "y": 0.0}, "bounds_rel": {"x": 0.0, "y": 0.0}, "scale_filter": "disable",
            "blend_method": "default", "blend_type": "normal", "show_transition": {"duration": 300},
            "hide_transition": {"duration": 300}, "private_settings": {}}


def collection():
    """The scene collection: "Live" = the Taco Cam camera filling the portrait canvas + the microphone."""
    cam = _source("Taco Cam", "dshow_input", {"video_device_id": TACO_CAM_DEVICE,
                                               "last_video_device_id": TACO_CAM_DEVICE,
                                               "resolution": "1920x1080", "last_resolution": "1920x1080",
                                               "res_type": 1, "active": True}, mixers=0)
    mic = _source("Mic", "wasapi_input_capture", {"device_id": "default"})
    # 1920x1080 turned 90 degrees clockwise around its top-left corner, placed at x = 1080: fills 1080x1920
    items = [_item(cam, 1, pos=(float(W), 0.0), rot=90.0, locked=True), _item(mic, 2)]
    live = _source("Live", "scene", {"id_counter": len(items), "custom_size": False, "items": items},
                   canvas_uuid=MAIN_CANVAS)
    return {
        "name": NAME,
        "sources": [cam, mic, live],
        "groups": [],
        "scene_order": [{"name": "Live"}],
        "current_scene": "Live",
        "current_program_scene": "Live",
        "canvases": [],
        "current_transition": "Fade",
        "transition_duration": 300,
        "transitions": [],
        "quick_transitions": [],
        "saved_projectors": [],
        "preview_locked": False,
        "scaling_enabled": False,
        "scaling_level": 0,
        "scaling_off_x": 0.0,
        "scaling_off_y": 0.0,
        "modules": {},
        "resolution": {"x": W, "y": H},
        "version": 2,
    }


def _write_profile(folder, videos, encoder="x264"):
    folder.mkdir(parents=True, exist_ok=True)
    ini = folder / "basic.ini"
    _backup(ini)
    set_ini(ini, "General", {"Name": NAME})
    set_ini(ini, "Output", {"Mode": "Advanced", "Reconnect": "true", "RetryDelay": 2, "MaxRetries": 25})
    set_ini(ini, "AdvOut", {"Encoder": ENCODERS[encoder][0], "AudioEncoder": "ffmpeg_opus", "Track1Bitrate": 160,
                            "TrackIndex": 1, "UseRescale": "false", "ApplyServiceSettings": "true",
                            "RecType": "Standard", "RecFilePath": str(videos).replace("\\", "\\\\"),
                            "RecFormat2": "hybrid_mp4", "RecEncoder": "none", "RecTracks": 1})
    set_ini(ini, "Video", {"BaseCX": W, "BaseCY": H, "OutputCX": W, "OutputCY": H, "FPSType": 0, "FPSCommon": FPS,
                           "FPSInt": FPS, "FPSNum": FPS, "FPSDen": 1, "ScaleType": "bicubic", "ColorFormat": "NV12",
                           "ColorSpace": "709", "ColorRange": "Partial"})
    set_ini(ini, "Audio", {"SampleRate": 48000, "ChannelSetup": "Stereo"})
    enc = folder / "streamEncoder.json"
    _backup(enc)
    enc.write_text(json.dumps(ENCODERS[encoder][1], indent=4), encoding="utf-8", newline="")
    # The service file holds the per-show stream key once Whatnot fills it in: only made when missing, never read.
    service = folder / "service.json"
    if not service.exists():
        service.write_text(json.dumps({"type": "whip_custom", "settings": {}}), encoding="utf-8", newline="")


def _websocket(obs):
    """Switch obs-websocket on with a new password when it is off, and also when it is on WITHOUT a password
    (then anyone on the same network could control OBS; security finding WEBCAM-20261128-04).
    -> (password, port, made_new, was_open)."""
    cfg_file = obs / "plugin_config" / "obs-websocket" / "config.json"
    try:
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    port = int(cfg.get("server_port") or 4455)
    if cfg.get("server_enabled") and cfg.get("auth_required") and cfg.get("server_password"):
        return cfg.get("server_password"), port, False, False
    was_open = bool(cfg.get("server_enabled"))        # on, but with no password asked
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    password = "".join(secrets.choice(alphabet) for _ in range(16))
    cfg.update(server_enabled=True, server_port=port, auth_required=True, server_password=password,
               alerts_enabled=cfg.get("alerts_enabled", False), first_load=False)
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    _backup(cfg_file)
    cfg_file.write_text(json.dumps(cfg, indent=4), encoding="utf-8", newline="")
    return password, port, True, was_open


def _ready(obs, check_running):
    obs = Path(obs) if obs else obs_dir()
    if check_running and obs_running():
        raise SetupProblem("OBS is open: close OBS first (it saves its own files when it closes), then click again")
    if not (obs / "basic").is_dir():
        raise SetupProblem("OBS hasn't been opened on this PC yet: open OBS once, close it, then click again "
                           "(OBS Studio comes from obsproject.com)")
    return obs


def active_profile(obs):
    """(folder, name) of the profile OBS opens on, from user.ini (OBS 31+) or global.ini."""
    for ini in (obs / "user.ini", obs / "global.ini"):
        folder = get_ini(ini, "Basic", "ProfileDir")
        if folder:
            path = obs / "basic" / "profiles" / folder
            return path, get_ini(path / "basic.ini", "General", "Name") or get_ini(ini, "Basic", "Profile") or folder
    return None, None


def apply_encoder(encoder, obs=None, check_running=True):
    """Put the encoder's settings on the profile OBS opens on now (e.g. after Whatnot's "Update Profile" made and
    switched to its own x264 profile, in Simple output mode: see _write_encoder). Only basic.ini's output lines and
    streamEncoder.json change, both backed up first. -> (the profile's name, the stream's bitrate in kbps).
    Raises SetupProblem."""
    obs = _ready(obs, check_running)
    _encoder(encoder)
    folder, name = active_profile(obs)
    if folder is None or not (folder / "basic.ini").exists():
        raise SetupProblem("Couldn't find the profile OBS opens on: open OBS once, close it, then click again")
    return name, _write_encoder(folder, encoder)


def setup(obs=None, check_running=True, encoder="x264"):
    """Write the profile and collection and make OBS open on them. encoder: "x264" (any PC) or "nvenc" (NVIDIA).
    -> {"profile", "collection", "encoder", "websocket_password", "websocket_port", "websocket_new",
        "websocket_was_open"} (was_open: OBS's connection was on without a password; it has one now).
    Raises SetupProblem."""
    obs = _ready(obs, check_running)
    _encoder(encoder)
    videos = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos"
    _write_profile(obs / "basic" / "profiles" / DIR_NAME, videos, encoder)
    scenes = obs / "basic" / "scenes"
    scenes.mkdir(parents=True, exist_ok=True)
    out = scenes / (DIR_NAME + ".json")
    _backup(out)
    out.write_text(json.dumps(collection(), indent=4), encoding="utf-8", newline="")
    choice = {"Profile": NAME, "ProfileDir": DIR_NAME, "SceneCollection": NAME, "SceneCollectionFile": out.name}
    wrote = False
    for ini in (obs / "user.ini", obs / "global.ini"):     # OBS 31+ keeps the choice in user.ini, older in global.ini
        if ini.exists():
            _backup(ini)
            set_ini(ini, "Basic", choice)
            wrote = True
    if not wrote:
        set_ini(obs / "user.ini", "Basic", choice)
    password, port, new, was_open = _websocket(obs)
    return {"profile": NAME, "collection": NAME, "encoder": encoder, "websocket_password": password,
            "websocket_port": port, "websocket_new": new, "websocket_was_open": was_open}
