# Webcam (Taco Cam): progress log

Taco Cam: our own iPhone-as-USB-webcam app (what Iriun Webcam does, every feature, plus a 0.5x ultra-wide
zoom-out). An iPhone app sends H.264/HEVC over the USB cable; a PC window shows it and feeds OBS through a
DirectShow camera called "Taco Cam". Used for the user's Whatnot box-break stream.

## Where it stands (2026-11-11)
- **In use**: iPhone 11 (iOS 27.0.1) over USB into OBS (Whatnot scene) and into the Whatnot card scanner.
- iPhone app: GitHub Actions build (last green run 40258964830), `dist/TacoCam.ipa` (gitignored) installed with
  **iloader**; reinstalled 2026-11-08, so 7 days runs to ~2026-11-15 (bottom bar shows the date, orange 2 days
  ahead). Sideloadly is broken (-80046).
- PC: starts with Windows (Startup shortcut, minimized); also Desktop / Start menu shortcuts. Tests
  `python -m pytest pc/tests -q` (303). Repo public (MIT): https://github.com/mAgNiFiCeNtTaCo/TacoCam.
- Settings for Whatnot: back camera **1080p** (the user was asked to switch back from 4K), 30 fps, H.264,
  20 Mbps; PC output 1920x1080 @ 30, rotate 0 (OBS turns the source 90 degrees). Presets 1 Wide Table (0.5x)
  and 2 Close UP (1.6x, focus + colors held; exposure lock suggested), Ctrl+Alt+1/2; Ctrl+Alt+0 saves a clip
  to Videos\Taco Cam clips.
- Scanner feed (shared memory "TacoCamFeed2", CONTRACT section 8) feeds the Whatnot scanner, whose camera is set
  to "Taco Cam (direct, full quality)".
- OBS's stream output is Whatnot's required WHIP setup: leave it alone.
- Not possible on this phone's back camera: anti-flicker, exact focus/ISO/shutter/white balance ("manual" = hold).
- 2026-10-26: smooth zoom (Zoom speed, default 0.5 s), Pre-show check button + check when OBS goes live (beep
  if the picture stops while live), red status line naming why the phone camera paused. iPhone build 40406780074
  in `dist/TacoCam.ipa`.
- 2026-11-08: Preview turn (Output tab) stands the picture upright in the window only; set to 90, window restarted
  on the new code. OBS still gets 1920x1080 rotate 0.
- Open: confirm the turned preview by eye; test glide / pause reasons on the real phone; front camera /
  upright check (`docs/QA.md`); scanner card finding on a busy background (54 failed frames in Whatnot
  `data/debug` to tune against) if Test mode shows it's still unreliable.

## Log
### 2026-11-11: USB only by default, Wi-Fi with a pairing code (security fix)
- Done by a Security_Agent_Audit session (1b98f3aa, fix round for the 2026-10-28 audit), on the user's "do it";
  logged here by the Webcam session. Commit a13b7a6, pushed; iPhone build GitHub run 43106745840 green (Swift
  compiled, unit tests pass). Findings: WEBCAM-20261028-02 and -05 fixed, -01 (high) and -04 partly fixed (until seen
  on the phone), -03 open (GitHub Support request for the old commits, the user's to send).
- Phone (`StreamServer.swift`, `Protocol.swift`, `AppModel.swift`, `SettingsView.swift`): a connection from the phone's
  own loopback address (the USB cable) is let in as before; anything else is refused unless Settings > Wi-Fi > "Allow
  Wi-Fi connections" is on, and then has to prove a 16-character code shown on the phone (HMAC-SHA256 challenge both
  ways, 5 wrong codes = 60 s wait). A connected PC is no longer pushed out by a new connection. Bonjour advertisement
  removed (Info.plist). CONTRACT sections 1 and 2.
- PC: Phone tab "Pairing code" box (`pc.wifi_code`); no Wi-Fi connection without a code, and the device must prove the
  code back (`link.py`, `protocol.py`). fake_phone takes `code=` (None = USB-like) and refuses a second PC.
- Camera install / uninstall scripts copy the two Unity Capture DLLs to Program Files, check their SHA-256 and register
  them from there. `ios.yml` pins its actions to commit ids and XcodeGen to a checked download.
- `/slop-check Webcam diff` (by that session): 0 scanner hits, four stale doc lines fixed.
- New `dist/TacoCam.ipa`; the last build before this change is kept as `dist/TacoCam-old-before-2026-11-11.ipa`
  (reinstall it if USB fails with the new one).
- Checked by this session: PC tests 317 pass (2026-11-11).
- Resources 2026-11-11 16:21 (OBS open, window on the 2026-11-08 code): Webcam 2 processes, CPU 184% of a core (5.7% of
  the PC), RAM 324 MB, GPU 0%; whole PC CPU 22% of 32 threads, RAM 29.1 of 64 GB, GPU 33%.
- Open (the user's): install the new IPA and run docs/QA.md "Who may connect" once, not right before a show (the
  Swift was never run on a phone); restart the Taco Cam window (still running the code from 2026-11-08); run the new
  "Install Taco Cam camera.bat" as admin with OBS closed; GitHub Support request for the old commits.

### 2026-11-10: Whatnot page showed the camera, not the OBS stream
- During a Testing show the Whatnot dashboard player showed the plain sideways Taco Cam picture, center-cropped,
  with no overlays. OBS was fine (program scene "Live" upright, sending 1080x1920 @ 60, 0 skipped frames; read
  only over the websocket while live). `tasklist /m UnityCaptureFilter64.dll` listed opera.exe: the Whatnot tab
  was using the Taco Cam camera directly.
- Fix (user, confirmed working): block Camera for whatnot.com in Opera and reload. No code change.
- Checked first: Taco Cam's window (Preview turn 90) and OBS's program scene showed the same upright picture
  (window captured with PrintWindow, OBS with GetSourceScreenshot), so the turn added 2026-11-08 is right.
- User then asked for the border and side sprites to show on viewers' phones, with a placement slider. That is
  Whatnot_Borders' work (its `phoneview` setting from 2026-11-10 already moves the sprites 110 px in; the frame
  lines stay at the edge and the margin is fixed). User: "we will handle this in correct project folder".
  Nothing changed there from this session.
- Resources 2026-11-10 01:20 (OBS live, Whatnot Testing show): Webcam 2 processes, CPU 208% of a core (6.5% of
  the PC), RAM 285 MB, GPU 0%; whole PC CPU 31% of 32 threads, RAM 26.2 of 64 GB, GPU 61%.

### 2026-11-08: Preview turn (window only)
- **Asked for**: the picture upright in the Taco Cam window without changing what OBS gets.
- **New setting `pc.preview_turn`** (0 | 90 | 180 | 270 clockwise, default 0; Output (OBS) tab "Preview turn"). The turn
  happens only in `App.draw_preview` (`turn_image`), so the 1920x1080 rotate-0 output, clips and the scanner feed are
  untouched. Value for this setup is 90: the saved OBS scenes (Whatnot_2, Whatnot_New; scene "Live") hold the Taco Cam
  source at rot 90.0.
- Click-to-focus on a turned picture is mapped back to the output (`preview_to_output`, `_img_turn`). The "waiting" card
  isn't turned, so its text stays readable (`Engine.preview_is_card`).
- Decided against: an "auto" turn from the phone's orientation hint. OBS's turn is a fixed 90, and the hint would be
  wrong for an overhead or flat phone mount.
- Tests: 303 pass (8 new: turn direction, click mapping at each turn, window-only update, card flag on the engine, plus the
  control round trip). `/slop-check Webcam diff`: 1 phrase fixed in the README row ("as before"), 3 CODE-001 false alarms
  on older code (`AI_SlopAgent/reports/2026-11-08-Webcam.md`).
- Window restarted on the new code at 19:39 on 2026-11-08 (not by this session) and `settings.json` holds
  `preview_turn` 90, rotate 0, output 1920x1080. Not yet confirmed by eye with the real phone picture.
- iPhone: the user reinstalled the expired app on 2026-11-08 and got iOS's "Untrusted Developer" alert; the fix is
  Settings > General > VPN & Device Management > Trust. Not checked which build went on the phone.
- Resources 2026-11-08 21:15 (OBS closed): Webcam 2 processes, CPU 181% of a core (5.7% of the PC), RAM 243 MB, GPU 0%,
  disk 4 MB; whole PC CPU 22% of 32 threads, RAM 38.8 of 64 GB.
- Open: confirm the turned preview looks right and click-to-focus lands where clicked; glide and pause reasons on the real
  phone if the new IPA is the one installed.

### 2026-10-26: Smooth zoom, pre-show check, phone pause reasons
- **Smooth zoom** (iPhone + PC): new phone setting `zoom_glide_s` (0..3 s, PC default 0.5, Camera tab "Zoom speed":
  Instant / Smooth / Slow / Very slow). The phone ramps with `ramp(toVideoZoomFactor:withRate:)`, rate =
  log2(to/from) / seconds; a camera switch or a stopped camera jumps. Holds of a preset (focus once / freeze
  brightness / colors on the combined back camera) wait until the glide ends (started halfway they would lock on
  the lens being left); AppModel applies once more glide + 0.15 s later. Applies to every zoom change (presets,
  zoom buttons, wheel, slider), not only presets.
- **Pause reasons**: STATE `interrupted` ("background" | "other_app" | "split_screen" | "too_hot" | "other") from
  AVCaptureSession interruption notifications; the phone clears it itself on its 2 s heartbeat when the session
  runs again (iOS doesn't always post "interruption ended"). PC: red "Phone: ..." line in the status bar; phone
  screen shows it too. The PC counts a pause only while no picture arrives (fps_in < 1), so a stale flag can't
  raise alarms.
- **Pre-show check** (`pc/tacocam/precheck.py`, pure; window in `app.py`): button under the picture; lists USB,
  picture coming in, 1080p, charging, heat, iPhone app days left, Taco Cam camera, OBS output 1920x1080 turn 0,
  scanner reading, Dim tip, Do Not Disturb reminder; refreshes every second while open. Runs by itself when OBS
  starts streaming (`pc.check_on_live`, Extras tab, default on): all good = a note, problems = window + beep.
  While live it beeps once when the picture is gone for 3 s (LOST_ALERT_S).
- `obsfollow.py` also polls `GetStreamStatus` (read-only); the watcher now runs for Follow OBS **or** the live
  check, and presets follow scenes only with Follow OBS on (changed `test_window_follows_obs_scene`). Checked
  against the real OBS: websocket on, outputActive False, scene "Scene".
- Tests: 295 pass (11 new in `test_showready.py`, zoom_glide_s round trip in test_engine_e2e). conftest swaps
  `app.ObsFollower` for `QuietObs` so test windows never talk to the real OBS. Fake phone: `zoom_glide_s`,
  `interrupted` + `set_interrupted()`, console `pause [reason]` / `resume`.
- iPhone build: GitHub run 40406780074 green; new `dist/TacoCam.ipa` downloaded (old one kept as
  `dist/TacoCam-previous.ipa`). Not yet installed on the phone; the PC window still runs the old code until it
  is restarted (not restarted: OBS might be live).
- Decided against: an "interrupted" card on the OBS output (viewers would see it; the normal waiting card shows
  after 3 s as before); a separate zoom speed for the phone-screen pinch.
- Same session, outside the project: a `fixterm` command (`%USERPROFILE%\.local\bin\fixterm.cmd`) + user skill
  `/fix-terminal` for terminals that type mouse codes after a crashed TUI (shared lesson in the brain).
- Open: install the new IPA with iloader (also renews the 7 days; the current copy expires ~2026-11-01), restart
  the window, then check on the real phone that the glide looks smooth and that FaceTime shows "Another app ...".

### 2026-10-25 (late): clips, start with Windows, battery warning, scanner feed
- **Save-the-hit clips** (`clips.py`): ring buffer of the phone's own H.264/HEVC packets (65 s, 400 MB cap), MP4
  without re-encoding, upright via the tkhd display matrix (bytes taken from ffmpeg's `-display_rotation`);
  Ctrl+Alt+0 / Save button; Extras tab (15/30/60 s, turn). Live test: 30 s, 908 frames, upright. HEVC clips use
  the "hev1" tag: PyAV 19 writes undecodable "hvc1" files from these packets (ffmpeg's own remux works).
- **Start with Windows**: `shortcuts.py` (COM code moved from `tools/make_shortcuts.py`) makes a Startup shortcut
  with `--minimized`; turned on for the user. **Battery warning**: orange <30% / red <15% when not charging,
  "charger unplugged" message.
- **Scanner feed** (`framefeed.py`, CONTRACT section 8): v1 (one slot, RGB) gave the scanner ~20 pictures/s,
  reading in place dropped to 5/s (reads collided with writes). v2: two slots, Taco Cam stores BGR already upright,
  readers only copy: 25 pictures/s at 4K. Tests use their own feed name (TACOCAM_FEED_NAME) so they never touch
  the running Taco Cam's feed.
- **4K was a mistake for the scanner**: its card finder works in pixels tuned at 1080p (DETECT_MAX effectively
  off) and cards are read at 420x612: on tonight's failed frames it found 0/12 at 4K vs 4/12 at 1080p, 2.5x
  slower. The scanner now shrinks to 1080p; the phone should stay at 1080p. Remaining misses: a very sparkly
  card in front of a busy background (cases, top-loaders, packs) and the easel ledge hiding the bottom edge.
- A bash heredoc wrote real NUL bytes into `clips.py` (rb"\x00..." became binary): fixed with a Write-tool script;
  all later patches were script files (the shared CLAUDE.md rule).
- Whatnot project (with the user's OK): "Taco Cam (direct, full quality)" camera, Card Scanner desktop shortcut
  + icon; see its PROGRESS.md.

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
