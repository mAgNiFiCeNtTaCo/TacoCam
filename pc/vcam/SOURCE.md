# Virtual camera: where these files come from

The "Taco Cam" camera that OBS sees is the **Unity Capture** DirectShow filter by Bernhard Schelling,
registered under our own name. The DLLs are unchanged copies from the official repository.

- Source: https://github.com/schellingb/UnityCapture, folder `Install/`
- Commit: `3ed54c325e0ad71afcf4f246c07e5e17b3d7f2d2` (2023-04-14, "New release with new DLL files (#33)")
- Downloaded: 2026-10-25 from https://codeload.github.com/schellingb/UnityCapture/zip/refs/heads/master
  (zip SHA-256 `a89c44940bfb6aa33859dc3fdf87a7383bef063a3c9d81c817a60d5cb63d5a0d`)
- Licence: MIT for the filter (see `LICENSE-UnityCapture.txt`; the repo keeps its licence in the README
  and the source file header, it has no separate LICENSE file).

| File | SHA-256 |
|---|---|
| `UnityCaptureFilter32.dll` | `aa3ebdf03dea7f3aab3dd7b724751f49ed71672256b57c6a19aa6809cabf30ba` |
| `UnityCaptureFilter64.dll` | `72812f5363d8ecb45632253f8c8c888844b1b62e27616f3c8cc21064ccde25e5` |
| `unitycapture-original/Install.bat` | `18335923b497ff4b029032fbf7bbd666976e2d2c9973a6067736a4b9f31dcb25` |
| `unitycapture-original/InstallCustomName.bat` | `14263cd7afa640929baeec96ccc9e006889b185c6c0a5114928ddf616d4a11be` |
| `unitycapture-original/InstallMultipleDevices.bat` | `5dbe62d14fc7fbd56810c640b6837b7f0cf59ec0b090ff810e710a695b4d2555` |
| `unitycapture-original/Uninstall.bat` | `756f268a907a09e9c54a45e041fc51507c137bcb19f7b37b620b1c037b93437e` |
| `unitycapture-original/README.md` | `8517678f6d9c744c17d6159cdf03b75196f6d982b694c1a90e7911ba100e8c7f` |

`unitycapture-original/` holds the repo's own install scripts and README for reference; use our two
scripts instead.

## What the source says (Source/UnityCaptureFilter.cpp, Source/shared.inl at that commit)

- **Custom name:** `RegisterFilters()` reads `/i:UnityCaptureName=NAME` from regsvr32's command line
  (quotes allowed: `"/i:UnityCaptureName=Taco Cam"`, name 1..199 characters). That is what the repo's
  `InstallCustomName.bat` does. Our `Install Taco Cam camera.bat` runs
  `regsvr32 /s "/i:UnityCaptureName=Taco Cam" UnityCaptureFilter64.dll` (System32) and the same for
  `UnityCaptureFilter32.dll` (SysWOW64). One device (no `/i:UnityCaptureDevices=`), so its name has no
  " #2" suffix.
- **Where it is registered:** 64-bit filter CLSID `{5C2CD55C-92AD-4999-8666-912BD3E70010}`, 32-bit
  `{5C2CD55C-92AD-4999-8666-912BD3E70020}` (separate GUIDs so both coexist), in the DirectShow
  "Video Input Device" category. `pc/tacocam/vcam.py` reads that CLSID's default value to tell whether
  "Taco Cam" is installed.
- **Uninstall:** `regsvr32 /u` removes every Unity Capture device of that DLL whatever its name.
- **Largest frame:** shared memory is `3840 * 2160 * 4 * 2` bytes (`MAX_SHARED_IMAGE_SIZE`), so up to
  3840x2160 (portrait 2160x3840 is the same size). Resolutions it offers to apps: 1920x1080, 1280x720,
  960x540, 640x360, 480x270, 256x144, 2560x1440, 3840x2160, several 4:3 and 16:10 sizes, plus one
  custom slot an app can ask for. Portrait outputs (1080x1920, 2160x3840) are not in the list: in OBS
  set the Video Capture Device to Resolution/FPS Type "Custom" and type the size. Width must be a
  multiple of 4 (all our sizes are).
- **When nothing is sent** the filter draws its own pattern (Unity "never started" / "stopped sending"),
  which is why the engine keeps sending a "waiting for iPhone" card instead.

## OBS 32 compatibility (checked 2026-10-25)

OBS blocks Unity Capture builds that have a deadlock during device enumeration
(UnityCapture issues #33 and #35; OBS `frontend/utility/win-dll-blocklist.c`). The block names only
the old DLL file `unitycapturefilter64bit.dll`. The fix is commit 2eabf0f, shipped in the 2023-04-14
release whose DLLs were renamed to `UnityCaptureFilter64.dll` / `UnityCaptureFilter32.dll`: the files
here. The maintainer and an OBS developer confirmed in issue #35 that this release shows up in OBS
29.1+ again. So it is expected to work with OBS 32.2.2; if it ever does not, the engine falls back to
the OBS Virtual Camera backend.
