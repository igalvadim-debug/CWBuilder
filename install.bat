@echo off
rem CWBuilder — Installation der Python-Umgebung (Windows).
rem 1) Interpreter: vorhandener venv -> Python 3.12 -> py -3.12 -> python,
rem 2) Ruft install.py auf: venv ./venv + requirements.txt + Modelle prüfen,
rem 3) Nach Installation: start.bat starten.
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title CWBuilder install

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "%~dp0install.py" (
    echo [fail] install.py nicht gefunden in diesem Ordner.
    pause
    exit /b 1
)

rem Installations-Interpreter: venv (geprueft) -> lokale 3.12 -> py -3.12 (geprueft) -> python aus PATH.
rem PYPYEXE = ausfuehrbare Datei (wird immer quoted aufgerufen), PYARGS = optionale Argumente (z.B. -3.12).
set "VERCHK=import sys; sys.exit(0 if sys.version_info ^>= (3, 12) else 1)"

rem --- venv vorhanden: nur verwenden, wenn er wirklich startet und Python >= 3.12 meldet.
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" -c "%VERCHK%" >nul 2>&1
    if not errorlevel 1 (
        set "PYPYEXE=%~dp0venv\Scripts\python.exe"
        set "PYARGS="
        goto exec
    )
)

rem Bekannte lokale Python 3.12 Installationen (wird zuerst geprüft).
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

rem Fallback: py-Launcher — erst pruefen, ob 3.12 wirklich installiert ist.
where py >nul 2>&1
if errorlevel 1 goto path_python
py -3.12 -c "%VERCHK%" >nul 2>&1
if not errorlevel 1 (
    set "PYPYEXE=py"
    set "PYARGS=-3.12"
    goto exec
)

:path_python
rem Letzter Ausweg: python aus PATH — erst Version pruefen, dann installieren.
where python >nul 2>&1
if errorlevel 1 goto no_python
python -c "%VERCHK%" >nul 2>&1
if errorlevel 1 goto bad_python
set "PYPYEXE=python"
set "PYARGS="

:exec
echo === CWBuilder Installation (alles lokal in diesem Ordner) ===
rem Der Zielpfad von cd /d endet auf "\" — "%~dp0." verhindert einen doppelten
rem Backslash ("...\\"), der sonst Windows-Fehler wie "No Python at '...'" ausloest.
call "!PYPYEXE!" !PYARGS! "%~dp0.\install.py" %*

if errorlevel 1 (
    echo.
    echo [fail] Installation nicht abgeschlossen. Siehe Meldungen oben.
    pause
    exit /b 1
)

echo.
choice /c YN /m "Installation abgeschlossen. Jetzt starten (start.bat)?"
if errorlevel 2 goto end
call "%~dp0start.bat"

:end
endlocal
exit /b 0

:no_python
echo [fail] Kein Python gefunden.
echo        Installieren Sie Python 3.12+ (https://python.org, "Add to PATH" aktivieren)
echo        und wiederholen Sie die Installation, oder starten Sie explizit:
echo            python install.py --python "C:\Pfad\zu\python.exe"
pause
exit /b 1

:bad_python
echo [fail] Python in PATH gefunden, aber Version ^< 3.12 — nicht unterstützt.
echo        Installieren Sie Python 3.12+ (https://python.org), oder geben Sie explizit an:
echo            python install.py --python "C:\Pfad\zu\python3.12.exe"
pause
exit /b 1
