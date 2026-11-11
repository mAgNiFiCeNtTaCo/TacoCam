"""Taco Cam wire protocol (CONTRACT section 2).

Every message: u32 big-endian N (length of what follows) + u8 type + N-1 bytes payload, N in 1..16_777_216.
"""
import hashlib
import hmac
import json
import os
import struct

HELLO = 0x01
SET = 0x02
STATE = 0x03
KEYFRAME = 0x04
FOCUS_POINT = 0x05
AUTH = 0x06
VIDEO = 0x10
PING = 0x20
PONG = 0x21
LOG = 0x30

NAMES = {HELLO: "HELLO", SET: "SET", STATE: "STATE", KEYFRAME: "KEYFRAME", FOCUS_POINT: "FOCUS_POINT",
         AUTH: "AUTH", VIDEO: "VIDEO", PING: "PING", PONG: "PONG", LOG: "LOG"}

# Wi-Fi pairing (CONTRACT section 2, "Pairing"): the code the phone shows, proved in both directions.
PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIR_CODE_LEN = 16
PAIR_NONCE_LEN = 16
_PAIR_LABEL = b"tacocam-pair-v1 "

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


def pair_normalize(text):
    """The code as both sides use it: capitals, only the letters and digits a code can hold (no dashes, spaces)."""
    return "".join(ch for ch in str(text or "").upper() if ch in PAIR_ALPHABET)


def pair_nonce():
    return os.urandom(PAIR_NONCE_LEN)


def pair_mac(code, role, phone_nonce, pc_nonce):
    """HMAC-SHA256 keyed with the code over "tacocam-pair-v1 <role> " + phone nonce + PC nonce. role: "pc" | "phone"."""
    msg = _PAIR_LABEL + role.encode("ascii") + b" " + bytes(phone_nonce) + bytes(pc_nonce)
    return hmac.new(pair_normalize(code).encode("ascii"), msg, hashlib.sha256).digest()


def pair_check(mac, code, role, phone_nonce, pc_nonce):
    """True when mac is the right proof. Compared in constant time; a code of the wrong length never passes."""
    if len(pair_normalize(code)) != PAIR_CODE_LEN or not isinstance(mac, (bytes, bytearray)):
        return False
    return hmac.compare_digest(bytes(mac), pair_mac(code, role, phone_nonce, pc_nonce))


def pair_unhex(text, length=None):
    """Hex string -> bytes, or None when it is not hex (or not `length` bytes long)."""
    try:
        data = bytes.fromhex(text) if isinstance(text, str) else None
    except ValueError:
        return None
    if data is None or (length is not None and len(data) != length):
        return None
    return data


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
