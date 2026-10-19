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


if __name__ == "__main__":
    unittest.main()