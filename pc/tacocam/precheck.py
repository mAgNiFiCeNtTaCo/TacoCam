"""Pre-show check: is everything ready to go live? Turns eng.get_status() + the settings into a list of
(level, text) lines for the check window, which opens from its button or by itself when OBS starts streaming.

Pure functions, no Tk.
"""
from datetime import datetime, timezone

OK, INFO, WARN, BAD = "ok", "info", "warn", "bad"

# The Whatnot scene takes a 1920x1080 landscape picture and turns it 90 degrees itself.
SHOW_OUTPUT = "1920x1080"
SHOW_ROTATE = 0

# STATE `interrupted` (why iOS paused the phone camera) in plain words.
INTERRUPTED = {
    "background": "Taco Cam on the iPhone is in the background: open it again",
    "other_app": "Another app on the iPhone took the camera (FaceTime or a video call): close it, open Taco Cam",
    "split_screen": "Split screen / slide over paused the iPhone camera: close the other app",
    "too_hot": "The iPhone is too hot and iOS paused its camera: let it cool down",
    "other": "iOS paused the iPhone camera",
}


def interruption_text(reason):
    if not reason:
        return ""
    return INTERRUPTED.get(reason, INTERRUPTED["other"])


def paused_reason(phone):
    """Why the phone sends no picture although it is connected, or None."""
    phone = phone or {}
    if phone.get("app_active") is False:
        return "background"
    return phone.get("interrupted") or None


def hours_left(expires, now=None):
    """Hours until the sideloaded iPhone app stops opening (STATE app_expires, ISO 8601), or None."""
    if not isinstance(expires, str):
        return None
    try:
        when = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (when - now).total_seconds() / 3600


def run_checks(st, settings, now=None, feed_in_use=False):
    """[(level, text), ...] in a fixed order. level: ok / info / warn / bad."""
    st = st or {}
    phone = st.get("phone") or {}
    ps = phone.get("settings") or {}
    pc = (settings or {}).get("pc") or {}
    out = []
    add = lambda level, text: out.append((level, text))  # noqa: E731

    link = st.get("link")
    if link != "connected" or not phone:
        add(BAD, "iPhone found, but Taco Cam isn't open on it: open the app on the phone" if link == "no_app"
            else "No iPhone connected: plug in the USB cable and open Taco Cam on the phone")
    else:
        if st.get("transport") == "wifi":
            add(WARN, "Connected by Wi-Fi: the USB cable is steadier for a show")
        else:
            add(OK, "iPhone connected by USB")
        fps = st.get("fps_in") or 0
        if fps < 1:
            add(BAD, interruption_text(paused_reason(phone))
                or "Connected, but no picture is coming from the iPhone camera")
        else:
            add(OK, f"Picture is coming in ({fps:.0f} fps)")
        if phone.get("error"):
            add(WARN, "The iPhone says: " + str(phone["error"]))

        res = ps.get("resolution")
        if res == "1080p":
            add(OK, "Phone camera at 1080p (what the card scanner is tuned for)")
        elif res:
            add(WARN, f"Phone camera at {res.upper()}: the card scanner works best at 1080p (Camera tab)")

        bat = phone.get("battery")
        pct = f"{round(bat * 100)}%" if isinstance(bat, (int, float)) and bat > 0 else "level unknown"
        if phone.get("charging"):
            add(OK, f"Phone is charging ({pct})")
        else:
            add(BAD if isinstance(bat, (int, float)) and 0 < bat <= 0.30 else WARN,
                f"Phone is NOT charging ({pct}): plug in the charger")

        th = phone.get("thermal")
        if th == "critical":
            add(BAD, "Phone is VERY hot: let it cool down before the show")
        elif th == "serious":
            add(WARN, "Phone is hot: it lowers the frame rate (Dim the phone screen, take off the case)")
        else:
            add(OK, "Phone temperature is fine")

        hours = hours_left(phone.get("app_expires"), now)
        if hours is not None:
            if hours <= 12:
                add(BAD, f"The iPhone app stops opening in {max(0, round(hours))} h: reinstall it with iloader first")
            elif hours <= 48:
                add(WARN, f"The iPhone app stops opening in {round(hours)} h: reinstall it with iloader after the show")
            else:
                add(OK, f"The iPhone app is good for {hours / 24:.0f} more days")

    vc = st.get("vcam")
    name = pc.get("vcam_name", "Taco Cam")
    if vc == "running" and st.get("vcam_backend") != "obs":
        add(OK, f'Virtual camera "{name}" is ready for OBS')
    elif vc == "running":
        add(WARN, 'Using OBS Virtual Camera: don\'t press "Start Virtual Camera" in OBS')
    elif vc == "not_installed":
        add(BAD, f'The "{name}" camera is not installed (button at the bottom right)')
    else:
        add(BAD, "Virtual camera problem: " + (st.get("error") or "see the Log tab"))

    output, rotate = pc.get("output"), pc.get("rotate")
    if output == SHOW_OUTPUT and rotate == SHOW_ROTATE:
        add(OK, f"OBS gets {SHOW_OUTPUT}, not turned (the Whatnot scene turns it)")
    else:
        add(WARN, f"OBS gets {output}, turn {rotate}: the Whatnot scene expects {SHOW_OUTPUT} with turn "
                  f"{SHOW_ROTATE} (Output tab)")

    if feed_in_use:
        add(OK, "The card scanner is reading the picture")
    else:
        add(INFO, "The card scanner isn't reading the picture (fine if you don't use it)")
    if ps and ps.get("screen") != "dim":
        add(INFO, "Tip: Dim the phone screen (Phone tab) to save battery and heat")
    add(INFO, "Turn on Do Not Disturb on the iPhone: a FaceTime call would take the camera away")
    return out


def problems(results):
    """The warn / bad lines only."""
    return [(lvl, text) for lvl, text in results if lvl in (WARN, BAD)]


def worst(results):
    levels = [lvl for lvl, _ in results]
    for lvl in (BAD, WARN):
        if lvl in levels:
            return lvl
    return OK
