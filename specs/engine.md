# Brief: Engine station (Taco Cam PC engine)

You are one station of a nodeterm team building Taco Cam in `D:\ClaudeProjects\Webcam` (shared working
tree, no worktrees). Read `D:\ClaudeProjects\Webcam\CONTRACT.md` first: it is binding. You build the
Windows engine in `pc/tacocam/` (protocol, usbmux, link, decoder, pipeline, vcam, engine), the fake
phone, the virtual camera install, and their tests. At the same time the iPhone station writes the
Swift app and the App station writes the tkinter window that calls YOUR `Engine` API (CONTRACT
section 6) - keep that API exactly as written, so their code works with yours.

This PC: Windows 11, Python 3.14 (user-site pip installs; do not run python with `-I`), ffmpeg on
PATH, OBS Studio 32.2.2 installed, Apple Mobile Device Service running (usbmuxd on 127.0.0.1:27015),
numpy + opencv + Pillow already installed. `av==19.0.2` and `pyvirtualcam==0.15.0` have wheels for
this Python: `python -m pip install --user -r pc/requirements.txt`. No admin rights in your session.
The user's iPhone is probably not plugged in right now.

## What to build

1. `protocol.py`: framing encode/decode (CONTRACT section 2), message type constants, a buffered
   reader that survives partial reads, length checks.
2. `usbmux.py`: pure-Python usbmuxd client (plistlib): list USB devices, connect to device port,
   listen for attach/detach. Test it against a small fake usbmuxd server in the tests; also run it
   for real once against 127.0.0.1:27015 (`ListDevices` must answer, probably with an empty list).
3. `link.py`: connection manager thread: usb mode (first USB iPhone, connect 47777; refused =
   status "no_app", retry every 1 s) or wifi mode (host:47777); handshake, PING 1 s / 5 s timeout,
   reconnect forever, send SET/KEYFRAME/FOCUS_POINT, deliver STATE/VIDEO/LOG to the engine.
4. `decoder.py`: PyAV H.264/HEVC Annex-B decoder (codec context + parser), restarts on format
   change, waits for a keyframe after errors, drops frames rather than lagging (decode on its own
   thread, keep only the newest decoded frame). Try hardware decode only if it is simple and proven
   faster; software is fine.
5. `pipeline.py`: rotate (auto from `rotation_hint`), mirror, flip, fit/crop/stretch to the output
   size (cv2), and the inverse mapping for `tap_focus` (output x,y -> sensor x,y). "Waiting for iPhone"
   card picture (Pillow, drawn once per size; says how to fix: plug in USB, open Taco Cam on the
   phone; says "Taco Cam app is in the background - open it on the iPhone" for app_active false).
6. `vcam.py`: pyvirtualcam output at `pc.output` / `pc.fps_out` with frame pacing, backend
   `unitycapture` with device "Taco Cam", fallback `obs`; status "not_installed" when neither works;
   restart on size/fps change; repeat the last frame when the phone is slower.
7. `engine.py`: the `Engine` class exactly per CONTRACT section 6, thread-safe, stop() within 2 s,
   stats (fps in/out, Mbps, RTT, dropped).
8. `pc/tools/fake_phone.py`: a fake iPhone that speaks the contract on 127.0.0.1:47777: answers
   HELLO, keeps a full section-4/5 STATE (cameras incl. back min_zoom 0.5, lens_zooms [0.5,1,3]),
   applies SET (clamped) and echoes STATE, encodes a moving test picture with PyAV H.264/HEVC at the
   requested size/fps whose content visibly shows the zoom (wider view at 0.5x), torch, camera
   (front/back label), plus a frame counter and clock, honours KEYFRAME, PONG, rotation_hint
   switchable from its command line (`--rotation 90`). It is the stand-in for the real phone in every
   PC test and for the user's demo.
9. Virtual camera install: vendor the Unity Capture DirectShow filter (official repo
   github.com/schellingb/UnityCapture, `Install/` folder: UnityCaptureFilter32.dll + 64.dll and its
   install scripts; keep its license file) into `pc/vcam/`, record source URL + SHA-256 in
   `pc/vcam/SOURCE.md`. Check in its source how a custom device name is registered (its
   `InstallCustomName.bat` / regsvr32 `/i:` parameter) and how big a frame it accepts; write
   `pc/vcam/Install Taco Cam camera.bat` and `Uninstall Taco Cam camera.bat` that self-elevate (UAC)
   and register both DLLs as "Taco Cam" (one device). You cannot run them (no admin): when they are
   ready, append a line to `D:\ClaudeProjects\Webcam\specs\NOTES.md` "READY FOR USER: run
   pc/vcam/Install Taco Cam camera.bat" and carry on. After the user ran it (check with
   `ffmpeg -hide_banner -list_devices true -f dshow -i dummy`), prove frames flow: run the engine with
   the fake phone and read a few frames back from the "Taco Cam" DirectShow device with ffmpeg
   (`-f dshow -i video="Taco Cam" -frames:v 3`) and compare them to the engine's output. If the user
   has not run it before you finish, test the obs backend path as far as possible and say so.
   If Unity Capture turns out not to work with OBS 32 (check its known issues), say why in NOTES.md
   and fall back to the OBS backend cleanly.

## Tests

`pc/tests/test_engine*.py` (pytest; install pytest --user if missing): framing round trips and bad
lengths, usbmux against a fake usbmuxd, decoder on fake-phone streams (h264 + hevc, format change mid
stream), pipeline rotate/mirror/fit and the tap_focus inverse (property-style: map a point forward and
back), end-to-end Engine + fake phone (connect, SET -> STATE round trip for every phone setting,
frames arrive at the requested output size, reconnect after the fake phone restarts, stop() < 2 s).
Engine tests must not need the virtual camera (inject a null output), so they pass without admin.

## Rules

- No secrets. Don't touch other stations' paths; don't change CONTRACT.md. Problems with the
  contract: append to `specs/NOTES.md` (dated, signed "Engine station") and carry on.
- Do not run git (the iPhone station is the only one that commits).
- Write multi-line scripts with the Write tool, not bash heredocs. Prefer threads over asyncio
  (loopback asyncio stalls were seen on this PC).

## When you are done

Run exactly one of:

```
sh "%APPDATA%\node-terminal\canvas-control\nodeterm.sh" report-outcome --outcome succeeded --note "engine + fake phone done, N tests pass"
sh "%APPDATA%\node-terminal\canvas-control\nodeterm.sh" report-outcome --outcome failed --note "<one line: why>"
```

`succeeded` only if all your tests pass. End with a short summary: files, test count, virtual camera
status (installed and verified, or waiting for the user), anything the App station must know.
