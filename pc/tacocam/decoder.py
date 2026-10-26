"""H.264 / HEVC decoder for the phone's VIDEO messages (CONTRACT section 2).

Each VIDEO message is one whole access unit in Annex-B form, so it goes straight into the codec as one
packet (no parser: a parser would hold every frame back until the next one arrives). Decoding runs on its
own thread and only the newest picture is kept. When decoding falls behind, waiting frames are thrown
away up to the next keyframe (P-frames can't be skipped alone) and a keyframe is asked for.
"""
import collections
import threading
import time

import av

from . import protocol

def iter_nal_headers(data, limit=8):
    """First two header bytes of the first `limit` NAL units in an Annex-B buffer."""
    out = []
    i = 0
    n = len(data)
    while len(out) < limit:
        j = data.find(b"\x00\x00\x01", i)
        if j < 0 or j + 4 >= n:
            break
        out.append((data[j + 3], data[j + 4]))
        i = j + 3
    return out


def sniff_codec(data):
    """'h264' or 'hevc' from the parameter sets in front of a keyframe; None when unsure.

    HEVC VPS/SPS/PPS: 2-byte header, type 32/33/34, layer 0, temporal id 0 -> 0x40/0x42/0x44 then 0x01.
    H.264 SPS: 1-byte header with type 7 (0x67, 0x27, 0x47, 0x07)."""
    for b0, b1 in iter_nal_headers(data):
        if b0 & 0x80:
            continue
        if b0 in (0x40, 0x42, 0x44) and b1 == 0x01:
            return "hevc"
        if b0 & 0x1F == 7:
            return "h264"
    return None


class Decoder:
    """submit() VIDEO messages from any thread; read the newest picture with latest()/wait_new()."""

    def __init__(self, request_keyframe=None, log=None, max_backlog=3, codec="h264"):
        self.request_keyframe = request_keyframe or (lambda: None)
        self.log = log or (lambda s: None)
        self.max_backlog = max_backlog
        self.codec_hint = codec
        self._q = collections.deque()
        self._cv = threading.Condition()
        self._stop = False
        self._thread = None
        self._ctx = None
        self._ctx_codec = None
        self._waiting_key = True
        self._latest = None          # (seq, rgb ndarray, pts_us, monotonic time)
        self._seq = 0
        self._new = threading.Condition()
        self.decoded = 0
        self.dropped = 0
        self.errors = 0
        self._last_key_request = 0.0

    # -- control ---------------------------------------------------------------------------------
    def start(self):
        with self._cv:
            self._stop = False
        self._thread = threading.Thread(target=self._run, name="tacocam-decoder", daemon=True)
        self._thread.start()
        return self

    def signal_stop(self):
        """Ask the thread to end without waiting for it."""
        with self._cv:
            self._stop = True
            self._q.clear()
            self._cv.notify_all()
        with self._new:
            self._new.notify_all()

    def stop(self, timeout=1.0):
        self.signal_stop()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        with self._new:
            self._new.notify_all()

    def reset(self):
        """New connection: forget queued frames and wait for the next keyframe."""
        with self._cv:
            self._q.clear()
            self._waiting_key = True
            self._reset_ctx = True
            self._cv.notify_all()

    def set_codec_hint(self, codec):
        if codec in ("h264", "hevc"):
            self.codec_hint = codec

    # -- input -----------------------------------------------------------------------------------
    def submit(self, flags, pts_us, data):
        key = bool(flags & protocol.VIDEO_FLAG_KEYFRAME)
        changed = bool(flags & protocol.VIDEO_FLAG_FORMAT_CHANGED)
        ask = False
        with self._cv:
            if self._stop:
                return
            if key:
                # A keyframe makes everything still waiting useless: decode from here.
                self.dropped += len(self._q)
                self._q.clear()
            elif len(self._q) >= self.max_backlog:
                self.dropped += len(self._q) + 1
                self._q.clear()
                self._waiting_key = True
                ask = True
                data = None
            if data is not None:
                self._q.append((key, changed, pts_us, data))
                self._cv.notify()
        if ask:
            self._ask_keyframe("decoder fell behind")

    def _ask_keyframe(self, why):
        now = time.monotonic()
        if now - self._last_key_request > 0.5:
            self._last_key_request = now
            try:
                self.request_keyframe()
            except Exception:
                pass

    # -- output ----------------------------------------------------------------------------------
    def latest(self):
        """(seq, rgb HxWx3 uint8, pts_us, decoded_at monotonic) or None. The array is not modified later."""
        return self._latest

    def wait_new(self, last_seq, timeout):
        with self._new:
            if self._latest is not None and self._latest[0] != last_seq:
                return self._latest
            self._new.wait(timeout)
            return self._latest

    def clear_latest(self):
        self._latest = None

    # -- thread ----------------------------------------------------------------------------------
    _reset_ctx = False

    def _run(self):
        while True:
            with self._cv:
                while not self._q and not self._stop:
                    self._cv.wait(0.5)
                if self._stop:
                    break
                key, changed, pts_us, data = self._q.popleft()
                if self._reset_ctx:
                    self._reset_ctx = False
                    self._close_ctx()
                waiting = self._waiting_key
            if waiting and not key:
                with self._cv:
                    self.dropped += 1
                self._ask_keyframe("waiting for keyframe")
                continue
            self._decode(key, changed, pts_us, data)
        self._close_ctx()

    def _close_ctx(self):
        self._ctx = None
        self._ctx_codec = None

    def _open_ctx(self, codec):
        ctx = av.CodecContext.create(codec, "r")
        try:
            ctx.flags |= av.codec.context.Flags.low_delay
        except Exception:
            pass
        self._ctx = ctx
        self._ctx_codec = codec

    def _decode(self, key, changed, pts_us, data):
        codec = self.codec_hint
        if key:
            codec = sniff_codec(data) or codec
        if self._ctx is None or (key and (changed or codec != self._ctx_codec)):
            if self._ctx is not None and codec != self._ctx_codec:
                self.log(f"Video format changed to {codec.upper()}")
            self._open_ctx(codec)
        try:
            frames = self._ctx.decode(av.Packet(data))
            for frame in frames:
                rgb = frame.to_ndarray(format="rgb24")
                with self._new:
                    self._seq += 1
                    self._latest = (self._seq, rgb, pts_us, time.monotonic())
                    self.decoded += 1
                    self._new.notify_all()
            if key:
                with self._cv:
                    self._waiting_key = False
        except (av.error.FFmpegError, ValueError, OSError) as e:
            self.errors += 1
            if self.errors <= 3 or self.errors % 100 == 0:
                self.log(f"Video decode error ({e}); waiting for the next keyframe")
            with self._cv:
                self._waiting_key = True
                self.dropped += 1
            self._close_ctx()
            self._ask_keyframe("decode error")

    @property
    def backlog(self):
        return len(self._q)
