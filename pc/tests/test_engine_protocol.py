"""Framing (CONTRACT section 2): round trips, partial reads, bad lengths."""
import os
import random
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tacocam import protocol  # noqa: E402


def test_encode_layout():
    msg = protocol.encode(protocol.PING, b"abc")
    assert msg == struct.pack(">I", 4) + bytes([0x20]) + b"abc"
    assert protocol.encode(protocol.KEYFRAME) == b"\x00\x00\x00\x01\x04"


def test_type_constants():
    assert (protocol.HELLO, protocol.SET, protocol.STATE, protocol.KEYFRAME, protocol.FOCUS_POINT) == (1, 2, 3, 4, 5)
    assert (protocol.VIDEO, protocol.PING, protocol.PONG, protocol.LOG) == (0x10, 0x20, 0x21, 0x30)


def test_round_trip_all_types():
    msgs = [
        (protocol.HELLO, b'{"proto":1}'),
        (protocol.SET, b'{"zoom":0.5}'),
        (protocol.STATE, b"{}"),
        (protocol.KEYFRAME, b""),
        (protocol.FOCUS_POINT, b'{"x":0.1,"y":0.9}'),
        (protocol.VIDEO, bytes(range(256)) * 10),
        (protocol.PING, b"\x00" * 8),
        (protocol.PONG, b"\x01" * 8),
        (protocol.LOG, "warning: ünïcode".encode()),
        (0x7F, b"unknown type is still framed"),
    ]
    stream = b"".join(protocol.encode(t, p) for t, p in msgs)
    r = protocol.FrameReader()
    assert r.feed(stream) == msgs
    assert r.pending == 0


@pytest.mark.parametrize("seed", range(5))
def test_partial_reads_any_split(seed):
    rnd = random.Random(seed)
    msgs = [(rnd.choice([1, 2, 3, 0x10, 0x21]), os.urandom(rnd.randint(0, 5000))) for _ in range(40)]
    stream = b"".join(protocol.encode(t, p) for t, p in msgs)
    r = protocol.FrameReader()
    got = []
    i = 0
    while i < len(stream):
        n = rnd.choice([1, 2, 3, 4, 5, 7, 100, 4096])
        got += r.feed(stream[i:i + n])
        i += n
    assert got == msgs


def test_one_byte_at_a_time():
    msg = protocol.encode_json(protocol.STATE, {"a": [1, 2, 3]})
    r = protocol.FrameReader()
    out = []
    for b in msg:
        out += r.feed(bytes([b]))
    assert out == [(protocol.STATE, b'{"a":[1,2,3]}')]


def test_zero_length_is_error():
    with pytest.raises(protocol.ProtocolError):
        protocol.FrameReader().feed(b"\x00\x00\x00\x00\x01")


def test_too_long_is_error():
    with pytest.raises(protocol.ProtocolError):
        protocol.FrameReader().feed(struct.pack(">I", protocol.MAX_LEN + 1) + b"\x10")


def test_max_length_accepted():
    # header only: a 16 MiB message is accepted (not yet complete)
    r = protocol.FrameReader()
    assert r.feed(struct.pack(">I", protocol.MAX_LEN) + b"\x10") == []
    assert r.pending == 5


def test_encode_refuses_oversize():
    with pytest.raises(protocol.ProtocolError):
        protocol.encode(protocol.VIDEO, bytes(protocol.MAX_LEN))
    assert len(protocol.encode(protocol.VIDEO, bytes(protocol.MAX_LEN - 1))) == protocol.MAX_LEN + 4


def test_bad_length_after_good_message():
    r = protocol.FrameReader()
    good = protocol.encode(protocol.PING, b"x")
    with pytest.raises(protocol.ProtocolError):
        r.feed(good + b"\xff\xff\xff\xff\x10")


def test_json_helpers():
    msg = protocol.encode_json(protocol.SET, {"zoom": 0.5, "focus": {"mode": "auto"}})
    (t, p), = protocol.FrameReader().feed(msg)
    assert t == protocol.SET
    assert protocol.decode_json(p) == {"zoom": 0.5, "focus": {"mode": "auto"}}
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_json(b"[1,2]")
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_json(b"{not json")
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_json(b"\xff\xfe")
    with pytest.raises(protocol.ProtocolError):
        protocol.encode_json(protocol.SET, [1])


def test_video_payload():
    data = b"\x00\x00\x00\x01\x67\x42" + os.urandom(1000)
    msg = protocol.encode_video(protocol.VIDEO_FLAG_KEYFRAME | protocol.VIDEO_FLAG_FORMAT_CHANGED,
                                123456789012, data)
    (t, p), = protocol.FrameReader().feed(msg)
    assert t == protocol.VIDEO
    assert p[0] == 0x03 and struct.unpack(">Q", p[1:9])[0] == 123456789012
    assert protocol.decode_video(p) == (3, 123456789012, data)
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_video(b"\x01\x00")


def test_pc_hello_matches_contract():
    assert protocol.PC_HELLO == {"proto": 1, "client": "TacoCam PC", "version": "1.0"}
    assert protocol.PORT == 47777
