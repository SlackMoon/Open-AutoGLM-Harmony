@echo off
setlocal
cd /d "%~dp0"
python -u gui_app.py
set "autoglm_exit_code=%errorlevel%"
if not "%autoglm_exit_code%"=="0" (
    echo GUI exited with code %autoglm_exit_code%.
    echo Check logs\runtime.log and logs\crash.log for details.
    pause
)
exit /b %autoglm_exit_code%
