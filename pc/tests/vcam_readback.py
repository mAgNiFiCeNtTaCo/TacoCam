"""Manual check (not a pytest test): engine + fake phone -> real virtual camera -> read frames back with ffmpeg.

    python pc/tests/vcam_readback.py                 # uses whatever open_camera picks (Taco Cam, else OBS)
    python pc/tests/vcam_readback.py --backend obs   # force the OBS Virtual Camera path

Prints the DirectShow device it read, and how close the frames are to the engine's own output (PSNR).
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from tacocam import vcam  # noqa: E402
from tacocam.engine import Engine  # noqa: E402
import fake_phone  # noqa: E402


def psnr(a, b):
    mse = np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2)
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=("auto", "unitycapture", "obs"), default="auto")
    ap.add_argument("--output", default="1280x720")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--skip", type=int, default=2, help="start-up frames to ignore (DirectShow sends black first)")
    args = ap.parse_args()
    backends = ("unitycapture", "obs") if args.backend == "auto" else (args.backend,)

    def factory(w, h, fps, name):
        return vcam.open_camera(w, h, fps, name, backends=backends)

    phone = fake_phone.FakePhone(port=0, rotation=0).start()
    logs = []
    eng = Engine({"pc": {"connect": "wifi", "wifi_host": f"127.0.0.1:{phone.port}", "output": args.output,
                         "fps_out": 30}, "phone": {"resolution": "1080p"}},
                 log=lambda s: (logs.append(s), print("ENGINE", s)), vcam_factory=factory)
    eng.start()
    ok = False
    try:
        end = time.monotonic() + 15
        while time.monotonic() < end:
            st = eng.get_status()
            if st["link"] == "connected" and st["vcam"] == "running" and st["fps_out"] > 10:
                break
            time.sleep(0.2)
        st = eng.get_status()
        print("status:", {k: st[k] for k in ("link", "vcam", "vcam_backend", "vcam_device", "fps_in", "fps_out",
                                              "out_size", "error")})
        if st["vcam"] != "running":
            print("RESULT: virtual camera not running:", st["error"])
            return 2
        device = st["vcam_device"]
        w, h = st["out_size"]
        out_dir = tempfile.mkdtemp(prefix="tacocam_readback_")
        pattern = os.path.join(out_dir, "frame%d.png")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "dshow", "-video_size", f"{w}x{h}",
               "-i", f"video={device}", "-frames:v", str(args.frames + args.skip), pattern]
        t0 = time.monotonic()
        ref_before = eng.get_preview(w, h)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ref_after = eng.get_preview(w, h)
        print("ffmpeg exit", r.returncode, r.stderr.strip()[-400:], f"({time.monotonic() - t0:.1f} s)")
        scores = []
        for i in range(args.skip + 1, args.skip + args.frames + 1):
            path = pattern % i
            if not os.path.exists(path):
                continue
            img = cv2.imread(path)[..., ::-1]
            if img.shape[:2] != (h, w):
                print(f"frame {i}: size {img.shape[1]}x{img.shape[0]} (expected {w}x{h})")
                img = cv2.resize(img, (w, h))
            # the picture moves (ball, clock): compare with the engine output around the capture time and
            # ignore the small moving parts by comparing blurred, downscaled pictures
            best = max(psnr(cv2.resize(img, (w // 8, h // 8), interpolation=cv2.INTER_AREA),
                            cv2.resize(ref, (w // 8, h // 8), interpolation=cv2.INTER_AREA))
                       for ref in (ref_before, ref_after))
            marker = img[25:60, 25:60].reshape(-1, 3).mean(axis=0)
            scores.append(best)
            print(f"frame {i}: PSNR vs engine output {best:.1f} dB, top-left marker RGB {marker.round()}")
        live_ok = len(scores) == args.frames and min(scores) > 20
        # Exact check: stop the phone; the engine then sends its static "waiting for iPhone" card, which
        # must come out of the camera (nearly) pixel for pixel.
        phone.stop()
        end = time.monotonic() + 10
        while time.monotonic() < end and eng.get_status()["link"] == "connected":
            time.sleep(0.1)
        time.sleep(1.0)
        card = eng.get_preview(w, h)
        card_pattern = os.path.join(out_dir, "card%d.png")
        cmd[-1] = card_pattern
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        card_scores = []
        for i in range(args.skip + 1, args.skip + args.frames + 1):
            path = card_pattern % i
            if os.path.exists(path):
                img = cv2.imread(path)[..., ::-1]
                if img.shape[:2] == (h, w):
                    card_scores.append(psnr(img, card))
        print("card frames PSNR vs engine output (full size):", [round(s, 1) for s in card_scores])
        card_ok = len(card_scores) == args.frames and min(card_scores) > 40
        ok = live_ok and card_ok
        print("frames saved in", out_dir)
        print("RESULT:", "OK - frames read from" if ok else "MISMATCH - frames read from", repr(device),
              f"via {st['vcam_backend']}")
    finally:
        eng.stop()
        phone.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
