# Put Taco Cam on your iPhone

Taco Cam is our own app, so it is not in the App Store. You put it on the phone yourself with a free
program called **Sideloadly**, using your normal Apple ID. You do this once, and then again every 7 days
(see "The 7-day refresh" below).

What you need:

- Your iPhone (iPhone 11 or newer) and its USB cable.
- This PC. Apple's phone drivers ("Apple Mobile Device Support") are already installed.
- The app file: `D:\ClaudeProjects\Webcam\dist\TacoCam.ipa`.
- Your Apple ID (email + password). A free one is fine.

## 1. Install Sideloadly (once)

1. Go to **https://sideloadly.io** and download the Windows version.
2. Run the installer and click through it. Open Sideloadly when it is done.

## 2. Plug in the iPhone

1. Unlock the iPhone and plug it into the PC with the cable.
2. If the iPhone asks **"Trust This Computer?"**, tap **Trust** and type your phone passcode.
3. In Sideloadly, your iPhone's name now shows at the top (the "iDevice" box).

## 3. Put the app on the phone

1. Drag `D:\ClaudeProjects\Webcam\dist\TacoCam.ipa` onto the big Sideloadly window (or click the IPA
   icon and pick the file).
2. Type your Apple ID email in the "Apple account" box.
3. Click **Start**. Type your Apple ID password when Sideloadly asks. If you get a code on another
   Apple device or by text, type that code too.
4. Wait until it says **Done**. The orange Taco Cam icon is now on the iPhone.

Your password goes only to Apple (Sideloadly uses it to make the free signing certificate).

## 4. Allow the app on the iPhone (once)

The first time, the iPhone does not open apps from a personal Apple ID until you say so:

1. On the iPhone open **Settings > General > VPN & Device Management**.
2. Under "Developer App", tap your Apple ID email, then tap **Trust "your email"** and **Trust** again.

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
- **Settings** has the same controls as the PC (resolution, frame rate, focus, exposure, white
  balance, ...). Changes show up on the PC right away.
- Tap the picture to focus on that spot.

Keep Taco Cam open on the phone while you use it. If you switch to another app or lock the phone,
the camera stops and the PC tells you to open Taco Cam again.

## The 7-day refresh

With a **free** Apple ID, Apple lets a self-installed app run for **7 days**. After that, Taco Cam
does not open any more (it just closes). To fix it, do step 3 again: plug in the phone, drag
`TacoCam.ipa` into Sideloadly, click Start. Your settings are kept.

Easier: in Sideloadly, turn on **auto-refresh** (the option next to Start, or right-click the app in
Sideloadly's list). Then Sideloadly refreshes the app by itself while the PC is on and the phone is on
the same Wi-Fi or plugged in.

With a **paid** Apple Developer account (99 USD a year) the app keeps working for a whole year.

## If something goes wrong

- **"Unable to Verify App" / the app closes right away**: do step 4 again (trust the developer), or the
  7 days are over: do step 3 again.
- **Sideloadly does not see the iPhone**: unlock the phone, unplug and plug it back in, tap Trust.
- **Black picture on the phone**: Settings > Taco Cam > turn Camera on.
- **The PC says "iPhone found, but Taco Cam is not open"**: open Taco Cam on the phone and keep it in
  front.
- **Sideloadly says the Apple ID needs an app-specific password or 2-factor code**: type the 6-digit code
  that appears on your other Apple device, or make an app-specific password at appleid.apple.com.
