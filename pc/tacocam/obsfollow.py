"""Watches which OBS scene is live (obs-websocket, asked once a second) so presets can follow it.

Runs only while "Follow OBS scenes" is on. Reconnects by itself; never changes anything in OBS.
"""
import threading
import time

from .obsws import ObsClient, ObsError, obs_config

POLL_S = 1.0
RETRY_S = 5.0
SCENES_EVERY_S = 10.0


class ObsFollower:
    def __init__(self, client_factory=None, log=None):
        self._factory = client_factory or (lambda: ObsClient(timeout=3.0))
        self._log = log or (lambda s: None)
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.scene = None          # live (program) scene name
        self.scenes = []           # all scene names, for linking presets
        self.status = "off"        # off | connecting | connected | error
        self.error = None

    def start(self):
        if self._thread is not None:
            return self
        self._stop.clear()
        self._set(status="connecting", error=None)
        self._thread = threading.Thread(target=self._run, name="tacocam-obs", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(4.0)
            self._thread = None
        self._set(status="off", scene=None)

    def snapshot(self):
        with self._lock:
            return {"status": self.status, "scene": self.scene, "scenes": list(self.scenes), "error": self.error}

    def _set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def _run(self):
        said_error = None
        while not self._stop.is_set():
            client = None
            try:
                cfg = obs_config()
                if cfg is not None and not cfg.get("enabled"):
                    raise ObsError("the OBS websocket server is off (OBS: Tools > WebSocket Server Settings)")
                client = self._factory().connect()
                self._set(status="connected", error=None)
                if said_error:
                    self._log("Connected to OBS: presets follow the live scene")
                said_error = None
                next_list = 0.0
                while not self._stop.is_set():
                    now = time.monotonic()
                    if now >= next_list:
                        names = [s.get("sceneName") for s in client.request("GetSceneList").get("scenes", [])]
                        self._set(scenes=[n for n in reversed(names) if isinstance(n, str)])
                        next_list = now + SCENES_EVERY_S
                    cur = client.request("GetCurrentProgramScene")
                    self._set(scene=cur.get("currentProgramSceneName") or cur.get("sceneName"))
                    self._stop.wait(POLL_S)
            except (OSError, ObsError, ValueError) as e:
                msg = str(e) or type(e).__name__
                if isinstance(e, OSError) and not isinstance(e, ObsError):
                    msg = "OBS is not running or its websocket server is off"
                self._set(status="error", error=msg, scene=None)
                if msg != said_error:
                    self._log(f"OBS scenes: {msg}")
                    said_error = msg
            finally:
                if client is not None:
                    try:
                        client.close()
                    except OSError:
                        pass
            self._stop.wait(RETRY_S)
