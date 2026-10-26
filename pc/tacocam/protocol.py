"""Taco Cam wire protocol (CONTRACT section 2).

Every message: u32 big-endian N (length of what follows) + u8 type + N-1 bytes payload, N in 1..16_777_216.
"""
import json
import struct

HELLO = 0x01
SET = 0x02
STATE = 0x03
KEYFRAME = 0x04
FOCUS_POINT = 0x05
VIDEO = 0x10
PING = 0x20
PONG = 0x21
LOG = 0x30

NAMES = {HELLO: "HELLO", SET: "SET", STATE: "STATE", KEYFRAME: "KEYFRAME", FOCUS_POINT: "FOCUS_POINT",
         VIDEO: "VIDEO", PING: "PING", PONG: "PONG", LOG: "LOG"}

MAX_LEN = 16_777_216          # largest N (type byte + payload)
PORT = 47777

VIDEO_FLAG_KEYFRAME = 0x01
VIDEO_FLAG_FORMAT_CHANGED = 0x02

_HEADER = struct.Struct(">IB")
_VIDEO_HEADER = struct.Struct(">BQ")

PC_HELLO = {"proto": 1, "client": "TacoCam PC", "version": "1.0"}


class ProtocolError(Exception):
    """The other side broke the framing rules: drop the connection."""


def encode(mtype, payload=b""):
    payload = bytes(payload)
    n = len(payload) + 1
    if n > MAX_LEN:
        raise ProtocolError(f"message too long ({n} bytes)")
    if not 0 <= mtype <= 0xFF:
        raise ProtocolError(f"bad message type {mtype}")
    return _HEADER.pack(n, mtype) + payload


def encode_json(mtype, obj):
    if not isinstance(obj, dict):
        raise ProtocolError("JSON payloads must be objects")
    return encode(mtype, json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def decode_json(payload):
    try:
        obj = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ProtocolError(f"bad JSON: {e}") from None
    if not isinstance(obj, dict):
        raise ProtocolError("JSON payload is not an object")
    return obj


def encode_video(flags, pts_us, data):
    return encode(VIDEO, _VIDEO_HEADER.pack(flags & 0xFF, pts_us & 0xFFFFFFFFFFFFFFFF) + bytes(data))


def decode_video(payload):
    """-> (flags, pts_us, annexb_bytes)"""
    if len(payload) < _VIDEO_HEADER.size:
        raise ProtocolError("VIDEO payload shorter than its 9-byte header")
    flags, pts = _VIDEO_HEADER.unpack_from(payload, 0)
    return flags, pts, bytes(payload[_VIDEO_HEADER.size:])


class FrameReader:
    """Collects bytes as they arrive (any split) and returns whole messages."""

    def __init__(self, max_len=MAX_LEN):
        self._buf = bytearray()
        self._max = max_len

    def feed(self, data):
        """Add received bytes; returns a list of (type, payload bytes). Raises ProtocolError on a bad length."""
        self._buf += data
        out = []
        buf = self._buf
        pos = 0
        end = len(buf)
        while end - pos >= 4:
            (n,) = struct.unpack_from(">I", buf, pos)
            if n < 1 or n > self._max:
                raise ProtocolError(f"bad message length {n}")
            if end - pos - 4 < n:
                break
            mtype = buf[pos + 4]
            out.append((mtype, bytes(buf[pos + 5:pos + 4 + n])))
            pos += 4 + n
        if pos:
            del buf[:pos]
        return out

    @property
    def pending(self):
        """Bytes received but not yet part of a whole message."""
        return len(self._buf)


def recv_messages(sock, reader, bufsize=1 << 20):
    """One recv() on sock; returns the whole messages it completed. Raises ConnectionError when closed."""
    data = sock.recv(bufsize)
    if not data:
        raise ConnectionError("connection closed")
    return reader.feed(data)
