"""Build dist\\TacoCam.zip and dist\\TacoCam-Setup-<version>.exe: Taco Cam for a friend's Windows PC with an Android
phone. Unzip and double-click "Start Taco Cam" (or run the installer), and the "Get started" window walks through
the rest.

    python pc/tools/build_portable.py                  build the phone app, the zip and the installer, test both
    python pc/tools/build_portable.py --no-test        build only
    python pc/tools/build_portable.py --keep-apk       use the phone app that's already built
    python pc/tools/build_portable.py --no-installer   the zip only

The installer (installer/TacoCam.iss, Inno Setup 6) holds the same folder as the zip. Its setup .exe isn't signed
by anyone (that needs a paid code-signing certificate), so Windows SmartScreen shows "Windows protected your PC"
once (More info > Run anyway); the zip has no such step. Both go on the GitHub release.

Why a zip with python.org's Python instead of one .exe: antivirus programs and browsers call new unsigned
one-file .exe programs a virus ("Couldn't download - Virus detected"; OBS Doctor, 2026-11-14). Python
(python.exe / pythonw.exe and the Tk files) is signed by the Python Software Foundation and adb.exe by Google;
the picture and video packages are the standard ones from PyPI (not signed). Our own code is plain .py text.

Nothing of the PC that builds it may end up inside (security finding WEBCAM-20261128-01): pip makes no compiled
files and no launcher programs here (both hold the builder's own folder paths), and the build stops when any file
still holds the Windows user folder of this PC.

Inside the zip:
    Taco Cam/
        Start Taco Cam.cmd            double-click this
        How to set up Taco Cam.html   the friend's guide
        settings.json                 starting settings (pc/tools/friend_settings.json: Android, Whatnot output)
        python/                       python.org "embeddable" Python (same version as this PC's) + tkinter
                                      + the packages in python/Lib/site-packages
        pc/tacocam/                   the program; pc/vcam/ the camera driver and its installer
        platform-tools/               Google's adb (talks to the Android phone over USB)
        android/TacoCam.apk           the phone app (+ TacoCam.version), installed by Taco Cam itself
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BUILD = REPO / "build" / "portable"
DIST = REPO / "dist"
ZIP = DIST / "TacoCam.zip"
ISS = REPO / "installer" / "TacoCam.iss"
FOLDER = "Taco Cam"
GUIDE = REPO / "docs" / "How to set up Taco Cam.html"
SDK = Path(os.environ.get("ANDROID_HOME") or r"D:\DevTools\Android")
KEYSTORE = Path(os.environ.get("TACOCAM_KEYSTORE") or r"D:\DevTools\tacocam-keystore.properties")
APK_OUT = REPO / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"

# the PC packages, at the versions this PC runs (and the tests pass with); opencv without its GUI parts
PACKAGES = [("av", "av"), ("numpy", "numpy"), ("opencv-python", "opencv-python-headless"), ("Pillow", "Pillow"),
            ("pyvirtualcam", "pyvirtualcam")]
ADB_FILES = ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt")
TK_FILES = ("_tkinter.pyd", "tcl90.dll", "tcl9tk90.dll", "libtommath.dll", "zlib1.dll")

# Who must have signed what, compared exactly with the O= field of the signature (a look-alike name that merely
# contains the word does not pass; WEBCAM-20261128-03).
SIGNERS = {"Python Software Foundation": "Python Software Foundation", "Google": "Google LLC"}
# SHA-256 of python.org's embeddable zip, per version. A new Python on this PC: check the new zip (its python.exe
# must be signed by the Python Software Foundation), then add its line here.
EMBED_SHA256 = {"3.14.10": "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159"}
# The release key's certificate fingerprint (public, not a secret): apksigner's "certificate SHA-256 digest".
APK_CERT_SHA256 = "eafa936354bebe61cc57d2ce6eeb0fef379edac69bbb3373eb2c1b81a4009092"

START_CMD = r"""@echo off
title Taco Cam
rem Starts Taco Cam with the Python that came in this folder.
if not exist "%~dp0python\pythonw.exe" (
  echo.
  echo  Taco Cam can't start from inside the zip file.
  echo  Close this window. Right-click the zip file, pick "Extract All...", click Extract,
  echo  then double-click "Start Taco Cam" in the new folder.
  echo.
  pause
  exit /b 1
)
start "" "%~dp0python\pythonw.exe" -m tacocam %*
"""


def log(text):
    print(time.strftime("%H:%M:%S"), text, flush=True)


def build_apk():
    """The phone app, signed with the release key (Android updates it only with the same key)."""
    if not KEYSTORE.is_file():
        raise SystemExit(f"The release key isn't there ({KEYSTORE}): run python android/make_keystore.py once")
    jdk = sorted(Path(r"C:\Program Files\Microsoft").glob("jdk-21*"))
    env = dict(os.environ, TACOCAM_KEYSTORE=str(KEYSTORE), GRADLE_USER_HOME=r"D:\DevTools\gradle-home")
    if jdk:
        env["JAVA_HOME"] = str(jdk[-1])
    log("building the phone app (gradle assembleRelease)")
    # full path: Windows may be set not to run programs from the current folder (NoDefaultCurrentDirectoryInExePath)
    subprocess.run(["cmd", "/c", str(REPO / "android" / "gradlew.bat"), "--no-daemon", "-q", "testDebugUnitTest",
                    "assembleRelease"], cwd=REPO / "android", env=env, check=True)


def apk_signer_ok(apk):
    tool = SDK / "build-tools" / "36.0.0" / "apksigner.bat"
    out = subprocess.run(["cmd", "/c", str(tool), "verify", "--print-certs", str(apk)], capture_output=True,
                         text=True).stdout
    # the fingerprint of the key, not the name on it: anyone can make a key called "Taco Cam"
    digests = re.findall(r"(?im)^Signer #\d+ certificate SHA-256 digest:\s*([0-9a-f]{64})\s*$", out)
    return digests == [APK_CERT_SHA256]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def embed_zip():
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    name = f"python-{ver}-embed-amd64.zip"
    dest = BUILD.parent / name
    want = EMBED_SHA256.get(ver)
    if want is None:
        raise SystemExit(f"No known checksum for {name}: add it to EMBED_SHA256 in build_portable.py after "
                         "checking the download")
    if dest.is_file():
        if sha256_of(dest) == want:
            return dest
        dest.unlink()                    # a cached copy that is not the known file: fetch it again
    url = f"https://www.python.org/ftp/python/{ver}/{name}"
    log(f"downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    got = sha256_of(tmp)
    if got != want:
        tmp.unlink()
        raise SystemExit(f"{name} from python.org is not the known file (SHA-256 {got[:16]}...): stopping")
    tmp.replace(dest)
    return dest


def signer(path):
    ps = (f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; \"$($s.Status)|$($s.SignerCertificate.Subject)\"")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    status, _, subject = out.partition("|")
    return status, subject


def signer_org(subject):
    """The O= field of a certificate subject ("CN=Google LLC, O=Google LLC, L=...") or ""."""
    m = re.search(r'(?:^|,\s*)O=(?:"([^"]*)"|([^,]*))', subject)
    return (m.group(1) or m.group(2) or "").strip() if m else ""


def must_be_signed(path, by):
    status, subject = signer(path)
    if status != "Valid" or signer_org(subject) != SIGNERS[by]:
        raise SystemExit(f"{path.name} is not signed by {by} ({status}, {subject[:80]}): stopping")
    log(f"{path.name}: signed by {by}")


def builder_marks():
    """Byte strings that give away the PC that builds: its Windows user folder, as text and as UTF-16."""
    user = (os.environ.get("USERNAME") or "").strip()
    marks = []
    if user:
        for form in ("\\Users\\" + user, "/Users/" + user):
            marks += [form.lower().encode("utf-8"), form.lower().encode("utf-16-le")]
    return marks


def files_with_builder_marks(folder, marks=None):
    """Files under folder that hold the builder's Windows user folder (relative paths; never the name itself)."""
    marks = builder_marks() if marks is None else marks
    found = []
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file() and marks:
            data = p.read_bytes().lower()
            if any(m in data for m in marks):
                found.append(p.relative_to(folder).as_posix())
    return found


def must_be_clean(folder, what):
    found = files_with_builder_marks(folder)
    if found:
        raise SystemExit(f"{what}: {len(found)} file(s) hold this PC's Windows user folder, for example "
                         + ", ".join(found[:5]) + ": stopping (nothing is published)")
    log(f"{what}: no file holds this PC's Windows user folder")


def build(keep_apk=False):
    if not keep_apk:
        build_apk()
    if not APK_OUT.is_file():
        raise SystemExit(f"No phone app at {APK_OUT}")
    if not apk_signer_ok(APK_OUT):
        raise SystemExit("The phone app isn't signed with the Taco Cam release key: build it with TACOCAM_KEYSTORE")

    stage = BUILD / "stage"
    if stage.exists():
        shutil.rmtree(stage)
    top = stage / FOLDER
    py = top / "python"
    py.mkdir(parents=True)
    with zipfile.ZipFile(embed_zip()) as z:
        z.extractall(py)
    for exe in ("python.exe", "pythonw.exe"):
        must_be_signed(py / exe, "Python Software Foundation")

    # tkinter (the window): the package from this PC's Python + its three signed files (Tcl/Tk 9 keeps its
    # scripts inside the DLLs)
    base = Path(sys.base_prefix)
    shutil.copytree(base / "Lib" / "tkinter", py / "tkinter", ignore=shutil.ignore_patterns("__pycache__", "test*"))
    for f in TK_FILES:
        if not (py / f).exists():
            shutil.copy2(base / "DLLs" / f, py / f)
        must_be_signed(py / f, "Python Software Foundation")

    site = py / "Lib" / "site-packages"
    pins = [f"{dist_name}=={importlib.metadata.version(local)}" for local, dist_name in PACKAGES]
    log("packages: " + ", ".join(pins))
    # --no-compile: pip's .pyc files remember the temp folder they were compiled in (inside this PC's user
    # folder). Python compiles on the friend's PC instead, into the tacocam-cache folder (tacocam/__init__.py).
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--only-binary=:all:",
                    "--no-compile",
                    "--platform", "win_amd64", "--python-version", f"{sys.version_info.major}.{sys.version_info.minor}",
                    "--implementation", "cp", "--target", str(site), *pins], check=True)
    # pip's launcher programs (f2py.exe, pyav.exe ...) hold the path of this PC's Python; Taco Cam uses none
    shutil.rmtree(site / "bin", ignore_errors=True)

    pth = next(py.glob("python3*._pth"))
    lines = [ln for ln in pth.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    for extra in ("Lib\\site-packages", "..\\pc"):
        if extra not in lines:
            lines.append(extra)
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"{pth.name}: {', '.join(lines)}")

    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.bak*", "*.tmp", "unitycapture-original")
    shutil.copytree(REPO / "pc" / "tacocam", top / "pc" / "tacocam", ignore=ignore)
    shutil.copytree(REPO / "pc" / "vcam", top / "pc" / "vcam", ignore=ignore)
    (top / "pc" / "tools").mkdir()
    shutil.copy2(REPO / "pc" / "tools" / "fake_phone.py", top / "pc" / "tools" / "fake_phone.py")   # "Start test phone"

    pt = top / "platform-tools"
    pt.mkdir()
    for f in ADB_FILES:
        if (SDK / "platform-tools" / f).is_file():
            shutil.copy2(SDK / "platform-tools" / f, pt / f)
    must_be_signed(pt / "adb.exe", "Google")

    (top / "android").mkdir()
    shutil.copy2(APK_OUT, top / "android" / "TacoCam.apk")
    shutil.copy2(REPO / "android" / "version.properties", top / "android" / "TacoCam.version")

    sys.path.insert(0, str(REPO / "pc"))
    from tacocam import settings as S
    friend = S.sanitize(json.loads((HERE / "friend_settings.json").read_text(encoding="utf-8")))
    (top / "settings.json").write_text(json.dumps(friend, indent=2), encoding="utf-8")
    (top / "Start Taco Cam.cmd").write_bytes(START_CMD.replace("\n", "\r\n").encode("ascii"))
    if GUIDE.is_file():
        shutil.copy2(GUIDE, top / GUIDE.name)
    shutil.copy2(REPO / "LICENSE", top / "LICENSE.txt")

    must_be_clean(stage, "the folder to pack")
    DIST.mkdir(exist_ok=True)
    tmp = ZIP.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(stage).as_posix())
    tmp.replace(ZIP)
    log(f"built {ZIP} ({ZIP.stat().st_size / 1_000_000:.1f} MB)")
    return ZIP


SMOKE = r"""
import sys, time, threading
sys.path.insert(0, r"{tools}")
import tacocam                      # first: it sends Python's compiled files to the tacocam-cache folder
import tkinter
r = tkinter.Tk(); r.withdraw(); r.update(); r.destroy()
import av, cv2, numpy, PIL, pyvirtualcam
from tacocam import adb, settings, vcam
from tacocam.engine import Engine
import fake_phone
print("adb:", adb.find_adb())
print("apk:", adb.find_apk())
s, note = settings.load()
assert s["pc"]["connect"] == "android" and s["pc"]["welcome"] is True, s["pc"]
phone = fake_phone.FakePhone(port=0, code="TACK2345CAMS6789").start()
cams = []
eng = Engine({{"pc": {{"connect": "wifi", "wifi_host": f"127.0.0.1:{{phone.port}}", "wifi_code": "TACK2345CAMS6789",
               "output": "1280x720"}}, "phone": {{"resolution": "720p"}}}}, log=print,
             vcam_factory=lambda w, h, f, n: cams.append(vcam.NullCamera(w, h, f, n)) or cams[-1])
eng.start()
end = time.monotonic() + 20
while time.monotonic() < end and not (eng.get_status()["link"] == "connected" and eng._decoder.decoded > 5):
    time.sleep(0.2)
ok = eng.get_status()["link"] == "connected" and eng._decoder.decoded > 5
eng.stop(); phone.stop()
print("engine:", "ok" if ok else "FAILED")
sys.exit(0 if ok else 1)
"""


def app_version():
    for line in (REPO / "android" / "version.properties").read_text(encoding="utf-8").splitlines():
        if line.startswith("versionName="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("android/version.properties has no versionName")


def iscc():
    for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
              Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"), Path(r"C:\Program Files\Inno Setup 6\ISCC.exe")):
        if p.is_file():
            return p
    raise SystemExit("Inno Setup 6 isn't installed: winget install --id JRSoftware.InnoSetup -e")


def build_installer():
    """dist\\TacoCam-Setup-<version>.exe from the zip's folder (build() must have run first)."""
    stage = BUILD / "stage" / FOLDER
    ver = app_version()
    log(f"building the installer (Inno Setup, version {ver})")
    subprocess.run([str(iscc()), "/Q", f"/DAppVersion={ver}", f"/DStage={stage}", str(ISS)], check=True)
    exe = DIST / f"TacoCam-Setup-{ver}.exe"
    log(f"built {exe} ({exe.stat().st_size / 1_000_000:.1f} MB)")
    return exe


def run_smoke(top):
    """The program's parts with its own Python: window toolkit, packages, adb and the phone app found, the starting
    settings, and the engine streaming from the test phone."""
    r = subprocess.run([str(top / "python" / "python.exe"), "-c", SMOKE.format(tools=top / "pc" / "tools")],
                       cwd=str(top), capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr).strip()
    print("\n".join(out.splitlines()[-12:]))
    return (r.returncode == 0 and f"{FOLDER}\\platform-tools\\adb.exe" in out
            and f"{FOLDER}\\\\android\\\\TacoCam.apk" in out and "engine: ok" in out)


def test(zip_path):
    """Unzip to a fresh folder and run the smoke checks."""
    where = Path(tempfile.mkdtemp(prefix="tacocam_zip_"))
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(where)
        leaks = files_with_builder_marks(where)
        if leaks:
            log(f"the zip holds this PC's Windows user folder in {len(leaks)} file(s): " + ", ".join(leaks[:5]))
        good = run_smoke(where / FOLDER) and not leaks
        stray = [p for p in (where / FOLDER).rglob("__pycache__")
                 if p.parent != where / FOLDER / "pc" / "tacocam" and "tacocam-cache" not in p.parts]
        if stray:
            log("compiled files outside tacocam-cache: " + ", ".join(str(p.relative_to(where)) for p in stray[:5]))
        good = good and not stray
        log("zip test: " + ("PASSED" if good else "FAILED"))
        return good
    finally:
        shutil.rmtree(where, ignore_errors=True)


def test_installer(exe):
    """Install silently into a fresh folder (no shortcuts, nothing in the Start menu), run the same smoke checks
    with the installed Python, then uninstall and check nothing is left."""
    where = Path(tempfile.mkdtemp(prefix="tacocam_setup_"))
    top = where / FOLDER
    try:
        subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", "/TASKS=",
                        f"/DIR={top}"], check=True, timeout=300)
        good = run_smoke(top)
        subprocess.run([str(top / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                       check=True, timeout=120)
        for _ in range(60):                      # the uninstaller finishes from a copy of itself
            if not top.exists():
                break
            time.sleep(0.5)
        left = sorted(str(p.relative_to(top)) for p in top.rglob("*")) if top.exists() else []
        if left:
            log("left after uninstalling: " + ", ".join(left[:10]))
        good = good and not left
        good = refuses_a_used_folder(exe) and good
        log("installer test: " + ("PASSED" if good else "FAILED"))
        return good
    finally:
        shutil.rmtree(where, ignore_errors=True)


def refuses_a_used_folder(exe):
    """The setup must not install into a folder that holds somebody's own files (the uninstaller would have to
    guess what is theirs; WEBCAM-20261128-05): it stops, and their file is still there."""
    where = Path(tempfile.mkdtemp(prefix="tacocam_used_"))
    try:
        theirs = where / "python" / "keep.txt"
        theirs.parent.mkdir()
        theirs.write_text("somebody's own file", encoding="utf-8")
        r = subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", "/TASKS=",
                            f"/DIR={where}"], timeout=300)
        installed = (where / "pc").exists() or (where / "unins000.exe").exists()
        ok = r.returncode != 0 and not installed and theirs.is_file()
        if not ok:
            log(f"the setup did not refuse a folder that is in use (exit {r.returncode}, installed: {installed})")
        return ok
    finally:
        shutil.rmtree(where, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-test", action="store_true")
    ap.add_argument("--keep-apk", action="store_true")
    ap.add_argument("--no-installer", action="store_true")
    a = ap.parse_args()
    z = build(keep_apk=a.keep_apk)
    exe = None if a.no_installer else build_installer()
    if a.no_test:
        return 0
    good = test(z)
    if exe:
        good = test_installer(exe) and good
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
