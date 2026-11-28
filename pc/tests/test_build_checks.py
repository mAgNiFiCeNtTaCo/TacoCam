"""The checks pc/tools/build_portable.py and android/make_keystore.py make before a friend's copy is published
(security findings WEBCAM-20261128-01 and -03). Nothing is built, downloaded, signed or started here."""
import os
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pc" / "tools"))
sys.path.insert(0, str(REPO / "android"))

import build_portable as bp      # noqa: E402
import make_keystore as mk       # noqa: E402

PSF = "CN=Python Software Foundation, O=Python Software Foundation, L=Beaverton, S=Oregon, C=US"
GOOGLE = "CN=Google LLC, O=Google LLC, L=Mountain View, S=California, C=US, SERIALNUMBER=3582691"


def test_signer_org_reads_the_o_field():
    assert bp.signer_org(PSF) == "Python Software Foundation"
    assert bp.signer_org(GOOGLE) == "Google LLC"
    assert bp.signer_org('CN=x, O="Some, Company", C=US') == "Some, Company"
    assert bp.signer_org("CN=only a name") == ""


def test_real_signers_pass(monkeypatch):
    monkeypatch.setattr(bp, "log", lambda text: None)
    monkeypatch.setattr(bp, "signer", lambda path: ("Valid", GOOGLE))
    bp.must_be_signed(Path("adb.exe"), "Google")
    monkeypatch.setattr(bp, "signer", lambda path: ("Valid", PSF))
    bp.must_be_signed(Path("python.exe"), "Python Software Foundation")


@pytest.mark.parametrize("status, subject", [
    ("Valid", "CN=Totally Not Google Fan Club, O=Somebody Else Ltd, C=XX"),      # the word in the name only
    ("Valid", "CN=Google LLC, O=Google LLC Fan Club, C=XX"),                    # a longer organisation
    ("Valid", "CN=Somebody, O=Somebody, OU=Google LLC"),                        # the name in another field
    ("NotSigned", ""),
    ("HashMismatch", GOOGLE),                                                   # the right signer, a changed file
])
def test_look_alike_signers_stop_the_build(monkeypatch, status, subject):
    monkeypatch.setattr(bp, "signer", lambda path: (status, subject))
    with pytest.raises(SystemExit):
        bp.must_be_signed(Path("adb.exe"), "Google")


def _apksigner_says(monkeypatch, text):
    monkeypatch.setattr(bp.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=text, stderr="", returncode=0))


def test_phone_app_is_judged_by_the_key_fingerprint(monkeypatch):
    head = "Verifies\nNumber of signers: 1\nSigner #1 certificate DN: CN=Taco Cam, O=Taco Cam\n"
    _apksigner_says(monkeypatch, head + "Signer #1 certificate SHA-256 digest: " + bp.APK_CERT_SHA256 + "\n")
    assert bp.apk_signer_ok(Path("app-release.apk"))
    _apksigner_says(monkeypatch, head + "Signer #1 certificate SHA-256 digest: " + "ab" * 32 + "\n")
    assert not bp.apk_signer_ok(Path("app-release.apk"))            # the right name on another key
    _apksigner_says(monkeypatch, head)
    assert not bp.apk_signer_ok(Path("app-release.apk"))
    two = (head + "Signer #1 certificate SHA-256 digest: " + bp.APK_CERT_SHA256 + "\n"
           "Signer #2 certificate SHA-256 digest: " + "ab" * 32 + "\n")
    _apksigner_says(monkeypatch, two)
    assert not bp.apk_signer_ok(Path("app-release.apk"))            # a second signer next to ours


def test_cached_python_zip_must_be_the_known_file(tmp_path, monkeypatch):
    v = sys.version_info
    name = f"python-{v.major}.{v.minor}.{v.micro}-embed-amd64.zip"
    monkeypatch.setattr(bp, "BUILD", tmp_path / "portable")
    monkeypatch.setattr(bp, "log", lambda text: None)
    cached = tmp_path / name
    cached.write_bytes(b"x" * 2_000_000)                            # big enough for the old check, not the real file

    def no_download(*a, **k):
        raise OSError("no network in tests")

    monkeypatch.setattr(bp.urllib.request, "urlopen", no_download)
    monkeypatch.setitem(bp.EMBED_SHA256, f"{v.major}.{v.minor}.{v.micro}", "0" * 64)
    with pytest.raises(OSError):
        bp.embed_zip()                                              # it went to fetch a fresh one
    assert not cached.exists()
    monkeypatch.setitem(bp.EMBED_SHA256, f"{v.major}.{v.minor}.{v.micro}", bp.sha256_of(_write(cached, b"known")))
    assert bp.embed_zip() == cached


def _write(path, data):
    path.write_bytes(data)
    return path


def test_unknown_python_version_stops_the_build(monkeypatch):
    monkeypatch.setattr(bp, "EMBED_SHA256", {})
    with pytest.raises(SystemExit):
        bp.embed_zip()


def test_builder_folder_is_found_in_text_and_utf16(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "Made Up Builder")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "clean.py").write_text("print('C:\\\\Users\\\\Public')", encoding="utf-8")
    (tmp_path / "a" / "compiled.pyc").write_bytes(b"\x00\x01C:\\Users\\made up builder\\AppData\\Local\\Temp\\x.py\x00")
    (tmp_path / "launcher.exe").write_bytes("MZ...C:/users/Made Up Builder/python.exe".encode("utf-16-le"))
    assert bp.files_with_builder_marks(tmp_path) == ["a/compiled.pyc", "launcher.exe"]
    with pytest.raises(SystemExit) as e:
        bp.must_be_clean(tmp_path, "the folder to pack")
    assert "Made Up Builder" not in str(e.value) and "compiled.pyc" in str(e.value)
    (tmp_path / "a" / "compiled.pyc").unlink()
    (tmp_path / "launcher.exe").unlink()
    monkeypatch.setattr(bp, "log", lambda text: None)
    bp.must_be_clean(tmp_path, "the folder to pack")


def test_keytool_is_never_taken_from_the_current_folder(tmp_path, monkeypatch):
    (tmp_path / "keytool.cmd").write_text("", encoding="ascii")
    (tmp_path / "keytool.exe").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setenv("NoDefaultCurrentDirectoryInExePath", "")
    try:
        found = mk.keytool()
    except SystemExit:
        return                                                      # no JDK on this PC: refusing is right
    assert Path(found).resolve().parent != tmp_path.resolve() and found.lower().endswith(".exe")


def test_new_key_password_is_not_on_the_command_line(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env") or {}
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(mk, "JKS", tmp_path / "k.jks")
    monkeypatch.setattr(mk, "PROPS", tmp_path / "k.properties")
    monkeypatch.setattr(mk, "keytool", lambda: "keytool.exe")
    monkeypatch.setattr(mk.subprocess, "run", fake_run)
    assert mk.main() == 0
    password = seen["env"]["TACOCAM_NEW_KEY_PASS"]
    assert len(password) >= 24 and password not in " ".join(seen["cmd"])
    assert "-storepass:env" in seen["cmd"] and "-keypass:env" in seen["cmd"]
    assert "TACOCAM_NEW_KEY_PASS" not in os.environ
