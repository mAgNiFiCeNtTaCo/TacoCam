@echo off
setlocal
title Uninstall the Taco Cam camera
rem Removes the "Taco Cam" camera (the Unity Capture DirectShow filter registered by "Install Taco Cam camera.bat")
rem and its folder "%ProgramFiles%\Taco Cam". Also removes an older install that was registered from this folder.
rem Needs administrator rights: asks Windows (UAC) for them by itself. Close OBS and other camera apps first.

set "HASH64=72812f5363d8ecb45632253f8c8c888844b1b62e27616f3c8cc21064ccde25e5"
set "HASH32=aa3ebdf03dea7f3aab3dd7b724751f49ed71672256b57c6a19aa6809cabf30ba"

fltmc >nul 2>&1
if errorlevel 1 goto elevate
goto uninstall

:elevate
echo Asking Windows for permission to remove the Taco Cam camera...
set "TC_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath $env:TC_SELF -Verb RunAs -ErrorAction Stop } catch { Write-Host 'Windows did not give permission, so nothing was removed.'; exit 1 }"
if errorlevel 1 pause
exit /b

:uninstall
cd /d "%~dp0"
set "DEST=%ProgramFiles%\Taco Cam"
echo Removing the "Taco Cam" camera...
rem Use the copy in the protected folder; an install from before 2026-11-11 only has the files in this folder.
set "DLL64=%DEST%\UnityCaptureFilter64.dll"
if not exist "%DLL64%" set "DLL64=%~dp0UnityCaptureFilter64.dll"
set "DLL32=%DEST%\UnityCaptureFilter32.dll"
if not exist "%DLL32%" set "DLL32=%~dp0UnityCaptureFilter32.dll"

rem regsvr32 runs code from the DLL as administrator: only do that with the original files (SOURCE.md).
call :checkhash "%DLL64%" %HASH64%
if errorlevel 1 goto badfile
"%SystemRoot%\System32\regsvr32.exe" /s /u "%DLL64%"
if errorlevel 1 echo Note: the 64-bit part was not registered or could not be removed.
if not exist "%SystemRoot%\SysWOW64\regsvr32.exe" goto check
call :checkhash "%DLL32%" %HASH32%
if errorlevel 1 goto skip32
"%SystemRoot%\SysWOW64\regsvr32.exe" /s /u "%DLL32%"
if errorlevel 1 echo Note: the 32-bit part was not registered or could not be removed.
goto check
:skip32
echo Note: UnityCaptureFilter32.dll is missing or not the original file, so the 32-bit part was left alone.

:check
reg query "HKLM\SOFTWARE\Classes\CLSID\{5C2CD55C-92AD-4999-8666-912BD3E70010}" >nul 2>&1
if not errorlevel 1 goto stillthere
if exist "%DEST%\UnityCaptureFilter64.dll" del /f /q "%DEST%\UnityCaptureFilter64.dll"
if exist "%DEST%\UnityCaptureFilter32.dll" del /f /q "%DEST%\UnityCaptureFilter32.dll"
if exist "%DEST%\" rmdir "%DEST%" >nul 2>&1
if exist "%DEST%\UnityCaptureFilter64.dll" echo Note: "%DEST%" could not be deleted (a program still uses the camera). Delete it after a restart.
echo.
echo Done. The "Taco Cam" camera is removed.
pause
exit /b 0

:badfile
echo FAILED: "%DLL64%" is missing or not the original file (its SHA-256 does not match SOURCE.md).
echo Nothing was removed. Get the project files again, then run this once more.
pause
exit /b 1

:stillthere
echo FAILED: the camera is still registered. Close OBS and try again.
pause
exit /b 1

rem ---- call :checkhash "file" expected-sha256   (errorlevel 0 = the file has that SHA-256)
:checkhash
set "GOT="
if not exist "%~1" exit /b 1
for /f "skip=1 delims=" %%H in ('%SystemRoot%\System32\certutil.exe -hashfile "%~1" SHA256') do if not defined GOT set "GOT=%%H"
if not defined GOT exit /b 1
set "GOT=%GOT: =%"
if /i "%GOT%"=="%~2" exit /b 0
exit /b 1
