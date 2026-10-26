"""Virtual camera helpers that run without admin and without touching the real camera."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tacocam import vcam  # noqa: E402


def test_sender_lock_allows_one_sender():
    a = vcam.SenderLock("unitycapture", "Taco Cam test-lock")
    b = vcam.SenderLock("unitycapture", "Taco Cam test-lock")
    assert a.acquire()
    if sys.platform == "win32":
        assert not b.acquire()
    a.release()
    assert b.acquire()
    b.release()


def test_no_backend_means_not_installed():
    with pytest.raises(vcam.VcamNotInstalled) as e:
        vcam.open_camera(1280, 720, 30, backends=())
    assert "Install Taco Cam camera.bat" in str(e.value)


def test_unitycapture_needs_the_right_name():
    with pytest.raises(vcam.VcamNotInstalled) as e:
        vcam.open_camera(1280, 720, 30, name="No Such Camera 123", backends=("unitycapture",))
    assert "not installed" in str(e.value)


def test_registered_name_is_text_or_none():
    name = vcam.unitycapture_registered_name()
    assert name is None or isinstance(name, str)


def test_null_camera_checks_frame_size():
    cam = vcam.null_factory(640, 360, 30)
    cam.send(np.zeros((360, 640, 3), np.uint8))
    assert cam.frames == 1
    with pytest.raises(ValueError):
        cam.send(np.zeros((720, 1280, 3), np.uint8))
    cam.close()
    assert cam.closed
