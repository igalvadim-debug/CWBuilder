"""Portable batch artifact contracts; these checks do not execute cmd.exe.

CWBuilder launchers (start.bat / ui.bat / install.bat) must be ASCII-only,
German without umlauts, and free of the old open-creator stack remnants.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BATS = ("start.bat", "ui.bat", "install.bat")


def commands(filename):
    """Ignore prose so comments cannot satisfy a launcher contract."""
    return "\n".join(line.strip() for line in (ROOT / filename).read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.lstrip().lower().startswith("rem "))


def section(text, label):
    m = re.search(rf"^{label}\r?\n(.*?)(?=^:\w|\Z)", text, re.MULTILINE | re.DOTALL)
    assert m, f"section :{label} not found"
    return m.group(1)


class WindowsLauncherContractTests(unittest.TestCase):
    def test_bat_files_are_ascii_only_and_crlf(self):
        for name in BATS:
            with self.subTest(bat=name):
                data = (ROOT / name).read_bytes()
                try:
                    data.decode("ascii")
                except UnicodeDecodeError as e:
                    self.fail(f"{name} contains non-ASCII bytes: {e}")
                # cmd.exe breaks on bare LF endings.
                crlf = data.count(b"\r\n")
                lf_only = data.count(b"\n") - crlf
                self.assertEqual(lf_only, 0, f"{name} has {lf_only} bare LF lines")

    def test_no_open_creator_or_nodejs_left_in_launchers(self):
        banned = ("open-creator", "OPENCREATOR", "local-stack", "pnpm", "corepack",
                  "web-dev-wrapper", "19861", ".env")
        for name in BATS:
            text = (ROOT / name).read_text(encoding="utf-8")
            for token in banned:
                with self.subTest(bat=name, token=token):
                    self.assertNotIn(token, text)

    def test_fresh_install_reaches_installer_without_requiring_a_venv(self):
        run = section(commands("install.bat"), ":run")
        invocation = '"%PYPATH%" %PYARGS% install.py %*'
        self.assertIn(invocation, run)
        # Regression: the deleted guards rejected every first installation.
        self.assertNotIn("if not exist", run[:run.index(invocation)].lower())
        self.assertRegex(run, re.escape(invocation) + r"\r?\nif errorlevel 1 \(")
        self.assertIn("exit /b 1", run)

    def test_installbat_accepts_mm_python_only_for_supported_versions(self):
        body = commands("install.bat")
        self.assertIn('if defined MM_PYTHON if exist "%MM_PYTHON%" (', body)
        self.assertIn("sys.version_info ^>= (3, 12)", body)
        # Candidate order: venv first, then MM_PYTHON, then known Python312, then py.
        positions = [body.index(c) for c in (
            'if exist "venv\\Scripts\\python.exe"',
            'if defined MM_PYTHON if exist "%MM_PYTHON%" (',
            'if exist "%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe"',
            'py -3.12 -c "import sys"',
        )]
        self.assertEqual(positions, sorted(positions))

    def test_startbat_dispatches_subcommands_and_menu(self):
        launcher = commands("start.bat")
        for subcmd in ("video", "image", "list", "check"):
            with self.subTest(subcmd=subcmd):
                self.assertIn(f'if /i "%~1"=="{subcmd}"  goto mmcmd', launcher)
        self.assertIn('if /i "%~1"=="ui"     goto runui', launcher)
        self.assertIn('"txt" == ".txt"'.replace('"', ""), launcher.replace('if /i "%~x1"==".txt"  goto mmcmd', "txt"))
        # Menu offers Gradio UI ([G]) and forwards it to src\mm_ui.py.
        self.assertIn("[G]", (ROOT / "start.bat").read_text(encoding="utf-8"))
        self.assertIn("src\\mm_ui.py", launcher)

    def test_startbat_menu_requires_venv_install_before_gradio(self):
        launcher = commands("start.bat")
        # The menu path checks the install marker and falls back to :install.
        self.assertIn('if exist "venv\\.install-complete" goto menu', launcher)
        install = section(launcher, ":install")
        self.assertIn('("venv\\Scripts\\python.exe" install.py) else ("%PYEXE%" install.py)', install)
        self.assertIn("exit /b 1", install)

    def test_startbat_ui_runs_selftest_before_launch(self):
        runui = section(commands("start.bat"), ":runui")
        self.assertLess(runui.index("install.py --check"), runui.index("src\\mm_ui.py"))
        self.assertIn('start "" "http://127.0.0.1:7865"', runui)

    def test_uibat_starts_gradio_directly(self):
        ui = (ROOT / "ui.bat").read_text(encoding="utf-8")
        self.assertIn("src\\mm_ui.py", ui)
        self.assertIn("http://127.0.0.1:7865", ui)
        self.assertIn("install.py --check", ui)

    def test_comfy_startbat_is_read_from_config_not_hardcoded(self):
        comfy = section(commands("start.bat"), ":comfy")
        self.assertIn("config.json", comfy)
        self.assertIn("start_bat", comfy)


if __name__ == "__main__":
    unittest.main()
