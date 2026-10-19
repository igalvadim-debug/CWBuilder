@echo off
rem CWBuilder — Installation der Python-Umgebung (Windows).
rem 1) Sucht CPython (py -3.12 -> py -3 -> python),
rem 2) Ruft install.py auf: venv ./venv + requirements.txt + Modelle prüfen,
rem 3) Nach Installation: start.bat starten.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title CWBuilder install

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYARGS="

if not exist "install.py" (
    echo [fail] install.py nicht gefunden in diesem Ordner.
    pause
    exit /b 1
)

rem Vorhandener venv hat Priorität (idempotenter erneuter Lauf).
if exist "venv\Scripts\python.exe" (
    set "PYPATH=venv\Scripts\python.exe"
    set "PYARGS="
    goto run
)

rem Bekannte lokale Python 3.12 Installation (wird zuerst geprüft).
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYPATH=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    set "PYARGS="
    goto run
)
if exist "C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PYPATH=C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe"
    set "PYARGS="
    goto run
)

rem Fallback: schneller PATH-Suche (py launcher -> python).
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
rem Version prüfen: install.py braucht CPython >= 3.12.
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto bad_python
set "PYPATH=python"
set "PYARGS="

:run
echo === CWBuilder Installation (alles lokal in diesem Ordner) ===
rem Nur Pfad zum exe in Anführungszeichen — damit Leerzeichen in %LOCALAPPDATA% nicht brechen,
rem py-Optionen (%PYARGS%) bleiben separate Argumente.
"%PYPATH%" %PYARGS% install.py %*
if errorlevel 1 (
    echo.
    echo [fail] Installation nicht abgeschlossen. Siehe Meldungen oben.
    pause
    exit /b 1
)

echo.
choice /c YN /m "Installation abgeschlossen. Jetzt starten (start.bat)?"
if errorlevel 2 goto end
call start.bat

:end
endlocal
exit /b 0

:no_python
echo [fail] Python nicht in PATH gefunden.
echo        Installieren Sie Python 3.12+ (https://python.org) und wiederholen,
echo        oder starten Sie explizit: "C:\Pfad\zu\python.exe" install.py
pause
exit /b 1

:bad_python
echo [fail] Python in PATH gefunden, aber Version < 3.12 — nicht unterstützt.
echo        Installieren Sie Python 3.12+ (https://python.org), oder geben Sie explizit an:
echo        "C:\Pfad\zu\python3.12.exe" install.py
pause
exit /b 1
