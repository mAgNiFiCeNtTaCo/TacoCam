"""The app against the REAL engine and the fake phone (skipped until both exist)."""
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from conftest import PC, pump

ENGINE = PC / "tacocam" / "engine.py"
FAKE = PC / "tools" / "fake_phone.py"

pytestmark = pytest.mark.skipif(not (ENGINE.exists() and FAKE.exists()),
                                reason="real engine / fake phone not written yet")


def null_engine(settings, log=None):
    """The real Engine, but with a null virtual camera so tests never feed the user's real Taco Cam camera."""
    from tacocam.engine import Engine
    from tacocam.vcam import null_factory
    return Engine(settings, log, vcam_factory=null_factory)


def _port_free(port=47777):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


@pytest.fixture
def fake_phone():
    if not _port_free():
        pytest.skip("port 47777 is already in use (a real or fake phone is running)")
    log = open(PC.parent / "fake-phone-test.log", "wb")
    p = subprocess.Popen([sys.executable, str(FAKE)], cwd=str(PC), stdout=log, stderr=log, stdin=subprocess.PIPE)
    for _ in range(100):
        if not _port_free():
            break
        time.sleep(0.1)
    yield p
    p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
    log.close()


@pytest.fixture
def real_app(tk_root, tmp_path, fake_phone):
    from tacocam import settings as S
    from tacocam.app import App
    from tacocam.engine import Engine
    p = tmp_path / "settings.json"
    S.save(S.deep_update(S.default_settings(), {"pc": {"connect": "wifi", "wifi_host": "127.0.0.1"}}), p)
    app = App(tk_root, null_engine, settings_path=p)
    yield app
    if not app._closing:
        app.close()


def _connected(app):
    app.refresh_from_status(force=True)
    return app._status.get("link") == "connected" and (app._status.get("phone") or {}).get("settings")


def _picture(app):
    fr = app.engine.get_preview(320, 320)
    return None if fr is None else np.asarray(fr, dtype=np.float32)


def test_connects_and_shows_picture(real_app, tk_root):
    assert pump(tk_root, 20, until=lambda: _connected(real_app)), (real_app._status, list(real_app.log_lines))
    assert pump(tk_root, 10, until=lambda: real_app.preview_frames > 0)
    assert real_app.conn_label.cget("text").startswith("Connected to")
    assert real_app.zoom_buttons and real_app.zoom_buttons[0].cget("text") == "0.5x"


def test_zoom_half_x_round_trip_and_picture(real_app, tk_root):
    app = real_app
    assert pump(tk_root, 20, until=lambda: _connected(app)), app._status
    assert pump(tk_root, 10, until=lambda: _picture(app) is not None)
    app.ctl["phone.zoom"].select(3.0)
    assert pump(tk_root, 10, until=lambda: abs(app._status["phone"]["settings"]["zoom"] - 3.0) < 0.05 or
                (app.refresh_from_status(force=True) and abs(app._status["phone"]["settings"]["zoom"] - 3.0) < 0.05))
    pump(tk_root, 1.0)
    tele = _picture(app)
    app.zoom_buttons[0].invoke()                                       # the 0.5x button
    got = lambda: (app.refresh_from_status(force=True) or True) and abs(app._status["phone"]["settings"]["zoom"] - 0.5) < 0.05
    assert pump(tk_root, 10, until=got), app._status["phone"]["settings"]
    assert app.ctl["phone.zoom"].value() == pytest.approx(0.5, abs=0.05)
    assert app.settings["phone"]["zoom"] == pytest.approx(0.5, abs=0.05)
    pump(tk_root, 1.5)
    wide = _picture(app)
    assert tele is not None and wide is not None
    n = min(tele.shape[0], wide.shape[0]), min(tele.shape[1], wide.shape[1])
    diff = np.abs(tele[:n[0], :n[1]] - wide[:n[0], :n[1]]).mean()
    assert diff > 3.0, f"picture did not change with 0.5x zoom (mean diff {diff:.2f})"


def test_settings_round_trip_through_the_phone(real_app, tk_root):
    app = real_app
    assert pump(tk_root, 20, until=lambda: _connected(app)), app._status

    def phone_has(path, want, tol=0.06):
        app.refresh_from_status(force=True)
        from tacocam import settings as S
        got = S.get_path(app._status["phone"]["settings"], path)
        return got == pytest.approx(want, abs=tol) if isinstance(want, float) else got == want

    for path, value in [("phone.codec", "hevc"), ("phone.fps", 25), ("phone.bitrate_mbps", 30),
                        ("phone.exposure.bias", -1.0), ("phone.white_balance.mode", "manual"),
                        ("phone.stabilization", "standard"), ("phone.screen", "dim"), ("phone.hdr", True)]:
        ctl = app.ctl[path]
        if not ctl.enabled:
            continue
        ctl.select(value)
        key = path[len("phone."):]
        assert pump(tk_root, 8, until=lambda: phone_has(key, value)), (path, app._status["phone"]["settings"])


def test_output_size_change_reaches_the_engine(real_app, tk_root):
    app = real_app
    assert pump(tk_root, 20, until=lambda: _connected(app)), app._status
    app.ctl["pc.output"].select("1080x1920")
    ok = pump(tk_root, 10, until=lambda: app.engine.get_status().get("out_size") == [1080, 1920])
    assert ok, app.engine.get_status()
    assert pump(tk_root, 5, until=lambda: (_picture(app) is not None and _picture(app).shape[0] >= _picture(app).shape[1]))


def test_close_stops_real_engine_quickly(real_app, tk_root):
    pump(tk_root, 3)
    t = time.monotonic()
    real_app.close()
    assert time.monotonic() - t < 5


def test_start_test_phone_button(tk_root, tmp_path):
    """Nothing running: the 'Start test phone' button launches fake_phone.py and the app connects to it."""
    if not _port_free():
        pytest.skip("port 47777 is in use")
    from tacocam.app import App
    from tacocam.engine import Engine
    app = App(tk_root, null_engine, settings_path=tmp_path / "settings.json")
    try:
        app.toggle_test_phone()
        assert app._test_proc is not None
        assert app.settings["pc"]["connect"] == "wifi" and app.settings["pc"]["wifi_host"] == "127.0.0.1"
        assert pump(tk_root, 30, until=lambda: _connected(app)), (app._status, list(app.log_lines))
        assert pump(tk_root, 10, until=lambda: app.preview_frames > 0)
        app.toggle_test_phone()
        assert app._test_proc is None
    finally:
        app.close()
