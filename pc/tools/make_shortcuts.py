"""Creates "Taco Cam" shortcuts on the Desktop and in the Start menu, with the Taco Cam icon.

The shortcuts carry the window's AppUserModelID (TacoCam.PC), so a pinned shortcut and the running window
share one taskbar button. Run once from anywhere: python pc/tools/make_shortcuts.py  (--remove deletes them)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tacocam.shortcuts import CSIDL_DESKTOP, CSIDL_PROGRAMS, NAME, known_folder, make, shell32  # noqa: E402


def main():
    places = [known_folder(CSIDL_DESKTOP), known_folder(CSIDL_PROGRAMS)]
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
