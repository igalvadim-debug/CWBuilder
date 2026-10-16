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
import random
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from mm_common import Catalog, ModelMissing, combo_options, http_json


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
}

MODE_INFO = {
    "krea2":     ("Krea 2 Turbo",          {"edit": False, "control": ["depth"]}),
    "klein9b":   ("FLUX.2 Klein 9B",       {"edit": True,  "control": ["union (experimentell)"]}),
    "klein4b":   ("FLUX.2 Klein 4B",       {"edit": True,  "control": ["union (experimentell)"]}),
    "qwen-edit": ("Qwen Image Edit 2511",  {"edit": True,  "control": []}),
    "qwen21":    ("Qwen Image 2.1",        {"edit": True,  "control": ["union"]}),
    "zimage":    ("Z-Image Turbo",         {"edit": False, "control": ["union", "tile"]}),
    "flux3":     ("FLUX.3 Klein Base int8", {"edit": True, "control": []}),
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


def resolve_turbo(p: Params, cat: Catalog, info: dict, base_name: str) -> Turbo | None:
    presets = TURBO_PRESETS.get(p.mode, {})
    choice = (p.turbo or "auto").strip().lower()
    inherent = "turbo" in base_name.lower()
    if choice in ("off", "no", "none", "0", "false"):
        return None
    if choice == "auto":
        if inherent:
            info["notes"].append("Basismodell ist bereits ein Turbo-Modell - keine zusaetzliche Turbo-LoRA (erzwingen: --turbo <preset>)")
            return None
        if not presets or p.mode == "flux3":
            # flux3: Base ist kein Turbo-Modell und es gibt (noch) kein festes Preset -
            # auto laedt keine Turbo-LoRA, nur ein explizites --turbo <lora> wirkt.
            return None
        key = next(iter(presets))
        try:
            cand, steps, cfg = presets[key]
            name = cat.pick("loras", [cand])
            t = Turbo(name, steps, cfg, key)
        except ModelMissing as e:
            warn(info, f"Turbo-LoRA '{key}' nicht gefunden - laeuft ohne.\n      {e}")
            return None
    elif choice in presets:
        cand, steps, cfg = presets[choice]
        t = Turbo(cat.pick("loras", [cand]), steps, cfg, choice)
    else:
        name = cat.pick("loras", [p.turbo])
        t = Turbo(name, steps_from_name(name), 1.0, p.turbo)
    note(info, "Turbo-LoRA", f"{t.lora} (Preset '{t.label}', {t.steps or '?'} Steps)")
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
FLUX3_CLIP_CANDS = ["gemma4-12b-with-proj-ltx-2.5-nvfp4", "gemma4_e2b_it_bf16", "gemma-4-E2B-it-abliterated",
                    "Gemma-4-12B-it-uncensored-hereti20DeepNeuralNerd20-LTX202.5-ComfyUI-int8convrot"]
FLUX3_UPSAMPLER_CANDS = ["qwen3.5_9b_flux3_prompt_upsampler_w4a8", "flux3_prompt_upsampler",
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


def flux3_upsample(g: Graph, p: Params, cat: Catalog, info: dict, prompt: str) -> list:
    """Prompt-Upsampler (LLM) - liefert einen STRING-Ausgang. None, wenn nichts passt."""
    if not cat.object_info:
        warn(info, "ComfyUI laeuft nicht - Prompt-Upsampler kann nicht geprueft werden "
                   "(mit laufendem Server erneut pruefen: mm.py check).")
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
            ins = node_inputs(spec, {"file_name": base, "model_name": base, "user_prompt": prompt,
                                     "prompt": prompt, "system_prompt": "", "temperature": 0.7,
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
        raise Unsupported("Flux 3: noch kein ControlNet - nutze klein9b (--control union) oder qwen21.")

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


BUILDERS = {
    "krea2": build_krea2,
    "klein9b": build_klein,
    "klein4b": build_klein,
    "qwen-edit": build_qwen_edit,
    "qwen21": build_qwen21,
    "zimage": build_zimage,
    "flux3": build_flux3,
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


# ───────────────────────────── Ausfuehrung ─────────────────────────────

def explain_http_error(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read().decode("utf-8", "replace"))
    except Exception:
        return f"HTTP {e.code}"
    lines = [f"ComfyUI lehnt den Workflow ab: {body.get('error', {}).get('message', e.code)}"]
    err = body.get("error", {})
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
