# -*- coding: utf-8 -*-
"""Catalog-Entdeckung fuer den 'llm'-Typ (Flux 3 Prompt-Upsampler)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mm_common import KIND_DIRS, Catalog  # noqa: E402

LLM_DIRS = ("LLM", "text_enchancer", "diffusion_llms", "large_language_model")


def make_root(tmp: Path) -> Path:
    for sub in LLM_DIRS:
        (tmp / sub).mkdir(parents=True, exist_ok=True)
        (tmp / sub / f"up_{sub}.safetensors").write_bytes(b"x")
    # 'models' ist KEIN unterstuetztes LLM-Verzeichnis - Dateien dort duerfen
    # nicht ueber den llm-Typ gefunden werden.
    (tmp / "models").mkdir(exist_ok=True)
    (tmp / "models" / "stray_in_models.safetensors").write_bytes(b"x")
    return tmp


class LlmDirsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(Path(self._tmp.name))
        self.cat = Catalog([self.root], url=None, prefer_live=False)

    def tearDown(self):
        self._tmp.cleanup()

    def test_supported_directories_are_exactly_four(self):
        self.assertEqual(KIND_DIRS["llm"], LLM_DIRS)

    def test_discovery_returns_only_the_four_supported_dirs(self):
        directories = KIND_DIRS["llm"]
        # Catalog liefert Namen relativ zum jeweiligen Unterordner (wie ComfyUI)
        expected = sorted(f"up_{d}.safetensors" for d in directories)
        found = [n.lower() for n in self.cat.names("llm")]
        self.assertEqual(sorted(found), [n.lower() for n in expected])

    def test_safetensors_under_models_is_not_discovered(self):
        names = [n.lower() for n in self.cat.names("llm")]
        self.assertFalse(any("stray_in_models" in n for n in names))
        self.assertIsNone(self.cat.pick("llm", ["stray_in_models"], required=False))


if __name__ == "__main__":
    unittest.main()
