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
- `pc/tools/fake_phone.py`: test iPhone on 127.0.0.1:47777. `pc/vcam/`: Unity Capture DLLs + admin install scripts.
- `dist/TacoCam.ipa` (gitignored), `settings.json` (gitignored, written by the window), `taco-cam.log`.

## Commands
- Run: `Taco Cam.bat` (or `Taco Cam (console).bat`). Tests: `python -m pytest pc/tests -q`.
- iPhone build: push `ios/` to `main` (public repo mAgNiFiCeNtTaCo/TacoCam, push allowed), `gh run watch <id>`,
  `gh run download <id> -n TacoCam-ipa -D dist`.
- Install on the phone: iloader (`Downloads\iloader`), Import IPA. Sideloadly login is broken (-80046).

## Rules
- Never read `%APPDATA%\obs-studio\basic\profiles\*\service.json` (Whatnot bearer token).
- Don't change OBS's stream output settings: they are Whatnot's required WHIP setup (x264 veryfast/zerolatency,
  CBR 3500, keyframe 2 s, Opus). Amazon IVS drops streams with B-frames or over 8.5 Mbps.
- The window saves `settings.json` on close: close it (WM_CLOSE) before editing the file, then reopen. Ask before
  restarting it (OBS may be live).
- Only one PC client at a time: connecting a probe to the phone kicks the window's connection.
- Keep the PC output at 1920x1080, rotate 0: the OBS scene rotates the source 90 degrees itself.
- The GitHub repo is PUBLIC (MIT): never commit settings.json, logs, the IPA, personal paths (use %APPDATA%)
  or names. Swift is only compiled on GitHub: read it carefully before each push.

## Gotchas
- The `gh` token needs the `workflow` scope to push `.github/workflows/*`.
- 4K output (2160x3840) is too slow in Python at 60 fps (~30 ms/frame); 1080p output is fine.
- iOS stops the camera in the background: the phone app must stay open on screen (Dim mode saves battery).
- Free Apple ID: the app stops opening after 7 days; reinstall with iloader. Developer Mode must be on.
- One full pytest run hit a MemoryError in Pillow's Tk image code (`test_app_real.py`); passes on rerun.
