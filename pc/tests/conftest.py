import gc
import sys
import time
import tkinter as tk
from pathlib import Path

import pytest

PC = Path(__file__).resolve().parents[1]
for p in (str(PC), str(PC / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)


def pump(root, seconds=0.0, until=None, step=0.02):
    """Run Tk's event loop for a while (or until `until()` is true). Returns the last `until()` value."""
    end = time.monotonic() + seconds
    while True:
        root.update()
        if until is not None and until():
            return True
        if time.monotonic() >= end:
            return bool(until()) if until is not None else True
        time.sleep(step)


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass
    del root
    gc.collect()      # free leftover Tk objects here, never inside an engine thread


@pytest.fixture
def stub_app(tk_root, tmp_path):
    from stub_engine import StubEngine
    from tacocam.app import App
    app = App(tk_root, StubEngine, settings_path=tmp_path / "settings.json")
    tk_root.withdraw()
    yield app
    if not app._closing:
        app.close()
