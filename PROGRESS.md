# Webcam (Taco Cam): progress log

Taco Cam: our own iPhone-as-USB-webcam app (what Iriun Webcam does, every feature, plus a 0.5x ultra-wide
zoom-out). An iPhone app sends H.264/HEVC over the USB cable; a PC window shows it and feeds OBS through a
DirectShow camera called "Taco Cam". Used for the user's Whatnot box-break stream.

## Where it stands (2026-10-25)
- **Working end to end with the real phone** (iPhone 11, iOS 27.0.1): USB connection, live picture in the PC
  window and in the "Taco Cam" camera (checked by grabbing a frame with ffmpeg), 0.5x lens found.
- iPhone app: built on GitHub Actions (`iPhone app` workflow, first run 40247409884 green, 14 iOS tests pass);
  `dist/TacoCam.ipa` (gitignored) installed on the phone with **iloader** (Sideloadly login is broken by
  Apple since 2026-10-21, error -80046). Free Apple ID: reinstall every 7 days.
- PC: `Taco Cam.bat`; tests `python -m pytest pc/tests -q` (246 tests).
- Settings in use for Whatnot (`settings.json`): phone back camera, 1080p, 30 fps, H.264, 20 Mbps,
  stabilization off; PC output 1920x1080 @ 30, rotate 0 (the OBS scene turns the source 90 degrees to fill
  its 1080x1920 canvas).
- OBS's stream output (WHIP to Whatnot/Amazon IVS, x264 veryfast/zerolatency, 3500 kbps CBR, keyframe 2 s,
  Opus 160) is Whatnot's required setup: leave it alone.
- Not yet checked on the phone: picture upright when the phone is held upright, front camera, manual
  exposure/white balance/torch round trips (checklist in `docs/QA.md`).

## Log
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
- Open: check upright picture with the phone held upright, front camera and the rest of `docs/QA.md`;
  reinstall with iloader every 7 days; update `docs/INSTALL_IPHONE.md` to iloader (still says Sideloadly).
