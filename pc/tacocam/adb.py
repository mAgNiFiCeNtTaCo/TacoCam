"""Android phones over the USB cable, through Google's adb (Android Debug Bridge).

The PC side of "plug in the phone and it just works": find the phone, install or update the Taco Cam app on it
(adb installs are allowed without Google's developer verification), give it the camera permission, open it, read
its pairing code and connect to it through `adb forward` (CONTRACT section 1, Android).

The phone needs "USB debugging" switched on once (Settings > About phone > tap Build number 7 times, then
Settings > System > Developer options > USB debugging) and the PC allowed once ("Allow USB debugging?").
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE = "com.tacocam.app"
ACTIVITY = f"{PACKAGE}/.MainActivity"
CODE_FILE = f"/sdcard/Android/data/{PACKAGE}/files/pairing.txt"
PHONE_PORT = 47777

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_HERE = Path(__file__).resolve().parent


class AdbError(Exception):
    """adb is missing or a command failed; the text is meant for the user."""


def app_root():
    """The folder Taco Cam runs from: the portable folder (app/tacocam -> ..) or the repo (pc/tacocam -> ../..)."""
    return _HERE.parent.parent


def find_adb():
    """adb.exe: TACOCAM_ADB, the one shipped next to Taco Cam, an Android SDK, or PATH. None when there is none."""
    exe = "adb.exe" if os.name == "nt" else "adb"
    candidates = [os.environ.get("TACOCAM_ADB")]
    root = app_root()
    candidates += [root / "platform-tools" / exe, root.parent / "platform-tools" / exe]
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(env):
            candidates.append(Path(os.environ[env]) / "platform-tools" / exe)
    candidates.append(Path(r"D:\DevTools\Android\platform-tools\adb.exe"))
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return shutil.which("adb")


def find_apk():
    """The Taco Cam app for the phone and its versionCode: (path, version) or (None, None)."""
    root = app_root()
    for apk in (root / "android" / "TacoCam.apk", root / "dist" / "TacoCam.apk",
                root / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"):
        if apk.is_file():
            return str(apk), apk_version(apk)
    return None, None


def apk_version(apk):
    """versionCode of a built APK: from <apk>.version (written by the build), else android/version.properties."""
    apk = Path(apk)
    for f in (apk.with_suffix(".version"), app_root() / "android" / "version.properties"):
        try:
            m = re.search(r"versionCode\s*=\s*(\d+)", f.read_text(encoding="utf-8"))
        except OSError:
            continue
        if m:
            return int(m.group(1))
    return None


class Adb:
    def __init__(self, path=None, timeout=10.0):
        self.path = path or find_adb()
        self.timeout = timeout

    def run(self, *args, serial=None, timeout=None):
        """-> (exit code, combined output text). Raises AdbError when adb itself is missing or hangs."""
        if not self.path:
            raise AdbError("adb is missing: reinstall Taco Cam (it comes with it)")
        cmd = [self.path] + (["-s", serial] if serial else []) + [str(a) for a in args]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout or self.timeout,
                               creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise AdbError(f"adb did not answer ({' '.join(str(a) for a in args[:2])})") from None
        except OSError as e:
            raise AdbError(f"adb could not start: {e}") from None
        out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
        return r.returncode, out.strip()

    def devices(self):
        """Phones adb sees: [{"serial", "state", "model", "usb"}]. state: device | unauthorized | offline | ..."""
        code, out = self.run("devices", "-l", timeout=15)
        found = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith(("List of devices", "*")) or "\t" not in line and "  " not in line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial = parts[0]
            # "no permissions (...)" has spaces in the state
            rest = " ".join(parts[1:])
            state = "no permissions" if rest.startswith("no permissions") else parts[1]
            info = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
            model = (info.get("model") or "").replace("_", " ") or "Android phone"
            found.append({"serial": serial, "state": state, "model": model,
                          "usb": "usb" in info or not serial.startswith("emulator-")})
        return found

    def installed_version(self, serial):
        """versionCode of Taco Cam on the phone, or None when it isn't installed."""
        code, out = self.run("shell", "dumpsys", "package", PACKAGE, serial=serial, timeout=15)
        m = re.search(r"versionCode=(\d+)", out)
        return int(m.group(1)) if m else None

    def install(self, serial, apk):
        """Install or update the app and grant the camera. Returns None, or a sentence saying what went wrong."""
        code, out = self.run("install", "-r", "-g", apk, serial=serial, timeout=180)
        if "Success" in out:
            self.grant_camera(serial)
            return None
        if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in out or "signatures do not match" in out:
            # a copy signed with another key (an old test build): replace it
            self.run("uninstall", PACKAGE, serial=serial, timeout=60)
            code, out = self.run("install", "-r", "-g", apk, serial=serial, timeout=180)
            if "Success" in out:
                self.grant_camera(serial)
                return None
        if "INSTALL_FAILED_USER_RESTRICTED" in out:
            return ("the phone blocked installing over USB: on the phone allow it (Xiaomi: Developer options > "
                    "Install via USB) and try again")
        if "INSTALL_FAILED_OLDER_SDK" in out:
            return "this phone's Android is too old for Taco Cam (it needs Android 11 or newer)"
        if "INSTALL_FAILED_INSUFFICIENT_STORAGE" in out:
            return "the phone is out of storage space"
        tail = out.splitlines()[-1] if out else f"exit code {code}"
        return f"installing the app failed ({tail[:120]})"

    def grant_camera(self, serial):
        self.run("shell", "pm", "grant", PACKAGE, "android.permission.CAMERA", serial=serial, timeout=15)

    def running(self, serial):
        code, out = self.run("shell", "pidof", PACKAGE, serial=serial, timeout=10)
        return code == 0 and out.strip().isdigit()

    def launch(self, serial):
        """Wake the screen and bring Taco Cam to the front."""
        self.run("shell", "input", "keyevent", "KEYCODE_WAKEUP", serial=serial, timeout=10)
        code, out = self.run("shell", "am", "start", "-n", ACTIVITY, serial=serial, timeout=15)
        return code == 0 and "Error" not in out

    def read_code(self, serial):
        """The pairing code the app made (it writes it where only adb and the app itself can read it)."""
        code, out = self.run("shell", "cat", CODE_FILE, serial=serial, timeout=10)
        text = "".join(ch for ch in out.upper() if ch.isalnum())
        return text if code == 0 and len(text) == 16 else None

    def forward(self, serial, remote=PHONE_PORT):
        """A local TCP port on this PC that leads to the phone's port `remote` (reused when it exists)."""
        code, out = self.run("forward", "--list", timeout=10)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == serial and parts[2] == f"tcp:{remote}" and parts[1].startswith("tcp:"):
                return int(parts[1][4:])
        code, out = self.run("forward", "tcp:0", f"tcp:{remote}", serial=serial, timeout=10)
        m = re.search(r"(\d+)", out)
        if code != 0 or not m:
            raise AdbError(f"could not open the USB connection to the phone ({out[:100]})")
        return int(m.group(1))


def main(argv=None):
    """Small check from the command line: python -m tacocam.adb"""
    a = Adb()
    print("adb:", a.path)
    print("app:", find_apk())
    for d in a.devices():
        print(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
