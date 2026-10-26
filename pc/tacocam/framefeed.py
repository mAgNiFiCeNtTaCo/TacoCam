"""Scanner feed: the newest full-quality phone picture in shared memory, for other programs on this PC
(the Whatnot card scanner). No compression, no network; costs nothing while nobody reads.

Layout v2 (CONTRACT section 8): a named shared memory block FEED_NAME, little-endian.
  0   magic   4s  b"TCF2"
  4   version u32 2
  8   want    f64 time.time() until which a reader wants pictures (the READER writes this, ~2 s ahead)
  16  latest  u32 slot (0/1) holding the newest complete picture
  64 + 32*i   slot i header: seq u64 (odd while being written), width u32, height u32, format u32
              (2 = BGR24, already upright), pad u32, time f64 (decoded at, time.time())
  128 + i*SLOT_BYTES  slot i pixels, rows packed (width * 3 bytes)
Two slots: Taco Cam writes the one readers are not on, then flips `latest`, so a reader copying the newest
picture (~8 ms at 4K) is not overwritten by the next one (33 ms later). The seq check still guards it.
"""
import struct
import time
from multiprocessing import shared_memory

import cv2
import numpy as np

FEED_NAME = "TacoCamFeed2"
MAGIC = b"TCF2"
MAX_PIXELS = 3840 * 2160
SLOT_BYTES = MAX_PIXELS * 3
DATA_OFF = 128
SIZE = DATA_OFF + 2 * SLOT_BYTES
WANT_OFF, LATEST_OFF = 8, 16
SLOT_HDR = struct.Struct("<QIIIId")          # seq, width, height, format, pad, time
FMT_BGR24 = 2
_ROTATE = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def _slot_hdr_off(i):
    return 64 + 32 * i


class FeedWriter:
    def __init__(self, name=FEED_NAME):
        try:
            self.shm = shared_memory.SharedMemory(name=name, create=True, size=SIZE)
        except FileExistsError:
            self.shm = shared_memory.SharedMemory(name=name)
        self.buf = self.shm.buf
        struct.pack_into("<4sIdI", self.buf, 0, MAGIC, 2, 0.0, 0)
        for i in (0, 1):
            SLOT_HDR.pack_into(self.buf, _slot_hdr_off(i), 0, 0, 0, 0, 0, 0.0)
        self.seq = [0, 0]

    def wanted(self, now=None):
        (want,) = struct.unpack_from("<d", self.buf, WANT_OFF)
        return want > (now or time.time())

    def write(self, rgb, turn=0):
        """Store an RGB picture as BGR, turned clockwise by `turn` degrees (0/90/180/270)."""
        h, w = rgb.shape[:2]
        if h * w > MAX_PIXELS or rgb.ndim != 3 or rgb.shape[2] != 3:
            return False
        turn = int(turn) % 360
        oh, ow = (w, h) if turn in (90, 270) else (h, w)
        (latest,) = struct.unpack_from("<I", self.buf, LATEST_OFF)
        i = 1 - latest
        off = _slot_hdr_off(i)
        self.seq[i] += 1                                                 # odd: being written
        struct.pack_into("<Q", self.buf, off, self.seq[i])
        dst = np.frombuffer(self.buf, np.uint8, count=oh * ow * 3, offset=DATA_OFF + i * SLOT_BYTES).reshape(oh, ow, 3)
        if turn in _ROTATE:
            cv2.rotate(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), _ROTATE[turn], dst=dst)
        else:
            cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR, dst=dst)
        del dst
        self.seq[i] += 1                                                 # even: complete
        SLOT_HDR.pack_into(self.buf, off, self.seq[i], ow, oh, FMT_BGR24, 0, time.time())
        struct.pack_into("<I", self.buf, LATEST_OFF, i)
        return True

    def close(self):
        self.buf = None
        self.shm.close()


class FeedReader:
    """Used by tests here; the scanner keeps its own copy of this reader."""

    def __init__(self, name=FEED_NAME):
        self.shm = shared_memory.SharedMemory(name=name)   # FileNotFoundError when Taco Cam isn't running
        if bytes(self.shm.buf[:4]) != MAGIC:
            self.shm.close()
            raise ValueError("not a Taco Cam feed (or an older version)")

    def read(self, max_age=2.0, tries=5):
        """(bgr copy, upright) of the newest picture, or None if there is none / it is older than max_age."""
        buf = self.shm.buf
        struct.pack_into("<d", buf, WANT_OFF, time.time() + 2.0)
        for _ in range(tries):
            (i,) = struct.unpack_from("<I", buf, LATEST_OFF)
            s1, w, h, fmt, _pad, t = SLOT_HDR.unpack_from(buf, _slot_hdr_off(i))
            if s1 % 2 or not w or not h or fmt != FMT_BGR24:
                if not s1:
                    return None
                time.sleep(0.002)
                continue
            if time.time() - t > max_age:
                return None
            img = np.frombuffer(buf, np.uint8, count=w * h * 3, offset=DATA_OFF + i * SLOT_BYTES).reshape(h, w, 3).copy()
            if SLOT_HDR.unpack_from(buf, _slot_hdr_off(i))[0] == s1:
                return img, (i, s1)
        return None

    def close(self):
        self.shm.close()
