# CWBuilder — ComfyUI Generator

Ein Paket für zwei Aufgaben:

1. **Video**: MiniMax-H3 (eingebaut), LTX-2.5 (eingebaut) — Workflow-JSON direkt aus optimierten Vorlagen.
2. **Bilder**: Krea 2, FLUX.2 Klein 9B/4B, Qwen Image 2.1, Qwen Image Edit, Z-Image Turbo, FLUX.3, **MOSS** (T2I, Inpaint, Detailer, Prompt Enhancer, 4-Step Rapid) — mit Turbo-LoRA, ControlNet, vLLM Prompt-Upsampler.

Ordner verschiebbar: alle Pfade relativ zum Projekt, externe Pfade in `config.json`.

## Start

- Doppelklick `start.bat` → Menü.
- `.txt` auf `start.bat` ziehen → **ganzer Dateiinhalt** wird Prompt (Video).
- Aus der Konsole:

```
start.bat video                                   (Prompt aus prompts\prompt.txt)
start.bat video "Leuchtturm bei Sonnenaufgang" -o lighthouse.json --steps 4
start.bat image krea2 --run
start.bat image klein9b -i foto.png --run
start.bat image qwen21 --turbo p8 --control --control-image pose.png --run
start.bat image qwen-edit -i a.png -i b.png "Text" --run
start.bat list        (Modi, Turbo-LoRAs, Server-Status)
start.bat check       (alle Modi gegen vorhandene Modelle prüfen)
start.bat ui          (Gradio-Weboberfläche auf 127.0.0.1:7865)
```

## Video-Modi (eingebaut, kein Playwright)

| Modus | Beschreibung | Turbo (Standard) |
|-------|--------------|------------------|
| `minimax_h3` | MiniMax H3 Video — Szenen-Kette, Audio, VL-LLM, EasyCache, SageAttention | Turbo-LoRA (4 Steps), LoRA ein/ausschaltbar |
| `ltx25` | LTX-Video 2.5 — Reference-Video, VL-LLM Frame-Beschreibung, Turbo-LoRA (8 Steps) | Turbo-LoRA (8 Steps), Refine-Denoise |

Beide nutzen **eingebaute Workflow-Vorlagen** aus `output/` — kein Playwright, keine HTML-Generierung.
Referenzbilder/Videos bekommen Zufallsnamen und werden nach `<ComfyUI>/input` kopiert.

### MiniMax-H3 Optionen (Extras abschaltbar)
`easycache`, `sage_attention`, `audio_enabled`, `lora_enabled`, `consistency_bible`, `keyframes`, `plan_export`, `skip_join`, `generate_references`, `external_tts`, `vl_llm_auto`.

### LTX-2.5 Optionen
`diffusion_model_25`, `turbo_lora_25`, `text_encoder` (Gemma), `clip_vision`, `video_vae`, `audio_vae`, `latents_upscaler`, `turbo_steps` (Standard 8), `refine` (Detail-LoRA Denoise), `vl_llm_auto`.

## Bild-Modi

| Modus | Modell | Turbo-LoRA (`--turbo` / UI-Checkbox) | ControlNet |
|-------|--------|--------------------------------------|------------|
| `krea2` | Krea 2 Turbo | `turbo`, `turbo2`, `distill` | `--control depth` (Control-LoRA) |
| `klein9b` / `klein4b` | FLUX.2 Klein | Modell bereits destilliert (4 Steps) | `--control union` (experimentell) |
| `qwen21` | Qwen Image 2.1 (`--variant int8/turbo/gguf`) | `acc4`, `p8`, `p5`, `viggle4`, `viggle5` | `--control union` |
| `qwen-edit` | Qwen Image Edit 2511 | `lightning` (4 Steps) | nein |
| `zimage` | Z-Image Turbo (AIO) | bereits Turbo (8 Steps) | `--control union` oder `tile` |
| `flux3` | FLUX.3 (Guidance Embedder) | — | — |
| **`moss_t2i`** | **MOSS T2I** (Text → Bild) | Rapid 4-Step optional | — |
| **`moss_inpaint`** | **MOSS Inpaint** | — | Maske (Wachstum/Blur/Engine wählbar) |
| **`moss_detailer`** | **MOSS Detailer** (Gesichter) | — | **Gesichtsanzahl 1–4**, **SeedVR2 Upscale** |
| **`moss_prompt_enhancer`** | **MOSS Prompt Enhancer** | — | LLM wählbar (auto/qwen3vl/chatgpt/llama), **Handoff an T2I** |
| **`moss_4step`** | **MOSS Rapid 4-Step** | Rapid LoRA (4 Steps) | — |

Prochee: `--lora name:strength` (mehrfach), `-i` für Referenzen (mehrfach), `-W/-H`, `--steps`, `--cfg`, `--seed`, `--preprocess canny|depth|lineart|none`.
Falls Turbo-LoRA oder Modell fehlen: Skript zeigt, was wo gesucht wurde, und schlägt ähnliche Dateien vor.

### vLLM Prompt-Upsampler (Flux 3 / MOSS / LTX-2.5 / MiniMax)
Flux 3 Prompt-Upsampler (LLM, safetensors oder GGUF) wird über `ChatGPT/LLMLoaderNodes` geladen — Modell-Art `llm` im Katalog (`LLM`, `text_enchancer`, `diffusion_llms`, `large_language_model`).

## Gradio-Weboberfläche (`start.bat ui` / `python src\mm.py ui`)

- **Prompt oben**, Modus wählen, darunter **nur Optionen passend zum Modus**.
- **Turbo standardmäßig AN** (Checkbox), bei anderer Modellwahl abschaltbar.
- **Letzte Auswahl** wird in `ui_state.json` gemerkt (Modus, Aspect, Megapixels, Steps, Turbo, Seed, Negative, Run, Modelle).
- **ComfyUI Health Check** (Button "🔄 Prüfen"): Erreichbarkeit, erforderliche Nodes (`/object_info`), Modelle (via Katalog).
- **Output-Galerie** (Bilder) + Video-Player + **"📁 Output-Ordner öffnen"** Button.
- **Per-Modus Optionen**:
  - **MOSS Inpaint**: Masken-Wachstum (px), Masken-Weichzeichner (px), Inpaint-Engine (auto/standard/lama/sd).
  - **MOSS Detailer**: Anzahl Gesichter (1–4, Slider), SeedVR2 Upscale (Checkbox).
  - **MOSS Prompt Enhancer**: LLM (auto/qwen3vl/chatgpt/llama), Enhanced Prompt an T2I übergeben (Checkbox).

## Wie es funktioniert

- **Bilder**: Skript baut Workflow im API-Format (`output\mm_<modus>_<zeit>.api.json`).
  Mit `--run` / "Sofort ausführen" sendet er an ComfyUI (`D:\ComfyUi2`, Port 8291) und speichert Ergebnisse in `output\`.
- **Modell-Liste** kommt **von laufender ComfyUI** (`/object_info`) — berücksichtigt `extra_model_paths.yaml`.
  Vor dem Senden Validierung: Nodes, Eingänge, Modelldateien vorhanden?
- `--start` (im Menü an) startet ComfyUI via `start_bat` aus `config.json`, falls nicht läuft.
- **Video-JSON** öffnet sich in `D:\ComfyUiVideo` (Port 8197).
- **MOSS Workflows** nutzen eingebaute Node-Ketten (RapidMOSSAdapter, InpaintModelConditioning, DetailerFaceCrop, SeedVR2, PromptEnhancerLLM).

## Dateien

```
start.bat            Menü & Start (Python: venv, python, py -3)
config.json          Ports, Pfade, Modelle, Defaults
prompts\prompt.txt   Prompt (ganzer Text)
prompts\negative.txt Negativ-Prompt Bilder (leer = keiner)
src\                 mm.py (CLI), mm_ui.py (Gradio), mm_video.py, mm_images.py, mm_common.py
assets\              (Legacy: Minimax HTML-Generator)
docs\                Modell-Notizen, Node-Referenz, Workflow-Beispiele
output\              Ergebnisse + eingebaute Workflow-Vorlagen (minimax_h3.json, ltx25.json)
ui_state.json        Letzte UI-Werte (wird automatisch erstellt)
```

Umgebungsvariablen (optional): `MM_PYTHON`, `MM_CONFIG`, `MM_OUTPUT_DIR`, `MM_IMAGE_URL`, `MM_VIDEO_URL`, `MM_MODEL_ROOTS`.

Für Video beim ersten Start: `playwright` + Chromium Installation, falls nicht vorhanden. Für Bilder: Standard-Python reicht.
