"""Taco Cam PC window (tkinter). Talks to the Engine only through the API in CONTRACT section 6."""
import collections
import ctypes
import logging
import os
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from . import presets as P
from . import settings as S
from .hotkeys import GlobalHotkeys
from .obsfollow import ObsFollower
from .ui_widgets import (ACCENT, BAD, BG, FG, GOOD, MUTED, WARN, Choice, Combo, Control, Slider,
                         Switch, Tooltip, apply_theme)

ROOT_DIR = S.ROOT
PC_DIR = ROOT_DIR / "pc"
INSTALL_BAT = PC_DIR / "vcam" / "Install Taco Cam camera.bat"
FAKE_PHONE = PC_DIR / "tools" / "fake_phone.py"
LOG_PATH = ROOT_DIR / "taco-cam.log"

PREVIEW_MS = 50          # ~20 fps
STATUS_MS = 250
SAVE_DELAY_MS = 600

OUTPUT_CHOICES = [
    ("1080x1920", "Portrait 1080x1920 (your Whatnot canvas)"),
    ("1920x1080", "Landscape 1920x1080"),
    ("1280x720", "Landscape 720p (1280x720)"),
    ("3840x2160", "4K landscape (3840x2160)"),
    ("2160x3840", "4K portrait (2160x3840)"),
]
FPS_CHOICES = [(24, "24"), (25, "25"), (30, "30"), (60, "60")]
ALL_RES = ["720p", "1080p", "4k"]
NO_PHONE_RANGES = {"min_zoom": 0.5, "max_zoom": 15.0, "iso": (32, 3072), "shutter": (0.00002, 0.5)}


# --------------------------------------------------------------------------- helpers

def acquire_single_instance(name="Local\\TacoCamPC"):
    """Named mutex: returns a handle (keep it alive), or None when another copy already runs."""
    if os.name != "nt":
        return True
    k = ctypes.windll.kernel32
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    handle = k.CreateMutexW(None, False, name)
    if k.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle or True


def fmt_zoom(v):
    return f"{v:.1f}x" if v < 10 else f"{v:.0f}x"


def fmt_shutter(s):
    if s >= 0.4:
        return f"{s:.1f} s"
    return f"1/{max(1, round(1 / s))}"


def describe_expiry(expires, now=None):
    """(text, color) for when the sideloaded iPhone app stops opening (STATE app_expires, ISO 8601)."""
    if not isinstance(expires, str):
        return "", MUTED
    try:
        when = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return "", MUTED
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    hours = (when - now).total_seconds() / 3600
    local = when.astimezone().strftime("%a %b %d, %I:%M %p").replace(" 0", " ")
    if hours <= 0:
        return "The iPhone app has expired: reinstall it with iloader (it won't open until you do)", BAD
    if hours <= 48:
        left = f"{max(1, round(hours))} h" if hours < 24 else "2 days"
        return f"iPhone app stops opening in {left} ({local}): reinstall it with iloader", (BAD if hours < 12 else WARN)
    return f"iPhone app good until {local}", MUTED


def describe_status(st, vcam_name="Taco Cam", now=None):
    """Turns eng.get_status() into the texts for the status bar (pure function, tested)."""
    st = st or {}
    phone = st.get("phone") or {}
    link = st.get("link")
    transport = st.get("transport")
    wifi = transport == "wifi"
    way = "Wi-Fi" if wifi else "USB"
    name = st.get("device_name") or "iPhone"
    if link == "connected":
        conn, color = f"Connected to {name} by {way}", GOOD
    elif link == "no_app":
        conn, color = "iPhone found: open Taco Cam on the phone", WARN
    elif link == "connecting":
        conn, color = f"Connecting to {name}...", WARN
    elif link == "error":
        conn, color = "Problem: " + (st.get("error") or "can't reach the iPhone"), BAD
    else:
        conn, color = ("Searching for iPhone on Wi-Fi..." if wifi else "Searching for iPhone on USB..."), MUTED
    out = {"conn": conn, "conn_color": color}

    bat = phone.get("battery")
    if isinstance(bat, (int, float)):
        out["battery"] = f"Phone battery {round(bat * 100)}%" + (" (charging)" if phone.get("charging") else "")
    else:
        out["battery"] = ""
    th = phone.get("thermal")
    if th in ("serious", "critical"):
        out["thermal"] = ("Phone is HOT: it lowers the frame rate. Let it cool down."
                          if th == "serious" else "Phone is VERY HOT: stop and let it cool down!")
        out["thermal_color"] = BAD if th == "critical" else WARN
    else:
        out["thermal"], out["thermal_color"] = "", MUTED
    problem = phone.get("error")
    if phone and phone.get("app_active") is False:
        problem = "Taco Cam on the phone went to the background: open it again"
    out["phone_problem"] = problem or ""
    out["expiry"], out["expiry_color"] = describe_expiry(phone.get("app_expires"), now)

    if link == "connected":
        rtt = st.get("rtt_ms")
        stream = phone.get("stream") or {}
        sz = f"{stream.get('width')}x{stream.get('height')} {str(stream.get('codec', '')).upper()}  |  " \
            if stream.get("width") else ""
        out["stats"] = (f"{sz}In {st.get('fps_in', 0):.0f} fps  |  Out {st.get('fps_out', 0):.0f} fps  |  "
                        f"{st.get('bitrate_mbps', 0):.1f} Mbps  |  RTT {'-' if rtt is None else f'{rtt:.0f}'} ms  |  "
                        f"Dropped {st.get('dropped', 0)}")
    else:
        out["stats"] = ""

    vc = st.get("vcam")
    out["vcam_install"] = False
    if vc == "running":
        out["vcam"], out["vcam_color"] = f'Virtual camera "{vcam_name}" ready in OBS', GOOD
        if st.get("vcam_backend") == "obs":
            out["vcam"] = ('Using OBS Virtual Camera (do not also press "Start Virtual Camera" in OBS; '
                           'install the Taco Cam camera to avoid this)')
            out["vcam_color"] = WARN
    elif vc == "not_installed":
        out["vcam"], out["vcam_color"] = f'Virtual camera "{vcam_name}" is not installed', BAD
        out["vcam_install"] = True
    elif vc == "error":
        out["vcam"], out["vcam_color"] = "Virtual camera problem: " + (st.get("error") or "see the Log tab"), BAD
    else:
        out["vcam"], out["vcam_color"] = "Virtual camera starting...", MUTED
    return out


class TextField(Control):
    """Entry + Apply button; commits on Enter / Apply / leaving the box."""

    def __init__(self, parent, title, hint="", **kw):
        super().__init__(parent, title, hint, **kw)
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self.body, textvariable=self.var, width=22)
        self.entry.pack(side="left")
        self.btn = ttk.Button(self.body, text="Apply", command=self.commit)
        self.btn.pack(side="left", padx=(6, 0))
        self.entry.bind("<Return>", lambda _e: self.commit())
        self.entry.bind("<FocusOut>", lambda _e: self.commit())
        self._committed = ""

    def commit(self):
        v = self.var.get().strip()
        if v != self._committed:
            self._committed = v
            self.user_changed(v)

    def value(self):
        return self.var.get().strip()

    def show(self, value):
        self._silent = True
        self.var.set(value or "")
        self._committed = (value or "").strip()
        self._silent = False

    def select(self, value):
        self.var.set(value)
        self.commit()

    def _apply_enabled(self):
        st = ["!disabled"] if self.enabled else ["disabled"]
        self.entry.state(st)
        self.btn.state(st)


# --------------------------------------------------------------------------- the window

class App:
    def __init__(self, root, engine_factory, settings_path=None, autostart=True,
                 install_bat=None, fake_phone=None):
        self.root = root
        self.settings_path = Path(settings_path) if settings_path else S.SETTINGS_PATH
        self.install_bat = Path(install_bat) if install_bat else INSTALL_BAT
        self.fake_phone = Path(fake_phone) if fake_phone else FAKE_PHONE
        self.logger = logging.getLogger("tacocam")
        self.log_lines = collections.deque(maxlen=300)
        self._log_shown = 0
        self.settings, note = S.load(self.settings_path)
        self.ctl = {}
        self.zoom_buttons = []
        self._zoom_lenses = None
        self._save_job = None
        self._closing = False
        self._photo = None
        self._img_box = None
        self._focus_job = None
        self._status = {}
        self._test_proc = None
        self.preview_frames = 0
        self.last_status_text = {}
        self.hotkeys = None
        self.obs = None
        self._obs_scene_seen = None
        self.preset_buttons = []
        self._active_preset = None
        self._expiry_logged = None
        self.lock_focus = tk.BooleanVar(master=root, value=True)
        self.lock_exposure = tk.BooleanVar(master=root, value=False)
        self.lock_colors = tk.BooleanVar(master=root, value=True)

        self.root.title("Taco Cam")
        apply_theme(root)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.engine = engine_factory(S.deep_update(S.default_settings(), self.settings), self.log)
        if note:
            self.log(note)
            self.set_hint(note)
        for path, ctl in self.ctl.items():
            v = S.get_path(self.settings, path)
            if v is not None:
                ctl.show(v)
        self.ctl["phone.exposure.iso"].show(100)          # starting points for manual exposure
        self.ctl["phone.exposure.shutter_s"].show(1 / 60)
        self.update_enabled()
        if autostart:
            self.start()

    # ---- lifecycle
    def start(self):
        self.engine.start()
        self._sync_background()
        self._preview_job = self.root.after(PREVIEW_MS, self._preview_tick)
        self._status_job = self.root.after(STATUS_MS, self._status_tick)

    def log(self, line):
        line = str(line)
        self.log_lines.append(line)
        try:
            self.logger.info(line)
        except Exception:
            pass

    def close(self):
        if self._closing:
            return
        self._closing = True
        for job in ("_preview_job", "_status_job", "_save_job", "_focus_job"):
            j = getattr(self, job, None)
            if j:
                try:
                    self.root.after_cancel(j)
                except tk.TclError:
                    pass
        self.flush_save()
        try:
            self.root.withdraw()
        except tk.TclError:
            pass
        self.stop_test_phone()
        for helper in (self.hotkeys, self.obs):
            if helper is not None:
                try:
                    helper.stop()
                except Exception:
                    self.logger.exception("stopping %s failed", helper)
        try:
            self.engine.stop()
        except Exception as e:  # keep closing no matter what
            self.logger.exception("engine.stop failed: %s", e)
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ---- building the window
    def _build(self):
        r = self.root
        r.minsize(1100, 700)
        w, h = min(1280, r.winfo_screenwidth() - 40), min(800, r.winfo_screenheight() - 80)
        r.geometry(f"{w}x{h}+{max(0, (r.winfo_screenwidth() - w) // 2)}+{max(0, (r.winfo_screenheight() - h) // 3)}")
        r.columnconfigure(0, weight=1)
        r.rowconfigure(0, weight=1)
        main = ttk.Frame(r, style="Dark.TFrame")
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        # left: preview + zoom bar
        left = ttk.Frame(main, style="Dark.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(left, bg="#000000", highlightthickness=0, width=560, height=520)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Button-1>", self._canvas_click)
        self.canvas.bind("<MouseWheel>", self._canvas_wheel)
        Tooltip(self.canvas, "Click the picture to focus there. Mouse wheel = zoom.", delay=900)
        self._placeholder = self.canvas.create_text(0, 0, text="Waiting for the iPhone...", fill=MUTED,
                                                    font=("Segoe UI", 14))
        self.canvas.bind("<Configure>", self._canvas_resized)
        self.hint_label = ttk.Label(left, text="", style="StatusMuted.TLabel")
        self.hint_label.grid(row=3, column=0, sticky="w", pady=(2, 0))
        self.preset_bar = ttk.Frame(left, style="Dark.TFrame")
        self.preset_bar.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        zoombar = ttk.Frame(left, style="Dark.TFrame")
        zoombar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        zoombar.columnconfigure(1, weight=1)
        self.zoom_btn_frame = ttk.Frame(zoombar, style="Dark.TFrame")
        self.zoom_btn_frame.grid(row=0, column=0, sticky="w")
        zs = Slider(zoombar, "", 0.5, 15.0, fmt=fmt_zoom, step=0.1, log=True, label_width=0,
                    hint="Zoom. 0.5x is the ultra-wide lens (zoomed out).")
        zs.configure(style="Dark.TFrame")
        zs.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self._register("phone.zoom", zs)
        self._rebuild_zoom_buttons([0.5, 1.0, 3.0])

        # right: tabs
        right = ttk.Frame(main, style="Dark.TFrame")
        right.grid(row=0, column=1, sticky="ns", padx=(4, 8), pady=8)
        self.tabs = ttk.Notebook(right, width=520)
        self.tabs.pack(fill="both", expand=True)
        self._tab_camera()
        self._tab_image()
        self._tab_presets()
        self._tab_output()
        self._tab_phone()
        self._tab_log()

        # status bar
        bar = ttk.Frame(r, style="Dark.TFrame")
        bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        bar.columnconfigure(3, weight=1)
        self.conn_label = ttk.Label(bar, text="", style="Status.TLabel", font=("Segoe UI", 10, "bold"))
        self.conn_label.grid(row=0, column=0, sticky="w")
        self.battery_label = ttk.Label(bar, text="", style="StatusMuted.TLabel")
        self.battery_label.grid(row=0, column=1, sticky="w", padx=(18, 0))
        self.thermal_label = ttk.Label(bar, text="", style="Status.TLabel")
        self.thermal_label.grid(row=0, column=2, sticky="w", padx=(18, 0))
        self.stats_label = ttk.Label(bar, text="", style="StatusMuted.TLabel")
        self.stats_label.grid(row=1, column=0, columnspan=3, sticky="w")
        self.expiry_label = ttk.Label(bar, text="", style="Status.TLabel")
        self.expiry_label.grid(row=2, column=0, columnspan=3, sticky="w")
        vc = ttk.Frame(bar, style="Dark.TFrame")
        vc.grid(row=0, column=3, rowspan=2, sticky="e")
        self.vcam_label = ttk.Label(vc, text="", style="Status.TLabel")
        self.vcam_label.pack(side="left")
        self.install_btn = ttk.Button(vc, text="Install virtual camera", style="Accent.TButton",
                                     command=self.install_vcam)
        self.install_btn.pack(side="left", padx=(8, 0))
        self.install_btn.pack_forget()
        Tooltip(self.install_btn, "Installs the \"Taco Cam\" camera so OBS can see it (asks for admin once).")

    def _page(self, title):
        f = ttk.Frame(self.tabs, padding=(12, 10))
        self.tabs.add(f, text=title)
        return f

    def _register(self, path, ctl):
        ctl.path = path
        ctl.on_change = self._user_changed
        self.ctl[path] = ctl
        return ctl

    def _add(self, page, path, ctl, pady=3):
        self._register(path, ctl)
        ctl.pack(fill="x", pady=pady)
        return ctl

    def _head(self, page, text):
        ttk.Label(page, text=text, style="Head.TLabel").pack(anchor="w", pady=(10, 2))

    def _tab_camera(self):
        p = self._page("Camera")
        self._add(p, "phone.camera", Choice(p, "Camera", [("back", "Back"), ("front", "Front")],
                  hint="Back camera has the 0.5x ultra-wide; front is the selfie camera."))
        self._add(p, "phone.resolution", Choice(p, "Resolution", [("720p", "720p"), ("1080p", "1080p"), ("4k", "4K")],
                  hint="Picture size from the phone. 1080p is plenty for a stream; 4K needs a strong PC and USB."))
        self._add(p, "phone.fps", Choice(p, "Frame rate (fps)", FPS_CHOICES,
                  hint="Frames per second from the phone. Only rates the camera supports at this resolution."))
        self._add(p, "phone.codec", Choice(p, "Video codec", [("h264", "H.264"), ("hevc", "HEVC (H.265)")],
                  hint="HEVC looks better at the same Mbps; H.264 is the safe choice."))
        self._add(p, "phone.bitrate_mbps", Slider(p, "Bitrate", 2, 80, step=1, fmt=lambda v: f"{v:g} Mbps",
                  hint="Higher = sharper picture but more data. 16 is good for 1080p over USB."))
        ttk.Label(p, text="Resolution and fps choices follow what the selected camera can do.",
                  style="Muted.TLabel").pack(anchor="w", pady=(12, 0))

    def _tab_image(self):
        p = self._page("Image")
        self._head(p, "Focus")
        self._add(p, "phone.focus.mode", Choice(p, "Focus", [("auto", "Auto"), ("manual", "Manual")],
                  hint="Auto keeps things sharp. Tip: click the preview to focus on a spot."))
        self._add(p, "phone.focus.position", Slider(p, "Focus distance", 0, 1, step=0.01,
                  fmt=lambda v: f"{v:.2f}", hint="Manual focus: 0 = far away, 1 = very close."))
        self._head(p, "Exposure (brightness)")
        self._add(p, "phone.exposure.mode", Choice(p, "Exposure", [("auto", "Auto"), ("manual", "Manual")],
                  hint="Auto adjusts brightness for you. Manual lets you set ISO and shutter."))
        self._add(p, "phone.exposure.bias", Slider(p, "Brightness (EV)", -3, 3, step=0.1,
                  fmt=lambda v: f"{v:+.1f}", hint="Makes the auto picture brighter or darker."))
        self._add(p, "phone.anti_flicker", Choice(p, "Anti-flicker", [("off", "Off"), ("60hz", "60 Hz (US)"), ("50hz", "50 Hz")],
                  hint="Stops LED / fluorescent lights from banding or flickering: the shutter follows the "
                       "mains frequency (60 Hz in the US), brightness stays automatic."))
        self._add(p, "phone.exposure.iso", Slider(p, "ISO", 32, 3072, step=1, log=True, fmt=lambda v: f"{v:.0f}",
                  hint="Manual exposure: higher ISO = brighter but grainier."))
        self._add(p, "phone.exposure.shutter_s", Slider(p, "Shutter", 0.00002, 0.5, log=True, fmt=fmt_shutter,
                  hint="Manual exposure: slower shutter = brighter but blurrier. 1/60 is normal at 30 fps."))
        self._head(p, "White balance (color)")
        self._add(p, "phone.white_balance.mode", Choice(p, "White balance", [("auto", "Auto"), ("manual", "Manual")],
                  hint="Manual fixes the colors so they don't shift when you move."))
        self._add(p, "phone.white_balance.temperature", Slider(p, "Temperature", 2500, 8000, step=50,
                  fmt=lambda v: f"{v:.0f} K", hint="Low = cooler (blue), high = warmer (orange). Room light is ~4000-5000 K."))
        self._add(p, "phone.white_balance.tint", Slider(p, "Tint", -150, 150, step=1,
                  fmt=lambda v: f"{v:+.0f}", hint="Green to magenta fine tuning."))
        self._head(p, "Extras")
        self._add(p, "phone.torch", Slider(p, "Torch (light)", 0, 1, step=0.05,
                  fmt=lambda v: "Off" if v <= 0 else f"{round(v * 100)}%", hint="The phone's flashlight, back camera only."))
        self._add(p, "phone.stabilization", Choice(p, "Stabilization",
                  [("off", "Off"), ("standard", "Standard"), ("cinematic", "Cinematic")],
                  hint="Steadies a handheld phone but adds delay. Leave off on a tripod."))
        self._add(p, "phone.hdr", Switch(p, "HDR video", "Use HDR", hint="Better highlights where the camera supports it."))
        ttk.Button(p, text="Reset image settings", command=self.reset_image).pack(anchor="w", pady=(12, 0))

    def _tab_output(self):
        p = self._page("Output (OBS)")
        ttk.Label(p, text="What OBS gets from the \"Taco Cam\" camera.", style="Muted.TLabel").pack(anchor="w")
        self._add(p, "pc.output", Combo(p, "Output size", OUTPUT_CHOICES,
                  hint="Pick the size of your OBS canvas. Portrait 1080x1920 is the Whatnot canvas."))
        self._add(p, "pc.fit", Choice(p, "Fit", [("crop", "Crop to fill"), ("fit", "Fit with bars"), ("stretch", "Stretch")],
                  hint="How the phone picture fills the output: cut the edges, add black bars, or stretch."))
        self._add(p, "pc.rotate", Choice(p, "Rotate", [("auto", "Auto"), (0, "0"), (90, "90"), (180, "180"), (270, "270")],
                  hint="Auto turns the picture upright from how the phone is held. Or pick the turn in degrees."))
        self._add(p, "pc.mirror", Switch(p, "Mirror", "Left-right", hint="Flip the picture left to right."))
        self._add(p, "pc.flip", Switch(p, "Flip", "Upside-down", hint="Flip the picture top to bottom."))
        self._add(p, "pc.fps_out", Choice(p, "Output fps", FPS_CHOICES,
                  hint="Frame rate of the camera OBS sees. Match your OBS frame rate."))
        self._add(p, "pc.when_disconnected", Choice(p, "When no phone",
                  [("card", "Waiting card"), ("last", "Last frame"), ("black", "Black")],
                  hint="What OBS shows when the phone is unplugged: a card, the frozen last picture, or black."))

    def _tab_phone(self):
        p = self._page("Phone")
        self._add(p, "phone.screen", Switch(p, "Phone screen", "Dim it (saves battery and heat)", on="dim", off="normal",
                  hint="The phone screen goes black with a small status line. Touch the phone to wake it."))
        self._head(p, "Connection")
        self._add(p, "pc.connect", Choice(p, "Connect by", [("usb", "USB cable"), ("wifi", "Wi-Fi")],
                  hint="USB is the most reliable. Wi-Fi needs the phone's IP address (shown in the phone app)."))
        self._add(p, "pc.wifi_host", TextField(p, "Phone IP address",
                  hint="Only for Wi-Fi: the number shown on the phone, like 192.168.1.23. 127.0.0.1 = the test phone."))
        self._head(p, "Try without the iPhone")
        row = ttk.Frame(p)
        row.pack(fill="x", pady=3)
        self.test_btn = ttk.Button(row, text="Start test phone", command=self.toggle_test_phone)
        self.test_btn.pack(side="left")
        Tooltip(self.test_btn, "Starts a pretend phone on this PC so you can try the app without the iPhone.")
        self.test_label = ttk.Label(row, text="", style="Muted.TLabel")
        self.test_label.pack(side="left", padx=10)

    def _tab_log(self):
        p = self._page("Log")
        self.log_text = tk.Text(p, height=24, width=60, bg="#15161a", fg=FG, state="disabled", wrap="word",
                                relief="flat", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

    def _tab_presets(self):
        p = self._page("Presets")
        ttk.Label(p, text="Save the picture settings you use often (zoom, focus, exposure, colors, light) and switch "
                          "with one click, with Ctrl+Alt+1..9 (also while OBS is in front), or automatically with "
                          "your OBS scenes. Resolution, fps and bitrate are not part of a preset.",
                  style="Muted.TLabel", wraplength=490, justify="left").pack(anchor="w")
        self.preset_list = tk.Listbox(p, height=9, bg="#15161a", fg=FG, selectbackground=ACCENT, relief="flat",
                                      activestyle="none", font=("Segoe UI", 10), exportselection=False)
        self.preset_list.pack(fill="x", pady=(8, 4))
        self.preset_list.bind("<Double-Button-1>", lambda _e: self.apply_selected_preset())
        for buttons in (
                (("Apply", self.apply_selected_preset, "Use the selected preset now (or double-click it)."),
                 ("Save new...", self.save_preset_new, "Save what the camera does now as a new preset."),
                 ("Update", self.update_selected_preset, "Replace the selected preset with what the camera does now.")),
                (("Rename...", self.rename_selected_preset, "Give the selected preset another name."),
                 ("Delete", self.delete_selected_preset, "Remove the selected preset."))):
            row = ttk.Frame(p)
            row.pack(fill="x", pady=(0, 4))
            for text, cmd, tip in buttons:
                b = ttk.Button(row, text=text, command=cmd)
                b.pack(side="left", padx=(0, 6))
                Tooltip(b, tip)
        self._head(p, "When saving, lock at what the camera uses right now")
        for var, text in ((self.lock_focus, "Focus (stops focus hunting when hands move in front of the camera)"),
                          (self.lock_exposure, "Exposure (keeps shiny foil from changing the brightness)"),
                          (self.lock_colors, "Colors / white balance (keeps colors steady)")):
            ttk.Checkbutton(p, text=text, variable=var).pack(anchor="w")
        self._head(p, "OBS scenes")
        self._add(p, "pc.follow_obs", Switch(p, "Follow OBS", "Switch presets with the live OBS scene",
                  hint="Uses OBS's websocket server (Tools > WebSocket Server Settings) only to read which scene "
                       "is live. Link a preset to a scene below."))
        srow = ttk.Frame(p)
        srow.pack(fill="x", pady=3)
        self.scene_combo = ttk.Combobox(srow, state="readonly", width=28, values=[])
        self.scene_combo.pack(side="left")
        ttk.Button(srow, text="Link to selected preset", command=self.link_scene).pack(side="left", padx=(6, 0))
        ttk.Button(srow, text="Unlink", command=lambda: self.link_scene(unlink=True)).pack(side="left", padx=(6, 0))
        self.obs_label = ttk.Label(p, text="", style="Muted.TLabel")
        self.obs_label.pack(anchor="w")
        self._head(p, "Hotkeys")
        self._add(p, "pc.hotkeys", Switch(p, "Hotkeys", "Ctrl+Alt+1..9 apply presets 1..9",
                  hint="Work in any program, also while OBS or Whatnot is in front."))
        self.hotkey_label = ttk.Label(p, text="", style="Muted.TLabel")
        self.hotkey_label.pack(anchor="w")
        self._refresh_presets()

    # ---- presets
    @property
    def presets(self):
        return self.settings.setdefault("presets", [])

    def _selected_preset(self, quiet=False):
        sel = self.preset_list.curselection()
        if sel and sel[0] < len(self.presets):
            return sel[0]
        if not quiet:
            self.set_hint("Pick a preset in the list first")
        return None

    def _refresh_presets(self, select=None):
        lb = self.preset_list
        lb.delete(0, "end")
        for i, pr in enumerate(self.presets):
            desc = P.describe(pr)
            lb.insert("end", f"{i + 1}   {pr['name']}" + (f"   ({desc})" if desc else ""))
        if select is not None and 0 <= select < len(self.presets):
            lb.selection_set(select)
        for b in self.preset_buttons:
            b.destroy()
        self.preset_buttons = []
        if not self.presets:
            lbl = ttk.Label(self.preset_bar, text="Presets: none yet (save some in the Presets tab)",
                            style="StatusMuted.TLabel")
            lbl.pack(side="left")
            self.preset_buttons.append(lbl)
        for i, pr in enumerate(self.presets):
            b = ttk.Button(self.preset_bar, text=f"{i + 1}  {pr['name']}", style="Zoom.TButton",
                           command=lambda i=i: self.apply_preset(i))
            b.pack(side="left", padx=(0, 6))
            Tooltip(b, f"Ctrl+Alt+{i + 1}. " + P.describe(pr))
            self.preset_buttons.append(b)
        if self._active_preset is not None and self._active_preset >= len(self.presets):
            self._active_preset = None
        self._mark_preset_buttons()

    def _mark_preset_buttons(self):
        for i, b in enumerate(self.preset_buttons):
            if isinstance(b, ttk.Button):
                b.configure(style="ZoomOn.TButton" if i == self._active_preset else "Zoom.TButton")

    def apply_preset(self, i, why=""):
        if not 0 <= i < len(self.presets):
            return
        pr = self.presets[i]
        partial = P.to_partial(pr)
        now = time.monotonic()
        for path, ctl in self.ctl.items():
            if path.startswith("phone."):
                v = S.get_path(partial, path)
                if v is not None:
                    ctl.show(v)
                    ctl.touched_at = now
        self.apply(partial)
        self._active_preset = i
        self._mark_preset_buttons()
        self.set_hint(f"Preset {i + 1}: {pr['name']}" + (f"  ({why})" if why else ""))
        self.log(f"Preset {i + 1} \"{pr['name']}\" applied" + (f" ({why})" if why else ""))

    def apply_selected_preset(self):
        i = self._selected_preset()
        if i is not None:
            self.apply_preset(i)

    def _capture(self):
        live = ((self._status or {}).get("phone") or {}).get("live")
        locks = (self.lock_focus.get(), self.lock_exposure.get(), self.lock_colors.get())
        if any(locks) and not live:
            self.set_hint("The phone isn't reporting its current focus/exposure (connect it, or update the "
                          "iPhone app): saved without locking")
        return P.capture(self.settings["phone"], live, *locks)

    def save_preset_new(self):
        if len(self.presets) >= P.MAX_PRESETS:
            messagebox.showinfo("Taco Cam", f"You can have {P.MAX_PRESETS} presets. Delete or update one first.",
                                parent=self.root)
            return
        name = simpledialog.askstring("Save preset", "Name for this preset (for example: Card close-up):",
                                      parent=self.root, initialvalue=f"Preset {len(self.presets) + 1}")
        if not name or not name.strip():
            return
        self.presets.append({"name": name.strip()[:P.NAME_MAX], "phone": self._capture(), "obs_scene": ""})
        self._active_preset = len(self.presets) - 1
        self._refresh_presets(select=len(self.presets) - 1)
        self.schedule_save()

    def update_selected_preset(self):
        i = self._selected_preset()
        if i is None:
            return
        self.presets[i]["phone"] = self._capture()
        self._active_preset = i
        self._refresh_presets(select=i)
        self.schedule_save()
        self.set_hint(f"Preset {i + 1} updated with the current camera settings")

    def rename_selected_preset(self):
        i = self._selected_preset()
        if i is None:
            return
        name = simpledialog.askstring("Rename preset", "New name:", parent=self.root,
                                      initialvalue=self.presets[i]["name"])
        if name and name.strip():
            self.presets[i]["name"] = name.strip()[:P.NAME_MAX]
            self._refresh_presets(select=i)
            self.schedule_save()

    def delete_selected_preset(self):
        i = self._selected_preset()
        if i is None:
            return
        if not messagebox.askyesno("Taco Cam", f"Delete preset \"{self.presets[i]['name']}\"?", parent=self.root):
            return
        del self.presets[i]
        if self._active_preset == i:
            self._active_preset = None
        elif self._active_preset is not None and self._active_preset > i:
            self._active_preset -= 1
        self._refresh_presets()
        self.schedule_save()

    def link_scene(self, unlink=False):
        i = self._selected_preset()
        if i is None:
            return
        scene = "" if unlink else self.scene_combo.get().strip()
        if not unlink and not scene:
            self.set_hint("Pick an OBS scene first (turn on Follow OBS so the list fills)")
            return
        if scene:
            for other in self.presets:  # one preset per scene
                if other.get("obs_scene") == scene:
                    other["obs_scene"] = ""
        self.presets[i]["obs_scene"] = scene
        self._refresh_presets(select=i)
        self.schedule_save()

    # ---- hotkeys + OBS scene follower (background helpers)
    def _sync_background(self):
        pc = self.settings["pc"]
        if pc.get("hotkeys", True) and self.hotkeys is None:
            self.hotkeys = GlobalHotkeys().start()
            if self.hotkeys.failed:
                self.log("Hotkeys " + ", ".join(f"Ctrl+Alt+{n}" for n in self.hotkeys.failed)
                         + " are already used by another program")
        elif not pc.get("hotkeys", True) and self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = None
        if pc.get("follow_obs") and self.obs is None:
            self.obs = ObsFollower(log=self.log).start()
        elif not pc.get("follow_obs") and self.obs is not None:
            self.obs.stop()
            self.obs = None
            self._obs_scene_seen = None
        self._show_background_status()

    def _show_background_status(self, snap=None):
        if self.hotkeys is None:
            hk = "Hotkeys are off"
        elif self.hotkeys.failed:
            hk = "Ctrl+Alt+" + ", ".join(map(str, self.hotkeys.failed)) + " are taken by another program; the others work"
        else:
            hk = "Ctrl+Alt+1..9 are ready"
        self.hotkey_label.configure(text=hk)
        if self.obs is None:
            text = "Follow OBS is off"
        else:
            snap = snap or self.obs.snapshot()
            if snap["status"] == "connected":
                text = f"Connected to OBS. Live scene: {snap['scene'] or '-'}"
            elif snap["status"] == "error":
                text = f"OBS: {snap['error']} (trying again)"
            else:
                text = "Connecting to OBS..."
        self.obs_label.configure(text=text)

    def _background_tick(self):
        if self.hotkeys is not None:
            for n in self.hotkeys.pressed():
                self.apply_preset(n - 1, f"Ctrl+Alt+{n}")
        snap = None
        if self.obs is not None:
            snap = self.obs.snapshot()
            if list(self.scene_combo.cget("values") or ()) != snap["scenes"]:
                self.scene_combo.configure(values=snap["scenes"])
            scene = snap["scene"]
            if scene and scene != self._obs_scene_seen:
                self._obs_scene_seen = scene
                i = P.for_scene(self.presets, scene)
                if i is not None:
                    self.apply_preset(i, f'OBS scene "{scene}"')
        self._show_background_status(snap)

    # ---- zoom buttons
    def _rebuild_zoom_buttons(self, lenses):
        for b in self.zoom_buttons:
            b.destroy()
        self.zoom_buttons = []
        self._zoom_lenses = list(lenses)
        for z in self._zoom_lenses:
            b = ttk.Button(self.zoom_btn_frame, text=fmt_zoom(z).replace(".0x", "x"), style="Zoom.TButton",
                           command=lambda z=z: self.set_zoom(z))
            b.pack(side="left", padx=(0, 6))
            b.zoom_value = z
            self.zoom_buttons.append(b)
        self._mark_zoom_buttons()

    def _mark_zoom_buttons(self):
        cur = self.ctl["phone.zoom"].value()
        for b in self.zoom_buttons:
            b.configure(style="ZoomOn.TButton" if abs(b.zoom_value - cur) < 0.06 else "Zoom.TButton")

    def set_zoom(self, z):
        self.ctl["phone.zoom"].select(z)

    # ---- user changes -> settings + engine
    def _user_changed(self, path, value):
        partial = S.nest(path, value)
        c = self.ctl
        if path == "phone.exposure.mode" and value == "manual":
            partial["phone"]["exposure"].update(iso=c["phone.exposure.iso"].value(),
                                                shutter_s=c["phone.exposure.shutter_s"].value())
        elif path == "phone.focus.mode" and value == "manual":
            partial["phone"]["focus"]["position"] = c["phone.focus.position"].value()
        elif path == "phone.white_balance.mode" and value == "manual":
            partial["phone"]["white_balance"].update(temperature=c["phone.white_balance.temperature"].value(),
                                                     tint=c["phone.white_balance.tint"].value())
        elif path == "pc.connect" and value == "wifi" and not self.settings["pc"].get("wifi_host"):
            pass  # nothing to connect to yet: the engine waits for an address
        self.apply(partial)
        if path in ("pc.follow_obs", "pc.hotkeys"):
            self._sync_background()
        if path.startswith("phone."):
            self._active_preset = None
            self._mark_preset_buttons()

    def apply(self, partial):
        """Remember + send a partial settings dict."""
        S.deep_update(self.settings, partial)
        try:
            self.engine.update_settings(partial)
        except Exception as e:
            self.log(f"update_settings failed: {e}")
        self.schedule_save()
        self.update_enabled()
        self._mark_zoom_buttons()

    def reset_image(self):
        d = S.DEFAULTS["phone"]
        partial = {"phone": {k: d[k] for k in ("focus", "exposure", "white_balance", "torch", "stabilization", "hdr",
                                               "anti_flicker")}}
        partial = S.deep_update({}, partial)
        for path, ctl in self.ctl.items():
            if path.startswith("phone.") and path not in ("phone.zoom", "phone.camera", "phone.resolution",
                                                         "phone.fps", "phone.codec", "phone.bitrate_mbps",
                                                         "phone.screen"):
                v = S.get_path(S.DEFAULTS, path)
                if v is not None:
                    ctl.show(v)
                ctl.touched_at = time.monotonic()
        self.apply(partial)

    # ---- saving
    def schedule_save(self):
        if self._closing:
            return
        if self._save_job:
            try:
                self.root.after_cancel(self._save_job)
            except tk.TclError:
                pass
        self._save_job = self.root.after(SAVE_DELAY_MS, self.flush_save)

    def flush_save(self):
        if self._save_job:
            try:
                self.root.after_cancel(self._save_job)
            except tk.TclError:
                pass
            self._save_job = None
        if not S.save(self.settings, self.settings_path):
            self.log("Could not write settings.json")

    # ---- what the phone can do
    def camera_caps(self):
        phone = (self._status or {}).get("phone") or {}
        cams = phone.get("cameras") or {}
        return cams.get(self.settings["phone"]["camera"])

    def update_enabled(self):
        """Enable/disable controls from the camera's abilities and the current modes."""
        c, ps = self.ctl, self.settings["phone"]
        cam = self.camera_caps()
        known = cam is not None
        cams = (((self._status or {}).get("phone") or {}).get("cameras")) or {}

        def get(key, default):
            return cam.get(key, default) if known else default

        # camera
        front_ok = cams.get("front", {}).get("available", True) if cams else True
        back_ok = cams.get("back", {}).get("available", True) if cams else True
        c["phone.camera"].set_allowed({v for v, ok in (("back", back_ok), ("front", front_ok)) if ok})
        c["phone.resolution"].set_allowed(set(get("resolutions", ALL_RES)))
        fps_map = get("fps", None)
        fps_ok = None
        if isinstance(fps_map, dict):
            fps_ok = set(fps_map.get(ps["resolution"], [24, 25, 30, 60]))
        c["phone.fps"].set_allowed(fps_ok)
        c["phone.stabilization"].set_allowed(set(get("stabilization", ["off", "standard", "cinematic"])))
        # zoom range + quick buttons
        zmin, zmax = float(get("min_zoom", 0.5)), float(get("max_zoom", 15.0))
        c["phone.zoom"].set_range(zmin, max(zmax, zmin + 0.1))
        lenses = get("lens_zooms", None) or ([0.5, 1.0, 3.0] if not known else [1.0])
        if lenses != self._zoom_lenses:
            self._rebuild_zoom_buttons(lenses)
        # focus
        manual_focus = bool(get("focus_manual", True))
        c["phone.focus.mode"].set_allowed(None if manual_focus else {"auto"})
        self._gate("phone.focus.position", manual_focus and ps["focus"]["mode"] == "manual",
                   "This camera can't focus manually" if not manual_focus else "Switch Focus to Manual first")
        # exposure
        self._gate("phone.exposure.bias", ps["exposure"]["mode"] == "auto", "Only in Auto exposure")
        self._gate("phone.anti_flicker", ps["exposure"]["mode"] == "auto", "Only in Auto exposure")
        for k in ("phone.exposure.iso", "phone.exposure.shutter_s"):
            self._gate(k, ps["exposure"]["mode"] == "manual", "Only in Manual exposure")
        iso = get("iso_range", None)
        if iso and iso[1] > iso[0]:
            c["phone.exposure.iso"].set_range(float(iso[0]), float(iso[1]))
        sh = get("shutter_range_s", None)
        if sh and sh[1] > sh[0] > 0:
            c["phone.exposure.shutter_s"].set_range(float(sh[0]), float(sh[1]))
        # white balance
        for k in ("phone.white_balance.temperature", "phone.white_balance.tint"):
            self._gate(k, ps["white_balance"]["mode"] == "manual", "Only in Manual white balance")
        # torch, hdr
        has_torch = bool(get("has_torch", ps["camera"] == "back"))
        self._gate("phone.torch", has_torch,
                   "The front camera has no torch" if ps["camera"] == "front" else "This camera has no torch")
        self._gate("phone.hdr", bool(get("hdr", True)), "This camera has no HDR video")
        # wifi address only matters for Wi-Fi
        self._gate("pc.wifi_host", self.settings["pc"]["connect"] == "wifi", "Only when connecting by Wi-Fi")

    def _gate(self, path, ok, reason):
        ctl = self.ctl[path]
        if ctl.enabled != ok or (not ok and ctl._reason != reason):
            ctl.set_enabled(ok, reason)

    # ---- polling the engine
    def refresh_from_status(self, force=False):
        """Pull status from the engine and show the phone's real (clamped) settings. force=True ignores
        the short 'user just touched this' guard."""
        try:
            st = self.engine.get_status() or {}
        except Exception as e:
            self.log(f"get_status failed: {e}")
            st = {}
        self._status = st
        phone = st.get("phone")
        changed = False
        if phone:
            ps = phone.get("settings") or {}
            for path, ctl in self.ctl.items():
                if not path.startswith("phone."):
                    continue
                v = S.get_path(ps, path[len("phone."):])
                if v is None or (not force and ctl.recently_touched()):
                    continue
                ctl.show(v)
                if S.get_path(self.settings, path) != v:
                    S.deep_update(self.settings, S.nest(path, v))
                    changed = True
        if changed:
            self.schedule_save()
        self.update_enabled()
        self._mark_zoom_buttons()
        self._show_status(st)
        return st

    def _show_status(self, st):
        d = describe_status(st, self.settings["pc"].get("vcam_name", "Taco Cam"))
        self.last_status_text = d
        self.conn_label.configure(text=d["conn"], foreground=d["conn_color"])
        self.battery_label.configure(text=d["battery"])
        self.thermal_label.configure(text=d["thermal"], foreground=d["thermal_color"])
        stats = d["stats"]
        if d["phone_problem"]:
            stats = (stats + "  |  " if stats else "") + "Phone: " + d["phone_problem"]
        self.stats_label.configure(text=stats)
        self.vcam_label.configure(text=d["vcam"], foreground=d["vcam_color"])
        self.expiry_label.configure(text=d["expiry"], foreground=d["expiry_color"])
        if d["expiry_color"] != MUTED and d["expiry"] != self._expiry_logged:
            self._expiry_logged = d["expiry"]
            self.log(d["expiry"])
        if d["vcam_install"]:
            if not self.install_btn.winfo_ismapped():
                self.install_btn.pack(side="left", padx=(8, 0))
        elif self.install_btn.winfo_ismapped():
            self.install_btn.pack_forget()
        # test phone button follows the process
        if self._test_proc is not None and self._test_proc.poll() is not None:
            self._test_proc = None
        self.test_btn.configure(text="Stop test phone" if self._test_proc else "Start test phone")
        self.test_label.configure(text="Test phone is running on this PC" if self._test_proc else "")
        # log tab
        n = len(self.log_lines)
        if n != self._log_shown:
            self._log_shown = n
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.insert("end", "\n".join(self.log_lines))
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def _status_tick(self):
        if self._closing:
            return
        try:
            self.refresh_from_status()
            self._background_tick()
        except Exception:
            self.logger.exception("status tick failed")
        self._status_job = self.root.after(STATUS_MS, self._status_tick)

    def set_hint(self, text):
        self.hint_label.configure(text=text)

    # ---- preview
    def _canvas_resized(self, e):
        self.canvas.coords(self._placeholder, e.width // 2, e.height // 2)

    def _preview_tick(self):
        if self._closing:
            return
        try:
            self.draw_preview()
        except Exception:
            self.logger.exception("preview failed")
        self._preview_job = self.root.after(PREVIEW_MS, self._preview_tick)

    def draw_preview(self):
        from PIL import Image, ImageTk
        cw, ch = max(self.canvas.winfo_width(), 16), max(self.canvas.winfo_height(), 16)
        frame = self.engine.get_preview(cw, ch)
        if frame is None:
            self._img_box = None
            self.canvas.delete("frame")
            self.canvas.itemconfigure(self._placeholder, state="normal",
                                      text=self.last_status_text.get("conn") or "Waiting for the iPhone...")
            return
        h, w = frame.shape[:2]
        img = Image.fromarray(frame)
        if w > cw or h > ch:  # engine should scale, but never overflow the canvas
            s = min(cw / w, ch / h)
            w, h = max(1, int(w * s)), max(1, int(h * s))
            img = img.resize((w, h))
        self._photo = ImageTk.PhotoImage(img)
        x0, y0 = (cw - w) // 2, (ch - h) // 2
        self._img_box = (x0, y0, w, h)
        self.canvas.itemconfigure(self._placeholder, state="hidden")
        self.canvas.delete("frame")
        self.canvas.create_image(x0, y0, image=self._photo, anchor="nw", tags="frame")
        self.canvas.tag_lower("frame")
        self.preview_frames += 1

    def _canvas_click(self, e):
        box = self._img_box
        if not box:
            return
        x0, y0, w, h = box
        if not (x0 <= e.x < x0 + w and y0 <= e.y < y0 + h):
            return
        self.tap_focus((e.x - x0) / w, (e.y - y0) / h, (e.x, e.y))

    def tap_focus(self, nx, ny, at=None):
        try:
            self.engine.tap_focus(nx, ny)
        except Exception as ex:
            self.log(f"tap_focus failed: {ex}")
        if at and self._img_box:
            self.canvas.delete("focus")
            x, y = at
            self.canvas.create_rectangle(x - 28, y - 28, x + 28, y + 28, outline=ACCENT, width=2, tags="focus")
            if self._focus_job:
                self.root.after_cancel(self._focus_job)
            self._focus_job = self.root.after(900, lambda: self.canvas.delete("focus"))

    def _canvas_wheel(self, e):
        z = self.ctl["phone.zoom"]
        if not z.enabled:
            return
        step = 1.08 ** (e.delta / 120.0)
        z.nudge(z.value() * step)

    # ---- virtual camera + test phone
    def install_vcam(self):
        if not self.install_bat.exists():
            messagebox.showerror("Taco Cam", f"The installer was not found:\n{self.install_bat}")
            return
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", str(self.install_bat), None,
                                                str(self.install_bat.parent), 1)
            messagebox.showinfo("Taco Cam", "The installer is running (allow the Windows question).\n\n"
                                "When it says it is done, close Taco Cam and open it again.")
        except Exception as e:
            messagebox.showerror("Taco Cam", f"Could not start the installer: {e}")

    def toggle_test_phone(self):
        if self._test_proc is not None and self._test_proc.poll() is None:
            self.stop_test_phone()
            return
        if not self.fake_phone.exists():
            messagebox.showerror("Taco Cam", f"The test phone was not found:\n{self.fake_phone}")
            return
        try:
            out = open(ROOT_DIR / "fake-phone.log", "ab")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._test_proc = subprocess.Popen([sys.executable, str(self.fake_phone)], cwd=str(PC_DIR),
                                               stdout=out, stderr=out, stdin=subprocess.PIPE,  # NUL looks like a console to it
                                               creationflags=flags)
        except OSError as e:
            messagebox.showerror("Taco Cam", f"Could not start the test phone: {e}")
            return
        self.log("Test phone started")
        self.ctl["pc.connect"].select("wifi")
        self.ctl["pc.wifi_host"].select("127.0.0.1")
        self.test_btn.configure(text="Stop test phone")

    def stop_test_phone(self):
        p, self._test_proc = self._test_proc, None
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
            self.log("Test phone stopped")
        if not self._closing:
            self.test_btn.configure(text="Start test phone")
