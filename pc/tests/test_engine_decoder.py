"""Decoder on fake-phone streams: H.264, HEVC, format change mid-stream, start mid-GOP, errors, backlog."""
import os
import sys
import time

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from tacocam import protocol  # noqa: E402
from tacocam.decoder import Decoder, sniff_codec  # noqa: E402
import fake_phone  # noqa: E402

KEY = protocol.VIDEO_FLAG_KEYFRAME
CHANGED = protocol.VIDEO_FLAG_FORMAT_CHANGED


@pytest.fixture(autouse=True)
def collect_garbage_on_main_thread():
    """Free Tk leftovers of the app tests on the main thread, not inside the decoder thread."""
    import gc
    gc.collect()
    yield


def make_stream(codec, w, h, n, key_every=None, fps=30):
    """n encoded frames from the fake phone's scene/encoder: [(flags, pts, data)]."""
    enc = fake_phone.Encoder(codec, w, h, fps, 4)
    scene = fake_phone.Scene()
    settings = dict(fake_phone.DEFAULT_SETTINGS)
    out = []
    for i in range(n):
        bgr = scene.render(settings, w, h, 0, i, f"{w}x{h}")
        force = i == 0 or (key_every and i % key_every == 0)
        for data, key in enc.encode(bgr, force_key=force):
            out.append(((KEY if key else 0), i * 33333, data))
    return out


def wait_frames(dec, count, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if dec.decoded >= count:
            return True
        time.sleep(0.01)
    return False


def feed(dec, stream, gap=0.0):
    for flags, pts, data in stream:
        dec.submit(flags, pts, data)
        if gap:
            time.sleep(gap)


@pytest.fixture
def dec():
    requests = []
    d = Decoder(request_keyframe=lambda: requests.append(time.monotonic()), max_backlog=1000)
    d.requests = requests
    d.start()
    yield d
    d.stop()


@pytest.mark.parametrize("codec", ["h264", "hevc"])
def test_decode_stream(dec, codec):
    stream = make_stream(codec, 640, 360, 20)
    assert stream[0][0] & KEY
    assert sniff_codec(stream[0][2]) == codec
    dec.set_codec_hint(codec)
    feed(dec, stream)
    assert wait_frames(dec, 20)
    seq, rgb, pts, t = dec.latest()
    assert rgb.shape == (360, 640, 3) and rgb.dtype == np.uint8
    assert pts == 19 * 33333
    assert dec.dropped == 0 and dec.errors == 0
    # the top-left marker of the scene is red (RGB)
    r, g, b = rgb[10:20, 10:20].reshape(-1, 3).mean(axis=0)
    assert r > 180 and g < 80 and b < 80


def test_codec_found_from_bitstream_even_with_wrong_hint(dec):
    dec.set_codec_hint("h264")
    feed(dec, make_stream("hevc", 320, 240, 5))
    assert wait_frames(dec, 5)
    assert dec.latest()[1].shape == (240, 320, 3)


def test_format_change_mid_stream(dec):
    a = make_stream("h264", 640, 360, 10)
    b = make_stream("hevc", 1280, 720, 10)
    c = make_stream("h264", 320, 180, 10)
    b[0] = (b[0][0] | CHANGED, b[0][1], b[0][2])
    c[0] = (c[0][0] | CHANGED, c[0][1], c[0][2])
    feed(dec, a)
    assert wait_frames(dec, 10)
    assert dec.latest()[1].shape == (360, 640, 3)
    dec.set_codec_hint("hevc")
    feed(dec, b)
    assert wait_frames(dec, 20)
    assert dec.latest()[1].shape == (720, 1280, 3)
    feed(dec, c)
    assert wait_frames(dec, 30)
    assert dec.latest()[1].shape == (180, 320, 3)
    assert dec.errors == 0 and dec.dropped == 0


def test_size_change_same_codec_without_flag(dec):
    feed(dec, make_stream("h264", 640, 360, 5))
    feed(dec, make_stream("h264", 1280, 720, 5))
    assert wait_frames(dec, 10)
    assert dec.latest()[1].shape == (720, 1280, 3)


def test_waits_for_keyframe_when_joining_mid_stream(dec):
    stream = make_stream("h264", 640, 360, 30, key_every=15)
    feed(dec, stream[3:], gap=0.002)     # starts with P-frames
    assert wait_frames(dec, 15)
    time.sleep(0.1)
    assert dec.decoded == 15               # frames 15..29 only
    assert dec.dropped == 12               # frames 3..14 thrown away
    assert dec.requests, "decoder must ask the phone for a keyframe"


def test_recovers_after_garbage(dec):
    stream = make_stream("h264", 640, 360, 20, key_every=10)
    feed(dec, stream[:5])
    assert wait_frames(dec, 5)
    dec.submit(0, 0, b"\x00\x00\x00\x01\x41" + os.urandom(3000))   # broken P-frame
    dec.submit(0, 0, b"\x00\x00\x01\xff\xff\xff")                    # not even a NAL
    feed(dec, stream[10:])
    assert wait_frames(dec, 15)
    assert dec.latest()[1].shape == (360, 640, 3)


def test_backlog_skips_to_next_keyframe():
    requests = []
    d = Decoder(request_keyframe=lambda: requests.append(1), max_backlog=3)
    # not started: submissions pile up like a stalled decoder
    stream = make_stream("h264", 320, 180, 12, key_every=8)
    d._stop = False
    for flags, pts, data in stream[:8]:
        d.submit(flags, pts, data)
    assert d.backlog <= 3
    assert d.dropped >= 4 and requests
    d.submit(*stream[8])                   # keyframe: everything older is dropped, decoding restarts here
    assert d.backlog == 1
    d.start()
    for item in stream[9:]:
        d.submit(*item)
    assert wait_frames(d, 4)
    d.stop()


def test_sniff_codec():
    assert sniff_codec(b"\x00\x00\x00\x01\x67\x42\x00\x1f") == "h264"
    assert sniff_codec(b"\x00\x00\x00\x01\x09\xf0\x00\x00\x00\x01\x67\x64") == "h264"
    assert sniff_codec(b"\x00\x00\x00\x01\x40\x01\x0c\x01") == "hevc"
    assert sniff_codec(b"\x00\x00\x00\x01\x41\x9a") is None
    assert sniff_codec(b"") is None


def test_keeps_only_newest_and_drops_rather_than_lags():
    """A burst faster than real time never builds a queue longer than max_backlog; once frames
    arrive at a normal pace again, latest() is the newest frame."""
    requests = []
    d = Decoder(request_keyframe=lambda: requests.append(1), max_backlog=3).start()
    stream = make_stream("h264", 1280, 720, 70, key_every=10)
    for item in stream[:60]:
        d.submit(*item)
        assert d.backlog <= 3
    feed(d, stream[60:], gap=0.02)
    assert wait_frames(d, 1)
    end = time.monotonic() + 5
    while time.monotonic() < end and d.latest()[2] != 69 * 33333:
        time.sleep(0.01)
    assert d.latest()[2] == 69 * 33333
    assert d.decoded + d.dropped == 70
    d.stop()


def test_stop_is_quick():
    d = Decoder().start()
    t0 = time.monotonic()
    d.stop()
    assert time.monotonic() - t0 < 1.0
