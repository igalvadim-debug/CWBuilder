"""Vertraege des Installers (install.py) und der Windows-Startskripte.

Die Tests fuehren keine Installation aus: sie pruefen Argumentbehandlung,
venv-Erkennung und die ASCII/Inhalts-Regeln der .bat-Dateien.
Passend zum Plan 1.4: install.py kennt KEIN --copy-models/--download-models
als funktionale Modell-Beschaffung mehr; Modelle bleiben auf der Festplatte.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import install


class ParseArgsTests(unittest.TestCase):
    """parse_args liefert (base_python, download_names); Modelle werden nicht kopiert."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.python = Path(self.directory.name) / "Python 3.12" / "python.exe"
        self.python.parent.mkdir()
        self.python.touch()
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_utf8_environment_defaults_are_set(self):
        install.parse_args([])
        self.assertEqual(os.environ["PYTHONUTF8"], "1")
        self.assertEqual(os.environ["PYTHONIOENCODING"], "utf-8")

    def test_explicit_python_option_wins_over_environment(self):
        os.environ["MM_PYTHON"] = str(self.python)
        explicit = str(self.python.with_name("explicit.exe"))
        with patch.object(install, "is_supported_python", return_value=True):
            base, names = install.parse_args(["--python", explicit])
        self.assertEqual(base, explicit)
        self.assertEqual(names, [])

    def test_positional_interpreter_is_accepted(self):
        with patch.object(install, "is_supported_python", return_value=True):
            base, _ = install.parse_args(["positional.exe"])
        self.assertEqual(base, "positional.exe")

    def test_mm_python_used_when_it_exists(self):
        os.environ["MM_PYTHON"] = f'  "{self.python}"  '
        with patch.object(install, "is_supported_python", return_value=True):
            base, _ = install.parse_args([])
        self.assertEqual(base, str(self.python))

    def test_missing_mm_python_falls_back_to_default(self):
        os.environ["MM_PYTHON"] = str(self.python.with_name("missing.exe"))
        with patch.object(install, "default_python", return_value="fallback.exe"), \
                patch.object(install, "is_supported_python", return_value=True):
            base, _ = install.parse_args([])
        self.assertEqual(base, "fallback.exe")

    def test_unsupported_fallback_hands_py_launcher_version_to_ensure_venv(self):
        # Der Umgebungs-Fallback kann zu alt sein: dann uebergibt parse_args
        # eine py-Version (z.B. "3.13"), die ensure_venv als `py -3.13` aufruft.
        with patch.object(install, "default_python", return_value="alt.exe"), \
                patch.object(install, "is_supported_python", return_value=False), \
                patch.object(install, "find_py_with_supported_python", return_value="3.13"):
            base, _ = install.parse_args([])
        self.assertEqual(base, "3.13")

    def test_download_model_names_are_recorded_but_never_copied(self):
        with patch.object(install, "is_supported_python", return_value=True):
            base, names = install.parse_args(["x.exe", "--download-models", "a.gguf", "b.gguf"])
        self.assertEqual(base, "x.exe")
        self.assertEqual(names, ["a.gguf", "b.gguf"])
        # main() darf wegen dieser Namen nichts herunterladen oder kopieren.
        source = (ROOT / "install.py").read_text(encoding="utf-8")
        self.assertNotIn("--copy-models", source)
        self.assertNotIn("shutil.copy", source)


class EnsureVenvTests(unittest.TestCase):
    """ensure_venv: vorhandene venv wird bestaetigt, neue mit Versionsschranke erzeugt."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        patches = [
            patch.object(install, "ROOT", self.root),
            patch.object(install, "VENV_DIR", self.root / "venv"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_existing_venv_interpreter_is_reused_without_creation(self):
        py = install.venv_python()
        py.parent.mkdir(parents=True)
        py.touch()
        self.assertEqual(install.ensure_venv("basis.exe"), py)

    def test_missing_base_interpreter_raises_systemexit(self):
        with self.assertRaises(SystemExit):
            install.ensure_venv(str(self.root / "fehlt.exe"))

    def test_base_below_312_is_rejected_before_any_venv_creation(self):
        base = self.root / "python.exe"
        base.touch()
        calls = []
        with patch.object(install.subprocess, "call",
                          side_effect=lambda cmd, **kw: calls.append(cmd) or 1), \
                patch.object(install.subprocess, "run",
                             return_value=subprocess.CompletedProcess(args=[], returncode=0,
                                                                      stdout="Python 3.11.9", stderr="")), \
                patch.object(install.subprocess, "check_call") as check_call:
            with self.assertRaises(SystemExit) as raised:
                install.ensure_venv(str(base))
        self.assertIn("3.12", str(raised.exception))
        check_call.assert_not_called()

    def test_supported_base_creates_the_venv(self):
        base = self.root / "python.exe"
        base.touch()

        def fake_check_call(cmd, cwd=None):
            # Nachbau: venv-Modul legt das Interpreter-File an.
            py = install.venv_python()
            py.parent.mkdir(parents=True, exist_ok=True)
            py.touch()

        with patch.object(install.subprocess, "call", return_value=0), \
                patch.object(install.subprocess, "run",
                             return_value=subprocess.CompletedProcess(args=[], returncode=0,
                                                                      stdout="Python 3.12.10", stderr="")), \
                patch.object(install.subprocess, "check_call", side_effect=fake_check_call):
            py = install.ensure_venv(str(base))
        self.assertTrue(py.is_file())


class LauncherContentTests(unittest.TestCase):
    """start.bat / ui.bat / install.bat: nur ASCII, deutsch ohne Umlaute, kein open-creator."""

    BATS = ("start.bat", "ui.bat", "install.bat")

    def test_bats_are_pure_ascii(self):
        for name in self.BATS:
            with self.subTest(name=name):
                data = (ROOT / name).read_bytes()
                non_ascii = [b for b in data if b > 0x7F]
                self.assertEqual(non_ascii, [], f"{name} enthaelt Nicht-ASCII-Bytes")

    def test_bats_have_no_dashes_or_umlaut_words(self):
        # Em-/En-Dash und Umlaute waeren Nicht-ASCII; zusaendlich verbotene Woerter:
        pattern = re.compile(r"[a-zA-Z]*[\u00e4\u00f6\u00fc\u00df\u2013\u2014]")
        for name in self.BATS:
            with self.subTest(name=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIsNone(pattern.search(text), f"{name}: verbotenes Zeichen")

    def test_bats_do_not_reference_open_creator(self):
        for name in self.BATS:
            with self.subTest(name=name):
                text = (ROOT / name).read_text(encoding="utf-8").lower()
                for forbidden in ("open-creator", "opencreator", "local-stack", "pnpm", "19861"):
                    self.assertNotIn(forbidden, text)

    def test_ui_and_start_launch_gradio_via_src_mm(self):
        start = (ROOT / "start.bat").read_text(encoding="utf-8")
        ui = (ROOT / "ui.bat").read_text(encoding="utf-8")
        self.assertIn('src\\mm.py ui', start)
        self.assertIn('src\\mm.py ui', ui)
        # Bei einem Absturz darf das Fenster nicht einfach verschwinden.
        self.assertIn("pause", start.split("\n:ui\n", 1)[1].split(":comfy", 1)[0])
        self.assertIn("if errorlevel 1", ui)

    def test_install_bat_probes_the_venv_before_using_it(self):
        text = (ROOT / "install.bat").read_text(encoding="utf-8")
        # Die venv wird nur gewaehlt, wenn ihr Python wirklich startet.
        self.assertRegex(
            text,
            r'(?ms)if exist "%~dp0venv\\Scripts\\python\.exe" \(\s*\n\s*"%~dp0venv\\Scripts\\python\.exe" -c',
        )


if __name__ == "__main__":
    unittest.main()
