# -*- coding: utf-8 -*-
"""VL-LLM im ComfyUI-Workflow: letztes Frame-Bild beschreiben und Prompt erweitern.

Wird von allen Video-Modi genutzt (Minimax H3, LTX 2.3, LTX 2.5). Der Workflow
enthaelt dazu eine Vision-Language-Kette:

    LoadImage/letzter Frame  ->  VAELoader/GGUF-Loader  ->  Text-Encoder(VL)
    -> Chat/Bildbeschreibung-Node  ->  STRING  ->  CLIPTextEncode der naechsten Scene

Die Node-Typen unterscheiden sich je nach installiertem Custom-Paket; ein
kompatibles Paar wird anhand der Ein-/Ausgabetypen aus /object_info gewaehlt.
"""
from __future__ import annotations

from typing import Callable, Optional

from mm_common import Catalog, combo_options

# Kandidaten fuer "Vision-Chat"-Nodes: (Klasse, Eingabe-Namen fuer Bild/Prompt/Modell)
VL_CHAT_CANDIDATES = [
    # (Node-Klasse, image-Eingabe, prompt-Eingabe, model-Eingabe oder None)
    ("LLMVisionSampler",        ("image", "images"),   ("prompt", "user_prompt"), ("llm", "model")),
    ("VisionLLMSampler",        ("image", "images"),   ("prompt", "user_prompt"), ("llm", "model")),
    ("mlmm_load_and_sample",    ("image",),            ("prompt",),                ("pipeline",)),
    ("MiniCPM_Video",           ("image",),            ("prompt",),                ("cpm_model",)),
    ("Joy_caption",             ("image",),            ("prompt",),                ("model",)),
    ("CogVLM2TextGenerator",    ("image",),            ("prompt",),                ("cogvlm2_model",)),
    ("LLaVA Vision Sampling",   ("image",),            ("prompt",),                ("llava_model",)),
    ("IDEFICS3 Sampler",        ("image",),            ("prompt",),                ("idefics3_pipeline",)),
    ("Moondream2Sampler",       ("image",),            ("question",),              ("moondream_model",)),
    ("Qwen2VisionLoader",       ("image",),            ("prompt",),                None),
]

# Loader-Kandidaten: (Node-Klasse, Modelleingabe, Catalog-Modellordner).
# Die Kompatibilitaet bestimmt der Ausgabetyp, nicht die Dateiendung.
VL_MODEL_LOADERS = [
    ("UnetLoaderGGUF",     "unet_name",      "unet"),
    ("GGUFLoader",         "gguf_name",      "llm"),
    ("LLMLoader",          "model_name",     "llm"),
    ("LLMSSRGLoader",      "model_name",     "llm"),
    ("DownloadAndLoadMoondream2", "model",   "llm"),
    ("CheckpointLoaderSimple", "ckpt_name", "checkpoints"),
]

# Typische Dateiname-Muster fuer Vision-Language-Modelle (LLM-Ordner)
VL_MODEL_CANDS = [
    "qwen2.5-vl", "qwen25-vl", "qwen2-vl", "qwen3vl", "llava", "moondream",
    "minicpm-v", "cogvlm", "joy_caption", "joy-caption", "internvl", "phi3.5-vision",
    "gemma-3-4b-it", "vit",
]


def find_vl_model(cat: Catalog, explicit: str | None) -> Optional[str]:
    """VL-Modell in den Auswahllisten/Ordnern kompatibler Loader finden."""
    chat = _chat_spec(cat)
    if chat and chat[3]:
        loaders = list(_compatible_loaders(cat, chat[4]))
        for _, _, kind, _, input_spec in loaders:
            name = _loader_model(cat, kind, input_spec, explicit)
            if name:
                return name
        if loaders:
            return None
    # Offline/ohne kompatiblen Loader nur entdecken; add_vl_branch warnt beim Bau.
    if explicit:
        for kind in ("llm", "text_encoders", "unet", "checkpoints"):
            n = cat.pick(kind, [explicit], required=False)
            if n:
                return n
        return None
    for kind in ("llm", "text_encoders", "unet", "checkpoints"):
        for c in VL_MODEL_CANDS:
            n = cat.pick(kind, [c], required=False)
            if n:
                return n
    return None


def _chat_spec(cat: Catalog):
    """Passende Vision-Chat-Node aus object_info (oder Standardannahme)."""
    oi = cat.object_info
    if oi:
        for cls, imgk, prk, modk in VL_CHAT_CANDIDATES:
            spec = oi.get(cls)
            if not spec:
                continue
            allowed = {**spec.get("input", {}).get("required", {}),
                       **spec.get("input", {}).get("optional", {})}
            img = next((k for k in imgk if k in allowed), None)
            pr = next((k for k in prk if k in allowed), None)
            mods = next((k for k in (modk or []) if k in allowed), None) if modk else None
            outs = spec.get("output") or []
            if img and pr and ("STRING" in outs or "TEXT" in outs):
                model_type = allowed[mods][0] if mods else None
                out_slot = outs.index("STRING") if "STRING" in outs else 0
                return cls, img, pr, mods, model_type, out_slot
        return None
    # Server nicht erreichbar: gangigstes Schema annehmen (ComfyUI-GGUF + KJNodes)
    return "LLMVisionSampler", "image", "prompt", "llm", None, 0


def _compatible_loaders(cat: Catalog, model_type):
    if not isinstance(model_type, str):
        return
    for cls, model_input, kind in VL_MODEL_LOADERS:
        spec = (cat.object_info or {}).get(cls, {})
        outputs = spec.get("output") or []
        inputs = {**spec.get("input", {}).get("required", {}),
                  **spec.get("input", {}).get("optional", {})}
        if model_type in outputs and model_input in inputs:
            yield cls, model_input, kind, outputs.index(model_type), inputs[model_input]


def _loader_model(cat: Catalog, kind: str, input_spec, explicit: str | None):
    options = combo_options(input_spec)
    candidates = [explicit] if explicit else VL_MODEL_CANDS
    if options is None:
        return cat.pick(kind, candidates, required=False)
    # Live-Auswahllisten sind massgeblich, auch bei extra_model_paths auf dem Server.
    for candidate in candidates:
        c = candidate.lower()
        for name in options:
            base = name.lower().replace("\\", "/").split("/")[-1]
            if c in (name.lower(), base, base.rsplit(".", 1)[0]):
                return name
    for candidate in candidates:
        hits = [name for name in options if candidate.lower() in name.lower()]
        if hits:
            return min(hits, key=len)
    return None


def add_vl_branch(g, cat: Catalog, *, image_src: list, prompt_text: str,
                  vl_model: str | None, max_tokens: int, seed: int,
                  info: dict, load_unet: Callable) -> Optional[list]:
    """Haengt die VL-Kette an den Graphen; liefert einen STRING-Link oder None.

    ``image_src`` ist ein IMAGE-Link (z.B. letzter Frame der vorherigen Scene),
    ``prompt_text`` der Entwurf der naechsten Scene. Der zurueckgegebene STRING-
    Link enthaelt die Bildbeschreibung + erweiterten Prompt und kann direkt in
    eine Texteingabe (CLIPTextEncode o.ae.) gefuettert werden.
    """
    pick = _chat_spec(cat)
    if not pick:
        info.setdefault("warnings", []).append(
            "Keine Vision-LLM-Node in der laufenden ComfyUI gefunden - "
            "Prompt-Erweiterung faellt aus (Installation: ComfyUI-GGUF / ComfyMLLM / KJNodes).")
        return None
    cls, img_in, pr_in, mod_in, model_type, out_slot = pick
    if not vl_model:
        info.setdefault("warnings", []).append(
            "Kein VL-LLM (qwen2.5-vl/llava/moondream ...) im LLM-/text_encoders-Ordner gefunden - "
            "Prompt-Erweiterung faellt aus. Setzen: --vl-llm <datei>")
        return None
    model_link = None
    if mod_in:
        for lc, li, kind, slot, input_spec in _compatible_loaders(cat, model_type):
            name = _loader_model(cat, kind, input_spec, vl_model)
            if name:
                nid = load_unet(g, kind, name)[0] if lc == "UnetLoaderGGUF" \
                    else g.add(lc, **{li: name})
                model_link = [nid, slot]
                break
        if model_link is None:
            info.setdefault("warnings", []).append(
                f"Kein kompatibler VL-Loader fuer {cls}.{mod_in} ({model_type}) "
                f"und '{vl_model}' gefunden - Prompt-Erweiterung faellt aus.")
            return None
    ins = {img_in: image_src, pr_in: prompt_text}
    if model_link is not None:
        ins[mod_in] = model_link
    for extra, val in (("max_tokens", max_tokens), ("max_new_tokens", max_tokens),
                       ("temperature", 0.6), ("top_p", 0.9), ("seed", seed)):
        spec = (cat.object_info or {}).get(cls, {})
        allowed = {**spec.get("input", {}).get("required", {}), **spec.get("input", {}).get("optional", {})}
        if not allowed or extra in allowed:
            if allowed:
                ins[extra] = val
    nid = g.add(cls, **ins)
    info.setdefault("models", []).append(("VL-LLM", f"{cls} + '{vl_model}'"))
    return [nid, out_slot]
