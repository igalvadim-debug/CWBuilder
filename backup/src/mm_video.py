# -*- coding: utf-8 -*-
"""Minimax-H3 Video-Workflow: fuellt den lokalen HTML-Generator per Playwright aus
und speichert das fertige ComfyUI-Workflow-JSON (UI-Format, per Drag&Drop ladbar).

Bugfix gegenueber der alten generate_minimax.bat:
  * Ein .json-Argument ist jetzt der AUSGABE-Pfad (frueher landete "output.json" im Prompt).
  * Eine .txt-Datei (auch per Drag&Drop) wird KOMPLETT als Prompt gelesen.
  * Die Suche nach prompt.txt passiert im Projektordner, nicht im aktuellen Verzeichnis.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from mm_common import (
    ROOT, Catalog, abspath, output_dir, read_text, resolve_prompt, target, timestamp,
)


def ensure_playwright() -> None:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        print("[i] Playwright fehlt - installiere (einmalig) ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "playwright"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


def classify_inputs(items: list[str]) -> tuple[str | None, str | None, str | None]:
    """Positionsargumente -> (prompt_text, prompt_file, output_json).

    .txt (existierend)  -> Prompt-Datei
    .json               -> Ausgabedatei
    sonst               -> Prompt-Text
    """
    text_parts: list[str] = []
    pfile = out = None
    for it in items:
        s = it.strip().strip('"')
        low = s.lower()
        if low.endswith(".txt") and Path(s).exists():
            pfile = s
        elif low.endswith(".json") and "\n" not in s and len(s) < 260:
            out = s
        else:
            text_parts.append(it)
    return (" ".join(text_parts).strip() or None), pfile, out


def list_minimax_loras(cfg: dict) -> list[str]:
    cat = Catalog(target(cfg, "video")["model_roots"], prefer_live=False)
    return [n for n in cat.names("loras") if "minimax" in n.lower() or "h3" in n.lower() or "taomate" in n.lower()]


async def _generate(prompt: str, out_path: Path, cfg: dict, headless: bool) -> dict:
    from playwright.async_api import async_playwright

    mm = cfg["minimax"]
    html_path = abspath(mm["html"])
    if not html_path.exists():
        raise FileNotFoundError(f"HTML-Generator nicht gefunden: {html_path}")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=headless)
        except Exception as e:
            if "playwright install" in str(e) or "Executable doesn't exist" in str(e):
                print("[i] Chromium fehlt - installiere ...")
                subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
                browser = await p.chromium.launch(headless=headless)
            else:
                raise
        page = await browser.new_page()
        await page.goto(html_path.as_uri())
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(500)

        # ── Formular ausfuellen (GESAMTER Prompt-Text in Szene 1) ──
        await page.fill("#scenes .sp", prompt)
        await page.fill("#neg", mm["negative_prompt"])
        await page.fill("#w", str(mm["width"]))
        await page.fill("#h", str(mm["height"]))
        await page.fill("#fps", str(mm["fps"]))
        await page.fill("#dd", str(mm["default_duration"]))
        await page.fill("#steps", str(mm["steps"]))
        await page.fill("#cfg", str(mm["cfg"]))
        await page.select_option("#smp", mm["sampler"])
        await page.select_option("#sch", mm["scheduler"])
        await page.fill("#dn", str(mm["denoise"]))
        await page.select_option("#sm", mm["seed_mode"])
        await page.fill("#bs", str(mm["base_seed"]))
        await page.fill("#bat", str(mm["batch_size"]))
        await page.fill("#un", mm["diffusion_model"])
        await page.select_option("#vae", mm["video_vae"])
        await page.fill("#te", mm["text_encoder"])
        await page.fill("#fin", mm["output_filename"])
        await page.fill("#ls", str(mm["lora_strength"]))

        checkboxes = {
            "#lora": mm["lora_enabled"], "#aud": mm["audio_enabled"], "#ec": mm["easycache"],
            "#sage": mm["sage_attention"], "#sv": mm["save_individual_scenes"],
            "#rm": mm["reference_mode"], "#kf": mm["keyframes"], "#bib": mm["consistency_bible"],
            "#ext": mm["external_tts"], "#nj": mm["skip_join"], "#exp": mm["plan_export"],
            "#rg": mm["generate_references"], "#lk": mm["order_lock"], "#sg": mm["subgraphs"],
        }
        for sel, want in checkboxes.items():
            if await page.is_checked(sel) != bool(want):
                await page.click(sel)

        # Turbo zuletzt (loest Autofill aus), danach Steps erneut setzen
        if await page.is_checked("#turbo") != bool(mm["turbo_mode"]):
            await page.click("#turbo")
        await page.wait_for_timeout(300)
        await page.fill("#steps", str(mm["steps"]))
        await page.wait_for_timeout(200)
        await page.select_option("#mode", mm["first_frame_mode"])

        await page.click("#bGen")
        await page.wait_for_timeout(1000)
        raw = await page.input_value("#out")
        await browser.close()

    if not raw.strip():
        raise RuntimeError("Workflow-Generierung lieferte leere Ausgabe (HTML-Generator geaendert?).")

    wf = json.loads(raw)

    # Post-Processing: LoRA-Dateiname und Steps (HTML hat feste Werte)
    if mm["lora_enabled"] and mm.get("lora_file"):
        for node in wf.get("nodes", []):
            if node.get("type") == "LoraLoaderModelOnly":
                node["widgets_values"][0] = mm["lora_file"]
                print(f"   LoRA gesetzt: {mm['lora_file']}")
    for node in wf.get("nodes", []):
        if node.get("type") == "BasicScheduler" and len(node.get("widgets_values", [])) >= 2:
            node["widgets_values"][1] = mm["steps"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(wf, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Workflow gespeichert: {out_path}")
    print(f"     Nodes: {len(wf.get('nodes', []))}   Links: {len(wf.get('links', []))}   "
          f"Subgraphs: {len(wf.get('definitions', {}).get('subgraphs', []))}")
    return wf


def run(cfg: dict, *, text: str | None, file: str | None, out: str | None, overrides: dict,
        show_browser: bool = False) -> Path:
    ensure_playwright()
    cfg = json.loads(json.dumps(cfg))  # tiefe Kopie
    cfg["minimax"].update({k: v for k, v in overrides.items() if v is not None})
    prompt, source = resolve_prompt(cfg, text, file)
    print(f"[i] Prompt ({len(prompt)} Zeichen) aus: {source}")
    if out:
        out_path = Path(out.strip('"')).expanduser()
        if not out_path.is_absolute():
            # nur Dateiname -> output-Ordner; mit Unterordner -> relativ zum aktuellen Verzeichnis
            out_path = (Path.cwd() / out_path) if out_path.parent != Path(".") else (output_dir(cfg) / out_path.name)
    else:
        out_path = output_dir(cfg) / f"minimax_h3_{timestamp()}.json"
    asyncio.run(_generate(prompt, out_path, cfg, headless=not show_browser))
    return out_path
