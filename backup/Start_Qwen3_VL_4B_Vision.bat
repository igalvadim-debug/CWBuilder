@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem ============================================================
rem CWBuilder — Qwen3-VL-4B Vision Server Launcher
rem Uses models from docs/models.txt and nodes from docs/custom_nodes.md
rem ============================================================

rem --- llama.cpp server binary (from workflow templates) ---
set "LLAMA_SERVER=D:\Unsloth\C-claude\llama.cpp\llama-server.exe"

rem --- Available Qwen3-VL-4B model variants (from docs/models.txt) ---
rem 1) Original abliterated Q8_0 (multiple locations)
set "MODEL_1=D:\SillyTavernAiO\KoboldCPP\models\Qwen3-VL-4B-Instruct-abliterated.Q8_0.gguf"
set "MODEL_2=D:\ComfyUiCuda\models\LLM\GGUF\mradermacher\Qwen3-VL-4B-Instruct-c_abliterated-v2-GGUF\Qwen3-VL-4B-Instruct-c_abliterated-v2.Q8_0.gguf"
set "MODEL_3=D:\ComfyUiCuda\models\text_enchancer\Qwen3-VL-4B-Instruct-abliterated.Q8_0.gguf"
set "MODEL_4=D:\ComfyUiCuda\models\text_encoders\Qwen3-VL-4B-Instruct-abliterated.Q8_0.gguf"
set "MODEL_5=C:\ai_diffusion\models\LLM\Qwen3-VL-4B-Instruct-abliterated.Q8_0.gguf"
set "MODEL_6=D:\ComfyUiVideo\models\LLM\Qwen3-VL-4B-Instruct-abliterated.Q8_0.gguf"

rem --- Available mmproj (vision projector) files ---
set "MMPROJ_1=D:\ComfyUiCuda\models\LLM\GGUF\mradermacher\Qwen3-VL-4B-Instruct-c_abliterated-v2-GGUF\Qwen3-VL-4B-Instruct-c_abliterated-v2.mmproj-Q8_0.gguf"
set "MMPROJ_2=C:\ai_diffusion\models\LLM\mmproj-F16.gguf"
set "MMPROJ_3=D:\ComfyUiVideo\models\LLM\mmproj-F16.gguf"

rem --- Server settings ---
set "PORT=8080"
set "CTX_SIZE=65536"

rem --- Relevant custom nodes for Qwen3-VL / VLM (from docs/custom_nodes.md) ---
rem ComfyUI-llama-cpp_vlm       - llama.cpp VLM integration for ComfyUI
rem ComfyUI-QwenVL-Mod          - Qwen-VL specific nodes
rem ComfyUI-GGUF-VLM            - GGUF VLM loader nodes
rem ComfyUI-cc_llama_vision     - cc llama vision nodes

echo.
echo ============================================================
echo  CWBuilder — Qwen3-VL-4B Vision Server
echo  Port %PORT%  -  Context %CTX_SIZE% (q8_0 KV)  -  all layers GPU
echo ============================================================
echo.

rem --- Auto-detect first existing model ---
set "MAIN_MODEL="
set "MMPROJ="

for %%M in (
    "%MODEL_1%" "%MODEL_2%" "%MODEL_3%" "%MODEL_4%" "%MODEL_5%" "%MODEL_6%"
) do (
    if not defined MAIN_MODEL if exist "%%M" set "MAIN_MODEL=%%M"
)

for %%P in (
    "%MMPROJ_1%" "%MMPROJ_2%" "%MMPROJ_3%"
) do (
    if not defined MMPROJ if exist "%%P" set "MMPROJ=%%P"
)

if not defined MAIN_MODEL (
    echo [ERROR] Kein Qwen3-VL-4B Modell gefunden!
    echo Gepruefte Pfade:
    echo   %MODEL_1%
    echo   %MODEL_2%
    echo   %MODEL_3%
    echo   %MODEL_4%
    echo   %MODEL_5%
    echo   %MODEL_6%
    pause
    exit /b 1
)

if not defined MMPROJ (
    echo [WARN] Kein mmproj (vision projector) gefunden!
    echo Gepruefte Pfade:
    echo   %MMPROJ_1%
    echo   %MMPROJ_2%
    echo   %MMPROJ_3%
    echo.
    echo Fortfahren ohne Vision-Projektor (Text-only Modus).
    echo.
)

if not exist "%LLAMA_SERVER%" (
    echo [ERROR] llama-server.exe nicht gefunden: %LLAMA_SERVER%
    echo Erwarteter Pfad aus Workflow-Templates (ltx25.ui.json, output/*.json)
    pause
    exit /b 1
)

echo Gefundenes Modell : %MAIN_MODEL%
if defined MMPROJ echo MMProj (Vision)  : %MMPROJ%
echo.
echo [INFO] Relevante ComfyUI Custom Nodes fuer VLM (aus docs/custom_nodes.md):
echo   - ComfyUI-llama-cpp_vlm
echo   - ComfyUI-QwenVL-Mod
echo   - ComfyUI-GGUF-VLM
echo   - ComfyUI-cc_llama_vision
echo.
echo Web UI: http://127.0.0.1:%PORT%/v1
echo.

rem --- llama.cpp arguments ---
rem -ngl 99              : offload all LLM layers to GPU
rem --mmproj-offload     : also offload the vision encoder to GPU
rem -c %CTX_SIZE%        : extended context via q8_0 KV-Cache
rem --cache-type-k/v q8_0: halve KV-Cache memory vs fp16
rem --port %PORT%        : OpenAI-compatible API -> http://localhost:%PORT%/v1
rem --ui-mcp-proxy       : enable MCP proxy in Web UI (optional)

if defined MMPROJ (
    "%LLAMA_SERVER%" -m "%MAIN_MODEL%" --mmproj "%MMPROJ%" --mmproj-offload -ngl 99 -c %CTX_SIZE% --cache-type-k q8_0 --cache-type-v q8_0 --port %PORT% --ui-mcp-proxy %*
) else (
    "%LLAMA_SERVER%" -m "%MAIN_MODEL%" -ngl 99 -c %CTX_SIZE% --cache-type-k q8_0 --cache-type-v q8_0 --port %PORT% --ui-mcp-proxy %*
)

echo.
echo Server stopped.
pause
endlocal