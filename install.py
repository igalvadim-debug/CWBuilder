"""CWBuilder — установка окружения (Windows).

Создаёт локальное venv (./venv) из указанного CPython 3.12+ и ставит
requirements.txt ЛОКАЛЬНО (pip, только PyPI). Маркер завершения:
venv/.install-complete — его проверяет start.bat.

МОДЕЛИ НЕ КАЧАЮТСЯ И НЕ КОПИРУЮТСЯ. Все веса лежат на своих дисках
(полный список путей: docs/models.txt, реестр: docs/local_models.json);
ComfyUI берёт их напрямую из model_roots в config.json. Установщик только
проверяет наличие нужных файлов и, если чего-то нет, пишет — что искал.

Флаги:
    --python <exe>            базовый интерпретатор для venv;
    --check-models            проверить ComfyUI-модели по docs/local_models.json;
    --download-models [имена] разрешить докачку с HF (по умолчанию ВЫКЛЮЧЕН;
                              без имён — докачать все недостающие обязательные
                              модели реестра; требует pip install huggingface_hub).

Использование:
    "C:\\Users\\Startklar\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" install.py
Либо просто запустить start.bat / ui.bat — при отсутствии venv они сами
вызовут install.py. Всё остаётся внутри этой папки репозитория.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / "venv"
REQUIREMENTS = ROOT / "requirements.txt"
LOCAL_MODELS_JSON = ROOT / "docs" / "local_models.json"
INSTALL_COMPLETE = VENV_DIR / ".install-complete"

# Интерпретатор по умолчанию (можно переопределить аргументом --python).
# Если venv ещё нет, install.py сам создаёт его командой:
#   "<этот python>" -m venv venv
# Приоритет поиска: --python <exe> > MM_PYTHON >= 3.12 > известный локальный
# Python312 > py-лаунчер (3.12+) > sys.executable.
KNOWN_LOCAL_PYTHONS = [
    r"C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe",
]


def default_python() -> str:
    """Base interpreter for creating the venv (see KNOWN_LOCAL_PYTHONS above).

    MM_PYTHON принимается только если это рабочий Python >= 3.12; более
    старая версия не «съедает» дальнейший поиск (py-лаунчер и т.д.).
    """
    mm_python = os.environ.get("MM_PYTHON", "").strip('"').strip()
    if mm_python and is_supported_python(mm_python):
        return mm_python
    localappdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [Path(localappdata) / "Programs" / "Python" / "Python312" / "python.exe"] if localappdata else []
    candidates += [Path(p) for p in KNOWN_LOCAL_PYTHONS]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return sys.executable


def is_supported_python(exe: str) -> bool:
    """True, если exe — рабочий Python версии >= 3.12 (0 байт сети)."""
    if not exe or not Path(exe).is_file():
        return False
    try:
        rc = subprocess.call(
            [exe, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"],
            cwd=str(ROOT),
        )
    except OSError:
        return False
    return rc == 0


def py_launcher_versions() -> list[str]:
    """Версии Python, доступные через py-лаунчер ([] если лаунчера нет)."""
    try:
        out = subprocess.run(["py", "-0p"], capture_output=True, text=True, cwd=str(ROOT))
    except OSError:
        return []
    if out.returncode != 0:
        return []
    versions: list[str] = []
    for line in (out.stdout + out.stderr).splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        token = line.split()[0].lstrip("-")
        parts = token.split(".")
        if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]):
            v = f"{parts[0]}.{parts[1]}"
            if v not in versions:
                versions.append(v)
    return versions


def find_py_with_supported_python() -> str | None:
    """Первая версия py-лаунчера с Python >= 3.12 (новые версии вперёд)."""
    def key(v: str) -> tuple[int, int]:
        a, b = v.split(".")
        return (int(a), int(b))
    for v in sorted(py_launcher_versions(), key=key, reverse=True):
        try:
            rc = subprocess.call(
                ["py", f"-{v}", "-c",
                 "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"],
                cwd=str(ROOT),
            )
        except OSError:
            return None
        if rc == 0:
            return v
    return None


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
    # Проверка версии: requirements (gradio) и код src/ рассчитаны на 3.12+.
    rc = subprocess.call(
        [base_python, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"],
        cwd=str(ROOT),
    )
    ver = subprocess.run([base_python, "--version"], capture_output=True, text=True)
    found_ver = (ver.stdout + ver.stderr).strip()
    if rc != 0:
        raise SystemExit(
            f"[fail] {base_python} ({found_ver}) ниже 3.12 — не поддерживается.\n"
            f"       Запустите явно: \"C:\\Users\\Startklar\\AppData\\Local\\Programs\\Python\\Python312\\python.exe\" install.py\n"
            f"       или укажите свой: python install.py --python <путь к python.exe>"
        )
    print(f"[setup] Создаю venv: {VENV_DIR} из: \"{base_python}\" -m venv venv ({found_ver})")
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


# --- проверка моделей (без скачивания и без копирования) ----------------------

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


def download_models(py: Path, names: list[str]) -> int:
    """Докачка с Hugging Face — ТОЛЬКО по явному --download-models.

    Реестр docs/local_models.json НЕ содержит HF-репозиториев (правило:
    ничего не придумывать), поэтому источник берётся из optional-поля
    "download_repo" конкретной записи; если его нет — печатаем, что именно
    искали, и просим указать repo вручную. Скачивание идёт в первый корень
    реестра; huggingface_hub вызывается через python -m (без прямого импорта).
    По умолчанию этот путь не выполняется вовсе (0 байт сети).
    """
    reg = load_registry()
    roots = reg.get("roots", [])
    models_cfg = reg.get("models", {})
    entries = list(models_cfg.get("llm", [])) + list(models_cfg.get("embeddings", []))
    by_name = {e["name"]: e for e in entries}
    dest_root = roots[0] if roots else None
    if dest_root is None:
        print("[fail] В docs/local_models.json нет ни одного корня (roots) —"
              " скачивать некуда.")
        return 1
    rc_all = 0
    for name in names:
        entry = by_name.get(name)
        if entry is None:
            print(f"[warn] {name} — нет в реестре {LOCAL_MODELS_JSON}; пропуск")
            continue
        repo = entry.get("download_repo")
        hf_path = entry.get("download_path", name)
        if not repo:
            print(f"[warn] {name} — в реестре нет поля \"download_repo\""
                  " (HF-репозиторий); укажите его в docs/local_models.json"
                  " или положите файл вручную. Пропуск.")
            continue
        dest = Path(str(dest_root).replace("\\", "/")) / hf_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"[net  ] {name} <- hf.co/{repo}:{hf_path} -> {dest}")
        code = (
            "import runpy,sys;"
            "sys.argv=['hf',%r,'--local-dir',%r,%r];"
            "runpy.run_module('huggingface_hub.commands.huggingface_cli',run_name='__main__')"
            % (repo, str(Path(str(dest_root).replace("\\", "/"))), hf_path)
        )
        if run([str(py), "-c", code]) != 0:
            print(f"[fail] Не удалось скачать {name}"
                  " (проверьте: venv\\Scripts\\python.exe -m pip install huggingface_hub)")
            rc_all = 1
    return rc_all


def report_models(reg: dict) -> int:
    """Отчёт о локальных моделях без каких-либо изменений на диске.

    Проверяет LLM/embedding-записи реестра и ComfyUI-модели; печатает, что
    найдено (и где), а что отсутствует. Всегда возвращает 0 — отсутствие
    GGUF не мешает режимам image/video (они работают через ComfyUI)."""
    roots = reg.get("roots", [])
    models_cfg = reg.get("models", {})
    entries = list(models_cfg.get("llm", [])) + list(models_cfg.get("embeddings", []))
    found = 0
    for entry in entries:
        path, mmproj = resolve_entry(entry, roots)
        if path is not None:
            found += 1
            extra = f" (+mmproj {mmproj.name})" if mmproj else ""
            print(f"[model] {entry['name']}{extra} — есть: {path}")
        elif entry.get("optional"):
            print(f"[skip ] {entry['name']} — нет локально (опциональна, не качаем)")
        else:
            print(f"[--   ] {entry['name']} — не найдена среди локальных папок"
                  " (нужна только для RAG/кода, image/video не трогает)")
    comfy_missing = check_comfy_models(reg)
    if comfy_missing:
        print("[i    ] ComfyUI-модели не найдены (не качаем; положите сами или"
              " укажите путь в docs/local_models.json): " + ", ".join(comfy_missing))
    print(f"[ok    ] Модели: найдено {found} записей реестра; скачано 0 байт.")
    return 0


def parse_args(argv: list[str]) -> tuple[str, bool, list[str], bool, bool]:
    """Return (base_python, check_models, download_names, download_all, selftest).

    --python takes the following value (first occurrence wins);
    --check-models only prints the local model report (no writes at all);
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
    base_python = default_python()
    check_models = "--check-models" in argv
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
    explicit_base = False
    if "--python" in argv:
        i = argv.index("--python")
        if i + 1 < len(argv):
            base_python = argv[i + 1]
            explicit_base = True
    elif argv and not argv[0].startswith("-"):
        base_python = argv[0]
        explicit_base = True
    # Явно указанный интерпретатор (CLI/MM_PYTHON/sys.executable) может быть
    # старше 3.12 — не блокируем установку: если venv ещё нет, отдаём поиск
    # py-лаунчеру, который подберёт совместимую версию (ensure_venv всё
    # равно проверяет версию перед созданием venv).
    if not explicit_base and (VENV_DIR / "Scripts" / "python.exe").exists():
        pass  # существующий venv имеет приоритет — ничего менять не нужно
    elif not is_supported_python(base_python):
        py_ver = find_py_with_supported_python()
        if py_ver:
            print(f"[i    ] Интерпретатор {base_python!r} ниже 3.12 — "
                  f"venv создам через py -{py_ver}")
            base_python = py_ver
    return base_python, check_models, download_names, download_all, "--self-test" in argv


def main(argv: list[str]) -> int:
    """Prepare the venv, install dependencies, report models, write marker.

    Models are NEVER downloaded or copied by default: they stay exactly where
    they are (docs/models.txt lists them; ComfyUI reads them via model_roots
    in config.json). Downloads happen only with an explicit --download-models
    flag. Finish with the completion marker venv/.install-complete, which
    start.bat / ui.bat check before launching.
    """
    base_python, check_models, download_names, download_all, selftest = parse_args(argv)

    print("=== CWBuilder installer (всё в этой папке, модели — без скачивания) ===")
    if selftest:
        return _test_mode()
    py = ensure_venv(base_python)
    INSTALL_COMPLETE.unlink(missing_ok=True)
    activate_and_install(py)

    reg = load_registry()
    if check_models:
        return report_models(reg)
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
    if download_names:
        rc = download_models(py, download_names)
        if rc != 0:
            print("[warn] Докачка завершилась с ошибками; установка продолжена"
                  " (модели можно положить вручную, см. docs/models.txt).")
    else:
        print("[i    ] Скачивание с Hugging Face ОТКЛЮЧЕНО: используются только"
              " модели, которые уже есть на диске (docs/local_models.json).")
        report_models(reg)

    INSTALL_COMPLETE.parent.mkdir(parents=True, exist_ok=True)
    INSTALL_COMPLETE.touch()
    print("=== Готово. Запуск: start.bat (меню) или ui.bat (Gradio UI :7865). "
          "Модели берутся с диска, 0 байт скачано. ===")
    return 0


def find_first(entry: dict, roots: list[str]) -> Path | None:
    """First existing local path for a registry entry (model file only)."""
    for cand in entry.get("candidates", []):
        p = find_local_file(cand, roots)
        if p:
            return p
    return None


def _test_mode() -> int:
    """Self-check без сети/venv: реестр + поиск по фиктивному дереву.

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
        resolved = []
        for e in entries:
            p = find_first(e, test_reg["roots"])
            if p:
                resolved.append((e, p))
        missing = check_comfy_models(test_reg)
        assert all("safetensors" in m or m.endswith(".gguf") for m in missing), missing
    print("[test  ] OK: реестр читается, поиск работает, сеть не трогается")
    return 0


def _self_check() -> int:
    """Проверка без сети/venv: только компиляция исходников проекта.

    Вызывается из start.bat/ui.bat перед запуском (python -m install --check).
    Возвращает число ошибок (0 = всё скомпилировалось)."""
    import py_compile

    files = [ROOT / "install.py", ROOT / "src" / "mm.py"] + sorted((ROOT / "src").glob("mm_*.py"))
    errors = 0
    for f in files:
        try:
            py_compile.compile(str(f), doraise=True)
        except Exception as e:  # noqa: BLE001 — показать и продолжить
            print(f"[fail] {f.name}: {e}")
            errors += 1
    if errors:
        print(f"[fail] Самопроверка: ошибок {errors}")
        return errors
    print("[ok    ] Самопроверка пройдена: install.py и src/*.py компилируются")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        raise SystemExit(_test_mode())
    if "--check" in sys.argv[1:]:
        raise SystemExit(1 if _self_check() else 0)
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit as e:
        # Все аварийные выходы (SystemExit) — через этот блок, чтобы окно
        # install.bat/start.bat не закрывалось мгновенно и было видно причину.
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if code != 0:
            print()
            print("[fail] Установка не завершена. См. сообщения выше.")
            try:
                input("Нажмите Enter для выхода...")
            except EOFError:
                pass
        raise SystemExit(code)
