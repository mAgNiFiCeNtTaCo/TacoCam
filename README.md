# Taco Cam

Taco Cam turns your iPhone into a webcam for OBS, like Iriun Webcam does, and adds a **0.5x zoom-out**
(the ultra-wide lens). It works mainly over the USB cable. It is made for a **portrait 1080x1920** OBS
canvas (your Whatnot box breaks), but landscape works too.

Two parts:

- **The iPhone app** (Taco Cam) sends the camera picture.
- **The PC window** (this folder) shows the picture, lets you change every camera setting, and gives OBS a
  camera called **Taco Cam**.

You need an iPhone 11 or newer (older phones have no 0.5x lens).

## One-time setup

1. **Python packages.** Open a terminal in this folder and run:
   `pip install --user -r pc/requirements.txt`
2. **The virtual camera.** Double-click `pc\vcam\Install Taco Cam camera.bat` and say **Yes** to the Windows
   question. Then restart OBS. (The app also has an **Install virtual camera** button in the bottom bar that
   does the same, if the camera is missing.)
3. **The iPhone app.** Follow `docs/INSTALL_IPHONE.md` (it explains iloader step by step).
4. Install **iTunes or Apple Devices** from the Microsoft Store if you haven't: Windows needs Apple's USB
   driver to talk to the iPhone.

## Shortcuts with the Taco Cam icon (optional)

Run `python pc/tools/make_shortcuts.py` once: it puts a **Taco Cam** shortcut (orange camera icon) on your
Desktop and in the Start menu. Right-click it > Pin to taskbar if you like. `--remove` takes them away.

## Daily use

1. Plug the iPhone into the PC with the cable. If it asks **Trust This Computer?**, tap **Trust**.
2. Open **Taco Cam** on the iPhone and leave it open (the screen stays on; you can dim it, see below).
3. Double-click **`Taco Cam.bat`** (or the **Taco Cam** shortcut on your Desktop / Start menu). The window
   opens and the picture appears within a few seconds.
4. In OBS, use the **Taco Cam** camera (next section).

Only one Taco Cam window can run at a time. Closing the window stops everything cleanly.

## Adding "Taco Cam" in OBS

1. In OBS: **Sources > + > Video Capture Device**. Name it, press OK.
2. **Device:** `Taco Cam`.
3. **Resolution/FPS Type:** `Custom`, then **Resolution:** the same size as the Output size in Taco Cam
   (for your portrait canvas: **1080x1920**). Set FPS to match.
4. Press OK. Resize the source to fill the canvas if needed.

If you also use OBS's own "Start Virtual Camera" button, note that Taco Cam avoids it: it uses its own
camera. Only when the Taco Cam camera isn't installed does it fall back to OBS's, and then the bottom bar tells
you not to press OBS's button.

## The window

**Left:** the live picture (exactly what OBS gets).

- **Click** the picture to focus on that spot (a small orange square shows where).
- **Mouse wheel** on the picture zooms.
- Under it: big **zoom buttons** (0.5x, 1x, 3x... whatever lenses your phone has) and a **zoom slider**.
- Under those: your preset buttons, **Pre-show check** and **Save last 30 s**.

**Bottom bar:** connection ("Searching for iPhone on USB", "iPhone found: open Taco Cam on the phone",
"Connected to ..."), phone battery, a warning if the phone gets hot, picture speed (in/out fps, Mbps, delay,
dropped frames), and whether the "Taco Cam" camera is ready for OBS. When the phone is connected but its camera
stopped, a red line says why (Taco Cam in the background, another app such as FaceTime took the camera, split
screen, phone too hot).

Greyed-out controls are things the current camera can't do; the little orange text says why. The window
always shows the value the phone really uses (it may adjust what you ask for).

### Camera tab
| Control | What it does |
|---|---|
| Camera | Back (has the 0.5x lens) or front. |
| Resolution | 720p, 1080p or 4K from the phone. 1080p is plenty. |
| Frame rate | 24 / 25 / 30 / 60, only what the camera supports. |
| Video codec | H.264 (safe) or HEVC (sharper at the same Mbps). |
| Bitrate | How much data per second. Higher = sharper. 16 Mbps is good for 1080p. |
| Zoom speed | How the zoom moves when you switch presets, click a zoom button or turn the wheel: **Smooth** (default) glides there in half a second instead of jumping; Slow / Very slow take 1 / 2 s; Instant jumps. Focus / brightness / color holds of a preset start once the glide has ended. |

### Image tab
| Control | What it does |
|---|---|
| Focus | Auto, or Manual with a distance slider. |
| Exposure | Auto with a brightness (EV) slider, or Manual with ISO and shutter. |
| Anti-flicker | **60 Hz (US)** stops LED / fluorescent room lights from banding or flickering on the picture (great on foil). The shutter follows the lights, brightness stays automatic. Auto exposure only. Not available on the back camera's combined 0.5x-1x lenses (Apple doesn't allow a fixed shutter there): greyed out then. |
| White balance | Auto, or Manual with temperature (cool to warm) and tint. |
| Torch | The phone's flashlight (back camera). |
| Stabilization | Off / Standard / Cinematic. Adds a little delay. Off is best on a tripod. |
| HDR video | Better bright areas, where supported. |
| Reset image settings | Puts focus, exposure, anti-flicker, white balance, torch, stabilization and HDR back to normal. |

### Presets tab
Save the picture settings you switch between during a show (zoom, focus, exposure, colors, light,
anti-flicker), for example **Wide table** (0.5x) and **Card close-up** (zoomed in, focus locked).
Resolution, fps and bitrate are not part of a preset (changing those restarts the video).

| Control | What it does |
|---|---|
| Save new... | Saves what the camera does now (on the back camera a lock means *hold*: focus once on the middle of the picture and stay there, freeze brightness / colors). The **lock** boxes turn auto focus / exposure / colors into fixed values at what the camera uses right now, so the focus doesn't hunt when your hands move and foil doesn't change the brightness. |
| Apply / double-click | Uses that preset. The buttons under the preview do the same (the lit one is in use; it goes dark when you change a camera setting by hand). |
| Update / Rename / Delete | Change the selected preset. Up to 9 presets. |
| Hotkeys | **Ctrl+Alt+1..9** apply presets 1..9 from any program, also while OBS is in front. |
| Follow OBS | Applies the preset linked to the live OBS scene whenever you switch scenes. Pick a scene, then **Link to selected preset**. It only reads the scene name through OBS's websocket server (Tools > WebSocket Server Settings) and never changes OBS. |

### Output (OBS) tab
| Control | What it does |
|---|---|
| Output size | Portrait 1080x1920 (your Whatnot canvas), Landscape 1920x1080, 720p, 4K landscape or portrait. |
| Fit | **Crop to fill** (cuts the edges, no bars), **Fit with bars**, or **Stretch**. |
| Rotate | Auto (follows how you hold the phone) or 0 / 90 / 180 / 270 degrees. |
| Mirror / Flip | Turn the picture left-right / upside-down. |
| Output fps | Frame rate OBS sees. Match OBS. |
| When no phone | What OBS shows if the phone is unplugged: a "waiting" card, the last picture, or black. |

### Extras tab
| Control | What it does |
|---|---|
| Clip length / Save clip now | **Ctrl+Alt+0** or the **Save last 30 s** button saves the last 15/30/60 s of the camera as an MP4 in `Videos\Taco Cam clips` (full phone quality, no re-encoding, upright). |
| Clip / scanner turn | Which way clips and the scanner feed are turned upright. Auto follows how the phone is held. |
| Card scanner feed | The Whatnot card scanner can read Taco Cam's picture directly, without OBS and without JPEG (pick **Taco Cam (direct, full quality)** in the scanner). 1080p is what the scanner wants; it shrinks a 4K picture to 1080p. |
| Pre-show check | When OBS goes live: **Check and warn me** (on by default) runs the pre-show check the moment OBS starts streaming. All good: a short note under the picture. Something off: the check window pops up with a beep. While live it also beeps once if the phone picture stops for 3 seconds. Uses OBS's websocket server only to read whether OBS is streaming. |
| Open Taco Cam when I log in | Starts Taco Cam minimized with Windows. |

The bottom bar's phone battery text turns orange (not charging, under 30%) or red (under 15%), and says when
the charger is unplugged.

### Bottom bar: the iPhone app's 7-day limit
With a free Apple ID the iPhone app stops opening 7 days after you install it. The bottom bar shows
"iPhone app good until ..." and turns orange two days before (red on the last day). Reinstall it with
iloader (`docs/INSTALL_IPHONE.md`) to get another 7 days.

### Pre-show check
The **Pre-show check** button under the picture opens a list of everything that matters before a show, green
when fine, orange or red when not: phone connected by USB, picture coming in, phone camera at 1080p, charger
plugged in, phone not hot, days left on the iPhone app, the "Taco Cam" camera ready for OBS, OBS getting
1920x1080 without a turn (the Whatnot scene turns it), and whether the card scanner is reading. It updates by
itself while open, so you can watch lines turn green as you fix them. Tip: turn on **Do Not Disturb** on the
iPhone during a show: a FaceTime call takes the camera away.

### Phone tab
| Control | What it does |
|---|---|
| Phone screen | **Dim** turns the phone screen black to save battery and heat. Touch the phone to wake it. |
| Connect by | **USB cable** (default) or **Wi-Fi** (type the IP address the phone app shows). |
| Start test phone | Starts a pretend phone on this PC (address 127.0.0.1) so you can try the app without the iPhone. |

### Log tab
The last messages from the program. Useful if you ask for help. The same lines go to `taco-cam.log`.

Your choices are saved automatically in `settings.json` and come back next time. If that file ever gets
damaged, Taco Cam starts with the normal settings and keeps the broken one as `settings.bad.json`.

## Troubleshooting

- **"iPhone found: open Taco Cam on the phone"**: the phone is connected but the app isn't open. Open Taco Cam
  on the iPhone and keep it on screen.
- **"Searching for iPhone on USB" for a long time**: check the cable (use a data cable), unlock the phone and
  tap **Trust This Computer** when asked, and make sure iTunes / Apple Devices is installed.
- **The app was working and now won't open on the iPhone (about 7 days later)**: apps installed with a free
  Apple ID expire after 7 days. Plug in the phone and install the app again with iloader (see
  `docs/INSTALL_IPHONE.md`).
- **OBS doesn't list "Taco Cam"**: run `pc\vcam\Install Taco Cam camera.bat` (Yes to the Windows question) and
  restart OBS.
- **Picture is sideways or upside down**: Output tab > Rotate, or hold the phone steadier and leave Rotate on Auto.
- **Picture is laggy or choppy**: lower Resolution or Bitrate, turn Stabilization off, use the USB cable
  instead of Wi-Fi.
- **Phone is warm**: use **Dim** on the Phone tab, lower to 1080p/30, keep it charging and out of the sun.
- **"Another app on the iPhone took the camera"**: FaceTime or another camera app is using it. Close that app
  and open Taco Cam again. Do Not Disturb during shows prevents it.
- **Taco Cam says it is already running**: look for its window in the taskbar.
- **The window won't open at all**: double-click `Taco Cam (console).bat` to see the error, and check
  `taco-cam.log`. A message about packages means step 1 of the setup needs to be run.

## For the curious

`pc/tacocam/` is the PC program (`app.py` is this window, `engine.py` does the connection, decoding and
virtual camera). `ios/` is the iPhone app. `CONTRACT.md` describes how they talk to each other. Tests:
`python -m pytest pc/tests -q`.

## License

MIT (see `LICENSE`). The virtual camera files in `pc/vcam/` are the Unity Capture DirectShow filter by
Bernhard Schelling, also MIT: see `pc/vcam/LICENSE-UnityCapture.txt`.
