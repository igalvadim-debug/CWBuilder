"""CWBuilder Windows launcher contracts; these checks do not execute cmd.exe."""

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def commands(filename):
    """Ignore prose so comments cannot satisfy a launcher contract."""
    return "\n".join(line.strip() for line in (ROOT / filename).read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.lstrip().lower().startswith("rem "))


def section(text, label):
    match = re.search(rf"^:{label}\n(.*?)(?=^:\w|\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return ""
    return match.group(1)


class CWBuilderLauncherContractTests(unittest.TestCase):
    def test_install_bat_runs_install_py_with_venv_python(self):
        text = commands("install.bat")
        # Should call venv Python with install.py
        self.assertIn('"%~dp0venv\\Scripts\\python.exe" install.py', text)
        # Should forward all arguments
        self.assertIn("%*", text)
        # Should check Python version
        self.assertIn("sys.version_info >= (3, 12)", text)

    def test_start_bat_menu_has_required_options(self):
        text = commands("start.bat")
        # Menu should have G, C, I, P, Q options
        self.assertIn("choice /c GCI PQ", text)
        # Should have :ui, :comfy, :install, :check labels
        for label in ["ui", "comfy", "install", "check"]:
            self.assertIn(f":{label}", text)

    def test_start_bat_ui_launches_gradio_on_port_7865(self):
        text = commands("start.bat")
        ui_section = section(text, "ui")
        # Should use venv Python
        self.assertIn('"%PYEXE%" mm.py ui', ui_section)
        # Should set encoding
        self.assertIn("PYTHONUTF8=1", ui_section)
        self.assertIn("PYTHONIOENCODING=utf-8", ui_section)

    def test_start_bat_comfy_launches_external_comfyui(self):
        text = commands("start.bat")
        comfy_section = section(text, "comfy")
        # Should reference external ComfyUI bat file
        self.assertIn("start_comfyu2i.bat", comfy_section)
        # Should use start command for separate window
        self.assertIn('start ""', comfy_section)

    def test_start_bat_install_runs_install_py(self):
        text = commands("start.bat")
        install_section = section(text, "install")
        self.assertIn('"%PYEXE%" install.py', install_section)

    def test_start_bat_check_runs_mm_check(self):
        text = commands("start.bat")
        check_section = section(text, "check")
        self.assertIn('"%PYEXE%" mm.py check', check_section)

    def test_start_bat_no_venv_shows_error(self):
        text = commands("start.bat")
        no_venv_section = section(text, "no_venv")
        self.assertIn("FEHLER", no_venv_section)
        self.assertIn("venv\\Scripts\\python.exe", no_venv_section)


class InstallBatContractTests(unittest.TestCase):
    """Check installer branches without running an installation or a prompt."""

    VENV_PYTHON = r"%~dp0venv\Scripts\python.exe"
    LOCAL_PYTHONS = (
        r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe",
        r"C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe",
    )

    def setUp(self):
        self.text = commands("install.bat")
        self.entry = self.text.split("\n:run\n", 1)[0]
        self.execution = section(self.text, "exec")

    def existence_guard(self, path, missing=False):
        condition = "if not exist" if missing else "if exist"
        match = re.search(
            rf'^{condition} "{re.escape(path)}" \(\n(.*?)^\)',
            self.entry, re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match, f"Missing {condition} guard for {path}")
        return match

    def test_script_directory_and_utf8_are_set_before_discovery(self):
        first_guard = self.entry.index('if not exist "%~dp0install.py"')
        for command in ('setlocal', 'chcp 65001 >nul', 'cd /d "%~dp0"',
                        'set "PYTHONUTF8=1"', 'set "PYTHONIOENCODING=utf-8"'):
            with self.subTest(command=command):
                self.assertIn(command, self.entry[:first_guard].splitlines())

    def test_missing_install_script_exits_before_interpreter_discovery(self):
        guard = self.existence_guard("%~dp0install.py", missing=True)
        self.assertIn("pause", guard.group(1).splitlines())
        self.assertRegex(guard.group(1), r"(?m)^exit /b 1$")
        self.assertLess(guard.end(), self.existence_guard(self.VENV_PYTHON).start())

    def test_existing_venv_is_quoted_and_bypasses_discovery(self):
        guard = self.existence_guard(self.VENV_PYTHON)
        self.assertIn(f'set "PYPATH="{self.VENV_PYTHON}""', guard.group(1).splitlines())
        self.assertRegex(guard.group(1), r"(?m)^goto exec$")
        self.assertLess(guard.end(), self.existence_guard(self.LOCAL_PYTHONS[0]).start())
        self.assertTrue(self.execution, "The venv jump must reach the installer call")

    def test_absent_venv_is_not_invoked_during_discovery(self):
        guard = self.existence_guard(self.VENV_PYTHON)
        outside_guard = self.entry[:guard.start()] + self.entry[guard.end():]
        self.assertNotRegex(
            outside_guard,
            rf'(?mi)^(?:call )?"{re.escape(self.VENV_PYTHON)}"\s',
            "A missing venv must fall back without trying to execute its python.exe",
        )

    def test_local_python_candidates_precede_path_lookup_in_priority_order(self):
        guards = [self.existence_guard(path) for path in self.LOCAL_PYTHONS]
        self.assertLess(guards[0].end(), guards[1].start())
        self.assertLess(guards[1].end(), self.entry.index("where py >nul 2>&1"))
        for path, guard in zip(self.LOCAL_PYTHONS, guards):
            with self.subTest(path=path):
                assignment = re.search(r'^set "PYPATH=(.*)"$', guard.group(1), re.MULTILINE)
                self.assertIsNotNone(assignment, "Existing Python must be selected")
                self.assertEqual(assignment.group(1).strip('"'), path)
                self.assertRegex(guard.group(1), r"(?m)^goto run$")

    def test_localappdata_python_path_keeps_quotes_for_profiles_with_spaces(self):
        # LOCALAPPDATA may contain spaces; call expands PYPATH without adding quotes.
        path = self.LOCAL_PYTHONS[0]
        guard = self.existence_guard(path)
        self.assertIn(
            f'set "PYPATH="{path}""', guard.group(1).splitlines(),
            "call %PYPATH% needs a quoted executable when its path contains spaces",
        )

    def test_launcher_lookup_clears_inherited_selection_before_testing_path(self):
        lookup = self.entry.index("where py >nul 2>&1")
        self.assertEqual(self.entry[:lookup].splitlines()[-1], 'set "PYPATH="')
        launcher = self.entry[lookup:].split("where python ", 1)[0]
        self.assertRegex(
            launcher, r'(?m)^if not errorlevel 1 set "PYPATH=py -3\.12"$',
        )
        self.assertRegex(launcher, r"(?m)^if defined PYPATH goto run$")
        self.assertLess(launcher.index('set "PYPATH=py -3.12"'),
                        launcher.index("if defined PYPATH goto run"))
        self.assertLess(self.entry.index("where py "), self.entry.index("where python "))

    def test_launcher_checks_python312_availability_before_selecting_it(self):
        # Finding py.exe does not mean that it has a Python 3.12 installation.
        launcher = self.entry.split("where py >nul 2>&1", 1)[1].split("where python ", 1)[0]
        probe = re.search(r'^py -3\.12 -c "[^"]+".*$', launcher, re.MULTILINE)
        self.assertIsNotNone(
            probe, "Probe py -3.12 so an unavailable runtime can fall back to PATH Python",
        )
        selection = launcher.index('set "PYPATH=py -3.12"')
        self.assertLess(probe.end(), selection)
        self.assertRegex(launcher[probe.end():selection], r"if not errorlevel 1")

    def test_path_python_requires_discovery_and_supported_version_before_selection(self):
        self.assertRegex(
            self.entry,
            r'(?m)^where python >nul 2>&1\n'
            r'if errorlevel 1 goto no_python\n'
            r'python -c "[^"]+" >nul 2>&1\n'
            r'if errorlevel 1 goto bad_python\n'
            r'set "PYPATH=python"$',
        )

    def test_installer_call_quotes_script_path_and_forwards_all_arguments(self):
        calls = [line for line in self.execution.splitlines() if line.startswith("call ")]
        self.assertTrue(calls, "The execution section must call the installer")
        self.assertEqual(calls[0], r'call %PYPATH% "%~dp0.\install.py" %*')
        self.assertEqual(sum("install.py" in line for line in calls), 1)

    def test_installer_failure_exits_before_offering_to_start(self):
        failure = re.search(
            r'^if errorlevel 1 \(\n(.*?)^\)',
            self.execution, re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(failure, "Installer errors must have a failure branch")
        self.assertEqual(self.execution[:failure.start()].splitlines(),
                         [r'call %PYPATH% "%~dp0.\install.py" %*'])
        self.assertEqual(failure.group(1).splitlines()[-2:], ["pause", "exit /b 1"])
        self.assertLess(failure.end(), self.execution.index("choice /c YN"))

    def test_declining_start_skips_script_and_accepting_uses_script_relative_path(self):
        self.assertRegex(
            self.execution,
            r'(?m)^choice /c YN [^\n]+\nif errorlevel 2 goto end\n'
            r'call "%~dp0start\.bat"$',
        )
        self.assertEqual(section(self.text, "end").splitlines(), ["endlocal", "exit /b 0"])

    def test_interpreter_errors_offer_explicit_override_and_exit_unsuccessfully(self):
        for label in ("no_python", "bad_python"):
            with self.subTest(label=label):
                body = section(self.text, label)
                self.assertRegex(body, r'(?m)^echo\s+python install\.py --python "[^"\n]+\.exe"$')
                self.assertEqual(body.splitlines()[-2:], ["pause", "exit /b 1"])
                self.assertNotRegex(body, r"(?m)^(?:call |goto (?:run|exec))")


class InstallBatVersionProbeTests(unittest.TestCase):
    """Execute the batch file's inline Python check at the support boundary."""

    def setUp(self):
        match = re.search(r'^python -c "([^"]+)"', commands("install.bat"), re.MULTILINE)
        self.assertIsNotNone(match, "PATH Python must have a version probe")
        self.probe = compile(match.group(1), "install.bat version probe", "exec")

    def assert_probe_exit(self, version, expected):
        with patch.object(sys, "version_info", version):
            with self.assertRaises(SystemExit) as raised:
                exec(self.probe, {})
        self.assertEqual(raised.exception.code, expected)

    def test_versions_below_python312_are_rejected(self):
        for version in ((2, 7, 18), (3, 0, 0), (3, 11, 99)):
            with self.subTest(version=version):
                self.assert_probe_exit(version, 1)

    def test_python312_and_newer_versions_are_accepted(self):
        for version in ((3, 12, 0), (3, 12, 9), (3, 13, 0), (4, 0, 0)):
            with self.subTest(version=version):
                self.assert_probe_exit(version, 0)


if __name__ == "__main__":
    unittest.main()
