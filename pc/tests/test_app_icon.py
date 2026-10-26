"""Taco Cam has its own window/taskbar icon (not another Python app's)."""
from PIL import Image

from tacocam import __main__ as M


def test_icon_files_have_every_size():
    ico = Image.open(M.ICON_DIR / "taco-cam.ico")
    sizes = set(ico.info["sizes"])
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes


def test_set_icon_on_a_window(tk_root):
    M._set_icon(tk_root)
    assert tk_root.winfo_exists()  # no TclError raised above


def test_own_app_id():
    assert M.APP_ID == "TacoCam.PC"
    M._own_taskbar_entry()  # harmless to call twice / in tests
