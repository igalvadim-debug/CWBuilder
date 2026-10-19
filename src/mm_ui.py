# -*- coding: utf-8 -*-
"""CWBuilder - Gradio-Oberflaeche (mm_ui.py).

Start:  python src\\mm.py ui   |   ui.bat   |   start.bat -> Menuepunkt [G]

Bewusst minimal: Prompt oben, Modus waehlen, darunter nur die zum Modus
passenden Optionen. Alles hat sinnvolle Defaults; Turbo ist standardmaessig AN
(bei anderer Modellwahl per Gaechen abschaltbar). Die Video-Modi LTX-2.5 und
MiniMax-H3 nutzen die eingebauten, optimierten Workflow-Vorlagen aus dem
output/-Ordner - ohne Playwright. Referenzbilder bekommen automatische
Zufallsnamen und werden nach <ComfyUI>/input kopiert.

Letzte Auswahl wird in ui_state.json gemerkt.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import gradio as gr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mm_common as C          # noqa: E402
import mm_builtin as B         # noqa: E402


CFG = C.load_config()
STATE_PATH = C.ROOT / "ui_state.json"
_lock = threading.Lock()

IMAGE_MODES = ["krea2", "klein9b", "klein4b", "qwen21", "qwen-edit", "zimage", "flux3",
               "moss_t2i", "moss_inpaint", "moss_detailer", "moss_prompt_enhancer", "moss_4step"]
VIDEO_MODES = ["minimax_h3", "ltx25", "html"]
MODE_LABELS = {
    "minimax_h3": "MiniMax H3 Video (eingebaut)",
    "ltx25": "LTX-2.5 Video (eingebaut)",
    "html": "Minimax HTML-Generator (alt, Playwright)",
    "krea2": "Krea 2 Bild",
    "klein9b": "FLUX.2 Klein 9B Bild",
    "klein4b": "FLUX.2 Klein 4B Bild",
    "qwen21": "Qwen Image 2.1 Bild",
    "qwen-edit": "Qwen Image Edit Bild",
    "zimage": "Z-Image Turbo Bild",
    "flux3": "FLUX.3 Bild",
    "moss_t2i": "MOSS T2I (Text zu Bild)",
    "moss_inpaint": "MOSS Inpaint",
    "moss_detailer": "MOSS Detailer (Gesichter)",
    "moss_prompt_enhancer": "MOSS Prompt Enhancer",
    "moss_4step": "MOSS 4-Step (Rapid)",
}
ALL_MODES = VIDEO_MODES + IMAGE_MODES
ASPECT_CHOICES = [(a.split(" ")[0], a) for a in B.ASPECTS]

DEFAULTS = {"mode": "minimax_h3", "aspect": "16:9 (Widescreen)", "mp": 0.5,
            "duration": 8, "fps": 24, "steps": 0, "seed": -1, "turbo": True,
            "run": True, "negative": ""}


# ───────────────────────────── Zustand ─────────────────────────────

def load_state() -> dict:
    """Gespeicherte UI-Werte mit Defaults ergaenzen; bei Lesefehlern Defaults liefern."""
    try:
        if STATE_PATH.exists():
            return {**DEFAULTS, **json.loads(C.read_text(STATE_PATH))}
    except Exception:
        pass
    return dict(DEFAULTS)


def save_state(patch: dict) -> None:
    """UI-Werte zusammenfuehren und speichern; Schreibfehler ignorieren."""
    st = load_state()
    st.update(patch)
    try:
        STATE_PATH.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ───────────────────────────── Modell-Katalog ─────────────────────────────

_cat_cache: dict[str, tuple[float, object]] = {}


def catalog_for(target_name: str):
    """Modellkatalog des Ziels liefern und fuer 60 Sekunden zwischenspeichern."""
    now = time.time()
    hit = _cat_cache.get(target_name)
    if hit and now - hit[0] < 60:
        return hit[1]
    tgt = C.target(CFG, target_name)
    cat = C.Catalog(tgt["model_roots"], url=tgt["url"])
    _cat_cache[target_name] = (now, cat)
    return cat


def combo(target_name: str, kind: str, needle: str | None = None, current: str | None = None,
          prefer: str | None = None):
    """Live-Dropdown der Modelle; Vorfilter 'needle' (Substrings, '|'-getrennt).

    'prefer' ist der modusspezifische Standard-Checkpoint: er wird gewaehlt,
    wenn 'current' leer/unbekannt ist oder nur per Teilstring matcht -
    so steht im Dropdown direkt das richtige Modell des Workflows.
    """
    cat = catalog_for(target_name)
    names = cat.names(kind)
    if needle:
        low = [x.lower() for x in needle.split("|")]
        filt = [n for n in names if any(x in n.lower() for x in low)]
        if filt:
            names = filt
    def _exact(c):
        c = c.lower()
        for n in names:
            nl = n.lower()
            base = nl.replace("\\", "/").split("/")[-1]
            if c in (nl, base, base.rsplit(".", 1)[0]):
                return n
        return None
    value = _exact(current) if current else None
    if value is None and prefer:
        value = _exact(prefer)
    if value is None and current:
        # Teilstring-Treffer des bisherigen Werts vor der Standardauswahl.
        c = _reg_ci(current)
        hits = sorted((n for n in names if c in n.lower()), key=len)
        value = hits[0] if hits else None
    if value is None:
        value = names[0] if names else None
    return gr.update(choices=names, value=value)


def _reg_ci(s: str) -> str:
    return s.lower().replace("\\", "/").split("/")[-1]


def server_status_md() -> str:
    """Erreichbarkeit der Bild- und Video-Server als Markdown anzeigen."""
    parts = []
    for name in ("image", "video"):
        t = C.target(CFG, name)
        ok = C.server_alive(t["url"], timeout=1.5)
        parts.append(f"**{name}**: {'🟢 online' if ok else '⚪ offline'} · `{t['url']}`")
    return "   |   ".join(parts)


def comfyui_health_check(target_name: str) -> tuple[bool, str, list[str], list[str]]:
    """ComfyUI Gesundheitspruefung: Erreichbarkeit, erforderliche Nodes, Modelle.

    Returns: (alive, status_md, missing_nodes, missing_models)
    """
    t = C.target(CFG, target_name)
    alive = C.server_alive(t["url"], timeout=3)
    if not alive:
        return False, f"⚪ **{target_name} ComfyUI offline** (`{t['url']}`)", [], []

    try:
        obj_info = C.http_json(t["url"].rstrip("/") + "/object_info", timeout=30)
    except Exception as e:
        return True, f"🟡 **{target_name} erreichbar aber /object_info fehlgeschlagen**: {e}", [], []

    # Required nodes per mode type
    if target_name == "image":
        required_nodes = {
            "MOSS": ["MOSSImageUNETLoader", "MOSSImageCLIPLoader", "RapidMOSSAdapter", "InpaintModelConditioning"],
            "Krea2": ["Krea2ControlLoRALoader", "Krea2ControlApply", "Krea2ControlImageEncode"],
            "Qwen21": ["TextEncodeQwenImage21", "QwenImage21Cache", "QwenImageDiffsynthControlnet"],
            "Flux3": ["Flux3ImageGuidanceEmbedder", "Flux2Scheduler"],
            "ZImage": ["CheckpointLoaderSimple"],
            "Klein": ["EmptyFlux2LatentImage", "Flux2Scheduler", "CFGGuider"],
            "General": ["CheckpointLoaderSimple", "CLIPLoader", "VAELoader", "KSampler", "SaveImage"]
        }
        required_models = {
            "moss_t2i": ["moss_image_sft_int8_convrot.safetensors", "qwen3.5_9b_int8_convrot.safetensors", "flux2_vae.safetensors"],
            "moss_inpaint": ["moss_image_sft_int8_convrot.safetensors", "qwen3.5_9b_int8_convrot.safetensors", "flux2_vae.safetensors"],
            "moss_detailer": ["moss_image_sft_int8_convrot.safetensors", "qwen3.5_9b_int8_convrot.safetensors", "flux2_vae.safetensors"],
            "moss_4step": ["moss_image_sft_int8_convrot.safetensors", "qwen3.5_9b_int8_convrot.safetensors", "flux2_vae.safetensors", "rapid-moss-4step"],
            "moss_prompt_enhancer": [],
        }
    else:  # video
        required_nodes = {
            "LTX": ["LTXVideoModelLoader", "LTXVideoSampler", "LTXVideoConditioner"],
            "MiniMax": [],
            "General": ["CheckpointLoaderSimple", "CLIPLoader", "VAELoader", "KSampler", "SaveImage"]
        }
        required_models = {}

    missing_nodes = []
    for category, nodes in required_nodes.items():
        for node in nodes:
            if node not in obj_info:
                missing_nodes.append(f"{category}: {node}")

    # Check models via catalog
    cat = catalog_for(target_name)
    missing_models = []
    if target_name == "image":
        for mode_key, models in required_models.items():
            for model in models:
                kind = "unet"
                if "text" in model.lower() or "clip" in model.lower() or "qwen3" in model.lower() or "gemma" in model.lower():
                    kind = "text_encoders"
                elif "vae" in model.lower():
                    kind = "vae"
                elif "lora" in model.lower() or "rapid-moss" in model.lower():
                    kind = "loras"
                try:
                    cat.pick(kind, [model], required=True)
                except Exception:
                    missing_models.append(f"{mode_key}: {model} ({kind})")

    status = "🟢 **Alles OK**" if not missing_nodes and not missing_models else              "🟡 **Warnungen**" if missing_nodes and not missing_models else              "🔴 **Kritisch**"

    md = f"{status} · `{t['url']}`"
    if missing_nodes:
        md += f"\n\n**Fehlende Nodes ({len(missing_nodes)}):**\n" + "\n".join(f"- {n}" for n in missing_nodes[:10])
        if len(missing_nodes) > 10:
            md += f"\n- ... und {len(missing_nodes) - 10} weitere"
    if missing_models:
        md += f"\n\n**Fehlende Modelle ({len(missing_models)}):**\n" + "\n".join(f"- {m}" for m in missing_models[:10])
        if len(missing_models) > 10:
            md += f"\n- ... und {len(missing_models) - 10} weitere"

    return alive, md, missing_nodes, missing_models


def open_output_folder():
    """Oeffnet den Output-Ordner im Dateimanager."""
    out_dir = C.output_dir(CFG)
    try:
        if os.name == "nt":
            os.startfile(str(out_dir))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(out_dir)])
        else:
            subprocess.run(["xdg-open", str(out_dir)])
        return f"Geoeffnet: {out_dir}"
    except Exception as e:
        return f"Fehler beim Oeffnen: {e}"


# ───────────────────────────── Sichtbarkeit je Modus ─────────────────────────────

def layout_for(mode: str) -> dict:
    """Sichtbarkeit der Optionsgruppen fuer den gewaehlten Modus bestimmen."""
    v = mode in VIDEO_MODES
    img = mode in IMAGE_MODES
    edit = mode in ("qwen-edit", "qwen21", "klein9b", "klein4b", "flux3", "minimax_h3",
                    "moss_inpaint", "moss_detailer")
    htmlm = mode == "html"
    moss_modes = mode in ("moss_t2i", "moss_inpaint", "moss_detailer", "moss_prompt_enhancer", "moss_4step")
    return {
        "refs": edit and not htmlm,
        "aspect": v and not htmlm, "mp": v and not htmlm,
        "dur": v and not htmlm, "fps": v and not htmlm,
        "steps": (img or mode == "minimax_h3") and not htmlm,
        "turbo": (img or v) and not htmlm,
        "extras": mode in ("ltx25", "minimax_h3"),
        "neg": img or mode == "ltx25",
        "wh": img,
        "models": img,
        "control": mode in ("qwen21", "zimage", "klein9b", "klein4b",
                            "moss_inpaint", "moss_detailer"),
        "moss_inpaint_opts": mode == "moss_inpaint",
        "moss_detailer_opts": mode == "moss_detailer",
        "moss_prompt_opts": mode == "moss_prompt_enhancer",
    }


# ───────────────────────────── Erzeugen ─────────────────────────────

def do_generate(prompt, mode, aspect, mp, duration, fps, steps, turbo, extras_off,
                seed, negative, ref_files, width, height, batch,
                unet, clip, vae, loras_txt, loras_sel=None, control_on=False,
                control_kind=None, control_img=None,
                run_now=True, out_json="", progress=gr.Progress()):
    """Workflow erstellen und speichern, optional ausfuehren und Ergebnisse abrufen.

    Gibt Protokolltext sowie Gradio-Updates fuer Video und Bilder zurueck.
    Die Generierung wird ueber den gemeinsamen Lock serialisiert.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        pf = C.abspath(CFG.get("prompt_file", "prompts/prompt.txt"))
        if pf.exists():
            prompt = C.read_text(pf).strip()
    if not prompt:
        raise gr.Error("Kein Prompt - Text eingeben oder prompts/prompt.txt fuellen.")
    lines: list[str] = []

    def log(s):
        """Nachricht im Terminal ausgeben und fuer das Ergebnisprotokoll sammeln."""
        print(s, flush=True)
        lines.append(str(s))

    def resolve_out(p: str, stamp: str) -> Path:
        """Ausgabepfad relativ zur Projektwurzel oder mit Standardnamen bestimmen."""
        p = (p or "").strip()
        if not p:
            return C.output_dir(CFG) / f"mm_{mode}_{stamp}.api.json"
        q = Path(p).expanduser()
        return q if q.is_absolute() else C.ROOT / q

    with _lock:
        # ---------- eingebaute Video-Workflows (LTX-2.5 / MiniMax-H3) ----------
        if mode in ("minimax_h3", "ltx25"):
            tgt = C.target(CFG, "video")
            disabled = list(extras_off or [])
            if not turbo:
                disabled = sorted(set(disabled) | set(B.TEMPLATES[mode]["changes"]))
            files = [f for f in (ref_files or []) if f]
            ref_names: list[str] = []
            if files:
                progress(0.05, desc="Referenzbilder kopieren")
                ref_names = B.stage_refs(files, tgt)
                log(f"[i] {len(ref_names)} Referenzbild(er) mit Zufallsnamen nach "
                    f"{tgt['comfy_dir']}\\input: " + ", ".join(ref_names))
            progress(0.15, desc="Workflow aufbauen")
            api, info = B.build_graph(
                mode, prompt=prompt, negative=negative or None, aspect=aspect,
                megapixels=float(mp or 0.5), duration=float(duration or 8),
                fps=int(fps) if fps else None, steps=int(steps) if steps else None,
                seed=int(seed) if seed is not None and int(seed) >= 0 else None,
                turbo=bool(turbo), disabled=disabled, refs=ref_names)
            for n in info["notes"]:
                log("[i] " + n)
            for w in info["warnings"]:
                log("[!] " + w)
            if info["disabled"]:
                ch = B._changes(mode)
                log("[i] abgeschaltet: " + "; ".join(ch.get(k, {}).get("label", k) for k in info["disabled"]))
            stamp = C.timestamp()
            jpath = resolve_out(out_json, stamp)
            jpath.parent.mkdir(parents=True, exist_ok=True)
            jpath.write_text(json.dumps(api, indent=2, ensure_ascii=False), encoding="utf-8")
            log(f"[OK] Workflow (API-Format, direkt sendbar): {jpath}")
            if run_now:
                from mm import ensure_server
                if not ensure_server(tgt, True):
                    raise gr.Error(f"Video-ComfyUI ({tgt['url']}) nicht erreichbar - Autostart fehlgeschlagen.")
                progress(0.3, desc="In ComfyUI (Video) laufen lassen")
                pid = B.submit(tgt["url"], api, timeout_s=3600)
                progress(0.9, desc="Ergebnis holen")
                saved = B.fetch_outputs(tgt["url"], pid, C.output_dir(CFG))
                vids = [s for s in saved if s.suffix.lower() in (".mp4", ".webm", ".mkv", ".gif")]
                imgs = [s for s in saved if s.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
                for s in saved:
                    log(f"[OK] Datei: {s}")
                return ("\n".join(lines),
                        gr.update(value=str(vids[-1])) if vids else gr.update(),
                        gr.update(value=[str(i) for i in imgs]) if imgs else gr.update())
            return "\n".join(lines), gr.update(), gr.update()

        # ---------- alter HTML-Generator (Playwright) ----------
        if mode == "html":
            import mm_video as V
            overrides = {"steps": int(steps) if steps else None,
                         "default_duration": int(duration) if duration else None,
                         "base_seed": int(seed) if seed is not None and int(seed) >= 0 else None}
            path = V.run(CFG, text=prompt, file=None, out=(out_json or None), overrides=overrides)
            log(f"[OK] Workflow gespeichert: {path}")
            log("[i] In der Video-ComfyUI per Drag&Drop laden und Queue druecken.")
            return "\n".join(lines), gr.update(), gr.update()

        # ---------- Bild-Modi ----------
        import mm_images as I
        # Start: Modellordner gemaess config.json scannen und docs/models.txt
        # aktualisieren (ergaenzt neue, entfernt verschwundene Dateien).
        try:
            reg = I.scan_model_registry()
            if reg.get("skipped"):
                log("[i] Modell-Scan: keine Root-Ordner auf diesem System - "
                    f"docs/models.txt bleibt unveraendelt ({reg['total']} Eintraege).")
            elif reg["added"] or reg["removed"]:
                log(f"[i] Modell-Scan: {reg['added']} neu, {reg['removed']} entfernt "
                    f"-> {reg['path']} ({reg['total']} Eintraege).")
        except Exception as e:
            log(f"[!] Modell-Scan fehlgeschlagen (weiter mit bestehender Liste): {e}")
        tgt = C.target(CFG, "image")
        progress(0.1, desc="Modelle bestimmen")
        cat = catalog_for("image")
        alive = C.server_alive(tgt["url"])
        staged = [I.stage_image(f, tgt, upload=alive) for f in (ref_files or []) if f]
        ctrl = I.stage_image(control_img, tgt, upload=alive) if control_img else None
        loras = []
        # Auswahl aus dem LoRA-Vorschlag: Label 'name.ext  [Trigger]' -> Pfad relativ
        # zum Root, in dem die Datei laut models.txt liegt (ComfyUI-Subpfad).
        label_paths = dict(I.loras_for_mode(mode, unet or None)) if loras_sel else {}
        reg_entries = I.load_models_txt() if label_paths else []
        for lbl in (loras_sel or []):
            fp = label_paths.get(lbl)
            if not fp:
                continue
            rel = Path(fp).name
            norm = fp.replace("\\", "/").lower()
            for e in reg_entries:
                ef = e["full"].replace("\\", "/")
                if ef.replace("\\", "/").lower() == norm and e["root"]:
                    rel = ef[len(e["root"].rstrip("/")) + 1:]
                    break
            loras.append((rel, 1.0))
        for it in (loras_txt or "").split(","):
            it = it.strip()
            if not it:
                continue
            name, strength = it, 1.0
            if ":" in it:
                head, tail = it.rsplit(":", 1)
                try:
                    name, strength = head.strip(), float(tail)
                except ValueError:
                    pass
            loras.append((name, strength))
        img_cfg = CFG["image"]
        p = I.Params(
            mode=mode, prompt=prompt, negative=negative or img_cfg.get("negative", ""),
            width=int(width or img_cfg["width"]), height=int(height or img_cfg["height"]),
            size_explicit=bool(width and height),
            steps=int(steps) if steps else None,
            seed=int(seed) if seed is not None and int(seed) >= 0 else -1,
            batch=int(batch or 1), loras=loras,
            turbo=("auto" if turbo else "off"),
            unet=unet or None, clip=clip or None, vae=vae or None,
            images=staged,
            control=(control_kind if control_on else None), control_image=ctrl,
        )
        progress(0.3, desc="Workflow aufbauen")
        nodes, info = I.build(p, cat)
        log(I.report(p, info, tgt["url"]))
        problems = I.validate(nodes, cat.object_info) if cat.object_info else []
        for x in problems[:8]:
            log("[!] " + x)
        stamp = C.timestamp()
        jpath = resolve_out(out_json, stamp)
        jpath.parent.mkdir(parents=True, exist_ok=True)
        jpath.write_text(json.dumps(nodes, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"[OK] Workflow (API-Format): {jpath}")
        if run_now:
            if problems:
                log("[!] Validierungsfehler - nicht gesendet (Liste oben).")
                return "\n".join(lines), gr.update(), gr.update()
            from mm import ensure_server
            if not ensure_server(tgt, True):
                raise gr.Error(f"Bild-ComfyUI ({tgt['url']}) nicht erreichbar - Autostart fehlgeschlagen.")
            progress(0.5, desc="In ComfyUI (Bild) laufen lassen")
            saved = I.run_on_server(tgt["url"], nodes, C.output_dir(CFG) / f"mm_{mode}_{stamp}",
                                    int(img_cfg["timeout_s"]))
            for s in saved:
                log(f"[OK] Bild: {s}")
            return ("\n".join(lines), gr.update(),
                    gr.update(value=[str(s) for s in saved]) if saved else gr.update())
        return "\n".join(lines), gr.update(), gr.update()


# ───────────────────────────── GUI ─────────────────────────────

CSS = ".tiny {font-size:12px;color:#888;} footer {display:none!important;}"

def _gradio_version() -> tuple:
    """Gradio-Version als Tuple (major, minor) liefern; bei Fehler (0, 0)."""
    try:
        parts = str(getattr(gr, "__version__", "")).split(".")
        return (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return (0, 0)


def build_ui() -> gr.Blocks:
    """Gradio-Oberflaeche mit gespeicherten Werten und Ereignis-Callbacks erstellen."""
    st = load_state()
    # Gradio < 6: theme/css gehoeren in den Blocks-Konstruktor.
    init_kwargs = {}
    if _gradio_version() < (6, 0):
        init_kwargs = {"css": CSS, "theme": gr.themes.Soft()}
    with gr.Blocks(title="CWBuilder", **init_kwargs) as app:
        gr.Markdown("## CWBuilder — ComfyUI Generator\n"
                    "<span class='tiny'>Nur Prompt schreiben und ERZEUGEN druecken - der Rest "
                    "hat Defaults. Turbo ist an; bei anderer Modellwahl abschaltbar.</span>")
        status = gr.Markdown(server_status_md())

        mode = gr.Radio([(MODE_LABELS[m], m) for m in ALL_MODES], value=st["mode"],
                                label="Modus")
        prompt = gr.Textbox(label="Prompt", lines=5,
                            placeholder="Hier reinkopieren - leer lassen = prompts/prompt.txt")
        refs = gr.File(label="Referenzbilder (Zufallsname + Copy nach ComfyUI\\input)",
                       file_count="multiple", file_types=["image"])

        with gr.Row():
            aspect = gr.Dropdown(ASPECT_CHOICES, value=st["aspect"], label="Format")
            mp = gr.Number(value=st["mp"], label="Megapixels", precision=2)
            duration = gr.Number(value=st["duration"], label="Dauer (Sek.)", precision=0)
            fps = gr.Number(value=st["fps"], label="FPS", precision=0)
            steps = gr.Number(value=st["steps"], label="Steps (0 = Standard)", precision=0)
        with gr.Row():
            turbo = gr.Checkbox(value=st["turbo"], label="Turbo (Standard)")
            seed = gr.Number(value=st["seed"], label="Seed (-1 = zufaellig)", precision=0)
            run_now = gr.Checkbox(value=st["run"], label="Sofort ausfuehren")
        extras = gr.CheckboxGroup(choices=[], value=[], label="Extras abschalten")
        negative = gr.Textbox(label="Negative Prompt", value=st["negative"], lines=2)

        with gr.Row(visible=False) as models_row:
            # Checkpoints in zwei Reihen, damit fuer die LoRA-Auswahl genug Platz bleibt.
            with gr.Row():
                unet = gr.Dropdown(label="Diffusion-Modell", choices=[], allow_custom_value=True)
                clip = gr.Dropdown(label="Text-Encoder", choices=[], allow_custom_value=True)
            with gr.Row():
                vae = gr.Dropdown(label="VAE", choices=[], allow_custom_value=True)
                loras_txt = gr.Textbox(label="LoRAs extra (Name:Staerke, Komma)", value="",
                                       info="Eintrag aus der Auswahl oben: Name; eigener Eintrag: Name:1.0")
            loras_pick = gr.CheckboxGroup(choices=[], label="LoRAs fuer dieses Modell (Vorschlag)", value=[])

        with gr.Row(visible=False) as wh_row:
            width = gr.Number(value=CFG["image"]["width"], label="Breite", precision=0)
            height = gr.Number(value=CFG["image"]["height"], label="Hoehe", precision=0)
            batch = gr.Number(value=1, label="Batch", precision=0)

        with gr.Row(visible=False) as ctl_row:
            ctl_on = gr.Checkbox(value=False, label="ControlNet")
            ctl_kind = gr.Dropdown(["auto", "union", "tile", "depth"], value="auto", label="Typ")
            ctl_img = gr.Image(type="filepath", label="Control-Bild")

        # Per-mode option groups
        with gr.Row(visible=False) as moss_inpaint_row:
            moss_mask_grow = gr.Number(value=8, label="Masken-Wachstum (px)", precision=0)
            moss_mask_blur = gr.Number(value=4, label="Masken-Weichzeichner (px)", precision=0)
            moss_inpaint_engine = gr.Dropdown(["auto", "standard", "lama", "sd"], value="auto", label="Inpaint-Engine")

        with gr.Row(visible=False) as moss_detailer_row:
            moss_face_count = gr.Slider(minimum=1, maximum=4, value=1, step=1, label="Anzahl Gesichter (1-4)")
            moss_seedvr2 = gr.Checkbox(value=False, label="SeedVR2 Upscale (nach Detailer)")

        with gr.Row(visible=False) as moss_prompt_row:
            moss_prompt_llm = gr.Dropdown(["auto", "qwen3vl", "chatgpt", "llama"], value="auto", label="LLM fuer Prompt-Enhancement")
            moss_prompt_handoff = gr.Checkbox(value=True, label="Enhanced Prompt an T2I uebergeben")

        out_json = gr.Textbox(label="Workflow-Datei (leer = output/mm_<modus>_<zeit>.api.json)", value="")
        btn = gr.Button("ERZEUGEN", variant="primary", size="lg")

        with gr.Row():
            log_box = gr.Textbox(label="Protokoll", lines=12)
            with gr.Column():
                video_out = gr.Video(label="Video")
                gallery = gr.Gallery(label="Bilder", columns=2)
                open_folder_btn = gr.Button("📁 Output-Ordner oeffnen", variant="secondary")

        # Health check row
        with gr.Row():
            health_image = gr.Markdown("Bild-ComfyUI: pruefen...")
            health_video = gr.Markdown("Video-ComfyUI: pruefen...")
            health_refresh = gr.Button("🔄 Pruefen", variant="secondary", size="sm")

        def lora_suggestions(m, u):
            """LoRA-Vorschlaege (Label, Pfad) zum Modus und gewaehltem Diffusionsmodell."""
            import mm_images as I
            try:
                return I.loras_for_mode(m, u or None)
            except Exception:
                return []

        def apply_mode(m, u, c, v):
            """Modus speichern und Sichtbarkeits- sowie Modell-Dropdown-Updates liefern."""
            import mm_images as I
            vis = layout_for(m)
            save_state({"mode": m})
            tgt_name = "video" if m in VIDEO_MODES else "image"
            needle_u = {"ltx25": "ltx", "minimax_h3": "minimax|h3"}.get(m)
            ch = B._changes("ltx25" if m == "ltx25" else "minimax_h3") \
                if m in ("ltx25", "minimax_h3") else {}
            uu = combo(tgt_name, "unet", needle_u, u, prefer=I.default_unet_for(m))
            sel_u = uu.get("value") if isinstance(uu, dict) else None
            picks = lora_suggestions(m, sel_u or u)
            return (
                gr.update(visible=vis["refs"]),
                gr.update(visible=vis["aspect"]), gr.update(visible=vis["mp"]),
                gr.update(visible=vis["dur"]), gr.update(visible=vis["fps"]),
                gr.update(visible=vis["steps"]), gr.update(visible=vis["turbo"]),
                gr.update(choices=[(lbl, k) for k, lbl in ch.items()], value=[],
                          visible=vis["extras"]),
                gr.update(visible=vis["neg"]),
                gr.update(visible=vis["models"]),
                gr.update(visible=vis["wh"]), gr.update(visible=vis["control"]),
                uu,
                combo(tgt_name, "text_encoders", needle_u, c),
                combo(tgt_name, "vae", needle_u, v),
                gr.update(choices=[lbl for lbl, _ in picks], value=[]),
                gr.update(visible=vis["moss_inpaint_opts"]),
                gr.update(visible=vis["moss_detailer_opts"]),
                gr.update(visible=vis["moss_prompt_opts"]),
            )

        def refresh_loras(m, u):
            """LoRA-Auswahl erneut füllen, wenn das Diffusionsmodell wechselt."""
            return gr.update(choices=[lbl for lbl, _ in lora_suggestions(m, u)], value=[])

        outputs = [refs, aspect, mp, duration, fps, steps, turbo, extras, negative,
                   models_row, wh_row, ctl_row, unet, clip, vae, loras_pick,
                   moss_inpaint_row, moss_detailer_row, moss_prompt_row]
        mode.change(apply_mode, [mode, unet, clip, vae], outputs)
        unet.change(refresh_loras, [mode, unet], loras_pick)

        def gen(*a):
            """Dateieingaben normalisieren, Generierung starten und erfolgreiche Auswahl speichern."""
            (prompt_v, mode_v, aspect_v, mp_v, dur_v, fps_v, steps_v, turbo_v, off_v,
             seed_v, neg_v, ref_v, w_v, h_v, b_v, unet_v, clip_v, vae_v, picks_v, loras_v,
             ctl_on_v, ctl_kind_v, ctl_img_v, run_v, out_v) = a
            files = [f if isinstance(f, str) else getattr(f, "name", "") for f in (ref_v or [])]
            res = do_generate(prompt_v, mode_v, aspect_v, mp_v, dur_v, fps_v, steps_v,
                              turbo_v, off_v, seed_v, neg_v, files, w_v, h_v, b_v,
                              unet_v, clip_v, vae_v, loras_v, picks_v,
                              ctl_on_v, ctl_kind_v,
                              ctl_img_v, run_v, out_v)
            save_state({"mode": mode_v, "aspect": aspect_v, "mp": mp_v,
                        "duration": dur_v, "fps": fps_v, "steps": steps_v,
                        "turbo": turbo_v, "seed": seed_v, "negative": neg_v,
                        "run": run_v, "unet": unet_v, "clip": clip_v, "vae": vae_v})
            return res

        inputs = [prompt, mode, aspect, mp, duration, fps, steps, turbo, extras, seed,
                  negative, refs, width, height, batch, unet, clip, vae, loras_pick, loras_txt,
                  ctl_on, ctl_kind, ctl_img, run_now, out_json]
        btn.click(gen, inputs, [log_box, video_out, gallery])

        def refresh_health():
            _, img_md, _, _ = comfyui_health_check("image")
            _, vid_md, _, _ = comfyui_health_check("video")
            return img_md, vid_md

        health_refresh.click(refresh_health, None, [health_image, health_video])
        open_folder_btn.click(open_output_folder, None, log_box)

        # Initial health check
        app.load(refresh_health, None, [health_image, health_video])

        gr.HTML("<div class='tiny'>Terminal: <code>start.bat</code> (Menue) oder "
                "<code>python src\\mm.py image|video ...</code> — gleicher Kern wie hier.</div>")
    return app


def main() -> None:
    """Gradio-Oberflaeche mit serieller Queue lokal auf Port 7865 starten."""
    app = build_ui()
    launch_kwargs = {"inbrowser": True}
    # Gradio >= 6: theme/css wurden vom Blocks-Konstruktor zu launch() verschoben.
    if _gradio_version() >= (6, 0):
        launch_kwargs["theme"] = gr.themes.Soft()
        launch_kwargs["css"] = CSS
    app.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=7865, share=False,
        **launch_kwargs)


if __name__ == "__main__":
    main()
