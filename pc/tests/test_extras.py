"""Save-the-hit clips, start with Windows, phone battery warning, Ctrl+Alt+0."""
import struct
import time
from fractions import Fraction

import av
import numpy as np
import pytest

from conftest import pump
from stub_engine import StubEngine
from test_engine_e2e import connected_with_video, make_engine, phone, wait_until  # noqa: F401  (fixture)

from tacocam import clips
from tacocam import settings as S
from tacocam.app import App, describe_status
from tacocam.ui_widgets import BAD, MUTED, WARN


def encoded_stream(n=90, fps=30, codec="libx264", w=320, h=180, gop=30):
    """[(flags, pts_us, annexb)] like the phone sends (keyframe flag, format-changed on the first)."""
    enc = av.CodecContext.create(codec, "w")
    enc.width, enc.height, enc.pix_fmt = w, h, "yuv420p"
    enc.time_base = Fraction(1, fps)
    enc.options = {"preset": "ultrafast", "tune": "zerolatency", "bf": "0", "g": str(gop),
                   "x264-params": "repeat-headers=1"}
    out = []
    for i in range(n + 1):
        frames = [None] if i == n else [i]
        for fi in frames:
            if fi is None:
                pkts = enc.encode(None)
            else:
                img = np.zeros((h, w, 3), np.uint8)
                img[:, : (fi * 5) % w] = (255, 120, 0)
                f = av.VideoFrame.from_ndarray(img, format="rgb24").reformat(format="yuv420p")
                f.pts = fi
                pkts = enc.encode(f)
            for p in pkts:
                flags = (1 if p.is_keyframe else 0) | (2 if not out else 0)
                out.append((flags, int(p.pts * 1_000_000 / fps), bytes(p)))
    return out


def tkhd_matrix(path):
    data = open(path, "rb").read()
    i = data.find(b"tkhd")
    off = i + 4 + (24 if data[i + 4] == 0 else 36) + 16
    return struct.unpack(">9i", data[off:off + 36])


# ---- clip buffer + MP4

def test_buffer_keeps_whole_groups_from_a_keyframe():
    buf = clips.ClipBuffer(keep_s=2)
    for flags, pts, data in encoded_stream(n=150, gop=30):   # 5 s, keyframe every 1 s
        buf.add(flags, pts, data)
    got = buf.take(60)
    assert got[0][1] is True                                  # starts at a keyframe
    assert 2.0 <= (got[-1][0] - got[0][0]) / 1e6 <= 3.1         # ~2 s kept, whole groups
    short = buf.take(0.5)
    assert short[0][1] is True and (short[-1][0] - short[0][0]) / 1e6 <= 1.1


def test_buffer_restarts_on_format_change_and_ignores_leading_non_keyframes():
    buf = clips.ClipBuffer()
    buf.add(0, 0, b"\x00\x00\x00\x01\x41xx")                  # not a keyframe: nothing to start from
    assert buf.take(30) == []
    stream = encoded_stream(n=40)
    for flags, pts, data in stream:
        buf.add(flags, pts, data)
    assert len(buf.take(30)) == len(stream)
    buf.add(3, 999_999_999, stream[0][2])                      # new connection / format
    assert len(buf.take(30)) == 1


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_write_mp4_without_reencoding(tmp_path, rotation):
    stream = encoded_stream(n=60)
    packets = [(pts, bool(flags & 1), data) for flags, pts, data in stream]
    path = tmp_path / "clip.mp4"
    length = clips.write_mp4(path, packets, rotation)
    assert 1.9 <= length <= 2.1
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        assert (s.codec_context.name, s.width, s.height) == ("h264", 320, 180)
        assert sum(1 for _ in c.decode(video=0)) == len(packets)
    assert tkhd_matrix(path) == clips._MATRIX[rotation]
    assert not (tmp_path / "clip.mp4.part").exists()


def test_write_mp4_hevc(tmp_path):
    try:
        stream = encoded_stream(n=30, codec="libx265")
    except Exception:
        pytest.skip("no HEVC encoder in this PyAV build")
    packets = [(pts, bool(flags & 1), data) for flags, pts, data in stream]
    clips.write_mp4(tmp_path / "h.mp4", packets, 90)
    with av.open(str(tmp_path / "h.mp4")) as c:
        assert c.streams.video[0].codec_context.name == "hevc"
        assert sum(1 for _ in c.decode(video=0)) == len(packets)


def test_engine_saves_a_clip_from_the_phone(phone, tmp_path):  # noqa: F811
    eng = make_engine(phone.port)
    eng.start()
    try:
        assert wait_until(lambda: connected_with_video(eng))
        assert wait_until(lambda: eng.clip_seconds() >= 2.0, timeout=10)
        path, length = eng.save_clip(30, rotation=90, folder=tmp_path)
        assert path.parent == tmp_path and path.name.startswith("Taco Cam ") and path.suffix == ".mp4"
        assert length >= 2.0
        with av.open(str(path)) as c:
            assert sum(1 for _ in c.decode(video=0)) >= 30
        assert tkhd_matrix(path) == clips._MATRIX[90]
    finally:
        eng.stop()


def test_engine_says_when_nothing_to_save(tmp_path):
    eng = make_engine(1)            # never connects
    with pytest.raises(ValueError, match="no video"):
        eng.save_clip(30, folder=tmp_path)


# ---- battery

def test_battery_warning_levels():
    base = {"link": "connected"}
    d = describe_status({**base, "phone": {"battery": 0.6, "charging": False}})
    assert d["battery_color"] == MUTED and "60%" in d["battery"]
    d = describe_status({**base, "phone": {"battery": 0.25, "charging": False}})
    assert d["battery_color"] == WARN and "plug in" in d["battery"]
    d = describe_status({**base, "phone": {"battery": 0.1, "charging": False}})
    assert d["battery_color"] == BAD and "now" in d["battery"]
    d = describe_status({**base, "phone": {"battery": 0.1, "charging": True}})
    assert d["battery_color"] == MUTED
    d = describe_status({**base, "phone": {"battery": 0.0, "charging": False}})   # unknown
    assert d["battery_color"] == MUTED


# ---- window

def _app(tk_root, tmp_path):
    path = tmp_path / "settings.json"
    s = S.default_settings()
    s["pc"]["hotkeys"] = False
    S.save(s, path)
    eng = {}

    def factory(settings, log=None):
        eng["e"] = StubEngine(settings, log)
        return eng["e"]
    return App(tk_root, factory, settings_path=path, autostart=False), eng


def test_ctrl_alt_0_saves_a_clip_turned_like_the_phone(tk_root, tmp_path):
    app, eng = _app(tk_root, tmp_path)
    e = eng["e"]
    calls = []

    def save_clip(seconds, rotation):
        calls.append((seconds, rotation))
        return tmp_path / "Taco Cam x.mp4", 30.0
    e.save_clip = save_clip

    class Keys:
        failed = []

        def __init__(self):
            self.n = [0]

        def pressed(self):
            out, self.n = self.n, []
            return out

        def stop(self):
            pass
    app.hotkeys = Keys()
    try:
        e.connect_phone()                       # rotation_hint 90
        app.refresh_from_status(force=True)
        app._background_tick()
        app._clip_thread.join(2)
        app._background_tick()
        assert calls == [(30, 90)]
        assert "Saved clip: Taco Cam x.mp4 (30 s)" in app.clip_label.cget("text")
        assert app.clip_btn.cget("text") == "Save last 30 s"
        app.ctl["pc.clip_seconds"].select(60)
        app.ctl["pc.clip_rotate"].select(0)
        app.save_clip()
        app._clip_thread.join(2)
        assert calls[-1] == (60, 0)
    finally:
        app.close()


def test_clip_error_is_shown(tk_root, tmp_path):
    app, eng = _app(tk_root, tmp_path)

    def broken(seconds, rotation):
        raise ValueError("no video from the iPhone yet")
    eng["e"].save_clip = broken
    try:
        app.save_clip()
        app._clip_thread.join(2)
        app._background_tick()
        assert "Clip not saved: no video" in app.clip_label.cget("text")
    finally:
        app.close()


def test_autostart_checkbox(tk_root, tmp_path, monkeypatch):
    state = {"on": False}

    def set_autostart(on):
        state["on"] = bool(on)
        return state["on"]
    monkeypatch.setattr("tacocam.app.shortcuts.set_autostart", set_autostart)
    app, _ = _app(tk_root, tmp_path)
    try:
        app.autostart_var.set(True)
        app.toggle_autostart()
        assert state["on"] is True and app.autostart_var.get() is True
        app.autostart_var.set(False)
        app.toggle_autostart()
        assert state["on"] is False
    finally:
        app.close()


def test_charger_unplugged_message(tk_root, tmp_path):
    app, eng = _app(tk_root, tmp_path)
    e = eng["e"]
    try:
        e.connect_phone(charging=True)
        app.refresh_from_status(force=True)
        with e.lock:
            e.status["phone"]["charging"] = False
        app.refresh_from_status(force=True)
        assert "unplugged" in app.hint_label.cget("text")
        pump(tk_root, 0.02)
    finally:
        app.close()


def test_startup_shortcut_path_and_args(monkeypatch, tmp_path):
    from tacocam import shortcuts
    made = []
    monkeypatch.setattr(shortcuts, "known_folder", lambda csidl: tmp_path)
    monkeypatch.setattr(shortcuts, "make", lambda path, args="-m tacocam": (made.append((path, args)),
                                                                             path.write_text("lnk")))
    assert shortcuts.set_autostart(True) is True
    assert made == [(tmp_path / "Taco Cam.lnk", "-m tacocam --minimized")]
    assert shortcuts.set_autostart(False) is False and not (tmp_path / "Taco Cam.lnk").exists()
