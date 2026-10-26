"""Presets, anti-flicker, install-expiry warning, hotkeys and the OBS scene follower."""
import json
import time
from datetime import datetime, timedelta, timezone

from conftest import pump
from stub_engine import StubEngine

from tacocam import presets as P
from tacocam import settings as S
from tacocam.app import App, describe_expiry
from tacocam.obsfollow import ObsFollower
from tacocam.obsws import ObsError
from tacocam.ui_widgets import BAD, MUTED, WARN

LIVE = {"lens_position": 0.61, "iso": 250.0, "shutter_s": 0.016667, "temperature": 4100, "tint": -6}


# ---- presets (pure)

def test_capture_keeps_only_picture_settings():
    phone = S.default_settings()["phone"]
    phone.update(zoom=2.0, fps=60, bitrate_mbps=40, anti_flicker="60hz")
    p = P.capture(phone)
    assert set(p) == set(P.PRESET_KEYS)
    assert p["zoom"] == 2.0 and p["anti_flicker"] == "60hz"
    assert "fps" not in p and "bitrate_mbps" not in p and "resolution" not in p


def test_capture_locks_at_live_values():
    phone = S.default_settings()["phone"]
    p = P.capture(phone, LIVE, lock_focus=True, lock_exposure=True, lock_colors=True)
    assert p["focus"] == {"mode": "manual", "position": 0.61}
    assert p["exposure"]["mode"] == "manual" and p["exposure"]["iso"] == 250.0 and p["exposure"]["shutter_s"] == 0.016667
    assert p["white_balance"] == {"mode": "manual", "temperature": 4100, "tint": -6}
    # no live values (old phone app): nothing locked
    q = P.capture(phone, None, True, True, True)
    assert q["focus"]["mode"] == "auto" and q["exposure"]["mode"] == "auto"


def test_sanitize_presets_drops_bad_entries_and_keeps_nine():
    good = {"name": "  Close-up ", "phone": {"zoom": 2.5, "focus": {"mode": "manual", "position": 0.7}}, "obs_scene": "Cards"}
    raw = [good, "junk", {"name": "", "phone": {"zoom": 1}}, {"name": "x", "phone": {}},
           {"name": "bad zoom", "phone": {"zoom": "huge", "torch": 0.5}}] + [dict(good, name=f"n{i}") for i in range(12)]
    out = P.sanitize_presets(raw)
    assert len(out) == P.MAX_PRESETS
    assert out[0] == {"name": "Close-up", "phone": {"zoom": 2.5, "focus": {"mode": "manual", "position": 0.7}},
                      "obs_scene": "Cards"}
    assert out[1]["name"] == "bad zoom" and out[1]["phone"]["zoom"] == 1.0 and out[1]["phone"]["torch"] == 0.5
    assert P.for_scene(out, "Cards") == 0 and P.for_scene(out, "Other") is None


def test_presets_survive_save_and_load(tmp_path):
    s = S.default_settings()
    s["presets"] = [{"name": "Wide", "phone": {"zoom": 0.5}, "obs_scene": ""}]
    s["phone"]["anti_flicker"] = "60hz"
    path = tmp_path / "settings.json"
    assert S.save(s, path)
    back, note = S.load(path)
    assert note is None and back["presets"] == s["presets"] and back["phone"]["anti_flicker"] == "60hz"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["phone"]["anti_flicker"] = "100hz"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert S.load(path)[0]["phone"]["anti_flicker"] == "off"


# ---- expiry text

def test_expiry_text_levels():
    now = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)
    iso = lambda h: (now + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert describe_expiry(None, now) == ("", MUTED)
    assert describe_expiry("garbage", now) == ("", MUTED)
    text, color = describe_expiry(iso(24 * 5), now)
    assert text.startswith("iPhone app good until") and color == MUTED
    text, color = describe_expiry(iso(30), now)
    assert "2 days" in text and "iloader" in text and color == WARN
    text, color = describe_expiry(iso(5), now)
    assert "5 h" in text and color == BAD
    text, color = describe_expiry(iso(-1), now)
    assert "expired" in text and color == BAD


# ---- the window

def _app(tk_root, tmp_path, presets=None):
    path = tmp_path / "settings.json"
    s = S.default_settings()
    s["pc"]["hotkeys"] = False
    s["presets"] = presets or []
    S.save(s, path)
    eng = {}

    def factory(settings, log=None):
        eng["e"] = StubEngine(settings, log)
        return eng["e"]
    app = App(tk_root, factory, settings_path=path, autostart=False)
    return app, eng["e"], path


def test_apply_preset_sends_phone_settings_and_marks_button(tk_root, tmp_path):
    pr = [{"name": "Close-up", "phone": {"zoom": 2.0, "focus": {"mode": "manual", "position": 0.6},
                                          "anti_flicker": "60hz"}, "obs_scene": ""}]
    app, eng, _ = _app(tk_root, tmp_path, pr)
    try:
        assert [b.cget("text") for b in app.preset_buttons] == ["1  Close-up"]
        app.apply_preset(0)
        sent = eng.updates[-1]["phone"]
        assert sent["zoom"] == 2.0 and sent["focus"] == {"mode": "manual", "position": 0.6}
        assert sent["anti_flicker"] == "60hz"
        assert app.settings["phone"]["zoom"] == 2.0
        assert app.ctl["phone.anti_flicker"].value() == "60hz"
        assert app.preset_buttons[0].cget("style") == "ZoomOn.TButton"
        # touching a camera control by hand un-marks the preset
        app.ctl["phone.zoom"].select(1.0)
        assert app.preset_buttons[0].cget("style") == "Zoom.TButton"
    finally:
        app.close()


def test_save_preset_with_locks_from_live_values(tk_root, tmp_path, monkeypatch):
    app, eng, path = _app(tk_root, tmp_path)
    try:
        eng.connect_phone(live=LIVE)
        app.refresh_from_status(force=True)
        monkeypatch.setattr("tacocam.app.simpledialog.askstring", lambda *a, **k: "Card close-up")
        app.lock_exposure.set(False)
        app.save_preset_new()
        assert len(app.presets) == 1
        pr = app.presets[0]
        assert pr["name"] == "Card close-up"
        assert pr["phone"]["focus"] == {"mode": "manual", "position": 0.61}
        assert pr["phone"]["white_balance"]["mode"] == "manual"
        assert pr["phone"]["exposure"]["mode"] == "auto"
        app.flush_save()
        assert json.loads(path.read_text(encoding="utf-8"))["presets"][0]["name"] == "Card close-up"
    finally:
        app.close()


def test_hotkey_presses_apply_presets(tk_root, tmp_path):
    pr = [{"name": "Wide", "phone": {"zoom": 0.5}, "obs_scene": ""},
          {"name": "Close", "phone": {"zoom": 3.0}, "obs_scene": ""}]
    app, eng, _ = _app(tk_root, tmp_path, pr)

    class FakeKeys:
        failed = []

        def pressed(self):
            return [2]

        def stop(self):
            pass
    app.hotkeys = FakeKeys()
    try:
        app._background_tick()
        assert eng.updates[-1]["phone"]["zoom"] == 3.0 and app._active_preset == 1
    finally:
        app.close()


class FakeObs:
    def __init__(self, scenes):
        self.scenes = scenes
        self.calls = 0

    def connect(self):
        return self

    def close(self):
        pass

    def request(self, kind, data=None):
        self.calls += 1
        if kind == "GetSceneList":
            return {"scenes": [{"sceneName": n} for n in reversed(self.scenes)]}
        return {"currentProgramSceneName": self.scenes[min(self.calls // 3, len(self.scenes) - 1)]}


def test_obs_follower_reports_scenes_and_live_scene():
    fake = FakeObs(["Wide", "Cards"])
    f = ObsFollower(client_factory=lambda: fake).start()
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and f.snapshot()["scene"] != "Cards":
            time.sleep(0.1)
        snap = f.snapshot()
        assert snap["status"] == "connected" and snap["scenes"] == ["Wide", "Cards"] and snap["scene"] == "Cards"
    finally:
        f.stop()
    assert f.snapshot()["status"] == "off"


def test_obs_follower_says_why_it_cannot_connect():
    logs = []

    def broken():
        raise ObsError("OBS rejected the login (wrong websocket password?)")
    f = ObsFollower(client_factory=broken, log=logs.append).start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and f.snapshot()["status"] != "error":
            time.sleep(0.05)
        assert f.snapshot()["status"] == "error" and "password" in f.snapshot()["error"]
        assert logs and "password" in logs[0]
    finally:
        f.stop()


def test_window_follows_obs_scene(tk_root, tmp_path):
    pr = [{"name": "Wide", "phone": {"zoom": 0.5}, "obs_scene": "Table"},
          {"name": "Close", "phone": {"zoom": 3.0}, "obs_scene": "Cards"}]
    app, eng, _ = _app(tk_root, tmp_path, pr)

    class Snap:
        def __init__(self):
            self.scene = "Cards"

        def snapshot(self):
            return {"status": "connected", "scene": self.scene, "scenes": ["Table", "Cards"], "error": None}

        def stop(self):
            pass
    snap = Snap()
    app.obs = snap
    try:
        app._background_tick()                 # Follow OBS off (the watcher only runs for the live check)
        assert eng.updates == []
        app.settings["pc"]["follow_obs"] = True
        app._background_tick()
        assert eng.updates[-1]["phone"]["zoom"] == 3.0
        n = len(eng.updates)
        app._background_tick()                 # same scene: nothing re-sent
        assert len(eng.updates) == n
        snap.scene = "Table"
        app._background_tick()
        assert eng.updates[-1]["phone"]["zoom"] == 0.5
        assert list(app.scene_combo.cget("values")) == ["Table", "Cards"]
    finally:
        app.close()


def test_anti_flicker_only_in_auto_exposure(tk_root, tmp_path):
    app, eng, _ = _app(tk_root, tmp_path)
    try:
        app.ctl["phone.anti_flicker"].select("60hz")
        assert eng.updates[-1] == {"phone": {"anti_flicker": "60hz"}}
        app.ctl["phone.exposure.mode"].select("manual")
        pump(tk_root, 0.05)
        assert not app.ctl["phone.anti_flicker"].enabled
    finally:
        app.close()


def test_combined_back_camera_greys_out_exact_values(tk_root, tmp_path):
    """iPhone 11 back camera (Dual Wide): only holding focus/brightness/colors, no anti-flicker."""
    app, eng, _ = _app(tk_root, tmp_path)
    try:
        eng.connect_phone()
        with eng.lock:
            back = eng.status["phone"]["cameras"]["back"]
            back.update(focus_manual=False, focus_lock=True, exposure_manual=False, wb_manual=False,
                        anti_flicker=False)
            s = eng.status["phone"]["settings"]
            s["exposure"]["mode"] = "manual"
            s["white_balance"]["mode"] = "manual"
            s["focus"]["mode"] = "manual"
        app.refresh_from_status(force=True)
        c = app.ctl
        assert "manual" in {v for v, _ in c["phone.focus.mode"].options}
        assert not c["phone.focus.position"].enabled and "hold" in c["phone.focus.position"]._reason
        assert not c["phone.exposure.iso"].enabled and "hold its brightness" in c["phone.exposure.iso"]._reason
        assert not c["phone.white_balance.temperature"].enabled
        with eng.lock:
            eng.status["phone"]["settings"]["exposure"]["mode"] = "auto"
        app.refresh_from_status(force=True)
        assert not c["phone.anti_flicker"].enabled and "Apple" in c["phone.anti_flicker"]._reason
        assert c["phone.exposure.bias"].enabled
    finally:
        app.close()
