"""Android phones over USB (adb.py + link.py "android"): a fake adb in front of the fake phone with pairing on."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, HERE)
from tacocam import adb as adbmod  # noqa: E402
from tacocam import link as linkmod  # noqa: E402
from tacocam import pipeline  # noqa: E402
from tacocam import precheck as PC  # noqa: E402
from tacocam.app import describe_status  # noqa: E402
from tacocam.engine import Engine  # noqa: E402
import fake_phone  # noqa: E402
from test_engine_e2e import PAIR_CODE, Logs, Recorder, wait_until  # noqa: E402

SERIAL = "R5CT123ABC"


class FakeAdb:
    """Stands in for adb.Adb: one phone on USB whose Taco Cam app is the fake phone (listening with a code)."""

    def __init__(self, phone, state="device", installed=None, bundled=3):
        self.phone = phone
        self.state = state
        self.installed = installed            # versionCode on the phone, None = not installed
        self.bundled = bundled
        self.app_running = False
        self.calls = []
        self.code = PAIR_CODE
        self.install_problem = None

    def devices(self):
        self.calls.append("devices")
        if self.state is None:
            return []
        return [{"serial": SERIAL, "state": self.state, "model": "Pixel 8", "usb": True}]

    def installed_version(self, serial):
        return self.installed

    def install(self, serial, apk):
        self.calls.append(("install", apk))
        if self.install_problem:
            return self.install_problem
        self.installed = self.bundled
        return None

    def running(self, serial):
        return self.app_running

    def launch(self, serial):
        self.calls.append("launch")
        self.app_running = self.installed is not None
        return True

    def read_code(self, serial):
        return self.code if self.app_running else None

    def forward(self, serial, remote=47777):
        self.calls.append("forward")
        return self.phone.port


@pytest.fixture
def phone():
    p = fake_phone.FakePhone(port=0, rotation=90, device="Google Pixel 8", code=PAIR_CODE).start()
    yield p
    p.stop()


def android_engine(fake, monkeypatch, bundled=3):
    monkeypatch.setattr(adbmod, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(adbmod, "find_apk", lambda: ("C:/TacoCam/android/TacoCam.apk", bundled))
    logs = Logs()
    eng = Engine({"pc": {"connect": "android", "output": "1280x720", "fps_out": 30},
                  "phone": {"resolution": "720p", "fps": 30}}, log=logs, vcam_factory=Recorder())
    eng.logs = logs
    return eng


def test_plug_in_installs_opens_and_streams(phone, monkeypatch):
    fake = FakeAdb(phone)
    eng = android_engine(fake, monkeypatch)
    eng.start()
    try:
        assert wait_until(lambda: eng.get_status()["link"] == "connected" and eng._decoder.decoded > 3, timeout=12)
        st = eng.get_status()
        assert st["transport"] == "android" and st["device_name"] == "Google Pixel 8"
        assert ("install", "C:/TacoCam/android/TacoCam.apk") in fake.calls and "launch" in fake.calls
        assert eng.logs.has("Taco Cam app installed on the Pixel 8")
        assert eng.logs.has("Connected to Google Pixel 8 (android")
        assert phone.auth_failures == 0
        assert describe_status(st)["conn"] == "Connected to Google Pixel 8 by USB"
    finally:
        eng.stop()


def test_up_to_date_app_is_not_installed_again(phone, monkeypatch):
    fake = FakeAdb(phone, installed=3)
    fake.app_running = True
    eng = android_engine(fake, monkeypatch, bundled=3)
    eng.start()
    try:
        assert wait_until(lambda: eng.get_status()["link"] == "connected", timeout=10)
        assert not any(isinstance(c, tuple) and c[0] == "install" for c in fake.calls)
        assert "launch" not in fake.calls
    finally:
        eng.stop()


def test_older_app_is_updated(phone, monkeypatch):
    fake = FakeAdb(phone, installed=2)
    eng = android_engine(fake, monkeypatch, bundled=3)
    eng.start()
    try:
        assert wait_until(lambda: eng.get_status()["link"] == "connected", timeout=12)
        assert fake.installed == 3 and eng.logs.has("Taco Cam app updated on the Pixel 8")
    finally:
        eng.stop()


@pytest.mark.parametrize("state, link, text", [
    (None, "searching", "Plug the Android phone"),
    ("unauthorized", "error", "Allow USB debugging?"),
    ("offline", "error", "not ready"),
])
def test_phone_not_ready_says_what_to_do(phone, monkeypatch, state, link, text):
    fake = FakeAdb(phone, state=state)
    eng = android_engine(fake, monkeypatch)
    eng.start()
    try:
        assert wait_until(lambda: eng.get_status()["link"] == link and eng.logs.has(text), timeout=6)
        assert "forward" not in fake.calls
        kind, _ = eng._card_kind()
        assert kind == ("android" if link == "searching" else "error")
    finally:
        eng.stop()


def test_install_problem_is_shown(phone, monkeypatch):
    fake = FakeAdb(phone)
    fake.install_problem = "this phone's Android is too old for Taco Cam (it needs Android 11 or newer)"
    eng = android_engine(fake, monkeypatch)
    eng.start()
    try:
        assert wait_until(lambda: eng.get_status()["error"] == fake.install_problem
                          or (eng.get_status()["phone"] is None and eng.logs.has("too old")), timeout=6)
        assert "Problem: this phone's Android is too old" in describe_status(eng.get_status())["conn"]
    finally:
        eng.stop()


def test_wrong_code_gets_no_picture(phone, monkeypatch):
    fake = FakeAdb(phone)
    fake.code = "WRNG2345WRNG6789"
    eng = android_engine(fake, monkeypatch)
    eng.start()
    try:
        assert wait_until(lambda: phone.auth_failures >= 1, timeout=10)
        assert eng.get_status()["link"] != "connected" and eng._decoder.decoded == 0
    finally:
        eng.stop()


def test_link_android_needs_no_settings_typed():
    """Android mode works from the settings alone: no IP address, no code typed by the user."""
    from tacocam import settings as S
    s = S.sanitize({"pc": {"connect": "android"}})
    assert s["pc"]["connect"] == "android" and s["pc"]["wifi_code"] == ""


# --- adb.py on its own (adb's text output parsed right) ----------------------------------------------------

class ScriptedAdb(adbmod.Adb):
    def __init__(self, answers):
        super().__init__(path="adb.exe")
        self.answers = answers
        self.ran = []

    def run(self, *args, serial=None, timeout=None):
        self.ran.append((serial, args))
        for key, answer in self.answers:
            if " ".join(str(a) for a in args).startswith(key):
                return answer
        return 1, ""


def test_devices_are_parsed():
    out = ("List of devices attached\n"
           "R5CT123ABC             device usb:1-4 product:a54xns model:SM_A546E device:a54x transport_id:3\n"
           "0A1B2C3D               unauthorized usb:1-5 transport_id:4\n"
           "9XYZ                   no permissions (missing udev rules?); see [http://x] usb:1-6\n"
           "emulator-5554          device product:sdk model:sdk_gphone64 transport_id:1\n")
    a = ScriptedAdb([("devices", (0, out))])
    devs = a.devices()
    assert [d["serial"] for d in devs] == ["R5CT123ABC", "0A1B2C3D", "9XYZ", "emulator-5554"]
    assert devs[0] == {"serial": "R5CT123ABC", "state": "device", "model": "SM A546E", "usb": True}
    assert devs[1]["state"] == "unauthorized" and devs[2]["state"] == "no permissions"
    assert devs[3]["usb"] is False


def test_forward_is_reused_and_code_read():
    a = ScriptedAdb([("forward --list", (0, "R5CT123ABC tcp:51234 tcp:47777\nOTHER tcp:5 tcp:47777")),
                     ("shell cat", (0, "ABCD EFGH JKLM NPQR\r\n")),
                     ("shell dumpsys", (0, "  Packages:\n    versionCode=7 minSdk=30 targetSdk=36\n"))])
    assert a.forward("R5CT123ABC") == 51234
    assert a.read_code("R5CT123ABC") == "ABCDEFGHJKLMNPQR"
    assert a.installed_version("R5CT123ABC") == 7
    b = ScriptedAdb([("forward --list", (0, "")), ("forward tcp:0", (0, "60001"))])
    assert b.forward("R5CT123ABC") == 60001


def test_install_messages():
    ok = ScriptedAdb([("install", (0, "Performing Streamed Install\nSuccess"))])
    assert ok.install("S", "app.apk") is None
    assert any(args[:2] == ("shell", "pm") for _s, args in ok.ran)          # camera granted
    old = ScriptedAdb([("install", (1, "Failure [INSTALL_FAILED_OLDER_SDK: Requires newer sdk version #30]"))])
    assert "Android 11" in old.install("S", "app.apk")
    xiaomi = ScriptedAdb([("install", (1, "Failure [INSTALL_FAILED_USER_RESTRICTED: Install canceled by user]"))])
    assert "Install via USB" in xiaomi.install("S", "app.apk")
    missing = adbmod.Adb(path=None)
    missing.path = None
    with pytest.raises(adbmod.AdbError):
        missing.run("devices")


# --- words for an Android phone ------------------------------------------------------------------------------

def test_android_words_in_status_and_check():
    st = {"link": "searching", "transport": "android", "vcam": "running", "vcam_backend": "unitycapture"}
    assert describe_status(st)["conn"] == "Searching for the Android phone on USB..."
    st["link"] = "no_app"
    assert "opening Taco Cam" in describe_status(st)["conn"]
    res = PC.run_checks(st, {"pc": {"connect": "android", "output": "1920x1080", "rotate": 0}})
    text = " | ".join(t for _l, t in res)
    assert "iPhone" not in text and "iOS" not in text and "FaceTime" not in text and "iloader" not in text
    assert "phone" in res[0][1]
    title, lines = pipeline.card_lines("android")
    assert "Allow USB debugging" in " ".join(lines)
    assert linkmod.ANDROID_ALLOW.startswith("On the phone")
