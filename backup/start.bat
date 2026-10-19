@echo off
rem CWBuilder — Startmenue
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title CWBuilder

rem ---------------------------------------------------------------
rem  start.bat   -> Menue: [G] Gradio UI, [C] ComfyUI (MOSS), [I] Install, [Q] Beenden
rem  start.bat ui   -> Gradio UI direkt starten
rem  start.bat comfy -> ComfyUI fuer MOSS starten (externe Datei)
rem  Gradio UI: http://127.0.0.1:7865
rem  ComfyUI (MOSS): http://127.0.0.1:8291 (via C:\Users\Startklar\Desktop\Comfyui\start_comfyu2i.bat)
rem  Modelle werden von den vorhandenen Pfaden geladen (config.json, docs/models.txt)
rem ---------------------------------------------------------------

if /i "%~1"=="ui" goto :ui
if /i "%~1"=="comfy" goto :comfy
if /i "%~1"=="install" goto :install
if /i "%~1"=="check" goto :check

:menu
cls
echo ============================================================
echo  CWBuilder — Auswahl
echo ============================================================
echo [1] Gradio UI (Port 7865) — Bild- und Video-Generierung
echo [2] ComfyUI fuer MOSS starten (Port 8291, externes Skript)
echo [3] Installation / Re-Installation
echo [4] Modi pruefen (mm.py check)
echo [5] Beenden
echo ============================================================
choice /c 12345 /n /m "Waehlen: "
if errorlevel 5 goto :eof
if errorlevel 4 goto :check
if errorlevel 3 goto :install
if errorlevel 2 goto :comfy
if errorlevel 1 goto :ui

:ui
rem Gradio UI starten
if not exist "venv\Scripts\python.exe" goto :no_venv
set "PYEXE=venv\Scripts\python.exe"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo Starte Gradio UI (src/mm.py ui)...
echo Interpreter: %PYEXE%
"%PYEXE%" src/mm.py ui %*
exit /b 0

:comfy
rem Externe ComfyUI fuer MOSS starten
set "COMFY_BAT=C:\Users\Startklar\Desktop\Comfyui\start_comfyu2i.bat"
if not exist "%COMFY_BAT%" (
    echo FEHLER: ComfyUI-Startdatei nicht gefunden:
    echo %COMFY_BAT%
    pause
    exit /b 1
)
echo Starte ComfyUI fuer MOSS (Port 8291)...
start "" "%COMFY_BAT%"
echo ComfyUI wird in einem separaten Fenster gestartet.
echo URL: http://127.0.0.1:8291
pause
exit /b 0

:install
rem Installation
if not exist "venv\Scripts\python.exe" goto :no_venv
set "PYEXE=venv\Scripts\python.exe"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo Starte Installation (install.py)...
"%PYEXE%" install.py %*
exit /b 0

:check
rem Modi pruefen
if not exist "venv\Scripts\python.exe" goto :no_venv
set "PYEXE=venv\Scripts\python.exe"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo Pruefe alle Modi gegen vorhandene Modelle...
"%PYEXE%" src/mm.py check %*
pause
exit /b 0

:no_venv
echo FEHLER: Virtuelle Umgebung nicht gefunden (venv\Scripts\python.exe).
echo Fuehren Sie zuerst die Installation aus: start.bat install
pause
exit /b 1

endlocal

