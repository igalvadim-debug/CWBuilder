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

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

COMMANDS = {"video", "image", "list", "check", "-h", "--help"}

MODE_ALIASES = {
    "krea": "krea2", "krea-2": "krea2",
    "klein": "klein9b", "flux2": "klein9b", "flux2klein": "klein9b", "klein-9b": "klein9b", "9b": "klein9b",
    "klein-4b": "klein4b", "4b": "klein4b",
    "edit": "qwen-edit", "qwenedit": "qwen-edit", "qwen_edit": "qwen-edit",
    "qwen": "qwen21", "qwen2.1": "qwen21", "qwen-image": "qwen21", "qwen-2.1": "qwen21",
    "z-image": "zimage", "zit": "zimage", "z": "zimage",
}

EPILOG = """\
Beispiele:
  mm.py video                                   Prompt aus prompts\\prompt.txt (GANZER Text)
  mm.py video "Ein Leuchtturm im Morgengrauen" -o leuchtturm.json --steps 4
  mm.py image krea2 --run                       Krea 2 Turbo, Turbo-LoRA automatisch
  mm.py image klein9b -i foto.png --run         FLUX.2 Klein 9B als Edit
  mm.py image qwen21 --turbo p8 --control --control-image pose.png --run
  mm.py image qwen-edit -i a.png -i b.png "Person aus Bild 2 in Szene 1" --run
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


def open_catalog(cfg: dict, tgt: dict) -> C.Catalog:
    cat = C.Catalog(tgt["model_roots"], url=tgt["url"])
    if cat.live_ok:
        print(f"[i] ComfyUI {tgt['url']} erreicht - Modellliste live aus der Installation")
    else:
        roots = ", ".join(str(r) for r in cat.roots) or "keine Modellordner gefunden"
        print(f"[i] ComfyUI nicht erreichbar - Modelle von Platte: {roots}")
    return cat


# ───────────────────────────── video ─────────────────────────────

def cmd_video(a) -> int:
    import mm_video as V

    cfg = C.load_config()
    if a.list_loras:
        print("Minimax-LoRAs:")
        for n in V.list_minimax_loras(cfg):
            print("  " + n)
        return 0
    text, pfile, out = V.classify_inputs(a.items)
    overrides = {
        "steps": a.steps, "default_duration": a.duration, "lora_file": a.lora,
        "lora_strength": a.lora_strength, "width": a.width, "height": a.height,
        "fps": a.fps, "base_seed": a.seed,
        "turbo_mode": False if a.no_turbo else None,
        "lora_enabled": False if a.no_lora else None,
        "audio_enabled": True if a.audio else (False if a.no_audio else None),
    }
    path = V.run(cfg, text=a.prompt or text, file=a.prompt_file or pfile, out=a.output or out,
                 overrides=overrides, show_browser=a.show_browser)
    print(f"\nFertig: {path}")
    print("In ComfyUI (Video-Installation) per Drag&Drop auf die Oberflaeche ziehen.")
    return 0


# ───────────────────────────── image ─────────────────────────────

def cmd_image(a) -> int:
    import mm_images as I

    cfg = C.load_config()
    tgt = C.target(cfg, "image")
    if a.url:
        tgt["url"] = a.url
    mode = MODE_ALIASES.get(a.mode.lower(), a.mode.lower())
    if mode not in I.BUILDERS:
        print(f"[!] Unbekannter Modus '{a.mode}'. Moeglich: {', '.join(I.BUILDERS)}", file=sys.stderr)
        return 2

    text, pfile, out_json = _classify(a.items)
    prompt, source = C.resolve_prompt(cfg, a.prompt or text, a.prompt_file or pfile)
    negative = C.resolve_negative(cfg, a.negative)
    print(f"[i] Prompt ({len(prompt)} Zeichen) aus: {source}")

    alive = ensure_server(tgt, a.start) if a.run else C.server_alive(tgt["url"])
    if a.run and not alive:
        print(f"[!] ComfyUI unter {tgt['url']} nicht erreichbar. Starte sie (z.B. D:\\ComfyUi2) "
              f"oder nutze --start (siehe start_bat in config.json).", file=sys.stderr)
        return 3
    cat = open_catalog(cfg, tgt)

    staged = [I.stage_image(x, tgt, upload=alive) for x in (a.image or [])]
    ctrl = I.stage_image(a.control_image, tgt, upload=alive) if a.control_image else None

    img = cfg["image"]
    p = I.Params(
        mode=mode, prompt=prompt, negative=negative,
        width=a.width or img["width"], height=a.height or img["height"],
        size_explicit=bool(a.width or a.height),
        steps=a.steps, cfg=a.cfg, seed=a.seed, sampler=a.sampler, scheduler=a.scheduler,
        batch=a.batch or img["batch"], loras=parse_loras(a.lora), turbo=a.turbo,
        variant=a.variant, unet=a.unet, clip=a.clip, vae=a.vae, images=staged,
        control=a.control, control_image=ctrl, preprocess=a.preprocess,
        control_strength=a.control_strength, megapixels=a.megapixels, prefix=a.prefix,
    )
    nodes, info = I.build(p, cat)
    print(I.report(p, info, tgt["url"]))

    problems = I.validate(nodes, cat.object_info) if cat.object_info else []
    if problems:
        print("[!] Validierung gegen die laufende ComfyUI:")
        for x in problems[:12]:
            print("    " + x)

    stamp = C.timestamp()
    outdir = C.output_dir(cfg)
    jpath = Path(out_json).expanduser() if out_json else outdir / f"mm_{mode}_{stamp}.api.json"
    if not jpath.is_absolute() and not out_json:
        jpath = outdir / jpath
    jpath.parent.mkdir(parents=True, exist_ok=True)
    jpath.write_text(json.dumps(nodes, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Workflow (API-Format): {jpath}")

    if not a.run:
        print("     Zum Ausfuehren: gleiche Eingabe mit --run (oder JSON ueber die ComfyUI-API senden).")
        return 0
    if problems and not a.force:
        print("[!] Abbruch wegen Validierungsfehlern (mit --force trotzdem senden).", file=sys.stderr)
        return 4
    saved = I.run_on_server(tgt["url"], nodes, outdir / f"mm_{mode}_{stamp}", int(img["timeout_s"]))
    if not saved:
        print("[!] ComfyUI lieferte keine Bilder zurueck.", file=sys.stderr)
        return 5
    for s in saved:
        print(f"[OK] Bild: {s}")
    return 0


def _classify(items: list[str]):
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


# ───────────────────────────── Parser ─────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mm", description=__doc__, epilog=EPILOG,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    v = sub.add_parser("video", help="Minimax-H3 Workflow erzeugen")
    v.add_argument("items", nargs="*", help="Prompt-Text, .txt (ganzer Inhalt = Prompt) oder .json (= Ausgabe)")
    v.add_argument("-p", "--prompt")
    v.add_argument("-f", "--prompt-file")
    v.add_argument("-o", "--output")
    v.add_argument("--steps", type=int)
    v.add_argument("--duration", type=int)
    v.add_argument("--lora")
    v.add_argument("--lora-strength", type=float)
    v.add_argument("--width", type=int)
    v.add_argument("--height", type=int)
    v.add_argument("--fps", type=int)
    v.add_argument("--seed", type=int)
    v.add_argument("--no-turbo", action="store_true")
    v.add_argument("--no-lora", action="store_true")
    v.add_argument("--audio", action="store_true")
    v.add_argument("--no-audio", action="store_true")
    v.add_argument("--show-browser", action="store_true")
    v.add_argument("--list-loras", action="store_true")
    v.set_defaults(fn=cmd_video)

    i = sub.add_parser("image", help="Bild-Workflow erzeugen / ausfuehren")
    i.add_argument("mode", help="krea2 | klein9b | klein4b | qwen-edit | qwen21 | zimage")
    i.add_argument("items", nargs="*", help="Prompt-Text oder .txt; .json = Ausgabedatei")
    i.add_argument("-p", "--prompt")
    i.add_argument("-f", "--prompt-file")
    i.add_argument("-n", "--negative")
    i.add_argument("-W", "--width", type=int)
    i.add_argument("-H", "--height", type=int)
    i.add_argument("--steps", type=int)
    i.add_argument("--cfg", type=float)
    i.add_argument("--seed", type=int, default=-1)
    i.add_argument("--sampler")
    i.add_argument("--scheduler")
    i.add_argument("--batch", type=int)
    i.add_argument("--lora", action="append", help="Name[:Staerke], mehrfach moeglich")
    i.add_argument("--turbo", default="auto", help="auto | off | Preset (siehe 'list') | LoRA-Name")
    i.add_argument("--variant", help="nur qwen21: int8 | turbo | gguf")
    i.add_argument("--unet")
    i.add_argument("--clip")
    i.add_argument("--vae")
    i.add_argument("-i", "--image", action="append", help="Referenzbild (mehrfach)")
    i.add_argument("--control", nargs="?", const="auto", help="ControlNet: auto|union|tile|depth")
    i.add_argument("--control-image")
    i.add_argument("--preprocess", default="auto", help="auto|none|canny|depth|lineart")
    i.add_argument("--control-strength", type=float, default=1.0)
    i.add_argument("--megapixels", type=float, default=1.0)
    i.add_argument("--prefix")
    i.add_argument("--run", action="store_true", help="in ComfyUI ausfuehren und Bilder speichern")
    i.add_argument("--start", action="store_true", help="ComfyUI bei Bedarf automatisch starten")
    i.add_argument("--url", help="ComfyUI-Adresse ueberschreiben")
    i.add_argument("--force", action="store_true", help="trotz Validierungsfehlern senden")
    i.set_defaults(fn=cmd_image)

    sub.add_parser("list", help="Modi, Turbo-LoRAs und Serverstatus").set_defaults(fn=cmd_list)
    sub.add_parser("check", help="alle Modi gegen vorhandene Modelle pruefen").set_defaults(fn=cmd_check)
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = build_parser()
    if not argv:
        ap.print_help()
        return 0
    if argv[0] not in COMMANDS:
        argv.insert(0, "video")  # alter Aufruf / Drag&Drop einer .txt
    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 0
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        return 130
    except (C.ModelMissing, FileNotFoundError, RuntimeError, SystemExit) as e:
        if isinstance(e, SystemExit):
            raise
        print(f"[!] {e}", file=sys.stderr)
        return 1
    except Exception as e:  # Unsupported u.a. mit lesbarer Meldung
        if e.__class__.__name__ == "Unsupported":
            print(f"[!] {e}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
