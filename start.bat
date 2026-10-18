@echo off
rem CWBuilder - Starter mit Menue (Video, Bild, Gradio-UI, Liste, Pruefung).
rem start.bat video "Text" ...   Minimax-H3 Workflow-JSON erzeugen
rem start.bat image <modus> ...   Bild-Workflow erzeugen / ausfuehren (+ --run)
rem start.bat ui                  Gradio-Oberflaeche (http://127.0.0.1:7865)
rem start.bat list                Modi, Turbo-LoRAs und Serverstatus
rem start.bat check               alle Modi gegen vorhandene Modelle pruefen
rem start.bat comfy               ComfyUI-Bildserver starten (start_comfyu2i.bat)
rem Eine .txt-Datei auf diese Datei ziehen = Video-Prompt aus der Datei.
setlocal
cd /d "%~dp0"
title CWBuilder

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

call :findpython
if not defined PYEXE goto noparams

rem Unterbefehl erkannt? Dann direkt an src\mm.py weitergeben.
if /i "%~1"=="video"  goto mmcmd
if /i "%~1"=="image"  goto mmcmd
if /i "%~1"=="list"   goto mmcmd
if /i "%~1"=="check"  goto mmcmd
if /i "%~1"=="ui"     goto runui
if /i "%~1"=="comfy"  goto comfy
if "%~1"==""          goto checkvenv_menu
rem .txtdatei als erstes Argument (auf die bat gezogen) = Video-Prompt.
if /i "%~x1"==".txt"  goto mmcmd
echo [warn] Unbekannter Parameter "%~1" - es wird das Menue geoeffnet.
goto checkvenv_menu

:mmcmd
"%PYEXE%" src\mm.py %*
set "RC=%errorlevel%"
if not "%~1"=="" exit /b %RC%
pause
exit /b %RC%

:checkvenv_menu
rem Ohne venv fuehrt das Menue zuerst die Installation nach (Pfad dafuer:
rem der hier bereits gefundene PYEXE, z.B. Ihr Python 3.12).
if exist "venv\Scripts\python.exe" (
    if exist "venv\.install-complete" goto menu
)
goto install

:menu
cls
echo ============================================
echo  CWBuilder
echo ============================================
echo  [V] Video (Minimax H3 Prompt aus prompts\prompt.txt)
echo  [B] Bild  (Modus und Prompt abfragen)
echo  [G] Gradio-UI starten (http://127.0.0.1:7865)
echo  [L] Liste der Modi / Serverstatus
echo  [C] Pruefung: Modi gegen vorhandene Modelle
echo  [S] ComfyUI-Bildserver starten (port 8291)
echo  [Q] Beenden
echo ============================================
choice /c VBGCSQL /n /m "Bitte waehlen: "
if errorlevel 7 goto menu
if errorlevel 6 goto menu
if errorlevel 5 goto comfy
if errorlevel 4 goto docmd_check
if errorlevel 3 goto docmd_list
if errorlevel 2 goto ask_image
if errorlevel 1 goto ask_video_prompt
goto menu

:ask_video_prompt
set "VPROMPT="
set /p VPROMPT=Video-Prompt (Enter = prompts\prompt.txt): 
if defined VPROMPT (
    "%PYEXE%" src\mm.py video "%VPROMPT%"
) else (
    "%PYEXE%" src\mm.py video
)
pause
goto menu

:ask_image
set "IMODE="
set /p IMODE=Bild-Modus (z.B. krea2, klein9b, qwen-edit, flux3): 
set "IPROMPT="
set /p IPROMPT=Bild-Prompt: 
"%PYEXE%" src\mm.py image "%IMODE%" "%IPROMPT%"
pause
goto menu

:docmd_list
"%PYEXE%" src\mm.py list
pause
goto menu

:docmd_check
"%PYEXE%" src\mm.py check
pause
goto menu

:runui
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

:comfy
rem ComfyUI fuer MOSS/Bilder: externer Start aus config.json (target image).
for /f "tokens=2 delims==" %%a in ('""%PYEXE%" -c "import json;print(json.load(open('config.json',encoding='utf-8'))['targets']['image'].get('start_bat',''))""') do set "COMFYBAT=%%a"
if not defined COMFYBAT (
    echo [fail] In config.json ist kein targets.image.start_bat eingetragen.
    pause
    exit /b 1
)
call "%COMFYBAT%"
exit /b %errorlevel%

:noparams
echo [fail] Kein passendes Python gefunden (venv oder py -3.12 erforderlich).
echo        Fuehren Sie zuerst install.bat aus, oder setzen Sie MM_PYTHON
echo        auf einen Python-3.12 Interpreter, z.B.:
echo        set MM_PYTHON=C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe
pause
exit /b 1

:install
rem venv fehlt - Installation nachholen, danach zurueck ins Menue.
echo venv nicht gefunden - Installation wird gestartet...
if exist "venv\Scripts\python.exe" ("venv\Scripts\python.exe" install.py) else ("%PYEXE%" install.py)
if errorlevel 1 (
    echo [fail] Installation nicht abgeschlossen. Siehe Meldungen oben.
    pause
    exit /b 1
)
goto menu

:findpython
rem Suchreihenfolge: venv -> MM_PYTHON (nur 3.12+) -> bekannter Python312 -> py -3.12 -> python
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
if errorlevel 1 goto try_plain_python
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=py -3.12"
    exit /b 0
)
py -3 -c "import sys; sys.exit(0 if sys.version_info ^>= (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=py -3"
    exit /b 0
)
goto try_plain_python
:try_plain_python
where python >nul 2>&1
if errorlevel 1 exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info ^>= (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 set "PYEXE=python"
exit /b 0
