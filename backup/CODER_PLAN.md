# CWBuilder — план для кодера

Дата: 2026-10-18. Папка: `D:\claudeAgent\CWBuilder` (Windows, Python 3.12, venv).

## Цель

1. Вернуть рабочий запуск: `start.bat` (меню) и `ui.bat` (Gradio UI).
2. Gradio UI работает с MOSS-Image workflows (T2I, Inpaint, Detailer, Prompt Enhancer, 4-Step).
3. Turbo для MOSS и единообразно во всём UI.
4. Убрать остатки open-creator, обновить README, тесты зелёные.

## Правила для кодера

- Сначала только фаза 0 (чтение). Потом короткий итог пользователю и ждать «ок». Файлы до «ок» не менять.
- Пользователь не программирует: все изменения делать самому, отдавать файлы целиком, не кусками.
- Не трогать: `venv\`, `.git`, `_dev\MOSS-upstream\` (оригиналы, только читать), существующие результаты в `output\`.
- Не пушить. Коммит только если пользователь попросит.
- После каждой фазы: `venv\Scripts\python.exe -m unittest discover -s tests` и показать результат.
- Пути считать от папки проекта, внешние пути — в `config.json`.
- Не придумывать значения (steps, cfg, имена нод и моделей): брать из workflow-файлов, Note-нод и `/object_info` запущенного ComfyUI.
- Все `.bat` писать только по-немецки и без умлаутов (ae, oe, ue, ss): rem-комментарии, echo, тексты меню. Только ASCII, кириллицы в `.bat` нет.
- Файл пользователя `C:\Users\Startklar\Desktop\Comfyui\start_comfyu2i.bat` лежит вне проекта: не менять, только вызывать.

## Решения пользователя (18.10.2026)

1. ComfyUI для MOSS запускается файлом `C:\Users\Startklar\Desktop\Comfyui\start_comfyu2i.bat`. Он делает `cd /d D:\ComfyUi2`, активирует `cvenv`, стартует `python main.py` с `--port 8291 --listen 127.0.0.1 --lowvram --force-fp16`. В `config.json` цель `image` уже указывает на `http://127.0.0.1:8291`, `D:/ComfyUi2` и этот же bat.
2. В Gradio ОДИН общий чекбокс «Turbo» для всех image-режимов (включая MOSS). Выпадающего выбора варианта в UI нет.
3. Prompt Enhancer использует LLM `C:\ai_diffusion\models\LLM\Qwen3-VL-4B-Instruct-abliterated.Q8_0.gguf` (файл существует, около 4 GB). Тот же файл лежит ещё в `D:\ComfyUiCuda\models\text_enchancer` (симлинк, так задумано, не проблема) и `\text_encoders`, `D:\ComfyUiVideo\models\LLM`, `D:\SillyTavernAiO\KoboldCPP\models`. mmproj с таким же именем нет; ближайший найден для другого варианта модели (`Qwen3-VL-4B-Instruct-c_abliterated-v2.mmproj-Q8_0.gguf` в `D:\ComfyUiCuda\models\LLM\GGUF\mradermacher\...`), подходит ли он — не проверено. Для чисто текстового улучшения промта mmproj не нужен.
4. Все `.bat` — немецкий без умлаутов (см. правила).
5. Модели НЕ копировать и не линковать. Все пути к моделям лежат в `docs\models.txt` (769 строк, полные пути, без секций; рядом `docs\local_models.json`). Брать модели ровно с тех мест, где они лежат. Файлы MOSS и SeedVR2 существуют в трёх корнях (`D:\ComfyUiCuda`, `C:\ai_diffusion`, `D:\ComfyUiVideo`, проверено).

## Что уже известно (проверено 18.10.2026)

- `src\mm_ui.py` — Gradio (`gradio>=4,<7`), порт 7865. `IMAGE_MODES` = krea2, klein9b, klein4b, qwen21, qwen-edit, zimage, flux3. `VIDEO_MODES` = minimax_h3, ltx25, html. Turbo в UI по умолчанию включён. Состояние хранится в `ui_state.json`.
- Docstring `mm_ui.py`: старт через `python src\mm.py ui`, `ui.bat` или `start.bat` → пункт [G]. Файла `ui.bat` в папке нет. В `mm.py` найдены подкоманды только `video`, `image`, `list`, `check`; подкоманды `ui` не видно (перепроверить).
- `start.bat` сейчас — стартер open-creator: ждёт `local-stack\start.py` и `scripts\web-dev-wrapper.mjs` (их нет). Меню с [G] пропало, вероятно перезаписано коммитами «Add files via upload» (не подтверждено).
- open-creator остался в `install.bat`, `install.py`, `requirements.txt`, `tests\test_windows_launchers.py` (OPENCREATOR_LOCAL, порт 19861, local-stack).
- MOSS в проекте: `assets\MOSS Image\` (5 workflows: T2I, Inpaint, Detailer 1–4 лица + SeedVR2, Prompt enhancer, moss4StepWorkflow_v10), `output\MOSS-with-my-models\` (те же с моделями пользователя), `_dev\MOSS-upstream\` (оригиналы), `tests\test_moss_workflows.py`, `output\simpleWorkflowForMOSS_t2iBBOX (1).json` (внутри Note со ссылками на модель и Turbo-LoRA).
- В `src\mm_images.py` и `src\mm_builtin.py` слова «moss» нет: в код MOSS не подключён.
- MOSS-ноды: `RapidMOSSAdapter` (адаптер `rapid-moss-4step`), `MOSSImageUNETLoader`, `MOSSImageCLIPLoader`.
- MOSS-модели: `moss_image_sft_int8_convrot.safetensors` (diffusion_models), `moss-image-sft-qwen35-int8-convrot.safetensors` (clip), `moss-image-sft-vae.safetensors`, LoRA `MOSS-Image-SFT-8-steps-dmd.safetensors` (loras, см. `docs\local_models.json`).
- `docs\models.txt`: корни — `D:\ComfyUiCuda` (254 пути), `C:\ai_diffusion` (202), `D:\ComfyUiVideo` (202), `D:\SillyTavernAiO\KoboldCPP` (21 GGUF), `.lmstudio` (7), `D:\claudeAgent\Coder` (6). `model_roots` цели `image` в `config.json`: `D:/ComfyUi2/models`, `C:/ai_diffusion/models`, `D:/ComfyUiCuda/models`.

## Не проверено — выяснить в фазе 0

- Формат MOSS-файлов: похоже на UI-формат ComfyUI (nodes/links), а `mm_images` строит API-формат и шлёт в `/prompt`. UI-формат напрямую отправить нельзя.
- Как именно Prompt Enhancer вызывает LLM (ноды внутри workflow или отдельный llama-server) и какие кастомные ноды нужны (SeedVR2, LoraManager). В комментариях `start_comfyu2i.bat` упоминается `ComfyUI-cc_llama_vision`, не проверено, установлена ли она.
- Лежат ли MOSS-модели в папках, которые видит этот ComfyUI (`D:\ComfyUi2\models`, `C:\ai_diffusion\models`, `D:\ComfyUiCuda\models`; в `docs\models.md` встречается ещё `D:\ComfyUiVideo`). На 18.10 19:38 порты 8291, 8197, 7865, 7845 не слушали: ComfyUI не запущен.

## TODO

### Фаза 0 — разведка (только чтение)

- [ ] 0.1 `git log --follow -- start.bat`: найти последнюю версию с меню [G] и `ui`; так же для `ui.bat`, `install.bat`. Смотреть через `git show <hash>:файл`.
- [ ] 0.2 Прочитать `mm.py`, `mm_ui.py`, `mm_builtin.py`, `mm_images.py`, `mm_common.py`, `config.json`: как строится workflow, как уходит в ComfyUI, как делается Turbo (LoRA), как ищутся модели (`/object_info`).
- [ ] 0.3 Определить формат каждого MOSS-workflow (UI или API). Если UI — выбрать способ получить API-граф (собрать граф в Python по образцу `mm_images` либо конвертер). Сначала проверить, нет ли готовой логики в `mm_builtin.py`.
- [ ] 0.4 Для каждого из 5 MOSS-workflows составить таблицу: входы для патча (prompt, negative, размер, seed, steps, cfg, sampler, LoRA, входное изображение, маска, filename_prefix), модели, кастомные ноды; для Prompt Enhancer — как вызывается LLM и как подставить GGUF из раздела «Решения пользователя».
- [ ] 0.5 Прочитать Note в `output\simpleWorkflowForMOSS_t2iBBOX (1).json` и в MOSS-workflows: Turbo-LoRA, рекомендуемые steps/cfg.
- [ ] 0.6 Если ComfyUI запущен: проверить `/object_info` на RapidMOSSAdapter, MOSSImageUNETLoader, MOSSImageCLIPLoader, SeedVR2, LoraManager. Если ComfyUI не запущен — запустить через `start_comfyu2i.bat` (или `--start`) и дождаться порта 8291. Проверить, что MOSS-модели видны.
- [ ] 0.7 Итог пользователю: находки, что будет изменено, ответы на вопросы ниже. Ждать «ок».

### Фаза 1 — запуск

- [ ] 1.1 `start.bat`: меню (video, image, Gradio UI [G], list, check, выход) плюс режим аргументов как в README (`start.bat video ...`, `start.bat image ...`, перетаскивание .txt = промт для видео). Поиск Python: `MM_PYTHON` → venv → `py -3.12`. Никакой зависимости от local-stack, pnpm, node. Тексты — по-немецки без умлаутов, только ASCII.
- [ ] 1.2 `ui.bat`: прямой запуск Gradio (http://127.0.0.1:7865), открывает браузер.
- [ ] 1.3 `mm.py`: подкоманда `ui` (если нет), вызывает `mm_ui`.
- [ ] 1.4 `install.bat` / `install.py`: убрать open-creator (OPENCREATOR_LOCAL, 19861, local-stack, pnpm/node). Оставить Python 3.12+, venv, `pip install -r requirements.txt`, маркер `venv\.install-complete`. install.py по умолчанию ничего не копирует и не создаёт симлинки моделей (сейчас, по истории коммита 636171d, умеет symlink/copy из `local_models.json`): это убрать, а флаги `--copy-models` / `--download-models` убрать или оставить строго выключенными по умолчанию, на усмотрение кодера.
- [ ] 1.5 `requirements.txt`: заголовок CWBuilder; gradio; playwright только если нужен режиму `html`.
- [ ] 1.6 Обновить `tests\test_windows_launchers.py`.
- [ ] 1.7 Проверить, что в `start.bat`, `ui.bat`, `install.bat` нет символов вне ASCII, кириллицы и умлаутов.

### Фаза 2 — MOSS в ядре

- [ ] 2.1 Новый модуль `src\mm_moss.py` (или раздел в `mm_images.py` — решить по итогам 0.2). Режимы: `moss-t2i`, `moss-inpaint`, `moss-detail`, `moss-prompt`, `moss-4step`.
- [ ] 2.2 Шаблон брать из `assets\MOSS Image\`, имена моделей подставлять по реальному списку из `/object_info` (как в `mm_images`: если файла нет — написать, что искал, и предложить похожие). Модели искать по `model_roots` из `config.json` и по списку `docs\models.txt`, ничего никуда не копировать. Если ComfyUI на 8291 файл не видит, не копировать, а предложить пользователю дописать корень в `extra_model_paths.yaml` ComfyUI (файл вне проекта: сначала спросить).
- [ ] 2.3 Функция патча графа: prompt, размер, seed, steps, cfg, filename_prefix, входное изображение (копия в `<ComfyUI>\input` со случайным именем, как в UI), маска для inpaint, `--lora имя:сила`.
- [ ] 2.4 Проверка перед отправкой (ноды, входы, файлы моделей) в том же формате ошибок, что у `mm_images`.
- [ ] 2.5 Отправка в ComfyUI при `--run`, ожидание, сохранение в `output\mm_moss_<режим>_<время>.*`.
- [ ] 2.6 CLI: `start.bat image moss-t2i "текст" --run` и т.д. `list` и `check` показывают MOSS-режимы.

- [ ] 2.7 ComfyUI для MOSS: цель `image` из `config.json` (`http://127.0.0.1:8291`, `D:/ComfyUi2`, `start_bat` = `start_comfyu2i.bat`). Значения уже совпадают, менять только если выяснится обратное. `--start` запускает ComfyUI этим bat, если порт 8291 не отвечает.
- [ ] 2.8 Prompt Enhancer: LLM = `C:\ai_diffusion\models\LLM\Qwen3-VL-4B-Instruct-abliterated.Q8_0.gguf`. Способ вызова (ноды в workflow или llama-server) — по итогам 0.4. Если нужен llama-server — путь к exe и порт брать из существующих настроек проекта/`config.json`, не выдумывать. Путь к GGUF вынести в `config.json`.

### Фаза 3 — Turbo

- [ ] 3.1 Два Turbo-пути для MOSS: (a) LoRA `MOSS-Image-SFT-8-steps-dmd` (8 шагов), (b) `RapidMOSSAdapter` `rapid-moss-4step` (4 шага, как в `moss4StepWorkflow_v10`). Steps/cfg/sampler взять из workflow и Note.
- [ ] 3.2 CLI: существующий синтаксис `--turbo <имя>` сохранить, для MOSS добавить значения `dmd8`, `rapid4`, `off`. Gradio: один чекбокс «Turbo». Какой путь стоит за чекбоксом для каждого MOSS-режима, кодер определяет в фазе 0 и называет в итоге; предложение: T2I, Inpaint, Detailer — `dmd8`, `moss-4step` — `rapid4` (workflow уже 4-шаговый). По умолчанию Turbo ВКЛ.
- [ ] 3.3 Turbo ВЫКЛ → базовые steps/cfg без LoRA.
- [ ] 3.4 Проверить, что чекбокс Turbo в UI одинаково работает для krea2, qwen21, qwen-edit, zimage, klein (таблица в README) и не ломается при смене режима.

### Фаза 4 — Gradio UI

- [ ] 4.1 MOSS-режимы в `IMAGE_MODES` и `MODE_LABELS` с понятными подписями.
- [ ] 4.2 Опции под режим (показывать только нужные): T2I — размер, seed, steps (авто от Turbo); Inpaint — загрузка изображения и рисование маски (редактор масок в установленной версии gradio); Detailer — изображение, число лиц 1–4, SeedVR2 upscale вкл/выкл; Prompt enhancer — текст → улучшенный промт (LLM из 2.8), с кнопкой «передать в T2I»; 4-Step — как T2I с Turbo rapid4.
- [ ] 4.3 ОДИН чекбокс «Turbo» для всех image-режимов, включая MOSS. Выбора варианта в UI нет, вариант определяется режимом (см. 3.2).
- [ ] 4.4 Статус: ComfyUI доступен? Нужные ноды и модели найдены? Если нет — сказать, чего именно не хватает.
- [ ] 4.5 Результат: превью/галерея и путь в `output\`, кнопка «открыть папку».
- [ ] 4.6 `ui_state.json` запоминает и MOSS-режим; старый файл состояния должен читаться без ошибок.
- [ ] 4.7 Поведение существующих режимов (video, остальные image) не менять.

### Фаза 5 — тесты

- [ ] 5.1 Существующие тесты зелёные (включая `test_moss_workflows.py`).
- [ ] 5.2 Новые offline-тесты: патч MOSS-графа (prompt, seed, steps, Turbo вкл/выкл), ошибка при отсутствующей модели, `list`/`check` видят MOSS-режимы, `mm_ui` собирает `gr.Blocks` без `launch`, `start.bat`/`ui.bat`/`install.bat` без «open-creator» и только ASCII.
- [ ] 5.3 Если ComfyUI запущен: ручной смоук `moss-t2i --run` 512x512 (не в unittest).

### Фаза 6 — документация

- [ ] 6.1 `README.md`: Gradio UI, MOSS-режимы, Turbo, LTX-2.5, сцены/vLLM, структура папок, актуальные команды. Без open-creator.
- [ ] 6.2 Короткий `docs\moss.md`: какие workflows, модели и ноды нужны.

### Фаза 7 — приёмка (делает пользователь)

- [ ] `start.bat` показывает меню, [G] открывает UI на http://127.0.0.1:7865
- [ ] MOSS T2I: промт → картинка в `output\` (Turbo вкл и выкл)
- [ ] Inpaint, Detailer, Prompt enhancer, 4-Step запускаются
- [ ] Video-режимы работают как раньше
- [ ] Модели нигде не копировались: размер папок ComfyUI не вырос, всё берётся с исходных путей
- [ ] В папке проекта нет упоминаний open-creator (кроме этого плана)

## Остаётся открытым

1. Способ вызова LLM в Prompt Enhancer и наличие mmproj — выяснить в 0.4 и назвать в итоге фазы 0.



