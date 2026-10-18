@echo off
rem open-creator LOCAL — запуск стека (LLM :8484, embeddings :8512, MCP :8001 ...)
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title open-creator LOCAL

rem ---------------------------------------------------------------
rem  start.bat   -> локальный стек (local-stack), затем веб-интерфейс
rem  start.bat stop -> все сервисы стека остановить (Ctrl+C в этом окне)
rem  Веб-интерфейс после старта: http://127.0.0.1:19861/
rem  Модели берутся с диска (см. .env: LOCAL_STACK_MODELS) — без скачивания.
rem ---------------------------------------------------------------

if /i "%~1"=="stop" goto :stop

if not exist "venv\Scripts\python.exe" goto install
if not exist "venv\.install-complete" goto install

:start
rem Интерпретатор для запуска стека: MM_PYTHON (например, ваш Python 3.12 вне
rem PATH), затем venv\Scripts\python.exe (он же активируется ниже).
set "PYEXE=venv\Scripts\python.exe"
if defined MM_PYTHON if exist "%MM_PYTHON%" set "PYEXE=%MM_PYTHON%"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set OPENCREATOR_LOCAL=1
for /f "tokens=1,* delims==" %%a in ('findstr /b "LOCAL_STACK_MODELS=" .env') do set "%%a=%%b"
for /f "tokens=1,* delims==" %%a in ('findstr /b "LOCAL_LLM_MODEL=" .env') do set "%%a=%%b"
for /f "tokens=1,* delims==" %%a in ('findstr /b "LOCAL_EMBED_MODEL=" .env') do set "%%a=%%b"

echo [1/2] Запускаю local-stack (llama-server :8484, embeddings :8512, MCP :8001)...
rem Стек сам пишет PID-файл local-stack\.pids — "start.bat stop" остановит только его
start "open-creator-local-stack" cmd /k ""venv\Scripts\activate.bat" && python local-stack\start.py"

echo [2/2] Запускаю веб-интерфейс (pnpm web:dev)...
timeout /t 5 /nobreak >nul
start "" http://127.0.0.1:19861/
rem PID-обёртка пишет .webui.pid и останавливает при Ctrl+C только своё дерево
node scripts\web-dev-wrapper.mjs pnpm web:dev

echo Готово. Закройте окно стека или выполните: start.bat stop
pause
exit /b 0

:install
rem Установка не завершена — запускаем install.py доступным способом (без скачивания из сети).
echo Установка не завершена — запускаю установку...
set "INSTALL_OK="
if defined MM_PYTHON if exist "%MM_PYTHON%" (
    "%MM_PYTHON%" install.py %*
    set "INSTALL_OK=1"
    goto install_after
)
if exist "venv\Scripts\python.exe" (
    rem Уже созданный venv имеет приоритет — ставим зависимости в него.
    "venv\Scripts\python.exe" install.py %*
    set "INSTALL_OK=1"
    goto install_after
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" install.py %*
    set "INSTALL_OK=1"
    goto install_after
)
rem Python 3.12+ через py-лаунчер (проверяется наличие лаунчера и версии).
where py >nul 2>&1
if errorlevel 1 goto install_no_py
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.12 install.py %*
    set "INSTALL_OK=1"
    goto install_after
)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto install_bad_py
py -3 install.py %*
set "INSTALL_OK=1"

:install_after
if not defined INSTALL_OK goto install_no_py
if not exist "venv\Scripts\python.exe" (
    echo [fail] venv не создан после установки. См. сообщения выше.
    pause
    exit /b 1
)
if not exist "venv\.install-complete" (
    echo [fail] Установка не завершена ^(нет venv\.install-complete^). См. сообщения выше.
    pause
    exit /b 1
)
goto start

:install_no_py
echo [fail] Не найден Python 3.12+ (нет venv и py-лаунчера).
echo        Установите Python 3.12+ ^(https://python.org^) либо запустите явно:
echo        "C:\путь\к\python.exe" install.py, затем повторите start.bat
pause
exit /b 1

:install_bad_py
echo [fail] py-лаунчер найден, но Python 3.12+ среди установленных версий нет.
echo        Установите Python 3.12+ ^(https://python.org^) и повторите start.bat
pause
exit /b 1

:stop
echo Останавливаю только процессы, записанные этим лаунчером (.pids / .webui.pid) ...
rem Стек: local-stack/start.py --stop шлёт сигнал только PID из local-stack\.pids
if exist "venv\Scripts\python.exe" ("venv\Scripts\python.exe" local-stack\start.py --stop) else (python local-stack\start.py --stop)
rem Веб-интерфейс: обёртка сверяет имя процесса перед остановкой; чужие не трогает
if exist ".webui.pid" (
    node scripts\web-dev-wrapper.mjs --stop ".webui.pid" || echo [warn] веб-интерфейс: процесс не найден или уже завершён
    del /q ".webui.pid" 2>nul
) else (
    echo [skip] .webui.pid нет — веб-интерфейс не запускался этим лаунчером
)
echo Готово. Чужие llama-server и слушатели портов не тронуты.
exit /b 0

endlocal
