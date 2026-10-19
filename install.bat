@echo off
rem CWBuilder - Installation der Python-Umgebung (Windows).
rem 1) Sucht ein funktionierendes Python 3.12+ (venv, lokal, py-Launcher, PATH),
rem 2) ruft install.py auf: venv ./venv + requirements.txt,
rem 3) danach optional start.bat.
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title CWBuilder install

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem Gemeinsamer Versionscheck: bricht unter Python 3.12 mit Exit-Code 1 ab.
set "VERCHK=import sys; sys.exit(0 if sys.version_info ^>= (3, 12) else 1)"
set "PYARGS="
set "PYPYEXE="

if not exist "%~dp0install.py" (
    echo [fehler] install.py nicht gefunden in diesem Ordner.
    pause
    exit /b 1
)

rem Vorhandene venv nur nehmen, wenn ihr Python wirklich startet.
rem Eine von Linux kopierte venv zeigt auf /usr/local/bin und ist defekt.
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" -c "%VERCHK%" >nul 2>&1
    if not errorlevel 1 (
        set "PYPYEXE=%~dp0venv\Scripts\python.exe"
        goto exec
    )
    echo [warnung] venv ist defekt oder zu alt - install.py ersetzt sie durch eine neue.
)

rem Bekannte lokale Python-3.12-Installationen zuerst pruefen.
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYPYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    set "PYARGS="
    goto exec
)
if exist "C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PYPYEXE=C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe"
    set "PYARGS="
    goto exec
)

rem Fallback: py-Launcher, dann python im PATH.
where py >nul 2>&1
if errorlevel 1 goto path_python
py -3.12 -c "%VERCHK%" >nul 2>&1
if not errorlevel 1 (
    set "PYPYEXE=py"
    set "PYARGS=-3.12"
    goto exec
)

:path_python
where python >nul 2>&1
if errorlevel 1 goto no_python
rem install.py braucht CPython ab 3.12.
python -c "%VERCHK%" >nul 2>&1
if errorlevel 1 goto bad_python
set "PYPYEXE=python"
set "PYARGS="

:exec
echo === CWBuilder Installation (alles lokal in diesem Ordner) ===
call "!PYPYEXE!" !PYARGS! "%~dp0.\install.py" %*
if errorlevel 1 (
    echo.
    echo [fehler] Installation nicht abgeschlossen. Siehe Meldungen oben.
    pause
    exit /b 1
)

echo.
choice /c YN /m "Installation fertig. Jetzt start.bat starten"
if errorlevel 2 goto end
call "%~dp0start.bat"

:end
endlocal
exit /b 0

:no_python
echo [fehler] Python nicht gefunden.
echo          Bitte Python 3.12 oder neuer installieren (https://python.org) und erneut starten,
echo          oder direkt: python install.py --python "C:\Pfad\zu\python.exe"
pause
exit /b 1

:bad_python
echo [fehler] Python im PATH gefunden, aber Version ^< 3.12 - nicht unterstuetzt.
echo          Bitte Python 3.12 oder neuer installieren (https://python.org),
echo          oder direkt: python install.py --python "C:\Pfad\zu\python3.12.exe"
pause
exit /b 1
