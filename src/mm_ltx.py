# -*- coding: utf-8 -*-
"""LTX-Video 2.3 / 2.5 - Workflow-Erzeugung (API-JSON) fuer die Video-ComfyUI.

Funktionen (wie Minimax H3, plus):
  * Turbo-Option: destillierte 4-8-Step-LoRAs (lightx2v / distill / turbo).
  * LoRA-Vorschlaege mit automatischem Triggerwort-Eintrag (bei mehreren
    Trigger-Wörtern wird der ERSTE verwendet).
  * Szenen-Kette: jedes naechste Video beginnt mit dem LETZTEN FRAME des
    vorherigen (ImageFromBatch -> LTXAddGuideImage latent=0) - keine Scene
    wird uebersprungen (feste Reihenfolge via verketteter Sampler).
  * Integriertes VL-LLM: beschreibt das letzte Frame-Bild und erweitert den
    Prompt der naechsten Scene direkt im Workflow.
  * Laengenangabe als "NxD" (z.B. 3x6 = 18 s); der Text wird auf genau N
    Szenen verteilt.

Node-Namen folgen ComfyUI-LTXVideo (ltx_utils.py); unbekannte Nodes werden per
/object_info auf die real vorhandenen Varianten umgebogen.
"""
from __future__ import annotations

import json
import random
import re
import urllib.error
from pathlib import Path

import mm_common as C
from mm_common import Catalog, ModelMissing, combo_options
from mm_scenes import (apply_trigger, describe_trigger_name, ltx_frames,
                       minimax_frames, parse_length_spec, scene_plan,
                       total_seconds, vl_prompt)
import mm_vllm


class Graph:
    """Minimaler API-Graph mit nummerierten Nodes."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self._n = 0

    def add(self, cls: str, **inputs) -> str:
        self._n += 1
        nid = str(self._n)
        self.nodes[nid] = {"class_type": cls, "inputs": inputs}
        return nid

    def remap(self, known: set | None):
        """Unbekannte Node-Klassen gegen reale Alternativen tauschen (best-effort)."""
        if not known:
            return
        alias = {
            "LTXVAddGuideImage": ("LTXVAddGuide", "LTXAddGuideImage"),
            "LTXVCropGuides": ("LTXVConditioning",),
            "LTXVEmptyLatentImage": ("EmptyLTXVLatentVideo", "LTXVEmptyLatentAudio"),
            "LTXVConditioning": ("LTXVConditioning",),
            "LTXVScheduler": ("LTXVScheduler",),
            "LTXVConcatConditioning": ("ConditioningConcat",),
        }
        for nid, node in list(self.nodes.items()):
            cls = node["class_type"]
            if cls in known:
                continue
            for cand in alias.get(cls, ()):
                if cand in known:
                    node["class_type"] = cand
                    break


def o(nid: str, slot: int = 0) -> list:
    return [nid, slot]


# ───────────────────────────── Modell-Auswahl ─────────────────────────────

UNET_CANDS = {
    "ltx23": ["ltx-2.3", "ltx2.3", "ltx_2.3", "ltxv-2.3", "ltxv19b_2.3", "ltx23"],
    "ltx25": ["ltx-2.5", "ltx2.5", "ltx_2.5", "ltxv-2.5", "ltx25", "redgraftltx25", "ltx2.5"],
}
TE_CANDS = {
    "ltx23": ["gemma_3_12b", "gemma-3-12b", "gemma3_12b", "gemma_3", "ltx-2.3-22b_text_projection",
              "ltx-2.3_text_projection"],
    "ltx25": ["gemma4-12b-with-proj-ltx-2.5", "gemma4_e2b", "gemma-4", "gemma4", "gemma_4"],
}
VAE_CANDS = {
    "ltx23": ["LTX23_video_vae", "ltx-2.3-video-vae", "ltx-2.3_video_vae", "ltxv192_vae", "ltxv-19b-vae",
              "ltxv.safetensors", "ltx_video"],
    "ltx25": ["ltx-2.5-video-vae", "LTX25_video_vae", "ltx-2.5-video-vae-conv"],
}
AUDIO_VAE_CANDS = {
    "ltx23": ["LTX23_audio_vae", "ltx-2.3-22b-distilled_audio_vae", "ltx-2.3-audio-vae", "LTX2_audio_vae"],
    "ltx25": ["ltx-2.5-audio-vae", "LTX25_audio_vae"],
}
CLIPV_CANDS = ["clip-vision_vit-h", "clip_vision_h", "sigclip_vision", "clip-vision_vit-g"]
UPSCALER_CANDS = {
    "ltx23": ["ltx-2.3-spatial-upscaler", "ltx-2-spatial-upscaler"],
    "ltx25": ["ltx-2.5-spatial-upscaler", "ltx-2.5-latent-spatial-upscaler", "ltx-2.5-temporal-upscaler"],
}

TURBO_LORA_CANDS = {
    "ltx23": ["ltx-2.3-22b-distilled-lora", "ltx-2.3-22b-distilled", "ltx2.3-distill", "ltx2.3-turbo",
              "lightx2v", "ltx-2.3-dmd", "ltx2.3_dmd", "ltxv-13b-0.9.7-distilled"],
    "ltx25": ["ltx25_turbo", "ltx-2.5-turbo", "ltx-2.5-distilled", "ltx-2.5-distill", "ltx2.5-turbo",
              "ltx2.5_distill", "turbo_distill"],
}
DETAIL_LORA_CANDS = ["ltx-2-19b-ic-lora-detailer", "detailer"]


def pick_models(mode: str, cat: Catalog, lcfg: dict, info: dict) -> dict:
    """Alle Modelle fuer den Modus zusammenstellen; fehlende optional -> Warnung."""
    key = "ltx23" if mode == "ltx23" else "ltx25"
    out: dict[str, str | None] = {}
    unet_c = [lcfg.get(f"diffusion_model_{key[-2:]}")] if False else []
    # explizite Konfiguration vor Automatensuche
    expl_unet = lcfg.get("diffusion_model_23") if key == "ltx23" else lcfg.get("diffusion_model_25")
    kind, uname = _pick_any(cat, "unet", ([expl_unet] if expl_unet else []) + UNET_CANDS[key])
    if uname is None:  # checkpoints?
        kind, uname = _pick_any(cat, "checkpoints", ([expl_unet] if expl_unet else []) + UNET_CANDS[key])
    if uname is None:
        raise ModelMissing(_explain(cat, "unet", UNET_CANDS[key]))
    out["unet_kind"], out["unet"] = kind, uname

    expl_te = lcfg.get("text_encoder")
    te = _pick_any(cat, "text_encoders", ([expl_te] if expl_te else []) + TE_CANDS[key], ext=".safetensors")[1] \
        or _pick_any(cat, "llm", ([expl_te] if expl_te else []) + TE_CANDS[key])[1]
    if te is None:
        raise ModelMissing(_explain(cat, "text_encoders", TE_CANDS[key]))
    out["text_encoder"] = te

    expl_vae = lcfg.get("video_vae")
    out["video_vae"] = _pick_any(cat, "vae", ([expl_vae] if expl_vae else []) + VAE_CANDS[key])[1]
    if not out["video_vae"]:
        raise ModelMissing(_explain(cat, "vae", VAE_CANDS[key]))

    expl_avae = lcfg.get("audio_vae")
    out["audio_vae"] = _pick_any(cat, "vae", ([expl_avae] if expl_avae else []) + AUDIO_VAE_CANDS[key])[1]

    expl_cv = lcfg.get("clip_vision")
    out["clip_vision"] = _pick_any(cat, "clip_vision", ([expl_cv] if expl_cv else []) + CLIPV_CANDS)[1]

    expl_up = lcfg.get("latents_upscaler")
    out["upscaler"] = _pick_any(cat, "latent_upscale_models", ([expl_up] if expl_up else []) + UPSCALER_CANDS[key])[1]
    return out


def _pick_any(cat: Catalog, kind: str, cands, ext=None):
    try:
        n = cat.pick(kind, cands, ext=ext, required=False)
    except Exception:
        n = None
    return (kind, n)


def _explain(cat: Catalog, kind: str, cands) -> str:
    try:
        cat.pick(kind, cands)   # wirft miterklaerendem Fehler
    except ModelMissing as e:
        return str(e)
    return f"{kind}: {cands}"


# ───────────────────────────── LoRA-Vorschlaege / Trigger ─────────────────────────────

def suggest_loras(mode: str, cat: Catalog, limit: int = 25) -> list[dict]:
    """Alle LTX-LoRAs mit erkanntem Triggerwort (best-effort aus dem Dateinamen)."""
    pats = ("ltx2", "ltx-2", "ltx 2", "ltxv", "ltx23", "ltx-2.3", "ltx2.3", "ltx25", "ltx-2.5", "ltx2.5")
    out = []
    for n in cat.names("loras"):
        low = n.lower()
        if not any(p in low for p in pats):
            continue
        trig = describe_trigger_name(n)
        kind = "turbo" if re.search(r"distill|turbo|lightx2v|dmd|fast|speedup|acc\d", low) else "style/IC"
        out.append({"name": n, "trigger": trig, "kind": kind})
        if len(out) >= limit:
            break
    return out


def resolve_turbo_lora(mode: str, cat: Catalog, lcfg: dict, explicit: str | None,
                       strength: float, info: dict) -> tuple[str, float] | None:
    """Turbo-LoRA: explizit > config > Automatik; Steps daraus ableiten."""
    key = "ltx23" if mode == "ltx23" else "ltx25"
    cands = ([explicit] if explicit else
             ([lcfg.get("turbo_lora_23") if key == "ltx23" else lcfg.get("turbo_lora_25")]
              if lcfg.get("turbo_lora_23" if key == "ltx23" else "turbo_lora_25") else []) + TURBO_LORA_CANDS[key])
    name = cat.pick("loras", cands, required=False)
    if not name:
        info.setdefault("warnings", []).append(
            "Turbo-LoRA nicht gefunden - Workflow nutzt Basis-Steps. Gesucht: " + ", ".join(cands[:4]))
        return None
    steps = None
    m = re.search(r"(\d+)\s*-?\s*step", name, re.I)
    if m:
        steps = int(m.group(1))
    info.setdefault("models", []).append(("Turbo-LoRA", f"{name} (x{strength})"))
    return name, strength


# ───────────────────────────── Workflow-Bau ─────────────────────────────

def build_workflow(mode: str, plan: list[dict], models: dict, *, cat: Catalog,
                   width: int, height: int, fps: int, seed: int,
                   steps: int, cfg: float, guidance: float, refine_lora: str | None,
                   turbo: tuple[str, float] | None, user_loras: list[tuple[str, float]],
                   audio: bool, vl_model: str | None, vl_max_tokens: int,
                   negative: str, output_name: str, info: dict) -> dict:
    g = Graph()
    base_seed = seed if seed >= 0 else random.randrange(2 ** 31)
    output_stem = (output_name or "ltx_video").rsplit(".", 1)[0]

    if models["unet_kind"] == "checkpoints":
        un = g.add("CheckpointLoaderSimple", ckpt_name=models["unet"])
        model, vae_auto = o(un, 0), o(un, 2)
    elif models["unet"].lower().endswith(".gguf"):
        un = g.add("UnetLoaderGGUF", unet_name=models["unet"])
        model, vae_auto = o(un), None
    else:
        un = g.add("UNETLoader", unet_name=models["unet"], weight_dtype="default")
        model, vae_auto = o(un), None

    te = models["text_encoder"]
    if te.lower().endswith(".gguf"):
        clip = o(g.add("CLIPLoaderGGUF", clip_name=te, type="ltxv"))
    else:
        clip = o(g.add("CLIPLoader", clip_name=te, type="ltxv", device="default"))
    vae = o(g.add("VAELoader", vae_name=models["video_vae"])) if models["video_vae"] else vae_auto

    loras: list[tuple[str, float]] = []
    if turbo:
        loras.append(turbo)
    loras += user_loras
    for ln, ls in loras:
        trig = describe_trigger_name(ln)
        if trig:
            info.setdefault("triggers", []).append((ln, trig))
        model = o(g.add("LoraLoaderModelOnly", model=model, lora_name=ln, strength_model=ls))

    clipv = None
    if mode == "ltx23" and models.get("clip_vision"):
        cvn = g.add("CLIPVisionLoader", ckpt_name=models["clip_vision"])
        clipv = o(cvn)

    sampler = o(g.add("KSamplerSelect", sampler_name="euler"))
    neg_txt = negative or ""

    prev_last_img: list | None = None      # IMAGE-Link des letzten Frames der Vorscene
    prev_samp: str | None = None           # Sampler der Vorscene -> harte Reihenfolge
    segments: list[tuple] = []             # (LATENT-Link, IMAGE-Sequenz-Link) je Scene
    triggers = {ln: describe_trigger_name(ln) for ln, _ in loras}

    for sc in plan:
        idx = sc["i"]
        draft = sc["prompt"] or ""
        frames = ltx_frames(sc["duration"], fps)

        # automatischer Triggerwort-Eintrag (bei mehreren LoRAs: alle ihre Triggers,
        # bei mehreren Triggerwoertern pro LoRA der ERSTE - siehe describe_trigger_name)
        prefix = " ".join(t for t in (triggers.values()) if t)
        pos_text: object = apply_trigger(draft, prefix) if idx == 1 else draft.strip()

        # VL-LLM: letztes Frame-Bild beschreiben und den Prompt der naechsten Scene
        # im Workflow erweitern (kein Skip: die Kette fuehrt durch ALLE Szenen)
        if vl_model and prev_last_img is not None:
            vlink = mm_vllm.add_vl_branch(
                g, cat, image_src=prev_last_img,
                prompt_text=vl_prompt(str(pos_text)),
                vl_model=vl_model, max_tokens=vl_max_tokens,
                seed=base_seed + idx, info=info,
                load_unet=lambda gg, kind, name: [gg.add("UnetLoaderGGUF", unet_name=name), 0])
            if vlink is not None:
                pos_text = vlink

        pos = o(g.add("CLIPTextEncode", text=pos_text, clip=clip))
        neg = o(g.add("CLIPTextEncode", text=neg_txt, clip=clip))
        pos, neg = o(g.add("LTXVConditioning", positive=pos, negative=neg, frame_rate=fps))

        lat = g.add("LTXVEmptyLatentImage", width=width, height=height, length=frames, batch_size=1)
        latent = o(lat)
        if prev_last_img is not None:
            # naechste Scene startet mit dem letzten Frame der vorherigen
            guide = g.add("LTXVAddGuideImage", positive=pos, negative=neg, vae=vae,
                          pixel_space=prev_last_img, latent=latent, frame_idx=0,
                          strength=1.0, latent_idx=-1)
            pos, neg, latent = o(guide, 0), o(guide, 1), o(guide, 2)

        noise = o(g.add("RandomNoise", noise_seed=base_seed + idx - 1))
        sig = g.add("LTXVScheduler", steps=steps, width=width, height=height,
                    frame_rate=float(fps), compression=1, shift=1.15)
        guider = g.add("CFGGuider", model=model, positive=pos, negative=neg, cfg=cfg)
        extra = {"dependency": [prev_samp, 0]} if prev_samp else {}
        samp = g.add("SamplerCustomAdvanced", noise=noise, guider=o(guider), sampler=sampler,
                     sigmas=o(sig), latent_image=latent, **extra)
        seg_lat = o(samp, 1)   # denoised_output

        if refine_lora:
            rmodel = o(g.add("LoraLoaderModelOnly", model=model, lora_name=refine_lora, strength_model=1.0))
            rguider = g.add("CFGGuider", model=rmodel, positive=pos, negative=neg, cfg=cfg)
            rsig = g.add("BasicScheduler", model=rmodel, steps=4, scheduler="simple")
            rn = o(g.add("RandomNoise", noise_seed=base_seed + 1000 + idx))
            rsamp = g.add("SamplerCustomAdvanced", noise=rn, guider=o(rguider), sampler=sampler,
                          sigmas=o(rsig), latent_image=seg_lat, denoise=refine_denoise(info))
            seg_lat = o(rsamp, 1)
            samp = rsamp

        dec = g.add("VAEDecode", samples=seg_lat, vae=vae)
        img_seq = o(dec)
        last = g.add("ImageFromBatch", image=img_seq, batch_index=-1, width=1, height=1)
        g.add("SaveImage", images=o(last), filename_prefix=f"{output_stem}_scene_{idx:02d}_lastframe")
        prev_last_img = o(last)
        prev_samp = str(samp)
        segments.append((seg_lat, img_seq))

    # Videos je Scene erzeugen und in Reihenfolge aneinanderhaengen
    vids: list[list] = []
    for seg_lat, img_seq in segments:
        cv = g.add("CreateVideo", images=img_seq, fps=float(fps))
        vids.append(o(cv))
    cur = vids[0]
    for nxt in vids[1:]:
        cur = o(g.add("ExtendVideo", video1=cur, video2=nxt))
    g.add("SaveVideo", video=cur, filename_prefix=output_stem, format="auto", codec="auto")

    g.remap(set(cat.object_info.keys()) if cat.object_info else None)
    return g.nodes


def refine_denoise(info: dict) -> float:
    return float(info.get("refine", 0.3))


# ───────────────────────────── Offentliche Einstiege ─────────────────────────────

def run(cfg: dict, mode: str, *, text: str | None, file: str | None, out: str | None,
        length: str | None, overrides: dict, run_now: bool = False, start: bool = False) -> Path:
    """Baut das LTX-Workflow-JSON (mode 'ltx23'/'ltx25') und speichert es."""
    import mm_images as I

    lcfg = dict(cfg["ltx"])
    lcfg.update({k: v for k, v in overrides.items() if v is not None})
    prompt, source = C.resolve_prompt(cfg, text, file)
    print(f"[i] Prompt ({len(prompt)} Zeichen) aus: {source}")

    durations = parse_length_spec(length, default_scenes=1,
                                  default_seconds=float(lcfg["default_duration"]))
    plan = scene_plan(prompt, durations)
    print(f"[i] Szenenplan: {len(plan)} Scenes x {[s['duration'] for s in plan]} s "
          f"= {total_seconds(plan)} s gesamt (keine Scene wird uebersprungen)")

    tgt = C.target(cfg, "video")
    if lcfg.get("url"):
        tgt["url"] = lcfg["url"]
    alive = C.server_alive(tgt["url"])
    cat = Catalog(tgt["model_roots"], url=tgt["url"] if alive else None, prefer_live=alive)
    if alive:
        print(f"[i] ComfyUI {tgt['url']} erreicht - Nodes/Modelle live geprueft")

    info: dict = {"models": [], "warnings": [], "notes": [], "triggers": [],
                  "refine": float(lcfg["refine"])}
    models = pick_models(mode, cat, lcfg, info)
    for k, v in (("UNet", models["unet"]), ("Text-Encoder", models["text_encoder"]),
                 ("Video-VAE", models["video_vae"]), ("Audio-VAE", models["audio_vae"]),
                 ("CLIP-Vision", models["clip_vision"])):
        if v:
            info["models"].append((k, v))

    turbo = None
    if lcfg.get("turbo", True):
        turbo = resolve_turbo_lora(mode, cat, lcfg, lcfg.get("turbo_lora"),
                                   float(lcfg.get("turbo_strength", 1.0)), info)
    steps = int(lcfg.get("steps") or (lcfg["turbo_steps"] if turbo else 30))
    if turbo:
        m = re.search(r"(\d+)\s*-?\s*step", turbo[0], re.I)
        steps = int(m.group(1)) if m else int(lcfg["turbo_steps"])

    detail = None
    if float(lcfg["refine"]) > 0:
        detail = cat.pick("loras", DETAIL_LORA_CANDS, required=False)
        if detail:
            info["models"].append(("Detail-LoRA", f"{detail} (Denoise {lcfg['refine']})"))
        else:
            info["refine"] = 0.0

    vl_model = None
    if lcfg.get("vl_llm_auto", True):
        vl_model = mm_vllm.find_vl_model(cat, lcfg.get("vl_llm") or None)
        if not vl_model and lcfg.get("vl_llm"):
            info["warnings"].append(f"VL-LLM '{lcfg['vl_llm']}' nicht gefunden - ohne Prompt-Erweiterung.")

    user_loras = []
    for q, s in lcfg.get("user_loras", []):
        n = cat.pick("loras", [q])
        user_loras.append((n, s))
        trig = describe_trigger_name(n)
        if trig:
            info["notes"].append(f"LoRA '{n}': Triggerwort '{trig}' wird automatisch eingetragen (Scene 1).")

    wf = build_workflow(
        mode, plan, models, cat=cat,
        width=int(lcfg["width"]), height=int(lcfg["height"]), fps=int(lcfg["fps"]),
        seed=int(lcfg.get("seed", -1)), steps=steps, cfg=float(lcfg["cfg"]),
        guidance=float(lcfg["guidance"]), refine_lora=detail if float(info["refine"]) > 0 else None,
        turbo=turbo, user_loras=user_loras, audio=bool(lcfg.get("audio")),
        vl_model=vl_model, vl_max_tokens=int(lcfg["vl_max_tokens"]),
        negative=lcfg["negative_prompt"], output_name=lcfg["output_filename"], info=info)

    problems = I.validate(wf, cat.object_info) if cat.object_info else []
    stamp = C.timestamp()
    outdir = C.output_dir(cfg)
    out_path = Path(out).expanduser() if out else outdir / f"{mode}_{stamp}.api.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(wf, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Workflow (API-Format): {out_path}")
    print(f"     Nodes: {len(wf)}   Scenes: {len(plan)}   Gesamt: {total_seconds(plan)}s")
    for k, v in info["models"]:
        print(f"     {k:<14} {v}")
    for n in info["notes"]:
        print(f"     [i] {n}")
    for w in info["warnings"]:
        print(f"     [!] {w}")
    if problems:
        print("[!] Validierung gegen die laufende ComfyUI:")
        for x in problems[:12]:
            print("      " + x)

    if run_now:
        if not alive:
            raise SystemExit(f"[!] ComfyUI unter {tgt['url']} laeuft nicht - zuerst starten "
                             f"(oder ohne --run nur JSON erzeugen).")
        saved = I.run_on_server(tgt["url"], wf, outdir / f"{mode}_{stamp}", int(cfg["image"]["timeout_s"]))
        for spath in saved:
            print(f"[OK] Ergebnis: {spath}")
    else:
        print(f"     Ausfuehren: gleiche Eingabe mit --run, oder JSON in ComfyUI ziehen.")
    return out_path


def list_loras(cfg: dict, mode: str) -> list[dict]:
    tgt = C.target(cfg, "video")
    cat = Catalog(tgt["model_roots"], prefer_live=False)
    return suggest_loras(mode, cat)
