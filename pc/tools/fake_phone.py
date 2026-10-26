"""Fake iPhone for Taco Cam: speaks the contract (CONTRACT sections 2-5) on 127.0.0.1:47777.

It stands in for the real phone in every PC test and for demos:

    python pc/tools/fake_phone.py                    # landscape picture
    python pc/tools/fake_phone.py --rotation 90      # "held in portrait": the PC must turn it 90 degrees

Then in the Taco Cam window choose Wi-Fi with address 127.0.0.1. While it runs you can type commands:
rotation 90 | background | foreground | zoom 0.5 | camera front | torch 0.5 | quit

The picture is a test scene seen through a virtual lens: at 0.5x you see the whole scene (the yellow
"ULTRA-WIDE" border is only visible then), 1x shows half its width, 3x a sixth. It also shows camera,
zoom, torch (brighter + "TORCH"), size/fps/codec, a frame counter, a clock and a moving ball. A red square
marks the upright picture's top-left corner; a yellow box shows the last focus point for 3 s.
"""
import argparse
import copy
import math
import os
import select
import socket
import sys
import threading
import time
from fractions import Fraction

import av
import cv2
import numpy as np
from av.video.frame import PictureType

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tacocam import protocol  # noqa: E402

RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}
ORIENTATION = {0: "landscape_port_right", 90: "portrait", 180: "landscape_port_left", 270: "portrait_upside_down"}

CAMERAS = {
    "back": {"available": True, "name": "Back Triple Camera", "min_zoom": 0.5, "max_zoom": 15.0,
             "lens_zooms": [0.5, 1.0, 3.0], "has_torch": True, "resolutions": ["720p", "1080p", "4k"],
             "fps": {"720p": [24, 25, 30, 60], "1080p": [24, 25, 30, 60], "4k": [24, 25, 30, 60]},
             "iso_range": [32, 3072], "shutter_range_s": [0.00002, 0.5], "focus_manual": True, "hdr": True,
             "stabilization": ["off", "standard", "cinematic"]},
    "front": {"available": True, "name": "Front TrueDepth Camera", "min_zoom": 1.0, "max_zoom": 5.0,
              "lens_zooms": [1.0], "has_torch": False, "resolutions": ["720p", "1080p", "4k"],
              "fps": {"720p": [24, 25, 30, 60], "1080p": [24, 25, 30, 60], "4k": [24, 25, 30]},
              "iso_range": [23, 2208], "shutter_range_s": [0.000014, 0.33], "focus_manual": False, "hdr": True,
              "stabilization": ["off", "standard"]},
}

DEFAULT_SETTINGS = {
    "camera": "back", "zoom": 1.0, "resolution": "1080p", "fps": 30, "codec": "h264", "bitrate_mbps": 16,
    "focus": {"mode": "auto", "position": 0.5},
    "exposure": {"mode": "auto", "bias": 0.0, "iso": None, "shutter_s": None},
    "white_balance": {"mode": "auto", "temperature": 5000, "tint": 0},
    "torch": 0.0, "stabilization": "off", "hdr": False, "screen": "normal",
}
NESTED = ("focus", "exposure", "white_balance")

MAX_QUEUED_FRAMES = 3
MAX_QUEUED_BYTES = 2 * 1024 * 1024


# --- settings ------------------------------------------------------------------------------------

def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"not a number: {v!r}")
    return float(v)


def _clamp(v, lo, hi):
    return min(max(v, lo), hi)


def apply_settings(current, patch):
    """current settings + a SET patch -> (settings in effect after clamping, notes about ignored values)."""
    s = copy.deepcopy(current)
    notes = []
    for key, val in (patch or {}).items():
        if key in NESTED:
            if isinstance(val, dict):
                for sub, v in val.items():
                    if sub in s[key]:
                        s[key][sub] = v
                    else:
                        notes.append(f"unknown setting {key}.{sub}")
            else:
                notes.append(f"{key} must be an object")
        elif key in s:
            s[key] = val
        else:
            notes.append(f"unknown setting {key}")
    return normalize(s, current, notes), notes


def normalize(s, prev, notes):
    out = copy.deepcopy(prev)

    def take(path, fn):
        try:
            value = fn()
        except (TypeError, ValueError, KeyError) as e:
            notes.append(f"{path}: {e}")
            return
        node = out
        parts = path.split(".")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value

    def enum(v, allowed):
        if v not in allowed:
            raise ValueError(f"{v!r} not one of {list(allowed)}")
        return v

    take("camera", lambda: enum(s["camera"], CAMERAS))
    cam = CAMERAS[out["camera"]]
    take("zoom", lambda: round(_clamp(_num(s["zoom"]), cam["min_zoom"], cam["max_zoom"]), 3))
    out["zoom"] = _clamp(out["zoom"], cam["min_zoom"], cam["max_zoom"])
    take("resolution", lambda: enum(s["resolution"], cam["resolutions"]))

    def fps():
        want = int(_num(s["fps"]))
        allowed = cam["fps"][out["resolution"]]
        if want in allowed:
            return want
        lower = [f for f in allowed if f <= want]
        return max(lower) if lower else min(allowed)
    take("fps", fps)
    if out["fps"] not in cam["fps"][out["resolution"]]:
        out["fps"] = max(cam["fps"][out["resolution"]])
    take("codec", lambda: enum(s["codec"], ("h264", "hevc")))
    take("bitrate_mbps", lambda: round(_clamp(_num(s["bitrate_mbps"]), 2, 80), 2))

    take("focus.mode", lambda: enum(s["focus"]["mode"], ("auto", "manual")))
    if out["focus"]["mode"] == "manual" and not cam["focus_manual"]:
        out["focus"]["mode"] = "auto"
        notes.append("this camera has no manual focus")
    take("focus.position", lambda: round(_clamp(_num(s["focus"]["position"]), 0.0, 1.0), 4))

    take("exposure.mode", lambda: enum(s["exposure"]["mode"], ("auto", "manual")))
    take("exposure.bias", lambda: round(_clamp(_num(s["exposure"]["bias"]), -3.0, 3.0), 3))
    lo, hi = cam["iso_range"]
    slo, shi = cam["shutter_range_s"]
    if out["exposure"]["mode"] == "manual":
        take("exposure.iso", lambda: round(_clamp(_num(s["exposure"]["iso"] if s["exposure"]["iso"] is not None
                                                       else 100), lo, hi), 1))
        take("exposure.shutter_s", lambda: _clamp(_num(s["exposure"]["shutter_s"]
                                                       if s["exposure"]["shutter_s"] is not None else 1 / 60),
                                                  slo, shi))
    else:
        out["exposure"]["iso"] = None
        out["exposure"]["shutter_s"] = None

    take("white_balance.mode", lambda: enum(s["white_balance"]["mode"], ("auto", "manual")))
    take("white_balance.temperature", lambda: int(round(_clamp(_num(s["white_balance"]["temperature"]), 2500, 8000))))
    take("white_balance.tint", lambda: int(round(_clamp(_num(s["white_balance"]["tint"]), -150, 150))))

    def torch():
        t = _clamp(_num(s["torch"]), 0.0, 1.0)
        if not cam["has_torch"]:
            return 0.0
        return 0.0 if t <= 0 else round(max(t, 0.01), 3)
    take("torch", torch)
    if not cam["has_torch"]:
        out["torch"] = 0.0
    take("stabilization", lambda: enum(s["stabilization"], cam["stabilization"]))
    if out["stabilization"] not in cam["stabilization"]:
        out["stabilization"] = "off"

    def hdr():
        if not isinstance(s["hdr"], bool):
            raise ValueError(f"{s['hdr']!r} is not true/false")
        return s["hdr"] and cam["hdr"]
    take("hdr", hdr)
    take("screen", lambda: enum(s["screen"], ("normal", "dim")))
    return out


# --- picture -------------------------------------------------------------------------------------

WORLD = 2048


def _world(camera):
    """The scene in front of the fake lens (BGR, WORLD x WORLD)."""
    img = np.zeros((WORLD, WORLD, 3), np.uint8)
    yy, xx = np.mgrid[0:WORLD, 0:WORLD].astype(np.float32) / WORLD
    if camera == "back":
        img[..., 0] = (60 + 140 * xx).astype(np.uint8)
        img[..., 1] = (50 + 120 * yy).astype(np.uint8)
        img[..., 2] = (90 + 100 * (1 - xx)).astype(np.uint8)
    else:
        img[..., 0] = (120 + 100 * yy).astype(np.uint8)
        img[..., 1] = (60 + 60 * xx).astype(np.uint8)
        img[..., 2] = (150 + 80 * (1 - yy)).astype(np.uint8)
    cells = 16
    step = WORLD // cells
    font = cv2.FONT_HERSHEY_SIMPLEX
    for i in range(cells):
        for j in range(cells):
            if (i + j) % 2 == 0:
                cv2.rectangle(img, (i * step, j * step), ((i + 1) * step, (j + 1) * step), (255, 255, 255), -1,
                              lineType=cv2.LINE_8)
                img[j * step:(j + 1) * step, i * step:(i + 1) * step] //= 2
            label = f"{chr(65 + j)}{i + 1}"
            cv2.putText(img, label, (i * step + 8, j * step + 40), font, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
    c = WORLD // 2
    for r, col in ((900, (0, 165, 255)), (600, (255, 255, 0)), (300, (255, 0, 255)), (120, (0, 255, 0))):
        cv2.circle(img, (c, c), r, col, 10, cv2.LINE_AA)
    # yellow border: only inside the 0.5x view
    b = WORLD // 20
    cv2.rectangle(img, (b // 2, b // 2), (WORLD - b // 2, WORLD - b // 2), (0, 230, 255), b // 2)
    for (x, y) in ((b * 2, int(b * 1.6)), (WORLD // 2 - 300, int(b * 1.6)), (b * 2, WORLD - b)):
        cv2.putText(img, "ULTRA-WIDE 0.5x", (x, y), font, 2.2, (0, 230, 255), 5, cv2.LINE_AA)
    title = "BACK CAMERA" if camera == "back" else "FRONT CAMERA"
    cv2.putText(img, title, (c - 520, c + 40), font, 4.0, (255, 255, 255), 10, cv2.LINE_AA)
    return img


class Scene:
    def __init__(self):
        self._worlds = {}

    def world(self, camera):
        if camera not in self._worlds:
            self._worlds[camera] = _world(camera)
        return self._worlds[camera]

    def render(self, settings, width, height, rotation, frame_no, stream_info, focus=None):
        """Sensor frame (landscape width x height, BGR) whose content is upright after turning it
        `rotation` degrees clockwise (what the PC does with rotation_hint)."""
        cw, ch = (height, width) if rotation in (90, 270) else (width, height)
        world = self.world(settings["camera"])
        zoom = max(0.5, float(settings["zoom"]))
        frac = min(1.0, 0.5 / zoom)                  # share of the scene's long side that is visible
        long_px = WORLD * frac
        if cw >= ch:
            vw, vh = long_px, long_px * ch / cw
        else:
            vw, vh = long_px * cw / ch, long_px
        x0, y0 = int(round((WORLD - vw) / 2)), int(round((WORLD - vh) / 2))
        x1, y1 = max(x0 + 2, int(round(x0 + vw))), max(y0 + 2, int(round(y0 + vh)))
        canvas = cv2.resize(world[y0:y1, x0:x1], (cw, ch), interpolation=cv2.INTER_LINEAR)
        torch = float(settings.get("torch") or 0.0)
        gain = 2.0 ** (float(settings["exposure"].get("bias") or 0.0) / 2.0) * (1.0 + 0.7 * torch)
        if abs(gain - 1.0) > 1e-3 or torch > 0:
            canvas = cv2.convertScaleAbs(canvas, alpha=gain, beta=45 * torch)
        unit = min(cw, ch)
        # moving ball
        t = time.monotonic()
        bx = int((0.5 + 0.4 * math.sin(t * 1.3)) * cw)
        by = int((0.62 + 0.2 * math.sin(t * 2.1)) * ch)
        cv2.circle(canvas, (bx, by), max(6, unit // 14), (40, 40, 240), -1, cv2.LINE_AA)
        cv2.circle(canvas, (bx, by), max(6, unit // 14), (255, 255, 255), max(2, unit // 200), cv2.LINE_AA)
        # top-left marker (pure red) used by tests to check orientation
        m = max(8, unit // 12)
        g = max(4, unit // 50)
        canvas[g:g + m, g:g + m] = (0, 0, 255)
        # text
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = unit / 900.0
        thick = max(1, int(round(unit / 360)))
        cam = settings["camera"].upper()
        lines = [
            f"FAKE iPHONE  {cam}  {settings['zoom']:.2f}x" + (f"  TORCH {int(round(torch * 100))}%" if torch else ""),
            f"{stream_info}  rot {rotation}",
            f"frame {frame_no:06d}  {time.strftime('%H:%M:%S')}.{int((time.time() % 1) * 1000):03d}",
        ]
        y = g + m + int(40 * scale)
        x = g
        for line in lines:
            (tw, th), _ = cv2.getTextSize(line, font, scale, thick)
            cv2.rectangle(canvas, (x - 4, y - th - 8), (x + tw + 6, y + 8), (0, 0, 0), -1)
            cv2.putText(canvas, line, (x, y), font, scale, (255, 255, 255), thick, cv2.LINE_AA)
            y += th + int(26 * scale)
        if rotation == 90:
            frame = cv2.rotate(canvas, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif rotation == 180:
            frame = cv2.rotate(canvas, cv2.ROTATE_180)
        elif rotation == 270:
            frame = cv2.rotate(canvas, cv2.ROTATE_90_CLOCKWISE)
        else:
            frame = canvas
        if focus is not None:
            fx, fy = int(focus[0] * width), int(focus[1] * height)
            r = max(10, unit // 16)
            cv2.rectangle(frame, (fx - r, fy - r), (fx + r, fy + r), (0, 255, 255), max(2, unit // 160))
        return np.ascontiguousarray(frame)


class Encoder:
    """PyAV H.264 (libx264) / HEVC (libx265) encoder: Annex-B, no B-frames, SPS/PPS(/VPS) before every
    keyframe, keyframe on demand."""

    def __init__(self, codec, width, height, fps, bitrate_mbps):
        self.codec, self.width, self.height, self.fps = codec, width, height, fps
        name = "libx264" if codec == "h264" else "libx265"
        ctx = av.CodecContext.create(name, "w")
        ctx.width, ctx.height = width, height
        ctx.pix_fmt = "yuv420p"
        ctx.time_base = Fraction(1, fps)
        ctx.framerate = Fraction(fps, 1)
        ctx.bit_rate = int(bitrate_mbps * 1_000_000)
        ctx.gop_size = fps * 4
        ctx.max_b_frames = 0
        if codec == "h264":
            ctx.options = {"preset": "ultrafast", "tune": "zerolatency", "forced-idr": "1",
                           "x264-params": "repeat-headers=1:bframes=0"}
        else:
            ctx.options = {"preset": "ultrafast", "tune": "zerolatency", "forced-idr": "1",
                           "x265-params": "repeat-headers=1:bframes=0:open-gop=0:log-level=error"}
        self.ctx = ctx
        self.n = 0

    def encode(self, bgr, force_key=False):
        yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)
        frame = av.VideoFrame.from_ndarray(yuv, format="yuv420p")
        frame.pts = self.n
        self.n += 1
        if force_key:
            frame.pict_type = PictureType.I
        return [(bytes(p), bool(p.is_keyframe)) for p in self.ctx.encode(frame)]


# --- connection ----------------------------------------------------------------------------------

class Session:
    """One PC connection: reader + writer threads, outgoing queue with back-pressure."""

    def __init__(self, phone, sock, addr):
        self.phone = phone
        self.sock = sock
        self.addr = addr
        self.cv = threading.Condition()
        self.out = []                  # [(bytes, is_video)]
        self.queued_video = 0
        self.queued_bytes = 0
        self.closed = False
        self.got_hello = False
        self.streaming = False
        self.hello_at = None
        self.need_key = True
        self.dropped = 0
        self.last_rx = time.monotonic()
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.reader = threading.Thread(target=self._read, name="fake-phone-reader", daemon=True)
        self.writer = threading.Thread(target=self._write, name="fake-phone-writer", daemon=True)

    def start(self):
        self.reader.start()
        self.writer.start()

    def close(self):
        with self.cv:
            if self.closed:
                return
            self.closed = True
            self.cv.notify_all()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, data):
        with self.cv:
            if self.closed:
                return False
            self.out.append((data, False))
            self.queued_bytes += len(data)
            self.cv.notify()
        return True

    def send_json(self, mtype, obj):
        return self.send(protocol.encode_json(mtype, obj))

    def send_video(self, flags, pts_us, data, key):
        """Back-pressure: with more than 3 frames or 2 MB waiting, drop non-key frames and make the next a keyframe."""
        msg = protocol.encode_video(flags, pts_us, data)
        with self.cv:
            if self.closed:
                return False
            if not key and (self.need_key or self.queued_video >= MAX_QUEUED_FRAMES
                            or self.queued_bytes > MAX_QUEUED_BYTES):
                self.dropped += 1
                self.need_key = True
                return False
            if key:
                self.need_key = False
            self.out.append((msg, True))
            self.queued_video += 1
            self.queued_bytes += len(msg)
            self.cv.notify()
        return True

    def _write(self):
        try:
            while True:
                with self.cv:
                    while not self.out and not self.closed:
                        self.cv.wait(0.5)
                    if self.closed:
                        return
                    data, is_video = self.out.pop(0)
                self.sock.sendall(data)
                with self.cv:
                    self.queued_bytes -= len(data)
                    if is_video:
                        self.queued_video -= 1
        except OSError:
            pass
        finally:
            self.close()

    def _read(self):
        reader = protocol.FrameReader()
        try:
            while not self.closed:
                # select() rather than a socket timeout: a timeout would also apply to the writer's sendall
                readable, _, _ = select.select([self.sock], [], [], 0.5)
                if readable:
                    data = self.sock.recv(65536)
                else:
                    if time.monotonic() - self.last_rx > 10.0:
                        self.phone.log("PC silent for 10 s: closing")
                        break
                    if self.got_hello and not self.streaming and time.monotonic() - self.hello_at > 2.0:
                        self.streaming = True
                    continue
                if not data:
                    break
                self.last_rx = time.monotonic()
                for mtype, payload in reader.feed(data):
                    self.phone.handle(self, mtype, payload)
        except (OSError, ValueError, protocol.ProtocolError) as e:
            if not self.closed:
                self.phone.log(f"connection error: {e}")
        finally:
            self.close()
            self.phone.session_ended(self)


class FakePhone:
    def __init__(self, host="127.0.0.1", port=protocol.PORT, rotation=0, device="Fake iPhone 13 Pro",
                 settings=None, log=None, ios="18.1"):
        self.host, self.port = host, port
        self.rotation = int(rotation) % 360
        self.device = device
        self.ios = ios
        self.log = log or (lambda s: None)
        self.lock = threading.RLock()
        self.settings, _ = apply_settings(DEFAULT_SETTINGS, settings or {})
        self.app_active = True
        self.battery = 0.82
        self.session = None
        self.focus = None
        self.focus_until = 0.0
        self.scene = Scene()
        self._stop = threading.Event()
        self._key_request = threading.Event()
        self._server = None
        self._threads = []
        # counters for tests
        self.connections = 0
        self.frames_sent = 0
        self.keyframes_sent = 0
        self.sets = []
        self.focus_points = []
        self.keyframe_requests = 0
        self.pings = 0
        self.stream_format = None

    # -- lifecycle -------------------------------------------------------------------------------
    def start(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        srv.bind((self.host, self.port))
        srv.listen(4)
        srv.settimeout(0.3)
        self.port = srv.getsockname()[1]
        self._server = srv
        self._stop.clear()
        for target, name in ((self._accept, "fake-phone-accept"), (self._stream, "fake-phone-video"),
                             (self._ticker, "fake-phone-state")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        self.log(f"Fake iPhone listening on {self.host}:{self.port} (rotation_hint {self.rotation})")
        return self

    def stop(self):
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        with self.lock:
            sess, self.session = self.session, None
        if sess is not None:
            sess.close()
        for t in self._threads:
            t.join(2.0)
        self._threads = []

    def _accept(self):
        while not self._stop.is_set():
            try:
                sock, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sess = Session(self, sock, addr)
            with self.lock:
                old, self.session = self.session, sess
                self.connections += 1
            if old is not None:
                self.log("new PC connection replaces the old one")
                old.close()
            self.log(f"PC connected from {addr[0]}:{addr[1]}")
            sess.start()

    def session_ended(self, sess):
        with self.lock:
            if self.session is sess:
                self.session = None
                self.log("PC disconnected")

    # -- protocol --------------------------------------------------------------------------------
    def state(self):
        with self.lock:
            s = copy.deepcopy(self.settings)
            w, h = RESOLUTIONS[s["resolution"]]
            return {
                "settings": s,
                "stream": {"codec": s["codec"], "width": w, "height": h, "fps": s["fps"]},
                "cameras": copy.deepcopy(CAMERAS),
                "rotation_hint": self.rotation,
                "orientation": ORIENTATION.get(self.rotation, "unknown"),
                "battery": round(self.battery, 3),
                "charging": True,
                "thermal": "nominal",
                "app_active": self.app_active,
                "error": None,
            }

    def send_state(self):
        sess = self.session
        if sess is not None and sess.got_hello:
            sess.send_json(protocol.STATE, self.state())

    def handle(self, sess, mtype, payload):
        if mtype == protocol.HELLO:
            hello = protocol.decode_json(payload)
            self.log(f"PC HELLO {hello}")
            sess.send_json(protocol.HELLO, {"proto": 1, "app": "TacoCam", "version": "1.0",
                                            "device": self.device, "ios": self.ios})
            sess.got_hello = True
            sess.hello_at = time.monotonic()
            sess.send_json(protocol.STATE, self.state())
        elif mtype == protocol.SET:
            patch = protocol.decode_json(payload)
            with self.lock:
                self.settings, notes = apply_settings(self.settings, patch)
                self.sets.append(patch)
            for note in notes:
                sess.send(protocol.encode(protocol.LOG, f"SET ignored: {note}".encode("utf-8")))
            sess.streaming = True
            self.send_state()
        elif mtype == protocol.KEYFRAME:
            self.keyframe_requests += 1
            self._key_request.set()
        elif mtype == protocol.FOCUS_POINT:
            p = protocol.decode_json(payload)
            try:
                x, y = _clamp(_num(p["x"]), 0, 1), _clamp(_num(p["y"]), 0, 1)
            except (KeyError, ValueError):
                sess.send(protocol.encode(protocol.LOG, b"FOCUS_POINT needs x and y 0..1"))
                return
            with self.lock:
                self.focus, self.focus_until = (x, y), time.monotonic() + 3.0
                self.focus_points.append((x, y))
            self.log(f"focus point {x:.3f},{y:.3f}")
        elif mtype == protocol.PING:
            self.pings += 1
            sess.send(protocol.encode(protocol.PONG, payload))
        # anything else: ignored

    # -- "phone screen" controls ------------------------------------------------------------------
    def set_rotation(self, degrees):
        with self.lock:
            self.rotation = int(degrees) % 360
        self.send_state()

    def set_app_active(self, active):
        with self.lock:
            self.app_active = bool(active)
        self.send_state()
        self._key_request.set()

    def change_from_screen(self, patch):
        with self.lock:
            self.settings, notes = apply_settings(self.settings, patch)
        self.send_state()
        return notes

    def request_keyframe(self):
        self._key_request.set()

    # -- threads ---------------------------------------------------------------------------------
    def _ticker(self):
        while not self._stop.wait(2.0):
            with self.lock:
                self.battery = max(0.05, self.battery - 0.0005)
            self.send_state()

    def _stream(self):
        enc = None
        enc_key = None
        last_format = None
        sent_on = None
        frame_no = 0
        next_t = time.monotonic()
        while not self._stop.is_set():
            sess = self.session
            if sess is None or not sess.streaming or sess.closed or not self.app_active:
                enc, enc_key, sent_on = None, None, None
                self._stop.wait(0.02)
                next_t = time.monotonic()
                continue
            with self.lock:
                s = copy.deepcopy(self.settings)
                rotation = self.rotation
                focus = self.focus if time.monotonic() < self.focus_until else None
            w, h = RESOLUTIONS[s["resolution"]]
            fps = int(s["fps"])
            key_params = (s["codec"], w, h, fps, s["bitrate_mbps"])
            force = False
            flags = 0
            if enc is None or key_params != enc_key:
                enc = Encoder(s["codec"], w, h, fps, s["bitrate_mbps"])
                enc_key = key_params
                force = True
            fmt = (s["codec"], w, h)
            if sent_on is not sess:          # a new connection starts with a keyframe
                sent_on = sess
                force = True
                last_format = fmt
            elif fmt != last_format:
                flags |= protocol.VIDEO_FLAG_FORMAT_CHANGED
                force = True
                last_format = fmt
            if self._key_request.is_set() or sess.need_key:
                self._key_request.clear()
                force = True
            info = f"{w}x{h} {fps}fps {s['codec'].upper()} {s['bitrate_mbps']:g}Mbps"
            bgr = self.scene.render(s, w, h, rotation, frame_no, info, focus)
            frame_no += 1
            pts = int(time.monotonic() * 1e6)
            try:
                packets = enc.encode(bgr, force_key=force)
            except av.error.FFmpegError as e:
                self.log(f"encoder error: {e}")
                enc = None
                continue
            self.stream_format = fmt
            for data, is_key in packets:
                f = flags | (protocol.VIDEO_FLAG_KEYFRAME if is_key else 0)
                if sess.send_video(f, pts, data, is_key):
                    self.frames_sent += 1
                    if is_key:
                        self.keyframes_sent += 1
                    flags = 0
            next_t += 1.0 / fps
            delay = next_t - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
            elif delay < -0.5:
                next_t = time.monotonic()


# --- command line --------------------------------------------------------------------------------

def _console(phone):
    """Typed commands. Returns True for "quit"; False when input ends (keep running then: on Windows the
    NUL device looks like a terminal and is at its end at once)."""
    help_text = "commands: rotation 0|90|180|270, background, foreground, zoom N, camera back|front, torch N, quit"
    print(help_text, flush=True)
    for line in sys.stdin:
        parts = line.strip().split()
        if not parts:
            continue
        cmd, args = parts[0].lower(), parts[1:]
        try:
            if cmd in ("q", "quit", "exit"):
                return True
            elif cmd in ("rotation", "rot", "r") and args:
                phone.set_rotation(int(args[0]))
            elif cmd in ("background", "bg"):
                phone.set_app_active(False)
            elif cmd in ("foreground", "fg"):
                phone.set_app_active(True)
            elif cmd == "zoom" and args:
                phone.change_from_screen({"zoom": float(args[0])})
            elif cmd == "camera" and args:
                phone.change_from_screen({"camera": args[0]})
            elif cmd == "torch" and args:
                phone.change_from_screen({"torch": float(args[0])})
            else:
                print(help_text, flush=True)
                continue
            st = phone.state()
            print(f"ok: rotation_hint {st['rotation_hint']}, app_active {st['app_active']}, "
                  f"camera {st['settings']['camera']}, zoom {st['settings']['zoom']}, torch {st['settings']['torch']}",
                  flush=True)
        except ValueError as e:
            print(f"bad value: {e}", flush=True)
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fake iPhone for Taco Cam (speaks the contract on TCP).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=protocol.PORT)
    ap.add_argument("--rotation", type=int, default=0, choices=(0, 90, 180, 270),
                    help="STATE rotation_hint: clockwise degrees the PC must turn the picture (90 = portrait)")
    ap.add_argument("--device", default="Fake iPhone 13 Pro")
    ap.add_argument("--codec", choices=("h264", "hevc"), default=None, help="starting codec (the PC's SET wins)")
    ap.add_argument("--resolution", choices=tuple(RESOLUTIONS), default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    start = {k: v for k, v in (("codec", args.codec), ("resolution", args.resolution)) if v}
    log = (lambda s: None) if args.quiet else (lambda s: print(time.strftime("%H:%M:%S"), s, flush=True))
    try:
        phone = FakePhone(args.host, args.port, args.rotation, args.device, start, log).start()
    except OSError as e:
        print(f"Cannot listen on {args.host}:{args.port}: {e} (is another fake phone running?)", flush=True)
        return 1
    try:
        quit_typed = sys.stdin is not None and sys.stdin.isatty() and _console(phone)
        while not quit_typed:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        phone.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
