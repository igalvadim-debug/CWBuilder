@echo off
rem CWBuilder - Installation der Python-Umgebung (Windows).
rem 1) Sucht ein funktionierendes Python 3.12 (venv, lokal, py-Launcher, PATH),
rem 2) ruft install.py auf: venv ./venv + requirements.txt,
rem 3) danach optional start.bat.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title CWBuilder install

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYARGS="
set "PYPATH="

if not exist "install.py" (
    echo [fehler] install.py nicht gefunden in diesem Ordner.
    pause
    exit /b 1
)

rem Vorhandene venv nur nehmen, wenn ihr Python wirklich startet.
rem Eine von Linux kopierte venv zeigt auf /usr/local/bin und ist defekt.
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYPATH=venv\Scripts\python.exe"
        goto run
    )
    echo [warnung] venv ist defekt - install.py ersetzt sie durch eine neue.
)

rem Bekannte lokale Python-3.12-Installation zuerst pruefen.
if exist "C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PYPATH=C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe"
    set "PYARGS="
    goto run
)

rem Fallback: py-Launcher, dann python im PATH.
where py >nul 2>&1
if errorlevel 1 goto try_python
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYPATH=py"
    set "PYARGS=-3.12"
    goto run
)
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYPATH=py"
    set "PYARGS=-3"
    goto run
)

:try_python
where python >nul 2>&1
if errorlevel 1 goto no_python
rem install.py braucht CPython ab 3.12.
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto bad_python
set "PYPATH=python"
set "PYARGS="

:run
echo === CWBuilder Installation (alles lokal in diesem Ordner) ===
rem Nur der Pfad zur exe steht in Anfuehrungszeichen, py-Optionen bleiben getrennte Argumente.
"%PYPATH%" %PYARGS% install.py %*
if errorlevel 1 (
    echo.
    echo [fehler] Installation nicht abgeschlossen. Siehe Meldungen oben.
    pause
    exit /b 1
)

echo.
choice /c JN /m "Installation fertig. Jetzt start.bat starten"
if errorlevel 2 goto end
call start.bat

:end
endlocal
exit /b 0

:no_python
echo [fehler] Python nicht gefunden.
echo          Bitte Python 3.12 oder neuer installieren (https://python.org) und erneut starten,
echo          oder direkt: "C:\Pfad\zu\python.exe" install.py
pause
exit /b 1

:bad_python
echo [fehler] Python im PATH gefunden, aber aelter als 3.12 - nicht unterstuetzt.
echo          Bitte Python 3.12 oder neuer installieren (https://python.org),
echo          oder direkt: "C:\Pfad\zu\python3.12.exe" install.py
pause
exit /b 1