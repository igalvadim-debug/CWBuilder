@echo off
rem CWBuilder - Gradio-Oberflaeche direkt starten (kein Menue).
rem http://127.0.0.1:7865 ; fuer das vollstaendige Menue: start.bat
setlocal
cd /d "%~dp0"
title CWBuilder Gradio UI

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

call :findpython
if not defined PYEXE goto noparams

"%PYEXE%" install.py --check
if errorlevel 1 (
    echo [fail] Selbsttest fehlgeschlagen. Siehe Meldungen oben.
    pause
    exit /b 1
)

echo === CWBuilder Gradio UI: http://127.0.0.1:7865 ===
start "" "http://127.0.0.1:7865"
"%PYEXE%" src\mm_ui.py
exit /b %errorlevel%

:noparams
echo [fail] Kein passendes Python gefunden.
echo        Fuehren Sie zuerst install.bat aus oder setzen Sie MM_PYTHON
echo        auf einen Python-3.12 Interpreter, z.B.:
echo        set MM_PYTHON=C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe
pause
exit /b 1

:findpython
rem Suchreihenfolge: venv -> MM_PYTHON (nur 3.12+) -> bekannter Python312 -> py -3.12
set "PYEXE="
if exist "venv\Scripts\python.exe" (
    set "PYEXE=venv\Scripts\python.exe"
    exit /b 0
)
if defined MM_PYTHON if exist "%MM_PYTHON%" (
    "%MM_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info ^>= (3, 12) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PYEXE=%MM_PYTHON%"
        exit /b 0
    )
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    exit /b 0
)
if exist "C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PYEXE=C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe"
    exit /b 0
)
where py >nul 2>&1
if errorlevel 1 exit /b 0
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=py -3.12"
    exit /b 0
)
py -3 -c "import sys; sys.exit(0 if sys.version_info ^>= (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 set "PYEXE=py -3"
exit /b 0
