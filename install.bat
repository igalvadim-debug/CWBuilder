@echo off
rem CWBuilder - Umgebungsinstallation (Windows).
rem Aequivalent zum manuellen Start: python install.py
rem   1) sucht CPython 3.12+ (MM_PYTHON -> venv -> bekannter Python312 -> py -3.12 -> python),
rem   2) ruft install.py auf: venv .\venv + requirements.txt (Modelle werden NICHT geladen),
rem   3) nach der Installation Angebot: Gradio-UI starten (ui.bat).
setlocal
cd /d "%~dp0"
title CWBuilder install

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYARGS="

if not exist "install.py" (
    echo [fail] install.py wurde in diesem Ordner nicht gefunden.
    pause
    exit /b 1
)

rem Ein vorhandenes venv hat Vorrang (Wiederholung der Installation ist sicher).
if exist "venv\Scripts\python.exe" (
    set "PYPATH=venv\Scripts\python.exe"
    set "PYARGS="
    goto run
)

rem Vom Benutzer angegebener Interpreter (MM_PYTHON): nur akzeptieren, wenn er
rem existiert und Python 3.12+ ist; aeltere Versionen blockieren die Suche nicht.
if defined MM_PYTHON if exist "%MM_PYTHON%" (
    "%MM_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info ^>= (3, 12) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PYPATH=%MM_PYTHON%"
        set "PYARGS="
        goto run
    )
)

rem Bekannte lokale Python-3.12-Installation (zuerst geprueft, kein PATH noetig).
rem Das ist der Interpreter des Benutzers; install.py erzeugt daraus das venv:
rem   "C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe" -m venv venv
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

rem Ersatz: kurzer Suchlauf im PATH (py launcher -> python).
where py >nul 2>&1
if errorlevel 1 goto try_python
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYPATH=py"
    set "PYARGS=-3.12"
    goto run
)
py -3 -c "import sys; sys.exit(0 if sys.version_info ^>= (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYPATH=py"
    set "PYARGS=-3"
    goto run
)

:try_python
where python >nul 2>&1
if errorlevel 1 goto no_python
rem Versionspruefung: install.py verlangt CPython 3.12+ (siehe MIN_PYTHON in install.py).
python -c "import sys; sys.exit(0 if sys.version_info ^>= (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto bad_python
set "PYPATH=python"
set "PYARGS="

:run
echo === CWBuilder Installation (alles lokal in diesem Ordner) ===
rem Anfuehrungszeichen nur um den exe-Pfad - Leerzeichen in %LOCALAPPDATA%
rem stoeren nicht, die py-Optionen (%PYARGS%) bleiben eigene Argumente.
"%PYPATH%" %PYARGS% install.py %*
if errorlevel 1 (
    echo.
    echo [fail] Installation nicht abgeschlossen. Siehe Meldungen oben.
    pause
    exit /b 1
)

echo.
choice /c YN /m "Installation fertig. Gradio-UI jetzt starten (ui.bat)?"
if errorlevel 2 goto end
call ui.bat

:end
endlocal
exit /b 0

:no_python
echo [fail] Python wurde im PATH nicht gefunden.
echo        Installieren Sie Python 3.12+ ^(https://python.org^) und wiederholen Sie,
echo        oder starten Sie es explizit: "C:\pfad\zu\python.exe" install.py
pause
exit /b 1

:bad_python
echo [fail] python im PATH gefunden, aber die Version ist aelter als 3.12 - nicht unterstuetzt.
echo        Installieren Sie Python 3.12+ ^(https://python.org^), oder zeigen Sie es explizit:
echo        "C:\pfad\zu\python3.12.exe" install.py
pause
exit /b 1
