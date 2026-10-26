"""The PC's saved settings win over what the phone remembers from last time (its first STATE, sent before
the PC's SET, carries the phone's old values)."""
import json
import socket
import time

from conftest import pump
from test_app_real import _connected, fake_phone, null_engine  # noqa: F401  (fixture)

from tacocam import protocol


def _phone_remembers(settings):
    """Connect once as a PC, send a SET, and leave: the fake phone keeps these as its own settings."""
    s = socket.create_connection(("127.0.0.1", protocol.PORT), timeout=3)
    s.sendall(protocol.encode_json(protocol.HELLO, protocol.PC_HELLO))
    reader = protocol.FrameReader()
    end = time.monotonic() + 3
    while time.monotonic() < end:
        if any(t == protocol.STATE for t, _ in protocol.recv_messages(s, reader)):
            break
    s.sendall(protocol.encode_json(protocol.SET, settings))
    time.sleep(0.5)
    s.close()
    time.sleep(0.3)


def test_saved_pc_settings_beat_the_phones_old_values(tk_root, tmp_path, fake_phone):  # noqa: F811
    from tacocam import settings as S
    from tacocam.app import App

    _phone_remembers({"fps": 60, "bitrate_mbps": 40})
    p = tmp_path / "settings.json"
    S.save(S.deep_update(S.default_settings(), {
        "phone": {"fps": 30, "bitrate_mbps": 20},
        "pc": {"connect": "wifi", "wifi_host": "127.0.0.1"},
    }), p)
    app = App(tk_root, null_engine, settings_path=p)
    try:
        assert pump(tk_root, 10, until=lambda: _connected(app))
        pump(tk_root, 3)
        app.refresh_from_status(force=True)
        phone = app._status["phone"]["settings"]
        assert (phone["fps"], phone["bitrate_mbps"]) == (30, 20)
        assert (app.settings["phone"]["fps"], app.settings["phone"]["bitrate_mbps"]) == (30, 20)
        app.flush_save()
        saved = json.loads(p.read_text(encoding="utf-8"))["phone"]
        assert (saved["fps"], saved["bitrate_mbps"]) == (30, 20)
    finally:
        app.close()
