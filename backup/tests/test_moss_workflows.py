"""Offline graph contracts for the MOSS workflow artifacts changed in PR #12."""

import json
import unittest
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "_dev" / "MOSS-upstream"
WORKFLOWS = (
    "MOSS Image Inpaint.json",
    "MOSS Image T2I.json",
    "MOSS Image detailer from 1 to 4 faces and seedvr2 upscale.json",
    "MOSS Image prompt enchancer.json",
    "moss4StepWorkflow_v10.json",
)


def load_workflow(name):
    return json.loads((UPSTREAM / name).read_text(encoding="utf-8"))


def normalized_type(value):
    """LoraManager exports the built-in string type using either spelling."""
    return "STRING" if value == "string" else value


class MossWorkflowTests(unittest.TestCase):
    def test_workflows_have_unique_ids_and_consistent_link_endpoints(self):
        for name in WORKFLOWS:
            with self.subTest(workflow=name):
                workflow = load_workflow(name)
                nodes = {node["id"]: node for node in workflow["nodes"]}
                links = {link[0]: link for link in workflow["links"]}
                self.assertTrue(nodes)
                self.assertTrue(links)
                self.assertEqual(len(nodes), len(workflow["nodes"]))
                self.assertEqual(len(links), len(workflow["links"]))
                self.assertGreaterEqual(workflow["last_node_id"], max(nodes))
                self.assertGreaterEqual(workflow["last_link_id"], max(links))
                for link in links.values():
                    with self.subTest(link=link):
                        self.assertEqual(len(link), 6)
                        link_id, source, output_slot, target, input_slot, link_type = link
                        self.assertIn(source, nodes)
                        self.assertIn(target, nodes)
                        self.assertGreaterEqual(output_slot, 0)
                        self.assertGreaterEqual(input_slot, 0)
                        self.assertLess(output_slot, len(nodes[source]["outputs"]))
                        self.assertLess(input_slot, len(nodes[target]["inputs"]))
                        output = nodes[source]["outputs"][output_slot]
                        target_input = nodes[target]["inputs"][input_slot]
                        self.assertIn(link_id, output["links"])
                        self.assertEqual(target_input["link"], link_id)
                        # LoraManager exports the built-in string type in both cases;
                        # its prompt input also accepts a comma-separated union.
                        self.assertEqual(normalized_type(output["type"]), normalized_type(link_type))
                        accepted = {normalized_type(value.strip())
                                    for value in target_input["type"].split(",")}
                        self.assertTrue("*" in accepted or normalized_type(link_type) in accepted)

    def test_socket_references_cannot_point_to_missing_or_unrelated_links(self):
        for name in WORKFLOWS:
            with self.subTest(workflow=name):
                workflow = load_workflow(name)
                links = {link[0]: link for link in workflow["links"]}
                for node in workflow["nodes"]:
                    for slot, socket in enumerate(node.get("inputs", [])):
                        link_id = socket.get("link")
                        if link_id is not None:
                            self.assertIn(link_id, links)
                            self.assertEqual(links[link_id][3:5], [node["id"], slot])
                    for slot, socket in enumerate(node.get("outputs", [])):
                        for link_id in socket.get("links") or []:
                            self.assertIn(link_id, links)
                            self.assertEqual(links[link_id][1:3], [node["id"], slot])

    def one_node(self, workflow, node_type):
        matches = [node for node in workflow["nodes"] if node["type"] == node_type]
        self.assertEqual(len(matches), 1, node_type)
        return matches[0]

    def assert_connection(self, workflow, source_type, source_slot, target_type, input_name):
        source = self.one_node(workflow, source_type)
        target = self.one_node(workflow, target_type)
        slot = next(i for i, socket in enumerate(target["inputs"]) if socket["name"] == input_name)
        self.assertTrue(any(link[1:5] == [source["id"], source_slot, target["id"], slot]
                            for link in workflow["links"]),
                        f"{source_type}[{source_slot}] must feed {target_type}.{input_name}")

    def test_rapid_workflow_loads_matching_models_and_uses_four_steps(self):
        workflow = load_workflow("moss4StepWorkflow_v10.json")
        expected_models = {
            "MOSSImageUNETLoader": "moss-image-sft-dit-int8-convrot.safetensors",
            "MOSSImageCLIPLoader": "moss-image-sft-qwen35-int8-convrot.safetensors",
            "VAELoader": "moss-image-sft-vae.safetensors",
        }
        for node_type, filename in expected_models.items():
            with self.subTest(loader=node_type):
                self.assertEqual(self.one_node(workflow, node_type)["widgets_values"][0], filename)
        adapter = self.one_node(workflow, "RapidMOSSAdapter")
        self.assertEqual(adapter["widgets_values"][:2], ["rapid-moss-4step", 4])
        self.assertTrue(all(node["mode"] == 0 for node in workflow["nodes"]))

    def test_rapid_adapter_drives_sampler_and_sigmas_without_cfg(self):
        workflow = load_workflow("moss4StepWorkflow_v10.json")
        for source, slot, target, input_name in (
            ("MOSSImageUNETLoader", 0, "RapidMOSSAdapter", "model"),
            ("MOSSImageCLIPLoader", 0, "CLIPTextEncode", "clip"),
            ("RapidMOSSAdapter", 0, "BasicGuider", "model"),
            ("CLIPTextEncode", 0, "BasicGuider", "conditioning"),
            ("RapidMOSSAdapter", 1, "SamplerCustomAdvanced", "sampler"),
            ("RapidMOSSAdapter", 2, "SamplerCustomAdvanced", "sigmas"),
            ("BasicGuider", 0, "SamplerCustomAdvanced", "guider"),
            ("RandomNoise", 0, "SamplerCustomAdvanced", "noise"),
            ("EmptyFlux2LatentImage", 0, "SamplerCustomAdvanced", "latent_image"),
            ("SamplerCustomAdvanced", 0, "VAEDecode", "samples"),
            ("VAELoader", 0, "VAEDecode", "vae"),
            ("VAEDecode", 0, "SaveImage", "images"),
        ):
            with self.subTest(source=source, target=target, input=input_name):
                self.assert_connection(workflow, source, slot, target, input_name)
        self.assertNotIn("CFGGuider", {node["type"] for node in workflow["nodes"]})

    def test_inpainting_preserves_image_mask_and_encoded_latent(self):
        workflow = load_workflow("MOSS Image Inpaint.json")
        self.assert_connection(workflow, "LoadImage", 0, "VAEEncodeForInpaint", "pixels")
        self.assert_connection(workflow, "LoadImage", 1, "VAEEncodeForInpaint", "mask")
        self.assert_connection(workflow, "VAEEncodeForInpaint", 0, "LanPaint_KSampler", "latent_image")
        self.assert_connection(workflow, "LanPaint_KSampler", 0, "VAEDecode", "samples")
        self.assert_connection(workflow, "VAEDecode", 0, "Image Save", "images")

    def test_prompt_enhancer_displays_generated_text_instead_of_thinking(self):
        workflow = load_workflow("MOSS Image prompt enchancer.json")
        self.assert_connection(workflow, "CLIPLoader", 0, "TextGenerate", "clip")
        self.assert_connection(workflow, "TextGenerate", 0, "ShowText|pysssss", "text")

    def test_both_output_subgraphs_use_the_case_sensitive_moss_lora_folder(self):
        path = ROOT / "output" / "simpleWorkflowForMOSS_t2iBBOX (1).json"
        workflow = json.loads(path.read_text(encoding="utf-8"))
        subgraphs = workflow["definitions"]["subgraphs"]
        self.assertEqual({graph["name"] for graph in subgraphs}, {"MOSS-Image", "MOSS-Image T2I"})
        for graph in subgraphs:
            loaders = [node for node in graph["nodes"] if node["type"] == "LoraLoaderModelOnly"]
            self.assertTrue(loaders, graph["name"])
            for loader in loaders:
                with self.subTest(graph=graph["name"], node=loader["id"]):
                    # Compare parts as strings: PureWindowsPath equality ignores case.
                    self.assertEqual(PureWindowsPath(loader["widgets_values"][0]).parts,
                                     ("MOSS", "MOSS-Image-SFT-8-steps-dmd.safetensors"))


if __name__ == "__main__":
    unittest.main()
