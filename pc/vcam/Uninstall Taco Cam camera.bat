@echo off
setlocal
title Uninstall the Taco Cam camera
rem Removes the "Taco Cam" camera (the Unity Capture DirectShow filter registered by "Install Taco Cam camera.bat").
rem Needs administrator rights: asks Windows (UAC) for them by itself. Close OBS and other camera apps first.

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
echo Removing the "Taco Cam" camera...
"%SystemRoot%\System32\regsvr32.exe" /s /u "%~dp0UnityCaptureFilter64.dll"
if errorlevel 1 echo Note: the 64-bit part was not registered or could not be removed.
if exist "%SystemRoot%\SysWOW64\regsvr32.exe" (
    "%SystemRoot%\SysWOW64\regsvr32.exe" /s /u "%~dp0UnityCaptureFilter32.dll"
    if errorlevel 1 echo Note: the 32-bit part was not registered or could not be removed.
)
reg query "HKLM\SOFTWARE\Classes\CLSID\{5C2CD55C-92AD-4999-8666-912BD3E70010}" >nul 2>&1
if not errorlevel 1 (
    echo FAILED: the camera is still registered. Close OBS and try again.
    pause
    exit /b 1
)
echo.
echo Done. The "Taco Cam" camera is removed.
pause
exit /b 0
