"""Creates "Taco Cam" shortcuts on the Desktop and in the Start menu, with the Taco Cam icon.

The shortcuts carry the window's AppUserModelID (TacoCam.PC), so a pinned shortcut and the running window
share one taskbar button. Run once from anywhere: python pc/tools/make_shortcuts.py  (--remove deletes them)
Windows only; no extra packages (plain COM through ctypes).
"""
import ctypes
import ctypes.wintypes as W
import os
import shutil
import sys
from pathlib import Path

PC = Path(__file__).resolve().parents[1]
ICON = PC / "tacocam" / "assets" / "taco-cam.ico"
APP_ID = "TacoCam.PC"
NAME = "Taco Cam.lnk"

ole32 = ctypes.windll.ole32
shell32 = ctypes.windll.shell32


class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]


def guid(s):
    g = GUID()
    if ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g)) != 0:
        raise ValueError(s)
    return g


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_uint32)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("p", ctypes.c_void_p), ("p2", ctypes.c_void_p)]


CLSID_ShellLink = guid("{00021401-0000-0000-C000-000000000046}")
IID_IShellLinkW = guid("{000214F9-0000-0000-C000-000000000046}")
IID_IPersistFile = guid("{0000010B-0000-0000-C000-000000000046}")
IID_IPropertyStore = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
PKEY_AppUserModel_ID = PROPERTYKEY(guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), 5)
VT_LPWSTR = 31
HRESULT = ctypes.c_long


class Com:
    """Minimal COM pointer: call(index, argtypes, *args) through the vtable."""

    def __init__(self, ptr):
        self.ptr = ptr

    def call(self, index, argtypes, *args):
        vtbl = ctypes.cast(ctypes.cast(self.ptr, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        fn = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, *argtypes)(vtbl[index])
        hr = fn(self.ptr, *args)
        if hr < 0:
            raise OSError(f"COM call {index} failed: {hr & 0xFFFFFFFF:#010x}")
        return hr

    def query(self, iid):
        out = ctypes.c_void_p()
        self.call(0, [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(iid), ctypes.byref(out))
        return Com(out)

    def release(self):
        vtbl = ctypes.cast(ctypes.cast(self.ptr, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(self.ptr)


def known_folder(csidl):
    buf = ctypes.create_unicode_buffer(W.MAX_PATH)
    shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def pythonw():
    """The pythonw that `Taco Cam.bat` uses (the Windows Store / Python manager alias when present)."""
    alias = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "pythonw.exe"
    if alias.exists():
        return alias
    found = shutil.which("pythonw") or shutil.which("pyw")
    if found:
        return Path(found)
    return Path(sys.executable).with_name("pythonw.exe")


def make(path):
    ole32.CoInitialize(None)
    raw = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(CLSID_ShellLink), None, 1, ctypes.byref(IID_IShellLinkW), ctypes.byref(raw))
    if hr != 0:
        raise OSError(f"CoCreateInstance failed: {hr & 0xFFFFFFFF:#010x}")
    link = Com(raw)
    wstr = [ctypes.c_wchar_p]
    link.call(20, wstr, str(pythonw()))                                   # SetPath
    link.call(11, wstr, "-m tacocam")                                     # SetArguments
    link.call(9, wstr, str(PC))                                           # SetWorkingDirectory
    link.call(7, wstr, "Use your iPhone as the Taco Cam webcam in OBS")   # SetDescription
    link.call(17, [ctypes.c_wchar_p, ctypes.c_int], str(ICON), 0)         # SetIconLocation

    store = link.query(IID_IPropertyStore)
    pv = PROPVARIANT()
    pv.vt = VT_LPWSTR
    text = ctypes.create_unicode_buffer(APP_ID)
    pv.p = ctypes.cast(text, ctypes.c_void_p)
    store.call(6, [ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)],
               ctypes.byref(PKEY_AppUserModel_ID), ctypes.byref(pv))      # SetValue
    store.call(7, [])                                                      # Commit
    store.release()

    pf = link.query(IID_IPersistFile)
    pf.call(6, [ctypes.c_wchar_p, W.BOOL], str(path), True)               # Save
    pf.release()
    link.release()


def main():
    places = [known_folder(0x10), known_folder(0x02)]  # Desktop, Start menu Programs
    for folder in places:
        target = folder / NAME
        if "--remove" in sys.argv:
            if target.exists():
                target.unlink()
                print("removed", target)
            continue
        make(target)
        print("created", target)
    # Tell Explorer the icons changed.
    shell32.SHChangeNotify(0x08000000, 0, None, None)


if __name__ == "__main__":
    main()
