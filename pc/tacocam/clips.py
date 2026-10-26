"""Save-the-hit clips: the last N seconds of the phone's video, written to an MP4 without re-encoding.

The engine feeds every VIDEO message into a ClipBuffer (the phone's own H.264/HEVC, full quality). Saving
copies the packets from a keyframe at least N seconds back into an MP4 and marks it upright (the MP4 track
matrix), so phones and social apps show it the right way round.
"""
import collections
import os
import re
import struct
import threading
from datetime import datetime
from fractions import Fraction
from pathlib import Path

import av

from .decoder import sniff_codec

KEEP_S = 65                     # longest clip offered is 60 s; a little extra to reach back to a keyframe
MAX_BYTES = 400 * 1024 * 1024   # never hold more than this (80 Mbps for 65 s would be ~650 MB)
START_CODE = b"\x00\x00\x00\x01"

# tkhd display matrices (as ffmpeg writes them) for turning the picture clockwise by 0/90/180/270 degrees.
_MATRIX = {
    0: (65536, 0, 0, 0, 65536, 0, 0, 0, 1 << 30),
    90: (0, 65536, 0, -65536, 0, 0, 0, 0, 1 << 30),
    180: (-65536, 0, 0, 0, -65536, 0, 0, 0, 1 << 30),
    270: (0, -65536, 0, 65536, 0, 0, 0, 0, 1 << 30),
}


class ClipBuffer:
    """Thread-safe ring of (pts_us, keyframe, data) for one continuous stream."""

    def __init__(self, keep_s=KEEP_S, max_bytes=MAX_BYTES):
        self.keep_us = int(keep_s * 1_000_000)
        self.max_bytes = max_bytes
        self._q = collections.deque()
        self._bytes = 0
        self._lock = threading.Lock()

    def add(self, flags, pts_us, data):
        key = bool(flags & 0x01)
        with self._lock:
            # A new format (codec/size) or a new connection starts a new stream: older packets can't be mixed in.
            if flags & 0x02 or (self._q and pts_us < self._q[-1][0]):
                self._q.clear()
                self._bytes = 0
            if not self._q and not key:
                return  # a clip must start with a keyframe
            self._q.append((pts_us, key, bytes(data)))
            self._bytes += len(data)
            newest = pts_us
            # Drop from the front, but only whole keyframe-to-keyframe groups (the front stays a keyframe), and
            # only while what remains still reaches back keep_s (or the memory cap forces it).
            while self._q:
                nxt = next((i for i, p in enumerate(self._q) if i > 0 and p[1]), None)
                if nxt is None:
                    break
                if not (newest - self._q[nxt][0] >= self.keep_us or self._bytes > self.max_bytes):
                    break
                for _ in range(nxt):
                    self._bytes -= len(self._q.popleft()[2])

    def clear(self):
        with self._lock:
            self._q.clear()
            self._bytes = 0

    def seconds(self):
        with self._lock:
            return (self._q[-1][0] - self._q[0][0]) / 1e6 if len(self._q) > 1 else 0.0

    def take(self, seconds):
        """Packets of the last `seconds`, starting at the keyframe at or before that point (or the oldest)."""
        with self._lock:
            items = list(self._q)
        if not items:
            return []
        start_at = items[-1][0] - int(seconds * 1_000_000)
        start = 0
        for i, (pts, key, _d) in enumerate(items):
            if pts > start_at:
                break
            if key:
                start = i
        return items[start:]


def _parameter_sets(data, codec):
    """SPS/PPS (H.264) or VPS/SPS/PPS (HEVC) from a keyframe, Annex-B, for the MP4 header."""
    keep = []
    for nal in re.split(rb"\x00\x00\x01", data):  # 3- and 4-byte start codes
        nal = nal.rstrip(b"\x00")
        if not nal:
            continue
        kind = (nal[0] >> 1) & 0x3F if codec == "hevc" else nal[0] & 0x1F
        if (codec == "hevc" and kind in (32, 33, 34)) or (codec != "hevc" and kind in (7, 8)):
            keep.append(START_CODE + nal)
    return b"".join(keep)


def _frame_size(data, codec):
    ctx = av.CodecContext.create(codec, "r")
    for frame in ctx.decode(av.Packet(data)):
        return frame.width, frame.height
    for frame in ctx.decode(None):
        return frame.width, frame.height
    raise ValueError("could not read the picture size")


def set_rotation(path, degrees):
    """Mark the MP4's video track to be shown turned clockwise by 0/90/180/270 degrees (tkhd matrix)."""
    m = _MATRIX[int(degrees) % 360]
    with open(path, "r+b") as f:
        data = f.read()
        i = data.find(b"tkhd")
        if i < 0:
            raise ValueError("no track header in the MP4")
        version = data[i + 4]
        off = i + 4 + (24 if version == 0 else 36) + 16
        f.seek(off)
        f.write(struct.pack(">9i", *m))


def write_mp4(path, packets, rotation=0):
    """packets: [(pts_us, keyframe, annexb)] starting with a keyframe. Returns the clip length in seconds."""
    if not packets or not packets[0][1]:
        raise ValueError("no video to save yet")
    first = packets[0][2]
    codec = sniff_codec(first) or "h264"
    width, height = _frame_size(first, codec)
    deltas = sorted(b[0] - a[0] for a, b in zip(packets, packets[1:]) if b[0] > a[0])
    fps = round(1e6 / deltas[len(deltas) // 2]) if deltas else 30
    tmp = Path(str(path) + ".part")
    ctr = av.open(str(tmp), "w", format="mp4")
    try:
        st = ctr.add_stream(codec, rate=max(1, min(fps, 120)))
        st.width, st.height = width, height
        st.time_base = Fraction(1, 90000)
        st.codec_context.extradata = _parameter_sets(first, codec)
        # HEVC stays "hev1" (parameter sets in the stream): PyAV 19 writes undecodable "hvc1" files from these
        # packets (tested 2026-10-25), while ffmpeg's own remux to hvc1 works. H.264 (the default) is "avc1".
        t0 = packets[0][0]
        last = -1
        for pts, key, data in packets:
            rel = pts - t0
            if rel <= last:
                continue
            last = rel
            pk = av.Packet(data)
            pk.stream = st
            pk.time_base = Fraction(1, 1_000_000)
            pk.pts = pk.dts = rel
            pk.is_keyframe = key
            ctr.mux(pk)
    finally:
        ctr.close()
    if rotation % 360:
        set_rotation(tmp, rotation)
    os.replace(tmp, path)
    return (packets[-1][0] - packets[0][0]) / 1e6


def clips_folder():
    """Videos\\Taco Cam clips (created when needed)."""
    folder = None
    if os.name == "nt":
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0E, None, 0, buf) == 0 and buf.value:  # My Videos
            folder = Path(buf.value)
    folder = (folder or Path.home() / "Videos") / "Taco Cam clips"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def clip_name(now=None):
    return f"Taco Cam {(now or datetime.now()).strftime('%Y-%m-%d %H-%M-%S')}.mp4"
