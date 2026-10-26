# Webcam (Taco Cam): progress log

Taco Cam: our own iPhone-as-USB-webcam app (what Iriun Webcam does, every feature, plus a 0.5x ultra-wide
zoom-out). An iPhone app sends H.264/HEVC over the USB cable; a PC window shows it and feeds OBS through a
DirectShow camera called "Taco Cam". Used for the user's Whatnot box-break stream.

## Where it stands (2026-10-25, evening)
- **Working end to end with the real phone** (iPhone 11, iOS 27.0.1) over USB into OBS (Whatnot scene).
- iPhone app: GitHub Actions build (last green run 40258964830, 14 iOS tests), `dist/TacoCam.ipa` (gitignored)
  installed with **iloader** (Sideloadly login broken since 2026-10-21, -80046). Free Apple ID: reinstall every
  7 days; the PC window's bottom bar shows the expiry date (orange 2 days ahead).
- PC: `Taco Cam.bat` or the Desktop / Start menu **Taco Cam** shortcuts (`pc/tools/make_shortcuts.py`); own
  icon and taskbar entry. Tests `python -m pytest pc/tests -q` (262).
- GitHub repo is **public** (MIT): https://github.com/mAgNiFiCeNtTaCo/TacoCam.
- Settings in use for Whatnot: back camera, 1080p, 30 fps, H.264, 20 Mbps, stabilization off; PC output
  1920x1080 @ 30, rotate 0 (the OBS scene turns the source 90 degrees). Presets **1 Wide Table** (0.5x,
  colors held) and **2 Close UP** (1.6x, focus + colors held), Ctrl+Alt+1 / Ctrl+Alt+2; Follow OBS off.
- OBS's stream output (WHIP to Whatnot/Amazon IVS, x264 veryfast/zerolatency, 3500 kbps CBR, keyframe 2 s,
  Opus 160) is Whatnot's required setup: leave it alone.
- Not possible on this phone's back camera: anti-flicker and exact focus/ISO/shutter/white-balance values
  (Apple refuses them on the combined Dual Wide camera); "manual" there means hold.
- Not yet checked on the phone: front camera, picture upright with the phone held upright (`docs/QA.md`).

## Log
### 2026-10-25 (evening): Public repo, own icon, presets, expiry warning, back-camera holds
- Repo made **public** with an MIT license; history rewritten first to replace the Windows user path in
  `specs/*.md` with `%APPDATA%` (old build run deleted; old commit 99059ad may stay reachable by SHA).
- Window icon: Windows grouped the Tk window with other pythonw apps (BabyG panel's gabsugc icon). Fixed with
  AppUserModelID `TacoCam.PC` + `pc/tacocam/assets/taco-cam.ico` (drawn by `pc/tools/make_icon.py`). Using
  `iconbitmap` and `iconphoto` together gave a blank icon (tested), so only `iconbitmap`.
- `pc/tools/make_shortcuts.py`: Desktop + Start menu shortcuts carrying the same AppUserModelID (plain COM via
  ctypes, no pywin32), so a pinned shortcut and the window share one taskbar button.
- Presets (`pc/tacocam/presets.py`, Presets tab, buttons under the preview): picture settings only (zoom,
  focus, exposure, colors, light, anti-flicker), lock boxes use the phone's new STATE `live` values, global
  Ctrl+Alt+1..9 (`hotkeys.py`, RegisterHotKey thread), optional Follow OBS (`obsfollow.py` polls
  GetCurrentProgramScene once a second via `obsws.py`, copied from Whatnot; read-only; tested against the real
  OBS: scene "Scene").
- iPhone: STATE `app_expires` (from embedded.mobileprovision) + phone-screen warning; STATE `live`;
  `anti_flicker` (fixed flicker-safe shutter, ISO steered from the meter). CONTRACT.md updated.
- Found on the real phone: the back camera (Dual Wide virtual device) refuses a lens position, custom exposure
  and custom white-balance gains, so locks and anti-flicker were refused. Fix: "manual" falls back to holding
  (one-shot autofocus on the middle, then locked; exposure / white balance locked); caps flags `focus_lock`,
  `exposure_manual`, `wb_manual`, `anti_flicker`; the PC greys out what can't work. Verified: no refusals, close-up
  frame sharp in the middle. Anti-flicker on this back camera would need single-lens mode (lens-switch pause):
  not built, only if the user sees flicker.
- Fixed the focus distance tip (lens position 0 = closest). 262 tests. `docs/INSTALL_IPHONE.md` now iloader.
- Open: front camera + upright check; anti-flicker via single-lens mode only if flicker shows up.

### 2026-10-25: Team build, first iPhone build, first real-phone run
- Nodeterm team (orchestrator + iPhone, PC engine, PC app stations; details in `WORKFLOW.md`) wrote
  `CONTRACT.md`, the iPhone app (`ios/`), the engine + fake phone + virtual camera (`pc/tacocam`,
  `pc/tools/fake_phone.py`, `pc/vcam/`) and the window (`app.py`, `README.md`). The user ran the vcam
  install script; the engine station proved the "Taco Cam" camera bit-exact with ffmpeg.
- The iPhone station stopped at the push: GitHub refused `.github/workflows/ios.yml` because the gh login
  lacked the `workflow` scope. Fixed by the user with `gh auth refresh -h github.com -s workflow`.
- Checker work (the Checker station never started; done in session 24137721): line-by-line Swift vs
  contract/PC check, all matched (`docs/QA.md`). Four iOS fixes before the first build: `inputPriority`
  session preset so the chosen format sticks; AVCaptureSession notification names as raw strings (Swift
  spellings differ between SDKs); iOS 16 front-camera rotation uses the same table as the back camera;
  screen stays awake whenever the app is open.
- First GitHub build green in under a minute; IPA downloaded. Sideloadly failed with -80046 (Apple-side
  change, affects all Sideloadly users since 2026-10-21); iloader v2.4.0 (official GitHub release, SHA-256
  checked, saved in `Downloads\iloader`) worked. A free Apple ID that isn't signed in on the phone is fine;
  Developer Mode must be on.
- Real phone: HELLO/STATE correct (iPhone 11, Back Dual Wide Camera, zoom 0.5-5, lenses [0.5, 1]).
- 4K lag explained (measured on this PC): 4K portrait **output** costs ~30 ms/frame (rotation 23 ms), too slow
  for 60 fps; 1080x1920 output is ~6 ms (13 ms from a 4K phone picture). No 2K: iPhone cameras only offer
  720p/1080p/4K at 16:9, and 2K gains nothing on a 1080x1920 canvas. Decided not to add it.
- Frame-rate "reverting to 60" was the user's own clicks; the phone obeys SET fps immediately (tested). Added
  `pc/tests/test_app_phone_memory.py`: saved PC settings beat the phone's remembered values on connect.
- Decided against changing OBS (NVENC, 6000 kbps): Whatnot's Show Tools applies required settings, and
  Amazon IVS disconnects streams with B-frames (NVENC default). Upload measured ~71 Mbps.
- One full test run had a MemoryError in Pillow's Tk image code (`test_app_real.py`); the file passed 3 runs
  alone. Watch for it.
- GitHub repo made **public** at the user's request (MIT license). Before that, history was rewritten to replace
  the Windows user path in `specs/*.md` with `%APPDATA%` (backup bundle kept in the session scratchpad only),
  force-pushed, and the old build run deleted. Mac build minutes are free for public repos.
- Open: check upright picture with the phone held upright, front camera and the rest of `docs/QA.md`;
  reinstall with iloader every 7 days; update `docs/INSTALL_IPHONE.md` to iloader (still says Sideloadly).
