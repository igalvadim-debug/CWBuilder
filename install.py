"""CWBuilder — установка Python-окружения (Windows).

Создаёт локальное venv (./venv) из указанного CPython, ставит requirements.txt.
Модели НЕ качаются и НЕ копируются: они берутся с диска по путям из
config.json (model_roots) и docs/local_models.json — ComfyUI читает их
напрямую через extra_model_paths.yaml.

Флаги:
    --python <exe>   базовый интерпретатор для venv (по умолчанию: поиск Python 3.12+).

Использование:
    "C:\\Users\\Startklar\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" install.py
Либо просто запустить start.bat — при отсутствии venv он сам вызовет install.py.
Всё остаётся внутри этой папки репозитория: venv, кэш pip — local.
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / "venv"
REQUIREMENTS = ROOT / "requirements.txt"
INSTALL_COMPLETE = VENV_DIR / ".install-complete"

# Известные локальные Python 3.12 (приоритет поиска)
KNOWN_LOCAL_PYTHONS = [
    r"C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe",
]


def known_local_python() -> str:
    """Первый существующий известный локальный Python312 ('' если не найден)."""
    localappdata = os.environ.get("LOCALAPPDATA", "")
    candidates = ([Path(localappdata) / "Programs" / "Python" / "Python312" / "python.exe"]
                  if localappdata else [])
    candidates += [Path(p) for p in KNOWN_LOCAL_PYTHONS]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return ""


def default_python() -> str:
    """Select a base interpreter path without checking its Python version.

    Prefer MM_PYTHON after stripping surrounding whitespace and double quotes,
    if it names an existing file; otherwise use known_local_python(), then
    sys.executable. MM_PYTHON need not be executable or a supported Python.
    """
    mm_python = _clean_path(os.environ.get("MM_PYTHON", ""))
    if mm_python and Path(mm_python).is_file():
        return mm_python
    local = known_local_python()
    if local:
        return local
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
    checking base_python. Raise SystemExit if base_python is absent or creation
    leaves no interpreter. Creation failures propagate as subprocess.CalledProcessError;
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
    print("[ok    ] Зависимости установлены в venv (все локально)")


def _clean_path(value: str) -> str:
    """Снять обрамляющие кавычки и пробелы с пути из аргументов/окружения."""
    return value.strip().strip('"').strip()


def parse_args(argv: list[str]) -> tuple[str, list[str]]:
    """Return (base_python, download_names) from argv.

    --python <exe>  explicit interpreter
    --download-models [names...]  reserved for future use (no-op currently)
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    download_names: list[str] = []
    dl_enabled = "--download-models" in argv
    if dl_enabled:
        i = argv.index("--download-models")
        for a in argv[i + 1:]:
            if a.startswith("-"):
                break
            download_names.append(a)

    # Позиционный интерпретатор — первое значение argv, не являющееся опцией
    positional = ""
    skip_next = False
    dl_seen = False
    for a in argv:
        if skip_next:
            skip_next = False
            continue
        if a == "--python":
            skip_next = True
            dl_seen = False
            continue
        if a == "--download-models":
            dl_seen = True
            continue
        if a.startswith("-"):
            dl_seen = False
            continue
        if dl_seen:
            break
        positional = a
        break

    mm_python = _clean_path(os.environ.get("MM_PYTHON", ""))
    if mm_python and not Path(mm_python).is_file():
        mm_python = ""

    explicit_base = ""
    if "--python" in argv:
        i = argv.index("--python")
        if i + 1 < len(argv):
            explicit_base = _clean_path(argv[i + 1])
    if not explicit_base and positional:
        explicit_base = _clean_path(positional)

    if explicit_base:
        base_python = explicit_base
    elif mm_python:
        base_python = mm_python
    else:
        base_python = default_python()
        # Фолбэк из окружения может быть старше 3.12 — не блокируем установку:
        # отдаём поиск py-лаунчеру, который подберёт совметимую версию.
        if not is_supported_python(base_python):
            py_ver = find_py_with_supported_python()
            if py_ver:
                print(f"[i    ] Интерпретатор {base_python!r} ниже 3.12 — "
                      f"venv создам через py -{py_ver}")
                base_python = py_ver
    return base_python, download_names


def main(argv: list[str]) -> int:
    """Prepare the venv, install dependencies, write completion marker."""
    base_python, download_names = parse_args(argv)

    print("=== CWBuilder installer (venv + requirements, модели — с диска) ===")
    py = ensure_venv(base_python)
    INSTALL_COMPLETE.unlink(missing_ok=True)
    activate_and_install(py)

    # Проверка наличия моделей (только информируем, не качаем и не копируем)
    config_path = ROOT / "config.json"
    if config_path.exists():
        import json
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            roots = []
            for target in cfg.get("targets", {}).values():
                roots.extend(target.get("model_roots", []))
            if roots:
                print("[info] Проверка model_roots из config.json:")
                for r in roots:
                    p = Path(r)
                    status = "OK" if p.is_dir() else "НЕТ"
                    print(f"       {r}  [{status}]")
        except Exception as e:
            print(f"[warn] config.json: {e}")

    INSTALL_COMPLETE.parent.mkdir(parents=True, exist_ok=True)
    INSTALL_COMPLETE.touch()
    print("=== Готово. Запуск: start.bat (меню: [G] Gradio UI, [C] ComfyUI, [P] Modi prüfen) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))