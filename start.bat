@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Minimax / ComfyUI Generator

rem --- Python suchen: MM_PYTHON, lokales venv, python, py -3 ---
set "PYEXE="
set "PYARG="
call :trypy "%MM_PYTHON%"
if not defined PYEXE call :trypy "%~dp0venv\Scripts\python.exe"
if not defined PYEXE call :trypy python
if not defined PYEXE call :trypy py -3
if not defined PYEXE (
    echo [!] Python 3 nicht gefunden. Bitte installieren oder MM_PYTHON setzen.
    pause
    exit /b 1
)

rem --- Mit Argumenten (z.B. .txt auf die bat gezogen): direkt ausfuehren ---
if not "%~1"=="" goto direct

:menu
cls
echo ==================================================
echo   Minimax / ComfyUI  -  Video + Bild-Workflows
echo ==================================================
echo   Prompt: prompts\prompt.txt   (Notepad: [0])
echo.
echo   [1] Video   Minimax-H3  -^> Workflow-JSON
echo   [2] Bild    Krea 2 Turbo
echo   [3] Bild    FLUX.2 Klein 9B
echo   [4] Bild    Qwen Image 2.1
echo   [5] Bild    Qwen Image Edit 2511
echo   [6] Bild    Z-Image Turbo
echo   [7] Modelle und Nodes pruefen
echo   [8] Uebersicht (Modi, Turbo-LoRAs, Server)
echo   [0] prompt.txt bearbeiten
echo   [Q] Ende
echo.
choice /c 123456780Q /n /m "Auswahl: "
if errorlevel 10 goto :eof
if errorlevel 9 goto edit
if errorlevel 8 goto list
if errorlevel 7 goto check
if errorlevel 6 call :image zimage & goto menu
if errorlevel 5 call :image qwen-edit & goto menu
if errorlevel 4 call :image qwen21 & goto menu
if errorlevel 3 call :image klein9b & goto menu
if errorlevel 2 call :image krea2 & goto menu
if errorlevel 1 goto video
goto menu

:video
echo.
"%PYEXE%" %PYARG% "%~dp0src\mm.py" video
echo.
pause
goto menu

:list
echo.
"%PYEXE%" %PYARG% "%~dp0src\mm.py" list
echo.
pause
goto menu

:check
echo.
"%PYEXE%" %PYARG% "%~dp0src\mm.py" check
echo.
pause
goto menu

:edit
if not exist "%~dp0prompts" mkdir "%~dp0prompts"
if not exist "%~dp0prompts\prompt.txt" type nul > "%~dp0prompts\prompt.txt"
notepad "%~dp0prompts\prompt.txt"
goto menu

:image
set "MODE=%~1"
set "IMG="
set "CTRL="
set "MORE="
echo.
echo Modus: %MODE%   (Prompt aus prompts\prompt.txt)
set /p "IMG=Referenzbild (Enter = keins, Datei hierher ziehen): "
set /p "CTRL=ControlNet-Bild (Enter = ohne ControlNet): "
set /p "MORE=Zusatzoptionen, z.B. --turbo p8 --seed 5 (Enter = keine): "
set "ARGS=image %MODE% --run --start"
if defined IMG set "IMG=%IMG:"=%"
if defined IMG set "ARGS=%ARGS% -i "%IMG%""
if defined CTRL set "CTRL=%CTRL:"=%"
if defined CTRL set "ARGS=%ARGS% --control --control-image "%CTRL%""
echo.
"%PYEXE%" %PYARG% "%~dp0src\mm.py" %ARGS% %MORE%
echo.
echo Ergebnisse: %~dp0output
pause
exit /b

:direct
"%PYEXE%" %PYARG% "%~dp0src\mm.py" %*
set "RC=%errorlevel%"
echo.
echo %cmdcmdline% | find /i "/c" >nul && pause
exit /b %RC%

:trypy
if "%~1"=="" exit /b
"%~1" %~2 -c "import sys" >nul 2>&1
if errorlevel 1 exit /b
set "PYEXE=%~1"
set "PYARG=%~2"
exit /b
