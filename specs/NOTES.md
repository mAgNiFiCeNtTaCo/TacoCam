# Team notes (append only: dated, signed by station)

Stations write questions, contract problems and "READY FOR USER" items here. The orchestrator reads it.

- 2026-10-25 Engine station: READY FOR USER: run pc/vcam/Install Taco Cam camera.bat (double-click it, say Yes to the Windows permission prompt; it registers the "Taco Cam" camera, then restart OBS). Unity Capture (2023-04-14 release, UnityCaptureFilter64.dll) is not on OBS 32 DLL blocklist (only the old ...64bit.dll name is). Details: pc/vcam/SOURCE.md.

- 2026-10-25 iPhone station: notes on choices the contract leaves open (no contract change needed):
  (1) VIDEO bit1 (format changed) is also set on the FIRST frame after video starts on each connection,
  and on any codec/size change; (2) rotation_hint on iOS 16 (table fallback): back camera portrait 90,
  port-right landscape 0, upside-down 270, port-left 180; FRONT camera = back + 180 (front sensor is
  mounted turned, unverified without a device). iOS 17+ uses RotationCoordinator for both cameras;
  (3) thermal: serious caps fps at 30, critical at 24 (LOG line says so; STATE settings.fps shows the cap);
  (4) video starts after the PC's SET is applied, or 3 s after HELLO if no SET comes; (5) the phone closes a
  connection it hears nothing on for 10 s; (6) STATE battery is 0 when iOS reports unknown (simulator).

- 2026-10-25 Engine station: virtual camera INSTALLED (the user ran the script) and VERIFIED. ffmpeg's DirectShow
  list shows "Taco Cam"; `python pc/tests/vcam_readback.py` (engine + fake phone -> Taco Cam -> ffmpeg) reads
  live frames, then the engine's static "waiting" card back bit-identical (PSNR 99 dB) at 1280x720 and 1080x1920.
  The OBS Virtual Camera fallback was also proven the same way (`--backend obs`). DirectShow gives 2 black frames
  when a reader starts (normal).
- 2026-10-25 Engine station, for README / App station: (1) portrait outputs (1080x1920, 2160x3840): Unity Capture
  only lists landscape sizes, so in OBS's Video Capture Device set "Resolution/FPS Type: Custom" and type the size;
  max is 3840x2160 (portrait 2160x3840 fits). (2) Only one sender per camera: a second Taco Cam process gets
  vcam "error" "Another Taco Cam window is already sending..." (named mutex) instead of flicker.
  (3) test_app_real.py builds App(tk_root, Engine) and so feeds the REAL Taco Cam camera during tests (seen
  interleaving with my readback); tests should pass `lambda s, log: Engine(s, log, vcam_factory=null_factory)`
  (from tacocam.vcam). Messaged the App station. (4) Engine keyword-only extras for tests: port=,
  usbmux_address=, vcam_factory=. pc.wifi_host also accepts "host:port". (5) The engine does not copy phone
  STATE settings back into its own settings; the app reads get_status()["phone"]["settings"] for what is in
  effect. Nested phone keys (focus/exposure/white_balance) are always sent whole in SET.
- 2026-10-25 Engine station: not verified here: a real iPhone over USB (none plugged in; usbmux tested against a
  fake usbmuxd plus a real ListDevices/Listen call to 127.0.0.1:27015, empty list). Decoding is software
  (PyAV, ~6 ms per 4K HEVC frame on this PC), no hardware decode needed.
- 2026-10-25 Checker: Swift matches CONTRACT + PC code (docs/QA.md). Push had been blocked: gh token lacked `workflow` scope (user ran `gh auth refresh -s workflow`). 4 small iOS fixes; first GitHub build green (run 40247409884, 14 iOS tests pass); dist/TacoCam.ipa downloaded. Needs the real iPhone next.
