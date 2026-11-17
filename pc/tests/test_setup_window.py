"""The "Get started" window (camera driver, phone, OBS) and its pure step list."""
from conftest import pump
from stub_engine import StubEngine

from tacocam import app as app_mod
from tacocam import settings as S
from tacocam.app import App, setup_steps


def test_steps_follow_the_status():
    s = S.default_settings()
    s["pc"]["connect"] = "android"
    steps = setup_steps({"vcam": "not_installed", "link": "searching", "transport": "android"}, s)
    assert [k for k, *_ in steps] == ["camera", "phone", "obs"]
    assert [done for _k, done, *_ in steps] == [False, False, False]
    assert steps[0][3] == "Install the camera" and steps[2][3] == "Set up OBS"
    assert "USB debugging" in steps[1][2] and "Searching for the Android phone" in steps[1][2]
    s["pc"]["obs_setup_done"] = True
    steps = setup_steps({"vcam": "running", "vcam_backend": "unitycapture", "link": "connected",
                         "device_name": "Google Pixel 8"}, s)
    assert all(done for _k, done, *_ in steps)
    assert steps[1][2] == "Connected to Google Pixel 8." and steps[0][3] is None
    s["pc"]["connect"] = "usb"
    assert setup_steps({}, s)[1][3] == "Use an Android phone"
    # the OBS Virtual Camera fallback is not the Taco Cam camera: still to do
    assert setup_steps({"vcam": "running", "vcam_backend": "obs"}, s)[0][1] is False


def _app(tk_root, tmp_path, **pc):
    path = tmp_path / "settings.json"
    s = S.default_settings()
    s["pc"].update(hotkeys=False, **pc)
    S.save(s, path)
    eng = {}

    def factory(settings, log=None):
        eng["e"] = StubEngine(settings, log)
        return eng["e"]
    return App(tk_root, factory, settings_path=path, autostart=False), eng["e"], path


def test_welcome_opens_by_itself_once(tk_root, tmp_path):
    app, eng, path = _app(tk_root, tmp_path, welcome=True, connect="android")
    try:
        pump(tk_root, 0.5, until=lambda: app.setup_win is not None)
        assert app.setup_win is not None
        mark, detail, btn = app._setup_rows["obs"]
        assert btn.cget("text") == "Set up OBS"
        app.close_setup()
        assert app.settings["pc"]["welcome"] is False
        app.flush_save()
        assert S.load(path)[0]["pc"]["welcome"] is False
    finally:
        app.close()


def test_obs_button_runs_the_setup(tk_root, tmp_path, monkeypatch):
    app, eng, path = _app(tk_root, tmp_path, connect="android")
    shown = []
    monkeypatch.setattr(app_mod.obssetup, "setup", lambda: {"profile": "Taco Cam Whatnot", "collection": "x",
                                                            "websocket_password": "Pw123", "websocket_port": 4455,
                                                            "websocket_new": True})
    monkeypatch.setattr(app_mod.messagebox, "showinfo", lambda title, text, **k: shown.append(text))
    try:
        app.open_setup()
        app._setup_action("obs")
        assert app.settings["pc"]["obs_setup_done"] is True
        assert "Pw123" in shown[0] and tk_root.clipboard_get() == "Pw123"
        assert eng.last_update() == {"pc": {"obs_setup_done": True}}
        app._fill_setup()
        assert app._setup_rows["obs"][2].cget("text") == "Set up OBS again"
    finally:
        app.close()


def test_obs_problem_is_shown(tk_root, tmp_path, monkeypatch):
    app, eng, path = _app(tk_root, tmp_path)
    warned = []

    def refuse():
        raise app_mod.obssetup.SetupProblem("OBS is open: close OBS first")
    monkeypatch.setattr(app_mod.obssetup, "setup", refuse)
    monkeypatch.setattr(app_mod.messagebox, "showwarning", lambda title, text, **k: warned.append(text))
    try:
        assert app.setup_obs() is None
        assert warned == ["OBS is open: close OBS first"] and app.settings["pc"]["obs_setup_done"] is False
    finally:
        app.close()


def test_phone_button_switches_to_android(tk_root, tmp_path):
    app, eng, path = _app(tk_root, tmp_path, connect="usb")
    try:
        app.open_setup()
        app._setup_action("phone")
        assert app.settings["pc"]["connect"] == "android"
        assert eng.last_update() == {"pc": {"connect": "android"}}
    finally:
        app.close()
