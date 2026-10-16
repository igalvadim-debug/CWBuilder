"""Unit tests for the Flux 3 prompt upsampler's model directories."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mm_common import Catalog, ModelMissing, SEP


class LlmCatalogTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def model(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def catalog(self):
        return Catalog([self.root], prefer_live=False)

    def test_discovers_models_in_each_new_directory(self):
        directories = ("LLM", "text_enchancer", "diffusion_llms",
                       "large_language_model", "models")
        for index, directory in enumerate(directories):
            self.model(f"{directory}/qwen{index}.safetensors")
        self.assertEqual(
            self.catalog().names("llm"),
            [f"qwen{index}.safetensors" for index in range(len(directories))],
        )

    def test_nested_paths_are_relative_to_the_model_directory(self):
        self.model("LLM/vendor/qwen3.5.gguf")
        cat = self.catalog()
        expected = SEP.join(("vendor", "qwen3.5.gguf"))
        self.assertEqual(cat.names("llm"), [expected])
        self.assertEqual(cat.pick("llm", ["qwen3.5"]), expected)

    def test_supported_model_extensions_are_case_insensitive(self):
        extensions = (".safetensors", ".sft", ".gguf", ".pth", ".pt", ".ckpt", ".bin")
        for extension in extensions:
            self.model("LLM/model" + extension.upper())
        self.model("LLM/README.md")
        self.model("LLM/model.gguf.download")
        self.assertEqual(
            set(self.catalog().names("llm")),
            {"model" + extension.upper() for extension in extensions},
        )

    def test_duplicate_names_across_directories_and_roots_are_deduplicated(self):
        self.model("LLM/Qwen.gguf")
        self.model("text_enchancer/qwen.gguf")
        self.model("other/LLM/QWEN.gguf")
        cat = Catalog([self.root, self.root / "other"], prefer_live=False)
        self.assertEqual(cat.names("llm"), ["Qwen.gguf"])

    def test_unrelated_model_kinds_do_not_leak_into_llm_names(self):
        self.model("text_encoders/qwen3.5.safetensors")
        self.model("loras/qwen3.5.gguf")
        self.assertEqual(self.catalog().names("llm"), [])

    def test_missing_upsampler_is_optional_or_reports_the_llm_kind(self):
        cat = self.catalog()
        self.assertIsNone(cat.pick("llm", ["qwen3.5"], required=False))
        with self.assertRaisesRegex(ModelMissing, r"\[llm\].*qwen3\.5"):
            cat.pick("llm", ["qwen3.5"])


if __name__ == "__main__":
    unittest.main()
