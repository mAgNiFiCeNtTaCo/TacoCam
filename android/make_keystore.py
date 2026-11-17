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
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / "keytool.exe").exists():
        return str(Path(home) / "bin" / "keytool.exe")
    found = shutil.which("keytool")
    if found:
        return found
    for jdk in sorted(Path(r"C:\Program Files\Microsoft").glob("jdk-*"), reverse=True):
        if (jdk / "bin" / "keytool.exe").exists():
            return str(jdk / "bin" / "keytool.exe")
    raise SystemExit("keytool not found: install a JDK (Microsoft OpenJDK 21)")


def main():
    if JKS.exists() and PROPS.exists():
        print("The key is there already:", JKS)
        return 0
    if JKS.exists() or PROPS.exists():
        raise SystemExit(f"Only half of the key is there ({JKS} / {PROPS}): restore it from the backup")
    password = secrets.token_urlsafe(24)
    subprocess.run([keytool(), "-genkeypair", "-keystore", str(JKS), "-storetype", "PKCS12", "-alias", "tacocam",
                    "-keyalg", "RSA", "-keysize", "3072", "-validity", "18250",
                    "-dname", "CN=Taco Cam, O=Taco Cam", "-storepass", password, "-keypass", password],
                   check=True, capture_output=True)
    PROPS.write_text(f"storeFile={JKS.as_posix()}\nstorePassword={password}\nkeyAlias=tacocam\nkeyPassword={password}\n",
                     encoding="utf-8")
    print("Made", JKS, "and", PROPS, "(back both up; never put them in git)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
