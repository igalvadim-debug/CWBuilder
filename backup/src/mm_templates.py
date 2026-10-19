# -*- coding: utf-8 -*-
"""Eingebaute UI-Format-Vorlagen fuer die Video-Workflows LTX-2.5 und Minimax-H3.

Diese JSON-Dateien sind optimierte Kopien der echten Workflows aus dem Ordner
'output/' (LTX-2.5_t2v_00048.json, minimax_00028_.json) mit diesem Unterschied:

  * alle Knoten liegen im API-Modus "normal" (keine bypassed/mute-Knoten),
  * optionale Zweige (Prompt-Upsampler, Latent-Upscaler, RTX-Super-Resolution)
    sind ueber .disabled-Aenderungslisten abschaltbar,
  * keine externen Abhaengigkeiten: mm_ui.py fuellt die Werte per Node-ID.

mm_ui.py entpackt die Vorlagen bei Bedarf nach templates/ und baut daraus ein
API-Graph-JSON (direkt an ComfyUI sendbar). mm_video.py kann sie ohne
Playwright/HTML-Generator verwenden (turbo = "eingebauter Workflow").
"""
from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# ── Aenderungen am eingebauten Workflow (Turbo-Schalter, IDs siehe Datei) ──
LTX_CHANGES = {
    "upsampler": {
        "label": "Latent-Upscaler x2 (LTXVLatentUpsampler + zweiter Sampler)",
        "set_mode": {"478": 4, "485": 4, "466": 4, "477": 4},   # 4 = mutieren
        "relink": [{"node": "463", "input": "video_latent", "to_node": "476", "to_input": "latent_image"}],
    },
    "rtx_sr": {
        "label": "RTX Video Super Resolution (Nachschaerfe)",
        "set_mode": {"545": 4},
        "relink": [
            {"node": "494", "input": "images", "to_node": "5506", "to_input": "anything"},
            {"node": "491", "input": "images", "to_node": "5506", "to_input": "anything"},
        ],
    },
}

MM_CHANGES = {
    "rtx_sr": {
        "label": "RTX Video Super Resolution (Nachschaerfe)",
        "set_mode": {"5524": 4},
        "relink": [{"node": "5473", "input": "images", "to_node": "5465", "to_input": "samples"}],
    },
    "lora_motion": {
        "label": "Motion-Booster-LoRA",
        "lora_slot": 3,
    },
    "lora_unlocked": {
        "label": "Minimax H3 Unlocked V2 (NSFW-LoRA)",
        "lora_slot": 4,
    },
}


def _blob(name: str) -> bytes:
    """Benannte eingebettete gzip/base64-Vorlage als dekomprimierte Bytes liefern."""
    from mm_embedded import DATA  # erzeugt von _dev/embed_templates.py
    return gzip.decompress(base64.b64decode(DATA[name]))


def ensure_files() -> dict:
    """Vorlagen + Aenderungslisten nach templates/ schreiben; liefert Pfad-Map."""
    paths = {}
    TEMPLATES_DIR.mkdir(exist_ok=True)
    for name in ("ltx25.ui.json", "minimax_h3.ui.json"):
        p = TEMPLATES_DIR / name
        data = _blob(name)
        if not p.exists() or p.stat().st_size != len(data):
            p.write_bytes(data)
        paths[name] = p
    changes = {"ltx25": LTX_CHANGES, "minimax_h3": MM_CHANGES}
    cp = TEMPLATES_DIR / "changes.json"
    cp.write_text(json.dumps(changes, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["changes.json"] = cp
    return paths


def load(name: str) -> dict:
    """Benannte eingebettete JSON-Vorlage als neues Workflow-Dict laden."""
    return json.loads(_blob(name).decode("utf-8"))
