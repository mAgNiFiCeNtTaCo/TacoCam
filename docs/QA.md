# Taco Cam: final check (2026-10-25)

## What was checked

**iPhone code against the PC code and CONTRACT.md, line by line** (`ios/TacoCam/*.swift` vs
`pc/tacocam/protocol.py`, `link.py`, `usbmux.py`, `engine.py`, `app.py`):

| Item | Result |
|---|---|
| Framing: u32 big-endian length incl. type byte, u8 type, 1..16 MB limit | match |
| Message numbers 0x01-0x05, 0x10, 0x20, 0x21, 0x30; unknown types ignored | match |
| VIDEO: u8 flags + u64 big-endian pts_us + Annex-B; bit0 keyframe, bit1 format changed | match |
| Annex-B: 4-byte lengths -> 00 00 00 01; SPS+PPS (HEVC: VPS+SPS+PPS) in front of every keyframe | match |
| No B-frames (AllowFrameReordering off), keyframe every 2 s and on KEYFRAME request | match |
| Handshake: PC HELLO -> phone HELLO + STATE -> PC SET -> VIDEO starting at a keyframe | match |
| PING -> PONG with the same bytes; phone drops a silent PC after 10 s, PC after 5 s | match |
| Back-pressure: >3 frames or >2 MB unsent -> drop non-key frames, then send a keyframe | match |
| SET / STATE key names, value types and units (displayed zoom, seconds, Kelvin, EV) | match (every key the PC reads is sent) |
| 0.5x: triple / dual-wide / dual / wide device order, displayed zoom = videoZoomFactor x multiplier | match |
| FOCUS_POINT in sensor coordinates (unrotated, unmirrored) | match |
| usbmuxd Connect with PortNumber byte-swapped (PC side) | match |
| Info.plist camera + local network texts (no Bonjour type since 2026-11-11) | present |
| Session changes inside begin/commitConfiguration, device changes inside lockForConfiguration | yes |
| Network listener restarted when the app returns to the foreground; UI updates on the main thread | yes |

## Fixed

- **The iPhone app had never reached GitHub**, so it was never built: the push was refused because the
  GitHub login lacked the `workflow` permission. Fix: `gh auth refresh -h github.com -s workflow`.
- Camera format could be overwritten by the session preset when the session starts: the session now uses
  the `inputPriority` preset, so the chosen resolution/fps format sticks.
- Two camera notification names used Swift spellings that changed between Apple SDK versions (a possible
  build break): now spelled as their fixed text names.
- iOS 16 only: the rotation table added 180 degrees for the front camera. AVFoundation's rotation is the
  same for both cameras, so the front camera now uses the same table (iOS 17+ was already right).
- The phone screen could auto-lock before the PC connected, which stops the camera and the listener. The
  screen now stays on whenever Taco Cam is open (use Dim to save battery).

## PC side

- `python -m pytest pc/tests -q`: 245 tests. One full run had 1 failure (`test_app_real.py`, an out-of-memory
  error inside Pillow's Tk image code); that file then passed 3 runs in a row on its own. Looks like
  a one-off memory hiccup on this PC, not a Taco Cam bug.
- The engine with the fake phone sends moving frames to the installed "Taco Cam" camera, verified by reading
  them back with ffmpeg (Engine station, see `specs/NOTES.md`).

## Needs the real iPhone (first-run checklist)

1. Install `dist/TacoCam.ipa` with iloader (`docs/INSTALL_IPHONE.md`). On the phone: Settings > General >
   VPN & Device Management > trust your Apple ID. Open Taco Cam, allow the camera.
2. Plug the phone into the PC, tap **Trust** if asked. Keep Taco Cam open on screen.
3. Double-click `Taco Cam.bat`. The bottom bar should say "Connected to iPhone ..." and the picture appears.
4. Press the **0.5x** button: the picture should get wider (ultra-wide lens).
5. Hold the phone upright: the picture should be upright in the window (if not, set Rotate by hand and tell
   Claude which way it was wrong). Try the front camera too.
6. Set Output to **1080x1920**, then in OBS add Video Capture Device > **Taco Cam**, Resolution/FPS Type
   **Custom**, **1080x1920**.
7. Try a few controls (focus tap, exposure, torch) and watch that the window shows the new values.

## Who may connect: check on the real iPhone

The phone app lets in the USB cable, and Wi-Fi only with a pairing code (CONTRACT sections 1 and 2). The
Swift for this was written on 2026-11-11 without a compiler or a phone at hand, so do these once with the
new build, not right before a show. Keep the old `dist/TacoCam.ipa` until
step 1 passes: reinstalling it brings the old behaviour back.

1. **USB still works.** Cable in, Taco Cam open on both. The phone should say "Connected (USB): 30 fps, ..."
   and OBS shows the picture. If the phone instead shows "Refused a connection from ...: Wi-Fi connections
   are off", this phone does not hand USB connections to the app the way the code expects: note the address
   it shows and tell Claude. Until that is fixed you can switch on Allow Wi-Fi connections and type the code
   on the PC (it is used over the cable too), or reinstall the old IPA.
2. **Wi-Fi is refused by default.** On the PC choose Connect by Wi-Fi and type the phone's IP address
   (iPhone Settings > Wi-Fi > the (i) next to the network), no code. The PC should say it needs the pairing
   code and the phone should stay on "Plug into the PC...".
3. **Wi-Fi works with the code.** Phone: Settings > Wi-Fi > Allow Wi-Fi connections. Type the code it shows
   into the PC's Pairing code box. The phone should say "Connected (Wi-Fi 192.168...)".
4. **A wrong code gets nothing.** Change one letter of the code on the PC: no picture, the PC log says the
   iPhone did not accept the pairing code, the phone shows "Refused ...: wrong pairing code".
5. **A second connection does not cut the first one off.** While the picture runs over USB, try to connect
   from another computer over Wi-Fi with the code: it is turned away ("a PC is already connected") and the
   picture in OBS keeps running.
6. Switch Allow Wi-Fi connections off again if you only use the cable.
