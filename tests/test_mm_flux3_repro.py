# -*- coding: utf-8 -*-
"""Flux-3-Reproduktionen aus dem hochgeladenen Workflow (mm_flux3_20261016_235552.api.json):

1) Upsampler-Aufruf mit leerem Prompt (+ negativer Prompt aus Datei) -> der
   Upsampler hat einen 'ChatGPT'-Loader-Knoten ohne 'user_prompt' in den Graphen
   gesetzt; ComfyUI lehnte die Queue mit 400 'invalid prompt' ab.
2) Der Flux-3-Graph braucht zwingend die Node 'Flux3ImageGuidanceEmbedder'
   (offizielles Template flux3_klein_base); ohne sie ignoriert FLUX.3 guidance/cfg.
"""
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import mm as MM  # noqa: E402
import mm_common as C  # noqa: E402
import mm_images as I  # noqa: E402


def make_models(tmp: Path) -> Path:
    root = tmp / "models"
    for sub, fname in (
        ("diffusion_models", "flux3_image_klein_base_int8_convrot.safetensors"),
        ("text_encoders", "gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors"),
        ("text_encoders", "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors"),
        ("vae", "flux2_vae.safetensors"),
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
        (root / sub / fname).write_bytes(b"x")
    llm = root / "LLM"
    llm.mkdir(parents=True, exist_ok=True)
    (llm / "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors").write_bytes(b"x")
    return root


def fake_object_info() -> dict:
    """Minimales object_info wie bei einer laufenden ComfyUI + ChatGPT-Node-Paket."""
    combo = lambda opts: [opts]
    info = {
        "UNETLoader": {"input": {"required": {"unet_name": combo([]), "weight_dtype": combo(["default"])}},
                       "output": ["MODEL"], "output_is_list": [False], "name": "UNETLoader"},
        "CLIPLoader": {"input": {"required": {"clip_name": combo([]), "type": combo(["flux3"]),
                                              "device": combo(["default"])}},
                       "output": ["CLIP"], "output_is_list": [False], "name": "CLIPLoader"},
        "VAELoader": {"input": {"required": {"vae_name": combo([])}},
                      "output": ["VAE"], "output_is_list": [False], "name": "VAELoader"},
        "LoraLoaderModelOnly": {"input": {"required": {"model": ["MODEL"], "lora_name": combo([]),
                                                       "strength_model": ["FLOAT"]}},
                                "output": ["MODEL"], "output_is_list": [False]},
        "LoraLoader": {"input": {"required": {"model": ["MODEL"], "clip": ["CLIP"], "lora_name": combo([]),
                                              "strength_model": ["FLOAT"], "strength_clip": ["FLOAT"]}},
                       "output": ["MODEL", "CLIP"], "output_is_list": [False, False]},
        "CLIPTextEncode": {"input": {"required": {"clip": ["CLIP"], "text": ["STRING"]}},
                           "output": ["CONDITIONING"], "output_is_list": [False]},
        "ConditioningZeroOut": {"input": {"required": {"conditioning": ["CONDITIONING"]}},
                                "output": ["CONDITIONING"], "output_is_list": [False]},
        "EmptyFlux2LatentImage": {"input": {"required": {"width": ["INT"], "height": ["INT"],
                                                         "batch_size": ["INT"]}},
                                  "output": ["LATENT"], "output_is_list": [False]},
        "BasicScheduler": {"input": {"required": {"model": ["MODEL"], "scheduler": combo(["simple"]),
                                                  "steps": ["INT"], "denoise": ["FLOAT"]}},
                           "output": ["SIGMAS"], "output_is_list": [False]},
        "KSamplerSelect": {"input": {"required": {"sampler_name": combo(["euler"])},
                                     "optional": {"function": ["CUSTOM"]}},
                           "output": ["SAMPLER"], "output_is_list": [False]},
        "RandomNoise": {"input": {"required": {"noise_seed": ["INT"]}},
                        "output": ["NOISE"], "output_is_list": [False]},
        "CFGGuider": {"input": {"required": {"model": ["MODEL"], "positive": ["CONDITIONING"],
                                             "negative": ["CONDITIONING"], "cfg": ["FLOAT"]}},
                      "output": ["GUIDER"], "output_is_list": [False]},
        "Flux2Scheduler": {"input": {"required": {"steps": ["INT"], "width": ["INT"], "height": ["INT"]}},
                            "output": ["SIGMAS"], "output_is_list": [False]},
        "Flux3ImageGuidanceEmbedder": {"input": {"required": {"model": ["MODEL"]},
                                                 "optional": {"guidance": ["FLOAT", {"default": 3.5}]}},
                                        "output": ["MODEL"], "output_is_list": [False]},
        "SamplerCustomAdvanced": {"input": {"required": {"noise": ["NOISE"], "guider": ["GUIDER"],
                                                          "sampler": ["SAMPLER"], "sigmas": ["SIGMAS"],
                                                          "latent_image": ["LATENT"]}},
                                   "output": ["LATENT", "LATENT"], "output_is_list": [False, False]},
        "VAEDecode": {"input": {"required": {"samples": ["LATENT"], "vae": ["VAE"]}},
                      "output": ["IMAGE"], "output_is_list": [False]},
        "SaveImage": {"input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING"]}},
                      "output": [], "output_is_list": []},
        "LoadImage": {"input": {"required": {"image": combo([])}, "optional": {"upload": ["IMAGEUPLOAD"]}},
                       "output": ["IMAGE", "MASK"], "output_is_list": [False, False]},
        "ImageScaleToTotalPixels": {"input": {"required": {"image": ["IMAGE"],
                                                            "upscale_method": combo(["lanczos"]),
                                                            "megapixels": ["FLOAT"]},
                                              "optional": {"resolution_steps": ["INT"]}},
                                     "output": ["IMAGE"], "output_is_list": [False]},
        "GetImageSize": {"input": {"required": {"image": ["IMAGE"]}},
                          "output": ["INT", "INT", "INT"], "output_is_list": [False, False, False]},
        "ReferenceLatent": {"input": {"required": {"conditioning": ["CONDITIONING"], "latent": ["LATENT"]}},
                             "output": ["CONDITIONING"], "output_is_list": [False]},
        "VAEEncode": {"input": {"required": {"pixels": ["IMAGE"], "vae": ["VAE"]}},
                      "output": ["LATENT"], "output_is_list": [False]},
    }
    # ChatGPT-Node (ComfyUI-GPT-Paket): 'file_name' PFLICHT - so wie real installiert
    info["ChatGPT"] = {
        "input": {"required": {"file_name": combo(["qwen3.5_9b_flux3_prompt_upsampler_w4a8"]),
                               "user_prompt": ["STRING", {"multiline": True}],
                               "system_prompt": ["STRING", {"multiline": True, "default": ""}],
                               "api_endpoint": ["STRING", {"default": "http://127.0.0.1:8181"}],
                               "temperature": ["FLOAT", {"default": 0.7}],
                               "top_p": ["FLOAT", {"default": 1.0}],
                               "max_tokens": ["INT", {"default": 512}],
                               "seed": ["INT", {"default": 0}],
                               "mode": combo(["chat"])},
                    "optional": {}},
        "output": ["STRING"], "output_is_list": [False], "name": "ChatGPT",
    }
    return info


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def live_cat(root: Path) -> C.Catalog:
    cat = C.Catalog([root], url=None, prefer_live=False)
    info = fake_object_info()
    info["UNETLoader"]["input"]["required"]["unet_name"] = [[p.name for p in (root / "diffusion_models").iterdir()]]
    info["CLIPLoader"]["input"]["required"]["clip_name"] = [[p.name for p in (root / "text_encoders").iterdir()]]
    info["VAELoader"]["input"]["required"]["vae_name"] = [[p.name for p in (root / "vae").iterdir()]]
    info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"] = [[]]
    cat.object_info = info
    cat._names = {}
    cat.live_ok = True
    return cat


class UpsamplerEmptyPromptTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_models(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_flux3_with_upsampler_and_empty_main_prompt(self):
        """Der Fall aus dem Upload: leerer Haupt-Prompt + negativer Prompt."""
        cat = live_cat(self.root)
        p = I.Params(mode="flux3", prompt="", negative="low quality, blurry, watermark",
                     no_upsample=False)
        info = {"models": [], "warnings": [], "notes": []}
        g = I.build_flux3(p, cat, info)
        chatgpt = [n for n in g.nodes.values() if n["class_type"] == "ChatGPT"]
        self.assertEqual(len(chatgpt), 1, "Upsampler soll genau einen Knoten anlegen")
        self.assertTrue(str(chatgpt[0]["inputs"].get("user_prompt", "")).strip(),
                        "ChatGPT.user_prompt darf nicht fehlen/leer sein (sonst 400 invalid prompt)")
        problems = I.validate(g.nodes, cat.object_info)
        self.assertEqual(problems, [], f"Validierungsprobleme: {problems}")

    def test_cmd_image_run_reports_invalid_prompt_instead_of_crashing(self):
        """Server antwortet 400 'invalid prompt' -> Exit 1, Meldung auf stderr, kein Traceback."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            cfg = {
                "output_dir": str(tdp / "out"),
                "prompt_file": str(tdp / "empty.txt"),
                "negative_file": str(tdp / "neg.txt"),
                "targets": {"image": {"url": "http://fake:1", "comfy_dir": None,
                                      "model_roots": [str(self.root)]}},
                "image": {"width": 1024, "height": 1024, "batch": 1, "timeout_s": 60, "negative": ""},
            }
            (tdp / "empty.txt").write_text("", encoding="utf-8")
            (tdp / "neg.txt").write_text("low quality, blurry, watermark", encoding="utf-8")
            calls = []
            object_info = live_cat(self.root).object_info

            def fake_urlopen(req, timeout=None):
                calls.append(req)
                if isinstance(req.data, bytes):     # POST /prompt -> exakt der reale Fehlerfall
                    body = json.dumps({"error": "invalid prompt", "node_errors": {}}).encode()
                    raise urllib.error.HTTPError("http://fake:1/prompt", 400, "Bad Request",
                                                 {}, io.BytesIO(body))
                self.assertEqual(req.full_url, "http://fake:1/object_info")
                return FakeResp(json.dumps(object_info).encode())

            argv = ["mm.py", "image", "flux3", "--prompt", "ein test-prompt", "--run"]
            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(C, "load_config", return_value=cfg), \
                 mock.patch.object(C, "server_alive", return_value=True), \
                 mock.patch.object(urllib.request, "urlopen", side_effect=fake_urlopen), \
                 redirect_stdout(io.StringIO()) as out, \
                 redirect_stderr(io.StringIO()) as err:
                code = MM.main()
        text = out.getvalue()
        self.assertEqual(code, 1, f"erwarteter Rueckgabewert 1, Text:\n{text}\n{err.getvalue()}")
        self.assertEqual(err.getvalue(), "[!] ComfyUI lehnt den Workflow ab: invalid prompt\n")
        self.assertNotIn("Traceback", text + err.getvalue())
        # Der gesendete Graph duerfte keinen unvollstaendigen ChatGPT-Knoten enthalten
        posts = [r for r in calls if isinstance(r.data, bytes)]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].full_url, "http://fake:1/prompt")
        sent = json.loads(posts[0].data.decode())["prompt"]
        self.assertEqual(I.validate(sent, object_info), [])
        chatgpt = [node for node in sent.values() if node["class_type"] == "ChatGPT"]
        self.assertEqual(len(chatgpt), 1)
        self.assertEqual(chatgpt[0]["inputs"]["user_prompt"], "ein test-prompt")


class GuidanceEmbedderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_models(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _params(self, **kw):
        p = I.Params(mode="flux3", prompt="test", no_upsample=True)
        for k, v in kw.items():
            setattr(p, k, v)
        return p

    def test_graph_contains_guidance_embedder_when_node_exists(self):
        cat = live_cat(self.root)
        info = {"models": [], "warnings": [], "notes": []}
        g = I.build_flux3(self._params(), cat, info)
        embedders = [n for n in g.nodes.values() if n["class_type"] == "Flux3ImageGuidanceEmbedder"]
        self.assertEqual(len(embedders), 1, "Flux 3 braucht den Guidance-Embedder (Template-Workflow)")
        self.assertEqual(embedders[0]["inputs"]["guidance"], 3.5)
        # CFGGuider muss das Modell VOM Embedder beziehen
        guider = next(n for n in g.nodes.values() if n["class_type"] == "CFGGuider")
        emb_id = next(nid for nid, n in g.nodes.items()
                      if n["class_type"] == "Flux3ImageGuidanceEmbedder")
        self.assertEqual(guider["inputs"]["model"][0], emb_id)

    def test_missing_node_in_server_warns_instead_of_hard_fail(self):
        cat = live_cat(self.root)
        del cat.object_info["Flux3ImageGuidanceEmbedder"]
        info = {"models": [], "warnings": [], "notes": []}
        g = I.build_flux3(self._params(), cat, info)
        self.assertFalse(any(n["class_type"] == "Flux3ImageGuidanceEmbedder" for n in g.nodes.values()))
        self.assertTrue(any("Flux3ImageGuidanceEmbedder" in w for w in info["warnings"]))

    def test_offline_build_still_has_embedder(self):
        cat = C.Catalog([self.root], url=None, prefer_live=False)
        info = {"models": [], "warnings": [], "notes": []}
        g = I.build_flux3(self._params(), cat, info)
        self.assertTrue(any(n["class_type"] == "Flux3ImageGuidanceEmbedder" for n in g.nodes.values()))


if __name__ == "__main__":
    unittest.main()
