@echo off
rem CWBuilder — Installation der Python-Umgebung (Windows).
rem 1) Interpreter: vorhandener venv -> Python 3.12 -> py -3.12 -> python,
rem 2) Ruft install.py auf: venv ./venv + requirements.txt + Modelle prüfen,
rem 3) Nach Installation: start.bat starten.
setlocal
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

rem Installations-Interpreter: vorhandener venv -> CPython 3.12 -> py -> python.
rem --- venv vorhanden: direkt damit install.py aufrufen (Zeile unten ist der Aufruf).
if exist "%~dp0venv\Scripts\python.exe" (
    set "PYPATH="%~dp0venv\Scripts\python.exe""
    goto exec
)
"%~dp0venv\Scripts\python.exe" install.py %*

rem Bekannte lokale Python 3.12 Installationen (wird zuerst geprüft).
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYPATH=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto run
)
if exist "C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PYPATH=C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe"
    goto run
)

rem Fallback: py-Launcher sucht Python 3.12 (keine hartkodierten Pfade mehr).
set "PYPATH="
where py >nul 2>&1
if not errorlevel 1 set "PYPATH=py -3.12"
if defined PYPATH goto run
rem Letzter Ausweg: python aus PATH — erst Version pruefen, dann installieren.
where python >nul 2>&1
if errorlevel 1 goto no_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto bad_python
set "PYPATH=python"

:run
echo === CWBuilder Installation (alles lokal in diesem Ordner) ===
rem %PYPATH% ist entweder ein quoted Pfad, "py -3.12" oder "python";
rem call handhabt alles drei. Der Zielpfad von cd /d endet auf "\" —
rem "%~dp0." verhindert einen doppelten Backslash ("...\\"), der sonst
rem Windows-Fehler wie "No Python at '...'" ausloest.
:exec
call %PYPATH% "%~dp0.\install.py" %*

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
echo [fail] Python in PATH gefunden, aber Version < 3.12 — nicht unterstützt.
echo        Installieren Sie Python 3.12+ (https://python.org), oder geben Sie explizit an:
echo            python install.py --python "C:\Pfad\zu\python3.12.exe"
pause
exit /b 1
