"""Scanner feed: full-quality pictures in shared memory (two slots, BGR, upright), only while a reader wants them."""
import os
import struct
import threading
import time

import cv2
import numpy as np
import pytest

from test_engine_e2e import connected_with_video, make_engine, phone, wait_until  # noqa: F401  (fixture)

from tacocam import framefeed as F


@pytest.fixture
def name():
    return f"TacoCamFeedUnit{os.getpid()}_{time.monotonic_ns()}"


def rgb_picture(w=320, h=180):
    """Red left half, blue right half: shows both colour order and turning."""
    img = np.zeros((h, w, 3), np.uint8)
    img[:, : w // 2] = (255, 0, 0)
    img[:, w // 2:] = (0, 0, 255)
    return img


def test_bgr_upright_round_trip(name):
    w = F.FeedWriter(name)
    r = F.FeedReader(name)
    try:
        assert r.read() is None                                     # nothing written yet
        assert w.write(rgb_picture(), turn=90)
        img, pid = r.read()
        assert img.shape == (320, 180, 3)                           # turned clockwise
        assert tuple(img[5, 90]) == (0, 0, 255) and tuple(img[-5, 90]) == (255, 0, 0)   # BGR red on top
        w.write(rgb_picture(), turn=0)
        img2, pid2 = r.read()
        assert img2.shape == (180, 320, 3) and pid2 != pid
        assert tuple(img2[90, 5]) == (0, 0, 255)
    finally:
        r.close()
        w.close()


def test_full_4k_fits_and_too_big_is_refused(name):
    w = F.FeedWriter(name)
    r = F.FeedReader(name)
    try:
        big = np.random.default_rng(1).integers(0, 255, (2160, 3840, 3), dtype=np.uint8)
        assert w.write(big, turn=270)
        img, _ = r.read()
        assert np.array_equal(img, cv2.rotate(cv2.cvtColor(big, cv2.COLOR_RGB2BGR), cv2.ROTATE_90_COUNTERCLOCKWISE))
        assert not w.write(np.zeros((4000, 4000, 3), np.uint8))
    finally:
        r.close()
        w.close()


def test_wanted_only_after_a_reader_asks(name):
    w = F.FeedWriter(name)
    try:
        assert not w.wanted()
        r = F.FeedReader(name)
        r.read()
        assert w.wanted()
        assert not w.wanted(now=time.time() + 5)                   # a reader that stops asking is forgotten
        r.close()
    finally:
        w.close()


def test_old_picture_is_not_returned(name):
    w = F.FeedWriter(name)
    r = F.FeedReader(name)
    try:
        w.write(np.zeros((10, 10, 3), np.uint8))
        (i,) = struct.unpack_from("<I", w.buf, F.LATEST_OFF)
        struct.pack_into("<d", w.buf, F._slot_hdr_off(i) + 24, time.time() - 10)   # decoded 10 s ago
        assert r.read() is None
    finally:
        r.close()
        w.close()


def test_reader_keeps_up_with_a_30_fps_4k_writer(name):
    """The real situation: 4K pictures 30 times a second. Reads must succeed and never be torn."""
    w = F.FeedWriter(name)
    r = F.FeedReader(name)
    stop = threading.Event()
    frames = [np.full((2160, 3840, 3), v, np.uint8) for v in (0, 255)]

    def writer():
        i = 0
        while not stop.is_set():
            w.write(frames[i % 2])
            i += 1
            time.sleep(1 / 30)
    t = threading.Thread(target=writer)
    t.start()
    try:
        time.sleep(0.2)
        good, end = 0, time.monotonic() + 2.0
        while time.monotonic() < end:
            got = r.read()
            if got is not None:
                img = got[0]
                assert img[0, 0, 0] == img[-1, -1, 0]               # one picture, never two halves
                good += 1
        assert good >= 40                                           # >= 20 reads a second
    finally:
        stop.set()
        t.join()
        r.close()
        w.close()


def test_missing_feed_is_a_clear_error():
    with pytest.raises(FileNotFoundError):
        F.FeedReader("TacoCamFeedDoesNotExist12345")


def test_engine_feeds_pictures_only_when_asked(phone):  # noqa: F811
    eng = make_engine(phone.port, clip_rotate=90)
    eng.start()
    try:
        assert wait_until(lambda: connected_with_video(eng))
        assert wait_until(lambda: eng._feed is not None)
        time.sleep(0.5)
        assert eng.feed_frames == 0 and not eng.feed_in_use()   # no reader: no copying
        r = F.FeedReader(eng.feed_name)
        try:
            img, _ = wait_until(lambda: r.read(), timeout=5)
            assert img.shape == (1280, 720, 3)                  # the phone's own 720p picture, turned upright
            assert eng.feed_in_use() and eng.feed_frames > 0
        finally:
            r.close()
    finally:
        eng.stop()
