# Webcam (Taco Cam): progress log

Taco Cam: our own iPhone-as-USB-webcam app (what Iriun Webcam does, every feature, plus a 0.5x ultra-wide
zoom-out). An iPhone app sends H.264/HEVC over the USB cable; a PC window shows it and feeds OBS through a
DirectShow camera called "Taco Cam". Used for the user's Whatnot box-break stream.

## Where it stands (2026-10-25, late)
- **In use**: iPhone 11 (iOS 27.0.1) over USB into OBS (Whatnot scene) and into the Whatnot card scanner.
- iPhone app: GitHub Actions build (last green run 40258964830), `dist/TacoCam.ipa` (gitignored) installed with
  **iloader**; expires ~2026-11-01 (bottom bar shows the date, orange 2 days ahead). Sideloadly is broken (-80046).
- PC: starts with Windows (Startup shortcut, minimized); also Desktop / Start menu shortcuts. Tests
  `python -m pytest pc/tests -q` (284). Repo public (MIT): https://github.com/mAgNiFiCeNtTaCo/TacoCam.
- Settings for Whatnot: back camera **1080p** (the user was asked to switch back from 4K), 30 fps, H.264,
  20 Mbps; PC output 1920x1080 @ 30, rotate 0 (OBS turns the source 90 degrees). Presets 1 Wide Table (0.5x)
  and 2 Close UP (1.6x, focus + colors held; exposure lock suggested), Ctrl+Alt+1/2; Ctrl+Alt+0 saves a clip
  to Videos\Taco Cam clips.
- Scanner feed (shared memory "TacoCamFeed2", CONTRACT section 8) feeds the Whatnot scanner, whose camera is set
  to "Taco Cam (direct, full quality)".
- OBS's stream output is Whatnot's required WHIP setup: leave it alone.
- Not possible on this phone's back camera: anti-flicker, exact focus/ISO/shutter/white balance ("manual" = hold).
- Open: front camera / upright check (`docs/QA.md`); scanner card finding on a busy background (54 failed
  frames in Whatnot `data/debug` to tune against) if Test mode shows it's still unreliable.

## Log
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
