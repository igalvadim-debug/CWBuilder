"""Installer interpreter selection and launcher generation without installation."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import install


class ParseArgsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.python = Path(self.directory.name) / "Python 3.12 — локальный" / "python.exe"
        self.python.parent.mkdir()
        self.python.touch()
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_default_interpreter_and_utf8_environment(self):
        self.assertEqual(install.parse_args([]), (install.DEFAULT_PYTHON, False, [], False))
        self.assertEqual(os.environ["PYTHONUTF8"], "1")
        self.assertEqual(os.environ["PYTHONIOENCODING"], "utf-8")

    def test_existing_mm_python_is_selected_without_executing_it(self):
        # An empty file is sufficient: parsing must never launch Python.
        os.environ["MM_PYTHON"] = str(self.python)
        self.assertEqual(install.parse_args([]), (str(self.python), False, [], False))

    def test_mm_python_accepts_quotes_and_whitespace(self):
        for value in (str(self.python), f'"{self.python}"', f"  {self.python}  ",
                      f'"  {self.python}  "'):
            with self.subTest(value=value):
                os.environ["MM_PYTHON"] = value
                self.assertEqual(install.parse_args([])[0], str(self.python))

    def test_empty_or_missing_mm_python_falls_back(self):
        for value in ("", "   ", '""', '"   "', str(self.python.with_name("missing.exe"))):
            with self.subTest(value=value):
                os.environ["MM_PYTHON"] = value
                self.assertEqual(install.parse_args([])[0], install.DEFAULT_PYTHON)

    def test_deleted_mm_python_is_not_reused_by_a_later_parse(self):
        os.environ["MM_PYTHON"] = str(self.python)
        self.assertEqual(install.parse_args([])[0], str(self.python))
        self.python.unlink()
        self.assertEqual(install.parse_args([])[0], install.DEFAULT_PYTHON)

    def test_explicit_interpreter_overrides_environment_even_if_not_yet_present(self):
        os.environ["MM_PYTHON"] = str(self.python)
        explicit = str(self.python.with_name("explicit.exe"))
        self.assertEqual(install.parse_args(["--python", explicit])[0], explicit)

    def test_positional_interpreter_overrides_environment(self):
        os.environ["MM_PYTHON"] = str(self.python)
        self.assertEqual(install.parse_args(["positional.exe"])[0], "positional.exe")

    def test_first_python_option_overrides_positional_and_environment(self):
        os.environ["MM_PYTHON"] = str(self.python)
        args = ["positional.exe", "--python", "first.exe", "--python", "second.exe"]
        self.assertEqual(install.parse_args(args)[0], "first.exe")

    def test_missing_python_value_keeps_the_environment_fallback(self):
        os.environ["MM_PYTHON"] = str(self.python)
        self.assertEqual(install.parse_args(["--python"])[0], str(self.python))

    def test_model_options_preserve_environment_selection_and_input_arguments(self):
        os.environ["MM_PYTHON"] = str(self.python)
        cases = (
            (["--copy-models"], True, [], False),
            (["--download-models"], False, [], True),
            (["--download-models", "--copy-models"], True, [], True),
            (["--download-models", "llm.gguf", "embedding.gguf", "--copy-models"],
             True, ["llm.gguf", "embedding.gguf"], False),
        )
        for args, copy_models, names, download_all in cases:
            with self.subTest(args=args):
                original = args.copy()
                self.assertEqual(install.parse_args(args),
                                 (str(self.python), copy_models, names, download_all))
                self.assertEqual(args, original)

    def test_explicit_python_after_downloads_is_not_a_model_name(self):
        os.environ["MM_PYTHON"] = str(self.python)
        self.assertEqual(
            install.parse_args(["--download-models", "model.gguf", "--python", "explicit.exe"]),
            ("explicit.exe", False, ["model.gguf"], False),
        )

    def test_utf8_defaults_fill_only_unset_variables(self):
        for supplied in ({"PYTHONUTF8": "0"}, {"PYTHONIOENCODING": "cp1251:replace"},
                         {"PYTHONUTF8": "", "PYTHONIOENCODING": ""}):
            with self.subTest(supplied=supplied), patch.dict(os.environ, supplied, clear=True):
                install.parse_args([])
                self.assertEqual(os.environ["PYTHONUTF8"], supplied.get("PYTHONUTF8", "1"))
                self.assertEqual(os.environ["PYTHONIOENCODING"],
                                 supplied.get("PYTHONIOENCODING", "utf-8"))

    def test_repeated_parsing_preserves_caller_environment_changes(self):
        install.parse_args([])
        os.environ["PYTHONUTF8"] = "0"
        os.environ["PYTHONIOENCODING"] = "ascii:replace"
        install.parse_args([])
        self.assertEqual(os.environ["PYTHONUTF8"], "0")
        self.assertEqual(os.environ["PYTHONIOENCODING"], "ascii:replace")


class LauncherGenerationTests(unittest.TestCase):
    def test_generated_launcher_matches_the_checked_in_launcher(self):
        # Installing must not restore a stale launcher with different Python fallbacks.
        expected = (Path(__file__).resolve().parents[1] / "start.bat").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "venv" / ".install-complete"
            with patch.object(install, "ROOT", root), \
                    patch.object(install, "INSTALL_COMPLETE", marker), \
                    redirect_stdout(io.StringIO()):
                install.write_start_bat()
            actual = (root / "start.bat").read_bytes()
            self.assertEqual(actual, expected)
            self.assertNotIn(b"\n", actual.replace(b"\r\n", b""))
            self.assertTrue(marker.is_file())

    def test_installation_replaces_an_old_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bat = root / "start.bat"
            bat.write_text("@echo off\ngoto menu\n", encoding="utf-8")
            with patch.object(install, "ROOT", root), \
                    patch.object(install, "INSTALL_COMPLETE", root / "venv" / ".install-complete"), \
                    redirect_stdout(io.StringIO()):
                install.write_start_bat()
            self.assertEqual(bat.read_text(encoding="utf-8"), install.START_BAT)


if __name__ == "__main__":
    unittest.main()
