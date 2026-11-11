@echo off
setlocal
title Install the Taco Cam camera
rem Registers the Unity Capture DirectShow filter as ONE camera named "Taco Cam".
rem Windows loads the two DLLs into every program that lists cameras, so they must sit where only
rem administrators can change them. This script copies them to "%ProgramFiles%\Taco Cam", checks the copies
rem against the SHA-256 values in SOURCE.md and registers them from there (never from this folder).
rem Needs administrator rights: asks Windows (UAC) for them by itself. Close OBS first when re-installing.

set "HASH64=72812f5363d8ecb45632253f8c8c888844b1b62e27616f3c8cc21064ccde25e5"
set "HASH32=aa3ebdf03dea7f3aab3dd7b724751f49ed71672256b57c6a19aa6809cabf30ba"
set "CLSID64=HKLM\SOFTWARE\Classes\CLSID\{5C2CD55C-92AD-4999-8666-912BD3E70010}"

fltmc >nul 2>&1
if errorlevel 1 goto elevate
goto install

:elevate
echo Asking Windows for permission to install the Taco Cam camera...
set "TC_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath $env:TC_SELF -Verb RunAs -ErrorAction Stop } catch { Write-Host 'Windows did not give permission, so nothing was installed.'; exit 1 }"
if errorlevel 1 pause
exit /b

:install
cd /d "%~dp0"
set "DEST=%ProgramFiles%\Taco Cam"
if exist "%~dp0UnityCaptureFilter64.dll" goto havedll
echo UnityCaptureFilter64.dll is missing from "%~dp0"
pause
exit /b 1
:havedll
echo Installing the "Taco Cam" camera into "%DEST%"
if not exist "%DEST%\" mkdir "%DEST%"
copy /y /b "%~dp0UnityCaptureFilter64.dll" "%DEST%\UnityCaptureFilter64.dll" >nul
if errorlevel 1 goto copyfailed
rem Only the copy in the protected folder is checked and used: nothing can swap it after the check.
call :checkhash "%DEST%\UnityCaptureFilter64.dll" %HASH64%
if errorlevel 1 goto badfile
rem Remove an older registration first (it may point at the project folder), then register this copy.
"%SystemRoot%\System32\regsvr32.exe" /s /u "%DEST%\UnityCaptureFilter64.dll"
"%SystemRoot%\System32\regsvr32.exe" /s "/i:UnityCaptureName=Taco Cam" "%DEST%\UnityCaptureFilter64.dll"
if errorlevel 1 goto regfailed

if not exist "%SystemRoot%\SysWOW64\regsvr32.exe" goto verify
if not exist "%~dp0UnityCaptureFilter32.dll" goto no32
copy /y /b "%~dp0UnityCaptureFilter32.dll" "%DEST%\UnityCaptureFilter32.dll" >nul
if errorlevel 1 goto no32
call :checkhash "%DEST%\UnityCaptureFilter32.dll" %HASH32%
if errorlevel 1 goto bad32
"%SystemRoot%\SysWOW64\regsvr32.exe" /s /u "%DEST%\UnityCaptureFilter32.dll"
"%SystemRoot%\SysWOW64\regsvr32.exe" /s "/i:UnityCaptureName=Taco Cam" "%DEST%\UnityCaptureFilter32.dll"
if errorlevel 1 echo Note: the 32-bit part could not be registered; OBS does not need it.
goto verify
:bad32
del /f /q "%DEST%\UnityCaptureFilter32.dll" >nul 2>&1
echo Note: UnityCaptureFilter32.dll is not the original file, so the 32-bit part was not installed. OBS does not need it.
goto verify
:no32
echo Note: the 32-bit part could not be copied; OBS does not need it. If it was installed before, run Uninstall first.

:verify
reg query "%CLSID64%" /ve | "%SystemRoot%\System32\find.exe" "Taco Cam" >nul
if errorlevel 1 goto notregistered
reg query "%CLSID64%\InprocServer32" /ve | "%SystemRoot%\System32\find.exe" /i "%DEST%\UnityCaptureFilter64.dll" >nul
if errorlevel 1 goto wrongfolder
echo.
echo Done. "Taco Cam" is installed. Restart OBS, then add a "Video Capture Device" and pick "Taco Cam".
pause
exit /b 0

:copyfailed
echo FAILED: could not copy UnityCaptureFilter64.dll to "%DEST%".
echo Close OBS and every other program that uses a camera, then run this again.
pause
exit /b 1

:badfile
del /f /q "%DEST%\UnityCaptureFilter64.dll" >nul 2>&1
echo FAILED: UnityCaptureFilter64.dll in "%~dp0" is not the original file.
echo Its SHA-256 does not match SOURCE.md. Nothing was installed. Get the project files again.
pause
exit /b 1

:regfailed
echo FAILED: Windows could not register UnityCaptureFilter64.dll.
pause
exit /b 1

:notregistered
echo FAILED: the camera is not registered as "Taco Cam".
pause
exit /b 1

:wrongfolder
echo FAILED: the camera is still registered from another folder. Run "Uninstall Taco Cam camera.bat", then this again.
pause
exit /b 1

rem ---- call :checkhash "file" expected-sha256   (errorlevel 0 = the file has that SHA-256)
:checkhash
set "GOT="
for /f "skip=1 delims=" %%H in ('%SystemRoot%\System32\certutil.exe -hashfile "%~1" SHA256') do if not defined GOT set "GOT=%%H"
if not defined GOT exit /b 1
set "GOT=%GOT: =%"
if /i "%GOT%"=="%~2" exit /b 0
exit /b 1
