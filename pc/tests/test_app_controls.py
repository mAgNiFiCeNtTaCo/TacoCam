import json
import time

import pytest

from conftest import pump
from tacocam import settings as S
from tacocam.app import acquire_single_instance, describe_status

# (control path, value the user picks, the partial the engine must receive)
CASES = [
    ("phone.camera", "front", {"phone": {"camera": "front"}}),
    ("phone.zoom", 3.0, {"phone": {"zoom": 3.0}}),
    ("phone.resolution", "4k", {"phone": {"resolution": "4k"}}),
    ("phone.fps", 60, {"phone": {"fps": 60}}),
    ("phone.codec", "hevc", {"phone": {"codec": "hevc"}}),
    ("phone.bitrate_mbps", 40, {"phone": {"bitrate_mbps": 40}}),
    ("phone.focus.position", 0.8, {"phone": {"focus": {"position": 0.8}}}),
    ("phone.exposure.bias", -1.5, {"phone": {"exposure": {"bias": -1.5}}}),
    ("phone.white_balance.temperature", 3200, {"phone": {"white_balance": {"temperature": 3200}}}),
    ("phone.white_balance.tint", -20, {"phone": {"white_balance": {"tint": -20}}}),
    ("phone.torch", 0.5, {"phone": {"torch": 0.5}}),
    ("phone.stabilization", "standard", {"phone": {"stabilization": "standard"}}),
    ("phone.hdr", True, {"phone": {"hdr": True}}),
    ("phone.screen", "dim", {"phone": {"screen": "dim"}}),
    ("pc.connect", "wifi", {"pc": {"connect": "wifi"}}),
    ("pc.wifi_host", "192.168.1.23", {"pc": {"wifi_host": "192.168.1.23"}}),
    ("pc.rotate", 270, {"pc": {"rotate": 270}}),
    ("pc.rotate", "auto", {"pc": {"rotate": "auto"}}),
    ("pc.mirror", True, {"pc": {"mirror": True}}),
    ("pc.flip", True, {"pc": {"flip": True}}),
    ("pc.output", "1080x1920", {"pc": {"output": "1080x1920"}}),
    ("pc.fit", "stretch", {"pc": {"fit": "stretch"}}),
    ("pc.fps_out", 60, {"pc": {"fps_out": 60}}),
    ("pc.when_disconnected", "black", {"pc": {"when_disconnected": "black"}}),
]


@pytest.fixture
def app(stub_app):
    stub_app.engine.connect_phone()
    stub_app.refresh_from_status(force=True)
    return stub_app


@pytest.mark.parametrize("path,value,expected", CASES)
def test_control_sends_the_right_key(app, path, value, expected):
    ctl = app.ctl[path]
    app.engine.updates.clear()
    ctl.select(value)
    assert app.engine.last_update() == expected
    assert S.get_path(app.settings, path) == value        # remembered for settings.json


def test_every_settings_key_has_a_control(app):
    leaves = []

    def walk(d, prefix):
        for k, v in d.items():
            p = f"{prefix}.{k}" if prefix else k
            walk(v, p) if isinstance(v, dict) else leaves.append(p)
    walk(S.DEFAULTS, "")
    missing = [p for p in leaves if p not in app.ctl and p not in ("pc.vcam_name", "phone.exposure.iso", "phone.exposure.shutter_s")]
    assert missing == []
    assert "phone.exposure.iso" in app.ctl and "phone.exposure.shutter_s" in app.ctl


def test_manual_modes_send_their_values_too(app):
    app.ctl["phone.exposure.iso"].show(400)
    app.ctl["phone.exposure.shutter_s"].show(1 / 120)
    app.ctl["phone.exposure.mode"].select("manual")
    ex = app.engine.last_update()["phone"]["exposure"]
    assert ex["mode"] == "manual" and ex["iso"] == 400 and abs(ex["shutter_s"] - 1 / 120) < 1e-3
    app.ctl["phone.focus.position"].show(0.3)
    app.ctl["phone.focus.mode"].select("manual")
    assert app.engine.last_update()["phone"]["focus"] == {"mode": "manual", "position": 0.3}
    app.ctl["phone.white_balance.temperature"].show(3500)
    app.ctl["phone.white_balance.mode"].select("manual")
    wb = app.engine.last_update()["phone"]["white_balance"]
    assert wb["mode"] == "manual" and wb["temperature"] == 3500


def test_zoom_buttons_include_half_x_and_work(app):
    labels = [b.cget("text") for b in app.zoom_buttons]
    assert labels == ["0.5x", "1x", "3x"]
    app.zoom_buttons[0].invoke()
    assert app.engine.last_update() == {"phone": {"zoom": 0.5}}
    assert app.ctl["phone.zoom"].value() == 0.5


def test_state_wins_over_what_the_user_asked(app):
    """The phone clamps: the control must end up showing the phone's value."""
    z = app.ctl["phone.zoom"]
    z.select(40.0)                                   # above the phone's max
    assert z.value() == 15.0 or z.value() <= 15.0    # slider already limited to the camera's range
    app.engine.status["phone"]["settings"]["zoom"] = 12.5
    z.touched_at = 0
    app.refresh_from_status()
    assert z.value() == pytest.approx(12.5, abs=0.1)
    assert app.settings["phone"]["zoom"] == pytest.approx(12.5, abs=0.1)


def test_state_updates_every_phone_control(app):
    new = {
        "camera": "back", "zoom": 2.0, "resolution": "720p", "fps": 60, "codec": "hevc", "bitrate_mbps": 33,
        "focus": {"mode": "manual", "position": 0.25},
        "exposure": {"mode": "manual", "bias": 0.0, "iso": 800, "shutter_s": 0.01},
        "white_balance": {"mode": "manual", "temperature": 6500, "tint": 40},
        "torch": 0.5, "stabilization": "cinematic", "hdr": True, "screen": "dim",
    }
    app.engine.status["phone"]["settings"] = new
    app.refresh_from_status(force=True)
    for path in [c[0] for c in CASES if c[0].startswith("phone.")] + ["phone.focus.mode", "phone.exposure.mode",
                                                                       "phone.white_balance.mode", "phone.exposure.iso",
                                                                       "phone.exposure.shutter_s"]:
        want = S.get_path(new, path[len("phone."):])
        got = app.ctl[path].value()
        assert got == pytest.approx(want, rel=0.06, abs=0.06), path


def test_recently_touched_control_is_not_overwritten(app):
    z = app.ctl["phone.zoom"]
    z.select(3.0)
    app.engine.status["phone"]["settings"]["zoom"] = 1.0       # an old STATE arriving late
    app.refresh_from_status()
    assert z.value() == 3.0


def test_unsupported_controls_are_disabled_with_a_reason(app):
    app.ctl["phone.camera"].select("front")
    app.engine.status["phone"]["settings"]["camera"] = "front"
    app.refresh_from_status(force=True)
    assert not app.ctl["phone.torch"].enabled and "no torch" in app.ctl["phone.torch"].note.cget("text")
    assert not app.ctl["phone.hdr"].enabled and app.ctl["phone.hdr"].note.cget("text")
    assert not app.ctl["phone.focus.mode"].buttons[1].instate(["!disabled"])      # no manual focus on the front camera
    res = app.ctl["phone.resolution"]
    assert not res.buttons[2].instate(["!disabled"]) and res.buttons[1].instate(["!disabled"])  # no 4K on front
    assert [b.cget("text") for b in app.zoom_buttons] == ["1x"]
    # back to the back camera: everything returns
    app.ctl["phone.camera"].select("back")
    app.engine.status["phone"]["settings"]["camera"] = "back"
    app.refresh_from_status(force=True)
    assert app.ctl["phone.torch"].enabled and app.ctl["phone.hdr"].enabled
    assert [b.cget("text") for b in app.zoom_buttons] == ["0.5x", "1x", "3x"]


def test_fps_choices_follow_resolution(app):
    app.ctl["phone.resolution"].select("4k")
    app.refresh_from_status(force=True)
    fps = app.ctl["phone.fps"]
    assert not fps.buttons[3].instate(["!disabled"])         # 60 fps not offered at 4k in the stub
    assert fps.buttons[2].instate(["!disabled"])


def test_mode_dependent_sliders(app):
    c = app.ctl
    assert c["phone.exposure.bias"].enabled and not c["phone.exposure.iso"].enabled
    assert not c["phone.focus.position"].enabled and "Manual" in c["phone.focus.position"].note.cget("text")
    c["phone.exposure.mode"].select("manual")
    assert not c["phone.exposure.bias"].enabled and c["phone.exposure.iso"].enabled and c["phone.exposure.shutter_s"].enabled
    c["phone.white_balance.mode"].select("manual")
    assert c["phone.white_balance.temperature"].enabled and c["phone.white_balance.tint"].enabled


def test_no_phone_yet_nothing_is_stuck_disabled_except_by_mode(stub_app):
    c = stub_app.ctl
    assert c["phone.torch"].enabled and c["phone.hdr"].enabled
    assert [b.cget("text") for b in stub_app.zoom_buttons] == ["0.5x", "1x", "3x"]


def test_reset_image_settings(app):
    c = app.ctl
    c["phone.exposure.mode"].select("manual")
    c["phone.torch"].select(0.7)
    c["phone.hdr"].select(True)
    c["phone.stabilization"].select("cinematic")
    c["phone.white_balance.temperature"].select(3000)
    app.engine.updates.clear()
    app.reset_image()
    p = app.engine.last_update()["phone"]
    assert p["focus"] == {"mode": "auto", "position": 0.5}
    assert p["exposure"] == {"mode": "auto", "bias": 0.0, "iso": None, "shutter_s": None}
    assert p["white_balance"] == {"mode": "auto", "temperature": 5000, "tint": 0}
    assert p["torch"] == 0.0 and p["stabilization"] == "off" and p["hdr"] is False
    assert "zoom" not in p and "camera" not in p and "resolution" not in p       # camera stuff untouched
    assert c["phone.torch"].value() == 0 and c["phone.exposure.mode"].value() == "auto"


def test_settings_are_saved_debounced_and_on_close(stub_app, tk_root, tmp_path):
    path = tmp_path / "settings.json"
    stub_app.ctl["pc.fit"].select("fit")
    stub_app.ctl["pc.fit"].select("stretch")
    assert not path.exists()                                      # not yet: debounced
    pump(tk_root, 1.5, until=path.exists)
    assert json.loads(path.read_text(encoding="utf-8"))["pc"]["fit"] == "stretch"
    stub_app.ctl["pc.mirror"].select(True)
    stub_app.close()                                              # saves immediately on close
    assert json.loads(path.read_text(encoding="utf-8"))["pc"]["mirror"] is True
    assert stub_app.engine.stopped


def test_settings_load_at_start(tk_root, tmp_path):
    from stub_engine import StubEngine
    from tacocam.app import App
    p = tmp_path / "settings.json"
    S.save(S.deep_update(S.default_settings(), {"phone": {"zoom": 0.5, "hdr": True}, "pc": {"output": "1080x1920", "fit": "fit"}}), p)
    app = App(tk_root, StubEngine, settings_path=p)
    assert app.ctl["phone.zoom"].value() == 0.5 and app.ctl["phone.hdr"].value() is True
    assert app.ctl["pc.output"].value() == "1080x1920" and app.ctl["pc.fit"].value() == "fit"
    assert app.engine.settings["pc"]["output"] == "1080x1920"      # the engine starts with the saved settings
    assert app.engine.started
    app.close()


def test_corrupt_settings_start_with_defaults(tk_root, tmp_path):
    from stub_engine import StubEngine
    from tacocam.app import App
    p = tmp_path / "settings.json"
    p.write_text("garbage{", encoding="utf-8")
    app = App(tk_root, StubEngine, settings_path=p)
    assert app.settings == S.DEFAULTS and (tmp_path / "settings.bad.json").exists()
    assert "settings.bad.json" in app.hint_label.cget("text")
    app.close()


def test_preview_draws_and_tap_focus(app, tk_root):
    tk_root.geometry("1280x800+0+0")
    tk_root.deiconify()
    pump(tk_root, 0.4, until=lambda: app.preview_frames > 0)
    assert app.preview_frames > 0 and app._img_box
    x0, y0, w, h = app._img_box
    class E: pass
    e = E(); e.x, e.y = x0 + w // 4, y0 + h // 2
    app._canvas_click(e)
    assert app.engine.taps and app.engine.taps[-1] == pytest.approx((0.25, 0.5), abs=0.02)
    assert app.canvas.find_withtag("focus")                       # the focus square
    e.x = x0 - 5                                                  # outside the picture: ignored
    n = len(app.engine.taps)
    app._canvas_click(e)
    assert len(app.engine.taps) == n
    tk_root.withdraw()


def test_mouse_wheel_zooms(app, tk_root):
    class E: delta = 120
    app.ctl["phone.zoom"].show(1.0)
    app._canvas_wheel(E())
    assert app.ctl["phone.zoom"].value() > 1.0
    pump(tk_root, 0.3)
    assert app.engine.last_update()["phone"]["zoom"] > 1.0


def test_status_texts():
    d = describe_status({"link": "searching"})
    assert d["conn"] == "Searching for iPhone on USB..."
    assert describe_status({"link": "no_app"})["conn"] == "iPhone found: open Taco Cam on the phone"
    st = {"link": "connected", "transport": "usb", "device_name": "iPhone 13 Pro", "fps_in": 30, "fps_out": 29.6,
          "bitrate_mbps": 15.5, "rtt_ms": 12.0, "dropped": 3, "vcam": "running", "vcam_backend": "unitycapture",
          "phone": {"battery": 0.82, "charging": True, "thermal": "serious", "app_active": True,
                    "stream": {"codec": "h264", "width": 1920, "height": 1080, "fps": 30}}}
    d = describe_status(st)
    assert d["conn"] == "Connected to iPhone 13 Pro by USB"
    assert d["battery"] == "Phone battery 82% (charging)"
    assert "HOT" in d["thermal"]
    assert "In 30 fps" in d["stats"] and "RTT 12 ms" in d["stats"] and "Dropped 3" in d["stats"] and "1920x1080" in d["stats"]
    assert d["vcam"] == 'Virtual camera "Taco Cam" ready in OBS' and not d["vcam_install"]
    d = describe_status(dict(st, vcam="not_installed"))
    assert d["vcam_install"] and "not installed" in d["vcam"]
    d = describe_status(dict(st, vcam_backend="obs"))
    assert "Start Virtual Camera" in d["vcam"]
    assert "background" in describe_status(dict(st, phone=dict(st["phone"], app_active=False)))["phone_problem"]


def test_status_bar_and_install_button(app, tk_root):
    app.refresh_from_status()
    assert app.conn_label.cget("text") == "Connected to iPhone 13 Pro by USB"
    assert not app.install_btn.winfo_ismapped()
    app.engine.set_status(vcam="not_installed")
    app.refresh_from_status()
    assert "not installed" in app.vcam_label.cget("text")
    assert app.install_btn.winfo_manager() == "pack"


def test_close_stops_engine(stub_app):
    stub_app.close()
    assert stub_app.engine.stopped


def test_only_one_copy_runs():
    name = f"Local\\TacoCamTest{time.time_ns()}"
    first = acquire_single_instance(name)
    assert first
    assert acquire_single_instance(name) is None
