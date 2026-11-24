@echo off
chcp 65001 >nul
title Video Variator
cd /d "%~dp0"

rem ---------- Python ----------
set "PY="
set "PYW="
py -3 --version >nul 2>&1 && (set "PY=py -3" & set "PYW=pyw -3")
if not defined PY (
    python --version >nul 2>&1 && (set "PY=python" & set "PYW=pythonw")
)
if not defined PY goto install_python

rem ---------- FFmpeg ----------
where ffmpeg >nul 2>&1 && goto check_libs
if exist "%~dp0ffmpeg.exe" goto check_libs
if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe" goto check_libs
echo.
echo [1/2] FFmpeg не знайдено. Встановлюю через winget...
winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo Не вдалося встановити FFmpeg автоматично.
    echo Завантажте його вручну: https://www.gyan.dev/ffmpeg/builds/
    echo і покладіть ffmpeg.exe та ffprobe.exe в цю папку.
    pause
    exit /b 1
)

:check_libs
rem ---------- CustomTkinter ----------
%PY% -c "import customtkinter, PIL, tkinterdnd2" >nul 2>&1 && goto run
echo.
echo [2/2] Встановлюю бібліотеки CustomTkinter, Pillow і tkinterdnd2...
%PY% -m pip install --user --upgrade customtkinter pillow tkinterdnd2
if errorlevel 1 (
    echo Не вдалося встановити бібліотеки. Перевірте інтернет і спробуйте ще раз.
    pause
    exit /b 1
)

:run
start "" %PYW% "%~dp0video_variator.py"
exit /b 0

:install_python
echo.
echo Python не знайдено. Встановлюю Python 3.12 через winget...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo Не вдалося встановити автоматично. Завантажте Python з https://www.python.org/downloads/
    echo і під час встановлення поставте галочку "Add python.exe to PATH".
    pause
    exit /b 1
)
echo.
echo Python встановлено. Закрийте це вікно і запустіть "Запуск.bat" ще раз.
pause
exit /b 0
