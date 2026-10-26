"""python -m tacocam  (run from the pc folder)"""
import logging
import logging.handlers
import sys
import tkinter as tk
from tkinter import messagebox


def _setup_logging():
    from .app import LOG_PATH
    handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def hook(exc_type, exc, tb):
        logging.getLogger("tacocam").error("Uncaught exception", exc_info=(exc_type, exc, tb))
    sys.excepthook = hook


def main():
    _setup_logging()
    log = logging.getLogger("tacocam")
    from .app import App, acquire_single_instance

    lock = acquire_single_instance()
    root = tk.Tk()
    if lock is None:
        root.withdraw()
        messagebox.showinfo("Taco Cam", "Taco Cam is already running.\n\nLook for its window in the taskbar.")
        return 0
    try:
        from .engine import Engine
    except Exception as e:  # missing packages or engine problems: say it in plain words
        log.exception("Could not load the engine")
        root.withdraw()
        messagebox.showerror(
            "Taco Cam",
            "Taco Cam could not start its video engine.\n\n"
            f"{type(e).__name__}: {e}\n\n"
            "Most likely the Python packages are missing. Open a terminal and run:\n"
            "pip install --user -r pc/requirements.txt")
        return 1

    def report(exc, val, tb):
        log.error("Tk callback error", exc_info=(exc, val, tb))
    root.report_callback_exception = report
    app = App(root, Engine)
    log.info("Taco Cam window started")
    root.mainloop()
    del app, lock
    return 0


if __name__ == "__main__":
    sys.exit(main())
