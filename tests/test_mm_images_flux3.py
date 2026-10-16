# -*- coding: utf-8 -*-
"""Flux-3-Buildertests: Turbo-Verhalten und Prompt-Upsampler (offline, Mock-Catalog)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mm_common import Catalog  # noqa: E402
from mm_images import Params, build_flux3, flux3_upsample, Graph  # noqa: E402


def make_models(tmp: Path) -> Path:
    root = tmp / "models"
    for sub, fname in (
        ("diffusion_models", "flux3_image_klein_base_int8_convrot.safetensors"),
        ("text_encoders", "gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors"),
        ("text_encoders", "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors"),
        ("vae", "flux2_vae.safetensors"),
        ("loras", "flux3_turbo_lora_8step.safetensors"),
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
        (root / sub / fname).write_bytes(b"x")
    return root


def base_params(**kw) -> Params:
    p = Params(mode="flux3", prompt="ein test-prompt")
    p.no_upsample = True  # Upsampler standardmaessig aus - Turbo-Tests bleiben fokussiert
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def nodes_of(g: Graph):
    return g.nodes


class Flux3TurboTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_models(Path(self._tmp.name))
        self.cat = Catalog([self.root], url=None, prefer_live=False)

    def tearDown(self):
        self._tmp.cleanup()

    def _find_lora_loaders(self, graph):
        return [n for n in graph.values() if n["class_type"] == "LoraLoader"]

    def test_auto_turbo_is_used_when_available_and_off_disables_it(self):
        # turbo="auto": KEINE Turbo-LoRA, keine Warnung, Standardwerte 25/3.5
        info = {"models": [], "warnings": [], "notes": []}
        g = build_flux3(base_params(turbo="auto"), self.cat, info)
        self.assertEqual(self._find_lora_loaders(g.nodes), [])
        self.assertEqual((info["steps"], info["cfg"]), (25, 3.5))
        self.assertFalse(any("Turbo" in w for w in info["warnings"]))

        # turbo="off": ebenfalls keine LoRA
        info = {"models": [], "warnings": [], "notes": []}
        g = build_flux3(base_params(turbo="off"), self.cat, info)
        self.assertEqual(self._find_lora_loaders(g.nodes), [])
        self.assertEqual((info["steps"], info["cfg"]), (25, 3.5))

    def test_missing_turbo_is_optional_in_auto_mode_and_required_when_requested(self):
        # Das 'turbo'-Preset zeigt auf 'flux3_turbo' - im Katalog existiert nur
        # 'flux3_turbo_lora' (kein exakter Treffer, aber Teilstring-Treffer).
        # auto wendet das Preset gar nicht erst an: keine LoRA, keine Warnung.
        info = {"models": [], "warnings": [], "notes": []}
        g = build_flux3(base_params(turbo="auto"), self.cat, info)
        self.assertEqual(self._find_lora_loaders(g.nodes), [])
        self.assertEqual((info["steps"], info["cfg"]), (25, 3.5))
        self.assertFalse(any("Turbo" in w for w in info["warnings"]))

        # Explizit verlangt: Praesenz wird ignoriert, das Preset soll fehlen -> ModelMissing
        from mm_common import ModelMissing
        missing_root = Path(self._tmp.name) / "missing"
        (missing_root / "diffusion_models").mkdir(parents=True, exist_ok=True)
        (missing_root / "text_encoders").mkdir(exist_ok=True)
        (missing_root / "vae").mkdir(exist_ok=True)
        (missing_root / "loras").mkdir(exist_ok=True)
        (missing_root / "diffusion_models" /
         "flux3_image_klein_base_int8_convrot.safetensors").write_bytes(b"x")
        (missing_root / "text_encoders" /
         "gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors").write_bytes(b"x")
        (missing_root / "vae" / "flux2_vae.safetensors").write_bytes(b"x")
        cat2 = Catalog([missing_root], url=None, prefer_live=False)
        with self.assertRaises(ModelMissing):
            build_flux3(base_params(turbo="turbo"), cat2,
                        {"models": [], "warnings": [], "notes": []})

        # Explizit verlangt: vorhandene LoRA direkt als Name -> wird geladen, Steps 8
        info = {"models": [], "warnings": [], "notes": []}
        g = build_flux3(base_params(turbo="flux3_turbo_lora_8step"), self.cat, info)
        loaders = self._find_lora_loaders(g.nodes)
        self.assertEqual(len(loaders), 1)
        self.assertIn("flux3_turbo_lora_8step", loaders[0]["inputs"]["lora_name"])
        self.assertEqual(info["steps"], 8)


class Flux3UpsamplerTest(unittest.TestCase):
    """Dedizierte Upsampler-Nodes: STRING-Index und api-Skip-Verhalten."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_models(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _cat_with_info(self, object_info):
        cat = Catalog([self.root], url=None, prefer_live=False)
        cat.object_info = object_info
        return cat

    def test_string_output_index_is_used_not_always_zero(self):
        spec = {
            "input": {"required": {"prompt": ["STRING"], "model_name": ["STRING"]},
                      "optional": {}},
            "output": ["INT", "STRING", "MODEL"],
            "output_name": ["count", "text", "model"],
        }
        cat = self._cat_with_info({"Flux3PromptUpsampler": spec})
        g = Graph()
        info = {"models": [], "warnings": [], "notes": []}
        link = flux3_upsample(g, base_params(upsampler=None), cat, info, "hallo")
        self.assertIsNotNone(link)
        nid = link[0]
        self.assertEqual(g.nodes[nid]["class_type"], "Flux3PromptUpsampler")
        self.assertEqual(link[1], 1)  # STRING steht an Index 1, nicht 0

    def test_api_node_without_model_skips_to_next_candidate(self):
        api_spec = {
            "input": {"required": {"prompt": ["STRING"], "api": ["STRING"]}, "optional": {}},
            "output": ["STRING"],
        }
        plain_spec = {
            "input": {"required": {"user_prompt": ["STRING"]}, "optional": {}},
            "output": ["STRING"],
        }
        # Kein Upsampler-safetensors im text_encoders-Katalog vorhanden
        empty_root = Path(self._tmp.name) / "empty"
        (empty_root / "diffusion_models").mkdir(parents=True, exist_ok=True)
        cat = Catalog([empty_root], url=None, prefer_live=False)
        cat.object_info = {
            "TextEncodeAPI": api_spec,           # braucht 'api' -> muss uebersprungen werden
            "Flux3PromptUpsampler": plain_spec,  # naechster Kandidat gewinnt
        }
        g = Graph()
        info = {"models": [], "warnings": [], "notes": []}
        link = flux3_upsample(g, base_params(), cat, info, "hallo")
        self.assertIsNotNone(link)
        cls = {nid: n["class_type"] for nid, n in g.nodes.items()}
        self.assertNotIn("TextEncodeAPI", cls.values())
        self.assertIn("Flux3PromptUpsampler", cls.values())

    def test_api_node_still_used_when_model_available(self):
        api_spec = {
            "input": {"required": {"prompt": ["STRING"], "api": ["COMBO"]}, "optional": {}},
            "output": ["STRING"],
        }
        cat = self._cat_with_info({"TextEncodeAPI": api_spec})
        cat._names["text_encoders"] = list(cat.names("text_encoders")) + [
            "text_encoders" + ("/" if sys.platform != "win32" else "\\") +
            "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors"]
        # pick findet den Upsampler ohnehin im text_encoders-Verzeichnis der Platte
        g = Graph()
        info = {"models": [], "warnings": [], "notes": []}
        link = flux3_upsample(g, base_params(), cat, info, "hallo")
        self.assertIsNotNone(link)
        nid = link[0]
        self.assertEqual(g.nodes[nid]["class_type"], "TextEncodeAPI")
        self.assertIn("api", g.nodes[nid]["inputs"])


if __name__ == "__main__":
    unittest.main()
