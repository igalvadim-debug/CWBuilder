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
        expected = sorted((f"up_{d}.safetensors".lower() for d in directories))
        found = sorted(n.lower() for n in self.cat.names("llm"))
        self.assertEqual(found, expected)

    def test_discovery_sorts_without_case_and_preserves_filename_spelling(self):
        filenames = ["Z_Upsampler.SAFETENSORS", "a_upsampler.gguf"]
        for filename in filenames:
            (self.root / "LLM" / filename).write_bytes(b"x")
        expected = [f"up_{sub}.safetensors" for sub in LLM_DIRS] + filenames

        self.assertEqual(self.cat.names("llm"), sorted(expected, key=str.lower))

    def test_case_insensitive_duplicates_keep_the_first_root_and_directory(self):
        (self.root / "LLM" / "Shared.GGUF").write_bytes(b"x")
        (self.root / "text_enchancer" / "shared.gguf").write_bytes(b"x")
        second_root = Path(self._tmp.name) / "second_root"
        (second_root / "LLM").mkdir(parents=True)
        (second_root / "LLM" / "SHARED.gguf").write_bytes(b"x")
        cat = Catalog([self.root, second_root], url=None, prefer_live=False)
        expected = [f"up_{sub}.safetensors" for sub in LLM_DIRS] + ["Shared.GGUF"]

        self.assertEqual(cat.names("llm"), sorted(expected, key=str.lower))
        self.assertEqual(cat.pick("llm", ["SHARED"], ext=".gguf"), "Shared.GGUF")

    def test_nested_models_are_relative_and_non_model_files_are_ignored(self):
        expected = [f"up_{sub}.safetensors" for sub in LLM_DIRS]
        for sub in LLM_DIRS:
            nested = self.root / sub / "vendor"
            nested.mkdir()
            # Gleicher Dateiname in verschiedenen Unterordnern bleibt eindeutig.
            (nested / "up_LLM.safetensors").write_bytes(b"x")
            for filename in ("README.txt", "config.json", "weights.safetensors.bak", "weights"):
                (nested / filename).write_bytes(b"x")
        expected.append(os.path.join("vendor", "up_LLM.safetensors"))

        self.assertEqual(self.cat.names("llm"), sorted(expected, key=str.lower))

    def test_files_in_other_model_kinds_are_not_discovered_as_llms(self):
        for sub in ("text_encoders", "loras", "checkpoints", "diffusion_models"):
            directory = self.root / sub
            directory.mkdir()
            (directory / f"excluded_{sub}.safetensors").write_bytes(b"x")
        (self.root / "excluded_root.gguf").write_bytes(b"x")
        expected = [f"up_{sub}.safetensors" for sub in LLM_DIRS]

        self.assertEqual(self.cat.names("llm"), sorted(expected, key=str.lower))
        self.assertIsNone(self.cat.pick("llm", ["excluded"], required=False))

    def test_safetensors_under_models_is_not_discovered(self):
        names = [n.lower() for n in self.cat.names("llm")]
        self.assertFalse(any("stray_in_models" in n for n in names))
        self.assertIsNone(self.cat.pick("llm", ["stray_in_models"], required=False))


if __name__ == "__main__":
    unittest.main()
