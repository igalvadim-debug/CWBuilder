# -*- coding: utf-8 -*-
"""Erzeugt aus den Workflow-JSONs im output/-Ordner optimierte Vorlagen in templates/.

Optimierungen:
  * alle Knoten zurueck auf Modus 0 (normal) - nichts ist bypassed/gemutet,
  * unbenutzte doppelte Ausgabeknoten werden entfernt,
  * LTX: Prompt-Upsampler-Schalter auf "aus" (einfacher Prompt laeuft direkt),
  * Dateigroesse: compactes JSON ohne UI-Rundballast (pos/size/flags/order).

Aufruf:  python _dev/optimize_templates.py [pfad-zu-output-ordner]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "output"
TPL = ROOT / "templates"
TPL.mkdir(exist_ok=True)


def strip_node(n: dict) -> dict:
    keep = ("id", "type", "inputs", "outputs", "widgets_values", "properties", "title")
    m = {k: n[k] for k in keep if k in n}
    m["mode"] = 0
    m["pos"] = n.get("pos", [0, 0])
    m["size"] = n.get("size", [210, 42])
    return m


def clean_widgets(wf: dict) -> None:
    """UI-Ballast aus widgets_values entfernen (z.B. videopreview in VHS-Knoten)."""
    for n in wf["nodes"]:
        wv = n.get("widgets_values")
        if isinstance(wv, dict):
            n["widgets_values"] = {k: v for k, v in wv.items() if k != "videopreview"}
    for sg in (wf.get("definitions") or {}).get("subgraphs", []):
        for n in sg.get("nodes", []):
            wv = n.get("widgets_values")
            if isinstance(wv, dict):
                n["widgets_values"] = {k: v for k, v in wv.items() if k != "videopreview"}


def prune(wf: dict, drop_ids: set[int]) -> dict:
    wf["nodes"] = [n for n in wf["nodes"] if n["id"] not in drop_ids]
    links = {}
    for l in wf.get("links", []):
        if l[1] in drop_ids or l[3] in drop_ids:
            continue
        links[l[0]] = l
    wf["links"] = list(links.values())
    byid = {n["id"]: n for n in wf["nodes"]}
    for n in wf["nodes"]:
        n["inputs"] = [i for i in n.get("inputs", [])
                       if i.get("link") is None or i["link"] in links]
        outs = []
        for ot in n.get("outputs", []):
            ls = [x for x in (ot.get("links") or []) if x in links]
            ot = dict(ot)
            ot["links"] = ls
            outs.append(ot)
        n["outputs"] = outs
    return wf


def fix_ltx(src: Path, dst: Path) -> None:
    wf = json.loads(src.read_text(encoding="utf-8"))
    byid = {n["id"]: n for n in wf["nodes"]}
    # Prompt-Upsampler im eingebauten Workflow standardmaessig AUS (Turbo/Pfad kurz halten)
    for n in wf["nodes"]:
        if n["id"] == 497:
            n["widgets_values"] = [False]
        if n["id"] == 455:
            n["widgets_values"] = [False]
    # nicht verbundene Doppelgaenger der VideoCombine-Ausgabe entfernen
    drop = set()
    used_links = {l[3] for l in wf.get("links", [])}
    for n in wf["nodes"]:
        if n["type"] == "VHS_VideoCombine" and n["id"] not in used_links:
            pass
    # VHS 491 hat dieselben Eingaben wie 494 und haengt an einem Output von 545? beide behalten:
    # einer speichert mit Audio (trim_to_audio), einer ohne - bewusst gelassen.
    wf = prune(wf, drop)
    clean_widgets(wf)
    wf["nodes"] = [strip_node(n) for n in wf["nodes"]]
    wf["last_node_id"] = max(n["id"] for n in wf["nodes"])
    dst.write_text(json.dumps(wf, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[OK] {src.name} -> {dst}  ({len(wf['nodes'])} Nodes)")


def fix_minimax(src: Path, dst: Path) -> None:
    wf = json.loads(src.read_text(encoding="utf-8"))
    # ungenutzte Preview-/Compose-Kette ohne Abnehmer entfernen
    used = {l[3] for l in wf.get("links", [])}
    srcs = {l[1] for l in wf.get("links", [])}
    drop = {n["id"] for n in wf["nodes"]
            if n["type"] in ("PreviewImage", "LoadImagesCompose (obvpm)")
            and n["id"] not in used}
    wf = prune(wf, drop)
    clean_widgets(wf)
    wf["nodes"] = [strip_node(n) for n in wf["nodes"]]
    wf["last_node_id"] = max(n["id"] for n in wf["nodes"])
    dst.write_text(json.dumps(wf, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[OK] {src.name} -> {dst}  ({len(wf['nodes'])} Nodes, dropped {sorted(drop)})")


def embed(dst_dir: Path) -> None:
    """templates/*.ui.json gzip+base64 in src/mm_embedded.py einbetten (laedt immer)."""
    import base64
    import gzip
    lines = [
        "# -*- coding: utf-8 -*-",
        "# ERZEUGT von _dev/optimize_templates.py - nicht manuell bearbeiten.",
        "# Eingebettete UI-Workflow-Vorlagen (gzip+base64), damit templates/ optional ist.",
        "DATA = {",
    ]
    for p in sorted(dst_dir.glob("*.ui.json")):
        blob = base64.b64encode(gzip.compress(p.read_bytes(), 9)).decode()
        lines.append(f'    "{p.name}": "{blob}",')
    lines.append("}")
    out = dst_dir.parent / "src" / "mm_embedded.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] eingebettet -> {out}")


if __name__ == "__main__":
    ltx = next(OUT.glob("LTX*"), None)
    mm = next(OUT.glob("minimax_0*"), None)
    if ltx:
        fix_ltx(ltx, TPL / "ltx25.ui.json")
    if mm:
        fix_minimax(mm, TPL / "minimax_h3.ui.json")
    embed(TPL)
