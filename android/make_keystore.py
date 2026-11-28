"""Make the release signing key for the Taco Cam Android app, once, on the developer PC.

    python android/make_keystore.py      -> D:\\DevTools\\tacocam-release.jks + D:\\DevTools\\tacocam-keystore.properties

Android installs an update only when it is signed with the same key as the copy on the phone, so this key must
be kept (and backed up) for as long as friends use the app. It never goes into git; the password is random and
stays in the .properties file next to it (never printed). Building with TACOCAM_KEYSTORE pointing at the
.properties file signs the release APK with it (app/build.gradle.kts).
"""
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

DIR = Path(os.environ.get("TACOCAM_DEVTOOLS", r"D:\DevTools"))
JKS = DIR / "tacocam-release.jks"
PROPS = DIR / "tacocam-keystore.properties"


def keytool():
    """keytool.exe by its full path: JAVA_HOME, an installed JDK, then PATH. Never a file from the current
    folder, and only a real .exe: this program is handed the new key's password (WEBCAM-20261128-03)."""
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / "keytool.exe").exists():
        return str(Path(home) / "bin" / "keytool.exe")
    for jdk in sorted(Path(r"C:\Program Files\Microsoft").glob("jdk-*"), reverse=True):
        if (jdk / "bin" / "keytool.exe").exists():
            return str(jdk / "bin" / "keytool.exe")
    os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"     # shutil.which: don't look in the current folder
    found = shutil.which("keytool.exe")
    if found and Path(found).suffix.lower() == ".exe" and Path(found).resolve().parent != Path.cwd().resolve():
        return found
    raise SystemExit("keytool not found: install a JDK (Microsoft OpenJDK 21)")


def main():
    if JKS.exists() and PROPS.exists():
        print("The key is there already:", JKS)
        return 0
    if JKS.exists() or PROPS.exists():
        raise SystemExit(f"Only half of the key is there ({JKS} / {PROPS}): restore it from the backup")
    password = secrets.token_urlsafe(24)
    # the password goes to keytool through its environment, not its command line (other programs can read that)
    subprocess.run([keytool(), "-genkeypair", "-keystore", str(JKS), "-storetype", "PKCS12", "-alias", "tacocam",
                    "-keyalg", "RSA", "-keysize", "3072", "-validity", "18250",
                    "-dname", "CN=Taco Cam, O=Taco Cam", "-storepass:env", "TACOCAM_NEW_KEY_PASS",
                    "-keypass:env", "TACOCAM_NEW_KEY_PASS"],
                   check=True, capture_output=True, env=dict(os.environ, TACOCAM_NEW_KEY_PASS=password))
    PROPS.write_text(f"storeFile={JKS.as_posix()}\nstorePassword={password}\nkeyAlias=tacocam\nkeyPassword={password}\n",
                     encoding="utf-8")
    print("Made", JKS, "and", PROPS, "(back both up; never put them in git)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
