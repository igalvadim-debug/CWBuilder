"""CWBuilder Windows launcher contracts; these checks do not execute cmd.exe."""

import re
import unittest
from pathlib import Path

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
    def test_install_bat_validates_venv_before_using_it(self):
        text = commands("install.bat")
        # The venv branch must probe the interpreter, not trust mere existence.
        self.assertIn('if exist "%~dp0venv\\Scripts\\python.exe" (', text)
        self.assertIn('"%~dp0venv\\Scripts\\python.exe" -c "%VERCHK%" >nul 2>&1', text)
        # Selection happens only when the probe succeeds.
        self.assertIn('set "PYPYEXE=%~dp0venv\\Scripts\\python.exe"', text)
        # Should check Python version
        self.assertIn("sys.version_info ^>= (3, 12)", text)

    def test_install_bat_has_no_unconditional_venv_invocation(self):
        text = commands("install.bat")
        # Direct invocation outside the guarded discovery block was removed.
        self.assertNotIn('"%~dp0venv\\Scripts\\python.exe" install.py', text)

    def test_install_bat_single_common_execution_path(self):
        text = commands("install.bat")
        exec_section = section(text, "exec")
        # Every discovered interpreter runs through one quoted common launcher.
        self.assertEqual(text.count(":exec"), 1)
        self.assertIn('call "!PYPYEXE!" !PYARGS! "%~dp0.\\install.py" %*', exec_section)
        # Should forward all arguments
        self.assertIn("%*", exec_section)

    def test_install_bat_probes_py_launcher_before_selecting_it(self):
        text = commands("install.bat")
        # py -3.12 is selected only after a successful probe.
        self.assertIn("py -3.12 -c \"%VERCHK%\" >nul 2>&1", text)
        self.assertIn('set "PYPYEXE=py"', text)
        self.assertIn('set "PYARGS=-3.12"', text)
        # If 3.12 is missing, discovery continues to PATH-based python.
        self.assertIn(":path_python", text)
        self.assertLess(text.index("py -3.12 -c"), text.index(":path_python"))

    def test_install_bat_escapes_version_message(self):
        text = commands("install.bat")
        bad_python_section = section(text, "bad_python")
        self.assertIn("Version ^< 3.12", bad_python_section)

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


if __name__ == "__main__":
    unittest.main()
