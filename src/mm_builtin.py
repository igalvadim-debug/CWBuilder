# -*- coding: utf-8 -*-
"""Eingebaute Video-Workflows (LTX-2.5, Minimax-H3) -> API-Graph fuer ComfyUI.

Nutzt die optimierten UI-Vorlagen aus templates/ (bzw. den eingebetteten Kopien
in mm_embedded.py) und fuellt per Node-ID:

  * Prompt, Negative, Seitenverhaeltnis/Megapixels, Dauer, Steps, Seed,
  * Turbo-Schalter (upsampler / RTX-SuperResolution / optionale LoRAs),
  * Referenzbilder: automatische Zufallsnamen + Kopie nach <comfy_dir>/input.

mm_ui.py (Gradio) und mm.py (CLI, "video ltx25 | minimax_builtin") nutzen diesen
Modul - ohne Playwright/HTML-Generator.
"""
from __future__ import annotations

import json
import random
import re
import string
import sys
import time
from pathlib import Path

import mm_common as C
from mm_images import explain_http_error, upload_image  # Validierung/Fehlerbild + Upload


class TemplateError(Exception):
    pass


TEMPLATES = {
    "ltx25": {
        "file": "ltx25.ui.json",
        "title": "LTX-2.5 Text/Image-to-Video (Audio, Fast-LoRA)",
        "target": "video",
        "prompt_node": "499",
        "negative_node": "475",
        "aspect_node": "495",          # ResolutionSelector [ratio, megapixels, multiple]
        "fps_node": "462",              # PrimitiveInt frame rate
        "duration_node": "493",         # PrimitiveInt Sekunden
        "seed_node": "457",             # RandomNoise
        "enhance_switch": {"set": ["497"], "switch": ["455"]},  # Prompt-Upsampler an
        "sigmas": {
            "turbo": ("473", "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"),
            "quality": ("473", "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.95625, 0.9375, 0.909375, 0.86875, 0.825, 0.7625, 0.6875, 0.6, 0.50625, 0.4, 0.2875, 0.175, 0.075, 0.0"),
        },
        "prefix_nodes": ["491", "494"],  # VHS_VideoCombine filename_prefix
        "ref_inputs": {},                # LTX: Bild geht in den Upsampler-Subgraph
        "ref_subgraph_input": "image",   # Eingang des eingebauten Vision-Subgraphs
        "changes": {
            "upsampler": "Latent-Upscaler x2 (2. Sampling-Durchlauf, scharfer, langsamer)",
            "rtx_sr": "RTX Video Super Resolution (GPU-Nachschaerfe)",
        },
    },
    "minimax_h3": {
        "file": "minimax_h3.ui.json",
        "title": "MiniMax-H3 Reference-to-Video (Spectrum, Audio)",
        "target": "video",
        "subgraph_id": "d5f58999-0fe9-475f-84f5-7088a6201e1a",
        "sg_prompt_widget": 3,           # innere PrimitiveStringMultiline
        "sg_duration_widget": 4,         # innere PrimitiveFloat (Sekunden)
        "aspect_node": None,             # sitzt im Subgraph (widgets 0..2)
        "steps_node": "5485",            # BasicScheduler [scheduler, steps, denoise]
        "seed_node": "5474",
        "lora_loader": "5605",
        "prefix_nodes": ["5468"],        # SaveVideo filename_prefix
        "ref_inputs": {                  # Slotname -> Liste der LoadImage-Node-IDs
            "ref_image_0": ["5483"], "ref_image_1": ["5484"], "ref_image_2": ["5630"],
            "ref_image_3": ["5652"], "ref_image_4": ["5653"], "ref_image_5": ["5654"],
        },
        "changes": {
            "rtx_sr": "RTX Video Super Resolution (GPU-Nachschaerfe)",
            "lora_motion": "Motion-Booster-LoRA (mehr Bewegung)",
            "lora_unlocked": "H3 Unlocked V2 (NSFW-LoRA)",
        },
    },
}

CHANGE_LISTS = {}  # name -> dict, lazy aus mm_templates


def _changes(name: str) -> dict:
    if not CHANGE_LISTS:
        import mm_templates as T
        CHANGE_LISTS["ltx25"] = T.LTX_CHANGES
        CHANGE_LISTS["minimax_h3"] = T.MM_CHANGES
    return CHANGE_LISTS[name]


# ───────────────────────────── Vorlage ─────────────────────────────

def load_template(key: str) -> dict:
    import mm_templates as T
    try:
        return T.load(TEMPLATES[key]["file"])
    except Exception as e:
        raise TemplateError(f"Vorlage '{key}' nicht verfuegbar: {e}") from None


def byid(wf: dict) -> dict:
    return {str(n["id"]): n for n in wf["nodes"]}


def set_widget(node: dict, idx: int, value) -> None:
    wv = node.get("widgets_values")
    if isinstance(wv, list):
        while len(wv) <= idx:
            wv.append(None)
        wv[idx] = value
    elif isinstance(wv, dict):
        keys = list(wv.keys())
        wv[keys[idx]] = value
    else:
        node["widgets_values"] = [value]


def set_widget_named(node: dict, name: str, value) -> bool:
    """Benanntes Widget setzen (dict oder Liste ueber inputs[].widget)."""
    wv = node.get("widgets_values")
    if isinstance(wv, dict):
        if name in wv:
            wv[name] = value
            return True
        return False
    if isinstance(wv, list):
        for i, inp in enumerate(node.get("inputs", [])):
            w = inp.get("widget")
            if w and w.get("name") == name:
                set_widget(node, i, value)
                return True
    return False


def unlink(wf: dict, nid: str, input_name: str) -> None:
    nodes = byid(wf)
    node = nodes.get(str(nid))
    if not node:
        return
    for inp in node.get("inputs", []):
        if inp.get("name") == input_name and inp.get("link") is not None:
            lid = inp["link"]
            inp["link"] = None
            src = nodes.get(str(_link_src(wf, lid, only=True)[0])) if False else None
            # Quell-Slot bereinigen
            for l in wf.get("links", []):
                if l[0] == lid:
                    snode = nodes.get(str(l[1]))
                    if snode:
                        for ot in snode.get("outputs", []):
                            if ot.get("slot") == l[2] or True:
                                links = ot.get("links")
                                if isinstance(links, list) and lid in links:
                                    links.remove(lid)
                    break
            wf["links"] = [l for l in wf.get("links", []) if l[0] != lid]
            return


def _link_src(wf: dict, lid: int, only=False):
    for l in wf.get("links", []):
        if l[0] == lid:
            return (l[1], l[2]) if only else (l[1], l[2])
    return None


def relink(wf: dict, nid: str, input_name: str, src_nid: str, src_slot: int = 0) -> None:
    """Verbindung neu setzen: Node nid.Input <- src_nid[src_slot]."""
    nodes = byid(wf)
    tgt = nodes[str(nid)]
    src = nodes[str(src_nid)]
    # alte Verbindung loesen
    for inp in tgt.get("inputs", []):
        if inp.get("name") == input_name and inp.get("link") is not None:
            old = inp["link"]
            ol = next((l for l in wf["links"] if l[0] == old), None)
            if ol:
                sn = nodes.get(str(ol[1]))
                if sn:
                    for ot in sn.get("outputs", []):
                        if isinstance(ot.get("links"), list) and old in ot["links"]:
                            ot["links"].remove(old)
                wf["links"] = [l for l in wf["links"] if l[0] != old]
            inp["link"] = None
    lid = max([l[0] for l in wf["links"]] + [int(wf.get("last_link_id", 0))]) + 1
    wf["links"].append([lid, int(src_nid), src_slot, int(nid), len(tgt.get("inputs", [])), "RELINK"])
    # Ziel-Eintrag finden/anlegen
    done = False
    for inp in tgt.get("inputs", []):
        if inp.get("name") == input_name:
            inp["link"] = lid
            done = True
            break
    if not done:
        tgt.setdefault("inputs", []).append({"name": input_name, "type": "*", "link": lid})
    for slot, ot in enumerate(src.get("outputs", [])):
        if slot == src_slot:
            ot.setdefault("links", [])
            if lid not in ot["links"]:
                ot["links"].append(lid)
    wf["last_link_id"] = lid


def apply_changes(wf: dict, key: str, disabled: list[str]) -> list[str]:
    """Setzt .disabled-Schalter; liefert Liste der abgeschalteten Funktionen."""
    changes = _changes(key)
    nodes = byid(wf)
    off = []
    for name in disabled:
        ch = changes.get(name)
        if not ch:
            continue
        for nid, mode in (ch.get("set_mode") or {}).items():
            if nid in nodes:
                nodes[nid]["mode"] = mode
        for r in (ch.get("relink") or []):
            relink(wf, r["node"], r["input"], r["to_node"], _slot_of(wf, r["to_node"], r.get("to_slot", 0)))
        off.append(name)
    return off


def _slot_of(wf: dict, nid: str, default: int = 0) -> int:
    return default


# ───────────────────────────── Referenzbilder ─────────────────────────────

def rand_name(path: Path, rng: random.Random | None = None) -> str:
    rng = rng or random
    suffix = "".join(rng.choices(string.ascii_lowercase + string.digits, k=5))
    ext = path.suffix.lower() or ".png"
    return f"mmref_{suffix}{ext}"


def stage_refs(files: list[str | Path], tgt: dict, *, copy_to_input: bool = True) -> list[str]:
    """Dateien -> ComfyUI-Input (Kopie nach comfy_dir/input UND/oder Upload). Gibt Namen zurueck."""
    names = []
    in_dir = (tgt.get("comfy_dir") / "input") if tgt.get("comfy_dir") else None
    if in_dir:
        in_dir.mkdir(parents=True, exist_ok=True)
    alive = C.server_alive(tgt["url"])
    for f in files:
        p = Path(str(f).strip('"')).expanduser()
        if not p.exists():
            alt = C.ROOT / p
            if alt.exists():
                p = alt
        if not p.exists():
            raise FileNotFoundError(f"Referenzbild nicht gefunden: {p}")
        name = rand_name(p)
        if in_dir:
            p2 = in_dir / name
            if not p2.exists():
                import shutil
                shutil.copy2(p, p2)
        if alive:
            try:
                name = upload_image(tgt["url"], p)
            except Exception as e:
                print(f"[!] Upload fehlgeschlagen ({e}) - nutze kopierte Datei {name}", file=sys.stderr)
        names.append(name)
    return names


# ───────────────────────────── Build ─────────────────────────────

ASPECTS = [
    "1:1 (Square)", "4:3 (Landscape)", "3:4 (Portrait)", "16:9 (Widescreen)",
    "9:16 (Portrait Widescreen)", "3:2 (Landscape)", "2:3 (Portrait)",
    "4:5 (Instagram Portrait)", "21:9 (Cinematic Ultrawide)",
]


def build_graph(key: str, *, prompt: str, negative: str | None = None,
                aspect: str = "16:9 (Widescreen)", megapixels: float = 0.5,
                duration: float | None = None, fps: int | None = None,
                steps: int | None = None, seed: int | None = None,
                turbo: bool = True, disabled: list[str] | None = None,
                refs: list[str] | None = None, prefix: str | None = None,
                enhance: bool = False) -> tuple[dict, dict]:
    """UI-Vorlage -> befuellter API-Graph. Gibt (api_graph, info) zurueck."""
    spec = TEMPLATES[key]
    wf = load_template(key)
    nodes = byid(wf)
    info = {"models": [], "warnings": [], "notes": [], "refs": [], "disabled": []}
    disabled = list(disabled or [])
    if not turbo:
        # "ohne Turbo" = alle optionalen Beschleuniger/Bypässe aus -> volle Qualitaet
        pass

    # ── Prompt / Negative ──
    sg_def = None
    if spec.get("subgraph_id"):
        sg_def = next((s for s in (wf.get("definitions") or {}).get("subgraphs", [])
                       if s.get("id") == spec["subgraph_id"]), None)
        if sg_def is None:
            raise TemplateError("Subgraph-Vorlage fehlt in der JSON-Datei")
        inner = {str(n["id"]): n for n in sg_def["nodes"]}
        pn = inner.get(spec.get("inner_prompt_node", "")) or _sg_widget_node(sg_def, spec["sg_prompt_widget"], "STRING")
        set_widget(pn, 0, prompt)
        dn = _sg_widget_node(sg_def, spec["sg_duration_widget"], "FLOAT")
        if duration is not None:
            set_widget(dn, 0, float(duration))
        rs = _sg_node(sg_def, "ResolutionSelector")
        if rs:
            set_widget(rs, 0, aspect)
            set_widget(rs, 1, float(megapixels))
    else:
        set_widget(nodes[spec["prompt_node"]], 0, prompt)
        rs = nodes.get(spec["aspect_node"])
        if rs:
            set_widget(rs, 0, aspect)
            set_widget(rs, 1, float(megapixels))
        if duration is not None and spec.get("duration_node"):
            set_widget(nodes[spec["duration_node"]], 0, int(duration))
        if fps and spec.get("fps_node"):
            set_widget(nodes[spec["fps_node"]], 0, int(fps))
        sw = spec.get("enhance_switch")
        if sw:
            want = bool(enhance)
            for nid in sw["set"]:
                set_widget(nodes[nid], 0, want)
            for nid in sw["switch"]:
                set_widget(nodes[nid], 0, want)
        if negative is not None and spec.get("negative_node"):
            set_widget(nodes[spec["negative_node"]], 0, negative)

    if steps and spec.get("steps_node"):
        set_widget(nodes[spec["steps_node"]], 1, int(steps))

    # ── Sigmas / Sampler-Qualitaet (LTX) ──
    sig = spec.get("sigmas")
    if sig:
        nid, val = sig["turbo" if turbo else "quality"]
        set_widget(nodes[nid], 0, val)
        if not turbo:
            info["notes"].append("Sigmas auf Qualitaetspfad (mehr Denkschritte) umgestellt")

    # ── Seed ──
    if spec.get("seed_node"):
        snode = nodes[spec["seed_node"]]
        if seed is None or seed < 0:
            s = random.randrange(2 ** 48)
            set_widget_named(snode, "noise_seed", s)
            _set_mode_fixed(snode, "randomize")
            info["notes"].append(f"Seed zufaellig: {s}")
        else:
            set_widget_named(snode, "noise_seed", int(seed))
            _set_mode_fixed(snode, "fixed")
            info["seed"] = int(seed)

    # ── Ausgabename ──
    stamp = time.strftime("%Y%m%d_%H%M%S")
    pref = prefix or f"mm_{key}_{stamp}"
    for nid in spec.get("prefix_nodes", []):
        if not set_widget_named(nodes[nid], "filename_prefix", pref):
            set_widget(nodes[nid], 0, pref)

    # ── Referenzbilder ──
    refs = refs or []
    mapping = spec.get("ref_inputs") or {}
    if mapping:
        slots = sorted(mapping.keys(), key=lambda s: int(s.rsplit("_", 1)[1]))
        used = 0
        for i, name in enumerate(refs[:len(slots)]):
            for nid in mapping[slots[i]]:
                if nid in nodes:
                    set_widget_named(nodes[nid], "image", name)
                    used += 1
                    info["refs"].append(name)
        # ungenutzte LoadImages abklemmen und stummschalten
        for slot in slots[len(refs):]:
            for nid in mapping[slot]:
                if nid in nodes:
                    nodes[nid]["mode"] = 2   # muted
                    _drop_input_links(wf, nodes[nid])
        if len(refs) > len(slots):
            info["warnings"].append(f"{len(refs)} Bilder gegeben, Vorlage hat nur {len(slots)} Slots - Rest ignoriert")
    elif refs and spec.get("ref_subgraph_input"):
        # LTX: erstes Bild in den Vision-/Upsampler-Subgraph fuehren
        info["notes"].append("LTX: Referenzbild(er) wirken erst mit aktivem Prompt-Upsampler (Schalter 'upsampler')")

    # ── Optionale Zweige abschalten ──
    wanted_off = set(disabled)
    if not turbo:
        wanted_off |= set(spec.get("changes", {}))   # ohne Turbo: alle Extras aus
    info["disabled"] = apply_changes(wf, key, sorted(wanted_off))

    # ── API-Graph erzeugen ──
    api = ui_to_api(wf)
    return api, info


def _set_mode_fixed(node: dict, mode_str: str) -> None:
    for i, inp in enumerate(node.get("inputs", [])):
        w = inp.get("widget")
        if w and w.get("name") in ("fixed", "control_after_generate"):
            pass
    wv = node.get("widgets_values")
    if isinstance(wv, list) and len(wv) >= 2 and isinstance(wv[1], str):
        wv[1] = mode_str


def _sg_widget_node(sg: dict, widget_idx: int, out_name: str) -> dict:
    for n in sg["nodes"]:
        if n.get("type") in ("PrimitiveStringMultiline", "PrimitiveFloat", "PrimitiveInt"):
            outs = [o.get("name") for o in n.get("outputs", [])]
            if out_name in outs:
                return n
    raise TemplateError(f"Subgraph-Widget #{widget_idx} ({out_name}) nicht gefunden")


def _sg_node(sg: dict, type_name: str) -> dict | None:
    return next((n for n in sg["nodes"] if n.get("type") == type_name), None)


def _drop_input_links(wf: dict, node: dict) -> None:
    nodes = byid(wf)
    for inp in node.get("inputs", []):
        lid = inp.get("link")
        if lid is None:
            continue
        inp["link"] = None
        l = next((x for x in wf["links"] if x[0] == lid), None)
        if l:
            sn = nodes.get(str(l[1]))
            if sn:
                for ot in sn.get("outputs", []):
                    if isinstance(ot.get("links"), list) and lid in ot["links"]:
                        ot["links"].remove(lid)
        wf["links"] = [x for x in wf["links"] if x[0] != lid]


def _sg_output_slot(sg_def: dict, out_name: str) -> int:
    for i, o in enumerate(sg_def.get("outputs", [])):
        if o.get("name") == out_name:
            return i
    return 0


def ui_to_api(wf: dict) -> dict:
    """UI-Workflow (nodes+links, inkl. Subgraphen) -> API-Graph fuer POST /prompt."""
    nodes = {str(n["id"]): n for n in wf["nodes"]}
    links = {l[0]: l for l in wf.get("links", [])}
    sub_defs = {s["id"]: s for s in (wf.get("definitions") or {}).get("subgraphs", [])}
    api: dict[str, dict] = {}

    def widget_value(node: dict, name: str):
        wv = node.get("widgets_values")
        if isinstance(wv, dict):
            return wv.get(name)
        if isinstance(wv, list):
            for i, inp in enumerate(node.get("inputs", [])):
                w = inp.get("widget")
                if w and w.get("name") == name:
                    return wv[i] if i < len(wv) else None
            m = re.search(r"\d+", name)  # value_3 -> Index 3 (Subgraph-Widgets)
            if name.startswith("value") and m:
                idx = int(m.group())
                return wv[idx] if idx < len(wv) else None
            if name == "value" and wv:
                return wv[0]
        return None

    def collect(n: dict, target: dict) -> None:
        cls = n["type"]
        if cls in sub_defs:
            expand_subgraph(sub_defs[cls], n, target)
            return
        inputs: dict = {}
        for inp in n.get("inputs", []):
            lid = inp.get("link")
            if lid is None:
                continue
            l = links.get(lid)
            if not l:
                continue
            sn = nodes.get(str(l[1]))
            if sn is None:
                continue
            if sn["type"] in sub_defs:
                # Wert aus Subgraph-Ausgabe ziehen
                sgd = sub_defs[sn["type"]]
                oname = sgd["outputs"][l[2]]["name"] if l[2] < len(sgd.get("outputs", [])) else None
                inner_out = _subgraph_inner_value(sgd, oname)
                if inner_out is not None:
                    inputs[inp["name"]] = inner_out
                continue
            inputs[inp["name"]] = [str(l[1]), l[2]]
        for wname in _widget_names(n):
            if wname in inputs:
                continue
            v = widget_value(n, wname)
            if v is not None:
                inputs[wname] = v
        target[str(n["id"])] = {"class_type": cls, "inputs": inputs}

    def _widget_names(n: dict) -> list[str]:
        wv = n.get("widgets_values")
        if isinstance(wv, dict):
            return [k for k in wv if k not in ("videopreview",)]
        names = []
        for inp in n.get("inputs", []):
            w = inp.get("widget")
            if w:
                names.append(w["name"])
        if not names and isinstance(wv, list):
            # Fallback: object_info-Reihenfolge ist hier nicht bekannt -> leer
            pass
        return names

    def _subgraph_inner_value(sgd: dict, out_name: str | None):
        """Findet den inneren Knoten einer Subgraph-Ausgabe (Primitive -> Konstante)."""
        if out_name is None:
            return None
        onode = next((n for n in sgd["nodes"] if n["id"] == sgd.get("outputNode", {}).get("id")), None)
        for o in (onode or {}).get("outputs", []):
            pass
        # Ausgabe-Link des outputNode (-20) rueckwaerts verfolgen
        olinks = {l["id"]: l for l in sgd.get("links", [])}
        out_entry = next((o for o in sgd.get("outputs", []) if o["name"] == out_name), None)
        if not out_entry:
            return None
        lids = out_entry.get("linkIds", [])
        if not lids:
            return None
        cur = olinks.get(lids[0])
        seen = 0
        while cur and seen < 12:
            src = next((n for n in sgd["nodes"] if n["id"] == cur["origin_id"]), None)
            if src is None:
                return None
            if src["type"] in ("PrimitiveStringMultiline", "PrimitiveFloat", "PrimitiveInt", "PrimitiveBoolean", "CR Text"):
                wv = src.get("widgets_values")
                return wv[0] if isinstance(wv, list) and wv else None
            ins = [i for i in src.get("inputs", []) if i.get("link") is not None]
            if not ins:
                return None
            nxt = olinks.get(ins[0]["link"])
            if nxt is None:
                return None
            cur = nxt
            seen += 1
        return None

    def expand_subgraph(sgd: dict, outer_node: dict, target: dict) -> None:
        """Subgraph inline aufloesen: innere Knoten + Verdrahtung nach aussen."""
        inodes = {str(n["id"]): n for n in sgd["nodes"]}
        ilinks = {l["id"]: l for l in sgd.get("links", [])}
        prefix = f"sg{outer_node['id']}_"

        def local_collect(n: dict, t: dict) -> None:
            inputs = {}
            for inp in n.get("inputs", []):
                lid = inp.get("link")
                if lid is None:
                    continue
                l = ilinks.get(lid)
                if not l:
                    continue
                if l["origin_id"] == -10:      # Subgraph-Eingang <- aeltere Knotenwert
                    sginp = sgd["inputs"][l["origin_slot"]]
                    val = _outer_input_value(outer_node, sginp["name"])
                    if isinstance(val, list):
                        inputs[inp["name"]] = val
                    elif val is not None:
                        inputs[inp["name"]] = val
                    continue
                inputs[inp["name"]] = [prefix + str(l["origin_id"]), l["origin_slot"]]
            wv = n.get("widgets_values")
            if isinstance(wv, dict):
                for k, v in wv.items():
                    if k != "videopreview" and k not in inputs and v is not None:
                        inputs[k] = v
            elif isinstance(wv, list):
                for i, inp in enumerate(n.get("inputs", [])):
                    w = inp.get("widget")
                    if w and i < len(wv) and wv[i] is not None:
                        inputs[w["name"]] = wv[i]
            t[prefix + str(n["id"])] = {"class_type": n["type"], "inputs": inputs}

        for n in sgd["nodes"]:
            local_collect(n, target)
        # Ausgaben des Subgraphs -> externe Abnehmer: Links der ausseren Outputs
        for oi in outer_node.get("inputs", []):
            pass
        # aeusserer Knoten leitet durch: seine outputs[].links zeigen auf Ziele mit slot-Typ
        for sgi_idx, sgo in enumerate(sgd.get("outputs", [])):
            # innerer Wert fuer jeden externen Verbraucher bestimmen
            val = _subgraph_inner_value(sgd, sgo["name"])
            onode = nodes_by_outer_target(outer_node["id"], sgi_idx)
            for (tid, tslot, tname) in onode:
                t = api.get(str(tid))
                if t is None:
                    continue
                if isinstance(val, list):
                    t["inputs"][tname] = val
                elif val is not None:
                    t["inputs"][tname] = val

    def nodes_by_outer_target(oid: int, out_slot: int) -> list[tuple[int, int, str]]:
        res = []
        for l in wf.get("links", []):
            if l[1] == oid and l[2] == out_slot:
                tn = nodes.get(str(l[3]))
                if tn:
                    for inp in tn.get("inputs", []):
                        if inp.get("link") == l[0]:
                            res.append((l[3], l[4], inp["name"]))
        return res

    def _outer_input_value(outer: dict, name: str):
        for inp in outer.get("inputs", []):
            if inp.get("name") != name:
                continue
            lid = inp.get("link")
            if lid is not None:
                l = links.get(lid)
                if l:
                    return [str(l[1]), l[2]]
            wv = outer.get("widgets_values")
            if isinstance(wv, list):
                idxs = [i for i, x in enumerate(outer.get("inputs", [])) if x.get("name") == name]
                if idxs and idxs[0] < len(wv):
                    return wv[idxs[0]]
            return None
        return None

    # Reihenfolge: erst normale Knoten, dann Subgraph-Werte einsetzen
    for n in wf["nodes"]:
        if n["type"] in sub_defs:
            continue
        collect(n, api)
    for n in wf["nodes"]:
        if n["type"] in sub_defs:
            expand_subgraph(sub_defs[n["type"]], n, api)

    # Subgraph-Knoten, die nie referenziert wurden, bleiben stehen (schadet nicht),
    # aber alles was von einem gemuteten Knoten abhaengtpruefen wir nicht.
    return api


# ───────────────────────────── Senden / Warten ─────────────────────────────

def submit(url: str, api: dict, timeout_s: int = 3600) -> str:
    import urllib.error
    import uuid
    cid = uuid.uuid4().hex
    try:
        res = C.http_json(url.rstrip("/") + "/prompt", {"prompt": api, "client_id": cid}, timeout=60)
    except urllib.error.HTTPError as e:
        raise RuntimeError(explain_http_error(e)) from None
    pid = res["prompt_id"]
    print(f"[i] In ComfyUI eingereiht (prompt_id {pid[:8]}) - warte ...")
    t0 = time.time()
    last = 0
    while True:
        try:
            h = C.http_json(f"{url.rstrip('/')}/history/{pid}", timeout=30)
        except Exception:
            h = {}
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                detail = ""
                for m in st.get("messages", []):
                    if m and m[0] == "execution_error":
                        d = m[1]
                        detail = f"{d.get('node_type')}: {d.get('exception_message', '').strip()}"
                raise RuntimeError(f"Fehler in ComfyUI: {detail or 'siehe ComfyUI-Konsole'}")
            if h[pid].get("outputs") is not None and st.get("completed", True):
                return pid
        el = int(time.time() - t0)
        if el - last >= 15:
            print(f"    ... {el}s", flush=True)
            last = el
        if el > timeout_s:
            raise RuntimeError(f"Zeitlimit ({timeout_s}s) ueberschritten - Job laeuft evtl. noch.")
        time.sleep(2)


def fetch_outputs(url: str, pid: str, outdir: Path) -> list[Path]:
    import urllib.parse
    import urllib.request
    h = C.http_json(f"{url.rstrip('/')}/history/{pid}", timeout=30)
    saved: list[Path] = []
    outdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for node_out in h[pid].get("outputs", {}).values():
        for item in list(node_out.get("images", [])) + list(node_out.get("videos", [])):
            q = urllib.parse.urlencode({"filename": item["filename"],
                                        "subfolder": item.get("subfolder", ""),
                                        "type": item.get("type", "output")})
            with urllib.request.urlopen(f"{url.rstrip('/')}/view?{q}", timeout=300) as r:
                data = r.read()
            n += 1
            dst = outdir / f"{Path(item['filename']).stem}_{n:02d}{Path(item['filename']).suffix}"
            dst.write_bytes(data)
            saved.append(dst)
    return saved
