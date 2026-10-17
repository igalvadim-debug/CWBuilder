# -*- coding: utf-8 -*-
"""Gemeinsame Helfer: Konfiguration, Pfade, Modell-Katalog, Prompt-Laden, HTTP.

Alle Pfade werden relativ zum Projektordner (ROOT) aufgeloest, damit der
komplette Ordner beliebig verschoben/kopiert werden kann.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ───────────────────────────── Konfiguration ─────────────────────────────

DEFAULT_CONFIG: dict = {
    "output_dir": "output",
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


def target(cfg: dict, name: str) -> dict:
    t = dict(cfg["targets"][name])
    t["name"] = name
    t["comfy_dir"] = abspath(t["comfy_dir"]) if t.get("comfy_dir") else None
    t["model_roots"] = [abspath(r) for r in t.get("model_roots", [])]
    return t


def output_dir(cfg: dict) -> Path:
    d = abspath(cfg["output_dir"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


# ───────────────────────────── Textdateien ─────────────────────────────

def read_text(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _newest(paths):
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def resolve_prompt(cfg: dict, text: str | None = None, file: str | None = None) -> tuple[str, str]:
    """Liefert (prompt, quelle). Der GESAMTE Text der Datei wird uebernommen."""
    if text and text.strip():
        return text.strip(), "Kommandozeile"
    if file:
        p = Path(file.strip('"'))
        if not p.is_absolute():
            p = Path.cwd() / p if (Path.cwd() / p).exists() else ROOT / p
        if not p.exists():
            raise SystemExit(f"[!] Prompt-Datei nicht gefunden: {p}")
        t = read_text(p).strip()
        if not t:
            raise SystemExit(f"[!] Prompt-Datei ist leer: {p}")
        return t, str(p)
    neg = abspath(cfg["negative_file"]).resolve()
    cands: list[Path] = [abspath(cfg["prompt_file"])]
    pdir = ROOT / "prompts"
    if pdir.is_dir():
        cands += _newest(pdir.glob("*.txt"))
    cands += _newest(Path.cwd().glob("*.txt"))
    for c in cands:
        try:
            if c.exists() and c.resolve() != neg:
                t = read_text(c).strip()
                if t:
                    return t, str(c)
        except OSError:
            continue
    raise SystemExit(
        "[!] Kein Prompt gefunden. Schreibe ihn in prompts\\prompt.txt, "
        "uebergib --prompt \"Text\" oder ziehe eine .txt-Datei auf die .bat."
    )


def resolve_negative(cfg: dict, override: str | None = None) -> str:
    if override is not None:
        return override
    p = abspath(cfg["negative_file"])
    if p.exists():
        return read_text(p).strip()
    return cfg["image"].get("negative", "")


# ───────────────────────────── HTTP ─────────────────────────────

def http_json(url: str, data: dict | None = None, timeout: float = 15):
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def server_alive(url: str, timeout: float = 2.5) -> bool:
    try:
        http_json(url.rstrip("/") + "/system_stats", timeout=timeout)
        return True
    except Exception:
        return False


# ───────────────────────────── Modell-Katalog ─────────────────────────────

KIND_DIRS = {
    "unet": ("diffusion_models", "unet"),
    "checkpoints": ("checkpoints",),
    "text_encoders": ("text_encoders", "clip"),
    "vae": ("vae",),
    "loras": ("loras",),
    "controlnet": ("controlnet",),
    "model_patches": ("model_patches",),
    # Flux 3 Prompt-Upsampler (LLM, safetensors oder gguf) - via ChatGPT/LLMLoaderNodes
    "llm": ("LLM", "text_enchancer", "diffusion_llms", "large_language_model"),
}
EXTS = {".safetensors", ".sft", ".gguf", ".pth", ".pt", ".ckpt", ".bin"}
SEP = "\\" if os.name == "nt" else "/"

# object_info: (Node-Klasse, Eingabename) je Modell-Art
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
    return None


class Catalog:
    """Welche Modelldateien sieht die Ziel-ComfyUI? (Platte oder live per API)"""

    def __init__(self, roots, url: str | None = None, prefer_live: bool = True):
        self.roots = [Path(r) for r in roots if Path(r).is_dir()]
        self.url = url
        self._names: dict[str, list[str]] = {}
        self.live_ok = False
        self.object_info: dict | None = None
        if prefer_live and url and server_alive(url):
            try:
                self.object_info = http_json(url.rstrip("/") + "/object_info", timeout=120)
                for kind, (cls, inp) in LIVE_SOURCES.items():
                    node = self.object_info.get(cls)
                    if not node:
                        continue
                    req = node.get("input", {}).get("required", {})
                    opts = combo_options(req.get(inp))
                    if opts is not None:
                        self._names[kind] = list(opts)
                self.live_ok = True
            except Exception:
                self.object_info = None

    def names(self, kind: str) -> list[str]:
        if kind in self._names:
            return self._names[kind]
        seen: dict[str, str] = {}
        for root in self.roots:
            for sub in KIND_DIRS[kind]:
                base = root / sub
                if not base.is_dir():
                    continue
                for dp, _dn, fns in os.walk(base):
                    for f in fns:
                        if Path(f).suffix.lower() not in EXTS:
                            continue
                        rel = os.path.relpath(os.path.join(dp, f), base).replace("\\", "/").replace("/", SEP)
                        seen.setdefault(rel.lower(), rel)
        self._names[kind] = sorted(seen.values(), key=str.lower)
        return self._names[kind]

    def pick(self, kind: str, candidates, *, ext: str | None = None, required: bool = True) -> str | None:
        cands = [c for c in candidates if c]
        names = self.names(kind)
        names_e = [n for n in names if n.lower().endswith(ext)] if ext else names
        for cand in cands:  # 1) exakter Treffer (Name / Dateiname / ohne Endung)
            c = cand.lower()
            for n in names_e:
                nl = n.lower()
                base = nl.replace("\\", "/").split("/")[-1]
                if c in (nl, base, base.rsplit(".", 1)[0]):
                    return n
        for cand in cands:  # 2) Teilstring, kuerzester Name gewinnt
            c = cand.lower()
            hits = sorted((n for n in names_e if c in n.lower()), key=len)
            if hits:
                return hits[0]
        if required:
            raise ModelMissing(self._explain(kind, cands))
        return None

    def _explain(self, kind: str, cands) -> str:
        toks = set()
        for c in cands:
            toks.update(t for t in re.split(r"[^a-z0-9]+", c.lower()) if len(t) >= 4)
        similar = [n for n in self.names(kind) if any(t in n.lower() for t in toks)][:8]
        where = ", ".join(str(r) for r in self.roots) or "(keine Modell-Ordner gefunden - config.json pruefen)"
        msg = f"Modell nicht gefunden [{kind}]: gesucht {cands[0] if cands else '?'}"
        if len(cands) > 1:
            msg += f" (oder: {', '.join(cands[1:3])})"
        msg += f"\n      Suchpfade: {where}"
        if similar:
            msg += "\n      Aehnliche Dateien: " + "; ".join(similar)
        return msg
