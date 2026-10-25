# Brief: App station (Taco Cam PC window)

You are one station of a nodeterm team building Taco Cam in `D:\ClaudeProjects\Webcam` (shared working
tree, no worktrees). Read `D:\ClaudeProjects\Webcam\CONTRACT.md` first: it is binding. You build the
Windows control window the user actually sees. The Engine station is writing `pc/tacocam/engine.py`
and `pc/tools/fake_phone.py` at the same time; you program against the `Engine` API exactly as written
in CONTRACT section 6. Until their files exist, work against a small stub of that API that you keep in
your test folder (`pc/tests/stub_engine.py`), never in their files; once `pc/tacocam/engine.py` and
`pc/tools/fake_phone.py` exist and work, switch to the real thing and test end to end.

The user is not a programmer, streams Yu-Gi-Oh box breaks on Whatnot from OBS with a PORTRAIT
1080x1920 canvas, and wants every Iriun Webcam (Pro) feature plus a 0.5x zoom-out. Python 3.14,
tkinter + Pillow + numpy installed (user-site; don't run python with `-I`). No PySide/PyQt: tkinter
(ttk, a clean dark theme) keeps it dependency-light.

## What to build

`pc/tacocam/app.py` (+ `settings.py`, optional `ui_*.py` helpers), started by `python -m tacocam`
from `pc/` (`pc/tacocam/__main__.py`) and by `Taco Cam.bat` in the project root (pythonw, no console
window, log to `taco-cam.log`; a `Taco Cam (console).bat` for troubleshooting).

1. **Window**: live preview of the OUTPUT frame (what OBS gets) via `eng.get_preview`, ~20 fps with
   `after()`, aspect kept; click on the preview = tap-to-focus (`eng.tap_focus`), with a short focus
   square drawn where clicked. Status bar: connection (Searching for iPhone on USB / iPhone found:
   open Taco Cam on the phone / Connected to <device> by USB), phone battery + charging, thermal
   warning, fps in/out, Mbps, RTT, dropped, virtual camera state ("Taco Cam" ready in OBS / not
   installed: button "Install virtual camera" that runs `pc/vcam/Install Taco Cam camera.bat`).
2. **Zoom**: big quick buttons from STATE `lens_zooms` (0.5x 1x 3x ...; 0.5x clearly there) + a
   zoom slider from min_zoom to max_zoom with a value label; mouse wheel on the preview zooms.
3. **Camera**: back/front, resolution 720p/1080p/4K, fps (only the ones STATE allows), codec
   H.264/HEVC, bitrate slider (Mbps).
4. **Image**: focus auto/manual + slider; exposure auto + EV slider, or manual ISO + shutter
   (ranges from STATE); white balance auto/manual + temperature + tint; torch slider (only when
   has_torch); stabilization; HDR (when supported); "Reset image settings".
5. **Output** (for OBS): orientation auto/0/90/180/270, mirror, flip, output size with friendly names
   ("Portrait 1080x1920 (your Whatnot canvas)", "Landscape 1920x1080", 720p, 4K landscape/portrait),
   fit (Crop to fill / Fit with bars / Stretch), output fps, when-disconnected (card/last frame/black).
6. **Phone**: dim phone screen toggle, connection mode USB (default) / Wi-Fi with an IP box (bonus;
   "127.0.0.1" + a "Start test phone" button that launches `pc/tools/fake_phone.py` so the user can try
   the app without the iPhone).
7. Every control sends `eng.update_settings` and then shows the value the phone actually reports in
   STATE (clamped values win). Controls the current camera doesn't support are disabled with a short
   reason. Settings persist to `settings.json` (CONTRACT section 6) on change (debounced) and load at
   start; a corrupt file falls back to defaults and is kept as `settings.bad.json`.
8. Plain tooltips or one-line hints on the less obvious controls. Keep the window usable at 1280x800.
   Closing the window stops the engine cleanly (virtual camera released).
9. Only one copy runs at a time (a lock file / named mutex; a second start brings a message).

## Docs

`README.md` in the project root, plain English for a non-programmer: what Taco Cam is, one-time setup
(Python packages: `pip install --user -r pc/requirements.txt`; virtual camera install script; the
iPhone app: see `docs/INSTALL_IPHONE.md`, written by the iPhone station), daily use (plug in, open the
app on the phone, double-click `Taco Cam.bat`), adding "Taco Cam" in OBS (Sources > + > Video Capture
Device > Taco Cam; Resolution/FPS Type Custom at the output size; for the portrait canvas pick Portrait
1080x1920), every control explained, troubleshooting (iPhone found but no picture = open the app;
Trust This Computer prompt; app expired after 7 days = re-sign in Sideloadly).

## Tests

`pc/tests/test_app*.py` (pytest): settings load/save/defaults/corrupt file, the control <-> settings
mapping (every control writes the right key, STATE updates the control), building the window hidden
(`withdraw()`) against the stub and against the real engine + fake phone, reading the widgets (screen
grabs here catch the terminal window on top, so don't rely on screenshots of Tk). Once the real engine
exists: an end-to-end run app + fake phone that changes zoom to 0.5 and sees it come back in STATE and
in the preview picture.

## Rules

- No secrets. Don't touch other stations' paths (CONTRACT table) and don't change CONTRACT.md. If the
  Engine API is missing something you need, append the request to `specs/NOTES.md` (dated, signed "App
  station") and work around it in your code meanwhile.
- Do not run git. Write multi-line scripts with the Write tool, not bash heredocs.

## When you are done

Run exactly one of:

```
sh "%APPDATA%\node-terminal\canvas-control\nodeterm.sh" report-outcome --outcome succeeded --note "PC app done, works with real engine + fake phone, N tests pass"
sh "%APPDATA%\node-terminal\canvas-control\nodeterm.sh" report-outcome --outcome failed --note "<one line: why>"
```

`succeeded` only if your tests pass against the REAL engine and fake phone (if the engine is still
not there when everything else is done, wait for it: check every few minutes for up to 60 minutes).
End with a short summary: files, tests, anything not verified.
