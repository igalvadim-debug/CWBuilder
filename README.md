# Minimax / ComfyUI Generator

Один пакет для двух задач:

1. **Видео Minimax-H3**: делает workflow-JSON через локальный HTML-генератор.
2. **Картинки**: Krea 2, FLUX.2 Klein 9B/4B, Qwen Image 2.1, Qwen Image Edit 2511, Z-Image Turbo, с Turbo-LoRA и ControlNet.

Папку можно переносить куда угодно: все пути считаются от неё, а внешние пути лежат в `config.json`.

> **Локальный режим: аккаунт и кредиты не нужны.** Всё (ComfyUI + твои safetensors-модели из `D:\ComfyUiCuda\models\...`) работает без интернета. Страница «OpenCreator-Konto / Anmeldedienst ist nicht verfügbar / Credits» — это сторонний облачный сервис, она НЕ относится к этому проекту; просто закрывай её, генерация работает офлайн.

## Запуск

- Двойной клик по `start.bat` открывает меню.
- Перетащи `.txt` на `start.bat`: **весь текст файла** становится промтом для видео.
- Из консоли:

```
start.bat video                                   (промт из prompts\prompt.txt)
start.bat video "Маяк на рассвете" -o lighthouse.json --steps 4
start.bat image krea2 --run
start.bat image klein9b -i foto.png --run
start.bat image qwen21 --turbo p8 --control --control-image pose.png --run
start.bat image qwen-edit -i a.png -i b.png "текст" --run
start.bat list        (режимы, Turbo-LoRA, статус серверов)
start.bat check       (все режимы против реально имеющихся моделей)
```

## Что исправлено в видео-части

Старый `generate_minimax.bat` принимал первый аргумент за промт, поэтому `output.json` попадал в окно промта.
Теперь `.json` в аргументах всегда означает **файл результата**, а `.txt` читается целиком.
Если промт не указан, берётся `prompts\prompt.txt` из папки проекта (а не из текущей папки).
Результат по умолчанию лежит в `output\minimax_h3_<время>.json`.

## Режимы изображений

| Режим | Модель | Turbo-LoRA (`--turbo`) | ControlNet |
|---|---|---|---|
| `krea2` | Krea 2 Turbo | `turbo`, `turbo2`, `distill` | `--control depth` (Control-LoRA) |
| `klein9b` / `klein4b` | FLUX.2 Klein | нет, модель уже дистиллирована (4 шага) | `--control union` (экспериментально) |
| `qwen21` | Qwen Image 2.1 (`--variant int8/turbo/gguf`) | `acc4`, `p8`, `p5`, `viggle4`, `viggle5` | `--control union` |
| `qwen-edit` | Qwen Image Edit 2511 | `lightning` (4 шага) | нет |
| `zimage` | Z-Image Turbo (AIO) | уже Turbo (8 шагов) | `--control union` или `tile` |

Прочее: `--lora имя:сила` (можно несколько раз), `-i` для референсов (несколько раз), `-W/-H`, `--steps`, `--cfg`, `--seed`, `--preprocess canny|depth|lineart|none`.
Если Turbo-LoRA или модель не найдены, скрипт пишет, что искал и где, и предлагает похожие файлы.

## Как это работает

- Картинки: скрипт собирает workflow в API-формате (`output\mm_<режим>_<время>.api.json`).
  С `--run` он отправляет его в ComfyUI (`D:\ComfyUi2`, порт 8291) и сохраняет результат в `output\`.
- Список моделей берётся **у запущенной ComfyUI** (`/object_info`), то есть с учётом `extra_model_paths.yaml`.
  Перед отправкой workflow проверяется: есть ли ноды, входы и файлы моделей.
- `--start` (в меню включён) запускает ComfyUI через `start_bat` из `config.json`, если она ещё не работает.
- Видео-JSON открывается в `D:\ComfyUiVideo` (порт 8197).

## Файлы

```
start.bat            меню и запуск (Python ищется сам: venv, python, py -3)
config.json          порты, пути, модели Minimax, размеры по умолчанию
prompts\prompt.txt   промт (весь текст)
prompts\negative.txt негативный промт для картинок (пусто = без него)
src\                 mm.py (CLI), mm_video.py, mm_images.py, mm_common.py
assets\              локальный HTML-генератор Minimax
docs\                заметки по моделям и нодам, примеры workflow
output\              результаты
```

Переменные окружения (по желанию): `MM_PYTHON`, `MM_CONFIG`, `MM_OUTPUT_DIR`, `MM_IMAGE_URL`, `MM_VIDEO_URL`, `MM_MODEL_ROOTS`.
Для видео при первом запуске ставится `playwright` и Chromium, если их нет. Для картинок хватает стандартного Python.
