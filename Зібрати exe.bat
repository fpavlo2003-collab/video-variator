@echo off
chcp 65001 >nul
title Збірка VideoVariator.exe
cd /d "%~dp0"
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY (
    echo Спочатку запустіть "Запуск.bat" — він встановить Python.
    pause
    exit /b 1
)
echo [1/2] Встановлюю PyInstaller і бібліотеки...
%PY% -m pip install --user --upgrade pyinstaller customtkinter pillow tkinterdnd2
echo.
echo [2/2] Збираю VideoVariator.exe (1-3 хвилини)...
%PY% -m PyInstaller --noconfirm --onefile --windowed --name VideoVariator ^
    --collect-all customtkinter --collect-all tkinterdnd2 video_variator.py
if errorlevel 1 (
    echo Збірка не вдалася. Надішліть скриншот цього вікна.
    pause
    exit /b 1
)
copy /y "dist\VideoVariator.exe" "VideoVariator.exe" >nul
echo.
echo Готово! Файл VideoVariator.exe лежить у цій папці.
echo Друзям потрібен ще FFmpeg: або встановлений (winget install Gyan.FFmpeg),
echo або ffmpeg.exe та ffprobe.exe, покладені поруч із VideoVariator.exe.
pause
