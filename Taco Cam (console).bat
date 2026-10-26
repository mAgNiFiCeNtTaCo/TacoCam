@echo off
rem Taco Cam with a console window, for troubleshooting (errors show here and in taco-cam.log)
cd /d "%~dp0pc"
python -m tacocam
echo.
echo Taco Cam closed. If something went wrong, see taco-cam.log in the Webcam folder.
pause
