"""open-creator LOCAL — установка окружения (Windows).

Создаёт локальное venv (./venv) из указанного CPython, «активирует» его
(для установки и запуска используется интерпретатор напрямую — эквивалент
activate без лишней оболочки), ставит requirements.txt ЛОКАЛЬНО.

МОДЕЛИ НЕ КАЧАЮТСЯ. Установщик читает реестр уже имеющихся на диске весов
(docs/local_models.json, составлен по docs/models.txt / docs/models.md) и
подключает их напрямую через env-переменную LOCAL_STACK_MODELS — в
./local-stack/models не копируется и с Hugging Face не скачивается ничего.
Отдельные ComfyUI-модели (workflow'и image/video) тоже проверяются только
на месте — если файла нет, выводится подсказка, но сеть не трогается.

Флаги:
    --copy-models    скопировать найденные GGUF в ./local-stack/models
                     (по умолчанию — нет, используем модели прямо с диска);
    --download-models [имя ...]  разрешить докачку недостающего с HF
                     (по умолчанию закачка полностью ВЫКЛЮЧЕНА);
    --python <exe>   базовый интерпретатор для venv.

Веб-интерфейс (open-creator UI): http://127.0.0.1:19861/ — поднимается
командой `pnpm web:dev` после того, как local-stack запущен (start.bat).
Для локального режима daemon использует OPENCREATOR_LOCAL=1 (см. .env.example).

Использование:
    "C:\\Users\\Startklar\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" install.py
Либо просто запустить start.bat — при отсутствии venv он сам вызовет install.py.
Всё остаётся внутри этой папки репозитория: venv, кэш pip/node — local;
модели лежат в ваших папках и не дублируются.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / "venv"
REQUIREMENTS = ROOT / "requirements.txt"
MODELS_DIR = ROOT / "local-stack" / "models"
LOCAL_MODELS_JSON = ROOT / "docs" / "local_models.json"
INSTALL_COMPLETE = VENV_DIR / ".install-complete"
ENV_FILE = ROOT / ".env"

# Интерпретатор по умолчанию (можно переопределить аргументом --python).
DEFAULT_PYTHON = sys.executable

# Кэш найденных путей записей реестра: id(entry) -> Path | None (заполняет prepare_models).
RESOLVED_PATHS: dict[int, Path | None] = {}


def venv_python() -> Path:
    """Путь к python.exe внутри venv (Windows) или bin/python (POSIX)."""
    if os_name_is_windows():
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def os_name_is_windows() -> bool:
    """Return whether the current Python platform is Windows."""
    return sys.platform.startswith("win")


def run(cmd: list[str]) -> int:
    """Run cmd from the repository root and return its exit status.

    Nonzero statuses are returned without raising; process launch errors
    propagate as OSError.
    """
    print("+ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


def ensure_venv(base_python: str) -> Path:
    """Return the interpreter in ROOT/venv, creating it if needed.

    Use base_python for creation; reuse an existing interpreter path without
    checking base_python.
    Raise SystemExit if base_python is absent or creation leaves no
    interpreter. Creation failures propagate as subprocess.CalledProcessError;
    process launch errors propagate as OSError.
    """
    py = venv_python()
    if py.exists():
        print(f"[ok  ] venv уже существует: {VENV_DIR}")
        return py
    if not Path(base_python).exists():
        raise SystemExit(
            f"[fail] Python не найден: {base_python}\n"
            f"       Укажите свой: python install.py --python <путь к python.exe>"
        )
    print(f"[setup] Создаю venv: {VENV_DIR} (из {base_python})")
    subprocess.check_call(
        [base_python, "-m", "venv", str(VENV_DIR)], cwd=str(ROOT)
    )
    if not py.exists():
        raise SystemExit(f"[fail] Неожиданно: {py} не появился после создания venv")
    return py


def activate_and_install(py: Path) -> None:
    """Upgrade pip, setuptools, and wheel; install requirements.txt via py.

    The parent process environment is unchanged. A nonzero packaging-tool
    upgrade status is ignored. Raise SystemExit if requirements.txt is missing
    or its installation exits nonzero; process launch errors propagate as
    OSError.
    """
    env_prefix = VENV_DIR / ("Scripts" if os_name_is_windows() else "bin")
    print(f"[activ ] VIRTUAL_ENV={VENV_DIR} PATH~={env_prefix}")
    # Обновление pip/setuptools внутри venv (только PyPI, локально).
    run([str(py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    if not REQUIREMENTS.exists():
        raise SystemExit(f"[fail] Нет файла требований: {REQUIREMENTS}")
    rc = run([str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    if rc != 0:
        raise SystemExit("[fail] Не удалось установить requirements.txt")
    print("[ok    ] Зависимости установлены в venv (все локально, без внешних AI API)")


# --- реестр локальных моделей (без скачивания) --------------------------------

def load_registry() -> dict:
    """Прочитать docs/local_models.json; пустой словарь, если файла нет."""
    try:
        return json.loads(LOCAL_MODELS_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"[warn] Нет реестра моделей: {LOCAL_MODELS_JSON}")
        return {}
    except json.JSONDecodeError as e:
        raise SystemExit(f"[fail] {LOCAL_MODELS_JSON} повреждён: {e}")


def _expand_root(root: str) -> Path | None:
    """Вернуть существующую папку-корень (Windows-путь) или None."""
    p = Path(root.replace("\\", "/"))
    return p if p.is_dir() else None


def find_local_file(cand: dict, default_roots: list[str]) -> Path | None:
    """Найти файл по кандидату реестра среди roots (filename или glob)."""
    roots = [cand["root"]] if "root" in cand else default_roots
    subdir = cand.get("subdir", "")
    for root in roots:
        rp = _expand_root(root)
        if rp is None:
            continue
        base = rp / subdir if subdir else rp
        if "filename" in cand:
            p = base / cand["filename"]
            if p.is_file():
                return p
        if "glob" in cand:
            if not base.is_dir():
                continue
            hits = sorted(base.glob(cand["glob"]))
            if hits:
                return hits[0]
    return None


def resolve_entry(entry: dict, default_roots: list[str]) -> tuple[Path | None, Path | None]:
    """Вернуть (путь к файлу модели, путь к mmproj) по записи реестра."""
    path = None
    for cand in entry.get("candidates", []):
        path = find_local_file(cand, default_roots)
        if path:
            break
    mmproj = None
    if path is not None and entry.get("mmproj_candidates"):
        mmproj = None
        for cand in entry["mmproj_candidates"]:
            mmproj = find_local_file(cand, default_roots)
            if mmproj:
                break
    return path, mmproj


def check_comfy_models(reg: dict) -> list[str]:
    """Проверить наличие ComfyUI-весов из реестра; вернуть имена отсутствующих.

    Ничего не качаем и не копируем — только проверка на месте; отсутствующие
    выводятся списком-подсказкой."""
    roots = reg.get("roots", [])
    missing: list[str] = []
    comfy = reg.get("models", {}).get("comfyui", {})
    for group in ("image", "video"):
        for entry in comfy.get(group, []):
            found = False
            for root in roots:
                rp = _expand_root(root)
                if rp is None:
                    continue
                for sub in entry.get("subdirs", [""]):
                    base = rp / sub if sub else rp
                    if "glob" in entry and base.is_dir():
                        if any(base.rglob(entry["glob"].split("/")[-1])):
                            found = True
                    name = entry["name"]
                    for variant in (name, name.lower(), name.replace("-dmd", "")):
                        if any(base.glob(f"{variant}*")):
                            found = True
                if found:
                    break
            if not found:
                missing.append(entry["name"])
    return missing


def _download_all_missing(reg: dict) -> list[str]:
    """Имена всех обязательных (не optional) моделей, не найденных локально.

    Используется при `--download-models` без имён: докачиваем ровно то, чего
    не хватает (по реестру docs/local_models.json), а не всё подряд."""
    roots = reg.get("roots", [])
    models_cfg = reg.get("models", {})
    entries = list(models_cfg.get("llm", [])) + list(models_cfg.get("embeddings", []))
    missing: list[str] = []
    for entry in entries:
        if entry.get("optional"):
            continue
        path, _mmproj = resolve_entry(entry, roots)
        if path is None:
            missing.append(entry["name"])
    return missing


def prepare_models(py: Path, copy_models: bool, download_names: list[str]) -> int:
    """Подключить локальные модели из реестра БЕЗ скачивания.

    Найденные GGUF-файлы остаются в своих папках; в ./local-stack/models
    кладутся симлинки (POSIX) либо список копируется (--copy-models), а
    local-stack указывает на них через LOCAL_STACK_MODELS в .env. Если часть
    моделей не найдена — установка продолжается на тех, что есть; при полном
    отсутствии LLM/embedding возвращается 1. Скачивание с HF выполняется
    только если передан непустой download_names (--download-models).
    """
    reg = load_registry()
    return wire_models(reg, py, copy_models, download_names)


def wire_models(reg: dict, py: Path, copy_models: bool,
                download_names: list[str]) -> int:
    """Подключить модели из уже загруженного реестра (см. prepare_models).

    Возвращает 0 при успехе; 1 — если LLM/embedding не найдено либо если в
    ./local-stack/models не удалось разместить нужные файлы (симлинки/копии)
    и при этом исходники лежат в разных папках — общей директории нет.
    """
    roots = reg.get("roots", [])
    models_cfg = reg.get("models", {})
    entries = list(models_cfg.get("llm", [])) + list(models_cfg.get("embeddings", []))

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    resolved: list[tuple[dict, Path]] = []
    missing_required: list[str] = []
    symlink_failed = False
    for entry in entries:
        path, mmproj = resolve_entry(entry, roots)
        RESOLVED_PATHS[id(entry)] = path
        if path is None:
            if entry.get("optional"):
                print(f"[skip ] {entry['name']} — нет локально (опциональна, не качаем)")
            else:
                missing_required.append(entry["name"])
                print(f"[--   ] {entry['name']} — не найдена среди локальных папок")
            continue
        target = MODELS_DIR / entry["name"]
        if copy_models and target != path and not target.exists():
            print(f"[copy ] {path} -> {target}")
            shutil.copy2(path, target)
        elif not copy_models and not target.is_file():
            try:
                target.symlink_to(path)
                print(f"[link ] {entry['name']} -> {path}")
            except OSError as e:
                symlink_failed = True
                print(f"[warn ] симлинк {target.name} не создан ({e});"
                      " пригодится --copy-models, если папки разные")
        if mmproj is not None:
            t2 = MODELS_DIR / mmproj.name
            if copy_models and not t2.exists():
                shutil.copy2(mmproj, t2)
            elif not copy_models and not t2.is_file():
                try:
                    t2.symlink_to(mmproj)
                except OSError as e:
                    symlink_failed = True
                    print(f"[warn ] симлинк {t2.name} не создан ({e})")
        resolved.append((entry, path))

    # Докачка разрешена только явным --download-models (по умолчанию — нет).
    if download_names:
        setup = ROOT / "local-stack" / "setup_models.py"
        if setup.exists():
            print(f"[net  ] Разрешена докачка: {', '.join(download_names)}")
            run([str(py), str(setup)] + [f"--only={','.join(download_names)}"])
        else:
            print("[warn] local-stack/setup_models.py не найден — докачка пропущена")
    elif missing_required:
        print("[i    ] Скачивание с Hugging Face ОТКЛЮЧЕНО: используются только"
              " модели, которые уже есть на диске (docs/local_models.json).")

    comfy_missing = check_comfy_models(reg)
    if comfy_missing:
        print("[i    ] ComfyUI-модели не найдены (не качаем; положите сами или"
              " укажите путь в docs/local_models.json): " + ", ".join(comfy_missing))

    llm_present = [e["name"] for e, _ in resolved if e.get("role")]
    embed_present = [e["name"] for e, _ in resolved if "primary" in e]
    if not llm_present:
        print("[fail] Ни одной локальной LLM-модели не найдено — стек не стартует.")
        return 1
    if not embed_present:
        print("[fail] Не найдено ни одной embedding-модели — RAG не будет работать.")
        return 1
    # Если симлинки не создались и исходники лежат в разных папках, общей
    # директории для LOCAL_STACK_MODELS гарантировать нельзя (см. main).
    if symlink_failed and not copy_models and \
            len({str(p.parent) for _e, p in resolved}) > 1:
        print("[fail] ./local-stack/models не может содержать все модели:"
              " симлинки не создаются, а GGUF лежат в разных папках.")
        print("       Перезапустите с копированием весов в одну папку:"
              " python install.py --copy-models")
        return 1
    print(f"[ok    ] Модели подключены локально без скачивания:"
          f" LLM={len(llm_present)}, embeddings={len(embed_present)}")
    return 0


def write_env(default_llm: str | None, embed_model: str | None,
              models_home: str | None = None) -> None:
    """Записать/обновить .env: LOCAL_STACK_MODELS и выбранные модели.

    models_home — папка, в которой лежат GGUF-файлы (при --copy-models это
    ./local-stack/models, иначе — исходная папка на диске). Existing keys
    are replaced in place; unknown lines are preserved.
    """
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    updates = {"OPENCREATOR_LOCAL": "1"}
    if models_home:
        updates["LOCAL_STACK_MODELS"] = models_home
    if default_llm:
        updates["LOCAL_LLM_MODEL"] = default_llm
    if embed_model:
        updates["LOCAL_EMBED_MODEL"] = embed_model

    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[ok    ] .env обновлён ({', '.join(sorted(updates))})")


def pick_defaults(resolved_entries: list[tuple[dict, Path]]) -> tuple[str | None, str | None]:
    """Вернуть (LOCAL_LLM_MODEL, LOCAL_EMBED_MODEL) по флагам реестра.

    LLM: use_as_default_if_present > role=coding > role=default > первый с ролью;
    embedding: use_as_embed_if_present > primary."""
    llm = embed = None
    for entry, _p in resolved_entries:
        if "primary" in entry:
            if entry.get("use_as_embed_if_present") or (embed is None and entry.get("primary")):
                embed = entry["name"]
            continue
        if entry.get("use_as_default_if_present"):
            llm = entry["name"]
        elif llm is None and entry.get("role") == "coding":
            llm = entry["name"]
        elif llm is None and entry.get("role") == "default":
            llm = entry["name"]
        elif llm is None and entry.get("role"):
            llm = entry["name"]
    return llm, embed


def install_web_deps() -> int:
    """Install the web UI JS dependencies via corepack/pnpm; return exit status.

    Runs `corepack enable`, then on success `pnpm install`, from the
    repository root (packageManager in package.json pins pnpm). Executables
    are resolved with shutil.which() so Windows .cmd shims (corepack.cmd,
    pnpm.cmd) can be launched; missing Corepack returns 1, while unresolved
    pnpm is launched by name. Nonzero statuses are
    returned without raising; process launch errors (e.g. missing Corepack
    executable) are converted to a nonzero status (1) instead of propagating,
    so callers can keep their warning flow and still write start.bat.
    """
    print("[web   ] Ставлю JS-зависимости веб-интерфейса (corepack + pnpm) ...")
    corepack = shutil.which("corepack")
    if corepack is None:
        print("[fail  ] corepack не найден в PATH — нужен Node.js 16.13+ "
              "(https://nodejs.org); веб-интерфейс можно поставить позже: pnpm install")
        return 1
    try:
        rc = run([corepack, "enable"])
    except OSError as e:
        print(f"[fail  ] corepack не запущен ({e}) — нужен Node.js 16.13+ "
              "(https://nodejs.org); веб-интерфейс можно поставить позже: pnpm install")
        return 1
    if rc != 0:
        print("[fail  ] corepack enable не удался — нужен Node.js 16.13+ "
              "(https://nodejs.org); веб-интерфейс можно поставить позже: pnpm install")
        return rc
    pnpm = shutil.which("pnpm") or "pnpm"
    try:
        rc = run([pnpm, "install"])
    except OSError as e:
        print(f"[fail  ] pnpm не запущен ({e}); повторите позже: pnpm install")
        return 1
    if rc != 0:
        print("[fail  ] pnpm install завершился с ошибкой;"
              " повторите позже: pnpm install")
    else:
        print("[ok    ] Веб-интерфейс установлен: запуск `pnpm web:dev`,"
              " затем http://127.0.0.1:19861/")
    return rc


START_BAT = """@echo off
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

if not exist "venv\\Scripts\\python.exe" goto install
if not exist "venv\\.install-complete" goto install

:start
rem Интерпретатор для запуска стека: MM_PYTHON (например, ваш Python 3.12 вне
rem PATH), затем venv\\Scripts\\python.exe (он же активируется ниже).
set "PYEXE=venv\\Scripts\\python.exe"
if defined MM_PYTHON if exist "%MM_PYTHON%" set "PYEXE=%MM_PYTHON%"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set OPENCREATOR_LOCAL=1
for /f "tokens=1,* delims==" %%a in ('findstr /b "LOCAL_STACK_MODELS=" .env') do set "%%a=%%b"
for /f "tokens=1,* delims==" %%a in ('findstr /b "LOCAL_LLM_MODEL=" .env') do set "%%a=%%b"
for /f "tokens=1,* delims==" %%a in ('findstr /b "LOCAL_EMBED_MODEL=" .env') do set "%%a=%%b"

echo [1/2] Запускаю local-stack (llama-server :8484, embeddings :8512, MCP :8001)...
rem Стек сам пишет PID-файл local-stack\\.pids — "start.bat stop" остановит только его
start "open-creator-local-stack" cmd /k ""venv\\Scripts\\activate.bat" && python local-stack\\start.py"

echo [2/2] Запускаю веб-интерфейс (pnpm web:dev)...
timeout /t 5 /nobreak >nul
start "" http://127.0.0.1:19861/
rem PID-обёртка пишет .webui.pid и останавливает при Ctrl+C только своё дерево
node scripts\\web-dev-wrapper.mjs pnpm web:dev

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
if exist "venv\\Scripts\\python.exe" (
    rem Уже созданный venv имеет приоритет — ставим зависимости в него.
    "venv\\Scripts\\python.exe" install.py %*
    set "INSTALL_OK=1"
    goto install_after
)
if exist "%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe" (
    "%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe" install.py %*
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
if not exist "venv\\Scripts\\python.exe" (
    echo [fail] venv не создан после установки. См. сообщения выше.
    pause
    exit /b 1
)
if not exist "venv\\.install-complete" (
    echo [fail] Установка не завершена ^(нет venv\\.install-complete^). См. сообщения выше.
    pause
    exit /b 1
)
goto start

:install_no_py
echo [fail] Не найден Python 3.12+ (нет venv и py-лаунчера).
echo        Установите Python 3.12+ ^(https://python.org^) либо запустите явно:
echo        "C:\\путь\\к\\python.exe" install.py, затем повторите start.bat
pause
exit /b 1

:install_bad_py
echo [fail] py-лаунчер найден, но Python 3.12+ среди установленных версий нет.
echo        Установите Python 3.12+ ^(https://python.org^) и повторите start.bat
pause
exit /b 1

:stop
echo Останавливаю только процессы, записанные этим лаунчером (.pids / .webui.pid) ...
rem Стек: local-stack/start.py --stop шлёт сигнал только PID из local-stack\\.pids
if exist "venv\\Scripts\\python.exe" ("venv\\Scripts\\python.exe" local-stack\\start.py --stop) else (python local-stack\\start.py --stop)
rem Веб-интерфейс: обёртка сверяет имя процесса перед остановкой; чужие не трогает
if exist ".webui.pid" (
    node scripts\\web-dev-wrapper.mjs --stop ".webui.pid" || echo [warn] веб-интерфейс: процесс не найден или уже завершён
    del /q ".webui.pid" 2>nul
) else (
    echo [skip] .webui.pid нет — веб-интерфейс не запускался этим лаунчером
)
echo Готово. Чужие llama-server и слушатели портов не тронуты.
exit /b 0

endlocal
"""


def write_start_bat() -> None:
    """Ensure ROOT/start.bat matches START_BAT encoded as UTF-8 with CRLF newlines.

    Windows batch files must use CRLF line endings (cmd.exe breaks on bare
    LF), so every newline in START_BAT is converted before writing. Leave a
    matching launcher untouched; otherwise create or overwrite it.
    Then touch INSTALL_COMPLETE inside the venv, creating its parent directory
    if needed. Filesystem errors propagate as OSError; an existing completion
    marker is not removed on failure.
    """
    bat = ROOT / "start.bat"
    data = START_BAT.replace("\n", "\r\n").encode("utf-8")
    if not bat.exists() or bat.read_bytes() != data:
        bat.write_bytes(data)
    INSTALL_COMPLETE.parent.mkdir(parents=True, exist_ok=True)
    INSTALL_COMPLETE.touch()
    print(f"[ok    ] Создан {bat.name}: двойной клик или .\\start.bat")


def parse_args(argv: list[str]) -> tuple[str, bool, list[str], bool]:
    """Return (base_python, copy_models, download_names, download_all) from argv.

    --python takes the following value (first occurrence wins);
    --copy-models enables copying into ./local-stack/models;
    --download-models [names...] enables HF downloads for the listed files
    (or everything missing when no names given — then download_all is True;
    the explicit flag is never silently dropped). Positional values that do
    not start with '-' select the base interpreter.
    Environment fallbacks: MM_PYTHON (the variable used by start.bat to point
    at a Python outside PATH) and PYTHONUTF8/PYTHONIOENCODING are exported to
    all child processes so install.py and its subprocesses always run in UTF-8
    on Windows.
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    base_python = DEFAULT_PYTHON
    mm_python = os.environ.get("MM_PYTHON", "").strip('"').strip()
    if mm_python and Path(mm_python).exists():
        base_python = mm_python
    copy_models = "--copy-models" in argv
    download_names: list[str] = []
    dl_enabled = "--download-models" in argv
    if dl_enabled:
        i = argv.index("--download-models")
        for a in argv[i + 1:]:
            if a.startswith("-"):
                break
            download_names.append(a)
    # Флаг задан, но имён нет — качаем все недостающие обязательные модели.
    download_all = dl_enabled and not download_names
    if "--python" in argv:
        i = argv.index("--python")
        if i + 1 < len(argv):
            base_python = argv[i + 1]
    elif argv and not argv[0].startswith("-"):
        base_python = argv[0]
    return base_python, copy_models, download_names, download_all


def models_home_for(resolved: list[tuple[dict, Path]], reg: dict) -> str | None:
    """Папка для LOCAL_STACK_MODELS — только если в ней реально есть всё нужное.

    Возвращает str(MODELS_DIR), лишь когда каждая разрешившаяся модель и её
    mmproj физически лежат в ./local-stack/models (при --copy-models — после
    копирования; иначе — когда симлинки создались либо файл уже был там).
    Если общую папку гарантировать нельзя (например, Windows без прав на
    симлинки и разные исходные папки), возвращаем None — вызывающий обязан
    сообщить о проблеме и порекомендовать --copy-models."""
    if not resolved:
        return None
    roots = reg.get("roots", [])
    for entry, path in resolved:
        target = MODELS_DIR / entry["name"]
        if not target.is_file():
            return None
        if entry.get("mmproj_candidates"):
            mmproj = None
            for cand in entry["mmproj_candidates"]:
                mmproj = find_local_file(cand, roots)
                if mmproj:
                    break
            if mmproj is not None and not (MODELS_DIR / mmproj.name).is_file():
                return None
    return str(MODELS_DIR)


def main(argv: list[str]) -> int:
    """Prepare the venv, install dependencies, wire local models, write start.bat.

    Models are NEVER downloaded by default: they are located on disk via
    docs/local_models.json and exposed to local-stack through .env
    (LOCAL_STACK_MODELS / LOCAL_LLM_MODEL / LOCAL_EMBED_MODEL). Downloads
    happen only with an explicit --download-models flag. Return the nonzero
    model-setup status if no usable LLM/embedding was found, otherwise finish
    with web dependencies (warn-only), start.bat and the completion marker.
    """
    base_python, copy_models, download_names, download_all = parse_args(argv)

    print("=== open-creator LOCAL installer (всё в этой папке, модели — без скачивания) ===")
    py = ensure_venv(base_python)
    INSTALL_COMPLETE.unlink(missing_ok=True)
    activate_and_install(py)

    reg = load_registry()
    if download_all:
        # --download-models без имён: докачиваем ровно все недостающие
        # обязательные модели (реестр уже может быть частично найден локально).
        download_names = _download_all_missing(reg)
        if download_names:
            print("[net  ] --download-models без имён: докачиваем недостающее: "
                  + ", ".join(download_names))
        else:
            print("[i    ] --download-models без имён: все обязательные модели"
                  " уже есть локально — докачка не требуется.")
    models_rc = wire_models(reg, py, copy_models, download_names)
    entries = list(reg.get("models", {}).get("llm", [])) + \
        list(reg.get("models", {}).get("embeddings", []))
    resolved = [(e, RESOLVED_PATHS[id(e)]) for e in entries
                if RESOLVED_PATHS.get(id(e)) is not None]
    llm, embed = pick_defaults(resolved)
    # LOCAL_STACK_MODELS указываем на ./local-stack/models ТОЛЬКО когда в ней
    # гарантированно лежат все нужные файлы (скопированы при --copy-models или
    # симлинки создались). Иначе — на реальную папку, где лежит единственный
    # общий набор; если единой папки нет — прерываем установку с рекомендацией.
    common_dir = models_home_for(resolved, reg)
    if common_dir is not None:
        models_home = common_dir
    else:
        homes = {str(p.parent) for _e, p in resolved}
        if len(homes) == 1:
            models_home = next(iter(homes))
        else:
            print("[fail] Не удалось собрать все модели в одной папке:"
                  " симлинки в ./local-stack/models не создаются (нет прав)"
                  " и исходные GGUF лежат в разных директориях:")
            for h in sorted(homes):
                print(f"       {h}")
            print("       Запустите установку с копированием весов в одну папку:")
            print("           python install.py --copy-models")
            return 1
    write_env(llm, embed, models_home)
    if models_rc != 0:
        print("[fail] Установка не завершена: подходящих локальных моделей нет."
              " Добавьте пути в docs/local_models.json или разрешите докачку:"
              " python install.py --download-models")
        return models_rc
    web_rc = install_web_deps()
    if web_rc != 0:
        print("[warn] Веб-интерфейс не установлен (нужен Node.js + pnpm);"
              " Python-стек готов, повторите позже: corepack enable && pnpm install")
    write_start_bat()
    print("=== Готово. Запуск: start.bat (стек + веб-интерфейс :19861). "
          "Модели подключены с диска, 0 байт скачано. ===")
    return 0


def find_first(entry: dict, roots: list[str]) -> Path | None:
    """First existing local path for a registry entry (model file only)."""
    for cand in entry.get("candidates", []):
        p = find_local_file(cand, roots)
        if p:
            return p
    return None


def _test_mode() -> int:
    """Self-check без сети/venv/pnpm: реестр + поиск по фиктивному дереву.

    Возвращает 0 при успехе; используется для проверки install.py на машине,
    где Windows-папок из реестра нет."""
    import tempfile

    reg = load_registry()
    assert isinstance(reg, dict), "нет docs/local_models.json"
    assert any(e.get("role") for e in reg["models"]["llm"]), "пустой список LLM"
    assert any("primary" in e for e in reg["models"]["embeddings"]), "нет embeddings"

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "models"
        (root / "LLM" / "GGUF").mkdir(parents=True)
        fake = [
            "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
            "Qwen2.5-7B-Instruct-q8_0.gguf",
            "workflow-generator-q8_0.gguf",
            "embeddinggemma-2-Q8_0.gguf",
            "mmproj-F16.gguf",
        ]
        for name in fake:
            (root / "LLM" / "GGUF" / name).write_text("x")
        test_reg = {"roots": [str(root)], "models": reg["models"]}
        entries = test_reg["models"]["llm"] + test_reg["models"]["embeddings"]
        RESOLVED_PATHS.clear()
        resolved = []
        for e in entries:
            p = find_first(e, test_reg["roots"])
            RESOLVED_PATHS[id(e)] = p
            if p:
                resolved.append((e, p))
        llm, embed = pick_defaults(resolved)
        assert llm and llm.endswith(".gguf"), f"не выбрана LLM: {llm}"
        assert embed == "embeddinggemma-2-Q8_0.gguf", f"embed: {embed}"
        missing = check_comfy_models(test_reg)
        assert all("safetensors" in m for m in missing), missing
    print("[test  ] OK: реестр читается, поиск/выбор работают, сеть не трогается")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        raise SystemExit(_test_mode())
    raise SystemExit(main(sys.argv[1:]))
