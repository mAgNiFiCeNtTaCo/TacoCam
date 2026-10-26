"""System-wide hotkeys Ctrl+Alt+1..9 (they work while OBS or any other window has the focus).

A background thread owns the registrations and its own message loop (WM_HOTKEY goes to the thread that
registered it). Presses land in a queue that the Tk thread drains; nothing here touches Tk.
"""
import ctypes
import ctypes.wintypes as W
import os
import queue
import threading

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
BASE_ID = 0x7A00


class GlobalHotkeys:
    def __init__(self, count=9):
        self.count = count
        self.presses = queue.Queue()
        self.failed = []          # numbers another program already uses
        self._thread = None
        self._tid = None
        self._ready = threading.Event()

    def start(self):
        if os.name != "nt" or self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run, name="tacocam-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)
        return self

    def stop(self):
        if self._thread is None:
            return
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self._thread.join(2.0)
        self._thread = None

    def pressed(self):
        """Numbers (1..9) pressed since the last call."""
        out = []
        while True:
            try:
                out.append(self.presses.get_nowait())
            except queue.Empty:
                return out

    def _run(self):
        user32 = ctypes.windll.user32
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        registered = []
        for n in range(1, self.count + 1):
            if user32.RegisterHotKey(None, BASE_ID + n, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, 0x30 + n):
                registered.append(n)
            else:
                self.failed.append(n)
        self._ready.set()
        msg = W.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and BASE_ID < msg.wParam <= BASE_ID + self.count:
                    self.presses.put(int(msg.wParam - BASE_ID))
        finally:
            for n in registered:
                user32.UnregisterHotKey(None, BASE_ID + n)
