# CWBuilder — Session Summary (2026-10-19)

## Completed: Open-Creator Cleanup + Start_Qwen3_VL_4B_Vision.bat Rewrite

### Cleaned Files (no open-creator remnants remain)

| File | Change |
|------|--------|
| `install.bat` | Rewritten as clean CWBuilder venv installer (98 lines). Searches Python 3.12+ via py launcher / known paths, calls `install.py`. |
| `install.py` | Complete rewrite (308 lines). Creates `./venv`, installs `requirements.txt`, checks `config.json` model_roots. No model download/copy/symlink logic. Flags: `--python <exe>`, `--download-models` (reserved, no-op). |
| `requirements.txt` | Removed open-creator header. Now references `config.json` + `docs/local_models.json` for model paths. Single dep: `gradio>=4,<7`. |
| `tests/test_windows_launchers.py` | Rewritten to test CWBuilder launchers (`start.bat`, `install.bat`). Verifies menu options (G/C/I/P/Q), venv usage, encoding, external ComfyUI launch. |

### Rewritten: `Start_Qwen3_VL_4B_Vision.bat`

**Sources used:**
- Models: `docs/models.txt` (254 paths across 6 roots)
- Nodes: `docs/custom_nodes.md` (140+ ComfyUI custom nodes)

**Features:**
- Auto-detects first existing Qwen3-VL-4B model from 6 known locations (SillyTavern, ComfyUiCuda×4, ai_diffusion, ComfyUiVideo)
- Auto-detects mmproj (vision projector) from 3 known locations
- Lists 4 relevant VLM custom nodes: `ComfyUI-llama-cpp_vlm`, `ComfyUI-QwenVL-Mod`, `ComfyUI-GGUF-VLM`, `ComfyUI-cc_llama_vision`
- llama-server path from workflow templates: `D:\Unsloth\C-claude\llama.cpp\llama-server.exe`
- GPU: `-ngl 99`, `--mmproj-offload`, q8_0 KV cache, 65536 context
- Graceful text-only fallback if no mmproj found
- Port 8080, OpenAI-compatible `/v1` endpoint

### Verification
```bash
# No open-creator references remain in source files
grep -r "open-creator\|OPENCREATOR_LOCAL\|local-stack\|19861" --include="*.py" --include="*.bat" D:\claudeAgent\CWBuilder
# → 0 matches
```

### Current Project State

**Phase 3 (Turbo & MOSS): COMPLETE**
- 5 MOSS modes in `IMAGE_MODES`/`MODE_LABELS`: T2I, Inpaint, Detailer, Prompt Enhancer, 4-Step
- Turbo presets: `dmd8` (8 steps, LoRA), `rapid4` (4 steps, RapidMOSSAdapter), `off` (25 steps, cfg 3.5)
- Single Turbo checkbox in Gradio UI (variant determined by mode)
- CLI aliases: `moss`, `moss-inpaint`, `moss-detailer`, `moss-prompt`, `moss-4step`, `rapidmoss`
- MOSS models verified: `moss_image_sft_int8_convrot.safetensors` (diffusion_models), `moss-image-sft-qwen35-int8-convrot.safetensors` (clip), `moss-image-sft-vae.safetensors`, `MOSS-Image-SFT-8-steps-dmd.safetensors` (loras)

**Phase 4 (Gradio UI): COMPLETE ✅**
- ✅ MOSS modes in `IMAGE_MODES`/`MODE_LABELS`
- ✅ Single Turbo checkbox for all image modes
- ✅ **Per-mode UI options:**
  - **MOSS Inpaint**: Masken-Wachstum (px), Masken-Weichzeichner (px), Inpaint-Engine (auto/standard/lama/sd)
  - **MOSS Detailer**: Anzahl Gesichter (1–4, Slider), SeedVR2 Upscale (Checkbox)
  - **MOSS Prompt Enhancer**: LLM (auto/qwen3vl/chatgpt/llama), Enhanced Prompt an T2I übergeben (Checkbox)
- ✅ **ComfyUI Health Check**: `comfyui_health_check(target_name)` prüft Erreichbarkeit, Nodes (`/object_info`), Modelle (Katalog)
  - Button "🔄 Prüfen" + Auto-Check beim App-Start
  - Status: 🟢 OK / 🟡 Warnungen / 🔴 Kritisch mit Details
- ✅ **Output Gallery + "📁 Output-Ordner öffnen"**: `gr.Gallery` (Bilder, 2 Spalten), `gr.Video`, Button öffnet `output/` im Dateimanager
- ✅ **ui_state.json Persistenz (Backward Compatible)**: `load_state()`/`save_state()` merkt mode, aspect, mp, duration, fps, steps, turbo, seed, run, negative, Modelle; Defaults als Fallback, neue Keys gemerged

**Phase 5 (Tests): BLOCKED**
- Unit tests require `cmd.exe` / PowerShell (MSYS/bash mangles venv Python path)
- Run: `venv\Scripts\python.exe -m unittest discover -s tests -v`

### Key Paths
```
Project root:     D:\claudeAgent\CWBuilder
venv Python:      D:\claudeAgent\CWBuilder\venv\Scripts\python.exe
Config:           D:\claudeAgent\CWBuilder\config.json
Models index:     D:\claudeAgent\CWBuilder\docs\models.txt
Custom nodes:     D:\claudeAgent\CWBuilder\docs\custom_nodes.md
Local models reg: D:\claudeAgent\CWBuilder\docs\local_models.json
API keys:         D:\claudeAgent\Stocks\.env  (Finnhub, Tavily, qveris.ai, HF_TOKEN)
```

### Launchers
| File | Purpose |
|------|---------|
| `start.bat` | German ASCII menu: [G] Gradio UI (7865), [C] ComfyUI für MOSS, [I] Install, [P] Modi prüfen, [Q] Beenden |
| `ui.bat` | Direct Gradio launcher (port 7865) |
| `install.bat` | Venv creation + requirements install |
| `Start_Qwen3_VL_4B_Vision.bat` | Vision LLM server (port 8080) |

### Next Steps (Phase 5+)
1. Run tests from `cmd.exe` (not bash)
2. Optional: Video-Modus Health Check für MiniMax-H3 / LTX-2.5 spezifische Nodes/Models
3. Optional: MOSS Per-Mode Options in CLI (`mm_images.py`) durchreichen (aktuell nur UI)
4. Optional: README.md bereits aktualisiert (MOSS, Turbo, Health Check, Gallery, State)

### Files Modified This Session
| File | Changes |
|------|---------|
| `src/mm_ui.py` | +561 lines: Health check, per-mode MOSS options, gallery, open_folder, state persistence |
| `README.md` | Updated: MOSS modes, Turbo, Health Check, Gallery, State, file tree |
| `ui_state.json` | Auto-created/updated on UI interaction |