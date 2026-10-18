# -*- coding: utf-8 -*-
"""MOSS-Image-Modi: Vorlagen patchen, pruefen, ausfuehren.

Vorlagen sind echte ComfyUI-Workflows (UI-Format) aus dem Ordner
``assets/MOSS Image/``; ``output/MOSS-with-my-models/`` dient als Ersatz,
falls die Vorlagen fehlen. Der Umbau nach API erfolgt ueber das vorhandene
``mm_builtin.ui_to_api``.

Turbo-Wege (Werte stammen aus den Workflow-Dateien und ihren Note-Knoten):
  dmd8   Turbo-LoRA MOSS/MOSS-Image-SFT-8-steps-dmd.safetensors, 8 Steps / CFG 1.0
         (Note "Recomendation": "Generation runs at 8 steps / CFG 1.0 via the
         Turbo (DMD) LoRA")
  rapid4 RapidMOSSAdapter 'rapid-moss-4step', 4 Steps (moss4StepWorkflow_v10)
  off    Basiswerte der Vorlage ohne Turbo-LoRA

Standard je Modus (Phase-0-Festlegung): T2I/Inpaint/Detailer -> dmd8,
moss-4step -> rapid4, moss-enhance hat keinen Sampling-Schritt.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mm_common as C          # noqa: E402
import mm_builtin as B         # noqa: E402
import mm_images as I          # noqa: E402  (stage_image, run_on_server, validate)

ROOT = C.ROOT
ASSETS_DIR = ROOT / "assets" / "MOSS Image"
FALLBACK_DIR = ROOT / "output" / "MOSS-with-my-models"

MODES = ("moss-t2i", "moss-inpaint", "moss-detailer", "moss-enhance", "moss-4step")

TEMPLATE_FILES = {
    "moss-t2i":      "MOSS Image T2I.json",
    "moss-inpaint":  "MOSS Image Inpaint.json",
    "moss-detailer": "MOSS Image detailer from 1 to 4 faces and seedvr2 upscale.json",
    "moss-enhance":  "MOSS Image prompt enchancer.json",
    "moss-4step":    "moss4StepWorkflow_v10.json",
}

TITLES = {
    "moss-t2i": "MOSS Image T2I",
    "moss-inpaint": "MOSS Image Inpaint",
    "moss-detailer": "MOSS Image Detailer (1-4 Gesichter)",
    "moss-enhance": "MOSS Image Prompt Enhancer",
    "moss-4step": "MOSS Image 4-Step (RapidMOSS)",
}

DEFAULT_TURBO = {"moss-t2i": "dmd8", "moss-inpaint": "dmd8",
                 "moss-detailer": "dmd8", "moss-4step": "rapid4",
                 "moss-enhance": "off"}

# Steps/CFG ohne Turbo-LoRA: Werte des Upstream-Templates
# _dev/MOSS-upstream/MOSS Image T2I.json (KSampler: 30 Steps, CFG 3.0).
BASE_SAMPLING = {"steps": 30, "cfg": 3.0}

# Sampler/Scheduler der MOSS-Vorlagen (Notizen: "euler/simple recommended").
_MOSS_SAMPLER = ("euler", "simple")
_LANPAINT_SCHED = ("euler", "normal")   # LanPaint_KSampler in der Inpaint-Vorlage


class MossError(Exception):
    pass


def template_path(mode: str) -> Path:
    """Vorlagendatei: assets/MOSS Image, sonst output/MOSS-with-my-models."""
    if mode not in TEMPLATE_FILES:
        raise MossError(f"Unbekannter MOSS-Modus '{mode}'. Moeglich: {', '.join(MODES)}")
    name = TEMPLATE_FILES[mode]
    p = ASSETS_DIR / name
    if p.is_file():
        return p
    alt = FALLBACK_DIR / (name.replace(".json", "") + " — my models.json")
    if alt.is_file():
        return alt
    alt2 = next((q for q in FALLBACK_DIR.glob(name.replace(".json", "*")) if q.is_file()), None) \
        if FALLBACK_DIR.is_dir() else None
    if alt2:
        return alt2
    raise MossError(f"Vorlage nicht gefunden: {p}")


def load_template(mode: str) -> dict:
    """Die zum Modus gehoerende Workflow-Vorlage als JSON laden."""
    return json.loads(C.read_text(template_path(mode)))


def _node(wf: dict, node_id: int) -> dict:
    """Knoten anhand seiner ID liefern oder bei Fehlen MossError ausloesen."""
    n = next((x for x in wf["nodes"] if x["id"] == node_id), None)
    if n is None:
        raise MossError(f"Node {node_id} fehlt in der Vorlage ({wf.get('_file')})")
    return n


def _set_widget(node: dict, index: int, value) -> None:
    """Widgetwert ersetzen; bei fehlender Liste oder Position MossError ausloesen."""
    wv = node.get("widgets_values")
    if not isinstance(wv, list) or index >= len(wv):
        raise MossError(f"Widget #{index} nicht vorhanden in Node {node['id']} "
                        f"({node['type']})")
    wv[index] = value


def _seed_value(seed) -> tuple[str, str]:
    """Seed als Text mit Modus 'fixed' liefern; negative/ungueltige Seeds auslosen."""
    try:
        s = int(seed)
    except (TypeError, ValueError):
        s = -1
    if s < 0:
        import random
        s = random.randint(0, 2**53)
    return str(s), "fixed"


def _apply_lanpaint_patch(node: dict, on: bool) -> None:
    """LanPaint_SamplerForwardMode abhaengt vom Modus: 0=aus, 3=an (Vorlage: 3)."""
    wv = node.get("widgets_values")
    if isinstance(wv, list) and len(wv) > 12:
        wv[12] = 3 if on else 0


# ───────────────────────────── Pattern pro Modus ─────────────────────────────

def _patch_t2i(wf, p, info):
    """T2I-Vorlage mit Prompt, Groesse und Sampling patchen und in info protokollieren."""
    ks = _node(wf, 4)                      # KSampler
    latent = _node(wf, 126)                # EmptyFlux2LatentImage
    pos = _node(wf, 28)                    # Prompt (LoraManager)
    neg = _node(wf, 3)                     # CLIPTextEncode (negativ)
    lay = _node(wf, 123)                   # MOSSImageLayoutPrompt
    boxes = _node(wf, 124)                 # PixaromaLayoutBoxes
    turbo = _node(wf, 127)                 # LoraLoaderModelOnly (dmd8)
    sampler, sched = _MOSS_SAMPLER
    if p.width and p.height:
        _set_widget(latent, 0, str(int(p.width)))
        _set_widget(latent, 1, str(int(p.height)))
        _set_widget(lay, 1, str(int(p.width)))
        _set_widget(lay, 2, str(int(p.height)))
        _set_widget(boxes, 0, str(int(p.width)))
        _set_widget(boxes, 1, str(int(p.height)))
    _set_widget(pos, 1, p.prompt)
    _set_widget(neg, 0, p.negative or "")
    seed, mode_str = _seed_value(p.seed)
    _set_widget(ks, 0, seed); _set_widget(ks, 1, mode_str)
    steps = p.steps if p.steps else (8 if p.turbo_kind != "off" else BASE_SAMPLING["steps"])
    cfg = p.cfg if p.cfg is not None else (1.0 if p.turbo_kind != "off" else BASE_SAMPLING["cfg"])
    _set_widget(ks, 2, str(steps)); _set_widget(ks, 3, str(cfg))
    _set_widget(ks, 4, p.sampler or sampler); _set_widget(ks, 5, p.scheduler or sched)
    _set_widget(turbo, 1, str(p.lora_strength))
    turbo["mode"] = 0 if p.turbo_kind != "off" else 4
    info["sampling"] = {"steps": steps, "cfg": cfg, "sampler": p.sampler or sampler,
                        "scheduler": p.scheduler or sched, "seed": seed}
    info["notes"].append("MOSS T2I: Layout-Knoten bleiben leer (ohne Boxen = normales T2I)")


def _patch_inpaint(wf, p, info):
    """Inpaint-Vorlage mit Pflichtbild, Prompts, LoRAs und Sampling patchen."""
    img = _node(wf, 1)                     # LoadImage
    ks = _node(wf, 38)                     # LanPaint_KSampler
    pos = _node(wf, 29)                    # Prompt (LoraManager)
    neg = _node(wf, 9)                     # CLIPTextEncode (negativ)
    turbo = _node(wf, 42)                  # LoraLoaderModelOnly (dmd8)
    loras = _node(wf, 28)                  # Lora Loader (LoraManager)
    if not p.images:
        raise MossError("moss-inpaint braucht ein Bild (--image) mit Maske")
    _set_widget(img, 0, p.images[0])
    _set_widget(pos, 1, p.prompt)
    _set_widget(neg, 0, p.negative or "")
    _set_widget(loras, 1, _loras_markup(p))
    seed, mode_str = _seed_value(p.seed)
    _set_widget(ks, 0, seed); _set_widget(ks, 1, mode_str)
    steps = p.steps if p.steps else (8 if p.turbo_kind != "off" else BASE_SAMPLING["steps"])
    cfg = p.cfg if p.cfg is not None else (1.0 if p.turbo_kind != "off" else BASE_SAMPLING["cfg"])
    _set_widget(ks, 2, str(steps)); _set_widget(ks, 3, str(cfg))
    _set_widget(ks, 4, p.sampler or _MOSS_SAMPLER[0])
    _set_widget(ks, 5, p.scheduler or _LANPAINT_SCHED[1])
    _set_widget(turbo, 1, str(p.lora_strength))
    turbo["mode"] = 0 if p.turbo_kind != "off" else 4
    info["sampling"] = {"steps": steps, "cfg": cfg, "sampler": p.sampler or _MOSS_SAMPLER[0],
                        "scheduler": p.scheduler or _LANPAINT_SCHED[1], "seed": seed}
    info["notes"].append("Maske kommt aus dem LoadImage-Malkasten (ComfyUI-Editor)")


def _patch_detailer(wf, p, info):
    """Detailer mit Pflichtbild, Gesichtsauswahl und Sampling konfigurieren."""
    img = _node(wf, 15)                    # LoadImage
    picker = _node(wf, 180)                # ImpactSEGSPicker (Face 1)
    det = _node(wf, 39)                    # DetailerForEachDebugPipe (Face 1)
    pos = _node(wf, 54)                    # Prompt (LoraManager) face 1
    neg = _node(wf, 31)                    # CLIPTextEncode negativ
    loras = _node(wf, 55)                  # Lora Loader (LoraManager) face 1
    turbo = _node(wf, 292)                 # LoraLoaderModelOnly (dmd8)
    if not p.images:
        raise MossError("moss-detailer braucht ein Bild (--image)")
    _set_widget(img, 0, p.images[0])
    faces = max(1, min(int(p.faces or 1), 4))
    _set_widget(picker, 0, ",".join(str(i) for i in range(1, faces + 1)))
    _set_widget(pos, 1, p.prompt)
    _set_widget(loras, 1, _loras_markup(p))
    if p.negative:
        _set_widget(neg, 0, p.negative)
    seed, mode_str = _seed_value(p.seed)
    _set_widget(det, 9, seed); _set_widget(det, 10, mode_str)
    steps = p.steps if p.steps else (8 if p.turbo_kind != "off" else BASE_SAMPLING["steps"])
    cfg = p.cfg if p.cfg is not None else (1.0 if p.turbo_kind != "off" else BASE_SAMPLING["cfg"])
    _set_widget(det, 11, str(steps)); _set_widget(det, 12, str(cfg))
    _set_widget(det, 13, p.sampler or _MOSS_SAMPLER[0])
    _set_widget(det, 14, p.scheduler or _LANPAINT_SCHED[1])
    _set_widget(turbo, 1, str(p.lora_strength))
    turbo["mode"] = 0 if p.turbo_kind != "off" else 4
    info["sampling"] = {"steps": steps, "cfg": cfg, "sampler": p.sampler or _MOSS_SAMPLER[0],
                        "scheduler": p.scheduler or _LANPAINT_SCHED[1], "seed": seed}
    info["notes"].append(f"Detailer: Gesichter 1..{faces} werden bearbeitet "
                         "(Segm-Detail-Zweige 2-4 bleiben in der Vorlage ausgeschaltet)")
    if p.seedvr2:
        info["warnings"].append("SeedVR2-Upscale-Zweig fehlt in der Vorlage "
                                "(aus Grunden entfernt) - --seedvr2 wirkt daher nicht")


def _patch_enhance(wf, p, info):
    """Enhancer-Vorlage mit Prompts, optionalem Bild und LLM-Parametern patchen."""
    gen = _node(wf, 3)                     # TextGenerate
    cat = _node(wf, 9)                     # StringConcatenate (System-Prompt)
    user = _node(wf, 16)                   # easy prompt (Benutzereingabe)
    clip = _node(wf, 5)                    # CLIPLoader (LLM)
    img = _node(wf, 6)                     # LoadImage (optional, Vision)
    seedn = _node(wf, 17)                  # Seed Generator
    system = p.system_prompt or _default_system_prompt()
    _set_widget(cat, 0, system)
    _set_widget(user, 0, p.prompt)
    if p.images:
        _set_widget(img, 0, p.images[0])
    else:
        _drop_link(gen, "image")
        _drop_link(img, "IMAGE")
        info["notes"].append("Ohne Bild: reiner Text-Enhancer (Vision-Eingang abgeklemmt)")
    llm = getattr(p, "llm", None)
    if llm:
        _set_widget(clip, 0, llm)
    s, _m = _seed_value(p.seed)
    _set_widget(seedn, 0, s)
    _set_widget(gen, 6, str(p.max_length))
    info["sampling"] = {"max_length": p.max_length, "seed": s}


def _patch_4step(wf, p, info):
    """4-Step-Vorlage fuer RapidMOSS, DMD oder Basissampling konfigurieren."""
    pos = _node(wf, 3)                     # CLIPTextEncode
    noise = _node(wf, 5)                   # RandomNoise
    latent = _node(wf, 6)                  # EmptyFlux2LatentImage
    sched = _node(wf, 15)                  # BasicScheduler
    save = _node(wf, 9)                    # SaveImage
    turbo = _node(wf, 2)                   # LoraLoaderModelOnly (dmd8)
    unloader = _node(wf, 13)               # MOSSImageUNETLoader
    _set_widget(pos, 0, p.prompt)
    if p.width and p.height:
        _set_widget(latent, 0, str(int(p.width)))
        _set_widget(latent, 1, str(int(p.height)))
    s, mode_str = _seed_value(p.seed)
    _set_widget(noise, 0, s); _set_widget(noise, 1, mode_str)
    if p.prefix:
        _set_widget(save, 0, p.prefix)
    if p.turbo_kind == "rapid4":
        _ensure_rapid_adapter(wf, unloader, info)
        steps = 4
        _set_widget(_node(wf, 14), 0, "euler")            # BasicKSamplerProvider
    else:
        _remove_rapid_adapter(wf, info)
        steps = 8 if p.turbo_kind == "dmd8" else (p.steps or BASE_SAMPLING["steps"])
        _set_widget(turbo, 1, str(p.lora_strength))
        turbo["mode"] = 0 if p.turbo_kind == "dmd8" else 4
        _set_widget(_node(wf, 14), 0, p.sampler or "euler_a")
    _set_widget(sched, 1, str(steps if p.steps is None and p.turbo_kind in ("rapid4", "dmd8")
                              else (p.steps or steps)))
    _set_widget(sched, 2, "1.0")
    if p.scheduler:
        _set_widget(sched, 0, p.scheduler)
    info["sampling"] = {"steps": steps, "cfg": 1.0, "sampler": "guider ohne CFG",
                        "scheduler": p.scheduler or "simple", "seed": s}


def _ensure_rapid_adapter(wf, unloader, info):
    """RapidMOSSAdapter (aus _dev/MOSS-upstream/moss4StepWorkflow_v10.json) einsetzen."""
    existing = next((n for n in wf["nodes"] if n["type"] == "RapidMOSSAdapter"), None)
    if existing:
        _set_widget(existing, 1, "4")
        return
    up = C.ROOT / "_dev" / "MOSS-upstream" / "moss4StepWorkflow_v10.json"
    src = None
    if up.is_file():
        upd = json.loads(C.read_text(up))
        src = next((n for n in upd["nodes"] if n["type"] == "RapidMOSSAdapter"), None)
    if src is None:
        info["warnings"].append("rapid4: RapidMOSSAdapter-Vorlage nicht gefunden - "
                                "es bleibt der DMD-Weg (8 Steps)")
        _set_widget(unloader, 0, unloader["widgets_values"][0])
        return
    import copy as _copy
    node = _copy.deepcopy(src)
    node["id"] = max(n["id"] for n in wf["nodes"]) + 1
    node["inputs"] = [{"name": "model", "type": "MODEL", "link": None}]
    node["outputs"] = [
        {"name": "model", "type": "MODEL", "links": []},
        {"name": "sampler", "type": "SAMPLER", "links": []},
        {"name": "sigmas", "type": "SIGMAS", "links": []},
    ]
    wf["nodes"].append(node)
    _rewire_rapid(wf, node, info)


def _rewire_rapid(wf, adapter, info):
    """UNET -> Adapter -> (Guider/Sampler/Scheduler); Basic*-Zweige abklemmen."""
    nodes = B.byid(wf)
    links = {l[0]: l for l in wf.get("links", [])}
    guider = next((n for n in wf["nodes"] if n["type"] == "BasicGuider"), None)
    sampler_node = next((n for n in wf["nodes"] if n["type"] == "SamplerCustomAdvanced"), None)
    provider = next((n for n in wf["nodes"] if n["type"] == "BasicKSamplerProvider"), None)
    sched = next((n for n in wf["nodes"] if n["type"] == "BasicScheduler"), None)
    if guider is None or sampler_node is None:
        info["warnings"].append("rapid4: Umpfadung fehlgeschlagen (Guider/Sampler nicht gefunden)")
        return
    next_lid = max([int(k) for k in links] or [0]) + 1

    def new_link(src_id: int, slot: int, dst_id: int, dst_slot: int, dtype: str) -> int:
        """Workflow-Link anlegen, Knotenreferenzen aktualisieren und Link-ID liefern."""
        nonlocal next_lid
        lid = next_lid
        next_lid += 1
        wf["links"].append([lid, src_id, slot, dst_id, dst_slot, dtype])
        sn = nodes[str(src_id)]
        for o in sn.get("outputs", []):
            if o.get("index") == slot or (sn["outputs"].index(o) == slot):
                if o.get("links") is None:
                    o["links"] = []
                if lid not in o["links"]:
                    o["links"].append(lid)
        dn = nodes[str(dst_id)]
        for i in dn.get("inputs", []):
            if i.get("index", dn["inputs"].index(i)) == dst_slot or True:
                if i.get("link") is not None:
                    old = i["link"]
                    i["link"] = lid
                    _clear_src_link(wf, old)
                    return lid
        dn.setdefault("inputs", []).append({"name": dtype.lower(), "type": dtype, "link": lid})
        return lid

    def _clear_src_link(wf, lid):
        """Link aus dem Workflow und den Ausgangsreferenzen seiner Quelle entfernen."""
        for l in wf["links"]:
            if l[0] == lid:
                sn = nodes.get(str(l[1]))
                if sn:
                    for o in sn.get("outputs", []):
                        if isinstance(o.get("links"), list) and lid in o["links"]:
                            o["links"].remove(lid)
        wf["links"] = [l for l in wf["links"] if l[0] != lid]

    un_loader = next((n for n in wf["nodes"] if n["type"] == "MOSSImageUNETLoader"), None)
    if un_loader:
        for l in wf["links"]:
            if l[1] == un_loader["id"]:
                _clear_src_link(wf, l[0])
        # UNET -> Adapter(model)
        for i in adapter.get("inputs", []):
            if i.get("name") == "model":
                lid = new_link(un_loader["id"], 0, adapter["id"], 0, "MODEL")
                i["link"] = lid
    # Adapter -> Guider.model (slot 0)
    for i in guider.get("inputs", []):
        if i.get("name") == "model":
            lid = new_link(adapter["id"], 0, guider["id"], 0, "MODEL")
            i["link"] = lid
    # Adapter -> SamplerCustomAdvanced.sampler/.sigmas
    for i in sampler_node.get("inputs", []):
        if i.get("name") == "sampler":
            lid = new_link(adapter["id"], 1, sampler_node["id"], 2, "SAMPLER")
            i["link"] = lid
        if i.get("name") == "sigmas":
            lid = new_link(adapter["id"], 2, sampler_node["id"], 3, "SIGMAS")
            i["link"] = lid
    # BasicKSamplerProvider / BasicScheduler / Turbo-LoRA abklemmen (mode 4)
    for n in (provider, sched):
        if n:
            n["mode"] = 4
            for i in n.get("inputs", []):
                if i.get("link") is not None:
                    _clear_src_link(wf, i["link"])
                    i["link"] = None
    turbo = next((n for n in wf["nodes"] if n.get("title", "").startswith("Turbo LoRA")), None)
    if turbo:
        turbo["mode"] = 4
        for l in wf["links"]:
            if l[1] == turbo["id"]:
                _clear_src_link(wf, l[0])
        for i in turbo.get("inputs", []):
            if i.get("link") is not None:
                _clear_src_link(wf, i["link"])
                i["link"] = None
    info["notes"].append("rapid4: RapidMOSSAdapter 'rapid-moss-4step' eingesetzt (4 Steps, ohne CFG)")


def _remove_rapid_adapter(wf, info):
    """Vorhandenen RapidMOSSAdapter deaktivieren und dies in info vermerken."""
    n = next((x for x in wf["nodes"] if x["type"] == "RapidMOSSAdapter"), None)
    if n:
        n["mode"] = 4
        info["notes"].append("rapid4 aus: RapidMOSSAdapter ausgeschaltet")


PATCHERS = {"moss-t2i": _patch_t2i, "moss-inpaint": _patch_inpaint,
             "moss-detailer": _patch_detailer, "moss-enhance": _patch_enhance,
             "moss-4step": _patch_4step}


def _drop_link(node, out_name):
    """Ausgang eines Knotens abklemmen (Link loeschen, Verbraucher verlieren ihn)."""
    for o in node.get("outputs", []):
        if o.get("name") == out_name and o.get("links"):
            for _lid in list(o["links"]):
                pass
            o["links"] = []


# ───────────────────────────── Parameter ─────────────────────────────

@dataclass_ok
class MossParams:
    pass
