"""Offline regression checks for MOSS template patching and graph links."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mm_moss as M  # noqa: E402


class MossWorkflowTest(unittest.TestCase):
    def assert_consistent_links(self, wf):
        nodes = {node["id"]: node for node in wf["nodes"]}
        links = {link[0]: link for link in wf["links"]}
        self.assertEqual(len(links), len(wf["links"]))
        for lid, src, src_slot, dst, dst_slot, _ in links.values():
            self.assertIn(lid, nodes[src]["outputs"][src_slot]["links"])
            self.assertEqual(nodes[dst]["inputs"][dst_slot]["link"], lid)
        for node in wf["nodes"]:
            for slot, inp in enumerate(node.get("inputs", [])):
                if inp.get("link") is not None:
                    self.assertEqual(links[inp["link"]][3:5], [node["id"], slot])
            for slot, output in enumerate(node.get("outputs", [])):
                for lid in output.get("links") or []:
                    self.assertEqual(links[lid][1:3], [node["id"], slot])

    def build_with_ui(self, p):
        with mock.patch.object(M.B, "ui_to_api", wraps=M.B.ui_to_api) as convert:
            graph, info = M.build(p)
        convert.assert_called_once()
        return convert.call_args.args[0], graph, info

    def test_public_builder_patches_all_modes_and_converts(self):
        for mode in M.MODES:
            with self.subTest(mode=mode):
                p = M.MossParams(mode, "A lighthouse at dusk", seed=42,
                                 images=["input.png"], loras=[("style", 0.75)])
                wf, graph, info = self.build_with_ui(p)
                self.assertTrue(graph)
                self.assertIsInstance(info["notes"], list)
                self.assertEqual(info["warnings"], [])
                self.assertEqual(info["turbo_kind"], M.DEFAULT_TURBO[mode])
                self.assertEqual(info["sampling"]["seed"], "42")
                self.assertIsNone(p.turbo_kind)  # Default resolution preserves the caller.
                if mode in ("moss-inpaint", "moss-detailer"):
                    nid = 28 if mode == "moss-inpaint" else 55
                    self.assertEqual(M._node(wf, nid)["widgets_values"][1],
                                     "<lora:style:0.75>")

    def test_optional_collections_are_independent(self):
        first = M.MossParams("moss-t2i", "first")
        second = M.MossParams("moss-t2i", "second")
        first.images.append("input.png")
        first.loras.append(("style", 1.0))
        self.assertEqual(second.images, [])
        self.assertEqual(M._loras_markup(second), "")
        self.assertEqual(M._loras_markup(first), "<lora:style:1.0>")

    def test_rapid_falls_back_before_sampling_when_template_is_missing(self):
        with tempfile.TemporaryDirectory() as empty_root:
            with mock.patch.object(M.C, "ROOT", Path(empty_root)):
                for explicit_steps in (None, 12):
                    with self.subTest(steps=explicit_steps):
                        p = M.MossParams("moss-4step", "test", turbo_kind="rapid4",
                                         seed=42, steps=explicit_steps, lora_strength=0.6,
                                         sampler="heun", scheduler="normal")
                        wf, graph, info = self.build_with_ui(p)
                        steps = explicit_steps or 8
                        self.assertEqual(info["turbo_kind"], "dmd8")
                        self.assertEqual(info["sampling"]["steps"], steps)
                        self.assertEqual(info["sampling"]["sampler"], "heun")
                        self.assertEqual(info["sampling"]["scheduler"], "normal")
                        self.assertEqual(M._node(wf, 15)["widgets_values"],
                                         ["normal", str(steps), "1.0"])
                        self.assertEqual(M._node(wf, 2)["mode"], 0)
                        self.assertEqual(M._node(wf, 2)["widgets_values"][1], "0.6")
                        self.assertEqual(M._node(wf, 14)["mode"], 0)
                        self.assertEqual(graph["7"]["inputs"]["sampler"], ["14", 0])
                        self.assertEqual(graph["7"]["inputs"]["sigmas"], ["15", 0])
                        self.assertIn("dmd8", info["warnings"][0])
                        self.assert_consistent_links(wf)

    def test_rapid_preserves_other_sampler_inputs_and_uses_destination_order(self):
        for variant in ("linked", "unlinked", "reordered"):
            with self.subTest(variant=variant):
                wf = M.load_template("moss-4step")
                sampler = M._node(wf, 7)
                if variant == "unlinked":
                    M._remove_link(wf, sampler["inputs"][2]["link"])
                    M._remove_link(wf, sampler["inputs"][3]["link"])
                if variant == "reordered":
                    sampler["inputs"][2:4] = reversed(sampler["inputs"][2:4])
                    for link in wf["links"]:
                        if link[3] == 7 and link[4] in (2, 3):
                            link[4] = 5 - link[4]
                info = {"warnings": [], "notes": []}
                self.assertTrue(M._ensure_rapid_adapter(wf, M._node(wf, 13), info))
                adapter = next(n for n in wf["nodes"] if n["type"] == "RapidMOSSAdapter")
                for _ in range(2):
                    self.assert_consistent_links(wf)
                    graph = M.B.ui_to_api(wf)
                    self.assertEqual(graph["7"]["inputs"], {
                        "noise": ["5", 0], "guider": ["4", 0],
                        "sampler": [str(adapter["id"]), 1],
                        "sigmas": [str(adapter["id"]), 2], "latent_image": ["6", 0]})
                    self.assertEqual(graph["4"]["inputs"]["model"], [str(adapter["id"]), 0])
                    self.assertEqual(graph[str(adapter["id"])]["inputs"]["model"], ["13", 0])
                    self.assertTrue(M._ensure_rapid_adapter(wf, M._node(wf, 13), info))
                self.assertEqual(len(sampler["inputs"]), 5)
                self.assertEqual(sum(n["type"] == "RapidMOSSAdapter" for n in wf["nodes"]), 1)

    def test_failed_rapid_rewire_returns_false_without_partial_mutation(self):
        wf = M.load_template("moss-4step")
        wf["nodes"] = [node for node in wf["nodes"] if node["type"] != "BasicGuider"]
        before = copy.deepcopy(wf)
        info = {"warnings": [], "notes": []}
        self.assertFalse(M._ensure_rapid_adapter(wf, M._node(wf, 13), info))
        self.assertEqual(wf, before)
        self.assertTrue(info["warnings"])

    def test_effective_steps_match_widgets_for_each_kind(self):
        for kind, default_steps in (("rapid4", 4), ("dmd8", 8), ("off", 30)):
            for explicit_steps in (None, 6):
                with self.subTest(kind=kind, steps=explicit_steps):
                    wf, _, info = self.build_with_ui(M.MossParams(
                        "moss-4step", "test", turbo_kind=kind, seed=42, steps=explicit_steps))
                    expected = explicit_steps or default_steps
                    self.assertEqual(info["sampling"]["steps"], expected)
                    self.assertEqual(M._node(wf, 15)["widgets_values"][1], str(expected))
                    if kind == "rapid4":
                        adapter = next(n for n in wf["nodes"] if n["type"] == "RapidMOSSAdapter")
                        self.assertEqual(adapter["widgets_values"][1], str(expected))

    def test_enhancer_default_custom_prompt_and_optional_image(self):
        for system in ("", "Keep the prompt concise."):
            for images in ([], ["input.png"]):
                with self.subTest(system=system, images=images):
                    original = M.load_template("moss-enhance")
                    wf, graph, info = self.build_with_ui(M.MossParams(
                        "moss-enhance", "A lighthouse", system_prompt=system,
                        images=images, llm="local-llm.safetensors", max_length=512, seed=42))
                    self.assertEqual(M._node(wf, 9)["widgets_values"][0],
                                     system or M._default_system_prompt())
                    self.assertTrue(M._node(wf, 9)["widgets_values"][0])
                    self.assertEqual(M._node(wf, 5)["widgets_values"][0], "local-llm.safetensors")
                    self.assertEqual(M._node(wf, 3)["widgets_values"][1], "512")
                    self.assertEqual(M._node(wf, 3)["widgets_values"][6],
                                     M._node(original, 3)["widgets_values"][6])
                    self.assertEqual("image" in graph["3"]["inputs"], bool(images))
                    self.assertEqual(info["sampling"]["max_length"], 512)
                    self.assert_consistent_links(wf)

    def test_drop_link_clears_all_consumers_but_preserves_other_outputs(self):
        wf = {"nodes": [
            {"id": 1, "outputs": [{"name": "IMAGE", "links": [10, 11]},
                                    {"name": "MASK", "links": [12]}]},
            {"id": 2, "inputs": [{"name": "image", "link": 10}]},
            {"id": 3, "inputs": [{"name": "image", "link": 11},
                                    {"name": "mask", "link": 12}]}],
            "links": [[10, 1, 0, 2, 0, "IMAGE"], [11, 1, 0, 3, 0, "IMAGE"],
                      [12, 1, 1, 3, 1, "MASK"]]}
        M._drop_link(wf, wf["nodes"][0], "IMAGE")
        self.assertEqual(wf["links"], [[12, 1, 1, 3, 1, "MASK"]])
        self.assertIsNone(wf["nodes"][1]["inputs"][0]["link"])
        self.assertIsNone(wf["nodes"][2]["inputs"][0]["link"])
        self.assert_consistent_links(wf)
        M._drop_link(wf, wf["nodes"][0], "IMAGE")
        self.assert_consistent_links(wf)

    def test_unknown_mode_raises_moss_error(self):
        with self.assertRaises(M.MossError):
            M.build(M.MossParams("unknown", "test"))


if __name__ == "__main__":
    unittest.main()
