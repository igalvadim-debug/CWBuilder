@echo off
rem CWBuilder — Gradio UI direkt starten
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title CWBuilder Gradio UI

rem ---------------------------------------------------------------
rem  ui.bat -> startet Gradio UI (mm.py ui) direkt
rem  Gradio UI: http://127.0.0.1:7865
rem ---------------------------------------------------------------

if not exist "venv\Scripts\python.exe" goto :no_venv
set "PYEXE=venv\Scripts\python.exe"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo Starte Gradio UI (src\mm.py ui)...
echo Interpreter: %PYEXE%
"%PYEXE%" src\mm.py ui %*
if errorlevel 1 (
    echo FEHLER: Gradio UI wurde beendet (siehe Meldung oben).
    pause
)
exit /b 0

:no_venv
echo FEHLER: Virtuelle Umgebung nicht gefunden (venv\Scripts\python.exe).
echo Fuehren Sie zuerst die Installation aus: start.bat install
pause
exit /b 1

endlocal
