"""Smooth zoom setting, phone pause reasons, the pre-show check and the OBS live watch."""
from datetime import datetime, timedelta, timezone

from conftest import pump
from stub_engine import StubEngine
from test_engine_e2e import connected_with_video, engine, phone, wait_until  # noqa: F401  (fixtures)

from tacocam import app as app_mod
from tacocam import precheck as PC
from tacocam import settings as S
from tacocam.app import App, describe_status
from tacocam.ui_widgets import BAD

NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def good_status(**phone_over):
    phone_settings = dict(S.default_settings()["phone"], screen="dim")
    phone = {"settings": phone_settings, "battery": 0.8, "charging": True, "thermal": "nominal",
             "app_active": True, "interrupted": None, "error": None,
             "app_expires": iso(NOW + timedelta(days=5))}
    phone.update(phone_over)
    return {"link": "connected", "transport": "usb", "phone": phone, "fps_in": 30.0,
            "vcam": "running", "vcam_backend": "unitycapture", "error": None}


def show_settings(**pc):
    s = S.default_settings()
    s["pc"].update({"output": "1920x1080", "rotate": 0, **pc})
    return s


# ---- settings

def test_zoom_speed_setting():
    assert S.default_settings()["phone"]["zoom_glide_s"] == 0.5
    for ok in (0, 0.5, 1, 2, 1.0):
        assert S.sanitize({"phone": {"zoom_glide_s": ok}})["phone"]["zoom_glide_s"] == ok
    for bad in (0.7, -1, "fast", True):
        assert S.sanitize({"phone": {"zoom_glide_s": bad}})["phone"]["zoom_glide_s"] == 0.5
    assert S.default_settings()["pc"]["check_on_live"] is True


# ---- pre-show check (pure)

def test_everything_ready():
    res = PC.run_checks(good_status(), show_settings(), now=NOW, feed_in_use=True)
    assert PC.worst(res) == PC.OK and PC.problems(res) == []
    texts = " | ".join(t for _l, t in res)
    assert "connected by USB" in texts and "30 fps" in texts and "1080p" in texts and "charging (80%)" in texts
    assert "5 more days" in texts and "Do Not Disturb" in texts


def test_every_problem_is_named():
    st = good_status(charging=False, battery=0.2, thermal="critical", app_expires=iso(NOW + timedelta(hours=5)))
    st["phone"]["settings"]["resolution"] = "4k"
    st.update(vcam="not_installed")
    res = PC.run_checks(st, show_settings(output="1080x1920"), now=NOW)
    bad = [t for lvl, t in res if lvl == PC.BAD]
    warn = [t for lvl, t in res if lvl == PC.WARN]
    assert any("NOT charging (20%)" in t for t in bad)
    assert any("VERY hot" in t for t in bad)
    assert any("stops opening in 5 h" in t for t in bad)
    assert any("not installed" in t for t in bad)
    assert any("4K" in t for t in warn) and any("1080x1920" in t for t in warn)
    assert PC.worst(res) == PC.BAD


def test_no_phone_and_paused_phone():
    res = PC.run_checks({"link": "searching", "vcam": "running"}, show_settings(), now=NOW)
    assert res[0][0] == PC.BAD and "No iPhone connected" in res[0][1]
    res = PC.run_checks({"link": "no_app", "vcam": "running"}, show_settings(), now=NOW)
    assert "isn't open" in res[0][1]
    res = PC.run_checks(dict(good_status(interrupted="other_app"), fps_in=0.0), show_settings(), now=NOW)
    assert (PC.BAD, PC.INTERRUPTED["other_app"]) in res
    res = PC.run_checks(good_status(interrupted="other_app"), show_settings(), now=NOW)   # stale: picture flows
    assert PC.problems(res) == []
    res = PC.run_checks(dict(good_status(), fps_in=0.0), show_settings(), now=NOW)
    assert (PC.BAD, "Connected, but no picture is coming from the iPhone camera") in res
    res = PC.run_checks(dict(good_status(), transport="wifi"), show_settings(), now=NOW)
    assert res[0][0] == PC.WARN


def test_status_bar_names_the_pause():
    d = describe_status(good_status(interrupted="too_hot"))
    assert d["phone_problem"] == PC.INTERRUPTED["too_hot"] and d["phone_problem_color"] == BAD
    d = describe_status(good_status(app_active=False))
    assert "background" in d["phone_problem"]
    d = describe_status(good_status(interrupted="something new"))
    assert d["phone_problem"] == PC.INTERRUPTED["other"]
    assert describe_status(good_status())["phone_problem"] == ""


# ---- the window

def _app(tk_root, tmp_path):
    path = tmp_path / "settings.json"
    s = S.default_settings()
    s["pc"].update(hotkeys=False, output="1920x1080", rotate=0)
    S.save(s, path)
    eng = {}

    def factory(settings, log=None):
        eng["e"] = StubEngine(settings, log)
        return eng["e"]
    app = App(tk_root, factory, settings_path=path, autostart=False)
    return app, eng["e"]


class Obs:
    def __init__(self, streaming=False):
        self.streaming = streaming

    def snapshot(self):
        return {"status": "connected", "scene": "Scene", "scenes": ["Scene"], "streaming": self.streaming,
                "error": None}

    def stop(self):
        pass


def test_zoom_speed_control_and_reset(tk_root, tmp_path):
    app, eng = _app(tk_root, tmp_path)
    try:
        app.ctl["phone.zoom_glide_s"].select(1)
        assert eng.last_update() == {"phone": {"zoom_glide_s": 1}}
        app.reset_image()
        assert "zoom_glide_s" not in eng.last_update()["phone"]
        assert app.ctl["phone.zoom_glide_s"].value() == 1
    finally:
        app.close()


def test_check_button_opens_the_window(tk_root, tmp_path):
    app, eng = _app(tk_root, tmp_path)
    try:
        eng.connect_phone()
        app.refresh_from_status()
        app.check_btn.invoke()
        pump(tk_root, 0.05)
        assert app.check_win is not None and app.check_win.winfo_exists()
        rows = app._check_rows.winfo_children()
        assert len(rows) >= 2 * 8
        assert app._check_head.cget("text")
        app.close_check()
        assert app.check_win is None
    finally:
        app.close()


def test_going_live_with_a_problem_opens_the_check(tk_root, tmp_path):
    app, eng = _app(tk_root, tmp_path)
    beeps = []
    app._beep = lambda: beeps.append(1)
    try:
        eng.connect_phone(charging=False, battery=0.5)
        app.refresh_from_status()
        app.obs = Obs(streaming=False)
        app._background_tick()
        assert app.check_win is None
        app.obs.streaming = True
        app._background_tick()
        assert app.check_win is not None and beeps == [1]
        assert "NOT charging" in " ".join(app.log_lines)
        app.close_check()
        app._background_tick()                  # still live: no second pop-up
        assert app.check_win is None
    finally:
        app.close()


def test_going_live_all_good_only_says_so(tk_root, tmp_path):
    app, eng = _app(tk_root, tmp_path)
    app._beep = lambda: None
    app.engine.feed_in_use = lambda: True
    try:
        eng.connect_phone(app_expires=iso(datetime.now(timezone.utc) + timedelta(days=5)))
        app.refresh_from_status()
        app.obs = Obs(streaming=False)
        app._background_tick()
        app.obs.streaming = True
        app._background_tick()
        assert app.check_win is None
        assert "all good" in app.hint_label.cget("text")
    finally:
        app.close()


def test_beeps_when_the_picture_stops_while_live(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "LOST_ALERT_S", 0.0)
    app, eng = _app(tk_root, tmp_path)
    beeps = []
    app._beep = lambda: beeps.append(1)
    try:
        eng.connect_phone(app_expires=iso(datetime.now(timezone.utc) + timedelta(days=5)))
        app.engine.feed_in_use = lambda: True
        app.refresh_from_status()
        app.obs = Obs(streaming=True)            # Taco Cam opened while already live: no check pop-up
        app._background_tick()
        assert app.check_win is None and beeps == []
        eng.status["phone"]["interrupted"] = "other_app"
        eng.status["fps_in"] = 0.0
        app.refresh_from_status()
        app._background_tick()                   # starts the clock
        app._background_tick()                   # past LOST_ALERT_S
        assert beeps == [1] and "LIVE" in app.hint_label.cget("text")
        app._background_tick()
        assert beeps == [1]                      # once per drop
        eng.status["phone"]["interrupted"] = None
        eng.status["fps_in"] = 30.0
        app.refresh_from_status()
        app._background_tick()
        assert "back" in app.hint_label.cget("text")
        app.settings["pc"]["check_on_live"] = False
        eng.status["phone"]["interrupted"] = "too_hot"
        eng.status["fps_in"] = 0.0
        app.refresh_from_status()
        for _ in range(3):
            app._background_tick()
        assert beeps == [1]                      # switched off
    finally:
        app.close()


# ---- with the test phone

def test_zoom_speed_and_pause_reach_the_engine(engine, phone):
    assert wait_until(lambda: connected_with_video(engine))
    engine.update_settings({"phone": {"zoom_glide_s": 1}})
    assert wait_until(lambda: (engine.get_status()["phone"] or {}).get("settings", {}).get("zoom_glide_s") == 1)
    phone.set_interrupted("other_app")
    assert wait_until(lambda: (engine.get_status()["phone"] or {}).get("interrupted") == "other_app")
    assert wait_until(lambda: engine.get_status()["fps_in"] < 1, timeout=6)
    phone.set_interrupted(None)
    assert wait_until(lambda: engine.get_status()["fps_in"] > 5)
