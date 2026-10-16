"""Flux 3 unit tests using synthetic ComfyUI schemas and empty model files.

No ComfyUI process, model weights, network access, or extra packages are needed.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mm_images as I
from mm_common import Catalog, ModelMissing


UNET = "flux3_image_klein_base_int8_convrot.safetensors"
CLIP = "gemma4_e2b_it_bf16.safetensors"
VAE = "flux2_vae.safetensors"
UPSAMPLER = "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors"
LLM = "qwen3.5_9b_flux3_prompt_upsampler_w4a8.gguf"


def schema(required=(), optional=(), output=("STRING",)):
    """Only the object_info fields consumed by the adapter are needed here."""
    return {
        "input": {
            "required": {name: ["STRING"] for name in required},
            "optional": {name: ["STRING"] for name in optional},
        },
        "output": list(output),
    }


def clip_schema(options):
    return {"CLIPLoader": {"input": {"required": {"type": [options]}}}}


class Flux3TestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for folder, name in (("diffusion_models", UNET), ("text_encoders", CLIP), ("vae", VAE)):
            self.add_model(folder, name)

    def add_model(self, folder, name):
        path = self.root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def catalog(self, object_info=None):
        cat = Catalog([self.root], prefer_live=False)
        cat.object_info = object_info
        return cat

    def params(self, **overrides):
        defaults = {"mode": "flux3", "prompt": "a lighthouse at dawn", "seed": 17}
        defaults.update(overrides)
        return I.Params(**defaults)

    def info(self):
        return {"models": [], "warnings": [], "notes": []}

    def nodes_of(self, graph, cls):
        return [(nid, node["inputs"]) for nid, node in graph.items() if node["class_type"] == cls]

    def one(self, graph, cls):
        nodes = self.nodes_of(graph, cls)
        self.assertEqual(len(nodes), 1, f"Expected one {cls}: {nodes}")
        return nodes[0]


class Flux3AdapterHelperTests(Flux3TestCase):
    def test_default_candidates_are_copied_and_custom_candidate_is_first(self):
        defaults = list(I.FLUX3_UPSAMPLER_CANDS)
        candidates = I.flux3_upsampler_cands(self.params())
        self.assertEqual(candidates, defaults)
        candidates.clear()
        self.assertEqual(I.FLUX3_UPSAMPLER_CANDS, defaults)
        self.assertEqual(
            I.flux3_upsampler_cands(self.params(upsampler="custom.gguf")),
            ["custom.gguf"] + defaults,
        )

    def test_clip_type_prefers_newest_compatible_type_and_keeps_server_case(self):
        cases = (
            (["flux", "FLUX2", "Flux 3", "FLUX3"], "FLUX3"),
            (["flux", "flux2", "Flux 3"], "Flux 3"),
            (["flux", "FLUX2"], "FLUX2"),
            (["sdxl", "Flux"], "Flux"),
        )
        for options, expected in cases:
            with self.subTest(options=options):
                self.assertEqual(I.flux3_clip_type(self.catalog(clip_schema(options))), expected)

    def test_clip_type_accepts_new_combo_schema(self):
        info = {"CLIPLoader": {"input": {"required": {
            "type": ["COMBO", {"options": ["sdxl", "FLUX3"]}],
        }}}}
        self.assertEqual(I.flux3_clip_type(self.catalog(info)), "FLUX3")

    def test_clip_type_returns_none_without_compatible_advertised_options(self):
        for info in (None, {}, {"OtherNode": {}}, {"CLIPLoader": {}},
                     clip_schema([]), clip_schema(["sdxl", "ltxv"]),
                     {"CLIPLoader": {"input": {"required": {"type": ["STRING"]}}}}):
            with self.subTest(info=info):
                self.assertIsNone(I.flux3_clip_type(self.catalog(info)))

    def test_node_inputs_filters_unknown_keys_without_mutating_values(self):
        wanted = {"prompt": "hello", "max_tokens": 0, "model": None, "extra": False}
        before = dict(wanted)
        selected = I.node_inputs(schema(("prompt",), ("max_tokens", "model")), wanted)
        self.assertEqual(selected, {"prompt": "hello", "max_tokens": 0, "model": None})
        self.assertEqual(wanted, before)

    def test_node_inputs_rejects_missing_required_values(self):
        self.assertIsNone(I.node_inputs(schema(("prompt", "api")), {"prompt": "hello"}))
        self.assertEqual(I.node_inputs({}, {"unknown": "value"}), {})


class Flux3UpsamplerTests(Flux3TestCase):
    def upsample(self, object_info, **overrides):
        graph, info = I.Graph(), self.info()
        params = self.params(**overrides)
        result = I.flux3_upsample(graph, params, self.catalog(object_info), info, params.prompt)
        return result, graph.nodes, info

    def test_offline_catalog_returns_none_and_warns_without_adding_nodes(self):
        result, graph, info = self.upsample(None)
        self.assertIsNone(result)
        self.assertEqual(graph, {})
        self.assertTrue(any("ComfyUI" in warning for warning in info["warnings"]))

    def test_all_dedicated_nodes_and_prompt_input_aliases_are_supported(self):
        classes = ("Flux3UpsamplePromptWithTextEncodeAPI", "Flux3PromptUpsampler",
                   "Flux3PromptUpsample", "UpsamplePromptWithTextEncodeAPI", "TextEncodeAPI")
        for cls in classes:
            for prompt_input in ("prompt", "user_prompt", "input_prompt", "text"):
                with self.subTest(cls=cls, prompt_input=prompt_input):
                    result, graph, info = self.upsample({cls: schema((prompt_input,))})
                    nid, inputs = self.one(graph, cls)
                    self.assertEqual(result, [nid, 0])
                    self.assertEqual(inputs, {prompt_input: "a lighthouse at dawn"})
                    self.assertTrue(any(cls in value for _, value in info["models"]))

    def test_dedicated_node_receives_discovered_model_for_each_model_alias(self):
        self.add_model("text_encoders", UPSAMPLER)
        for model_input in ("model_name", "model", "llm", "ckpt_name", "unet_name", "api"):
            with self.subTest(model_input=model_input):
                cls = "Flux3PromptUpsampler"
                _, graph, _ = self.upsample({cls: schema(("prompt", model_input))})
                self.assertEqual(self.one(graph, cls)[1][model_input], UPSAMPLER)

    def test_dedicated_node_preserves_token_limits_seed_and_sampling_parameters(self):
        cls = "Flux3PromptUpsampler"
        for token_input in ("max_tokens", "max_new_tokens"):
            for limit in (0, 1, 2048):
                with self.subTest(token_input=token_input, limit=limit):
                    spec = schema(("prompt", token_input), ("temperature", "top_p", "seed"))
                    _, graph, _ = self.upsample({cls: spec}, upsample_max_tokens=limit, seed=0)
                    inputs = self.one(graph, cls)[1]
                    self.assertEqual(inputs[token_input], limit)
                    self.assertEqual(inputs["seed"], 0)
                    self.assertEqual(inputs["temperature"], 0.7)
                    self.assertEqual(inputs["top_p"], 1.0)

    def test_custom_safetensors_upsampler_is_preferred_over_default_model(self):
        self.add_model("text_encoders", UPSAMPLER)
        self.add_model("text_encoders", "custom.safetensors")
        cls = "Flux3PromptUpsampler"
        _, graph, _ = self.upsample({cls: schema(("prompt", "model_name"))}, upsampler="custom")
        self.assertEqual(self.one(graph, cls)[1]["model_name"], "custom.safetensors")

    def test_gguf_in_text_encoders_is_not_passed_to_safetensors_api(self):
        self.add_model("text_encoders", LLM)
        result, graph, _ = self.upsample({"TextEncodeAPI": schema(("prompt", "api"))})
        self.assertIsNone(result)
        self.assertEqual(graph, {})

    def test_incompatible_dedicated_nodes_are_skipped_for_a_compatible_one(self):
        for bad in (schema(("prompt", "unknown_required")),
                    schema(("prompt",), output=("IMAGE",)),
                    schema(("prompt",), output=())):
            with self.subTest(bad=bad):
                _, graph, _ = self.upsample({
                    "Flux3PromptUpsampler": bad,
                    "TextEncodeAPI": schema(("text",)),
                })
                self.assertEqual(len(graph), 1)
                self.one(graph, "TextEncodeAPI")

    def test_loader_sampler_pairs_support_their_model_and_connection_aliases(self):
        self.add_model("LLM", LLM)
        for loader, sampler in (("LLMSSRGLoader", "LLMSimpleTextGen"), ("LLMLoader", "LLMSampler")):
            for model_input in ("model_name", "ckpt_name", "name", "lora_name"):
                for connection in ("llm", "model", "server"):
                    with self.subTest(loader=loader, model_input=model_input, connection=connection):
                        result, graph, info = self.upsample({
                            loader: schema((model_input,), output=("LLM",)),
                            sampler: schema((connection, "user_prompt", "max_new_tokens")),
                        }, upsample_max_tokens=99)
                        lid, linputs = self.one(graph, loader)
                        sid, sinputs = self.one(graph, sampler)
                        self.assertEqual(len(graph), 2)
                        self.assertEqual(linputs, {model_input: LLM})
                        self.assertEqual(sinputs, {
                            connection: [lid, 0], "user_prompt": "a lighthouse at dawn", "max_new_tokens": 99,
                        })
                        self.assertEqual(result, [sid, 0])
                        self.assertTrue(any(LLM in value for _, value in info["models"]))

    def test_loader_can_discover_upsampler_in_loras_directory(self):
        self.add_model("loras", UPSAMPLER)
        _, graph, _ = self.upsample({
            "LLMLoader": schema(("model_name",)),
            "LLMSampler": schema(("model", "prompt")),
        })
        self.assertEqual(self.one(graph, "LLMLoader")[1]["model_name"], UPSAMPLER)

    def test_llm_directory_is_preferred_to_loras_directory(self):
        self.add_model("LLM", LLM)
        self.add_model("loras", UPSAMPLER)
        _, graph, _ = self.upsample({
            "LLMLoader": schema(("model_name",)),
            "LLMSampler": schema(("model", "prompt")),
        })
        self.assertEqual(self.one(graph, "LLMLoader")[1]["model_name"], LLM)

    def test_invalid_loader_sampler_pairs_leave_no_partial_graph(self):
        self.add_model("LLM", LLM)
        for loader_spec, sampler_spec in (
            (schema(("unknown_required",)), schema(("model", "prompt"))),
            (schema(("model_name",)), schema(("model", "unknown_required"))),
            (schema(("model_name",)), schema(("model", "prompt"), output=("IMAGE",))),
        ):
            with self.subTest(loader_spec=loader_spec, sampler_spec=sampler_spec):
                result, graph, _ = self.upsample({"LLMLoader": loader_spec, "LLMSampler": sampler_spec})
                self.assertIsNone(result)
                self.assertEqual(graph, {})

    def test_chatgpt_strips_windows_and_posix_paths_and_only_the_final_extension(self):
        for model_path in ("vendor/qwen3.5.gguf", r"vendor\qwen3.5.gguf"):
            with self.subTest(model_path=model_path):
                # Catalog returns native paths; stub only model selection to cover both OS forms.
                cat = self.catalog({"ChatGPT": schema(("file_name", "user_prompt"), ("mode", "system_prompt"))})
                graph, info = I.Graph(), self.info()
                with patch.object(cat, "pick", side_effect=lambda kind, *args, **kwargs: model_path if kind == "llm" else None):
                    result = I.flux3_upsample(graph, self.params(), cat, info, "hello")
                nid, inputs = self.one(graph.nodes, "ChatGPT")
                self.assertEqual(result, [nid, 0])
                self.assertEqual(inputs, {
                    "file_name": "qwen3.5", "user_prompt": "hello", "mode": "chat", "system_prompt": "",
                })

    def test_chatgpt_rejects_unknown_required_inputs_or_nonstring_outputs(self):
        self.add_model("LLM", LLM)
        for spec in (schema(("prompt", "unknown_required")), schema(("prompt",), output=("IMAGE",))):
            with self.subTest(spec=spec):
                result, graph, _ = self.upsample({"ChatGPT": spec})
                self.assertIsNone(result)
                self.assertEqual(graph, {})

    def test_no_matching_model_or_complete_node_pair_returns_none(self):
        for info in ({"OtherNode": schema()}, {"LLMLoader": schema(("model_name",))},
                     {"LLMLoader": schema(("model_name",)), "LLMSampler": schema(("model", "prompt"))},
                     {"ChatGPT": schema(("file_name", "prompt"))}):
            with self.subTest(info=info):
                result, graph, _ = self.upsample(info)
                self.assertIsNone(result)
                self.assertEqual(graph, {})

    def test_dedicated_node_takes_priority_over_loader_and_chatgpt(self):
        self.add_model("LLM", LLM)
        _, graph, _ = self.upsample({
            "Flux3PromptUpsampler": schema(("prompt",)),
            "LLMLoader": schema(("model_name",)),
            "LLMSampler": schema(("model", "prompt")),
            "ChatGPT": schema(("prompt", "file_name")),
        })
        self.assertEqual(len(graph), 1)
        self.one(graph, "Flux3PromptUpsampler")

    def test_regression_string_output_can_be_after_another_output(self):
        """The adapter links the STRING output even when it follows another output."""
        result, graph, _ = self.upsample({
            "Flux3PromptUpsampler": schema(("prompt",), output=("IMAGE", "STRING")),
        })
        nid, _ = self.one(graph, "Flux3PromptUpsampler")
        self.assertEqual(result, [nid, 1])

    def test_regression_missing_api_model_does_not_hide_later_compatible_node(self):
        """A missing API model does not hide a later compatible dedicated node."""
        result, graph, _ = self.upsample({
            "Flux3UpsamplePromptWithTextEncodeAPI": schema(("prompt", "api")),
            "Flux3PromptUpsampler": schema(("prompt",)),
        })
        self.assertIsNotNone(result)
        self.one(graph, "Flux3PromptUpsampler")


class Flux3WorkflowTests(Flux3TestCase):
    def build(self, object_info=None, **overrides):
        defaults = {"no_upsample": True, "turbo": "off"}
        defaults.update(overrides)
        if object_info is None:
            object_info = clip_schema(["flux3"])
        return I.build(self.params(**defaults), self.catalog(object_info))

    def test_default_workflow_loads_models_and_wires_sampler_through_save_image(self):
        graph, info = self.build()
        unet, uinputs = self.one(graph, "UNETLoader")
        clip, cinputs = self.one(graph, "CLIPLoader")
        vae, vinputs = self.one(graph, "VAELoader")
        self.assertEqual(uinputs, {"unet_name": UNET, "weight_dtype": "default"})
        self.assertEqual(cinputs, {"clip_name": CLIP, "type": "flux3", "device": "default"})
        self.assertEqual(vinputs, {"vae_name": VAE})
        encodes = self.nodes_of(graph, "CLIPTextEncode")
        self.assertEqual([inputs["text"] for _, inputs in encodes], ["a lighthouse at dawn", ""])
        self.assertTrue(all(inputs["clip"] == [clip, 0] for _, inputs in encodes))
        latent, linputs = self.one(graph, "EmptyFlux2LatentImage")
        sigmas, sinputs = self.one(graph, "Flux2Scheduler")
        noise, ninputs = self.one(graph, "RandomNoise")
        sampler, selselect = self.one(graph, "KSamplerSelect")
        guider, ginputs = self.one(graph, "CFGGuider")
        sampled, sample_inputs = self.one(graph, "SamplerCustomAdvanced")
        decoded, decode_inputs = self.one(graph, "VAEDecode")
        self.assertEqual(linputs, {"width": 1024, "height": 1024, "batch_size": 1})
        self.assertEqual(sinputs, {"steps": 25, "width": 1024, "height": 1024})
        self.assertEqual(ninputs, {"noise_seed": 17})
        self.assertEqual(selselect, {"sampler_name": "euler"})
        self.assertEqual(ginputs, {
            "model": [unet, 0], "positive": [encodes[0][0], 0],
            "negative": [encodes[1][0], 0], "cfg": 3.5,
        })
        self.assertEqual(sample_inputs, {
            "noise": [noise, 0], "guider": [guider, 0], "sampler": [sampler, 0],
            "sigmas": [sigmas, 0], "latent_image": [latent, 0],
        })
        self.assertEqual(decode_inputs, {"samples": [sampled, 0], "vae": [vae, 0]})
        self.assertEqual(self.one(graph, "SaveImage")[1], {
            "images": [decoded, 0], "filename_prefix": "mm_flux3",
        })
        self.assertEqual((info["steps"], info["cfg"], info["seed"]), (25, 3.5, 17))
        self.assertEqual(info["sampler"], "euler/Flux2Scheduler")
        self.assertEqual(info["warnings"], [])
        self.assertIn(("Text-Encoder", CLIP), info["models"])

    def test_model_overrides_are_used_by_each_loader(self):
        for folder, name in (("diffusion_models", "custom_unet.gguf"),
                             ("text_encoders", "custom_clip.safetensors"), ("vae", "custom_vae.pt")):
            self.add_model(folder, name)
        graph, _ = self.build(unet="custom_unet", clip="custom_clip", vae="custom_vae")
        self.assertEqual(self.one(graph, "UnetLoaderGGUF")[1], {"unet_name": "custom_unet.gguf"})
        self.assertEqual(self.one(graph, "CLIPLoader")[1]["clip_name"], "custom_clip.safetensors")
        self.assertEqual(self.one(graph, "VAELoader")[1]["vae_name"], "custom_vae.pt")

    def test_checkpoint_fallback_is_used_when_no_diffusion_model_matches(self):
        (self.root / "diffusion_models" / UNET).unlink()
        self.add_model("checkpoints", UNET)
        graph, _ = self.build()
        checkpoint, inputs = self.one(graph, "CheckpointLoaderSimple")
        self.assertEqual(inputs, {"ckpt_name": UNET})
        self.assertEqual(self.one(graph, "CFGGuider")[1]["model"], [checkpoint, 0])

    def test_missing_required_models_raise_modelmissing(self):
        for overrides in ({"unet": "missing_unet"}, {"clip": "missing_clip"}, {"vae": "missing_vae"}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ModelMissing):
                    self.build(**overrides)

    def test_missing_live_clip_type_warns_and_falls_back_to_flux(self):
        graph, info = self.build(object_info={"OtherNode": schema()})
        self.assertEqual(self.one(graph, "CLIPLoader")[1]["type"], "flux")
        self.assertTrue(any("CLIPLoader" in warning for warning in info["warnings"]))

    def test_upsampling_is_enabled_by_default_and_feeds_only_positive_conditioning(self):
        obj = clip_schema(["flux3"])
        obj["Flux3PromptUpsampler"] = schema(("prompt",))
        graph, info = I.build(self.params(turbo="off", negative="blurry"), self.catalog(obj))
        upsampler, inputs = self.one(graph, "Flux3PromptUpsampler")
        self.assertEqual(inputs["prompt"], "a lighthouse at dawn")
        encodes = self.nodes_of(graph, "CLIPTextEncode")
        self.assertEqual(encodes[0][1]["text"], [upsampler, 0])
        self.assertEqual(encodes[1][1]["text"], "blurry")
        self.assertEqual(info["warnings"], [])

    def test_disabling_upsampling_does_not_call_the_adapter(self):
        with patch.object(I, "flux3_upsample") as adapter:
            graph, info = self.build(no_upsample=True)
        adapter.assert_not_called()
        self.assertEqual(self.nodes_of(graph, "CLIPTextEncode")[0][1]["text"], "a lighthouse at dawn")
        self.assertEqual(info["warnings"], [])

    def test_missing_upsampler_keeps_original_prompt_and_warns(self):
        graph, info = self.build(no_upsample=False)
        self.assertEqual(self.nodes_of(graph, "CLIPTextEncode")[0][1]["text"], "a lighthouse at dawn")
        self.assertTrue(any("Prompt-Upsampler" in warning for warning in info["warnings"]))

    def test_turbo_preset_and_user_loras_chain_model_and_clip_connections(self):
        self.add_model("loras", "flux3_turbo.safetensors")
        self.add_model("loras", "style.safetensors")
        graph, info = self.build(turbo="turbo", loras=[("style", 0.65)])
        first, second = self.nodes_of(graph, "LoraLoader")
        self.assertEqual(first[1]["lora_name"], "flux3_turbo.safetensors")
        self.assertEqual((first[1]["strength_model"], first[1]["strength_clip"]), (1.0, 1.0))
        self.assertEqual(second[1], {
            "model": [first[0], 0], "clip": [first[0], 1], "lora_name": "style.safetensors",
            "strength_model": 0.65, "strength_clip": 0.65,
        })
        self.assertEqual(self.one(graph, "CFGGuider")[1]["model"], [second[0], 0])
        self.assertEqual(self.nodes_of(graph, "CLIPTextEncode")[0][1]["clip"], [second[0], 1])
        self.assertEqual((info["steps"], info["cfg"]), (8, 1.0))
        self.one(graph, "ConditioningZeroOut")

    def test_auto_and_off_skip_turbo_even_when_available(self):
        self.add_model("loras", "flux3_turbo.safetensors")
        graph, info = self.build(turbo="auto")
        self.assertEqual(self.nodes_of(graph, "LoraLoader"), [])
        self.assertEqual((info["steps"], info["cfg"]), (25, 3.5))
        self.assertFalse(any("Turbo-LoRA" in warning for warning in info["warnings"]))
        graph, info = self.build(turbo="off")
        self.assertEqual(self.nodes_of(graph, "LoraLoader"), [])
        self.assertEqual((info["steps"], info["cfg"]), (25, 3.5))

    def test_missing_turbo_is_optional_in_auto_mode_and_required_when_requested(self):
        graph, info = self.build(turbo="auto")
        self.assertEqual(self.nodes_of(graph, "LoraLoader"), [])
        self.assertEqual((info["steps"], info["cfg"]), (25, 3.5))
        self.assertFalse(any("Turbo-LoRA" in warning for warning in info["warnings"]))
        with self.assertRaises(ModelMissing):
            self.build(turbo="turbo")

    def test_explicit_sampling_sizes_batch_and_prefix_override_turbo_defaults(self):
        self.add_model("loras", "flux3_turbo.safetensors")
        graph, info = self.build(turbo="turbo", steps=28, cfg=4.0, sampler="heun",
                                 width=777, height=513, batch=3, prefix="custom", seed=0)
        self.assertEqual((info["steps"], info["cfg"], info["seed"]), (28, 4.0, 0))
        self.assertEqual(self.one(graph, "EmptyFlux2LatentImage")[1], {
            "width": 784, "height": 512, "batch_size": 3,
        })
        self.assertEqual(self.one(graph, "Flux2Scheduler")[1], {"steps": 28, "width": 784, "height": 512})
        self.assertEqual(self.one(graph, "KSamplerSelect")[1]["sampler_name"], "heun")
        self.assertEqual(self.one(graph, "SaveImage")[1]["filename_prefix"], "custom")

    def test_cfg_zero_is_preserved_and_nonempty_negative_is_encoded(self):
        graph, info = self.build(cfg=0.0, negative="blurry")
        self.assertEqual(info["cfg"], 0.0)
        self.assertEqual(self.one(graph, "CFGGuider")[1]["cfg"], 0.0)
        self.assertEqual(self.nodes_of(graph, "ConditioningZeroOut"), [])
        self.assertEqual(self.nodes_of(graph, "CLIPTextEncode")[1][1]["text"], "blurry")

    def test_blank_negative_at_cfg_one_zeros_positive_conditioning(self):
        graph, _ = self.build(cfg=1.0, negative=" \n ")
        positive, _ = self.one(graph, "CLIPTextEncode")
        zero, inputs = self.one(graph, "ConditioningZeroOut")
        self.assertEqual(inputs["conditioning"], [positive, 0])
        self.assertEqual(self.one(graph, "CFGGuider")[1]["negative"], [zero, 0])

    def test_multiple_references_condition_both_branches_and_first_image_sets_size(self):
        graph, _ = self.build(images=["first.png", "second.png"], megapixels=0.75)
        loaded = self.nodes_of(graph, "LoadImage")
        scales = self.nodes_of(graph, "ImageScaleToTotalPixels")
        encoded = self.nodes_of(graph, "VAEEncode")
        refs = self.nodes_of(graph, "ReferenceLatent")
        text = self.nodes_of(graph, "CLIPTextEncode")
        self.assertEqual([inputs["image"] for _, inputs in loaded], ["first.png", "second.png"])
        self.assertEqual(len(refs), 4)
        vae, _ = self.one(graph, "VAELoader")
        for index in range(2):
            self.assertEqual(scales[index][1], {
                "image": [loaded[index][0], 0], "upscale_method": "lanczos",
                "megapixels": 0.75, "resolution_steps": 16,
            })
            self.assertEqual(encoded[index][1], {"pixels": [scales[index][0], 0], "vae": [vae, 0]})
            for branch in range(2):
                prior = text[branch][0] if index == 0 else refs[branch][0]
                self.assertEqual(refs[2 * index + branch][1], {
                    "conditioning": [prior, 0], "latent": [encoded[index][0], 0],
                })
        size, inputs = self.one(graph, "GetImageSize")
        self.assertEqual(inputs["image"], [scales[0][0], 0])
        for cls in ("EmptyFlux2LatentImage", "Flux2Scheduler"):
            self.assertEqual(self.one(graph, cls)[1]["width"], [size, 0])
            self.assertEqual(self.one(graph, cls)[1]["height"], [size, 1])
        guider = self.one(graph, "CFGGuider")[1]
        self.assertEqual(guider["positive"], [refs[2][0], 0])
        self.assertEqual(guider["negative"], [refs[3][0], 0])

    def test_explicit_dimensions_override_reference_image_size(self):
        graph, _ = self.build(images=["first.png"], size_explicit=True, width=512, height=768)
        self.assertEqual(self.nodes_of(graph, "GetImageSize"), [])
        self.assertEqual(self.one(graph, "EmptyFlux2LatentImage")[1], {
            "width": 512, "height": 768, "batch_size": 1,
        })
        self.assertEqual(len(self.nodes_of(graph, "ReferenceLatent")), 2)

    def test_controlnet_requests_are_rejected_for_flux3(self):
        for control in ("auto", "union", "depth", "tile"):
            with self.subTest(control=control):
                with self.assertRaisesRegex(I.Unsupported, "Flux 3.*ControlNet"):
                    self.build(control=control, control_image="pose.png")


if __name__ == "__main__":
    unittest.main()
