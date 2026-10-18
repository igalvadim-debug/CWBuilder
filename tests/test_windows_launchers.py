"""Portable batch artifact contracts; these checks do not execute cmd.exe."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def commands(filename):
    """Ignore prose so comments cannot satisfy a launcher contract."""
    return "\n".join(line.strip() for line in (ROOT / filename).read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.lstrip().lower().startswith("rem "))


def section(text, label):
    return re.search(rf"^:{label}\n(.*?)(?=^:\w|\Z)", text, re.MULTILINE | re.DOTALL).group(1)


class WindowsLauncherContractTests(unittest.TestCase):
    def test_fresh_install_reaches_installer_without_requiring_a_venv(self):
        run = section(commands("install.bat"), "run")
        invocation = '"%PYPATH%" %PYARGS% install.py %*'
        self.assertIn(invocation, run)
        # Regression: the deleted guards rejected every first installation.
        self.assertNotIn("if not exist", run[:run.index(invocation)].lower())
        self.assertRegex(run, re.escape(invocation) + r"\nif errorlevel 1 \(")
        self.assertIn("exit /b 1", run)

    def test_stop_dispatch_precedes_installation_checks(self):
        launcher = commands("start.bat")
        self.assertLess(launcher.index('if /i "%~1"=="stop" goto :stop'),
                        launcher.index('if not exist "venv\\Scripts\\python.exe" goto install'))

    def test_bootstrap_candidates_are_ordered_and_forward_all_arguments(self):
        bootstrap = section(commands("start.bat"), "install")
        candidates = (
            '"%MM_PYTHON%" install.py %*',
            '"venv\\Scripts\\python.exe" install.py %*',
            '"%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe" install.py %*',
            'py -3.12 install.py %*',
            'py -3 install.py %*',
        )
        positions = [bootstrap.index(candidate) for candidate in candidates]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(bootstrap.index('set "INSTALL_OK="'), positions[0])
        for candidate in candidates[:-1]:
            with self.subTest(candidate=candidate):
                self.assertIn(candidate + '\nset "INSTALL_OK=1"\ngoto install_after', bootstrap)
        self.assertIn('if defined MM_PYTHON if exist "%MM_PYTHON%" (', bootstrap)
        self.assertIn('if errorlevel 1 goto install_no_py', bootstrap)
        self.assertIn('sys.version_info >= (3, 12)', bootstrap)
        self.assertIn('if errorlevel 1 goto install_bad_py', bootstrap)

    def test_bootstrap_checks_both_installation_artifacts_before_start(self):
        after = section(commands("start.bat"), "install_after")
        for artifact in ("venv\\Scripts\\python.exe", "venv\\.install-complete"):
            with self.subTest(artifact=artifact):
                guard = f'if not exist "{artifact}" (\n'
                self.assertIn(guard, after)
                # A closing parenthesis in an escaped echo is not a block terminator.
                block = after.split(guard, 1)[1].split("\n)", 1)[0]
                self.assertIn("\nexit /b 1", block)
        self.assertTrue(after.rstrip().endswith("goto start"))

    def test_stack_start_precedes_web_wrapper_and_opens_the_local_ui(self):
        start = section(commands("start.bat"), "start")
        self.assertIn("set OPENCREATOR_LOCAL=1", start)
        self.assertLess(start.index('start "open-creator-local-stack"'),
                        start.index("node scripts\\web-dev-wrapper.mjs pnpm web:dev"))
        self.assertIn('start "" http://127.0.0.1:19861/', start)

    def test_stop_uses_recorded_process_helpers_instead_of_killing_by_image_name(self):
        stop = section(commands("start.bat"), "stop")
        self.assertIn("local-stack\\start.py --stop", stop)
        self.assertIn('if exist ".webui.pid" (\nnode scripts\\web-dev-wrapper.mjs --stop ".webui.pid"', stop)
        self.assertNotRegex(stop.lower(), r"taskkill\b|stop-process\b")


if __name__ == "__main__":
    unittest.main()
