"""Taco Cam: iPhone as a webcam for OBS."""
import sys
from pathlib import Path


def _own_cache_folder():
    """In the friend's copy (the zip or the installed one, which bring their own Python) keep Python's compiled
    files in ONE folder, <Taco Cam>\\tacocam-cache, instead of __pycache__ folders all over pc\\ and python\\.
    The uninstaller can then remove exactly what Taco Cam made (security finding WEBCAM-20261128-05)."""
    try:
        exe_dir = Path(sys.executable).resolve().parent
        top = Path(__file__).resolve().parents[2]
        if exe_dir == top / "python" and any(exe_dir.glob("python3*._pth")):
            sys.pycache_prefix = str(top / "tacocam-cache")
    except (OSError, IndexError):
        pass


_own_cache_folder()
