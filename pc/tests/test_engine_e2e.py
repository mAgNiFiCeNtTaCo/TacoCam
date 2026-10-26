"""End to end: Engine + fake phone (Wi-Fi and USB through a fake usbmuxd), with a null virtual camera."""
import os
import socket
import sys
import threading
import time

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, HERE)
from tacocam import pipeline, protocol, vcam  # noqa: E402
from tacocam.engine import Engine  # noqa: E402
import fake_phone  # noqa: E402
from test_engine_usbmux import FakeUsbmuxd  # noqa: E402


@pytest.fixture(autouse=True)
def collect_garbage_on_main_thread():
    """Tk objects left by the app tests (same pytest run) must be freed here, on the main thread: freed by
    the garbage collector inside an engine thread, each Tk call waits ~1 s for a Tk main loop that isn't
    running and stalls the engine."""
    import gc
    gc.collect()
    yield


def wait_until(fn, timeout=8.0, step=0.02):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        last = fn()
        if last:
            return last
        time.sleep(step)
    return last


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Recorder:
    """vcam_factory that hands out NullCameras and remembers them."""

    def __init__(self):
        self.cams = []

    def __call__(self, w, h, fps, name):
        cam = vcam.NullCamera(w, h, fps, name)
        self.cams.append(cam)
        return cam

    @property
    def cam(self):
        return self.cams[-1] if self.cams else None


class Logs(list):
    def __call__(self, line):
        self.append(line)

    def has(self, text):
        return any(text in line for line in self)


def red_at(img, x0, y0, x1, y1):
    r, g, b = img[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
    return r > 170 and g < 90 and b < 90


@pytest.fixture
def phone():
    p = fake_phone.FakePhone(port=0, rotation=0).start()
    yield p
    p.stop()


def make_engine(phone_port, rec=None, logs=None, **pc):
    settings = {"pc": {"connect": "wifi", "wifi_host": f"127.0.0.1:{phone_port}", "output": "1280x720",
                       "fps_out": 30, **pc},
                "phone": {"resolution": "720p", "fps": 30}}
    eng = Engine(settings, log=logs if logs is not None else Logs(), vcam_factory=rec or Recorder())
    return eng


@pytest.fixture
def engine(phone):
    rec, logs = Recorder(), Logs()
    eng = make_engine(phone.port, rec, logs)
    eng.rec, eng.logs = rec, logs
    eng.start()
    yield eng
    eng.stop()


def connected_with_video(eng):
    st = eng.get_status()
    return st["link"] == "connected" and eng._decoder.decoded > 3


def test_connect_and_frames_at_output_size(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    st = wait_until(lambda: (lambda s: s if s["rtt_ms"] is not None and s["fps_in"] > 10 else None)(
        engine.get_status()))
    assert st["link"] == "connected" and st["transport"] == "wifi"
    assert st["device_name"] == "Fake iPhone 13 Pro"
    assert st["vcam"] == "running" and st["vcam_backend"] == "null" and st["vcam_device"] == "null:Taco Cam"
    assert st["out_size"] == [1280, 720]
    assert st["phone"]["stream"] == {"codec": "h264", "width": 1280, "height": 720, "fps": 30}
    assert st["bitrate_mbps"] > 0 and st["dropped"] == 0 and st["error"] is None
    assert 0 <= st["rtt_ms"] < 200
    cam = engine.rec.cam
    assert wait_until(lambda: cam.frames > 10)
    assert cam.last.shape == (720, 1280, 3)
    assert red_at(cam.last, 25, 25, 60, 60)          # the phone's top-left marker, landscape, 1:1
    assert wait_until(lambda: engine.get_status()["fps_out"] > 20)
    prev = engine.get_preview(320, 320)
    assert prev.shape == (180, 320, 3) and prev.dtype == np.uint8
    # handshake: PC HELLO first, then one SET with ALL phone settings
    assert phone.sets and set(phone.sets[0]) == set(fake_phone.DEFAULT_SETTINGS)


ROUND_TRIPS = [
    ({"zoom": 0.5}, lambda s, st: s["zoom"] == 0.5),
    ({"zoom": 3.0}, lambda s, st: s["zoom"] == 3.0),
    ({"zoom": 100}, lambda s, st: s["zoom"] == 15.0),                      # clamped to max_zoom
    ({"zoom_glide_s": 1}, lambda s, st: s["zoom_glide_s"] == 1),
    ({"zoom_glide_s": 9}, lambda s, st: s["zoom_glide_s"] == 3),             # clamped to 3 s
    ({"resolution": "1080p"}, lambda s, st: s["resolution"] == "1080p" and st["stream"]["width"] == 1920),
    ({"fps": 60}, lambda s, st: s["fps"] == 60 and st["stream"]["fps"] == 60),
    ({"fps": 24}, lambda s, st: s["fps"] == 24),
    ({"fps": 25}, lambda s, st: s["fps"] == 25),
    ({"codec": "hevc"}, lambda s, st: s["codec"] == "hevc" and st["stream"]["codec"] == "hevc"),
    ({"bitrate_mbps": 40}, lambda s, st: s["bitrate_mbps"] == 40),
    ({"bitrate_mbps": 500}, lambda s, st: s["bitrate_mbps"] == 80),
    ({"focus": {"mode": "manual", "position": 0.3}},
     lambda s, st: s["focus"] == {"mode": "manual", "position": 0.3}),
    ({"exposure": {"mode": "manual", "iso": 400, "shutter_s": 0.01}},
     lambda s, st: s["exposure"]["mode"] == "manual" and s["exposure"]["iso"] == 400
     and s["exposure"]["shutter_s"] == 0.01),
    ({"exposure": {"mode": "auto", "bias": 1.5, "iso": None, "shutter_s": None}},
     lambda s, st: s["exposure"] == {"mode": "auto", "bias": 1.5, "iso": None, "shutter_s": None}),
    ({"exposure": {"bias": -9}}, lambda s, st: s["exposure"]["bias"] == -3.0),
    ({"white_balance": {"mode": "manual", "temperature": 3200, "tint": 20}},
     lambda s, st: s["white_balance"] == {"mode": "manual", "temperature": 3200, "tint": 20}),
    ({"torch": 0.5}, lambda s, st: s["torch"] == 0.5),
    ({"stabilization": "cinematic"}, lambda s, st: s["stabilization"] == "cinematic"),
    ({"hdr": True}, lambda s, st: s["hdr"] is True),
    ({"screen": "dim"}, lambda s, st: s["screen"] == "dim"),
    ({"anti_flicker": "60hz"}, lambda s, st: s["anti_flicker"] == "60hz" and st["live"]["shutter_s"] == round(1 / 60, 6)),
    ({"anti_flicker": "bogus"}, lambda s, st: s["anti_flicker"] == "60hz"),
    ({"anti_flicker": "off"}, lambda s, st: s["anti_flicker"] == "off"),
    ({"camera": "front"}, lambda s, st: s["camera"] == "front" and s["torch"] == 0.0 and s["zoom"] >= 1.0
     and s["stabilization"] in ("off", "standard") and s["focus"]["mode"] == "auto"),
    ({"zoom": 0.5}, lambda s, st: s["zoom"] == 1.0),                       # front camera: no 0.5x
    ({"camera": "back", "zoom": 0.5, "codec": "h264", "resolution": "720p"},
     lambda s, st: s["camera"] == "back" and s["zoom"] == 0.5 and st["stream"]["width"] == 1280),
    ({"screen": "normal", "hdr": False, "torch": 0.0},
     lambda s, st: s["screen"] == "normal" and s["hdr"] is False and s["torch"] == 0.0),
]


def test_set_state_round_trip_every_phone_setting(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    keys_covered = set()
    for patch, check in ROUND_TRIPS:
        engine.update_settings({"phone": patch})
        keys_covered |= set(patch)

        def ok():
            st = engine.get_status()["phone"]
            return st is not None and check(st["settings"], st)
        assert wait_until(ok, timeout=5), f"STATE did not reflect {patch}: {engine.get_status()['phone']['settings']}"
    assert keys_covered == set(fake_phone.DEFAULT_SETTINGS)
    # video still decodes after all the codec/size changes
    n = engine._decoder.decoded
    assert wait_until(lambda: engine._decoder.decoded > n + 10)
    assert engine._decoder.latest()[1].shape == (720, 1280, 3)


def test_nested_settings_are_sent_whole(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    engine.update_settings({"phone": {"focus": {"mode": "manual"}}})
    assert wait_until(lambda: phone.sets and phone.sets[-1].get("focus") == {"mode": "manual", "position": 0.5})


def test_codec_switch_mid_stream_keeps_picture(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    engine.update_settings({"phone": {"codec": "hevc", "resolution": "1080p"}})
    assert wait_until(lambda: engine._decoder.latest() and engine._decoder.latest()[1].shape == (1080, 1920, 3))
    n = engine._decoder.decoded
    assert wait_until(lambda: engine._decoder.decoded > n + 10)
    assert engine._decoder.errors == 0


def test_output_size_and_fps_change_restart_vcam(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    first = engine.rec.cam
    engine.update_settings({"pc": {"output": "1080x1920", "fps_out": 60}})
    assert wait_until(lambda: engine.rec.cam is not first and engine.rec.cam.frames > 5)
    assert first.closed
    cam = engine.rec.cam
    assert (cam.width, cam.height, cam.fps) == (1080, 1920, 60)
    assert cam.last.shape == (1920, 1080, 3)
    assert engine.get_status()["out_size"] == [1080, 1920]
    assert wait_until(lambda: engine.get_status()["fps_out"] > 45)


@pytest.mark.parametrize("rotation", [90, 270, 180])
def test_auto_rotation_uses_rotation_hint(rotation):
    p = fake_phone.FakePhone(port=0, rotation=rotation).start()
    portrait = rotation in (90, 270)
    eng = make_engine(p.port, output="1080x1920" if portrait else "1920x1080", fit="fit")
    eng.update_settings({"phone": {"resolution": "1080p"}})
    rec = eng._vcam_factory
    eng.start()
    try:
        assert wait_until(lambda: connected_with_video(eng) and rec.cam and rec.cam.frames > 3)
        time.sleep(0.2)
        out = rec.cam.last
        assert red_at(out, 30, 30, 90, 90), "upright picture's top-left marker must be top-left in the output"
        # a fixed rotation overrides the hint: turning a further 180 puts the marker bottom-right
        fixed = (rotation + 180) % 360
        eng.update_settings({"pc": {"rotate": fixed}})
        h, w = out.shape[:2]
        assert wait_until(lambda: red_at(rec.cam.last, w - 90, h - 90, w - 30, h - 30))
    finally:
        eng.stop()
        p.stop()


def test_hint_change_while_running(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    engine.update_settings({"pc": {"fit": "fit"}})
    phone.set_rotation(90)
    # portrait picture fitted into 1280x720: black bars left and right, marker top-left of the picture
    assert wait_until(lambda: engine.get_status()["phone"]["rotation_hint"] == 90)
    time.sleep(0.3)
    out = engine.rec.cam.last
    assert (out[:, :100] == 0).all()
    left = (1280 - 720 * 720 // 1280) // 2
    assert red_at(out, left + 15, 15, left + 35, 35)


@pytest.mark.parametrize("mirror", [False, True])
def test_tap_focus_maps_to_sensor(mirror):
    p = fake_phone.FakePhone(port=0, rotation=90).start()
    eng = make_engine(p.port, output="1080x1920", fit="crop", mirror=mirror)
    eng.update_settings({"phone": {"resolution": "1080p"}})
    eng.start()
    try:
        assert wait_until(lambda: connected_with_video(eng) and eng._last_transform is not None)
        res = eng.tap_focus(0.25, 0.1)
        assert res is not None
        assert wait_until(lambda: p.focus_points)
        fx, fy = p.focus_points[-1]
        # output = sensor turned 90 clockwise, same size: (x, y) -> sensor (y, 1 - x); mirror flips x first
        x = 0.75 if mirror else 0.25
        assert abs(fx - 0.1) < 1e-3 and abs(fy - (1 - x)) < 1e-3
    finally:
        eng.stop()
        p.stop()


def test_keyframe_request_reaches_phone(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    n = phone.keyframes_sent
    engine.request_keyframe()
    assert wait_until(lambda: phone.keyframe_requests >= 1 and phone.keyframes_sent > n)


def test_phone_log_reaches_engine_log(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    engine.update_settings({"phone": {"zoom": "very close"}})
    assert wait_until(lambda: engine.logs.has("iPhone: SET ignored: zoom"))


def test_reconnect_after_phone_restarts():
    port = free_port()
    p = fake_phone.FakePhone(port=port).start()
    rec, logs = Recorder(), Logs()
    eng = make_engine(port, rec, logs)
    eng.start()
    try:
        assert wait_until(lambda: connected_with_video(eng))
        p.stop()
        assert wait_until(lambda: eng.get_status()["link"] != "connected", timeout=7)
        assert eng.get_status()["phone"] is None
        p = fake_phone.FakePhone(port=port).start()
        n = eng._decoder.decoded
        assert wait_until(lambda: eng.get_status()["link"] == "connected", timeout=8)
        assert wait_until(lambda: eng._decoder.decoded > n + 5)
        assert p.connections == 1 and p.sets, "new phone got a fresh handshake with a full SET"
        assert logs.has("iPhone disconnected")
    finally:
        eng.stop()
        p.stop()


def test_dead_connection_detected_after_5s():
    """A 'phone' that answers HELLO and then goes silent is dropped after 5 s."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    accepted = []

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            accepted.append(c)
            c.sendall(protocol.encode_json(protocol.HELLO, {"proto": 1, "app": "TacoCam", "version": "1.0",
                                                            "device": "Silent iPhone", "ios": "18"}))
    threading.Thread(target=serve, daemon=True).start()
    logs = Logs()
    eng = make_engine(srv.getsockname()[1], logs=logs)
    eng.start()
    try:
        assert wait_until(lambda: eng.get_status()["link"] == "connected", timeout=4)
        t0 = time.monotonic()
        assert wait_until(lambda: logs.has("no answer from the iPhone for 5 s"), timeout=8)
        assert 4.0 < time.monotonic() - t0 < 7.0
        assert wait_until(lambda: len(accepted) >= 2, timeout=4), "engine reconnects"
    finally:
        eng.stop()
        srv.close()


def test_stop_within_2s_while_connected(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    t0 = time.monotonic()
    engine.stop()
    assert time.monotonic() - t0 < 2.0
    assert engine.rec.cam.closed
    names = [t.name for t in threading.enumerate() if t.name.startswith("tacocam-") and t.is_alive()]
    assert names == []
    assert engine.get_status()["vcam"] == "stopped"


def test_stop_within_2s_while_connecting_to_unreachable_host():
    eng = Engine({"pc": {"connect": "wifi", "wifi_host": "10.255.255.1"}}, vcam_factory=vcam.null_factory)
    eng.start()
    time.sleep(0.3)
    t0 = time.monotonic()
    eng.stop()
    assert time.monotonic() - t0 < 2.0


def test_start_stop_start_again(phone):
    eng = make_engine(phone.port)
    for _ in range(2):
        eng.start()
        assert wait_until(lambda: connected_with_video(eng))
        eng.stop()


def test_waiting_card_and_disconnected_modes():
    port = free_port()            # nothing listens there
    rec = Recorder()
    eng = make_engine(port, rec)
    eng.start()
    try:
        assert wait_until(lambda: rec.cam and rec.cam.frames > 2)
        card = pipeline.make_card(1280, 720, "wifi", host="127.0.0.1")
        assert wait_until(lambda: np.array_equal(rec.cam.last, card))
        assert eng.get_status()["link"] in ("searching", "no_app")
        eng.update_settings({"pc": {"when_disconnected": "black"}})
        assert wait_until(lambda: not rec.cam.last.any())
        eng.update_settings({"pc": {"wifi_host": ""}})
        eng.update_settings({"pc": {"when_disconnected": "card"}})
        nohost = pipeline.make_card(1280, 720, "wifi_nohost")
        assert wait_until(lambda: np.array_equal(rec.cam.last, nohost))
        st = wait_until(lambda: (lambda s: s if s["link"] == "error" else None)(eng.get_status()))
        assert "IP address" in st["error"]
    finally:
        eng.stop()


def test_freeze_last_frame_when_disconnected():
    port = free_port()
    p = fake_phone.FakePhone(port=port).start()
    rec = Recorder()
    eng = make_engine(port, rec, when_disconnected="last")
    eng.start()
    try:
        assert wait_until(lambda: connected_with_video(eng))
        time.sleep(0.3)
        p.stop()
        assert wait_until(lambda: eng.get_status()["link"] != "connected", timeout=7)
        time.sleep(0.3)
        frozen = rec.cam.last.copy()
        time.sleep(0.3)
        assert np.array_equal(rec.cam.last, frozen)
        assert red_at(frozen, 25, 25, 60, 60)       # still the phone picture, not the card
    finally:
        eng.stop()
        p.stop()


def test_app_in_background_shows_card(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    phone.set_app_active(False)
    card = pipeline.make_card(1280, 720, "background")
    assert wait_until(lambda: np.array_equal(engine.rec.cam.last, card))
    assert engine.get_status()["link"] == "connected"
    phone.set_app_active(True)
    assert wait_until(lambda: red_at(engine.rec.cam.last, 25, 25, 60, 60))


def test_vcam_not_installed_status_and_preview_still_works(phone):
    def factory(w, h, fps, name):
        raise vcam.VcamNotInstalled("The Taco Cam camera is not installed: run the install script")
    logs = Logs()
    eng = Engine({"pc": {"connect": "wifi", "wifi_host": f"127.0.0.1:{phone.port}"}}, log=logs,
                 vcam_factory=factory)
    eng.start()
    try:
        assert wait_until(lambda: connected_with_video(eng))
        st = eng.get_status()
        assert st["vcam"] == "not_installed" and st["vcam_backend"] is None
        assert "not installed" in st["error"]
        assert wait_until(lambda: eng.get_preview(640, 360) is not None)
        assert eng.get_preview(640, 360).shape == (360, 640, 3)
    finally:
        eng.stop()


def test_usb_mode_through_usbmuxd():
    port = free_port()               # the phone's 47777, reached through the fake usbmuxd
    mux = FakeUsbmuxd()
    logs = Logs()
    rec = Recorder()
    eng = Engine({"pc": {"connect": "usb", "output": "1280x720"}, "phone": {"resolution": "720p"}}, log=logs,
                 usbmux_address=mux.address, vcam_factory=rec)
    eng.start()
    p = None
    try:
        assert wait_until(lambda: eng.get_status()["link"] == "searching")
        assert wait_until(lambda: rec.cam and np.array_equal(rec.cam.last, pipeline.make_card(1280, 720, "usb")))
        mux.attach(11, "00008101-000A1B2C3D4E5F60", "Network", ports={47777: ("127.0.0.1", port)})
        time.sleep(1.5)
        assert eng.get_status()["link"] == "searching", "Wi-Fi-synced devices are not used in usb mode"
        mux.attach(12, "00008101-000A1B2C3D4E5F61", "USB", ports={47777: ("127.0.0.1", port)})
        st = wait_until(lambda: (lambda s: s if s["link"] == "no_app" else None)(eng.get_status()))
        assert st["transport"] == "usb" and st["device_name"] == "0000...5F61"
        assert wait_until(lambda: np.array_equal(rec.cam.last, pipeline.make_card(1280, 720, "no_app")))
        p = fake_phone.FakePhone(port=port, device="USB Fake iPhone").start()
        assert wait_until(lambda: connected_with_video(eng), timeout=8)
        st = eng.get_status()
        assert st["transport"] == "usb" and st["device_name"] == "USB Fake iPhone"
        assert wait_until(lambda: red_at(rec.cam.last, 25, 25, 60, 60))
        # unplug: the pipe closes, the engine goes back to searching
        mux.detach(12)
        p.stop()
        p = None
        assert wait_until(lambda: eng.get_status()["link"] == "searching", timeout=8)
    finally:
        eng.stop()
        if p:
            p.stop()
        mux.close()


def test_usbmuxd_missing_is_an_error():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    addr = s.getsockname()
    s.close()
    eng = Engine({"pc": {"connect": "usb"}}, usbmux_address=addr, vcam_factory=vcam.null_factory)
    eng.start()
    try:
        st = wait_until(lambda: (lambda s: s if s["link"] == "error" else None)(eng.get_status()))
        assert "Apple Mobile Device Service" in st["error"]
    finally:
        eng.stop()


def test_switch_usb_to_wifi_at_runtime(phone):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    addr = s.getsockname()
    s.close()
    eng = Engine({"pc": {"connect": "usb"}}, usbmux_address=addr, vcam_factory=vcam.null_factory)
    eng.start()
    try:
        assert wait_until(lambda: eng.get_status()["link"] == "error")
        eng.update_settings({"pc": {"connect": "wifi", "wifi_host": f"127.0.0.1:{phone.port}"}})
        assert wait_until(lambda: connected_with_video(eng))
        assert eng.get_status()["transport"] == "wifi"
    finally:
        eng.stop()


def test_fake_phone_command_line():
    """The demo way: python pc/tools/fake_phone.py --rotation 90 (here on a free port)."""
    import subprocess
    port = free_port()
    script = os.path.join(HERE, "..", "tools", "fake_phone.py")
    proc = subprocess.Popen([sys.executable, script, "--port", str(port), "--rotation", "90", "--quiet"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    eng = make_engine(port)
    try:
        eng.start()
        assert wait_until(lambda: connected_with_video(eng), timeout=15)
        assert eng.get_status()["phone"]["rotation_hint"] == 90
        assert eng.get_status()["phone"]["orientation"] == "portrait"
    finally:
        eng.stop()
        proc.kill()
        proc.wait(5)
