# Brief: Checker station (Taco Cam final check)

You start after the iPhone, Engine and App stations reported success. You are linked to them: read
what they did with the get-linked-context skill if you need to. Read
`D:\ClaudeProjects\Webcam\CONTRACT.md` and `D:\ClaudeProjects\Webcam\specs\NOTES.md` first.

The iPhone app cannot run on this PC (no Mac, the user's phone may not be plugged in), so the most
important job is a careful, line-by-line **conformance check of the Swift code (`ios/`) against the
Python side (`pc/tacocam/protocol.py`, `link.py`, `decoder.py`, `pc/tools/fake_phone.py`) and the
contract**: byte order and length of every header (u32 BE length incl. type byte, u8 type, VIDEO
`u8 flags + u64 BE pts_us`), message type numbers, handshake order, JSON key names and value types
for SET/STATE (every key in CONTRACT sections 4-5, units: displayed zoom vs videoZoomFactor, seconds,
Kelvin), Annex-B conversion (AVCC 4-byte lengths -> 00 00 00 01, parameter sets in front of every
keyframe, HEVC VPS), keyframe flag, back-pressure, rotation_hint meaning (clockwise degrees PC
applies), FOCUS_POINT coordinate space, ping/timeout numbers, port 47777, usbmuxd plist
(PortNumber byte-swapped). Also check iOS details that would fail only on a device: camera permission
keys in Info.plist, session configuration inside begin/commitConfiguration, lockForConfiguration
around device changes, format/fps selection, zoom clamping with the 0.5x multiplier, VideoToolbox
callbacks, Network.framework listener restart after the app returns to the foreground, main-thread UI.

Then run the PC side yourself: `python -m pytest pc/tests -q`; fake phone + `python -m tacocam` (or
the engine directly) end to end; if `ffmpeg -hide_banner -list_devices true -f dshow -i dummy` lists
"Taco Cam", read frames from it while the fake phone runs and check they move.

Fix real defects you find (small, surgical edits, in any station's files; re-run the tests). If a fix
touches `ios/`, commit just those paths (`git add ios .github` then commit) and push, and watch the
GitHub build (`gh run watch`): at most 3 builds, the repo's macOS minutes are limited; re-download
`dist/TacoCam.ipa` when green (`gh run download <id> -D dist`, then move the ipa to `dist/TacoCam.ipa`).
Write `docs/QA.md`: what you checked, what you fixed, what still needs the real iPhone (a short
first-run checklist for the user: install, open, plug in, 0.5x button, portrait in OBS).

Rules: no secrets; don't change CONTRACT.md (write disagreements into docs/QA.md); write scripts with
the Write tool, not bash heredocs.

When you are done run exactly one of:

```
sh "%APPDATA%\node-terminal\canvas-control\nodeterm.sh" report-outcome --outcome succeeded --note "checked: Swift matches contract, N tests pass, fixes: ..."
sh "%APPDATA%\node-terminal\canvas-control\nodeterm.sh" report-outcome --outcome failed --note "<one line: why>"
```
