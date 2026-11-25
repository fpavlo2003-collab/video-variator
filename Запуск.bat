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
if not defined PY call :find_local_python
if not defined PY goto install_python

:check_ffmpeg
rem ---------- FFmpeg ----------
where ffmpeg >nul 2>&1 && goto check_libs
if exist "%~dp0ffmpeg.exe" goto check_libs
if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe" goto check_libs
echo.
echo [1/2] FFmpeg не знайдено. Завантажую (~90 МБ)...
where winget >nul 2>&1 && (
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements && goto check_libs
)
set "FFZIP=%TEMP%\vv_ffmpeg.zip"
curl -L --fail -o "%FFZIP%" "https://github.com/GyanD/codexffmpeg/releases/download/8.0/ffmpeg-8.0-full_build-shared.zip"
if errorlevel 1 powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing 'https://github.com/GyanD/codexffmpeg/releases/download/8.0/ffmpeg-8.0-full_build-shared.zip' -OutFile '%FFZIP%'"
if not exist "%FFZIP%" goto ffmpeg_fail
if exist "%TEMP%\vv_ffmpeg" rmdir /s /q "%TEMP%\vv_ffmpeg"
powershell -NoProfile -Command "Expand-Archive -Force '%FFZIP%' '%TEMP%\vv_ffmpeg'"
for /d %%D in ("%TEMP%\vv_ffmpeg\*") do xcopy /y /q "%%D\bin\*" "%~dp0" >nul
del /q "%~dp0ffplay.exe" >nul 2>&1
del /q "%FFZIP%" >nul 2>&1
rmdir /s /q "%TEMP%\vv_ffmpeg" >nul 2>&1
if not exist "%~dp0ffmpeg.exe" goto ffmpeg_fail

:check_libs
rem ---------- Бібліотеки ----------
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

:find_local_python
for %%V in (313 312 311 310) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PY="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe""
        set "PYW="%LOCALAPPDATA%\Programs\Python\Python%%V\pythonw.exe""
        exit /b 0
    )
)
exit /b 0

:install_python
echo.
echo Python не знайдено. Встановлюю Python 3.12 (~25 МБ), зачекайте 1-3 хвилини...
where winget >nul 2>&1 && (
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
)
call :find_local_python
if defined PY goto check_ffmpeg
set "PYEXE=%TEMP%\vv_python_setup.exe"
curl -L --fail -o "%PYEXE%" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
if errorlevel 1 powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile '%PYEXE%'"
if not exist "%PYEXE%" goto python_fail
"%PYEXE%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
del /q "%PYEXE%" >nul 2>&1
call :find_local_python
if defined PY (
    echo Python встановлено.
    goto check_ffmpeg
)

:python_fail
echo.
echo Не вдалося встановити Python автоматично. Завантажте його з https://www.python.org/downloads/
echo і під час встановлення поставте галочку "Add python.exe to PATH". Потім запустіть цей файл ще раз.
pause
exit /b 1

:ffmpeg_fail
echo.
echo Не вдалося завантажити FFmpeg. Завантажте "ffmpeg-release-essentials.zip" з https://www.gyan.dev/ffmpeg/builds/
echo і покладіть ffmpeg.exe та ffprobe.exe з папки bin поруч із цим файлом.
pause
exit /b 1
