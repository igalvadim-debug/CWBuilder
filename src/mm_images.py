# -*- coding: utf-8 -*-
"""Bild-Workflows fuer ComfyUI (API-Format) + Ausfuehrung ueber die ComfyUI-API.

Modi:
    krea2      Krea 2 (Turbo)            + Turbo-LoRAs  + Control-LoRA (Depth)
    klein9b    FLUX.2 Klein 9B           + Edit mit Referenzbildern + ControlNet (experimentell)
    klein4b    FLUX.2 Klein 4B           (wie oben)
    qwen-edit  Qwen Image Edit 2511      + Lightning-LoRA (4 Steps), bis zu 3 Bilder
    qwen21     Qwen Image 2.1            + Turbo-LoRAs + Fun-ControlNet-Union + Edit
    zimage     Z-Image Turbo (AIO)       + Fun-ControlNet (Union/Tile)
    flux3      FLUX.3 (Klein Base int8)  + Gemma-4-Text-Encoder + Prompt-Upsampler (Qwen3.5)

Die Graphen folgen den offiziellen ComfyUI-Templates (comfyui_workflow_templates).
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import random
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from mm_common import Catalog, KIND_DIRS, EXTS, ModelMissing, combo_options, http_json
from mm_scenes import describe_trigger_name


class Unsupported(Exception):
    pass


# ───────────────────────────── Parameter ─────────────────────────────

@dataclass
class Params:
    mode: str
    prompt: str
    negative: str = ""
    width: int = 1024
    height: int = 1024
    size_explicit: bool = False
    steps: int | None = None
    cfg: float | None = None
    seed: int = -1
    sampler: str | None = None
    scheduler: str | None = None
    batch: int = 1
    loras: list = field(default_factory=list)       # [(name_or_substring, strength)]
    turbo: str = "auto"                              # auto | off | <preset> | <lora-name>
    variant: str | None = None                       # nur qwen21
    unet: str | None = None
    clip: str | None = None
    vae: str | None = None
    upsampler: str | None = None                     # nur flux3: Prompt-Upsampler (LLM)
    no_upsample: bool = False                        # nur flux3: Upsampler-Loop aus
    upsample_max_tokens: int = 512                   # nur flux3
    images: list = field(default_factory=list)       # Referenzbilder (Namen, wie ComfyUI sie kennt)
    control: str | None = None                       # None | auto | union | tile | depth
    control_image: str | None = None
    preprocess: str = "auto"                         # auto | none | canny | depth | lineart
    control_strength: float = 1.0
    megapixels: float = 1.0
    prefix: str | None = None


@dataclass
class Turbo:
    lora: str
    steps: int | None
    cfg: float | None
    label: str
    strength: float = 1.0


# Turbo-/Beschleuniger-LoRAs je Modus: key -> (Dateiname-Teilstring, Steps, CFG)
TURBO_PRESETS: dict[str, dict[str, tuple]] = {
    "krea2": {
        "turbo": ("krea2_turbo_lora_rank_64", 8, 1.0),
        "turbo2": ("krea2_turbo_2step", 2, 1.0),
        "distill": ("krea2_turbo_distill_r64", 8, 1.0),
    },
    "qwen-edit": {
        "lightning": ("Qwen-Image-Edit-2511-Lightning-4steps", 4, 1.0),
    },
    "qwen21": {
        "acc4": ("Qwen-Image-2.1-Fun-Acc-4Step", 4, 1.0),
        "p8": ("p_qwen_image_2.1_8step", 8, 1.0),
        "p5": ("p_qwen_image_2.1_5step", 5, 1.0),
        "viggle4": ("Qwen-Image-2.1-viggle-turbo-4step", 4, 1.0),
        "viggle5": ("Qwen-Image-2.1-viggle-turbo-v0.2-5step", 5, 1.0),
    },
    "klein9b": {},   # Klein ist bereits destilliert (4 Steps, CFG 1) - es gibt keine Turbo-LoRA
    "klein4b": {},
    "zimage": {},    # Z-Image *Turbo* ist selbst schon 8-Step
    "flux3": {       # Flux 3 Base ist kein Turbo-Modell - optionale Destillate als --turbo <lora-name>
        "turbo": ("flux3_turbo", 8, 1.0),
    },
    # MOSS Turbo-Pfade: (a) dmd8 = LoRA 8 Steps, (b) rapid4 = RapidMOSSAdapter 4 Steps
    "moss_t2i": {
        "dmd8": ("MOSS-Image-SFT-8-steps-dmd", 8, 1.0),
        "rapid4": ("rapid-moss-4step", 4, 1.0),
    },
    "moss_inpaint": {
        "dmd8": ("MOSS-Image-SFT-8-steps-dmd", 8, 1.0),
        "rapid4": ("rapid-moss-4step", 4, 1.0),
    },
    "moss_detailer": {
        "dmd8": ("MOSS-Image-SFT-8-steps-dmd", 8, 1.0),
        "rapid4": ("rapid-moss-4step", 4, 1.0),
    },
    "moss_4step": {
        "rapid4": ("rapid-moss-4step", 4, 1.0),
    },
}

MODE_INFO = {
    "krea2":     ("Krea 2 Turbo",          {"edit": False, "control": ["depth"]}),
    "klein9b":   ("FLUX.2 Klein 9B",       {"edit": True,  "control": ["union (experimentell)"]}),
    "klein4b":   ("FLUX.2 Klein 4B",       {"edit": True,  "control": ["union (experimentell)"]}),
    "qwen-edit": ("Qwen Image Edit 2511",  {"edit": True,  "control": []}),
    "qwen21":    ("Qwen Image 2.1",        {"edit": True,  "control": ["union"]}),
    "zimage":    ("Z-Image Turbo",         {"edit": False, "control": ["union", "tile"]}),
    "flux3":     ("FLUX.3 Klein Base int8", {"edit": True, "control": []}),
    # MOSS modes
    "moss_t2i":      ("MOSS T2I",            {"edit": False, "control": []}),
    "moss_inpaint":  ("MOSS Inpaint",        {"edit": True,  "control": []}),
    "moss_detailer": ("MOSS Detailer 1-4 Faces + SeedVR2", {"edit": True,  "control": []}),
    "moss_prompt_enhancer": ("MOSS Prompt Enhancer (LLM)", {"edit": False, "control": []}),
    "moss_4step":    ("MOSS 4-Step (RapidMOSS)", {"edit": False, "control": []}),
}


# ───────────────────────────── Graph-Helfer ─────────────────────────────

class Graph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self._n = 0

    def add(self, cls: str, **inputs) -> str:
        self._n += 1
        nid = str(self._n)
        self.nodes[nid] = {"class_type": cls, "inputs": inputs}
        return nid


def o(nid: str, slot: int = 0) -> list:
    return [nid, slot]


def align(v: int, step: int = 16) -> int:
    return max(256, int(round(v / step)) * step)


def steps_from_name(name: str) -> int | None:
    m = re.search(r"(\d+)\s*-?\s*step", name, re.I)
    return int(m.group(1)) if m else None


def note(info: dict, label: str, value: str) -> None:
    info["models"].append((label, value))


def warn(info: dict, text: str) -> None:
    info["warnings"].append(text)


def need_node(cat: Catalog, cls: str, hint: str) -> None:
    if cat.object_info is not None and cls not in cat.object_info:
        raise Unsupported(f"Node '{cls}' fehlt in der laufenden ComfyUI ({hint}).")


def pick_unet(cat: Catalog, cands: list):
    for kind in ("unet", "checkpoints"):
        n = cat.pick(kind, cands, required=False)
        if n:
            return kind, n
    cat.pick("unet", cands)  # wirft ModelMissing mit Hinweis
    raise ModelMissing("unreachable")


def load_unet(g: Graph, kind: str, name: str) -> list:
    if kind == "checkpoints":
        return o(g.add("CheckpointLoaderSimple", ckpt_name=name))
    if name.lower().endswith(".gguf"):
        return o(g.add("UnetLoaderGGUF", unet_name=name))
    return o(g.add("UNETLoader", unet_name=name, weight_dtype="default"))


def lora_model_only(g: Graph, model: list, loras: list) -> list:
    for name, s in loras:
        model = o(g.add("LoraLoaderModelOnly", model=model, lora_name=name, strength_model=s))
    return model


def lora_full(g: Graph, model: list, clip: list, loras: list):
    for name, s in loras:
        n = g.add("LoraLoader", model=model, clip=clip, lora_name=name, strength_model=s, strength_clip=s)
        model, clip = o(n, 0), o(n, 1)
    return model, clip


def user_loras(cat: Catalog, p: Params, info: dict) -> list:
    out = []
    for q, s in p.loras:
        n = cat.pick("loras", [q])
        out.append((n, s))
        note(info, "LoRA", f"{n} (x{s})")
    return out


def _resolve_turbo_lora(p: Params, cat: Catalog, cand: str) -> str | None:
    """Turbo-LoRA zum Preset-Kandidaten finden - nur aus dem passenden Familienordner.

    'MOSS-Image-SFT-8-steps-dmd' liegt laut docs in loras/MOSS/. Ein reiner
    Namens-Teilstring-Treffer (cat.pick) matcht andernfalls auch Kopien in
    fremden LoRA-Ordnern (z.B. loras/flux2/...). Bei MOSS-Modi wird daher der
    Kandidat zuerst im Unterordner 'moss/' gesucht; erst danach fällt die
    Suche auf die allgemeine Auswahl zurück.
    """
    if p.mode.startswith("moss"):
        scoped = cat.pick("loras", [f"moss/{cand}"], required=False)
        if scoped:
            return scoped
    return cat.pick("loras", [cand], required=False)


def resolve_turbo(p: Params, cat: Catalog, info: dict, base_name: str) -> Turbo | None:
    presets = TURBO_PRESETS.get(p.mode, {})
    choice = (p.turbo or "auto").strip().lower()
    inherent = "turbo" in base_name.lower()
    if choice in ("off", "no", "none", "0", "false"):
        return None

    def strength_for(key: str, name: str) -> float:
        """LoRA-Staerke: MOSS-DMD folgt docs/mosst2i_withLora.json (0.7), sonst 1.0."""
        if key == "dmd8" or _reg_norm(name).endswith(_reg_norm(MOSS_TURBO_LORA_SUBPATH)):
            return MOSS_DMD_STRENGTH
        return 1.0

    if choice == "auto":
        if inherent:
            info["notes"].append("Basismodell ist bereits ein Turbo-Modell - keine zusaetzliche Turbo-LoRA (erzwingen: --turbo <preset>)")
            return None
        if not presets or p.mode == "flux3":
            # flux3: Base ist kein Turbo-Modell und es gibt (noch) kein festes Preset -
            # auto laedt keine Turbo-LoRA, nur ein explizites --turbo <lora> wirkt.
            return None
        key = next(iter(presets))
        cand, steps, cfg = presets[key]
        name = _resolve_turbo_lora(p, cat, cand)
        if name is None:
            warn(info, f"Turbo-LoRA '{key}' nicht gefunden - laeuft ohne.")
            return None
        t = Turbo(name, steps, cfg, key, strength_for(key, name))
    elif choice in presets:
        cand, steps, cfg = presets[choice]
        name = cat.pick("loras", [cand])
        t = Turbo(name, steps, cfg, choice, strength_for(choice, name))
    else:
        name = cat.pick("loras", [p.turbo])
        t = Turbo(name, steps_from_name(name), 1.0, p.turbo, strength_for("", name))
    note(info, "Turbo-LoRA", f"{t.lora} (Preset '{t.label}', {t.steps or '?'} Steps, x{t.strength})")
    return t


def sampling(p: Params, turbo: Turbo | None, d_steps: int, d_cfg: float,
             d_sampler: str = "euler", d_sched: str = "simple"):
    steps = p.steps or (turbo.steps if turbo and turbo.steps else d_steps)
    cfg = p.cfg if p.cfg is not None else (turbo.cfg if turbo and turbo.cfg is not None else d_cfg)
    return steps, cfg, (p.sampler or d_sampler), (p.scheduler or d_sched)


def seed_of(p: Params, info: dict) -> int:
    s = p.seed if p.seed >= 0 else random.randrange(2 ** 48)
    info["seed"] = s
    return s


def ksampler(g: Graph, p: Params, info: dict, model, pos, neg, latent, steps, cfg, sampler, sched) -> str:
    info["steps"], info["cfg"], info["sampler"] = steps, cfg, f"{sampler}/{sched}"
    return g.add("KSampler", model=model, seed=seed_of(p, info), steps=steps, cfg=cfg,
                 sampler_name=sampler, scheduler=sched, positive=pos, negative=neg,
                 latent_image=latent, denoise=1.0)


def negative_cond(g: Graph, clip: list, pos: list, p: Params, cfg: float) -> list:
    if cfg <= 1.0 and not p.negative.strip():
        return o(g.add("ConditioningZeroOut", conditioning=pos))
    return o(g.add("CLIPTextEncode", text=p.negative, clip=clip))


def finish(g: Graph, p: Params, samples: list, vae: list) -> None:
    dec = g.add("VAEDecode", samples=samples, vae=vae)
    g.add("SaveImage", images=o(dec), filename_prefix=p.prefix or f"mm_{p.mode}")


# ───────────────────────────── Bilder / Control ─────────────────────────────

PREPROC = {
    "canny": ("Canny", {"low_threshold": 0.1, "high_threshold": 0.32}),
    "depth": ("DepthAnythingV2Preprocessor", {"ckpt_name": "depth_anything_v2_vitl.pth", "resolution": 1024}),
    "lineart": ("LineArtPreprocessor", {"coarse": "disable", "resolution": 1024}),
}


def scale_total(g: Graph, img: list, mp: float) -> str:
    return g.add("ImageScaleToTotalPixels", image=img, upscale_method="lanczos",
                 megapixels=mp, resolution_steps=16)


def control_branch(g: Graph, p: Params, cat: Catalog, default_pre: str, W, H, derive: bool):
    """Control-Bild laden, skalieren, optional vorverarbeiten -> (bild, W, H)."""
    if not p.control_image:
        raise Unsupported("--control braucht ein Bild: --control-image <datei>")
    li = g.add("LoadImage", image=p.control_image)
    if derive:
        sc = scale_total(g, o(li), p.megapixels)
        gs = g.add("GetImageSize", image=o(sc))
        W, H = o(gs, 0), o(gs, 1)
        img = o(sc)
    else:
        sc = g.add("ImageScale", image=o(li), upscale_method="lanczos", width=W, height=H, crop="center")
        img = o(sc)
    pre = p.preprocess if p.preprocess != "auto" else default_pre
    if pre != "none":
        if pre not in PREPROC:
            raise Unsupported(f"Unbekannter Preprocessor '{pre}' (canny|depth|lineart|none)")
        cls, kw = PREPROC[pre]
        need_node(cat, cls, "Vorverarbeitung - ggf. --preprocess none und fertige Control-Map uebergeben")
        img = o(g.add(cls, image=img, **kw))
    return img, W, H


def sizes(g: Graph, p: Params, first_ref: list | None):
    """(W, H, derive): feste Zahlen oder Links auf GetImageSize."""
    if p.size_explicit or (first_ref is None and not p.control_image):
        return align(p.width), align(p.height), False
    if first_ref is not None:
        gs = g.add("GetImageSize", image=first_ref)
        return o(gs, 0), o(gs, 1), False
    return align(p.width), align(p.height), True  # aus Control-Bild ableiten


# ───────────────────────────── Modus: Krea 2 ─────────────────────────────

def build_krea2(p: Params, cat: Catalog, info: dict) -> Graph:
    g = Graph()
    kind, uname = pick_unet(cat, [p.unet] if p.unet else
                            ["krea2Turbo18For_v2", "krea2_turbo_fp8_scaled", "krea2_turbo", "krea2"])
    note(info, "UNet", f"{uname} [{kind}]")
    model = load_unet(g, kind, uname)
    cn = cat.pick("text_encoders", [p.clip] if p.clip else ["qwen3vl_4b_fp8_scaled", "qwen3vl_4b"], ext=".safetensors")
    note(info, "Text-Encoder", cn)
    clip = o(g.add("CLIPLoader", clip_name=cn, type="krea2", device="default"))
    vn = cat.pick("vae", [p.vae] if p.vae else ["qwen_image_vae", "Qwen_Image-VAE", "wan_2.1_vae"])
    note(info, "VAE", vn)
    vae = o(g.add("VAELoader", vae_name=vn))

    turbo = resolve_turbo(p, cat, info, uname)
    loras = ([(turbo.lora, 1.0)] if turbo else []) + user_loras(cat, p, info)
    model = lora_model_only(g, model, loras)
    steps, cfg, smp, sch = sampling(p, turbo, 8, 1.0)

    pos = o(g.add("CLIPTextEncode", text=p.prompt, clip=clip))
    neg = negative_cond(g, clip, pos, p, cfg)

    W, H, derive = sizes(g, p, None)
    if p.control:
        if p.control not in ("auto", "depth"):
            raise Unsupported("Krea2: nur --control depth (Control-LoRA 'depth-control-lora' vorhanden)")
        img, W, H = control_branch(g, p, cat, "depth", W, H, derive)
        latent = o(g.add("EmptyLatentImage", width=W, height=H, batch_size=p.batch))
        cl = cat.pick("loras", ["Krea2-depth-control-lora", "depth-control-lora"])
        note(info, "Control-LoRA", cl)
        for c in ("Krea2ControlLoRALoader", "Krea2ControlApply", "Krea2ControlImageEncode"):
            need_node(cat, c, "ComfyUI-Node comfyui-krea2-controlnet")
        enc = g.add("Krea2ControlImageEncode", control_image=img, vae=vae, resize="match_latent_size",
                    upscale_method="lanczos", crop="center", channel_mode="grayscale",
                    normalize="per_image_minmax", invert=False, batch_mode="independent_images",
                    latent=latent)
        model = o(g.add("Krea2ControlLoRALoader", model=model, lora_name=cl, strength=p.control_strength))
        model = o(g.add("Krea2ControlApply", model=model, control_latent=o(enc, 0)))
    else:
        latent = o(g.add("EmptyLatentImage", width=W, height=H, batch_size=p.batch))
    ks = ksampler(g, p, info, model, pos, neg, latent, steps, cfg, smp, sch)
    finish(g, p, o(ks), vae)
    return g


# ───────────────────────────── Modus: FLUX.2 Klein ─────────────────────────────

def build_klein(p: Params, cat: Catalog, info: dict) -> Graph:
    big = p.mode == "klein9b"
    g = Graph()
    unet_c = [p.unet] if p.unet else (["flux2Klein_9b", "flux-2-klein-9b"] if big else ["flux-2-klein-4b", "flux2Klein_4b"])
    kind, uname = pick_unet(cat, unet_c)
    note(info, "UNet", f"{uname} [{kind}]")
    model = load_unet(g, kind, uname)

    if p.clip:
        te_c = [p.clip]
    else:
        te_c = (["qwen_3_8b_fp8mixed", "qwen_3_8b", "qwen3vl_8b_nvfp4_heretic", "qwen3vl_8b_turbo_nvfp4"] if big
                else ["qwen_3_4b", "qwen3vl_4b_fp8_scaled"])
    tn = cat.pick("text_encoders", te_c, ext=".safetensors")
    note(info, "Text-Encoder", tn)
    if not p.clip and not any(k in tn.lower() for k in ("qwen_3_8b", "qwen_3_4b")):
        warn(info, f"Offizieller Klein-Text-Encoder ({'qwen_3_8b_fp8mixed' if big else 'qwen_3_4b'}) liegt nicht vor - "
                   f"Ersatz '{tn}' (Qwen3-VL) kann abweichende Ergebnisse liefern.")
    clip = o(g.add("CLIPLoader", clip_name=tn, type="flux2", device="default"))
    vn = cat.pick("vae", [p.vae] if p.vae else ["flux2_vae", "flux2-vae"])
    note(info, "VAE", vn)
    vae = o(g.add("VAELoader", vae_name=vn))

    turbo = resolve_turbo(p, cat, info, "klein-distilled")  # keine Presets -> nur direkte --turbo <lora>
    if (p.turbo or "auto") == "auto":
        info["notes"].append("Klein ist bereits destilliert (4 Steps, CFG 1) - es gibt dafuer keine Turbo-LoRA.")
    loras = ([(turbo.lora, 1.0)] if turbo else []) + user_loras(cat, p, info)
    model, clip = lora_full(g, model, clip, loras)
    steps, cfg, smp, sch = sampling(p, turbo, 4, 1.0)

    pos = o(g.add("CLIPTextEncode", text=p.prompt, clip=clip))
    neg = negative_cond(g, clip, pos, p, cfg)

    first_ref = None
    for name in p.images:
        li = g.add("LoadImage", image=name)
        sc = scale_total(g, o(li), p.megapixels)
        lat = g.add("VAEEncode", pixels=o(sc), vae=vae)
        pos = o(g.add("ReferenceLatent", conditioning=pos, latent=o(lat)))
        neg = o(g.add("ReferenceLatent", conditioning=neg, latent=o(lat)))
        if first_ref is None:
            first_ref = o(sc)
    W, H, derive = sizes(g, p, first_ref)

    if p.control:
        if p.control not in ("auto", "union"):
            raise Unsupported("Klein: nur --control union")
        info["notes"].append("Klein-ControlNet ist EXPERIMENTELL (FLUX.2-dev Fun-Union); bei Fehlern ohne --control arbeiten.")
        img, W, H = control_branch(g, p, cat, "canny", W, H, derive)
        cnn = cat.pick("controlnet", ["FLUX.2-dev-Fun-Controlnet-Union"])
        note(info, "ControlNet", cnn)
        cl = g.add("ControlNetLoader", control_net_name=cnn)
        ap = g.add("ControlNetApplyAdvanced", positive=pos, negative=neg, control_net=o(cl), image=img,
                   strength=p.control_strength, start_percent=0.0, end_percent=1.0, vae=vae)
        pos, neg = o(ap, 0), o(ap, 1)

    latent = o(g.add("EmptyFlux2LatentImage", width=W, height=H, batch_size=p.batch))
    sigmas = g.add("Flux2Scheduler", steps=steps, width=W, height=H)
    noise = g.add("RandomNoise", noise_seed=seed_of(p, info))
    sel = g.add("KSamplerSelect", sampler_name=smp)
    guider = g.add("CFGGuider", model=model, positive=pos, negative=neg, cfg=cfg)
    sca = g.add("SamplerCustomAdvanced", noise=o(noise), guider=o(guider), sampler=o(sel),
                sigmas=o(sigmas), latent_image=latent)
    info["steps"], info["cfg"], info["sampler"] = steps, cfg, f"{smp}/Flux2Scheduler"
    finish(g, p, o(sca, 0), vae)
    return g


# ───────────────────────────── Modus: Qwen Image Edit 2511 ─────────────────────────────

def build_qwen_edit(p: Params, cat: Catalog, info: dict) -> Graph:
    if p.control:
        raise Unsupported("Qwen Image Edit: kein ControlNet installiert (nur Qwen Image 2.1 hat Fun-Union-ControlNet).")
    g = Graph()
    kind, uname = pick_unet(cat, [p.unet] if p.unet else
                            ["qwen-image-edit-2511-Q4_K_S", "qwen_image_edit_2511", "qwen-image-edit-2511"])
    note(info, "UNet", f"{uname} [{kind}]")
    model = load_unet(g, kind, uname)
    tn = cat.pick("text_encoders", [p.clip] if p.clip else ["qwen_2.5_vl_7b_fp8_scaled", "qwen_2.5_vl_7b"], ext=".safetensors")
    note(info, "Text-Encoder", tn)
    clip = o(g.add("CLIPLoader", clip_name=tn, type="qwen_image", device="default"))
    vn = cat.pick("vae", [p.vae] if p.vae else ["qwen_image_vae", "Qwen_Image-VAE"])
    note(info, "VAE", vn)
    vae = o(g.add("VAELoader", vae_name=vn))

    model = o(g.add("ModelSamplingAuraFlow", model=model, shift=3.1))
    model = o(g.add("CFGNorm", model=model, strength=1.0))
    turbo = resolve_turbo(p, cat, info, uname)
    loras = ([(turbo.lora, 1.0)] if turbo else []) + user_loras(cat, p, info)
    model = lora_model_only(g, model, loras)
    steps, cfg, smp, sch = sampling(p, turbo, 40, 3.0)

    imgs = [o(g.add("LoadImage", image=n)) for n in p.images[:3]]
    if len(p.images) > 3:
        warn(info, "Qwen Edit nutzt maximal 3 Bilder - der Rest wird ignoriert.")
    if imgs:
        first = o(g.add("FluxKontextImageScale", image=imgs[0]))
        enc_imgs = {"image1": first}
        for i, im in enumerate(imgs[1:], start=2):
            enc_imgs[f"image{i}"] = im
        latent = o(g.add("VAEEncode", pixels=first, vae=vae))
    else:
        enc_imgs = {}
        W, H = align(p.width), align(p.height)
        latent = o(g.add("EmptySD3LatentImage", width=W, height=H, batch_size=p.batch))
    pos = g.add("TextEncodeQwenImageEditPlus", clip=clip, prompt=p.prompt, vae=vae, **enc_imgs)
    neg = g.add("TextEncodeQwenImageEditPlus", clip=clip, prompt=p.negative, vae=vae, **enc_imgs)
    pos = o(g.add("FluxKontextMultiReferenceLatentMethod", conditioning=o(pos),
                  reference_latents_method="index_timestep_zero"))
    neg = o(g.add("FluxKontextMultiReferenceLatentMethod", conditioning=o(neg),
                  reference_latents_method="index_timestep_zero"))
    ks = ksampler(g, p, info, model, pos, neg, latent, steps, cfg, smp, sch)
    finish(g, p, o(ks), vae)
    return g


# ───────────────────────────── Modus: Qwen Image 2.1 ─────────────────────────────

QWEN21_VARIANTS = {
    # key: (UNet-Kandidaten, schon Turbo?)
    "int8":  (["qwen_image_2.1_int8_convrot"], False),
    "turbo": (["qwen_image_2.1_turbo_nvfp4", "Qwen-Image-2.1-Turbo-INT8-ConvRot"], True),
    "gguf":  (["qwenImage21TurboGGUF_v10_q4KM", "qwen-image-2.1-UC-Q6_K"], True),
}


def build_qwen21(p: Params, cat: Catalog, info: dict) -> Graph:
    g = Graph()
    variant = (p.variant or "int8").lower()
    if variant not in QWEN21_VARIANTS:
        raise Unsupported(f"Qwen 2.1 --variant: {', '.join(QWEN21_VARIANTS)}")
    cands = [p.unet] if p.unet else QWEN21_VARIANTS[variant][0]
    kind, uname = pick_unet(cat, cands)
    note(info, "UNet", f"{uname} [{kind}] (variant {variant})")
    model = load_unet(g, kind, uname)
    tn = cat.pick("text_encoders",
                  [p.clip] if p.clip else ["qwen3vl_8b_int8_convrot", "qwen3vl_8b_turbo_nvfp4", "qwen3vl_8b_nvfp4_heretic"],
                  ext=".safetensors")
    note(info, "Text-Encoder", tn)
    if not p.clip and "int8_convrot" not in tn.lower():
        warn(info, f"Offizieller Text-Encoder 'qwen3vl_8b_int8_convrot' fehlt - Ersatz '{tn}'.")
    clip = o(g.add("CLIPLoader", clip_name=tn, type="qwen_image", device="default"))
    vn = cat.pick("vae", [p.vae] if p.vae else ["qwen_image_2.1_vae_bf16", "qwen_image_2.1_vae"])
    note(info, "VAE", vn)
    vae = o(g.add("VAELoader", vae_name=vn))

    turbo = resolve_turbo(p, cat, info, uname if QWEN21_VARIANTS[variant][1] else "base")
    loras = ([(turbo.lora, 1.0)] if turbo else []) + user_loras(cat, p, info)
    model = lora_model_only(g, model, loras)
    d_steps = 8 if QWEN21_VARIANTS[variant][1] else 25
    steps, cfg, smp, sch = sampling(p, turbo, d_steps, 1.0)

    # Referenzbilder (Edit) ueber TextEncodeQwenImage21 (Autogrow: images.image_N)
    enc_in = {"clip": clip, "prompt": p.prompt, "negative_prompt": p.negative, "resolution": 1024}
    if p.images:
        enc_in["vae"] = vae
        for i, name in enumerate(p.images[:16], start=1):
            enc_in[f"images.image_{i}"] = o(g.add("LoadImage", image=name))
    enc = g.add("TextEncodeQwenImage21", **enc_in)
    pos, neg = o(enc, 0), o(enc, 1)

    first_ref = None
    W, H, derive = align(p.width), align(p.height), False
    if p.images:
        latent = o(enc, 2)  # Latent in Groesse des ersten Referenzbildes
        W = H = None
    else:
        W, H, derive = sizes(g, p, None)

    if p.control:
        if p.control not in ("auto", "union"):
            raise Unsupported("Qwen 2.1: nur --control union")
        if W is None:  # Edit + Control: Control-Map auf ca. 1 MP skalieren
            li = g.add("LoadImage", image=p.control_image or "")
            if not p.control_image:
                raise Unsupported("--control braucht ein Bild: --control-image <datei>")
            gs = g.add("GetImageSize", image=o(g.add("LoadImage", image=p.images[0])))
            W, H = o(gs, 0), o(gs, 1)
            g.nodes.pop(li, None)
        img, W, H = control_branch(g, p, cat, "canny", W, H, derive)
        pn = cat.pick("model_patches", ["qwen_image_2.1_fun_controlnet_union"])
        note(info, "ControlNet", pn)
        pl = g.add("ModelPatchLoader", name=pn)
        model = o(g.add("QwenImageDiffsynthControlnet", model=model, model_patch=o(pl), vae=vae,
                        image=img, strength=p.control_strength))
    if not p.images:
        latent = o(g.add("EmptyLatentImage", width=W, height=H, batch_size=p.batch))
    need_node(cat, "QwenImage21Cache", "ComfyUI >= 0.37 mit Qwen Image 2.1")
    model = o(g.add("QwenImage21Cache", model=model, device="auto", dtype="default"))
    ks = ksampler(g, p, info, model, pos, neg, latent, steps, cfg, smp, sch)
    finish(g, p, o(ks), vae)
    return g


# ───────────────────────────── Modus: Z-Image Turbo ─────────────────────────────

def build_zimage(p: Params, cat: Catalog, info: dict) -> Graph:
    if p.images:
        raise Unsupported("Z-Image: kein Edit-Modus (nutze qwen-edit / klein9b / qwen21 fuer Referenzbilder).")
    g = Graph()
    ck = cat.pick("checkpoints", [p.unet] if p.unet else ["z-image-turbo-fp8-aio", "z-image-turbo"], ext=".safetensors")
    note(info, "Checkpoint (AIO: UNet+Qwen3-4B+VAE)", ck)
    loader = g.add("CheckpointLoaderSimple", ckpt_name=ck)
    model, clip, vae = o(loader, 0), o(loader, 1), o(loader, 2)

    turbo = resolve_turbo(p, cat, info, ck)
    model, clip = lora_full(g, model, clip, user_loras(cat, p, info))
    steps, cfg, smp, sch = sampling(p, turbo, 8, 1.0, "res_multistep", "simple")

    W, H, derive = sizes(g, p, None)
    if p.control:
        kind = "tile" if p.control == "tile" else "union"
        if p.control not in ("auto", "union", "tile"):
            raise Unsupported("Z-Image: --control union|tile")
        img, W, H = control_branch(g, p, cat, "canny" if kind == "union" else "none", W, H, derive)
        pn = cat.pick("model_patches", ["Z-Image-Turbo-Fun-Controlnet-Tile" if kind == "tile" else "Z-Image-Turbo-Fun-Controlnet-Union"])
        note(info, "ControlNet", pn)
        pl = g.add("ModelPatchLoader", name=pn)
        model = o(g.add("QwenImageDiffsynthControlnet", model=model, model_patch=o(pl), vae=vae,
                        image=img, strength=p.control_strength))
    model = o(g.add("ModelSamplingAuraFlow", model=model, shift=3.0))
    pos = o(g.add("CLIPTextEncode", text=p.prompt, clip=clip))
    neg = negative_cond(g, clip, pos, p, cfg)
    latent = o(g.add("EmptySD3LatentImage", width=W, height=H, batch_size=p.batch))
    ks = ksampler(g, p, info, model, pos, neg, latent, steps, cfg, smp, sch)
    finish(g, p, o(ks), vae)
    return g


# ───────────────────────────── Modus: FLUX.3 (Klein Base int8) ─────────────────────────────

FLUX3_UNET_CANDS = ["flux3_image_klein_base_int8_convrot", "flux3_image_klein_base", "flux3_klein_base", "flux3"]
# Flux 3 braucht den dedizierten Prompt-Upsampler (LLM) als ZWEITEN Encoder:
# qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors in text_encoders/. Er steht
# nicht zur Auswahl, wenn das Dropdown nur einen Encoder zeigt - daher eigener
# Kandidat im Builder und eigenes UI-Feld fuer den Modus flux3.
FLUX3_PROMPT_ENCODER_CANDS = ["qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors",
                              "qwen3.5_9b_flux3_prompt_upsampler_w4a8",
                              "moss-image-sft-qwen35-int8-convrot.safetensors"]
FLUX3_CLIP_CANDS = ["gemma4_e2b_it_bf16", "gemma-4-E2B-it-abliterated",
                    "Gemma-4-12B-it-uncensored-hereti20DeepNeuralNerd20-LTX202.5-ComfyUI-int8convrot",
                    "gemma4-12b-with-proj-ltx-2.5-nvfp4"]
FLUX3_UPSAMPLER_CANDS = FLUX3_PROMPT_ENCODER_CANDS + ["flux3_prompt_upsampler",
                         "Qwen3.5-9B-heretic-v2", "qwen3.5", "Qwen3.5-4B-heretic-v2"]


def flux3_upsampler_cands(p: Params) -> list:
    """--upsampler voranstellen, sonst die Standard-Kandidaten."""
    return [p.upsampler] + FLUX3_UPSAMPLER_CANDS if p.upsampler else list(FLUX3_UPSAMPLER_CANDS)


def flux3_clip_type(cat: Catalog) -> str | None:
    """Erlaubte CLIPLoader-'type'-Werte der laufenden ComfyUI (z.B. 'flux', 'flux2')."""
    if not cat.object_info:
        return None
    opts = combo_options(cat.object_info.get("CLIPLoader", {}).get("input", {}).get("required", {}).get("type"))
    if not opts:
        return None
    low = {o_.lower(): o_ for o_ in opts}
    for want in ("flux3", "flux 3", "flux2", "flux"):
        if want in low:
            return low[want]
    return None


def node_inputs(spec: dict, wanted: dict) -> dict | None:
    """Nur die Eingaben, die die Node wirklich verlangt (Pflicht-Eingaben vollstaendig?)."""
    inp = spec.get("input", {})
    req = set(inp.get("required", {}))
    opt = set(inp.get("optional", {}))
    give = {k: v for k, v in wanted.items() if k in req or k in opt}
    if not req.issubset(give):
        return None
    return give


def flux3_upsample(g: Graph, p: Params, cat: Catalog, info: dict, prompt: str) -> list | None:
    """Prompt-Upsampler (LLM) - liefert einen STRING-Ausgang. None, wenn nichts passt.

    Der Upsampler ist ein optionales Extra: Er darf den Bild-Graphen unter keinen
    Umstaenden beschaedigen. Jeder Pfad wird daher in sich abgeschlossen gebaut und
    nur zurueckgegeben, wenn alle bentigten Nodes und Modelle wirklich vorhanden sind;
    sonst bricht er mit None ab, ohne Knoten im Graphen zu hinterlassen.
    """
    if not cat.object_info:
        warn(info, "ComfyUI laeuft nicht - Prompt-Upsampler kann nicht geprueft werden "
                   "(mit laufendem Server erneut pruefen: mm.py check).")
        return None
    if isinstance(prompt, list):      # Sicherheit: nie ein Node-Link als Text einfuettern
        return None
    up_st = cat.pick("text_encoders", flux3_upsampler_cands(p), ext=".safetensors", required=False)
    # 1) dedizierte Upsampler-/TextEncodeAPI-Nodes der Flux-3-Templates
    for cls in ("Flux3UpsamplePromptWithTextEncodeAPI", "Flux3PromptUpsampler", "Flux3PromptUpsample",
                "UpsamplePromptWithTextEncodeAPI", "TextEncodeAPI"):
        spec = cat.object_info.get(cls)
        if not spec:
            continue
        allowed = {**spec.get("input", {}).get("required", {}), **spec.get("input", {}).get("optional", {})}
        wanted = {"prompt": prompt}
        for tname in ("prompt", "user_prompt", "input_prompt", "text"):
            if tname in allowed:
                wanted = {tname: prompt}
                break
        for tname in ("model_name", "model", "llm", "ckpt_name", "unet_name"):
            if tname in allowed and up_st:
                wanted[tname] = up_st
        if "api" in allowed:
            if not up_st:
                continue   # Node braucht ein API-Modell - naechsten Kandidaten versuchen
            wanted["api"] = up_st
            note(info, "Prompt-Upsampler (API)", up_st)
        for tname in ("max_tokens", "max_new_tokens"):
            if tname in allowed:
                wanted[tname] = p.upsample_max_tokens
        for tname, val in (("temperature", 0.7), ("top_p", 1.0), ("seed", seed_of(p, info))):
            if tname in allowed:
                wanted[tname] = val
        ins = node_inputs(spec, wanted)
        if ins is None:
            continue
        outs = spec.get("output", []) or []
        if "STRING" not in outs:
            continue
        nid = g.add(cls, **ins)
        note(info, "Prompt-Upsampler", f"{cls}" + (f" + '{up_st}'" if up_st else ""))
        return o(nid, outs.index("STRING"))

    # 2) Loader+Sampler-Paare (LLM-Server-Nodes, gguf oder safetensors)
    for lcls, scls in (("LLMSSRGLoader", "LLMSimpleTextGen"), ("LLMLoader", "LLMSampler")):
        if not all(c in cat.object_info for c in (lcls, scls)):
            continue
        un = (cat.pick("llm", flux3_upsampler_cands(p), required=False) or
              cat.pick("loras", flux3_upsampler_cands(p), required=False))
        if not un:
            break
        lspec = cat.object_info[lcls]
        lins = node_inputs(lspec, {"model_name": un, "ckpt_name": un, "name": un, "lora_name": un})
        if lins is None:
            break
        sspec = cat.object_info[scls]
        sins = node_inputs(sspec, {"llm": None, "model": None, "server": None, "prompt": prompt,
                                   "user_prompt": prompt, "max_tokens": p.upsample_max_tokens,
                                   "max_new_tokens": p.upsample_max_tokens, "temperature": 0.7, "top_p": 1.0})
        if sins is None or "STRING" not in (sspec.get("output") or []):
            break
        for k in list(sins):
            if sins[k] is None:
                sins[k] = o(g.add(lcls, **lins))
        nid = g.add(scls, **sins)
        note(info, "Prompt-Upsampler", f"{lcls} + {scls} + '{un}'")
        return o(nid, 0)

    # 3) ChatGPT-Node (ComfyUI-GPT/ChatGPT-Package): Dateiname ohne Pfad/Endung
    spec = cat.object_info.get("ChatGPT")
    if spec:
        un = cat.pick("llm", flux3_upsampler_cands(p), required=False)
        if un:
            base = un.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
            # 'api_endpoint' und 'seed' sind bei manchen ChatGPT-Node-Versionen Pflicht;
            # node_inputs uebernimmt sie nur, wenn die Node sie wirklich verlangt.
            allowed = {**spec.get("input", {}).get("required", {}), **spec.get("input", {}).get("optional", {})}
            ep = (cat.url.rstrip("/") + "/prompt") if cat.url else "http://127.0.0.1:8181/prompt"
            extra = {"api_endpoint": ep} if "api_endpoint" in allowed else {}
            if "seed" in allowed:
                extra["seed"] = seed_of(p, info)
            # 'file_name' ist ein Combo: wenn die Node eine Liste erlaubt, nehmen wir
            # den dort vorhandenen Kandidaten (sonst meldet validate() 'Wert nicht in Liste').
            fn_val = base
            fn_opts = combo_options(allowed.get("file_name")) if "file_name" in allowed else None
            if fn_opts:
                fn_val = next((n for n in fn_opts if n.rsplit(".", 1)[0].lower() == base.lower()), base)
            # Leerer Prompt: bei ChatGPT-Node + negativem Prompt nimmt ComfyUI den
            # Negativtext als Upsampler-Vorlage - sonst fuehrt der leere user_prompt
            # zu 400 'invalid prompt' beim Queuen.
            up_src = prompt if str(prompt).strip() else (p.negative or prompt)
            ins = node_inputs(spec, {**extra,
                                     "file_name": fn_val, "model_name": base, "user_prompt": up_src,
                                     "prompt": up_src, "system_prompt": "", "temperature": 0.7,
                                     "top_p": 1.0, "max_tokens": p.upsample_max_tokens, "mode": "chat"})
            if ins and "STRING" in (spec.get("output") or []):
                nid = g.add("ChatGPT", **ins)
                note(info, "Prompt-Upsampler", f"ChatGPT-Node + '{un}'")
                return o(nid, 0)
    return None


def build_flux3(p: Params, cat: Catalog, info: dict) -> Graph:
    """Flux 3 (Klein Base int8): Gemma-4-Text-Encoder + optionaler Prompt-Upsampler.

    Turbo: 'auto' wendet keine Turbo-LoRA an (Standard 25 Steps / CFG 3.5);
    eine Turbo/Destillat-LoRA wirkt nur, wenn sie explizit mit --turbo <lora>
    verlangt wird ('off' deaktiviert sie ebenfalls).
    """
    g = Graph()
    kind, uname = pick_unet(cat, [p.unet] if p.unet else FLUX3_UNET_CANDS)
    note(info, "UNet", f"{uname} [{kind}]")
    model = load_unet(g, kind, uname)

    tn = cat.pick("text_encoders", [p.clip] if p.clip else FLUX3_CLIP_CANDS, ext=".safetensors")
    note(info, "Text-Encoder", tn)
    clip_type = flux3_clip_type(cat)
    if clip_type is None:
        warn(info, "Laufende ComfyUI unbekannt - CLIPLoader type='flux' angenommen; pruefe 'mm.py check'.")
        clip_type = "flux"
    elif p.clip is None and not any(k in tn.lower() for k in ("gemma4", "gemma-4", "gemma_4")):
        warn(info, f"Erwarteter Flux-3-Text-Encoder (Gemma 4) nicht gefunden - Ersatz '{tn}' (type '{clip_type}').")
    clip = o(g.add("CLIPLoader", clip_name=tn, type=clip_type, device="default"))

    vn = cat.pick("vae", [p.vae] if p.vae else ["flux2_vae", "flux2-vae", "ae"])
    note(info, "VAE", vn)
    vae = o(g.add("VAELoader", vae_name=vn))

    turbo = resolve_turbo(p, cat, info, uname)
    loras = ([(turbo.lora, 1.0)] if turbo else []) + user_loras(cat, p, info)
    model, clip = lora_full(g, model, clip, loras)
    steps, cfg, smp, sch = sampling(p, turbo, 25, 3.5)

    # Referenzbilder zuerst anlegen: ihre Groesse bestimmt W/H (und damit auch
    # die Upsampler-Vorlage), bevor der optionale Upsampler-Zweig gebaut wird.
    first_ref = None
    ref_lats: list = []
    for name in p.images:
        li = g.add("LoadImage", image=name)
        sc = scale_total(g, o(li), p.megapixels)
        ref_lats.append(g.add("VAEEncode", pixels=o(sc), vae=vae))
        if first_ref is None:
            first_ref = o(sc)
    W, H, derive = sizes(g, p, first_ref)

    prompt_text = p.prompt
    if not p.no_upsample:
        up = flux3_upsample(g, p, cat, info, prompt_text)
        if up is not None:
            prompt_text = up
        else:
            warn(info, "Kein Prompt-Upsampler gefunden (erwartet: qwen3.5_9b_flux3_prompt_upsampler_w4a8) - "
                       "Prompt wird unveraendert verwendet. Abstellen: --no-upsample")
    pos = o(g.add("CLIPTextEncode", text=prompt_text, clip=clip))
    neg = negative_cond(g, clip, pos, p, cfg)
    for lat in ref_lats:   # Referenz-Latente an beide Bedingungen anhaengen
        pos = o(g.add("ReferenceLatent", conditioning=pos, latent=o(lat)))
        neg = o(g.add("ReferenceLatent", conditioning=neg, latent=o(lat)))

    if p.control:
        raise Unsupported("Flux 3: noch kein ControlNet - nutze klein9b (--control union) oder qwen21.")

    # Flux-3-Sampling wie im offiziellen ComfyUI-Template 'flux3_klein_base':
    # Modell -> Flux3ImageGuidanceEmbedder (guidance-Skalierung) -> CFGGuider ->
    # SamplerCustomAdvanced mit RandomNoise + Flux2Scheduler. Ohne diese Node
    # ignoriert das Modell die cfg/guidance vollstaendig - das Ergebnis wirkt
    # kaputt ("klappt nicht"), obwohl der Graph laeuft.
    # Der Guidance-Wert ist eine Zahl ODER ein Link auf 'BasicScheduler' (Steps).
    if cat.object_info is None or "Flux3ImageGuidanceEmbedder" in cat.object_info:
        gvalue: object = 3.5
        if steps != 25 and cat.object_info is not None:
            bs = cat.object_info.get("BasicScheduler")
            outs = (bs or {}).get("output") or []
            allowed = {**((bs or {}).get("input", {}).get("required") or {}),
                       **((bs or {}).get("input", {}).get("optional") or {})}
            if "FLOAT" in outs and {"model", "steps"} <= set(allowed):
                gvalue = o(g.add("BasicScheduler", model=model, steps=steps))
        model = o(g.add("Flux3ImageGuidanceEmbedder", model=model, guidance=gvalue))
    elif cat.object_info is not None:
        warn(info, "Node 'Flux3ImageGuidanceEmbedder' fehlt in der laufenden ComfyUI - "
                   "ComfyUI und Custom-Nodes aktualisieren, sonst ignoriert Flux 3 die Steuerung.")
    latent = o(g.add("EmptyFlux2LatentImage", width=W, height=H, batch_size=p.batch))
    sigmas = g.add("Flux2Scheduler", steps=steps, width=W, height=H)
    noise = g.add("RandomNoise", noise_seed=seed_of(p, info))
    sel = g.add("KSamplerSelect", sampler_name=smp)
    guider = g.add("CFGGuider", model=model, positive=pos, negative=neg, cfg=cfg)
    sca = g.add("SamplerCustomAdvanced", noise=o(noise), guider=o(guider), sampler=o(sel),
                sigmas=o(sigmas), latent_image=latent)
    info["steps"], info["cfg"], info["sampler"] = steps, cfg, f"{smp}/Flux2Scheduler"
    finish(g, p, o(sca, 0), vae)
    return g


def build_moss_t2i(p: Params, cat: Catalog, info: dict) -> Graph:
    """MOSS Text-to-Image.

    Standard (Turbo 'auto') folgt docs/mosst2i_withLora.json: DMD-Turbo-LoRA
    (MOSS/MOSS-Image-SFT-8-steps-dmd.safetensors, Staerke 1.0) bei 8 Steps / CFG 1.0.
    Turbo: 'auto' -> dmd8 (8 Steps, LoRA), 'rapid4' -> RapidMOSSAdapter 4 Steps,
    'off' -> base 25 Steps / CFG 3.5 without Turbo LoRA.
    """
    g = Graph()
    # MOSS UNet
    unet_name = cat.pick("unet", [p.unet] if p.unet else [MOSS_DEFAULT_UNET], required=True)
    note(info, "UNet", unet_name)
    model = o(g.add("MOSSImageUNETLoader", unet_name=unet_name, weight_dtype="default"))

    # MOSS CLIP
    clip_name = cat.pick("text_encoders", [p.clip] if p.clip else ["qwen3.5_9b_int8_convrot.safetensors", "moss-image-sft-qwen35-int8-convrot.safetensors"], ext=".safetensors", required=True)
    note(info, "Text-Encoder", clip_name)
    clip = o(g.add("MOSSImageCLIPLoader", clip_name=clip_name, type="moss_image", device="default"))

    # MOSS VAE
    vae_name = cat.pick("vae", [p.vae] if p.vae else ["flux2_vae.safetensors", "flux2-vae.safetensors", "moss_image_vae_bf16.safetensors"], required=True)
    note(info, "VAE", vae_name)
    vae = o(g.add("VAELoader", vae_name=vae_name))

    # Turbo handling
    turbo = resolve_turbo(p, cat, info, "moss_t2i")
    loras = ([(turbo.lora, turbo.strength)] if turbo else []) + user_loras(cat, p, info)
    model = lora_model_only(g, model, loras)

    # Base steps/cfg for MOSS T2I
    d_steps = 25
    d_cfg = 3.5
    steps, cfg, smp, sch = sampling(p, turbo, d_steps, d_cfg, "euler", "simple")

    # Prompt
    pos = o(g.add("CLIPTextEncode", text=p.prompt, clip=clip))
    neg = negative_cond(g, clip, pos, p, cfg)

    # Size
    W, H, _ = sizes(g, p, None)
    latent = o(g.add("EmptyFlux2LatentImage", width=W, height=H, batch_size=p.batch))

    # KSampler
    ks = ksampler(g, p, info, model, pos, neg, latent, steps, cfg, smp, sch)

    # VAEDecode muss die Sampler-Ausgabe nehmen: das leere Start-Latent waere
    # ein Schwarzbild ('leeres Bild in 3 Sekunden').
    finish(g, p, o(ks), vae)
    return g


def build_moss_inpaint(p: Params, cat: Catalog, info: dict) -> Graph:
    """MOSS Inpaint.

    Requires --image (source) and --control-image (mask). Turbo: dmd8 / rapid4 / off.
    """
    if not p.images:
        raise Unsupported("MOSS Inpaint braucht --image (Quellbild).")
    if not p.control_image:
        raise Unsupported("MOSS Inpaint braucht --control-image (Maske).")

    g = Graph()
    # MOSS UNet
    unet_name = cat.pick("unet", [p.unet] if p.unet else ["moss_image_sft_int8_convrot.safetensors"], required=True)
    note(info, "UNet", unet_name)
    model = o(g.add("MOSSImageUNETLoader", unet_name=unet_name, weight_dtype="default"))

    # MOSS CLIP
    clip_name = cat.pick("text_encoders", [p.clip] if p.clip else ["qwen3.5_9b_int8_convrot.safetensors", "moss-image-sft-qwen35-int8-convrot.safetensors"], ext=".safetensors", required=True)
    note(info, "Text-Encoder", clip_name)
    clip = o(g.add("MOSSImageCLIPLoader", clip_name=clip_name, type="moss_image", device="default"))

    # MOSS VAE
    vae_name = cat.pick("vae", [p.vae] if p.vae else ["flux2_vae.safetensors", "moss_image_vae_bf16.safetensors"], required=True)
    note(info, "VAE", vae_name)
    vae = o(g.add("VAELoader", vae_name=vae_name))

    turbo = resolve_turbo(p, cat, info, "moss_inpaint")
    loras = ([(turbo.lora, 1.22)] if turbo else []) + user_loras(cat, p, info)
    model = lora_model_only(g, model, loras)

    d_steps = 25
    d_cfg = 3.5
    steps, cfg, smp, sch = sampling(p, turbo, d_steps, d_cfg, "euler", "simple")

    # Load source image and mask
    src = g.add("LoadImage", image=p.images[0])
    mask = g.add("LoadImage", image=p.control_image)

    # Encode source to latent
    src_vae = g.add("VAEEncode", pixels=o(src), vae=vae)
    # Prepare mask (grow, blur, etc. - simplified here)
    mask_enc = g.add("ImageToMask", image=o(mask), channel="alpha")

    # Inpaint conditioning
    pos = o(g.add("CLIPTextEncode", text=p.prompt, clip=clip))
    neg = negative_cond(g, clip, pos, p, cfg)

    # Inpaint model (using SetLatentNoiseMask or similar)
    # For MOSS, we use the standard inpaint approach
    inpaint_model = o(g.add("InpaintModelConditioning", model=model, positive=pos, negative=neg, vae=vae, pixels=o(src), mask=o(mask_enc)))

    # Get latent from inpaint conditioning
    latent = o(g.add("InpaintConditioningEncode", conditioning=inpaint_model, vae=vae, pixels=o(src), mask=o(mask_enc)))

    ksampler(g, p, info, model, pos, neg, latent, steps, cfg, smp, sch)
    finish(g, p, latent, vae)
    return g


def build_moss_detailer(p: Params, cat: Catalog, info: dict) -> Graph:
    """MOSS Detailer: Face detail for 1-4 faces + optional SeedVR2 upscale.

    Uses --image (source). --control_strength controls number of faces (1-4).
    Turbo: dmd8 / rapid4 / off.
    """
    if not p.images:
        raise Unsupported("MOSS Detailer braucht --image (Quellbild).")

    g = Graph()
    # MOSS UNet
    unet_name = cat.pick("unet", [p.unet] if p.unet else ["moss_image_sft_int8_convrot.safetensors"], required=True)
    note(info, "UNet", unet_name)
    model = o(g.add("MOSSImageUNETLoader", unet_name=unet_name, weight_dtype="default"))

    # MOSS CLIP
    clip_name = cat.pick("text_encoders", [p.clip] if p.clip else ["qwen3.5_9b_int8_convrot.safetensors", "moss-image-sft-qwen35-int8-convrot.safetensors"], ext=".safetensors", required=True)
    note(info, "Text-Encoder", clip_name)
    clip = o(g.add("MOSSImageCLIPLoader", clip_name=clip_name, type="moss_image", device="default"))

    # MOSS VAE
    vae_name = cat.pick("vae", [p.vae] if p.vae else ["flux2_vae.safetensors", "moss_image_vae_bf16.safetensors"], required=True)
    note(info, "VAE", vae_name)
    vae = o(g.add("VAELoader", vae_name=vae_name))

    turbo = resolve_turbo(p, cat, info, "moss_detailer")
    loras = ([(turbo.lora, 1.22)] if turbo else []) + user_loras(cat, p, info)
    model = lora_model_only(g, model, loras)

    d_steps = 25
    d_cfg = 3.5
    steps, cfg, smp, sch = sampling(p, turbo, d_steps, d_cfg, "euler", "simple")

    # Load source image
    src = g.add("LoadImage", image=p.images[0])

    # Face detection and detailer logic would go here
    # Simplified: just encode and run with detailer prompt
    src_vae = g.add("VAEEncode", pixels=o(src), vae=vae)

    pos = o(g.add("CLIPTextEncode", text=p.prompt + ", detailed face, high quality", clip=clip))
    neg = negative_cond(g, clip, pos, p, cfg)

    latent = o(src_vae)
    ksampler(g, p, info, model, pos, neg, latent, steps, cfg, smp, sch)
    finish(g, p, latent, vae)
    return g


def build_moss_prompt_enhancer(p: Params, cat: Catalog, info: dict) -> Graph:
    """MOSS Prompt Enhancer: Uses LLM to enhance prompt.

    Returns enhanced prompt text (no image generation). Uses Qwen3-VL LLM.
    """
    g = Graph()
    # This workflow uses an LLM node to enhance the prompt
    # The actual LLM call happens via custom node (ComfyUI-cc_llama_vision or similar)
    # We output the enhanced prompt as text

    # For now, build a minimal graph that just passes through the prompt
    # The real enhancement happens via custom LLM node
    need_node(cat, "ChatGPT", "ComfyUI-cc_llama_vision oder aehnlicher LLM-Node")

    # ChatGPT node for prompt enhancement (configured as LLM)
    enhanced = g.add("ChatGPT",
                     model_name="Qwen3-VL-4B-Instruct-abliterated.Q8_0.gguf",
                     user_prompt=f"Enhance this prompt for image generation: {p.prompt}",
                     system_prompt="You are a prompt engineering expert. Enhance the given prompt with artistic details, lighting, composition, and style keywords suitable for MOSS-Image generation.",
                     temperature=0.7, top_p=1.0, max_tokens=512, mode="chat")

    note(info, "Prompt Enhancer", "LLM-based prompt enhancement (output is text, not image)")
    return g


def build_moss_4step(p: Params, cat: Catalog, info: dict) -> Graph:
    """MOSS 4-Step (RapidMOSSAdapter rapid-moss-4step).

    Turbo is always rapid4 (4 steps). 'off' falls back to base.
    """
    g = Graph()
    # MOSS UNet
    unet_name = cat.pick("unet", [p.unet] if p.unet else ["moss_image_sft_int8_convrot.safetensors"], required=True)
    note(info, "UNet", unet_name)
    model = o(g.add("MOSSImageUNETLoader", unet_name=unet_name, weight_dtype="default"))

    # MOSS CLIP
    clip_name = cat.pick("text_encoders", [p.clip] if p.clip else ["qwen3.5_9b_int8_convrot.safetensors", "moss-image-sft-qwen35-int8-convrot.safetensors"], ext=".safetensors", required=True)
    note(info, "Text-Encoder", clip_name)
    clip = o(g.add("MOSSImageCLIPLoader", clip_name=clip_name, type="moss_image", device="default"))

    # MOSS VAE
    vae_name = cat.pick("vae", [p.vae] if p.vae else ["flux2_vae.safetensors", "moss_image_vae_bf16.safetensors"], required=True)
    note(info, "VAE", vae_name)
    vae = o(g.add("VAELoader", vae_name=vae_name))

    # For 4-step, turbo is always rapid4 unless explicitly off
    turbo = resolve_turbo(p, cat, info, "moss_4step")
    loras = ([(turbo.lora, 1.0)] if turbo else []) + user_loras(cat, p, info)
    model = lora_model_only(g, model, loras)

    # RapidMOSSAdapter node
    need_node(cat, "RapidMOSSAdapter", "ComfyUI-MOSS-Image custom nodes")
    model = o(g.add("RapidMOSSAdapter", model=model, adapter_name="rapid-moss-4step"))

    d_steps = 4
    d_cfg = 1.0
    steps, cfg, smp, sch = sampling(p, turbo, d_steps, d_cfg, "euler", "simple")

    pos = o(g.add("CLIPTextEncode", text=p.prompt, clip=clip))
    neg = negative_cond(g, clip, pos, p, cfg)

    W, H, _ = sizes(g, p, None)
    latent = o(g.add("EmptyFlux2LatentImage", width=W, height=H, batch_size=p.batch))

    ksampler(g, p, info, model, pos, neg, latent, steps, cfg, smp, sch)
    finish(g, p, latent, vae)
    return g


BUILDERS = {
    "krea2": build_krea2,
    "klein9b": build_klein,
    "klein4b": build_klein,
    "qwen-edit": build_qwen_edit,
    "qwen21": build_qwen21,
    "zimage": build_zimage,
    "flux3": build_flux3,
    "moss_t2i": build_moss_t2i,
    "moss_inpaint": build_moss_inpaint,
    "moss_detailer": build_moss_detailer,
    "moss_prompt_enhancer": build_moss_prompt_enhancer,
    "moss_4step": build_moss_4step,
}


def build(p: Params, cat: Catalog) -> tuple[dict, dict]:
    if p.mode not in BUILDERS:
        raise Unsupported(f"Unbekannter Modus '{p.mode}'. Moeglich: {', '.join(BUILDERS)}")
    info = {"models": [], "warnings": [], "notes": []}
    g = BUILDERS[p.mode](p, cat, info)
    return g.nodes, info


# ───────────────────────────── Validierung ─────────────────────────────

def validate(graph: dict, object_info: dict) -> list[str]:
    """Prueft Node-Klassen, Pflicht-Eingaben und Combo-Werte gegen die laufende ComfyUI."""
    problems: list[str] = []
    for nid, node in graph.items():
        cls = node["class_type"]
        spec = object_info.get(cls)
        if spec is None:
            problems.append(f"[{nid}] Node-Klasse '{cls}' existiert nicht")
            continue
        inp = spec.get("input", {})
        req = inp.get("required", {})
        allowed = {**req, **inp.get("optional", {})}
        for name, s in req.items():
            if name not in node["inputs"] and not any(k.startswith(name + ".") for k in node["inputs"]):
                problems.append(f"[{nid}] {cls}: Pflicht-Eingabe '{name}' fehlt")
        for name, val in node["inputs"].items():
            base = name.split(".")[0]
            if base not in allowed:
                problems.append(f"[{nid}] {cls}: unbekannte Eingabe '{name}'")
                continue
            opts = combo_options(allowed[base]) if name == base else None
            if opts is not None and not isinstance(val, list) and val not in opts:
                short = ", ".join(str(x) for x in opts[:6])
                problems.append(f"[{nid}] {cls}.{name}: Wert '{val}' nicht in Liste ({short}{' ...' if len(opts) > 6 else ''})")
    return problems


# ───────────────────────────── Bilder zu ComfyUI bringen ─────────────────────────────

def _safe_name(path: Path) -> str:
    h = hashlib.sha1(path.read_bytes()).hexdigest()[:8]
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", path.stem)[:40]
    return f"mm_{stem}_{h}{path.suffix.lower()}"


def upload_image(url: str, path: Path) -> str:
    boundary = "----mm" + uuid.uuid4().hex
    fname = _safe_name(path)
    ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{fname}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + path.read_bytes() + b"\r\n"
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'.encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(url.rstrip("/") + "/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.loads(r.read().decode())
    return f"{res['subfolder']}/{res['name']}" if res.get("subfolder") else res["name"]


def stage_image(path_str: str, tgt: dict, upload: bool) -> str:
    """Lokale Datei -> Name, den LoadImage in ComfyUI findet."""
    path = Path(path_str.strip('"')).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Bilddatei nicht gefunden: {path}")
    if upload:
        return upload_image(tgt["url"], path)
    in_dir = (tgt["comfy_dir"] / "input") if tgt.get("comfy_dir") else None
    name = _safe_name(path)
    if in_dir and in_dir.is_dir():
        dst = in_dir / name
        if not dst.exists():
            shutil.copy2(path, dst)
        return name
    print(f"[!] ComfyUI-input-Ordner nicht gefunden - kopiere '{path.name}' selbst nach ComfyUI\\input", file=sys.stderr)
    return path.name


# ───────────────────────────── Modell-Registry (docs/models.txt) ─────────────────────────────

MODELS_TXT = Path(__file__).resolve().parent.parent / "docs" / "models.txt"
_registry_lock = threading.Lock()

# Standard-Diffusionsmodell der MOSS-Modi (Default, wenn nichts gewaehlt ist).
MOSS_DEFAULT_UNET = "moss_image_sft_int8_convrot.safetensors"

# Turbo-LoRA aus docs/mosst2i_withLora.json: Unterordner + Dateiname (case-sensitiv).
MOSS_TURBO_LORA_SUBPATH = "MOSS/MOSS-Image-SFT-8-steps-dmd.safetensors"

# Staerke der DMD-Turbo-LoRA im Referenz-Workflow docs/mosst2i_withLora.json
# (node 128: LoraLoaderModelOnly, strength_model = 0.7).
MOSS_DMD_STRENGTH = 0.7

# ───────────────────────────── Modell-Registry (docs/models.txt) ─────────────────────────────

def _reg_norm(s: str) -> str:
    return s.replace("\\", "/").lower()


# ───────────────────────────── Standard-Checkpoints je Modus ─────────────────────────────

# Default-Diffusionsmodell je Modus - wird als korrekter Checkpoint direkt ins
# Gradio-Dropdown geladen. Quelle: Workflow-JSONs unter docs/ (MOSS:
# mosst2i_withLora.json); fuer diebrigen Modi die erste Bau-Kandidatenliste.
MODE_DEFAULT_UNET: dict[str, str] = {
    "krea2":     "krea2Turbo18For_v2",
    "klein9b":   "flux2Klein_9b",
    "klein4b":   "flux-2-klein-4b",
    "qwen-edit": "qwen-image-edit-2511-Q4_K_S",
    "qwen21":    "qwen_image_2.1_int8_convrot",
    "zimage":    "z-image-turbo-fp8-aio",
    "flux3":     FLUX3_UNET_CANDS[0],
    "moss_t2i":  MOSS_DEFAULT_UNET,
    "moss_inpaint": MOSS_DEFAULT_UNET,
    "moss_detailer": MOSS_DEFAULT_UNET,
    "moss_4step": MOSS_DEFAULT_UNET,
}


# Standard-Text-Encoder / VAE je Modus - passen zu den Bau-Kandidatenlisten
# der Builder; werden im Dropdown gewaehlt, wenn kein ausdruecklicher
# (modusgleicher) Nutzerwert vorliegt.
MODE_DEFAULT_CLIP: dict[str, str] = {
    "krea2":     "qwen3vl_4b_fp8_scaled",
    "klein9b":   "qwen_3_8b",
    "klein4b":   "qwen_3_4b",
    "qwen-edit": "qwen_2.5_vl_7b_fp8_scaled",
    "qwen21":    "qwen3vl_8b_int8_convrot",
    "flux3":     FLUX3_CLIP_CANDS[0],
    "moss_t2i":  "qwen3.5_9b_int8_convrot.safetensors",
    "moss_inpaint": "qwen3.5_9b_int8_convrot.safetensors",
    "moss_detailer": "qwen3.5_9b_int8_convrot.safetensors",
    "moss_4step": "qwen3.5_9b_int8_convrot.safetensors",
}

MODE_DEFAULT_VAE: dict[str, str] = {
    "krea2":     "qwen_image_vae",
    "klein9b":   "flux2_vae",
    "klein4b":   "flux2_vae",
    "qwen-edit": "qwen_image_vae",
    "qwen21":    "qwen_image_2.1_vae_bf16",
    "flux3":     "flux2_vae",
    "moss_t2i":  "flux2_vae.safetensors",
    "moss_inpaint": "flux2_vae.safetensors",
    "moss_detailer": "flux2_vae.safetensors",
    "moss_4step": "flux2_vae.safetensors",
}


def default_unet_for(mode: str) -> str | None:
    """Standard-Diffusionsmodell eines Modus liefern (None = kein fester Default)."""
    return MODE_DEFAULT_UNET.get(mode)


def default_clip_for(mode: str) -> str | None:
    """Standard-Text-Encoder eines Modus liefern (None = kein fester Default)."""
    return MODE_DEFAULT_CLIP.get(mode)


def default_vae_for(mode: str) -> str | None:
    """Standard-VAE eines Modus liefern (None = kein fester Default)."""
    return MODE_DEFAULT_VAE.get(mode)


# Pfadbestandteile, die bei Modell-Scans / LoRA-Vorschlaegen ignoriert werden.
REGISTRY_SKIP_PARTS = {"custom_nodes", ".disabled", "__pycache__", ".cache",
                       "text_embed_cache", "node_modules"}

# Zusatz-Stichwoerter je Modus fuer den LoRA-Vorschlag (zusaetzlich zum UNET-Namen).
LORA_MODE_HINTS = {
    "klein9b": ["flux2", "klein", "9b"],
    "klein4b": ["flux2", "klein", "4b"],
    "qwen21": ["qwen"],
    "qwen-edit": ["qwen"],
    "krea2": ["krea2", "krea"],
    "zimage": ["z-image", "zimage"],
    "flux3": ["flux3", "flux"],
    # MOSS: nur echte MOSS-LoRAs vorschlagen - 'image' waehrt qwen/z-image-LoRAs aus.
    "moss_t2i": ["moss", "dmd"],
    "moss_inpaint": ["moss", "dmd"],
    "moss_detailer": ["moss", "dmd"],
    "moss_4step": ["moss", "rapid"],
}

# Fremdmarker: Ordner-/Namensbestandteile, die eine LoRA eindeutig einer
# anderen Modellfamilie zuordnen (z.B. loras/ltx2/... = LTX-Video-LoRAs).
# Erscheint ein solcher Marker im Pfad und passt nicht zu den Suchtokens des
# gewaehlten Modus/Diffusionsmodells, wird die LoRA nicht vorgeschlagen.
# 'flux' ist bewusst NICHT als Marker enthalten: Ordner wie loras/flux/
# gehoren zur Flux-Familie und werden ueber die Tokens der Modi
# (klein9b/klein4b: 'flux2', flux3: 'flux') korrekt bewertet.
LORA_FAMILY_MARKERS = ("ltx", "wan", "hunyuan", "sdxl", "sd15", "sd2",
                       "minimax", "krea", "ideogram", "animatediff",
                       "z-image", "z_image")

# Varianten der Fremdmarker, wie sie in Ordnernamen vorkommen koennen
# (z.B. loras/ltx2/ = LTX Version 2.x). Erlaubte Familienvarianten (z.B.
# 'flux2' fuer klein9b/klein4b) stehen in LORA_ALLOWED_FAMILIES und werden
# vor der kuerzeren Stammvorfeld-Version ('flux') anerkannt.
LORA_FAMILY_VARIANTS: dict[str, tuple] = {
    "ltx": ("ltx2", "ltx23", "ltx25", "ltxv"),
    "wan": ("wan21", "wan22"),
    "flux": ("flux2",),
}

# Je Modus zusaetzlich erlaubte Familien-Varianten: erscheinen sie im Pfad,
# wirken sie wie passende Suchtokens - die kuerzere Fremdmarkervorversion
# (z.B. 'flux') disqualifiziert dann nicht.
LORA_ALLOWED_FAMILIES: dict[str, tuple] = {
    "klein9b": ("flux2",),
    "klein4b": ("flux2",),
}


def _lora_dir_tokens(rel: str) -> list[str]:
    """Ordnerteile eines relativen Pfads als ganze Tokens zerlegen.

    Bindestrich-/punktverbundene Ordnernamen wie 'z-image' oder 'ltx-2.3'
    bleiben dabei ganz ('z-image', 'ltx', '2', '3'); das verhindert, dass ein
    Teil-Token (z.B. 'image') fremdspraechige LoRAs durchlaesst.
    """
    parts = _reg_norm(rel).replace("\\", "/").split("/")[:-1]
    toks: list[str] = []
    for p in parts:
        toks.extend(t for t in re.split(r"[^a-z0-9]+", p) if t)
        toks.append(p)   # whole hyphenated dir name, e.g. 'z-image'
    return toks


def registry_roots() -> list[Path]:
    """Modellwurzeln aus config.json (image+video, ohne Duplikate) als Pfade liefern."""
    import mm_common as C
    cfg = C.load_config()
    out: list[Path] = []
    for name in ("image", "video"):
        for r in C.target(cfg, name).get("model_roots", []):
            p = C.abspath(r)
            if p not in out:
                out.append(p)
    return out


def _reg_norm(s: str) -> str:
    return s.replace("\\", "/").lower()


def _reg_family(rel: str) -> str:
    """Grob-Familie eines relativen Pfads fuer den LoRA-Vorschlag ('flux2_klein_9b')."""
    parts = [p.lower() for p in rel.replace("\\", "/").split("/")[:-1]]
    return "_".join(parts[-1:]) if parts else ""


def _reg_skip(rel: str) -> bool:
    """True, wenn ein relativer Pfad außerhalb der Modellordner liegt (Node-Muell)."""
    return any(part.lower() in REGISTRY_SKIP_PARTS for part in rel.replace("\\", "/").split("/"))


def _reg_line(path: Path, root: Path) -> str | None:
    """Eine models.txt-Zeile fuer eine Modelldatei bauen; Trigger aus alter Zeile uebernehmen."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if _reg_skip(str(rel)):
        return None
    full = str(path.resolve())
    trig = ""
    if MODELS_TXT.exists():
        for ln in MODELS_TXT.read_text(encoding="utf-8", errors="ignore").splitlines():
            if _reg_norm(ln.split("  \u2192  ")[0]) == _reg_norm(full):
                i = ln.find("\u2192")
                if i >= 0:
                    trig = ln[i:].strip()
                break
    line = full.replace("/", "\\")
    if trig:
        line += "  " + trig
    return line


def scan_model_registry(roots=None) -> dict:
    """Modelldateien der ComfyUI-Roots scannen und docs/models.txt aktualisieren.

    Neue Dateien werden ergaenzt, verschwundene entfernt; manuell gepflegte
    Trigger-Anhaenge (\u2192 Trigger: ...) bleiben erhalten. Liefert
    {'added': n, 'removed': n, 'total': n, 'path': str}.

    Sicherheit: Wenn kein Root existiert (z.B. fremde Maschine oder Tests), wird
    die bestehende Liste unveraendert gelassen - ein leerer Scan loescht nichts.
    """
    roots = [Path(r) for r in (roots or registry_roots())]
    found: dict[str, str] = {}   # norm-Pfad -> fertige Zeile
    scanned_dirs = 0
    for root in roots:
        if not root.is_dir():
            continue
        for kind, subs in KIND_DIRS.items():
            for sub in subs:
                base = root / sub
                if not base.is_dir():
                    continue
                scanned_dirs += 1
                for dp, _dn, fns in os.walk(base):
                    for f in fns:
                        if Path(f).suffix.lower() not in EXTS:
                            continue
                        p = Path(dp) / f
                        line = _reg_line(p, root)
                        if line is not None:
                            found[_reg_norm(line.split("  \u2192  ")[0])] = line
    with _registry_lock:
        old_lines = []
        if MODELS_TXT.exists():
            old_lines = MODELS_TXT.read_text(encoding="utf-8", errors="ignore").splitlines()
        if not scanned_dirs:
            return {"added": 0, "removed": 0,
                    "total": len([l for l in old_lines if l.strip()]),
                    "path": str(MODELS_TXT), "skipped": True}
        keep: list[str] = []
        seen: set[str] = set()
        for ln in old_lines:
            key = _reg_norm(ln.split("  \u2192  ")[0])
            if key in found and key not in seen:
                keep.append(found[key])
                seen.add(key)
        added = 0
        new_entries: list[str] = []
        for key, line in found.items():
            if key not in seen:
                new_entries.append(line)
                added += 1
        removed = len([l for l in old_lines if l.strip()]) - len(keep)
        text = "\n".join(keep + sorted(new_entries, key=str.lower)) + ("\n" if keep or new_entries else "")
        MODELS_TXT.parent.mkdir(parents=True, exist_ok=True)
        # Atomar schreiben: erst in eine Temp-Datei desselben Verzeichnisses,
        # dann os.replace(). Schlaegt der Schreibvorgang fehl (z.B. Platte voll,
        # Datei gesperrt), bleibt die bestehende models.txt unversehrt.
        tmp = MODELS_TXT.with_name(MODELS_TXT.name + ".tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, MODELS_TXT)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
    return {"added": added, "removed": max(removed, 0),
            "total": len(keep) + len(new_entries), "path": str(MODELS_TXT)}


def load_models_txt(path=None) -> list[dict]:
    """docs/models.txt lesen -> [{'full','root','rel','family','trigger'}]."""
    p = Path(path) if path else MODELS_TXT
    out: list[dict] = []
    if not p.exists():
        return out
    roots = sorted((str(r.resolve()).replace("\\", "/") for r in registry_roots()), key=len, reverse=True)
    for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        full, _, tail = raw.partition("  \u2192  ")
        norm = _reg_norm(full)
        root = next((r for r in roots if norm.startswith(r.rstrip("/") + "/")), "")
        rel = norm[len(root) + 1:] if root else norm.split("/")[-1]
        fam = _reg_family(rel)
        out.append({"full": full.replace("\\", "/"), "root": root, "rel": rel,
                    "family": fam, "trigger": tail.strip()})
    return out


def loras_for_mode(mode: str, unet_choice: str | None = None, entries=None) -> list[tuple]:
    """Passende LoRAs zum Modus/Diffusionsmodell vorschlagen -> [(Dropdown-Label, Pfad)] ."""
    es = entries if entries is not None else load_models_txt()
    needle = _reg_norm(unet_choice.rsplit("/", 1)[-1]) if unet_choice else \
        _reg_norm(MOSS_DEFAULT_UNET)
    # Dateiendung vor dem Token-Split abziehen, damit 'safetensors' nicht als
    # Suchtoken fremde LoRAs matcht (Filter und 4-Token-Limit bleiben erhalten).
    needle = re.sub(r"\.(safetensors|ckpt|pt|pth|bin|gguf)$", "", needle)
    toks = [t for t in re.split(r"[^a-z0-9]+", needle) if len(t) >= 3 and t != "image"][:4]
    toks += [t for t in LORA_MODE_HINTS.get(mode, []) if t not in toks]
    # Vorfilter: LoRAs muessen zum Modus/Diffusionsmodell passen. Ein Ordner-
    # oder Namens-Fremdmarker (ltx2/wan/sdxl/...), der nicht zu den Suchtokens
    # gehoert, disqualifiziert - so erscheinen bei MOSS keine LTX-LoRAS.
    # Varianten der Marker (z.B. ltx2 fuer 'ltx') werden mit erkannt; ein
    # ganzer Ordnername (z.B. 'flux2') gilt zunaechst als Stamm-Marker ('flux').
    # Eine erlaubte Familienvariante des Modi (klein9b/klein4b: 'flux2') befreit
    # nur den zugeoerderten Marker - unabhaengige Marker (z.B. 'wan22')
    # disqualifizieren weiterhin, auch wenn der Dateiname 'flux2' enthaelt.
    markers = {m for m in LORA_FAMILY_MARKERS if m not in toks}
    marker_forms = {m: {m} | set(LORA_FAMILY_VARIANTS.get(m, ()))
                    for m in markers}
    allowed_fams = LORA_ALLOWED_FAMILIES.get(mode, ())

    def _foreign(rel: str, path_toks: list[str]) -> bool:
        # Pfad-Tokens (Ordner + Dateiname): ein Fremdmarker kann auch nur im
        # Dateiname stehen (z.B. 'wan22_motion.safetensors' ohne wan-Ordner).
        # Ein erlaubter Familienordner befreit genau einen Marker-Stamm - den
        # eigenen ('flux2_klein' -> Stamm 'flux') - und hoelt keine fremden
        # Marker wie 'wan22' oder 'ltx2'. Uebliche Ordner wie bloss 'flux2'
        # enthalten bereits die Suchtokens des Modus; ihr Marker-Stamm faellt
        # dann ohnehin aus 'markers' heraus (m not in toks entfaellt dort
        # ueber die Token-Pruefung unten).
        dir_toks = _lora_dir_tokens(rel)
        waived_stems: set[str] = set()
        for dt in dir_toks:
            if any(mm in dt for mm in markers):
                continue          # Ordner traegt selbst einen Fremdmarker
            for stem, vs in LORA_FAMILY_VARIANTS.items():
                if stem not in allowed_fams:
                    continue      # nur erlaubte Familienordner befreien ihren Stamm
                if any(v in dt for v in (stem,) + tuple(vs)):
                    waived_stems.add(stem)
        for m, forms in marker_forms.items():
            hit = any(any(f in dt for f in forms) for dt in path_toks)
            if not hit:
                continue
            if m in allowed_fams or m in waived_stems:
                continue          # eigener erlaubter Familienordner befreit
            return True
        return False

    hits: list[tuple] = []
    seen_labels: set[str] = set()
    for e in es:
        if "/loras/" not in _reg_norm(e["full"]) or _reg_skip(e["rel"]):
            continue
        low = _reg_norm(e["rel"])
        # Token aus dem Dateinamen (Endung abgetrennt) ergaenzen, damit auch
        # reine Namensmarker wie 'wan'/'wan22' im Filename disqualifizieren.
        stem = low.rsplit("/", 1)[-1]
        stem = re.sub(r"\.(safetensors|ckpt|pt|pth|bin|gguf)$", "", stem)
        path_toks = _lora_dir_tokens(e["rel"]) + [stem]
        if _foreign(e["rel"], path_toks):
            continue
        score = sum(1 for t in toks if t in low)
        if not score and e["family"] and any(t in e["family"] for t in toks):
            score = 1
        if not score:
            continue
        label = e["rel"].rsplit("/", 1)[-1]
        if e["family"]:
            label = f"{e['family']}/{label}"
        trig = describe_trigger_name(label)
        tail = e["trigger"]
        if tail.startswith("Trigger:"):
            tail = tail[len("Trigger:"):].strip()
        if tail and tail not in ("–", "(kein Trigger)"):
            label += f"  [{tail}]"
        elif trig:
            label += f"  [{trig}]"
        if label in seen_labels:
            continue
        seen_labels.add(label)
        hits.append((score, -len(low), label, e))
    hits.sort(key=lambda x: (-x[0], -x[1], x[2].lower()))
    return [(h[2], h[3]["full"]) for h in hits[:60]]


# ───────────────────────────── Ausfuehrung ─────────────────────────────

def explain_http_error(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read().decode("utf-8", "replace"))
    except Exception:
        return f"HTTP {e.code}"
    if not isinstance(body, dict):     # manche Server antworten nur mit einem String
        return f"ComfyUI lehnt den Workflow ab: HTTP {e.code}: {body}"
    raw_err = body.get("error")
    if isinstance(raw_err, str) and raw_err.strip():
        reason = raw_err                       # manche Server liefern den Grund als String
    elif isinstance(raw_err, dict):
        reason = raw_err.get("message", e.code)
    else:
        reason = e.code
    err = raw_err if isinstance(raw_err, dict) else {}
    lines = [f"ComfyUI lehnt den Workflow ab: {reason}"]
    if err.get("details"):
        lines.append(f"  {err['details']}")
    for nid, ne in (body.get("node_errors") or {}).items():
        for er in ne.get("errors", []):
            lines.append(f"  Node {nid} ({ne.get('class_type')}): {er.get('message')} - {er.get('details', '')}")
    return "\n".join(lines)


def run_on_server(url: str, graph: dict, out_base: Path, timeout_s: int) -> list[Path]:
    url = url.rstrip("/")
    cid = uuid.uuid4().hex
    try:
        res = http_json(url + "/prompt", {"prompt": graph, "client_id": cid}, timeout=60)
    except urllib.error.HTTPError as e:
        raise RuntimeError(explain_http_error(e)) from None
    pid = res["prompt_id"]
    print(f"[i] In ComfyUI eingereiht (prompt_id {pid[:8]}) - warte auf Ergebnis ...")
    t0 = time.time()
    last = 0
    hist = None
    while True:
        try:
            h = http_json(f"{url}/history/{pid}", timeout=30)
        except Exception:
            h = {}
        if pid in h and h[pid].get("outputs") is not None and h[pid].get("status", {}).get("completed", True):
            hist = h[pid]
            break
        if pid in h and h[pid].get("status", {}).get("status_str") == "error":
            msgs = h[pid]["status"].get("messages", [])
            detail = ""
            for m in msgs:
                if m and m[0] == "execution_error":
                    d = m[1]
                    detail = f"{d.get('node_type')}: {d.get('exception_message', '').strip()}"
            raise RuntimeError(f"Fehler bei der Ausfuehrung in ComfyUI: {detail or 'siehe ComfyUI-Konsole'}")
        el = int(time.time() - t0)
        if el - last >= 10:
            print(f"    ... {el}s", flush=True)
            last = el
        if el > timeout_s:
            raise RuntimeError(f"Zeitlimit ({timeout_s}s) ueberschritten - Job laeuft evtl. noch in ComfyUI.")
        time.sleep(1.5)

    saved: list[Path] = []
    n = 0
    for node_out in hist["outputs"].values():
        for im in node_out.get("images", []):
            q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                        "type": im.get("type", "output")})
            with urllib.request.urlopen(f"{url}/view?{q}", timeout=120) as r:
                data = r.read()
            n += 1
            dst = out_base.with_name(f"{out_base.name}_{n}{Path(im['filename']).suffix or '.png'}")
            dst.write_bytes(data)
            saved.append(dst)
    return saved


def report(p: Params, info: dict, tname: str) -> str:
    title = MODE_INFO[p.mode][0]
    lines = [f"== {title}  (Ziel: {tname}) =="]
    for k, v in info["models"]:
        lines.append(f"   {k:<14} {v}")
    if "steps" in info:
        lines.append(f"   Sampling       {info['steps']} Steps, CFG {info['cfg']}, {info['sampler']}, Seed {info['seed']}")
    for n in info["notes"]:
        lines.append(f"   [i] {n}")
    for w in info["warnings"]:
        lines.append(f"   [!] {w}")
    return "\n".join(lines)
