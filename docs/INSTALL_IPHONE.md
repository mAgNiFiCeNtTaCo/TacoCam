# Put Taco Cam on your iPhone

Taco Cam is our own app, so it is not in the App Store. You put it on the phone yourself with a free
program called **iloader**, using an Apple ID. You do this once, and then again every 7 days
(see "The 7-day refresh" below).

(Until October 2026 this guide used Sideloadly. Since Apple changed its sign-in on 2026-10-21, Sideloadly's
login fails with error **-80046**. iloader works.)

What you need:

- Your iPhone (iPhone 11 or newer) and its USB cable.
- This PC, with Apple's phone driver (iTunes or Apple Devices from the Microsoft Store).
- The app file: `dist\TacoCam.ipa` in the Webcam folder (from the GitHub build).
- An Apple ID (email + password). A free one is fine, and it does **not** have to be the one signed in on
  the phone. Have a device signed in with that Apple ID nearby: the 6-digit sign-in code appears there
  (or comes by text to its phone number).

## 1. Install iloader (once)

1. Download it only from **https://iloader.app** or its official releases page,
   https://github.com/nab138/iloader/releases (the Windows file is `iloader-windows-x64.exe`).
2. Run it. Windows may say **"Windows protected your PC"** (it is a free tool without a paid Microsoft
   certificate): click **More info**, then **Run anyway**, and click through the installer.

## 2. Plug in the iPhone

1. Unlock the iPhone and plug it into the PC with the cable.
2. If the iPhone asks **"Trust This Computer?"**, tap **Trust** and type your phone passcode.

## 3. Put the app on the phone

1. Open iloader and sign in with the Apple ID. Type the 6-digit code when Apple asks.
2. Choose **Import IPA** and pick `dist\TacoCam.ipa` from the Webcam folder.
3. Wait until it says it is done. The orange Taco Cam icon is now on the iPhone.

Your password goes to Apple (iloader uses it to make the free signing certificate). Don't click Start /
sign in over and over if it fails: repeated failed sign-ins can lock the Apple ID for a while.

## 4. Allow the app on the iPhone (once)

The first time, the iPhone does not open apps from a personal Apple ID until you say so:

1. On the iPhone open **Settings > General > VPN & Device Management**.
2. Under "Developer App", tap the Apple ID email, then tap **Trust "email"** and **Trust** again.
   (The phone needs Wi-Fi or mobile data for this.)

**Developer Mode** (needed on iOS 16 and newer):

1. Open **Settings > Privacy & Security**, scroll all the way down, tap **Developer Mode**.
2. Turn it on and tap **Restart**. After the restart, tap **Turn On** and type your passcode.

(If you don't see "Developer Mode" yet, try to open Taco Cam once first; the menu then appears.)

## 5. First start

1. Open **Taco Cam** on the iPhone.
2. When it asks for the **camera**, tap **Allow**. (Without it there is no picture.)
3. If it asks about the **local network**, tap **Allow**. That is only for the Wi-Fi mode; the USB
   cable works either way.
4. Leave the cable plugged in and start **Taco Cam on the PC**. The phone says
   "Connected: 30 fps, ..." and the PC shows the picture.

On the phone screen:

- **0.5x / 1x / 2x / 3x** buttons switch lenses (0.5x is the ultra-wide). Pinch to zoom in between.
- **Flip** switches between the back and front camera.
- **Light** turns the flashlight on or off (back camera only).
- **Dim** turns the screen black so the phone stays cooler and saves battery. Tap the black screen to
  wake it. The video keeps going.
- **Settings** has the same controls as the PC (resolution, frame rate, focus, exposure, anti-flicker,
  white balance, ...). Changes show up on the PC right away. At the bottom it shows when this copy stops
  opening.
- Tap the picture to focus on that spot.

Keep Taco Cam open on the phone while you use it. If you switch to another app or lock the phone,
the camera stops and the PC tells you to open Taco Cam again.

## The 7-day refresh

With a **free** Apple ID, Apple lets a self-installed app run for **7 days**. After that, Taco Cam
does not open any more (it just closes).

- The **PC window** shows the date at the bottom ("iPhone app good until ...") and turns it orange two
  days before the end. The **phone** shows an orange line too.
- To refresh: plug in the phone, open iloader, **Import IPA** with the same `TacoCam.ipa` (step 3).
  Your settings are kept. Each reinstall starts a new 7 days.

With a **paid** Apple Developer account (99 USD a year) the app keeps working for a whole year.

## If something goes wrong

- **"Unable to Verify App" / the app closes right away**: do step 4 again (trust the developer), or the
  7 days are over: do step 3 again.
- **iloader does not see the iPhone**: unlock the phone, unplug and plug it back in, tap Trust. Make sure
  iTunes or Apple Devices is installed.
- **Black picture on the phone**: Settings > Taco Cam > turn Camera on.
- **The PC says "iPhone found: open Taco Cam on the phone"**: open Taco Cam on the phone and keep it in
  front.
- **Sign-in fails**: wait a few minutes before trying again, and check the code went to a device with the
  same Apple ID.
