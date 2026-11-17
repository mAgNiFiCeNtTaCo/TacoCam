"""End-to-end check of the Android app: the real PC engine connects to the real app on an Android phone or
emulator through adb, the way it does for a friend (install, open, read the pairing code, connect, video).

    python pc/tools/android_e2e.py [--apk path] [--seconds 150] [--save frame.png]

Used by .github/workflows/android.yml on an emulator; also works with a real phone plugged into this PC (it
installs / updates the app on it). Exit code 0 = pictures decoded and settings round-trip; 1 = not.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tacocam import adb as adbmod  # noqa: E402
from tacocam import vcam  # noqa: E402
from tacocam.engine import Engine  # noqa: E402


def wait(fn, seconds, step=0.25):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", help="app to install (default: the one adb.find_apk finds)")
    ap.add_argument("--seconds", type=float, default=150)
    ap.add_argument("--save", help="save one output picture as PNG")
    args = ap.parse_args(argv)
    if args.apk:
        version = adbmod.apk_version(args.apk)
        adbmod.find_apk = lambda: (args.apk, version)
    print("adb:", adbmod.find_adb(), "app:", adbmod.find_apk(), flush=True)

    cams = []

    def factory(w, h, fps, name):
        cams.append(vcam.NullCamera(w, h, fps, name))
        return cams[-1]

    eng = Engine({"pc": {"connect": "android", "output": "1280x720", "fps_out": 30, "rotate": "auto"},
                  "phone": {"resolution": "720p", "fps": 30, "codec": "h264", "bitrate_mbps": 4}},
                 log=lambda s: print(time.strftime("%H:%M:%S"), s, flush=True), vcam_factory=factory)
    eng.start()
    ok = False
    try:
        got = wait(lambda: eng.get_status()["link"] == "connected" and eng._decoder.decoded > 10, args.seconds)
        st = eng.get_status()
        print("status:", {k: st.get(k) for k in ("link", "transport", "device_name", "fps_in", "error")}, flush=True)
        if not got:
            print("FAIL: no pictures from the app", flush=True)
            return 1
        phone = st["phone"] or {}
        print("stream:", phone.get("stream"), "rotation_hint:", phone.get("rotation_hint"),
              "cameras:", sorted((phone.get("cameras") or {}).keys()), flush=True)
        back = (phone.get("cameras") or {}).get("back") or {}
        target = 2.0 if (back.get("max_zoom") or 1) >= 2 else 1.0
        eng.update_settings({"phone": {"zoom": target}})
        zoomed = wait(lambda: abs(((eng.get_status()["phone"] or {}).get("settings") or {}).get("zoom", 0) - target)
                      < 0.01, 15)
        print("zoom round trip:", "ok" if zoomed else "FAILED", flush=True)
        before = eng._decoder.decoded
        more = wait(lambda: eng._decoder.decoded > before + 30, 30)
        print("pictures still coming:", "ok" if more else "FAILED", eng._decoder.decoded, flush=True)
        if args.save and eng.get_preview(1280, 720) is not None:
            from PIL import Image
            Image.fromarray(eng.get_preview(1280, 720)).save(args.save)
            print("saved", args.save, flush=True)
        ok = bool(zoomed and more and st["transport"] == "android")
    finally:
        eng.stop()
    print("PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
