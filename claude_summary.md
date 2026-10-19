Anfrage
Command
cd D:\claudeAgent\CWBuilder
$m = Get-Content src\mm.py -Encoding UTF8
"=== 1-112 ==="; $m[0..111]
"=== 238-320 ==="; $m[237..319]
"=== mm_common load_config / LIVE_SOURCES ==="; $c = Get-Content src\mm_common.py -Encoding UTF8; $c[24..160]

Timeout
30Response: === 1-112 ===
# -*- coding: utf-8 -*-
"""Minimax / ComfyUI Generator - Kommandozeile.

    mm.py video  [prompt | datei.txt | ziel.json] [Optionen]     Minimax-H3 Workflow-JSON
    mm.py image  <modus> [prompt | datei.txt] [Optionen]          Bild-Workflow (+ --run)
    mm.py list                                                    Modi, Turbo-LoRAs, Server
    mm.py check                                                   alle Modi gegen vorhandene Modelle testen

Ohne Unterbefehl (z.B. .txt auf die start.bat gezogen) wird 'video' angenommen.
Alle Pfade stehen in config.json; der Ordner kann beliebig verschoben werden.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mm_common as C  # noqa: E402

LTX_MODES = {"ltx23": "LTX-Video 2.3", "ltx25": "LTX-Video 2.5"}

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

COMMANDS = {"video", "image", "list", "check", "ui", "-h", "--help"}

MODE_ALIASES = {
    "krea": "krea2", "krea-2": "krea2",
    "klein": "klein9b", "flux2": "klein9b", "flux2klein": "klein9b", "klein-9b": "klein9b", "9b": "klein9b",
    "klein-4b": "klein4b", "4b": "klein4b",
    "edit": "qwen-edit", "qwenedit": "qwen-edit", "qwen_edit": "qwen-edit",
    "qwen": "qwen21", "qwen2.1": "qwen21", "qwen-image": "qwen21", "qwen-2.1": "qwen21",
    "z-image": "zimage", "zit": "zimage", "z": "zimage",
    "flux3": "flux3", "flux-3": "flux3", "flux3klein": "flux3", "flux3-base": "flux3", "f3": "flux3",
    # MOSS aliases
    "moss": "moss_t2i", "moss-t2i": "moss_t2i", "moss_t2i": "moss_t2i",
    "moss-inpaint": "moss_inpaint", "moss_inpaint": "moss_inpaint",
    "moss-detailer": "moss_detailer", "moss_detailer": "moss_detailer",
    "moss-prompt": "moss_prompt_enhancer", "moss-prompt-enhancer": "moss_prompt_enhancer", "moss_prompt_enhancer": "moss_prompt_enhancer",
    "moss-4step": "moss_4step", "moss_4step": "moss_4step", "moss4step": "moss_4step",
}

EPILOG = """\
Beispiele:
  mm.py video                                   Prompt aus prompts\\prompt.txt (GANZER Text)
  mm.py video "Ein Leuchtturm im Morgengrauen" -o leuchtturm.json --steps 4
  mm.py image krea2 --run                       Krea 2 Turbo, Turbo-LoRA automatisch
  mm.py image klein9b -i foto.png --run         FLUX.2 Klein 9B als Edit
  mm.py image qwen21 --turbo p8 --control --control-image pose.png --run
  mm.py image qwen-edit -i a.png -i b.png "Person aus Bild 2 in Szene 1" --run
  mm.py image flux3 --run                       Flux 3 (Klein Base int8 + Gemma 4 + Prompt-Upsampler)
  mm.py image flux3 --no-upsample --steps 28 --cfg 4.0 --run
  mm.py image moss --run                        MOSS T2I (Turbo dmd8, 8 Steps)
  mm.py image moss --turbo rapid4 --run         MOSS T2I mit RapidMOSSAdapter (4 Steps)
  mm.py image moss-inpaint -i img.png --control-image mask.png --run
  mm.py image moss-detailer -i portrait.png --run
  mm.py image moss-4step --run                  MOSS 4-Step (RapidMOSS, 4 Steps)
  mm.py ui                                      Gradio-Oberflaeche (Port 7865)

"""


# ───────────────────────────── Hilfsfunktionen ─────────────────────────────

def parse_loras(items: list[str] | None) -> list[tuple[str, float]]:
    out = []
    for it in items or []:
        name, strength = it, 1.0
        if ":" in it:
            head, tail = it.rsplit(":", 1)
            try:
                strength, name = float(tail), head
            except ValueError:
                pass
        out.append((name.strip().strip('"'), strength))
    return out


def ensure_server(tgt: dict, start: bool) -> bool:
    """True, wenn ComfyUI antwortet. Startet sie bei Bedarf ueber start_bat."""
    url = tgt["url"]
    if C.server_alive(url):
        return True
    bat = tgt.get("start_bat")
    if not (start and bat):
        return False
    bat = C.abspath(bat)
    if not bat.exists():
        print(f"[!] start_bat nicht gefunden: {bat}", file=sys.stderr)
        return False
    if not hasattr(os, "startfile"):
        print("[!] Automatischer Start geht nur unter Windows.", file=sys.stderr)
        return False
    print(f"[i] ComfyUI ({tgt['name']}) laeuft nicht - starte {bat.name} ...")
    os.startfile(str(bat))  # noqa: S606 - eigenes Konsolenfenster
    t0 = time.time()
    while time.time() - t0 < 300:
        time.sleep(3)
        if C.server_alive(url):
            print(f"[OK] ComfyUI bereit nach {int(time.time() - t0)}s")
            return True
        print("    ... warte auf ComfyUI", flush=True)
    return False

=== 238-320 ===
    text, pfile, out = [], None, None
    for it in items or []:
        s = it.strip().strip('"')
        low = s.lower()
        if low.endswith(".txt") and Path(s).exists():
            pfile = s
        elif low.endswith(".json") and "\n" not in s and len(s) < 260:
            out = s
        else:
            text.append(it)
    return (" ".join(text).strip() or None), pfile, out


# ───────────────────────────── list / check ─────────────────────────────

def cmd_list(a) -> int:
    import mm_images as I

    cfg = C.load_config()
    for name in ("image", "video"):
        t = C.target(cfg, name)
        state = "ONLINE" if C.server_alive(t["url"]) else "offline"
        print(f"Ziel {name:<5} {t['url']:<24} {state:<8} {t.get('comfy_dir')}")
    tgt = C.target(cfg, "image")
    cat = C.Catalog(tgt["model_roots"], url=tgt["url"])
    print(f"\nModelle: {'live' if cat.live_ok else 'von Platte'}\n")
    for mode, (title, caps) in I.MODE_INFO.items():
        edit = "Edit/Referenzbilder" if caps["edit"] else "nur Text"
        ctl = ", ".join(caps["control"]) or "kein ControlNet"
        print(f"{mode:<10} {title:<22} {edit:<20} Control: {ctl}")
        presets = I.TURBO_PRESETS.get(mode, {})
        if not presets:
            print("           Turbo: (Modell ist bereits destilliert / keine Turbo-LoRA)")
        for key, (cand, steps, c) in presets.items():
            found = cat.pick("loras", [cand], required=False)
            print(f"           Turbo '{key}': {steps} Steps  {'OK  ' + found if found else 'FEHLT (' + cand + ')'}")
    print("\nAliase:", ", ".join(f"{k}->{v}" for k, v in MODE_ALIASES.items()))
    return 0


def cmd_check(a) -> int:
    import mm_images as I

    cfg = C.load_config()
    tgt = C.target(cfg, "image")
    cat = open_catalog(cfg, tgt)
    bad = 0
    for mode in I.BUILDERS:
        p = I.Params(mode=mode, prompt="test", seed=1)
        try:
            nodes, info = I.build(p, cat)
            probs = I.validate(nodes, cat.object_info) if cat.object_info else []
            tag = "OK  " if not probs and not info["warnings"] else "WARN"
            print(f"[{tag}] {mode:<10} {len(nodes)} Nodes")
            for w in info["warnings"]:
                print("        " + w.replace("\n", "\n        "))
            for x in probs[:5]:
                print("        " + x)
            bad += bool(probs)
        except (I.Unsupported, C.ModelMissing) as e:
            bad += 1
            print(f"[FAIL] {mode:<10} {str(e)}")
    if not cat.object_info:
        print("\n[i] ComfyUI lief nicht - Nodes/Eingaben wurden NICHT geprueft, nur Modelldateien.")
    return 1 if bad else 0


# ───────────────────────────── ui ─────────────────────────────

def cmd_ui(a) -> int:
    """Start Gradio UI."""
    import mm_ui
    return mm_ui.main()


# ───────────────────────────── Parser ─────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser with subcommand handlers stored in ``fn``.

    This does not parse arguments or run a command; legacy invocation handling
    and the default video command are applied by ``main``.
    """
=== mm_common load_config / LIVE_SOURCES ===
    "prompt_file": "prompts/prompt.txt",
    "negative_file": "prompts/negative.txt",
    # Zwei ComfyUI-Installationen: Bilder / Video (wegen Node-Konflikten getrennt)
    "targets": {
        "image": {
            "url": "http://127.0.0.1:8291",
            "comfy_dir": "D:/ComfyUi2",
            "model_roots": ["D:/ComfyUi2/models", "C:/ai_diffusion/models", "D:/ComfyUiCuda/models"],
        },
        "video": {
            "url": "http://127.0.0.1:8197",
            "comfy_dir": "D:/ComfyUiVideo",
            "model_roots": ["D:/ComfyUiVideo/models", "C:/ai_diffusion/models", "D:/ComfyUiCuda/models"],
        },
    },
    "image": {
        "width": 1024,
        "height": 1024,
        "batch": 1,
        "timeout_s": 3600,
        "negative": "",
    },
    "minimax": {
        "html": "assets/minimax_h3_comfyui_local_generator.html",
        "diffusion_model": "minimax_h3_fl2va_pruned_w6a8.safetensors",
        "video_vae": "minimax_h3_video_vae_fp16",
        "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
        "text_encoder": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "lora_file": "minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors",
        "lora_strength": 0.75,
        "width": 512,
        "height": 288,
        "fps": 24,
        "default_duration": 15,
        "steps": 6,
        "cfg": 1.0,
        "sampler": "res_multistep",
        "scheduler": "simple",
        "denoise": 1.0,
        "seed_mode": "same_seed_for_all_scenes",
        "base_seed": -1,
        "batch_size": 1,
        "output_filename": "minimax_h3_final_video.mp4",
        "turbo_mode": True,
        "lora_enabled": True,
        "audio_enabled": True,
        "easycache": True,
        "sage_attention": True,
        "save_individual_scenes": False,
        "first_frame_mode": "last_frame_chain",
        "reference_mode": False,
        "keyframes": False,
        "consistency_bible": False,
        "external_tts": False,
        "skip_join": False,
        "plan_export": False,
        "generate_references": False,
        "order_lock": True,
        "subgraphs": True,
        # Szenen-Kette: laesst kein Scene aus (first_frame_mode last_frame_chain + order_lock)
        "vl_llm": "",                 # VL-LLM (Vision+Text) zum Bild-Beschreiben/Prompt-Erweitern
        "vl_llm_auto": True,          # VL-LLM automatisch suchen und einbinden
        "vl_max_tokens": 512,         # maximale Antwortlaenge des VL-LLM
        "negative_prompt": (
            "low quality, blurry, distorted faces, extra limbs, watermark, text, flickering, "
            "jitter, bad anatomy, oversaturated, noisy, artifacts"
        ),
    },
    # LTX-Video 2.3 / 2.5 (ComfyUI-LTXVideo; laeuft in der Video-ComfyUI)
    "ltx": {
        "diffusion_model_23": "",     # leer = automatisch suchen (ltx-2.3*)
        "diffusion_model_25": "",     # leer = automatisch suchen (ltx-2.5* / ltxv25*)
        "turbo_lora_23": "",          # leer = automatisch (distill/turbo/lightx2v ... 2.3)
        "turbo_lora_25": "",          # leer = automatisch (ltx25_turbo*, distill ... 2.5)
        "text_encoder": "",           # GGUF/Safetensors; leer = Gemma-Automatik
        "clip_vision": "",            # nur 2.3 (ImageOnlyReferenceEncode); leer = Automatik
        "video_vae": "",              # leer = automatisch
        "audio_vae": "",              # nur 2.5 mit Ton; leer = automatisch
        "latents_upscaler": "",       # latent_upscale_models; leer = automatisch
        "width": 768,
        "height": 512,
        "fps": 25,
        "default_duration": 6,        # Sekunden pro Scene
        "steps": 30,                  # ohne Turbo
        "turbo_steps": 8,             # mit Turbo-LoRA
        "cfg": 1.0,                   # LTXVGuideConditioner arbeitet mit guidance
        "guidance": 1.03,
        "refine": 0.3,                # Detail-LoRA-Denoise (0 = aus)
        "seed": -1,
        "output_filename": "ltx_final_video.mp4",
        "vl_llm": "",                 # VL-LLM im Workflow (beschreibt den letzten Frame)
        "vl_llm_auto": True,
        "vl_max_tokens": 512,
        "negative_prompt": (
            "low quality, blurry, distorted faces, extra limbs, watermark, text, flickering, "
            "jitter, bad anatomy, oversaturated, noisy, artifacts"
        ),
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    cfg_path = Path(os.environ.get("MM_CONFIG", ROOT / "config.json"))
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if cfg_path.exists():
        try:
            cfg = _deep_merge(cfg, json.loads(read_text(cfg_path)))
        except Exception as e:  # kaputte config soll das Tool nicht killen
            print(f"[!] config.json konnte nicht gelesen werden ({e}) - nutze Standardwerte", file=sys.stderr)
    if os.environ.get("MM_OUTPUT_DIR"):
        cfg["output_dir"] = os.environ["MM_OUTPUT_DIR"]
    for name, env in (("image", "MM_IMAGE_URL"), ("video", "MM_VIDEO_URL")):
        if os.environ.get(env):
            cfg["targets"][name]["url"] = os.environ[env]
    if os.environ.get("MM_MODEL_ROOTS"):
        roots = [r for r in os.environ["MM_MODEL_ROOTS"].split(os.pathsep) if r]
        for t in cfg["targets"].values():
            t["model_roots"] = roots
    return cfg


def abspath(p: str | Path) -> Path:
    s = os.path.expandvars(os.path.expanduser(str(p)))
    q = Path(s)
    return q if q.is_absolute() else (ROOT / q)



Status Code: 0
Tracing exit codes through command-line handler functions.

Marking certain modes as intentionally skipped rather than failed.

Drafting new image-generation graphs with exact workflow parameters.

Writing helper functions to resolve node parameter options.

Assembling the base loader graph with turbo and lora logic.

Listing required nodes and models for each workflow mode.

Patching loader code with new MOSS wrapper functions.

Extending the interface to support new generation options.

Rewiring generation outputs to chain enhancer into image mode.

Drafting the mm_moss module implementation plan and backups

Anfrage
{
  "command": "cd D:\\claudeAgent\\CWBuilder\n$bk = \"D:\\claudeAgent\\CWBuilder\\_dev\\backup_20261019\"\nNew-Item -ItemType Directory -Force -Path $bk | Out-Null\nforeach ($f in 'src\\mm_images.py','src\\mm.py','src\\mm_ui.py','src\\mm_common.py','config.json','start.bat','ui.bat','Start_Qwen3_VL_4B_Vision.bat','requirements.txt','tests\\test_install.py','tests\\test_windows_launchers.py','README.md') { if (Test-Path $f) { $dst = Join-Path $bk ($f -replace '[\\\\/]','__'); Copy-Item $f $dst -Force } }\n\"Backups: $((Get-ChildItem $bk | Measure-Object).Count) Dateien in $bk\"\n\"=== LIVE_SOURCES / KIND_DIRS ===\"; Select-String -Path src\\mm_common.py -Pattern 'LIVE_SOURCES|KIND_DIRS|EXTS|SEP' | Select-Object -First 8 | ForEach-Object { \"$($_.LineNumber): $($_.Line.Trim())\" }\n$c = Get-Content src\\mm_common.py -Encoding UTF8\n$i = ($c | Select-String -Pattern '^LIVE_SOURCES').LineNumber; $c[($i-1)..($i+22)]\n\"=== combo_options ===\"; $j = ($c | Select-String -Pattern '^def combo_options').LineNumber; $c[($j-1)..($j+11)]\n\"=== crop/scale-Nodes: Signaturen ===\"\n$tmp = Join-Path $env:TEMP 'cwb_phase0'\n$py = @'\nimport json, os\noi = json.load(open(os.path.join(os.environ[\"TEMP\"], \"cwb_phase0\", \"object_info.json\"), encoding=\"utf-8\"))\ndef short(v):\n    o = v[0]\n    if isinstance(o, list): return \"COMBO\" + str(o[:5])\n    if o == \"COMBO\": return \"COMBO\" + str((v[1] or {}).get(\"options\", [])[:5])\n    d = v[1].get(\"default\") if len(v) > 1 and isinstance(v[1], dict) else None\n    return f\"{o}\" + (f\"={d}\" if d is not None else \"\")\nfor c in [\"MaskToImage\",\"ImageCompositeMasked\",\"ImageScaleToTotalPixels\",\"GetImageSize\",\"ImageScale\",\"CLIPTextEncode\",\"VAELoader\",\"MOSSImageUNETLoader\",\"MOSSImageCLIPLoader\"]:\n    n = oi.get(c)\n    if not n: print(\"##\", c, \"FEHLT\"); continue\n    print(\"##\", c, n.get(\"output\"))\n    for sec in (\"required\", \"optional\"):\n        for k, v in (n[\"input\"].get(sec) or {}).items():\n            if k in (\"image\",\"clip_name\",\"unet_name\",\"vae_name\") and v[0] == \"COMBO\": print(\"   \", sec[0], k, \"COMBO...\")\n            else: print(\"   \", sec[0], k, short(v))\nks = oi[\"KSampler\"][\"input\"][\"required\"][\"sampler_name\"]\nopts = ks[0] if isinstance(ks[0], list) else ks[1][\"options\"]\nprint(\"er_sde in KSampler:\", \"er_sde\" in opts, \"| euler:\", \"euler\" in opts)\nprint(\"scheduler normal/simple:\", [x for x in (oi[\"KSampler\"][\"input\"][\"required\"][\"scheduler\"][0] if isinstance(oi[\"KSampler\"][\"input\"][\"required\"][\"scheduler\"][0], list) else oi[\"KSampler\"][\"input\"][\"required\"][\"scheduler\"][1][\"options\"]) if x in (\"normal\",\"simple\")])\nprint(\"SeedVR2 DiT-Liste:\", (lambda v: v[0] if isinstance(v[0], list) else v[1][\"options\"])(oi[\"SeedVR2LoadDiTModel\"][\"input\"][\"required\"][\"model\"]))\nprint(\"Ultralytics bbox:\", (lambda v: v[0] if isinstance(v[0], list) else v[1][\"options\"])(oi[\"UltralyticsDetectorProvider\"][\"input\"][\"required\"][\"model_name\"]))\n'@\nSet-Content -LiteralPath \"$tmp\\sig2.py\" -Value $py -Encoding UTF8\n& 'C:\\Users\\Startklar\\AppData\\Local\\Programs\\Python\\Python312\\python.exe' -X utf8 -I \"$tmp\\sig2.py\" 2>&1 | ForEach-Object { \"$_\" }",
  "timeout": 60
}
Antwort
Response: Backups: 12 Dateien in D:\claudeAgent\CWBuilder\_dev\backup_20261019
=== LIVE_SOURCES / KIND_DIRS ===
150: roots = [r for r in os.environ["MM_MODEL_ROOTS"].split(os.pathsep) if r]
264: KIND_DIRS = {
275: EXTS = {".safetensors", ".sft", ".gguf", ".pth", ".pt", ".ckpt", ".bin"}
276: SEP = "\\" if os.name == "nt" else "/"
279: LIVE_SOURCES = {
318: for kind, (cls, inp) in LIVE_SOURCES.items():
335: for sub in KIND_DIRS[kind]:
341: if Path(f).suffix.lower() not in EXTS:
LIVE_SOURCES = {
    "unet": ("UNETLoader", "unet_name"),
    "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
    "text_encoders": ("CLIPLoader", "clip_name"),
    "vae": ("VAELoader", "vae_name"),
    "loras": ("LoraLoaderModelOnly", "lora_name"),
    "controlnet": ("ControlNetLoader", "control_net_name"),
    "model_patches": ("ModelPatchLoader", "name"),
}


class ModelMissing(Exception):
    pass


def combo_options(spec) -> list | None:
    """Liest die Auswahlliste aus einem object_info-Eintrag (altes + neues Format)."""
    if not spec:
        return None
    first = spec[0]
    if isinstance(first, list):
        return first
    if first == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        return spec[1].get("options")
=== combo_options ===
def combo_options(spec) -> list | None:
    """Liest die Auswahlliste aus einem object_info-Eintrag (altes + neues Format)."""
    if not spec:
        return None
    first = spec[0]
    if isinstance(first, list):
        return first
    if first == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        return spec[1].get("options")
    return None


class Catalog:
=== crop/scale-Nodes: Signaturen ===
## MaskToImage ['IMAGE']
    r mask MASK
## ImageCompositeMasked ['IMAGE']
    r destination IMAGE
    r source IMAGE
    r x INT=0
    r y INT=0
    r resize_source BOOLEAN=False
    o mask MASK
## ImageScaleToTotalPixels ['IMAGE']
    r image IMAGE
    r upscale_method COMBO['nearest-exact', 'bilinear', 'area', 'bicubic', 'lanczos']
    r megapixels FLOAT=1.0
    r resolution_steps INT=1
## GetImageSize ['INT', 'INT', 'INT']
    r image IMAGE
## ImageScale ['IMAGE']
    r image IMAGE
    r upscale_method COMBO['nearest-exact', 'bilinear', 'area', 'bicubic', 'lanczos']
    r width INT=512
    r height INT=512
    r crop COMBO['disabled', 'center']
## CLIPTextEncode ['CONDITIONING']
    r text STRING
    r clip CLIP
## VAELoader ['VAE']
    r vae_name COMBO['Flux2AnimeVAE.safetensors', 'LTX23_audio_vae_bf16.safetensors', 'LTX23_video_vae_bf16.safetensors', 'LTX2_audio_vae_bf16.safetensors', 'MMaudio_vae\\diffusion_pytorch_model.safetensors']
## MOSSImageUNETLoader ['MODEL']
    r unet_name COMBO...
    r weight_dtype COMBO['default', 'bf16', 'fp32', 'fp8_e4m3fn', 'fp8_e4m3fn_fast']
## MOSSImageCLIPLoader ['CLIP']
    r clip_name COMBO...
    r device COMBO['default', 'cpu']
er_sde in KSampler: True | euler: True
scheduler normal/simple: ['simple', 'normal']
SeedVR2 DiT-Liste: ['seedvr2_ema_3b-Q4_K_M.gguf', 'seedvr2_ema_3b-Q8_0.gguf', 'seedvr2_ema_3b_fp8_e4m3fn.safetensors', 'seedvr2_ema_3b_fp16.safetensors', 'seedvr2_ema_7b-Q4_K_M.gguf', 'seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors', 'seedvr2_ema_7b_fp16.safetensors', 'seedvr2_ema_7b_sharp-Q4_K_M.gguf', 'seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors', 'seedvr2_ema_7b_sharp_fp16.safetensors']
Ultralytics bbox: ['bbox/2DCockAndBallYolo8x.pt', 'bbox/Eyes.pt', 'bbox/assdetailer-seg.pt', 'bbox/face_yolov8m.pt', 'bbox/female_breast-v4.2.pt', 'bbox/hand_yolov8s.pt', 'bbox/hand_yolov9c.pt', 'bbox/pussy_best_v3.pt', 'bbox/pussy_last_v3.pt', 'bbox/unwanted-3x.pt', 'segm/PitEyeDetailer-v2-seg.pt', 'segm/PitHandDetailer-v1-seg.pt', 'segm/apanzhcbreastssegv11024m.pt', 'segm/assdetailer-seg.pt', 'segm/face_yolov8m-seg_60.pt', 'segm/face_yolov8n-seg2_60.pt', 'segm/hair_yolov8n-seg_60.pt', 'segm/hand_yolov8s.pt', 'segm/person_yolov8m-seg.pt', 'segm/person_yolov8s-seg.pt']

Status Code: 0
