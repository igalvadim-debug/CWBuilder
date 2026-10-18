@echo off
rem open-creator LOCAL — установка окружения (Windows).
rem Эквивалент ручного запуска: python install.py
rem   1) ищет CPython (py -3.12 -> py -3 -> python),
rem   2) вызывает install.py: venv ./venv + requirements.txt + модели + pnpm install,
rem   3) после установки предлагает запустить start.bat (стек + веб :19861).
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title open-creator LOCAL install

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYARGS="

if not exist "install.py" (
    echo [fail] Не найден install.py в этой папке.
    pause
    exit /b 1
)

rem Уже установленный venv имеет приоритет (идемпотентный повторный запуск).
if exist "venv\Scripts\python.exe" (
    set "PYPATH=venv\Scripts\python.exe"
    set "PYARGS="
    goto run
)

rem Известная локальная установка Python 3.12 (проверяется первой — поиск в PATH не нужен).
rem Это ваш интерпретатор: install.py создаст из него venv командой
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

rem Запасной вариант: быстрый поиск в PATH (py launcher -> python).
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
rem Проверка версии: install.py требует CPython >= 3.12 (см. MIN_PYTHON в install.py).
rem При --version не-интерактивный вывод, код 0 только если версия подходит.
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto bad_python
set "PYPATH=python"
set "PYARGS="

:run
echo === Установка open-creator LOCAL (всё локально в этой папке) ===
rem Кавычки только вокруг пути exe — чтобы пробелы в %LOCALAPPDATA% не ломали запуск,
rem а опции py-лаунчера (%PYARGS%) оставались отдельными аргументами.
"%PYPATH%" %PYARGS% install.py %*
if errorlevel 1 (
    echo.
    echo [fail] Установка не завершена. См. сообщения выше.
    pause
    exit /b 1
)

echo.
choice /c YN /m "Установка завершена. Запустить стек сейчас (start.bat)?"
if errorlevel 2 goto end
call start.bat

:end
endlocal
exit /b 0

:no_python
echo [fail] Python не найден в PATH.
echo        Установите Python 3.12+ ^(https://python.org^) и повторите,
echo        либо запустите явно: "C:\путь\к\python.exe" install.py
pause
exit /b 1

:bad_python
echo [fail] Найден python в PATH, но его версия ниже 3.12 — не поддерживается.
echo        Установите Python 3.12+ ^(https://python.org^), либо укажите явно:
echo        "C:\путь\к\python3.12.exe" install.py
pause
exit /b 1
