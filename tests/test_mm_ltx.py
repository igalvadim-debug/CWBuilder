"""Offline graph checks for LTX conditioning, refinement and scene handoff."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mm_common import Catalog  # noqa: E402
from mm_ltx import build_workflow  # noqa: E402
from mm_scenes import ltx_frames, scene_plan  # noqa: E402


class LtxWorkflowTest(unittest.TestCase):
    def test_scene_links_and_refinement_inputs(self):
        for mode in ("ltx23", "ltx25"):
            for refine in (None, "detailer.safetensors"):
                with self.subTest(mode=mode, refine=refine):
                    plan = scene_plan("First\n\nSecond", [1, 2])
                    graph = build_workflow(
                        mode, plan,
                        {"unet_kind": "unet", "unet": "ltx.safetensors",
                         "text_encoder": "gemma.safetensors", "video_vae": "vae.safetensors"},
                        cat=Catalog([], prefer_live=False), width=512, height=512,
                        fps=8, seed=42, steps=4, cfg=2, guidance=1,
                        refine_lora=refine, turbo=None, user_loras=[], audio=False,
                        vl_model=None, vl_max_tokens=128, negative="bad",
                        output_name="test", info={"refine": 0.42})
                    by_type = lambda cls: [(nid, n["inputs"]) for nid, n in graph.items()
                                           if n["class_type"] == cls]
                    conditions = by_type("LTXVConditioning")
                    guide_id, guide = by_type("LTXVAddGuideImage")[0]
                    self.assertEqual(guide["positive"], [conditions[1][0], 0])
                    self.assertEqual(guide["negative"], [conditions[1][0], 1])
                    for index, (_, guider) in enumerate(by_type("CFGGuider")):
                        scene = index // (2 if refine else 1)
                        source = conditions[0][0] if scene == 0 else guide_id
                        self.assertEqual(guider["positive"], [source, 0])
                        self.assertEqual(guider["negative"], [source, 1])
                    samplers = by_type("SamplerCustomAdvanced")
                    for _, inputs in samplers:
                        self.assertNotIn("denoise", inputs)
                    schedulers = by_type("BasicScheduler")
                    self.assertEqual(len(schedulers), 2 if refine else 0)
                    for scene, (nid, inputs) in enumerate(schedulers):
                        self.assertEqual(inputs["denoise"], 0.42)
                        self.assertEqual(samplers[2 * scene + 1][1]["sigmas"], [nid, 0])
                        self.assertEqual(samplers[2 * scene + 1][1]["latent_image"],
                                         [samplers[2 * scene][0], 1])
                    last_frames = by_type("ImageFromBatch")
                    for (_, inputs), scene in zip(last_frames, plan):
                        self.assertEqual(set(inputs), {"image", "batch_index", "length"})
                        self.assertEqual(inputs["batch_index"], ltx_frames(scene["duration"], 8) - 1)
                        self.assertEqual(inputs["length"], 1)
                        self.assertEqual(graph[inputs["image"][0]]["class_type"], "VAEDecode")
                    self.assertEqual(guide["pixel_space"], [last_frames[0][0], 0])


if __name__ == "__main__":
    unittest.main()
