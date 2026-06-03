[![English](https://img.shields.io/badge/lang-English-blue.svg)](README.md) [![Русский](https://img.shields.io/badge/lang-Русский-red.svg)](README.ru.md) [![中文](https://img.shields.io/badge/lang-中文-green.svg)](README.zh.md)

> **Это форк** [`checkerup/video-transcriber`](https://github.com/checkerup/video-transcriber),
> в который добавлены **оффлайн-диаризация спикеров** (кто-что-сказал, без HF-токена)
> и **режим live-записи** (микрофон / микрофон+экран / микрофон+экран+системный звук,
> с автоматической расшифровкой по нажатию `Ctrl+C`).
>
> Пайплайн диаризации вдохновлён [`VoxTerm`](https://github.com/dmarzzz/VoxTerm)
> от [@dmarzzz](https://github.com/dmarzzz) — полная атрибуция в [`NOTICE.md`](NOTICE.md).
> ✨ **В этой ветке десктопный GUI** на PyWebView.
> Запуск: `python -m video_transcriber.main --gui` после `pip install -e .[gui]`.
> Если нужен только CLI — есть зеркальная ветка
> [`feat/voxterm-integration`](https://github.com/checkerup/video-transcriber-voxterm/tree/feat/voxterm-integration).


# Video Transcriber

Автоматическая расшифровка видео: следит за папкой или запуском программ, записывает экран, транскрибирует локально (бесплатно!), шлет уведомление в Telegram.

**Whisper — полностью бесплатная модель (MIT лицензия).** Всё работает локально, ничего не уходит в облако.

## Возможности

- **Автозапись экрана** — при запуске программы (Zoom, OBS и т.д.) автоматически начинается запись экрана, при закрытии — стоп + транскрипция
- **Автодетект железа** — скрипт проверяет CPU/RAM/GPU и подбирает оптимальную модель
- **First-run визард** — при первом запуске интерактивная настройка (6 шагов)
- **Слежка за папкой** — watchdog автоматически ловит новые видеофайлы
- **Экстракция аудио** — FFmpeg вытягивает MP3 без перекодирования
- **Транскрибация** — faster-whisper (локально, бесплатно, приватно) с таймкодами
- **Уведомления** — Telegram-бот сообщает когда готово
- **Автозапуск** — установка в автозапуск одной командой (Windows/macOS/Linux)
- **Интерактивное меню** — `menu.bat` / `menu.sh` со всеми режимами
- **Кроссплатформенный** — Windows, macOS, Linux
- **Оффлайн-диаризация спикеров** — sherpa-onnx + 3D-Speaker (CAM++ / ERes2NetV2) + pyannote-3.0 segmentation. Полностью локально, без HF-токена, модели подкачиваются автоматически при первом запуске (~30 МБ). Вдохновлено VoxTerm.
- **Режим live-записи** — `--record-live voice|screen|full` пишет микрофон (опционально + экран + системный звук), при остановке автоматически транскрибирует. На Windows используется WASAPI loopback, **VB-Cable не нужен**.

## Быстрый старт

### Windows

```bat
git clone https://github.com/checkerup/video-transcriber-voxterm.git
cd video-transcriber-voxterm
install.bat
menu.bat
```

### macOS / Linux

```bash
git clone https://github.com/checkerup/video-transcriber-voxterm.git
cd video-transcriber-voxterm
chmod +x install.sh menu.sh start.sh stop.sh
./install.sh
./menu.sh
```

При **первом запуске** автоматически запустится визард:
1. Проверка железа → рекомендация модели
2. Настройка путей (watch folder, output folder)
3. Выбор языка и формата транскрипта (txt/srt/vtt)
4. Настройка Telegram (bot token + chat ID)
5. Настройка Process Watcher (автозапись при запуске программы)
6. Предложение установить в автозапуск

## Интерактивное меню

Запустите `menu.bat` (Windows) или `./menu.sh` (macOS/Linux):

```
  ╔══════════════════════════════════════════════╗
  ║       Video Transcriber — Main Menu          ║
  ╚══════════════════════════════════════════════╝

  [1]  Setup / Install           (first run)
  [2]  Start daemon              (watch folder)
  [3]  Process single file       (one-shot)
  [4]  Screen recording          (manual, Ctrl+C stop)
  [5]  Watch process + record    (auto on program launch)
  [6]  Check hardware            (CPU/RAM/GPU)
  [7]  Re-run setup wizard
  [8]  Install autostart
  [9]  Uninstall autostart
  [10] Push to GitHub
  [0]  Exit
```

## Режимы работы

### 1. Демон — слежка за папкой

Следит за папкой, новые видео обрабатываются автоматически. Если в конфиге указаны `program_names`, параллельно работает Process Watcher.

```bash
python -m video_transcriber.main
```

### 2. Process Watcher — автозапись при запуске программы

Когда программа (например Zoom) запустилась — автоматически начинается запись экрана. Когда закрылась — запись останавливается и запускается транскрипция.

В `config.yaml`:
```yaml
process_watcher:
  program_names: ["Zoom.exe", "obs64.exe"]
  poll_interval: 5
```

Или через CLI:
```bash
python -m video_transcriber.main --watch-process "Zoom.exe"
```

Можно мониторить несколько программ через запятую:
```bash
python -m video_transcriber.main --watch-process "Zoom.exe,Teams.exe"
```

### 3. Ручная запись экрана

Начать запись → Ctrl+C → стоп → транскрипция:

```bash
python -m video_transcriber.main --record
```

### 4. Один файл

Обработать конкретное видео без демона:

```bash
python -m video_transcriber.main --file "video.mp4"
```

## Полный пайплайн

```
Видео появилось в папке (или запись экрана завершена)
  → FFmpeg извлекает аудиодорожку в MP3
  → faster-whisper транскрибирует (с таймкодами)
  → Текст сохраняется (txt/srt/vtt)
  → Telegram-бот отправляет уведомление с путями к файлам
```

## CLI (все флаги)

```bash
python -m video_transcriber.main                        # демон (папка + process watcher)
python -m video_transcriber.main --file "vid.mp4"       # один файл
python -m video_transcriber.main --record               # ручная запись экрана
python -m video_transcriber.main --watch-process "Zoom" # автозапись при запуске программы
python -m video_transcriber.main --setup                 # перенастроить (визард)
python -m video_transcriber.main --check-hardware       # проверить железо
python -m video_transcriber.main --install-autostart    # установить автозапуск
python -m video_transcriber.main --uninstall-autostart  # убрать автозапуск
python -m video_transcriber.main --config my.yaml       # использовать свой конфиг
python -m video_transcriber.main --verbose              # debug логирование
```

## Конфигурация

`config.yaml` (создается визардом автоматически, или вручную из `config.example.yaml`):

```yaml
watch:
  folder: "~/Videos/Incoming"       # папка для слежки
  extensions: [.mp4, .mkv, .avi, .mov, .webm]
  delay_seconds: 10                 # ожидание до обработки (файл должен дозаписаться)

processing:
  output_folder: "~/Videos/Processed"  # куда сохранять результаты
  audio_format: "mp3"
  audio_bitrate: "192k"
  keep_audio: true                  # сохранять MP3 после транскрибации

transcription:
  model_size: "base"               # tiny/base/small/medium/large-v2
  device: "auto"                    # auto/cpu/cuda (auto = определит GPU)
  compute_type: "int8"             # int8/int8_float16/float16
  language: "ru"                    # язык или "auto" для автоопределения
  output_format: "txt"             # txt/srt/vtt
  word_timestamps: true             # таймкоды для каждого слова

telegram:
  bot_token: ""                    # от @BotFather (или в .env)
  chat_id: ""                      # ваш chat ID (или в .env)

recorder:
  fps: 30                          # FPS записи экрана
  # video_size: "1920x1080"        # разрешение (только для Linux/x11grab)

process_watcher:
  program_names: ["Zoom.exe"]       # имена процессов для отслеживания
  poll_interval: 5                  # секунд между проверками
```

Секреты через `.env` (альтернатива config.yaml):
```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=123456789
```

## Как работает Process Watcher

```
Zoom.exe запустился
  → psutil обнаруживает процесс (каждые 5 сек)
  → FFmpeg начинает запись экрана (gdigrab/avfoundation/x11grab)
Zoom.exe закрылся
  → FFmpeg останавливается (отправляется сигнал 'q')
  → Видео сохраняется в ~/Videos/Processed/screen_2025-01-15_14-30-00.mp4
  → Запускается пайплайн: MP3 → транскрибация → Telegram уведомление
```

## Запись экрана — платформы

| ОС | Метод FFmpeg | Примечание |
|----|-------------|------------|
| Windows | `-f gdigrab -i desktop` | Работает из коробки |
| macOS | `-f avfoundation -i 1` | Требуется разрешение: Системные настройки → Конфиденциальность → Запись экрана |
| Linux | `-f x11grab -i :0.0` | Требует X11. На Wayland: использовать pipewire или переключиться на X11 |

## Захват аудио

Экранный рекордер по умолчанию захватывает **микрофон + системный звук** (`recorder.audio_mode: both`).
Установите `mic`, `system` или `none` в `config.yaml`, или выберите устройства
во вкладке Settings в десктопном UI. Подробности в [docs/audio.md](docs/audio.md).

| Режим | Что записывается |
|-------|-----------------|
| `none` | Только видео (старое поведение) |
| `mic` | Только микрофон |
| `system` | Только системный звук («то, что слышно») |
| `both` | Микрофон + системный звук, смешанные в одну AAC-дорожку (по умолчанию) |

> **Примечание:** Это отдельная функция от режима `--record-live` во вкладке Live,
> который использует `sounddevice`/`soundcard`. Экранный рекордер работает
> напрямую через FFmpeg (dshow на Windows, avfoundation на macOS, PulseAudio на Linux).

## Модели Whisper (бесплатные, MIT лицензия)

Модель скачивается **один раз** автоматически при первом запуске. Все модели OpenAI Whisper — открытые (MIT), бесплатны навсегда.

| Размер | RAM/VRAM | Скорость | Качество | Автовыбор при |
|--------|----------|----------|----------|---------------|
| tiny   | ~1 GB    | fastest  | basic    | < 4GB RAM, нет GPU |
| base   | ~1 GB    | fast     | good     | 4-8GB RAM или 1.5GB VRAM |
| small  | ~2 GB    | moderate | great    | 8-16GB RAM или 2.5GB VRAM |
| medium | ~5 GB    | slow     | excellent| 16GB+ RAM или 5GB+ VRAM |
| large-v2| ~10 GB  | v.slow   | best     | 10GB+ VRAM |

## Автозапуск (OS-специфичный)

| ОС | Метод | Расположение |
|----|-------|-------------|
| Windows | Task Scheduler | `schtasks /Create /SC ONLOGON` |
| macOS | LaunchAgent | `~/Library/LaunchAgents/com.video-transcriber.plist` |
| Linux | systemd user service | `~/.config/systemd/user/video-transcriber.service` |

## ИИ-Суммаризация (Gemini)

Вы можете включить автоматическое составление резюме (summary) и оглавления по главам с помощью Gemini API. Резюме будет сохранено в файл `{имя_файла}_summary.md` и отправлено в ваш Telegram-бот.

Для активации установите `summarization.enabled: true` в `config.yaml` и укажите ваш `api_key`.

### Смена модели
Вы можете изменить параметр `summarization.model` в `config.yaml` (например, на `gemini-1.5-pro` или `gemini-2.0-flash-exp`) или переопределить модель через CLI:
```bash
python -m video_transcriber.main --summarize --summarization-model "gemini-1.5-pro"
```

### Изменение промпта (Prompt)
Вы можете настроить промпт, отправляемый в Gemini, отредактировав опцию `summarization.prompt` в `config.yaml` или используя параметр командной строки `--summarization-prompt`.

Используйте плейсхолдер `{text}` внутри промпта для указания места, куда должен быть вставлен текст расшифровки. Например:
```yaml
summarization:
  enabled: true
  api_key: "ваш_api_key"
  model: "gemini-1.5-flash"
  prompt: "Прочитай следующий текст расшифровки и выдели главные решения на русском языке: {text}"
```

Если промпт не содержит плейсхолдера `{text}`, текст расшифровки будет автоматически добавлен в конец промпта.

## CUDA (GPU ускорение)

Скрипт автоматически обнаружит NVIDIA GPU через `torch.cuda` или `nvidia-smi`. Если CUDA доступна — транскрибация пойдёт на GPU (в 3-10 раз быстрее CPU).

Ручная установка CUDA-зависимостей:
```bash
pip install video-transcriber[cuda]
```

В конфиге: `device: "cuda"` (или `"auto"` — определит автоматически).

## Требования

- **Python 3.10+**
- **FFmpeg** — автоматически установится через `install.bat` (winget) или `install.sh` (brew/apt)
- **NVIDIA GPU** (опционально) — для GPU-ускорения

## Структура проекта

```
video-transcriber/
├── src/video_transcriber/
│   ├── hardware.py          # детект CPU/RAM/GPU, рекомендация модели
│   ├── setup_wizard.py      # интерактивный визард первого запуска
│   ├── autostart.py         # автозапуск (Windows/macOS/Linux)
│   ├── process_watcher.py   # слежка за процессами (psutil)
│   ├── screen_recorder.py   # запись экрана (FFmpeg)
│   ├── config.py            # загрузка конфига (YAML + .env)
│   ├── diarizer.py          # диспетчер диаризации (voxterm | pyannote)
│   ├── diarizer_voxterm.py  # оффлайн-диаризация (sherpa-onnx, в стиле VoxTerm)
│   ├── live_recorder.py     # live-запись микрофон/экран/полный + авто-транскрипт
│   ├── watcher.py           # слежка за папкой (watchdog)
│   ├── extractor.py         # FFmpeg → MP3
│   ├── transcriber.py       # faster-whisper транскрибация
│   ├── notifier.py          # Telegram уведомления
│   ├── pipeline.py          # оркестрация пайплайна
│   └── main.py              # CLI входная точка
├── menu.bat / menu.sh       # интерактивное меню
├── install.bat / install.sh # авто-установка
├── start.bat / start.sh     # быстрый запуск
├── stop.bat / stop.sh       # остановка
├── config.example.yaml      # пример конфига
├── .env.example             # пример секретов
├── pyproject.toml           # Python-пакет
├── requirements.txt         # зависимости
└── LICENSE                  # MIT
```

## 🎨 Десктопный GUI

Одно окно, кроссплатформенный GUI на PyWebView. Без сборки, ~60 КБ статики, тот же пайплайн что и CLI. Все настройки роутятся через `config.yaml`, поэтому CLI и GUI всегда синхронны.

### Установка + запуск

```bash
pip install -e .[gui]
python -m video_transcriber.main --gui
```

### Вкладки

| Вкладка | Что внутри |
|---|---|
| 📥 **Process** | Кликом выбираешь файл → форма настроек (модель Whisper, язык, перевод, саммари, полный блок диаризации: бэкенд / модель / слайдер порога / число спикеров) → Start. Живой прогресс со стадией / прошедшим временем / ETA + последние 30 строк лога. Можно отменить активную задачу. |
| 🎙 **Live** | Режимы Voice / Screen / Full, Start/Stop, автоочередь на транскрипцию после остановки. |
| 📋 **History** | Прошлые запуски из `timing.json`-отчётов. Клик → ящик с транскриптом и **🔁 Retag speakers** (число спикеров + слайдер порога — пересчитывает ТОЛЬКО диаризацию, без повторного Whisper). |
| ⚙ **Settings** | Папки, карта AI / LLM (радио провайдер, API-ключ с маской, модель, промпт, температура, язык, кнопка **🧪 Test connection**), карта Telegram (токен + chat-id + переключатели вложений), редактор сырого `config.yaml`. |
| 🔧 **System** | Информация о железе (CPU / GPU / RAM), хвост stderr, версия, кредитсы. |

### Замечания

- На Windows используется встроенный Edge WebView2 (есть в Windows 10+ из коробки). Никакого Chromium качать не надо.
- Drag-and-drop намеренно отключён — pywebview не отдаёт реальный OS-путь из HTML5 drop. Дроп-зона всегда открывает нативный пикер.
- Адаптивный polling: 1000 мс пока есть активная задача, 3000 мс на холостом ходу.
- Внизу есть диагностическая полоса с JS-ошибками. Через 4 с чистой загрузки сворачивается в иконку.

## Диаризация спикеров (кто-что-сказал)

Доступно два бэкенда, переключаются в `config.yaml` в секции `diarization:`.

### Бэкенд `voxterm` — *по умолчанию, полностью оффлайн, без HF-токена* ⭐

Использует [`sherpa-onnx`](https://github.com/k2-fsa/sherpa-onnx) с моделью
сегментации pyannote-3.0 + модель эмбеддингов 3D-Speaker (по умолчанию CAM++,
опционально ERes2NetV2). Вдохновлено [`VoxTerm`](https://github.com/dmarzzz/VoxTerm) —
полная атрибуция в [`NOTICE.md`](NOTICE.md).

```bash
pip install video-transcriber[diarization-voxterm]
```

```yaml
diarization:
  enabled: true
  backend: "voxterm"      # по умолчанию
  model: "cam++"          # или "eres2net"
  cluster_threshold: 0.5  # ниже = больше спикеров, выше = меньше
  num_speakers: null      # задайте число если знаете точное количество спикеров
```

Модели (~30 МБ) скачиваются один раз в `~/.cache/video-transcriber/diarization/`
и далее переиспользуются оффлайн.

### Бэкенд `pyannote` — *legacy, нужен HF-токен*

Оригинальный бэкенд через gated-пайплайн `pyannote/speaker-diarization-3.1`.
Требуется HuggingFace токен и принятие условий модели на HF.

```bash
pip install video-transcriber[diarization-pyannote]
```

```yaml
diarization:
  enabled: true
  backend: "pyannote"
  hf_token: "hf_xxx"
```

### Выход

Строки транскрипта помечаются ярлыком спикера:

```
[00:00:03 → Спикер 1] Привет, как дела?
[00:00:05 → Спикер 2] Норм, успел посмотреть...
[00:00:09 → Спикер 1] Да, кстати...
```

В SRT / VTT ярлык спикера попадает в текст реплики.

## Режим live-записи

Запиши аудио (и опционально экран) прямо из терминала и получи
транскрипт с диаризацией по `Ctrl+C`.

```bash
# только микрофон -> .wav + транскрипт
python -m video_transcriber.main --record-live voice

# экран + микрофон -> .mp4 + транскрипт
python -m video_transcriber.main --record-live screen

# экран + микрофон + системный звук -> .mp4 + транскрипт
# (идеально для Zoom / Meet — слышно и тебя, и собеседника)
python -m video_transcriber.main --record-live full
```

Результат сохраняется в папку с таймстампом внутри `processing.output_folder`:

```
recordings/2026-05-28_04-15-22/
├── audio.wav           # микс микрофон + системный звук (mono 16k)
├── screen.mp4          # только для screen / full
├── transcript.txt      # транскрипт с разметкой спикеров
└── transcript.srt      # субтитры с ярлыками спикеров
```

### Системный звук (`full`) — нюансы по ОС

| ОС | Как работает | Доп. установка |
|---|---|---|
| **Windows 10/11** | WASAPI loopback через `soundcard` | Ничего не нужно — работает на чистой системе |
| **macOS 13+** | ScreenCaptureKit когда `soundcard` поддерживает | Иначе поставить [BlackHole](https://existential.audio/blackhole/) и выбрать как input |
| **Linux** | PulseAudio / PipeWire monitor-source | Из коробки в большинстве дистров |

Установка опционального экстра:

```bash
pip install video-transcriber[live-record]
```

## Авторы и благодарности

Этот форк построен на основе [`checkerup/video-transcriber`](https://github.com/checkerup/video-transcriber)
и сильно вдохновлён:

- **[VoxTerm](https://github.com/dmarzzz/VoxTerm)** от [@dmarzzz](https://github.com/dmarzzz) — проект, который показал что этот стек диаризации работает полностью локально и кроссплатформенно без HF-токена. Новый модуль `diarizer_voxterm.py` переисполняет его концептуальный пайплайн (VAD → сегментация → эмбеддинг спикера → косинусная кластеризация) поверх `sherpa-onnx`. **Код из VoxTerm не копируется напрямую**, но дизайн ему явно обязан. MIT-лицензия; полная атрибуция в [`NOTICE.md`](NOTICE.md).

Используемые ML-компоненты:

- **[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)** — Apache-2.0 — ONNX-рантайм.
- **[3D-Speaker](https://github.com/modelscope/3D-Speaker)** (CAM++ / ERes2NetV2) — Apache-2.0 — эмбеддинги спикеров.
- **[pyannote.audio](https://github.com/pyannote/pyannote-audio)** — MIT (код) / CC-BY 4.0 (модель) — segmentation 3.0.
- **[Silero VAD](https://github.com/snakers4/silero-vad)** — MIT — детектор речи.
- **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** — MIT — транскрибация.

Полные атрибуции третьих сторон: [`NOTICE.md`](NOTICE.md).

## Лицензия

MIT
