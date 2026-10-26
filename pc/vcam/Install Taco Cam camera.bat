@echo off
setlocal
title Install the Taco Cam camera
rem Registers the Unity Capture DirectShow filter (both DLLs in this folder) as ONE camera named "Taco Cam".
rem Needs administrator rights: asks Windows (UAC) for them by itself. Keep this folder where it is:
rem Windows loads the DLLs from here. Moving the folder? Run Uninstall first, move, then Install again.

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
if exist "%~dp0UnityCaptureFilter64.dll" goto havedll
echo UnityCaptureFilter64.dll is missing from "%~dp0"
pause
exit /b 1
:havedll
echo Installing the "Taco Cam" camera from "%~dp0"
"%SystemRoot%\System32\regsvr32.exe" /s "/i:UnityCaptureName=Taco Cam" "%~dp0UnityCaptureFilter64.dll"
if errorlevel 1 (
    echo FAILED: Windows could not register UnityCaptureFilter64.dll.
    pause
    exit /b 1
)
if exist "%SystemRoot%\SysWOW64\regsvr32.exe" (
    "%SystemRoot%\SysWOW64\regsvr32.exe" /s "/i:UnityCaptureName=Taco Cam" "%~dp0UnityCaptureFilter32.dll"
    if errorlevel 1 echo Note: the 32-bit part could not be registered; OBS (64-bit^) does not need it.
)
reg query "HKLM\SOFTWARE\Classes\CLSID\{5C2CD55C-92AD-4999-8666-912BD3E70010}" /ve | "%SystemRoot%\System32\find.exe" "Taco Cam" >nul
if errorlevel 1 (
    echo FAILED: the camera is not registered as "Taco Cam".
    pause
    exit /b 1
)
echo.
echo Done. "Taco Cam" is installed. Restart OBS, then add a "Video Capture Device" and pick "Taco Cam".
pause
exit /b 0
