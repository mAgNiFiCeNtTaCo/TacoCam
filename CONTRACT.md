# Taco Cam: build contract

Our own iPhone-as-webcam app (what Iriun Webcam does, every feature included, plus a 0.5x ultra-wide
zoom-out), used mainly over the USB cable, feeding OBS on this Windows 11 PC. This is an independent app:
never touch, patch or talk to Iriun's own app or driver.

Decided with the user (2026-10-25): iPhone 11 or newer (has the 0.5x ultra-wide lens); our own iPhone
app built on GitHub Actions (macOS) from the PRIVATE repo `mAgNiFiCeNtTaCo/TacoCam`, installed with
Sideloadly + the user's Apple ID; used in OBS (Video Capture Device). No phone microphone.

## Folder layout (D:\ClaudeProjects\Webcam)

| Path | Owner |
|---|---|
| `CONTRACT.md`, `specs/` | orchestrator (read-only for stations; ask before changing) |
| `ios/` (XcodeGen `project.yml`, `TacoCam/*.swift`, `Info.plist`, assets) | iPhone station |
| `.github/workflows/ios.yml`, `dist/TacoCam.ipa`, `docs/INSTALL_IPHONE.md` | iPhone station |
| `pc/tacocam/{protocol,usbmux,link,decoder,pipeline,vcam,engine}.py`, `pc/tools/fake_phone.py`, `pc/vcam/` (virtual camera DLLs + install scripts), `pc/tests/test_engine*.py`, `pc/requirements.txt` | Engine station |
| `pc/tacocam/{app,settings,ui_*}.py`, `pc/tacocam/__main__.py`, `Taco Cam.bat`, `README.md`, `pc/tests/test_app*.py` | App station |

Only the iPhone station runs git (it must push so GitHub can build): it commits ONLY `ios/`,
`.github/`, `docs/INSTALL_IPHONE.md` with `git add ios .github docs/INSTALL_IPHONE.md` (never `git add -A`).
Other stations do not commit; the orchestrator snapshots at the end.

## 1. Transport

- The iPhone app listens on **TCP port 47777** on all interfaces (Network.framework `NWListener`).
  One PC client at a time; a new connection replaces the old one (close the old one).
- **USB (main way):** the PC connects through Apple's usbmuxd, which the Apple Mobile Device Service on
  Windows exposes at **TCP 127.0.0.1:27015**. Protocol: 16-byte little-endian header
  `(u32 total_length incl. header, u32 version=1, u32 message=8 (plist), u32 tag)` + XML plist body.
  - `{"MessageType":"ListDevices","ClientVersionString":"TacoCam","ProgName":"TacoCam"}` -> reply
    `DeviceList`, each with `DeviceID` and `Properties` (`ConnectionType` "USB"/"Network", `SerialNumber`).
  - `{"MessageType":"Connect","DeviceID":id,"PortNumber":htons(47777),...}` -> reply `Result` with
    `Number` 0 = success; from then on the same socket is a raw byte pipe to the phone's port 47777.
  - `Listen` gives `Attached`/`Detached` events (used to notice plug/unplug).
  - Use only USB-connected devices for the "usb" mode. Device name: lockdown is not needed; show the
    `SerialNumber` (shortened) until the phone's HELLO gives its name.
- **Wi-Fi (bonus):** direct TCP to `<phone ip>:47777`; the phone shows its IP addresses on screen.
  The fake phone (`pc/tools/fake_phone.py`) listens on 127.0.0.1:47777 and is reached this way.

## 2. Framing (both directions, after the transport is open)

Every message: `u32 big-endian N` (length of what follows) + `u8 type` + `N-1` bytes payload.
N must be 1..16_777_216; anything else = protocol error, drop the connection.

| Type | Name | Dir | Payload |
|---|---|---|---|
| 0x01 | HELLO | both | UTF-8 JSON |
| 0x02 | SET | PC->phone | UTF-8 JSON: partial settings (section 4) |
| 0x03 | STATE | phone->PC | UTF-8 JSON: full state (section 5) |
| 0x04 | KEYFRAME | PC->phone | empty: send an IDR frame now |
| 0x05 | FOCUS_POINT | PC->phone | UTF-8 JSON `{"x":0..1,"y":0..1}` in SENSOR frame coords (as sent, before any PC rotation/mirror); focus + exposure point of interest, then continuous auto around it |
| 0x10 | VIDEO | phone->PC | `u8 flags` + `u64 big-endian pts_us` + Annex-B bitstream (00 00 00 01 start codes) |
| 0x20 | PING | PC->phone | any bytes; phone answers PONG with the same bytes |
| 0x21 | PONG | phone->PC | the PING's bytes |
| 0x30 | LOG | phone->PC | UTF-8 text line (errors/warnings, shown in the PC log) |

Unknown types are ignored (forward compatibility). JSON is objects only.

**Handshake:** PC connects -> PC sends HELLO `{"proto":1,"client":"TacoCam PC","version":"1.0"}` ->
phone sends HELLO `{"proto":1,"app":"TacoCam","version":"1.0","device":"iPhone 13 Pro","ios":"18.1"}`
then a STATE, then the PC sends one SET with ALL its phone settings, then the phone starts sending
VIDEO (starting with a keyframe). The phone sends STATE after every change (from the PC or its own
screen) and every 2 s (battery/thermal). The PC sends PING every 1 s; no data from the phone for 5 s =
connection dead, reconnect.

**VIDEO flags:** bit0 = keyframe (IDR), bit1 = format changed (codec/size differ from the previous
frame). Every keyframe carries its parameter sets in front (H.264: SPS+PPS, HEVC: VPS+SPS+PPS) so the
PC decoder can start at any keyframe. Codec + size of the stream are in STATE `stream`.
No B-frames (no frame reordering), so decode order = display order.

**Back-pressure (phone):** never let latency build up. If more than ~3 frames (or 2 MB) are waiting
unsent, drop non-key frames until the queue drains, then send the next frame as a keyframe.

## 3. Frames and orientation

The phone sends frames as the sensor delivers them (`videoRotationAngle` 0: landscape) and never
rotates or mirrors them. The PC rotates/mirrors. STATE `rotation_hint` = clockwise degrees (0/90/180/270)
the PC must turn the frame so the scene is upright for how the phone is held right now
(iOS 17+: `AVCaptureDevice.RotationCoordinator.videoRotationAngleForHorizonLevelCapture`; older iOS: from
`UIDevice.orientation` with a table, back camera portrait = 90). PC rotate "auto" uses it.

## 4. Phone settings (SET payload, STATE `settings`; all keys optional in SET)

```json
{
  "camera": "back",                 // "back" | "front"
  "zoom": 1.0,                      // DISPLAYED zoom like the Camera app: 0.5 = ultra-wide, 1 = main, 2/3/5 = tele/crop
  "resolution": "1080p",            // "720p" (1280x720) | "1080p" (1920x1080) | "4k" (3840x2160)
  "fps": 30,                        // 24 | 25 | 30 | 60 (phone clamps to what the active device/format supports)
  "codec": "h264",                  // "h264" | "hevc"
  "bitrate_mbps": 16,               // 2..80 average bitrate
  "focus": {"mode": "auto", "position": 0.5},           // "auto" (continuous) | "manual" (lens position 0..1)
  "exposure": {"mode": "auto", "bias": 0.0, "iso": null, "shutter_s": null},
                                    // "auto" (+ EV bias -3..3, clamped) | "manual" (iso + shutter_s seconds, clamped)
  "white_balance": {"mode": "auto", "temperature": 5000, "tint": 0},  // "auto" | "manual" (K 2500..8000, tint -150..150)
  "torch": 0.0,                     // 0 = off, 0.01..1 = level (back camera with torch only)
  "stabilization": "off",           // "off" | "standard" | "cinematic" (adds latency; off is default)
  "hdr": false,                     // video HDR when the format supports it
  "screen": "normal",               // "normal" | "dim" (phone shows black + small status to save battery/heat)
  "anti_flicker": "off"             // "off" | "60hz" | "50hz" (added 2026-10-25): in AUTO exposure only, the phone fixes
                                    // the shutter to a flicker-safe time (60hz: 1/60 s, 50hz: 1/50 s, or 1/120 / 1/100 when
                                    // that is longer than a frame) and steers ISO from the meter itself (bias still applies).
                                    // STATE reports "off" when the camera/frame rate can't do it; in manual exposure it keeps
                                    // the requested value (it applies again once exposure is back on auto).
}
```

**0.5x zoom:** back camera uses the best virtual device available, in order
`builtInTripleCamera`, `builtInDualWideCamera`, `builtInDualCamera`, `builtInWideAngleCamera`.
On a device containing the ultra-wide, `videoZoomFactor` 1.0 is the ultra-wide (displayed 0.5x).
Displayed zoom = `videoZoomFactor * m`, with m = `displayVideoZoomFactorMultiplier` on iOS 18+, else
`1 / virtualDeviceSwitchOverVideoZoomFactors[0]` when the device has an ultra-wide constituent, else 1.
The phone converts the displayed zoom to `videoZoomFactor` and clamps it into the active format's range.
The lens switch-over itself is automatic (virtual device). Front camera: min displayed zoom 1.

## 5. STATE (phone -> PC)

```json
{
  "settings": { ...section 4, the values actually in effect after clamping... },
  "stream": {"codec": "h264", "width": 1920, "height": 1080, "fps": 30},
  "cameras": {
    "back":  {"available": true, "name": "Back Triple Camera", "min_zoom": 0.5, "max_zoom": 15.0,
              "lens_zooms": [0.5, 1.0, 3.0], "has_torch": true,
              "resolutions": ["720p","1080p","4k"], "fps": {"720p":[24,25,30,60],"1080p":[24,25,30,60],"4k":[24,25,30,60]},
              "iso_range": [32, 3072], "shutter_range_s": [0.00002, 0.5], "focus_manual": true, "hdr": true,
              "stabilization": ["off","standard","cinematic"],
              "focus_lock": true, "exposure_manual": false, "wb_manual": false, "anti_flicker": false},
              // (flags added 2026-10-25) The combined back camera (Dual Wide / Triple virtual device) refuses a lens
              // position, custom ISO/shutter and custom white-balance gains. There a "manual" focus / exposure /
              // white_balance in SET means HOLD: focus once on the middle of the picture then lock, freeze exposure,
              // freeze colors; STATE then reports the values in use. anti_flicker needs exposure_manual.
    "front": { ...same keys... }
  },
  "rotation_hint": 90,
  "orientation": "portrait",        // "portrait" | "portrait_upside_down" | "landscape_port_right" | "landscape_port_left" | "flat" | "unknown"
  "battery": 0.82, "charging": true,
  "thermal": "nominal",             // "nominal" | "fair" | "serious" | "critical" (phone lowers fps itself at serious+ and says so in LOG)
  "app_active": true,               // false right before iOS sends the app to the background (camera stops)
  "error": null,                    // text when the camera could not start / a setting failed
  "live": {"lens_position": 0.42, "iso": 200.0, "shutter_s": 0.016667, "temperature": 4650, "tint": 4},
                                    // (added 2026-10-25) what the camera really uses right now, also in auto modes;
                                    // the PC locks presets at these values. null before the camera runs.
  "app_expires": "2026-11-01T20:30:00Z"
                                    // (added 2026-10-25) when this sideloaded copy stops opening (ExpirationDate of the
                                    // embedded provisioning profile, UTC ISO 8601); null when unknown. PC warns 2 days ahead.
}
```

`lens_zooms` = displayed zooms of the physical lenses (0.5 ultra-wide, 1 wide, 2/3/5 tele) for the
quick-zoom buttons.

## 6. PC settings and the engine API (Python, `pc/tacocam/`)

Python 3.14, packages: `av==19.0.2` (PyAV, H.264/HEVC decode), `pyvirtualcam==0.15.0`, `numpy`,
`opencv-python` (cv2, resize/rotate), `Pillow` (preview). `pc/requirements.txt` pins them.

Settings file: `D:\ClaudeProjects\Webcam\settings.json` (gitignored), written by the app, shape:

```json
{
  "phone": { ...section 4 ... },
  "pc": {
    "connect": "usb",               // "usb" | "wifi"
    "wifi_host": "",                // phone IP for "wifi"; "127.0.0.1" = fake phone
    "rotate": "auto",               // "auto" | 0 | 90 | 180 | 270 (clockwise)
    "mirror": false, "flip": false, // after rotation: mirror = left-right, flip = upside-down
    "output": "1920x1080",          // virtual camera size: "1280x720","1920x1080","3840x2160" landscape, "1080x1920","2160x3840" portrait
    "fit": "crop",                  // "crop" (fill, cut edges) | "fit" (black bars) | "stretch"
    "fps_out": 30,                  // virtual camera frame rate (repeats the last frame if the phone is slower)
    "vcam_name": "Taco Cam",
    "when_disconnected": "card"     // "card" (a "Taco Cam: waiting for iPhone" picture) | "last" (freeze last frame) | "black"
  }
}
```

Engine API (Engine station builds, App station uses; thread-safe, never blocks the UI thread):

```python
from tacocam.engine import Engine
eng = Engine(settings: dict, log=callable_or_None)  # log(str) gets human-readable lines
eng.start()                       # connection + decode + virtual camera threads; reconnects forever
eng.stop()                        # stops all threads within 2 s, releases the virtual camera
eng.update_settings(partial)      # same shape as settings.json, partial; "phone" keys go to the phone as SET,
                                  # "pc" keys apply locally (vcam size/fps change restarts the vcam output)
eng.get_status() -> dict          # {"link": "searching"|"connecting"|"connected"|"no_app"|"error",
                                  #  "transport": "usb"|"wifi"|None, "device_name": str|None,
                                  #  "phone": <last STATE dict>|None, "fps_in": float, "fps_out": float,
                                  #  "bitrate_mbps": float, "rtt_ms": float|None, "dropped": int,
                                  #  "vcam": "running"|"not_installed"|"error"|"stopped",
                                  #  "vcam_backend": "unitycapture"|"obs"|None, "vcam_device": str|None,
                                  #  "out_size": [w, h], "error": str|None}
eng.get_preview(max_w, max_h)     # latest OUTPUT frame (what OBS gets), RGB uint8 HxWx3 numpy, scaled to fit; or None
eng.tap_focus(x, y)               # x,y 0..1 on the OUTPUT frame; engine maps back through fit/rotate/mirror to sensor coords -> FOCUS_POINT
eng.request_keyframe()
```

"no_app" = a USB iPhone is attached but nothing listens on 47777 (app not open / in background).

## 7. Virtual camera

OBS must see a DirectShow video capture device named **Taco Cam** (like it sees "Iriun Webcam").
First choice: the Unity Capture DirectShow filter (pyvirtualcam backend `unitycapture`) registered under
the custom name "Taco Cam"; installed once by the user with an admin script
(`pc/vcam/Install Taco Cam camera.bat` / `Uninstall ...bat`). Fallback: OBS Virtual Camera (backend `obs`),
which conflicts with OBS's own Start Virtual Camera button, so the app says so.
Output frames: RGB at `pc.output` size and `pc.fps_out`.

## 8. Scanner feed (added 2026-10-25)

Taco Cam publishes its newest decoded phone picture (full stream size, up to 3840x2160) in a named
shared memory block **"TacoCamFeed2"** for other programs on this PC (the Whatnot card scanner,
`scanner/tacocam_feed.py` there). Little-endian layout:

| Offset | Field |
|---|---|
| 0 | magic `"TCF2"` (4 bytes), 4: version u32 = 2 |
| 8 | want f64: `time.time()` until which a reader wants pictures. The READER writes it (~2 s ahead); Taco Cam copies pictures only while it is in the future |
| 16 | latest u32: slot (0/1) with the newest complete picture |
| 64 + 32*i | slot i header: seq u64 (odd while written), width u32, height u32, format u32 (2 = BGR24, already turned upright with `pc.clip_rotate`), pad u32, time f64 (decoded at) |
| 128 + i * 3840*2160*3 | slot i pixels, rows packed |

Taco Cam writes the slot readers are not on, then flips `latest`. Readers copy the newest slot and check its
seq did not change. Pictures older than ~2 s are stale (phone gone).

## 9. Definition of done

- iPhone: GitHub Actions builds `TacoCam.ipa` (unsigned, for Sideloadly) green; `dist/TacoCam.ipa`
  downloaded; code implements sections 1-5 exactly; `docs/INSTALL_IPHONE.md` explains Sideloadly
  install + 7-day refresh in plain words.
- PC: `python -m pytest pc/tests -q` passes; with `pc/tools/fake_phone.py` running, `Taco Cam.bat`
  shows the moving test picture in the app preview and every control round-trips (SET -> STATE);
  the virtual camera "Taco Cam" is visible to DirectShow (`ffmpeg -list_devices true -f dshow -i dummy`)
  once the user ran the install script, and frames read from it are the app's output.
- Plain-English `README.md`: install, connect by USB, add "Taco Cam" in OBS, every control explained.
