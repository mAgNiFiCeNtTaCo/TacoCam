@echo off
rem Taco Cam: starts the control window with no console window (log: taco-cam.log)
cd /d "%~dp0pc"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw -m tacocam
) else (
    where pyw >nul 2>nul
    if %errorlevel%==0 (
        start "" pyw -m tacocam
    ) else (
        echo Python was not found. Install Python 3 from python.org, then try again.
        pause
    )
)
