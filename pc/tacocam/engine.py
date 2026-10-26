"""Taco Cam engine: phone link + decoder + picture pipeline + virtual camera (CONTRACT section 6).

    eng = Engine(settings, log=print)
    eng.start(); ...; eng.stop()

Thread-safe; no method blocks the caller for long (the UI thread calls these).
Threads: tacocam-link (+ its writer), tacocam-decoder, tacocam-output (renders at pc.fps_out and feeds the
virtual camera; repeats the last frame when the phone is slower; shows the "waiting" card when there is
no picture).
"""
import collections
import copy
import threading
import time
from pathlib import Path

import numpy as np

from . import pipeline, protocol
from .decoder import Decoder
from .link import Link, split_host
from . import vcam as vcam_mod
from .clips import ClipBuffer, clip_name, clips_folder, write_mp4

DEFAULT_SETTINGS = {
    "phone": {
        "camera": "back", "zoom": 1.0, "resolution": "1080p", "fps": 30, "codec": "h264", "bitrate_mbps": 16,
        "focus": {"mode": "auto", "position": 0.5},
        "exposure": {"mode": "auto", "bias": 0.0, "iso": None, "shutter_s": None},
        "white_balance": {"mode": "auto", "temperature": 5000, "tint": 0},
        "torch": 0.0, "stabilization": "off", "hdr": False, "screen": "normal", "anti_flicker": "off",
    },
    "pc": {
        "connect": "usb", "wifi_host": "", "rotate": "auto", "mirror": False, "flip": False,
        "output": "1920x1080", "fit": "crop", "fps_out": 30, "vcam_name": "Taco Cam",
        "when_disconnected": "card",
    },
}

VIDEO_STALE_S = 3.0          # no new picture for this long = treat as disconnected (card / last / black)
VCAM_RETRY_S = 5.0


def _merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


class RateMeter:
    """Events (and amounts) per second over the last `window` seconds."""

    def __init__(self, window=2.0):
        self.window = window
        self._ev = collections.deque()
        self._lock = threading.Lock()

    def add(self, amount=1.0, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            self._ev.append((now, amount))
            self._trim(now)

    def _trim(self, now):
        while self._ev and now - self._ev[0][0] > self.window:
            self._ev.popleft()

    def rate(self, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            self._trim(now)
            if not self._ev:
                return 0.0
            total = sum(a for _, a in self._ev)
            span = max(now - self._ev[0][0], 0.5) if len(self._ev) > 1 else self.window
            if len(self._ev) > 1:
                total -= self._ev[0][1]   # n events span n-1 intervals
            return total / span

    def clear(self):
        with self._lock:
            self._ev.clear()


class Engine:
    def __init__(self, settings, log=None, *, port=protocol.PORT, usbmux_address=None, vcam_factory=None):
        """settings: same shape as settings.json (missing keys use the defaults).
        port / usbmux_address / vcam_factory are for tests (vcam_factory=tacocam.vcam.null_factory)."""
        self._lock = threading.RLock()
        self._settings = _merge(copy.deepcopy(DEFAULT_SETTINGS), settings or {})
        self._user_log = log
        self._log_lock = threading.Lock()
        self.port = port
        self.usbmux_address = usbmux_address
        self._vcam_factory = vcam_factory or vcam_mod.open_camera
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._running = False
        self._link = None
        self._decoder = None
        self._out_thread = None
        self._phone_state = None
        self._latest_out = None
        self._last_transform = None
        self._vcam = None
        self._vcam_status = "stopped"
        self._vcam_error = None
        self._vcam_reopen = True
        self._error = None
        self._fps_in = RateMeter()
        self._clips = ClipBuffer()
        self._fps_out = RateMeter()
        self._bytes_in = RateMeter()

    # -- logging ---------------------------------------------------------------------------------
    def _log(self, text):
        fn = self._user_log
        if fn is None:
            return
        with self._log_lock:
            try:
                fn(str(text))
            except Exception:
                pass

    # -- public API ------------------------------------------------------------------------------
    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop.clear()
            pc = self._settings["pc"]
            self._decoder = Decoder(request_keyframe=self.request_keyframe, log=self._log,
                                    codec=self._settings["phone"].get("codec", "h264"))
            self._decoder.start()
            self._link = Link(connect=pc.get("connect", "usb"), wifi_host=pc.get("wifi_host", ""),
                              port=self.port, usbmux_address=self.usbmux_address, log=self._log,
                              on_hello=self._on_hello, on_state=self._on_state, on_video=self._on_video,
                              on_log=self._on_phone_log, on_connected=self._on_connected,
                              on_disconnected=self._on_disconnected, get_phone_settings=self._phone_settings)
            self._link.start()
            self._vcam_reopen = True
            self._out_thread = threading.Thread(target=self._output_loop, name="tacocam-output", daemon=True)
            self._out_thread.start()
        self._log("Taco Cam engine started")

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            link, dec, out_thread = self._link, self._decoder, self._out_thread
        deadline = time.monotonic() + 1.8
        threads = [out_thread, link._thread, dec._thread if dec else None]
        # Wake every thread and close the socket first, then wait for them all against one deadline.
        self._stop.set()
        self._wake.set()
        link.signal_stop()
        if dec is not None:
            dec.signal_stop()
        for t in threads:
            if t is not None:
                t.join(max(0.0, deadline - time.monotonic()))
        link._thread = None
        if dec is not None:
            dec._thread = None
        with self._lock:
            cam, self._vcam = self._vcam, None
        if cam is not None:
            cam.close()
        with self._lock:
            self._vcam_status = "stopped"
            self._phone_state = None
        self._log("Taco Cam engine stopped")

    def update_settings(self, partial):
        if not isinstance(partial, dict):
            return
        phone_set = {}
        with self._lock:
            phone = partial.get("phone")
            if isinstance(phone, dict) and phone:
                _merge(self._settings["phone"], phone)
                for key in phone:  # nested objects (focus, exposure, white_balance) are sent whole
                    phone_set[key] = copy.deepcopy(self._settings["phone"][key])
            pc = partial.get("pc")
            target = None
            if isinstance(pc, dict) and pc:
                old = dict(self._settings["pc"])
                _merge(self._settings["pc"], pc)
                new = self._settings["pc"]
                if old.get("connect") != new.get("connect") or old.get("wifi_host") != new.get("wifi_host"):
                    target = (new.get("connect"), new.get("wifi_host"))
                if any(old.get(k) != new.get(k) for k in ("output", "fps_out", "vcam_name")):
                    self._vcam_reopen = True
                    self._wake.set()
            link, dec = self._link, self._decoder
        if phone_set and link is not None:
            if "codec" in phone_set and dec is not None:
                dec.set_codec_hint(phone_set["codec"])
            link.send_set(phone_set)
        if target is not None and link is not None:
            link.set_target(*target)

    def get_status(self):
        with self._lock:
            link = self._link
            pc = self._settings["pc"]
            out_size = list(pipeline.parse_size(pc.get("output")))
            cam = self._vcam
            status = {
                "link": link.state if link and self._running else "searching",
                "transport": link.transport if link and self._running else None,
                "device_name": link.device_name if link and self._running else None,
                "phone": copy.deepcopy(self._phone_state),
                "fps_in": round(self._fps_in.rate(), 1),
                "fps_out": round(self._fps_out.rate(), 1),
                "bitrate_mbps": round(self._bytes_in.rate() * 8 / 1e6, 2),
                "rtt_ms": round(link.rtt_ms, 1) if link and link.rtt_ms is not None else None,
                "dropped": self._decoder.dropped if self._decoder else 0,
                "vcam": self._vcam_status,
                "vcam_backend": cam.backend if cam is not None else None,
                "vcam_device": cam.device if cam is not None else None,
                "out_size": out_size,
                "error": None,
            }
            errors = [e for e in (link.error if link and self._running else None, self._vcam_error,
                                  (self._phone_state or {}).get("error")) if e]
            status["error"] = errors[0] if errors else None
        if not self._running:
            status["link"] = "searching"
            status["vcam"] = "stopped"
        return status

    def get_preview(self, max_w, max_h):
        frame = self._latest_out
        if frame is None:
            return None
        return pipeline.scale_to_fit(frame, max(1, int(max_w)), max(1, int(max_h)))

    def tap_focus(self, x, y):
        """x, y 0..1 on the OUTPUT frame -> FOCUS_POINT in sensor coordinates. Returns (sx, sy) or None."""
        x = min(max(float(x), 0.0), 1.0)
        y = min(max(float(y), 0.0), 1.0)
        tr = self._last_transform or self._make_transform(None)
        sx, sy = tr.out_to_sensor(x, y)
        link = self._link
        if link is None or not link.send_focus(sx, sy):
            return None
        return sx, sy

    def save_clip(self, seconds=30, rotation=0, folder=None):
        """Writes the last `seconds` of the phone's video to an MP4 (no re-encoding). Blocking (call it from a
        worker thread). Returns (path, length in seconds); raises ValueError when there is nothing to save."""
        packets = self._clips.take(seconds)
        if not packets:
            raise ValueError("no video from the iPhone yet")
        path = Path(folder or clips_folder()) / clip_name()
        length = write_mp4(path, packets, rotation)
        self._log(f"Saved clip {path.name} ({length:.0f} s)")
        return path, length

    def clip_seconds(self):
        """How many seconds of video are ready to save."""
        return self._clips.seconds()

    def request_keyframe(self):
        link = self._link
        if link is not None:
            link.send_keyframe()

    # -- link callbacks (link thread) ------------------------------------------------------------
    def _phone_settings(self):
        with self._lock:
            return copy.deepcopy(self._settings["phone"])

    def _on_hello(self, hello):
        pass

    def _on_connected(self):
        dec = self._decoder
        if dec is not None:
            dec.reset()
            dec.clear_latest()
        self._fps_in.clear()
        self._bytes_in.clear()

    def _on_disconnected(self):
        with self._lock:
            self._phone_state = None
        self._fps_in.clear()
        self._bytes_in.clear()

    def _on_state(self, state):
        with self._lock:
            prev = self._phone_state
            self._phone_state = state
        stream = state.get("stream") if isinstance(state, dict) else None
        if isinstance(stream, dict) and self._decoder is not None:
            self._decoder.set_codec_hint(stream.get("codec"))
        if prev is None or prev.get("app_active") != state.get("app_active"):
            if state.get("app_active") is False:
                self._log("Taco Cam app is in the background on the iPhone - open it again")
        if state.get("error") and (prev is None or prev.get("error") != state.get("error")):
            self._log(f"iPhone: {state.get('error')}")

    def _on_video(self, flags, pts_us, data, nbytes):
        now = time.monotonic()
        self._fps_in.add(1, now)
        self._bytes_in.add(nbytes, now)
        self._clips.add(flags, pts_us, data)
        dec = self._decoder
        if dec is not None:
            dec.submit(flags, pts_us, data)

    def _on_phone_log(self, text):
        self._log(f"iPhone: {text}")

    # -- output loop -----------------------------------------------------------------------------
    def _make_transform(self, frame_shape):
        with self._lock:
            pc = dict(self._settings["pc"])
            hint = (self._phone_state or {}).get("rotation_hint", 0)
            stream = (self._phone_state or {}).get("stream") or {}
        if frame_shape is not None:
            src_h, src_w = frame_shape[:2]
        else:
            src_w, src_h = int(stream.get("width") or 1920), int(stream.get("height") or 1080)
        ow, oh = pipeline.parse_size(pc.get("output"))
        rot = pipeline.effective_rotation(pc.get("rotate", "auto"), hint)
        return pipeline.Transform(src_w, src_h, ow, oh, rot, pc.get("mirror"), pc.get("flip"), pc.get("fit"))

    def _card_kind(self):
        link = self._link
        with self._lock:
            pc = self._settings["pc"]
            state = self._phone_state
            connect, host = pc.get("connect"), pc.get("wifi_host")
        if link is not None and link.state == "connected" and state and state.get("app_active") is False:
            return "background", {}
        if link is not None and link.state == "no_app":
            return "no_app", {}
        if link is not None and link.state == "error" and connect != "wifi" and link.error:
            return "error", {"error": link.error}
        if connect == "wifi":
            h, _port = split_host(host)
            if not h:
                return "wifi_nohost", {}
            return "wifi", {"host": h}
        return "usb", {}

    def _open_vcam(self, w, h, fps, name):
        try:
            cam = self._vcam_factory(w, h, fps, name)
        except vcam_mod.VcamNotInstalled as e:
            return None, "not_installed", str(e)
        except Exception as e:
            return None, "error", str(e)
        return cam, "running", None

    def _output_loop(self):
        last_seq = None
        last_key = None
        last_video_out = None
        current = None
        next_vcam_try = 0.0
        next_unity_check = time.monotonic() + 10.0
        cfg = None
        next_t = time.monotonic()
        try:
            while not self._stop.is_set():
                try:
                    with self._lock:
                        pc = self._settings["pc"]
                        ow, oh = pipeline.parse_size(pc.get("output"))
                        fps = pc.get("fps_out") or 30
                        try:
                            fps = min(max(float(fps), 1.0), 120.0)
                        except (TypeError, ValueError):
                            fps = 30.0
                        name = pc.get("vcam_name") or "Taco Cam"
                        mode = pc.get("when_disconnected", "card")
                        reopen = self._vcam_reopen
                        self._vcam_reopen = False
                    new_cfg = (ow, oh, fps, name)
                    now = time.monotonic()
                    # (re)open the virtual camera
                    if reopen or new_cfg != cfg:
                        if self._vcam is not None:
                            old = self._vcam
                            with self._lock:
                                self._vcam = None
                            old.close()
                        cfg = new_cfg
                        next_vcam_try = 0.0
                        last_key = None
                    if self._vcam is None and now >= next_vcam_try:
                        cam, st, err = self._open_vcam(ow, oh, fps, name)
                        with self._lock:
                            changed = st != self._vcam_status or err != self._vcam_error
                            self._vcam, self._vcam_status, self._vcam_error = cam, st, err
                        if cam is not None:
                            self._log(f"Virtual camera on: {cam.device} ({cam.backend}, {ow}x{oh} @ {fps:g} fps)")
                            if cam.backend == "obs":
                                self._log("Using OBS Virtual Camera: don't press OBS's own Start Virtual Camera "
                                          "button. Install the Taco Cam camera to avoid this.")
                        elif changed:
                            self._log(f"Virtual camera: {err}")
                        next_vcam_try = now + VCAM_RETRY_S
                    elif (self._vcam is not None and self._vcam.backend == "obs" and now >= next_unity_check):
                        next_unity_check = now + 10.0
                        if vcam_mod.unitycapture_registered_name() == name:
                            self._log("Taco Cam camera is now installed: switching to it")
                            with self._lock:
                                self._vcam_reopen = True
                            continue

                    # pick the picture
                    dec = self._decoder
                    latest = dec.latest() if dec is not None else None
                    link = self._link
                    state = self._phone_state
                    video_ok = (latest is not None and link is not None and link.state == "connected"
                                and now - latest[3] < VIDEO_STALE_S and not (state and state.get("app_active") is False))
                    frame = None
                    if video_ok:
                        seq, rgb = latest[0], latest[1]
                        tr = self._make_transform(rgb.shape)
                        key = (seq, tr.key())
                        if key != last_key or last_video_out is None:
                            try:
                                frame = tr.apply(rgb)
                            except Exception as e:
                                self._log(f"Picture processing error: {e!r}")
                                frame = None
                            if frame is not None:
                                last_video_out, last_key = frame, key
                                self._last_transform = tr
                        else:
                            frame = last_video_out
                    if frame is None:
                        if mode == "last" and last_video_out is not None and last_video_out.shape[:2] == (oh, ow):
                            frame = last_video_out
                        elif mode == "black":
                            frame = pipeline.black(ow, oh)
                        else:
                            kind, fields = self._card_kind()
                            frame = pipeline.make_card(ow, oh, kind, **fields)
                    self._latest_out = frame

                    cam = self._vcam
                    if cam is not None:
                        try:
                            cam.send(frame)
                            self._fps_out.add(1)
                        except Exception as e:
                            self._log(f"Virtual camera stopped: {e}")
                            with self._lock:
                                self._vcam = None
                                self._vcam_status, self._vcam_error = "error", str(e)
                            cam.close()
                            next_vcam_try = time.monotonic() + VCAM_RETRY_S
                    else:
                        self._fps_out.add(1)

                    # pacing: steady fps_out, catch up at most one frame
                    next_t += 1.0 / fps
                    now = time.monotonic()
                    if next_t < now - 1.0 / fps:
                        next_t = now
                    delay = next_t - now
                    if delay > 0:
                        self._wake.wait(delay)
                        self._wake.clear()
                except Exception as e:  # one bad frame must not stop the camera
                    self._log(f"Output error: {e!r}")
                    with self._lock:
                        self._error = str(e)
                    self._stop.wait(0.5)
                    next_t = time.monotonic()
        finally:
            cam = self._vcam
            if cam is not None:
                with self._lock:
                    self._vcam = None
                cam.close()
