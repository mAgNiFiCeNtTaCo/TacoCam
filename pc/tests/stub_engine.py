"""A pretend Engine (CONTRACT section 6) for testing the app without the real engine or a phone.
It keeps a phone STATE, clamps the way the real phone would, and records everything the app sends."""
import copy
import threading

import numpy as np

CAM = {
    "available": True, "name": "Back Triple Camera", "min_zoom": 0.5, "max_zoom": 15.0,
    "lens_zooms": [0.5, 1.0, 3.0], "has_torch": True,
    "resolutions": ["720p", "1080p", "4k"],
    "fps": {"720p": [24, 25, 30, 60], "1080p": [24, 25, 30, 60], "4k": [24, 25, 30]},
    "iso_range": [32, 3072], "shutter_range_s": [0.00002, 0.5], "focus_manual": True, "hdr": True,
    "stabilization": ["off", "standard", "cinematic"],
}
FRONT = dict(CAM, name="Front Camera", min_zoom=1.0, max_zoom=5.0, lens_zooms=[1.0], has_torch=False,
             resolutions=["720p", "1080p"], fps={"720p": [30], "1080p": [30]}, focus_manual=False,
             hdr=False, stabilization=["off"])


def deep_update(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_update(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


def make_state(phone_settings, **over):
    st = {
        "settings": copy.deepcopy(phone_settings),
        "stream": {"codec": "h264", "width": 1920, "height": 1080, "fps": 30},
        "cameras": {"back": copy.deepcopy(CAM), "front": copy.deepcopy(FRONT)},
        "rotation_hint": 90, "orientation": "portrait", "battery": 0.82, "charging": True,
        "thermal": "nominal", "app_active": True, "error": None,
    }
    st.update(over)
    return st


class StubEngine:
    def __init__(self, settings, log=None):
        self.settings = copy.deepcopy(settings)
        self.log = log
        self.started = self.stopped = False
        self.updates = []          # every partial the app sent, in order
        self.taps = []
        self.keyframes = 0
        self.lock = threading.Lock()
        self.status = {
            "link": "searching", "transport": None, "device_name": None, "phone": None,
            "fps_in": 0.0, "fps_out": 0.0, "bitrate_mbps": 0.0, "rtt_ms": None, "dropped": 0,
            "vcam": "running", "vcam_backend": "unitycapture", "vcam_device": "Taco Cam",
            "out_size": [1920, 1080], "error": None,
        }
        self.frame = np.zeros((90, 160, 3), np.uint8)
        self.frame[:, :, 0] = np.linspace(0, 255, 160, dtype=np.uint8)[None, :]

    # -- the contract
    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def update_settings(self, partial):
        with self.lock:
            self.updates.append(copy.deepcopy(partial))
            deep_update(self.settings, partial)
            phone = self.status["phone"]
            if phone and "phone" in partial:
                s = phone["settings"]
                deep_update(s, partial["phone"])
                cam = phone["cameras"][s["camera"]]
                s["zoom"] = min(max(s["zoom"], cam["min_zoom"]), cam["max_zoom"])   # clamped like the phone
                s["bitrate_mbps"] = min(max(s["bitrate_mbps"], 2), 80)

    def get_status(self):
        with self.lock:
            return copy.deepcopy(self.status)

    def get_preview(self, max_w, max_h):
        return self.frame

    def tap_focus(self, x, y):
        self.taps.append((x, y))

    def request_keyframe(self):
        self.keyframes += 1

    # -- test helpers
    def connect_phone(self, **state_over):
        with self.lock:
            self.status.update(link="connected", transport="usb", device_name="iPhone 13 Pro",
                               fps_in=30.0, fps_out=30.0, bitrate_mbps=15.5, rtt_ms=12.0)
            self.status["phone"] = make_state(self.settings["phone"], **state_over)

    def set_status(self, **kw):
        with self.lock:
            self.status.update(kw)

    def last_update(self):
        return self.updates[-1] if self.updates else None
