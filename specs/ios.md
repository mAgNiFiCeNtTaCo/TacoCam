# Brief: iPhone station (Taco Cam iPhone app)

You are one station of a nodeterm team building Taco Cam in `D:\ClaudeProjects\Webcam` (shared working
tree, no worktrees). Read `D:\ClaudeProjects\Webcam\CONTRACT.md` first: it is binding, especially
sections 1-5 (transport, framing, settings, STATE). Two other stations are building the Windows side
against the same contract at the same time, and a checker compares your Swift against their Python
afterwards, so implement the bytes exactly.

The user is not a programmer, has an iPhone 11 or newer, and uses it over the USB cable. This PC has
no Mac and no Xcode: you write the code here and GitHub Actions (macOS runner) compiles it.

## What to build

A SwiftUI iPhone app "Taco Cam" in `ios/`, generated with XcodeGen (`ios/project.yml`), iOS 16.0+,
bundle id `com.tacogabs.tacocam` (Sideloadly may rewrite it), no external packages.

1. **Camera** (AVFoundation): back camera = best virtual device per CONTRACT section 4 so 0.5x works;
   front = TrueDepth/wide. Formats for 720p/1080p/4k at 24/25/30/60 fps, picked from the device's
   formats (prefer 420v/x420 biplanar, video-binned off, matching max fps). Zoom in DISPLAYED units with
   the contract's multiplier rule, smooth `ramp` only when the PC asks for small steps is optional:
   plain set is fine. Focus auto/manual (lens position), exposure auto + EV bias / manual ISO+shutter,
   white balance auto/manual (temperature+tint -> gains, clamped to maxWhiteBalanceGain), torch level,
   stabilization off/standard/cinematic, HDR when supported, focus/exposure point of interest from
   FOCUS_POINT. Clamp every value; report the in-effect values in STATE. Fill STATE `cameras` from the
   real devices (lens_zooms from constituent devices + switch-over factors, iso/shutter ranges, fps per
   resolution). Never mirror; `videoRotationAngle` 0 on the data output. `rotation_hint` via
   `AVCaptureDevice.RotationCoordinator` on iOS 17+, table fallback on 16.
2. **Encoder** (VideoToolbox `VTCompressionSession`): H.264 High / HEVC Main, real-time, no frame
   reordering, average bitrate + data-rate limit, keyframe every 2 s and on KEYFRAME, output Annex-B
   (convert AVCC length prefixes to start codes, prepend parameter sets on every keyframe), pts in us.
   Recreate the session on codec/size/fps/bitrate change (bitrate can be set live).
3. **Server** (Network.framework): `NWListener` TCP 47777, one client, framing exactly per CONTRACT
   section 2, handshake order, PONG, STATE after every change and every 2 s, LOG lines for errors,
   back-pressure rule (drop non-key frames when >3 frames/2 MB queued, then keyframe). Encoder and
   camera run only while a PC is connected (or while the preview is visible on the phone).
   `NSLocalNetworkUsageDescription` for Wi-Fi.
4. **Phone screen**: full-screen live preview, quick-zoom buttons from `lens_zooms` (0.5x / 1x / 2x /
   3x...) plus pinch zoom, front/back switch, torch button, a settings sheet with the same controls
   the PC has, status line ("Plug into the PC with the USB cable and open Taco Cam on the PC" /
   "Connected: <fps> fps, <Mbps>"), its Wi-Fi/Tailscale IP addresses (for the bonus Wi-Fi mode),
   battery + thermal. Changes on the phone send STATE to the PC. "Dim screen" button (black screen,
   tap to wake) = `screen: "dim"`. Keep the phone awake while connected (`isIdleTimerDisabled`).
   Remember the last settings in UserDefaults. When iOS moves the app to the background, send
   STATE with `app_active: false` first (iOS stops the camera; the PC tells the user to reopen it).
   An app icon (simple generated PNG set: a taco-orange camera glyph is fine; draw it in Python with
   Pillow here and commit the PNGs).
5. **Build**: `.github/workflows/ios.yml` on push to main + manual dispatch, `runs-on: macos-15`,
   install XcodeGen (brew), generate, `xcodebuild` for `generic/platform=iOS` Release with
   `CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY=""`, package
   `Payload/TacoCam.app` into `TacoCam.ipa`, upload it as an artifact. Also add a quick unit-test
   target for the framing + Annex-B conversion (run with `xcodebuild test` on an iOS Simulator in the
   same job; no camera needed for those tests).

## Git and GitHub (you are the ONLY station that runs git)

The repo `D:\ClaudeProjects\Webcam` is already initialised with the private remote
`https://github.com/mAgNiFiCeNtTaCo/TacoCam` (branch main). Commit ONLY your paths:
`git add ios .github docs/INSTALL_IPHONE.md` (never `git add -A`, other stations' files are not yours
to commit), then `git push`. Watch the run with `gh run watch` / `gh run view --log-failed`.
**The repo is private: macOS minutes are billed 10x against a 2000-minute monthly free allowance, so
you have about 20 builds. Read your Swift very carefully before every push (types, optionals, actor
isolation, imports, availability checks), batch fixes, and stop after 15 runs** (report failed with
the remaining compile errors if it still does not build). Use `swift-tools`-free Swift 5 language
mode (`SWIFT_VERSION: 5.0`, strict concurrency minimal) to avoid Swift 6 isolation errors.
When green: `gh run download <id> -n <artifact> -D dist` so `dist/TacoCam.ipa` exists (dist/ is
gitignored).

## Install guide

`docs/INSTALL_IPHONE.md`, plain words for a non-programmer: install Sideloadly (sideloadly.io) and
iTunes-style Apple drivers (already present: Apple Mobile Device Support is installed), plug the
iPhone in, drag `dist\TacoCam.ipa` into Sideloadly, sign in with the Apple ID, then on the iPhone:
Settings > General > VPN & Device Management > trust the developer; turn on Developer Mode (iOS 16+:
Settings > Privacy & Security > Developer Mode, restart). Free Apple ID: the app stops opening after
7 days, re-drag (or Sideloadly's auto-refresh); paid developer account: 1 year. Allow camera access.

## Rules

- No secrets in files or logs. Don't touch other stations' paths (CONTRACT table). Don't change
  CONTRACT.md; if something in it is impossible on iOS, write the problem and your proposed change to
  `D:\ClaudeProjects\Webcam\specs\NOTES.md` (append, dated, signed "iPhone station") and carry on
  with the closest behaviour.
- Write multi-line scripts with the Write tool, not bash heredocs.

## When you are done

Run exactly one of (absolute shim path):

```
sh "%APPDATA%\node-terminal\canvas-control\nodeterm.sh" report-outcome --outcome succeeded --note "iPhone app builds green, dist/TacoCam.ipa downloaded"
sh "%APPDATA%\node-terminal\canvas-control\nodeterm.sh" report-outcome --outcome failed --note "<one line: why>"
```

`succeeded` only if the GitHub build is green and `dist/TacoCam.ipa` exists. End with a short summary:
files, the run URL, what could not be verified without a real iPhone.
