"""Virtual camera output (CONTRACT section 7).

First choice: the Unity Capture DirectShow filter registered as "Taco Cam" (pc/vcam/Install Taco Cam camera.bat),
through pyvirtualcam's "unitycapture" backend. Fallback: OBS Virtual Camera ("obs" backend), which can't be
used while OBS's own Start Virtual Camera button is on. Frame pacing and repeating the last frame are done
by the engine's output loop; this module only opens, sends and closes.
"""
import numpy as np

UNITY_CLSID_64 = "{5C2CD55C-92AD-4999-8666-912BD3E70010}"
MAX_W, MAX_H = 3840, 3840          # Unity Capture's buffer holds 3840x2160 RGBA16 = any of our sizes


class VcamNotInstalled(Exception):
    """Neither the Taco Cam camera nor OBS Virtual Camera is available."""


class VcamError(Exception):
    """A camera exists but could not be started (e.g. busy)."""


def unitycapture_registered_name():
    """Name the 64-bit Unity Capture filter is registered under ("Taco Cam" after our install), or None."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{UNITY_CLSID_64}") as k:
            value, _ = winreg.QueryValueEx(k, "")
            return str(value) if value else None
    except OSError:
        return None


class SenderLock:
    """Only one Taco Cam may feed a camera: two senders into the same Unity Capture device make the picture
    flicker between them. A Windows named mutex (freed by Windows if the process dies)."""

    def __init__(self, backend, name):
        self.name = f"Local\\TacoCam-vcam-{backend}-{name}"
        self._handle = None

    def acquire(self):
        try:
            import ctypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except (ImportError, OSError, AttributeError):
            return True                      # not Windows: nothing to guard
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        k32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = k32.CreateMutexW(None, 0, self.name)
        if not handle:
            return True
        if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS: someone else holds it
            k32.CloseHandle(handle)
            return False
        self._handle, self._k32 = handle, k32
        return True

    def release(self):
        if self._handle:
            self._k32.CloseHandle(self._handle)
            self._handle = None


class PyVirtualCam:
    """An open pyvirtualcam camera."""

    def __init__(self, cam, backend, lock=None):
        self._cam = cam
        self._lock = lock
        self.backend = backend
        self.device = cam.device
        self.width, self.height = cam.width, cam.height

    def send(self, frame):
        self._cam.send(frame)

    def close(self):
        try:
            self._cam.close()
        except Exception:
            pass
        if self._lock is not None:
            self._lock.release()
            self._lock = None


def open_camera(width, height, fps, name="Taco Cam", backends=("unitycapture", "obs")):
    """Open the virtual camera: Unity Capture under `name`, else OBS Virtual Camera.

    Raises VcamNotInstalled or VcamError (message says what to do)."""
    try:
        import pyvirtualcam
    except ImportError as e:
        raise VcamNotInstalled(f"pyvirtualcam is not installed ({e})") from None
    errors = []
    busy = False
    for backend in backends:
        if backend == "unitycapture":
            registered = unitycapture_registered_name()
            if registered != name:
                errors.append(f"unitycapture: '{name}' camera not installed"
                              + (f" (registered as '{registered}')" if registered else ""))
                continue
        lock = SenderLock(backend, name if backend == "unitycapture" else "obs")
        if not lock.acquire():
            raise VcamError(f"Another Taco Cam window is already sending to the "
                            f"{name if backend == 'unitycapture' else 'OBS Virtual Camera'} camera: close it first.")
        try:
            cam = pyvirtualcam.Camera(int(width), int(height), float(fps), fmt=pyvirtualcam.PixelFormat.RGB,
                                      backend=backend, device=name if backend == "unitycapture" else None)
        except Exception as e:
            lock.release()
            text = str(e)
            errors.append(f"{backend}: {text}")
            low = text.lower()
            if backend == "obs" and ("in use" in low or "could not be started" in low or "already" in low):
                busy = True
            continue
        return PyVirtualCam(cam, backend, lock)
    msg = "; ".join(errors)
    if busy:
        raise VcamError("OBS Virtual Camera is busy (turn off OBS's own Start Virtual Camera button) "
                        "and the Taco Cam camera is not installed. " + msg)
    raise VcamNotInstalled("The Taco Cam camera is not installed: run pc/vcam/Install Taco Cam camera.bat. "
                           + msg)


class NullCamera:
    """Stand-in output for tests and for running without a virtual camera. Keeps the last frame sent."""

    backend = "null"

    def __init__(self, width, height, fps, name="Taco Cam"):
        self.width, self.height, self.fps = int(width), int(height), fps
        self.device = f"null:{name}"
        self.frames = 0
        self.last = None
        self.closed = False

    def send(self, frame):
        if frame.shape != (self.height, self.width, 3) or frame.dtype != np.uint8:
            raise ValueError(f"frame {frame.shape} does not match {self.width}x{self.height}")
        self.frames += 1
        self.last = frame

    def close(self):
        self.closed = True


def null_factory(width, height, fps, name="Taco Cam"):
    return NullCamera(width, height, fps, name)
