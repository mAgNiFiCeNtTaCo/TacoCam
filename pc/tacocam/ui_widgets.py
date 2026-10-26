"""Small tkinter widgets for the Taco Cam window: dark theme, tooltips, and controls that know
how to show a value without sending it (so the phone's STATE can update them)."""
import math
import time
import tkinter as tk
from tkinter import ttk

BG = "#1b1c20"
PANEL = "#24262c"
FIELD = "#30333b"
FG = "#e8e8ea"
MUTED = "#9a9fab"
ACCENT = "#ff8a1f"
ACCENT_DK = "#c96a10"
GOOD = "#5fd068"
WARN = "#ffc233"
BAD = "#ff5d5d"

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_BIG = ("Segoe UI", 15, "bold")


def apply_theme(root):
    root.configure(bg=BG)
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    s.configure(".", background=PANEL, foreground=FG, fieldbackground=FIELD, font=FONT,
                bordercolor=FIELD, lightcolor=PANEL, darkcolor=PANEL, troughcolor=FIELD)
    s.configure("TFrame", background=PANEL)
    s.configure("Dark.TFrame", background=BG)
    s.configure("TLabel", background=PANEL, foreground=FG)
    s.configure("Muted.TLabel", foreground=MUTED, font=FONT_SMALL)
    s.configure("Note.TLabel", foreground=WARN, font=("Segoe UI", 9, "italic"))
    s.configure("Status.TLabel", background=BG, foreground=FG)
    s.configure("StatusMuted.TLabel", background=BG, foreground=MUTED)
    s.configure("Head.TLabel", foreground=ACCENT, font=FONT_BOLD)
    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(2, 4, 2, 0))
    s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(14, 6), font=FONT_BOLD)
    s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ACCENT)])
    s.configure("TButton", background=FIELD, foreground=FG, padding=(10, 5), borderwidth=1)
    s.map("TButton", background=[("active", "#3c404a"), ("disabled", PANEL)],
          foreground=[("disabled", "#666b75")])
    s.configure("Accent.TButton", background=ACCENT_DK, foreground="white", font=FONT_BOLD)
    s.map("Accent.TButton", background=[("active", ACCENT)])
    # Big quick-zoom buttons
    s.configure("Zoom.TButton", background=FIELD, foreground=FG, font=FONT_BIG, padding=(14, 8))
    s.map("Zoom.TButton", background=[("active", "#3c404a")])
    s.configure("ZoomOn.TButton", background=ACCENT_DK, foreground="white", font=FONT_BIG, padding=(14, 8))
    s.map("ZoomOn.TButton", background=[("active", ACCENT)])
    # Segmented choice buttons
    s.configure("Seg.Toolbutton", background=FIELD, foreground=FG, padding=(9, 4), borderwidth=1,
                relief="flat")
    s.map("Seg.Toolbutton",
          background=[("disabled", PANEL), ("selected", ACCENT_DK), ("active", "#3c404a")],
          foreground=[("disabled", "#5d626c"), ("selected", "white")])
    s.configure("TCheckbutton", background=PANEL, foreground=FG)
    s.map("TCheckbutton", background=[("active", PANEL)], foreground=[("disabled", "#5d626c")])
    s.configure("TScale", background=PANEL, troughcolor=FIELD)
    s.configure("Horizontal.TScale", background=PANEL, troughcolor=FIELD)
    s.map("Horizontal.TScale", background=[("active", ACCENT), ("disabled", PANEL)])
    s.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG,
                arrowcolor=FG, selectbackground=FIELD, selectforeground=FG)
    s.map("TCombobox", fieldbackground=[("readonly", FIELD), ("disabled", PANEL)],
          foreground=[("disabled", "#5d626c")])
    s.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DK)
    root.option_add("*Font", FONT)
    return s


class Tooltip:
    """One-line hint shown after the mouse rests on a widget."""

    def __init__(self, widget, text="", delay=500):
        self.widget, self.text, self.delay = widget, text, delay
        self._job = None
        self._tip = None
        for ev in ("<Enter>", "<Motion>"):
            widget.bind(ev, self._schedule, add="+")
        for ev in ("<Leave>", "<ButtonPress>", "<Destroy>"):
            widget.bind(ev, self._hide, add="+")

    def set_text(self, text):
        self.text = text

    def _schedule(self, _e=None):
        self._cancel()
        if self.text:
            self._job = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _show(self):
        self._job = None
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_pointerx() + 14
            y = self.widget.winfo_pointery() + 18
            self._tip = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tk.Label(tw, text=self.text, bg="#101114", fg=FG, bd=1, relief="solid",
                     padx=6, pady=3, font=FONT_SMALL, wraplength=380, justify="left").pack()
        except tk.TclError:
            self._tip = None

    def _hide(self, _e=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


class Control(ttk.Frame):
    """Base for the settings controls. `path` is the settings key ("phone.zoom"), `on_change` is called
    with (path, value) only when the USER changes something; show() updates silently."""

    def __init__(self, parent, title, hint="", label_width=17):
        super().__init__(parent)
        self.path = None
        self.on_change = None
        self.touched_at = 0.0
        self.dragging = False
        self.enabled = True
        self._silent = False
        self._hint = hint
        self._reason = ""
        self.columnconfigure(1, weight=1)
        self.title_label = ttk.Label(self, text=title, width=label_width)
        self.title_label.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.body = ttk.Frame(self)
        self.body.grid(row=0, column=1, sticky="ew")
        self.note = ttk.Label(self, text="", style="Note.TLabel")
        self.note.grid(row=1, column=1, sticky="w")
        self.note.grid_remove()
        self.tip = Tooltip(self.title_label, hint)

    # -- to be provided by subclasses
    def show(self, value):
        raise NotImplementedError

    def value(self):
        raise NotImplementedError

    def _apply_enabled(self):
        raise NotImplementedError

    # -- shared
    def user_changed(self, value=None):
        """Called by widget callbacks (and by tests) for a change the user made."""
        if self._silent:
            return
        self.touched_at = time.monotonic()
        if value is None:
            value = self.value()
        if self.on_change:
            self.on_change(self.path, value)

    def recently_touched(self, seconds=1.2):
        return self.dragging or (time.monotonic() - self.touched_at) < seconds

    def set_enabled(self, enabled, reason=""):
        self.enabled = bool(enabled)
        self._reason = "" if enabled else reason
        if self.enabled:
            self.note.grid_remove()
        else:
            self.note.configure(text=reason)
            if reason:
                self.note.grid()
        self.tip.set_text(self._reason or self._hint)
        self._apply_enabled()


class Choice(Control):
    """A row of buttons where exactly one is selected. options = [(value, label), ...]."""

    def __init__(self, parent, title, options, hint="", **kw):
        super().__init__(parent, title, hint, **kw)
        self.options = list(options)
        self._var = tk.IntVar(value=-1)
        self.buttons = []
        for i, (val, label) in enumerate(self.options):
            b = ttk.Radiobutton(self.body, text=label, value=i, variable=self._var,
                                style="Seg.Toolbutton", command=self._clicked)
            b.pack(side="left", padx=(0, 3))
            self.buttons.append(b)

    def _clicked(self):
        i = self._var.get()
        if 0 <= i < len(self.options):
            self.user_changed(self.options[i][0])

    def value(self):
        i = self._var.get()
        return self.options[i][0] if 0 <= i < len(self.options) else None

    def show(self, value):
        for i, (val, _l) in enumerate(self.options):
            if val == value and isinstance(val, bool) == isinstance(value, bool):
                self._silent = True
                self._var.set(i)
                self._silent = False
                return
        self._silent = True
        self._var.set(-1)
        self._silent = False

    def set_allowed(self, allowed):
        """Disable the options whose value is not in `allowed` (None = all allowed)."""
        for b, (val, _l) in zip(self.buttons, self.options):
            ok = self.enabled and (allowed is None or val in allowed)
            b.state(["!disabled"] if ok else ["disabled"])
        self._allowed = allowed

    def _apply_enabled(self):
        self.set_allowed(getattr(self, "_allowed", None))

    def select(self, value):
        """Programmatic user-style selection (used by tests and buttons)."""
        self.show(value)
        self.user_changed(value)


class Combo(Control):
    """Drop-down list. options = [(value, label), ...]."""

    def __init__(self, parent, title, options, hint="", **kw):
        super().__init__(parent, title, hint, **kw)
        self.options = list(options)
        self.cb = ttk.Combobox(self.body, state="readonly", width=44,
                               values=[label for _v, label in self.options])
        self.cb.pack(side="left", fill="x", expand=True)
        self.cb.bind("<<ComboboxSelected>>", lambda _e: self.user_changed())

    def value(self):
        i = self.cb.current()
        return self.options[i][0] if i >= 0 else None

    def show(self, value):
        for i, (val, _l) in enumerate(self.options):
            if val == value:
                self._silent = True
                self.cb.current(i)
                self._silent = False
                return

    def select(self, value):
        self.show(value)
        self.user_changed(value)

    def _apply_enabled(self):
        self.cb.state(["!disabled"] if self.enabled else ["disabled"])


class Switch(Control):
    """On/off checkbox. on/off values default to True/False."""

    def __init__(self, parent, title, text="On", hint="", on=True, off=False, **kw):
        super().__init__(parent, title, hint, **kw)
        self.on, self.off = on, off
        self._var = tk.BooleanVar(value=False)
        self.cb = ttk.Checkbutton(self.body, text=text, variable=self._var, command=self._clicked)
        self.cb.pack(side="left")

    def _clicked(self):
        self.user_changed(self.value())

    def value(self):
        return self.on if self._var.get() else self.off

    def show(self, value):
        self._silent = True
        self._var.set(value == self.on)
        self._silent = False

    def select(self, value):
        self.show(value)
        self.user_changed(value)

    def _apply_enabled(self):
        self.cb.state(["!disabled"] if self.enabled else ["disabled"])


class Slider(Control):
    """Slider with a value label. Position is 0..1000 internally; log=True spreads lo..hi on a log scale.
    While the user drags, on_change is throttled; the final value is sent on release."""

    STEPS = 1000

    def __init__(self, parent, title, lo, hi, fmt=None, step=None, log=False, hint="",
                 throttle_ms=70, **kw):
        super().__init__(parent, title, hint, **kw)
        self.lo, self.hi, self.step, self.log, self.fmt = lo, hi, step, log, fmt or (lambda v: f"{v:g}")
        self.throttle_ms = throttle_ms
        self._pending = False
        self._value = lo
        self.body.columnconfigure(0, weight=1)
        self._pos = tk.DoubleVar(value=0)
        self.scale = ttk.Scale(self.body, from_=0, to=self.STEPS, variable=self._pos,
                               orient="horizontal", command=self._moved)
        self.scale.grid(row=0, column=0, sticky="ew")
        self.value_label = ttk.Label(self.body, text="", width=9, anchor="e")
        self.value_label.grid(row=0, column=1, padx=(8, 0))
        self.scale.bind("<ButtonPress-1>", self._press, add="+")
        self.scale.bind("<ButtonRelease-1>", self._release, add="+")
        self.show(lo)

    # value <-> position
    def _to_pos(self, v):
        v = min(max(v, self.lo), self.hi)
        if self.hi == self.lo:
            return 0.0
        if self.log:
            return self.STEPS * math.log(v / self.lo) / math.log(self.hi / self.lo)
        return self.STEPS * (v - self.lo) / (self.hi - self.lo)

    def _from_pos(self, p):
        t = min(max(p / self.STEPS, 0.0), 1.0)
        v = self.lo * (self.hi / self.lo) ** t if self.log else self.lo + t * (self.hi - self.lo)
        return self._quantize(v)

    def _quantize(self, v):
        if self.step:
            v = round(v / self.step) * self.step
            v = round(v, 6)
            if float(self.step).is_integer():
                v = int(v)
        return min(max(v, self.lo), self.hi)

    def value(self):
        return self._value

    def show(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        self._silent = True
        self._value = self._quantize(value) if self.step else min(max(value, self.lo), self.hi)
        self._pos.set(self._to_pos(self._value))
        self.value_label.configure(text=self.fmt(self._value))
        self._silent = False

    def set_range(self, lo, hi):
        if (lo, hi) == (self.lo, self.hi) or hi <= lo:
            return
        self.lo, self.hi = lo, hi
        self.show(self._value)

    # events
    def _moved(self, _v=None):
        if self._silent:
            return
        self._value = self._from_pos(self._pos.get())
        self.value_label.configure(text=self.fmt(self._value))
        self.touched_at = time.monotonic()
        if not self._pending:
            self._pending = True
            self.after(self.throttle_ms, self._flush)

    def _flush(self):
        self._pending = False
        self.user_changed(self._value)

    def _press(self, _e):
        if self.enabled:
            self.dragging = True

    def _release(self, _e):
        if self.dragging:
            self.dragging = False
            self.touched_at = time.monotonic()
            self.user_changed(self._value)

    def nudge(self, value):
        """Change from a wheel turn: shows now, sends throttled."""
        self.show(value)
        self.touched_at = time.monotonic()
        if not self._pending:
            self._pending = True
            self.after(self.throttle_ms, self._flush)

    def select(self, value):
        """Programmatic user-style change (tests, zoom buttons): shows and sends at once."""
        self.show(value)
        self.user_changed(self._value)

    def _apply_enabled(self):
        self.scale.state(["!disabled"] if self.enabled else ["disabled"])
        self.value_label.configure(foreground=FG if self.enabled else "#5d626c")
