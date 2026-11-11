# Webcam (Taco Cam)

Our own iPhone-as-webcam app (like Iriun, plus a 0.5x ultra-wide zoom-out), used over the USB cable to feed
OBS for the user's Whatnot box-break stream (portrait 1080x1920 canvas). The user isn't a programmer:
explain in plain words and finish jobs end to end.

## Read first
- `PROGRESS.md` (log + where it stands), `WORKFLOW.md` (who built what). `WORKFLOW.html` is the picture of how
  the project was built, drawn from `workflow.json` by `_brain/workflow.py` on each /save-progress: edit the
  JSON, never the HTML.
- `CONTRACT.md`: the binding phone <-> PC protocol and Engine API. `specs/NOTES.md`: team notes.
- `docs/QA.md` (checks + first-run checklist), `docs/INSTALL_IPHONE.md`, `README.md` (the window explained).

## Layout
- `ios/`: Swift app (XcodeGen `project.yml`), built only on GitHub Actions (`.github/workflows/ios.yml`).
- `pc/tacocam/`: engine (protocol, usbmux, link, decoder, pipeline, vcam, engine) + window (app, settings, ui_widgets).
- `pc/tacocam/assets/taco-cam.ico`: window/taskbar icon, drawn by `pc/tools/make_icon.py`. `__main__.py` sets the
  AppUserModelID `TacoCam.PC` (else Windows groups it with other pythonw apps) and uses only `iconbitmap`
  (adding `iconphoto` too gives a blank icon).
- `pc/tacocam/clips.py` (save-the-hit MP4s), `framefeed.py` (scanner feed, shared memory TacoCamFeed2),
  `shortcuts.py` (Desktop/Start menu/Startup .lnk with the AppUserModelID).
- `pc/tacocam/presets.py` (camera presets), `hotkeys.py` (global Ctrl+Alt+1..9), `obsfollow.py` + `obsws.py`
  (read-only: which OBS scene is live and whether OBS streams; obsws copied from the Whatnot project).
- `pc/tacocam/precheck.py`: the pre-show check (pure function over get_status + settings); `app.py` shows it in
  a window from its button or when OBS starts streaming (`pc.check_on_live`) and beeps if the picture stops live.
- `pc/tools/fake_phone.py`: test iPhone on 127.0.0.1:47777 (`code=` for a phone with Wi-Fi pairing on). `pc/vcam/`:
  Unity Capture DLLs + admin install scripts (copy to Program Files, SHA-256 check, register from there).
- `dist/TacoCam.ipa` (gitignored; `TacoCam-old-before-2026-11-11.ipa` = last build before pairing), `settings.json` (gitignored, written by the window), `taco-cam.log`.

## Commands
- Run: `Taco Cam.bat` (or `Taco Cam (console).bat`), or the Desktop/Start menu shortcuts made by
  `python pc/tools/make_shortcuts.py` (carry AppUserModelID TacoCam.PC). Tests: `python -m pytest pc/tests -q`.
- iPhone build: push `ios/` to `main` (public repo mAgNiFiCeNtTaCo/TacoCam, push allowed), `gh run watch <id>`,
  `gh run download <id> -n TacoCam-ipa -D dist`.
- Install on the phone: iloader (`Downloads\iloader`), Import IPA. Sideloadly login is broken (-80046).

## Rules
- Never read `%APPDATA%\obs-studio\basic\profiles\*\service.json` (Whatnot bearer token).
- Don't change OBS's stream output settings: they are Whatnot's required WHIP setup (x264 veryfast/zerolatency,
  CBR 3500, keyframe 2 s, Opus). Amazon IVS drops streams with B-frames or over 8.5 Mbps.
- The window saves `settings.json` on close: close it (WM_CLOSE) before editing the file, then reopen. Ask before
  restarting it (OBS may be live).
- Only one PC client at a time: since 2026-11-11 a connected PC is not pushed out, so a probe is refused while the
  window is connected (and a probe must never be left connected). Wi-Fi needs "Allow Wi-Fi connections" on the
  phone plus the pairing code (`pc.wifi_code`); USB (loopback on the phone) needs none. CONTRACT sections 1-2.
- Keep the PC output at 1920x1080, rotate 0: the OBS scene rotates the source 90 degrees itself. To stand the picture
  up in the window, use `pc.preview_turn` (90 here): it turns the window's picture only.
- The GitHub repo is PUBLIC (MIT): never commit settings.json, logs, the IPA, personal paths (use %APPDATA%)
  or names. Swift is only compiled on GitHub: read it carefully before each push.

## Gotchas
- The Whatnot scanner is tuned for 1080p: keep the phone at 1080p (it shrinks 4K, which found no cards).
- Tests must never use the real feed name: conftest sets TACOCAM_FEED_NAME per test run. Windows made by tests
  must never talk to the real OBS: conftest swaps app.ObsFollower for QuietObs.
- The iPhone back camera is a virtual device (Dual Wide / Triple): no lens position, custom ISO/shutter,
  custom white-balance gains or anti-flicker. "manual" there means hold (CONTRACT section 5 caps flags).
- The `gh` token needs the `workflow` scope to push `.github/workflows/*`.
- 4K output (2160x3840) is too slow in Python at 60 fps (~30 ms/frame); 1080p output is fine.
- iOS stops the camera in the background: the phone app must stay open on screen (Dim mode saves battery).
- Free Apple ID: the app stops opening after 7 days; reinstall with iloader. Developer Mode must be on. "Untrusted
  Developer" after a reinstall: Settings > General > VPN & Device Management > Trust.
- Whatnot's web page showed a sideways, zoomed picture with no overlays while OBS was fine: the page was
  using the Taco Cam camera itself in the browser (Opera had the Unity Capture filter loaded; camera icon in
  the address bar). Fix: block Camera for whatnot.com in the browser and reload; the page then shows OBS's
  stream. Never "fix" it by turning Taco Cam's output, which would make OBS sideways.
- One full pytest run hit a MemoryError in Pillow's Tk image code (`test_app_real.py`); passes on rerun.
