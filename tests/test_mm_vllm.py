"""VL loader selection uses socket metadata and loader-specific model locations."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mm_common import Catalog  # noqa: E402
from mm_ltx import Graph  # noqa: E402
from mm_vllm import _chat_spec, add_vl_branch, find_vl_model  # noqa: E402


def node(inputs, outputs, optional=None):
    return {"input": {"required": inputs, "optional": optional or {}}, "output": outputs}


def catalog(metadata, roots=()):
    cat = Catalog(roots, prefer_live=False)
    cat.object_info = metadata
    return cat


def chat(model_type="LLM", outputs=None):
    return node({"image": ["IMAGE"], "prompt": ["STRING"], "llm": [model_type]},
                outputs or ["INT", "STRING"])


def branch(cat, name, load_unet=None):
    graph, info = Graph(), {}
    link = add_vl_branch(graph, cat, image_src=["image", 0], prompt_text="continue",
                         vl_model=name, max_tokens=128, seed=42, info=info,
                         load_unet=load_unet or Mock(side_effect=AssertionError("unexpected UNET loader")))
    return graph, info, link


class VlLoaderTest(unittest.TestCase):
    def test_loader_type_and_nonzero_output_slots_override_extension_order(self):
        for extension in ("gguf", "safetensors"):
            with self.subTest(extension=extension):
                name = f"qwen2.5-vl.{extension}"
                cat = catalog({
                    "LLMVisionSampler": chat(),
                    "UnetLoaderGGUF": node({"unet_name": [[name]]}, ["MODEL"]),
                    "GGUFLoader": node({"gguf_name": [[name]]}, ["WRONG_TYPE"]),
                    "CheckpointLoaderSimple": node({"ckpt_name": [[name]]}, ["MODEL", "CLIP", "VAE"]),
                    "LLMLoader": node({}, ["AUX", "LLM"], {"model_name": [[name]]}),
                })
                self.assertEqual(_chat_spec(cat)[4], "LLM")
                self.assertEqual(find_vl_model(cat, None), name)
                graph, info, link = branch(cat, name)
                self.assertEqual(link[1], 1)
                loader = graph.nodes["1"]
                self.assertEqual(loader, {"class_type": "LLMLoader", "inputs": {"model_name": name}})
                self.assertEqual(graph.nodes[link[0]]["inputs"]["llm"], ["1", 1])
                self.assertNotIn("warnings", info)

    def test_discovery_uses_compatible_loader_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("LLM", "text_encoders", "checkpoints"):
                (root / folder).mkdir()
                (root / folder / f"qwen2.5-vl-{folder}.safetensors").touch()
            cat = catalog({
                "LLMVisionSampler": chat("MODEL"),
                "CheckpointLoaderSimple": node({"ckpt_name": ["STRING"]}, ["MODEL", "CLIP", "VAE"]),
            }, [root])
            name = "qwen2.5-vl-checkpoints.safetensors"
            self.assertEqual(find_vl_model(cat, None), name)
            self.assertIsNone(find_vl_model(cat, "qwen2.5-vl-LLM"))
            graph, _, link = branch(cat, name)
            self.assertIsNotNone(link)
            self.assertEqual(graph.nodes["1"]["class_type"], "CheckpointLoaderSimple")

    def test_incompatible_or_unavailable_models_warn_without_graph_changes(self):
        name = "qwen2.5-vl.safetensors"
        for metadata in (
            None,
            {"LLMVisionSampler": chat(),
             "CheckpointLoaderSimple": node({"ckpt_name": [[name]]}, ["MODEL", "CLIP", "VAE"])},
            {"LLMVisionSampler": chat(),
             "LLMLoader": node({"model_name": [[]]}, ["LLM"])},
            {"LLMVisionSampler": chat(),
             "LLMLoader": node({}, ["LLM"])},
        ):
            with self.subTest(metadata=metadata):
                graph, info, link = branch(catalog(metadata), name)
                self.assertIsNone(link)
                self.assertEqual(graph.nodes, {})
                self.assertEqual(len(info["warnings"]), 1)

    def test_loader_failure_is_not_retried(self):
        name = "qwen2.5-vl.gguf"
        cat = catalog({"LLMVisionSampler": chat("MODEL"),
                       "UnetLoaderGGUF": node({"unet_name": [[name]]}, ["MODEL"])})
        load = Mock(side_effect=RuntimeError("loader failed"))
        with self.assertRaisesRegex(RuntimeError, "loader failed"):
            branch(cat, name, load)
        load.assert_called_once()

    def test_combo_metadata_format_is_supported(self):
        name = "qwen2.5-vl.gguf"
        cat = catalog({"LLMVisionSampler": chat(),
                       "LLMLoader": node({"model_name": ["COMBO", {"options": [name]}]}, ["LLM"])})
        _, _, link = branch(cat, name)
        self.assertEqual(link[1], 1)


if __name__ == "__main__":
    unittest.main()
