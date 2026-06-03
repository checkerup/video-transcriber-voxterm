[![English](https://img.shields.io/badge/lang-English-blue.svg)](README.md) [![Русский](https://img.shields.io/badge/lang-Русский-red.svg)](README.ru.md) [![中文](https://img.shields.io/badge/lang-中文-green.svg)](README.zh.md)

> **This is a fork** of [`checkerup/video-transcriber`](https://github.com/checkerup/video-transcriber)
> that adds **offline speaker diarization** (who-said-what, no HuggingFace token)
> and a **live-recording mode** (mic / mic+screen / mic+screen+system-audio,
> transcribed automatically when you stop).
>
> The diarization pipeline is inspired by [`VoxTerm`](https://github.com/dmarzzz/VoxTerm)
> by [@dmarzzz](https://github.com/dmarzzz) — full credits in [`NOTICE.md`](NOTICE.md).
> ✨ **This branch ships a desktop GUI** built on PyWebView.
> Launch with `python -m video_transcriber.main --gui` after `pip install -e .[gui]`.
> If you only need the CLI, the matching CLI-only branch is
> [`feat/voxterm-integration`](https://github.com/checkerup/video-transcriber-voxterm/tree/feat/voxterm-integration).


# Video Transcriber

Automatic video transcription: watches a folder or program launches, records screen, transcribes locally (free!), sends Telegram notifications.

**Whisper is a completely free model (MIT license).** Everything runs locally — nothing leaves your machine.

## Features

- **Auto screen recording** — when a target program (Zoom, OBS, etc.) launches, screen recording starts automatically; when it closes, recording stops and transcription begins
- **Hardware auto-detect** — checks CPU/RAM/GPU and recommends the optimal Whisper model
- **First-run wizard** — interactive 6-step setup on first launch
- **Folder watcher** — watchdog automatically catches new video files
- **Audio extraction** — FFmpeg pulls MP3 without re-encoding
- **Transcription** — faster-whisper (local, free, private) with timestamps
- **Notifications** — Telegram bot reports when done with file paths
- **Autostart** — install as auto-start service with one command (Windows/macOS/Linux)
- **Interactive menu** — `menu.bat` / `menu.sh` with all modes
- **Cross-platform** — Windows, macOS, Linux
- **Offline speaker diarization** — sherpa-onnx + 3D-Speaker (CAM++ / ERes2NetV2) + pyannote-3.0 segmentation. Fully local, no HF token, models auto-downloaded on first run (~30 MB). Inspired by VoxTerm.
- **Live recording mode** — `--record-live voice|screen|full` records mic (and optionally screen + system-audio loopback), then auto-transcribes on stop. Windows uses WASAPI loopback, **no VB-Cable required**.
- **Audio capture during screen recording** — the screen recorder captures mic + system audio by default (`recorder.audio_mode: both`). Configure via `config.yaml` or the Settings tab in the desktop UI.

## Quick Start

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

On **first run**, the setup wizard launches automatically:
1. Hardware check → model recommendation
2. Folder setup (watch folder, output folder)
3. Language & transcript format selection (txt/srt/vtt)
4. Telegram setup (bot token + chat ID)
5. Process Watcher setup (auto-record on program launch)
6. Autostart offer

## Interactive Menu

Run `menu.bat` (Windows) or `./menu.sh` (macOS/Linux):

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

## Operating Modes

### 1. Daemon — Folder Watch

Watches a folder, new videos are processed automatically. If `program_names` are configured, Process Watcher runs in parallel.

```bash
python -m video_transcriber.main
```

### 2. Process Watcher — Auto-record on Program Launch

When a target program (e.g. Zoom) launches — screen recording starts automatically. When it closes — recording stops and transcription begins.

In `config.yaml`:
```yaml
process_watcher:
  program_names: ["Zoom.exe", "obs64.exe"]
  poll_interval: 5
```

Or via CLI:
```bash
python -m video_transcriber.main --watch-process "Zoom.exe"
```

Monitor multiple programs:
```bash
python -m video_transcriber.main --watch-process "Zoom.exe,Teams.exe"
```

### 3. Manual Screen Recording

Start recording → Ctrl+C → stop → transcribe. Captures audio alongside the screen (configurable via `recorder.audio_mode`):

```bash
python -m video_transcriber.main --record
```

### 4. Single File

Process a specific video without the daemon:

```bash
python -m video_transcriber.main --file "video.mp4"
```

## Full Pipeline

```
Video appears in folder (or screen recording finishes)
  → FFmpeg extracts audio track to MP3
  → faster-whisper transcribes (with timestamps)
  → Text saved (txt/srt/vtt)
  → Telegram bot sends notification with file paths
```

## CLI (all flags)

```bash
python -m video_transcriber.main                        # daemon (folder + process watcher)
python -m video_transcriber.main --file "vid.mp4"       # single file
python -m video_transcriber.main --record               # manual screen recording
python -m video_transcriber.main --watch-process "Zoom" # auto-record on program launch
python -m video_transcriber.main --setup                # re-run setup wizard
python -m video_transcriber.main --check-hardware       # detect hardware
python -m video_transcriber.main --install-autostart    # install autostart
python -m video_transcriber.main --uninstall-autostart  # remove autostart
python -m video_transcriber.main --config my.yaml       # custom config
python -m video_transcriber.main --verbose              # debug logging
```

## Configuration

`config.yaml` (created by wizard automatically, or manually from `config.example.yaml`):

```yaml
watch:
  folder: "~/Videos/Incoming"       # folder to monitor
  extensions: [.mp4, .mkv, .avi, .mov, .webm]
  delay_seconds: 10                 # wait before processing (file must finish writing)

processing:
  output_folder: "~/Videos/Processed"  # where to save results
  audio_format: "mp3"
  audio_bitrate: "192k"
  keep_audio: true                  # keep MP3 after transcription

transcription:
  model_size: "base"               # tiny/base/small/medium/large-v2
  device: "auto"                    # auto/cpu/cuda (auto = detect GPU)
  compute_type: "int8"             # int8/int8_float16/float16
  language: "en"                    # language or "auto" for auto-detect
  output_format: "txt"             # txt/srt/vtt
  word_timestamps: true             # timestamps for each word

telegram:
  bot_token: ""                    # from @BotFather (or in .env)
  chat_id: ""                      # your chat ID (or in .env)

recorder:
  fps: 30                          # screen recording FPS
  # video_size: "1920x1080"        # resolution (Linux/x11grab only)
  audio_mode: both                 # none | mic | system | both (default: both)
  mic_device: ""                   # leave empty for OS default
  system_device: ""                # leave empty for OS default loopback

process_watcher:
  program_names: ["Zoom.exe"]       # process names to watch for
  poll_interval: 5                  # seconds between checks
```

Secrets via `.env` (alternative to config.yaml):
```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=123456789
```

## How Process Watcher Works

```
Zoom.exe launches
  → psutil detects process (every 5 sec)
  → FFmpeg starts screen recording (gdigrab/avfoundation/x11grab)
Zoom.exe exits
  → FFmpeg stops (sends 'q' signal)
  → Video saved to ~/Videos/Processed/screen_2025-01-15_14-30-00.mp4
  → Pipeline runs: MP3 → transcription → Telegram notification
```

## Screen Recording — Platforms

| OS | FFmpeg Method | Notes |
|----|---------------|-------|
| Windows | `-f gdigrab -i desktop` | Works out of the box |
| macOS | `-f avfoundation -i 1` | Requires Screen Recording permission in System Settings → Privacy |
| Linux | `-f x11grab -i :0.0` | Requires X11. On Wayland: use pipewire or switch to X11 |

## Audio Capture

The screen recorder captures **mic + system audio by default** (`recorder.audio_mode: both`).
Set it to `mic`, `system`, or `none` in `config.yaml`, or pick devices from the
Settings tab in the desktop UI. Full details in [docs/audio.md](docs/audio.md).

| Mode | What gets captured |
|------|--------------------|
| `none` | Video only (legacy behaviour) |
| `mic` | Microphone only |
| `system` | System audio ("what you hear") only |
| `both` | Mic + System mixed into one AAC track (default) |

> **Note:** This is separate from the Live tab's `--record-live` mode, which uses
> `sounddevice`/`soundcard` for audio capture. The screen recorder uses FFmpeg
> directly (dshow on Windows, avfoundation on macOS, PulseAudio on Linux).

## Whisper Models (free, MIT license)

The model downloads **once** automatically on first run. All OpenAI Whisper models are open-source (MIT), free forever.

| Size | RAM/VRAM | Speed | Quality | Auto-select when |
|------|----------|-------|---------|------------------|
| tiny | ~1 GB | fastest | basic | < 4GB RAM, no GPU |
| base | ~1 GB | fast | good | 4-8GB RAM or 1.5GB VRAM |
| small | ~2 GB | moderate | great | 8-16GB RAM or 2.5GB VRAM |
| medium | ~5 GB | slow | excellent | 16GB+ RAM or 5GB+ VRAM |
| large-v2 | ~10 GB | v.slow | best | 10GB+ VRAM |

## Autostart (OS-specific)

| OS | Method | Location |
|----|--------|----------|
| Windows | Task Scheduler | `schtasks /Create /SC ONLOGON` |
| macOS | LaunchAgent | `~/Library/LaunchAgents/com.video-transcriber.plist` |
| Linux | systemd user service | `~/.config/systemd/user/video-transcriber.service` |

## AI Summarization (Gemini)

You can enable automatic transcription summarization and chapter generation using the Gemini API. The summary will be saved to `{filename}_summary.md` and sent to your Telegram bot.

To enable it, set `summarization.enabled: true` in `config.yaml` and provide your `api_key`.

### Changing the Model
You can change the `summarization.model` parameter in `config.yaml` (e.g. to `gemini-1.5-pro` or `gemini-2.0-flash-exp`) or override it via CLI:
```bash
python -m video_transcriber.main --summarize --summarization-model "gemini-1.5-pro"
```

### Changing the Prompt
You can customize the prompt sent to Gemini by editing the `summarization.prompt` option in `config.yaml` or using the `--summarization-prompt` CLI option.

Use the `{text}` placeholder within your prompt to specify where the transcription text should be injected. For example:
```yaml
summarization:
  enabled: true
  api_key: "your_api_key"
  model: "gemini-1.5-flash"
  prompt: "Read the following transcription and summarize the main decisions in English: {text}"
```

If the prompt does not contain the `{text}` placeholder, the transcription text will automatically be appended to the end of the prompt.

## CUDA (GPU Acceleration)

The script auto-detects NVIDIA GPU via `torch.cuda` or `nvidia-smi`. If CUDA is available — transcription runs on GPU (3-10x faster than CPU).

Manual CUDA dependency install:
```bash
pip install video-transcriber[cuda]
```

In config: `device: "cuda"` (or `"auto"` — detects automatically).

## Requirements

- **Python 3.10+**
- **FFmpeg** — auto-installed via `install.bat` (winget) or `install.sh` (brew/apt)
- **NVIDIA GPU** (optional) — for GPU acceleration

## Project Structure

```
video-transcriber/
├── src/video_transcriber/
│   ├── hardware.py          # CPU/RAM/GPU detect, model recommendation
│   ├── setup_wizard.py      # interactive first-run wizard
│   ├── autostart.py         # autostart (Windows/macOS/Linux)
│   ├── process_watcher.py   # process monitoring (psutil)
│   ├── screen_recorder.py   # screen recording (FFmpeg) with audio capture
│   ├── audio_devices.py     # enumerate audio input devices (dshow/AVFoundation/PulseAudio)
│   ├── config.py            # config loader (YAML + .env) + audio_mode fields
│   ├── config_migration.py  # auto-migrate legacy config to PR1 schema
│   ├── diarizer.py          # diarization dispatcher (voxterm | pyannote)
│   ├── diarizer_voxterm.py  # offline diarization (sherpa-onnx, VoxTerm-style)
│   ├── live_recorder.py     # live mic/screen/full recording + auto-transcribe
│   ├── watcher.py           # folder watching (watchdog)
│   ├── extractor.py         # FFmpeg → MP3
│   ├── transcriber.py       # faster-whisper transcription
│   ├── notifier.py          # Telegram notifications
│   ├── pipeline.py          # pipeline orchestration
│   ├── main.py              # CLI entry point
│   └── webui/               # desktop GUI (PyWebView)
│       ├── api.py           # JsApi bridge (Python ↔ JavaScript)
│       ├── app.py           # pywebview window launcher
│       ├── jobs.py          # background job manager
│       └── static/          # HTML/CSS/JS frontend (Alpine.js)
├── docs/
│   └── audio.md             # audio capture configuration guide
├── menu.bat / menu.sh       # interactive menu
├── install.bat / install.sh # auto-installer
├── start.bat / start.sh     # quick start
├── stop.bat / stop.sh       # stop service
├── config.example.yaml      # config example
├── .env.example             # secrets example
├── pyproject.toml           # Python package
├── requirements.txt         # dependencies
└── LICENSE                  # MIT
```

## 🎨 Desktop GUI

A single-window cross-platform GUI built on PyWebView. No build step, ~60 KB of static assets, runs on the same Python pipeline as the CLI. All settings round-trip through `config.yaml`, so the CLI and GUI stay in sync.

### Install + run

```bash
pip install -e .[gui]
python -m video_transcriber.main --gui
```

### Tabs

| Tab | What's there |
|---|---|
| 📥 **Process** | Click to browse a file → settings form (Whisper model, language, translate-to, summarize, full diarization block with backend / model / cluster-threshold slider / num-speakers) → Start. Live progress with stage / elapsed / ETA + a 30-line log tail. Cancel in-flight jobs. |
| 🎙 **Live** | Voice / Screen / Full record mode (sounddevice/soundcard), Start/Stop, auto-queue for transcription on stop. Plus **Screen recorder** card (FFmpeg-based, captures audio via configured devices). |
| 📋 **History** | Past runs from `timing.json` reports. Click a run to open the transcript drawer with **🔁 Retag speakers** controls (num-speakers + threshold slider — re-runs ONLY diarization, no Whisper re-cost). |
| ⚙ **Settings** | Folders, **Audio capture** card (audio mode, mic/loopback device pickers), AI / LLM card (provider radio, API key with mask, model, prompt, temperature, language, **🧪 Test connection** button), Telegram card (token + chat-id + attachment toggles), raw `config.yaml` editor. |
| 🔧 **System** | Hardware probe (CPU / GPU / RAM), recent stderr tail, version, credits. |

### Notes

- On Windows uses the built-in Edge WebView2 (already shipped with Windows 10+). No Chromium download.
- Drag-and-drop is intentionally disabled — pywebview's HTML5 drop never gives a real OS file path. The drop zone falls back to the native file picker.
- Polling is adaptive: 1000 ms while a job is active, 3000 ms when idle.
- A bottom diagnostic strip surfaces JS errors. It auto-collapses to a small icon after 4 s of clean boot. Click to re-open if something goes wrong.

## Speaker Diarization (who-said-what)

Two backends are available, configurable in `config.yaml` under `diarization:`.

### `voxterm` backend — *default, fully offline, no HF token* ⭐

Uses [`sherpa-onnx`](https://github.com/k2-fsa/sherpa-onnx) with a pyannote-3.0
segmentation model + a 3D-Speaker embedding model (CAM++ by default, ERes2NetV2
optional). Inspired by [`VoxTerm`](https://github.com/dmarzzz/VoxTerm) — full
attribution in [`NOTICE.md`](NOTICE.md).

```bash
pip install video-transcriber[diarization-voxterm]
```

```yaml
diarization:
  enabled: true
  backend: "voxterm"      # default
  model: "cam++"          # or "eres2net"
  cluster_threshold: 0.5  # lower = more speakers, higher = fewer
  num_speakers: null      # set to an integer to force a known speaker count
```

Models (~30 MB) are downloaded once into `~/.cache/video-transcriber/diarization/`
and reused offline forever after.

### `pyannote` backend — *legacy, requires HF token*

The original backend that uses the gated `pyannote/speaker-diarization-3.1`
pipeline. Needs a HuggingFace token + accepting model terms on the HF page.

```bash
pip install video-transcriber[diarization-pyannote]
```

```yaml
diarization:
  enabled: true
  backend: "pyannote"
  hf_token: "hf_xxx"
```

### Output

Transcript lines are tagged with the speaker label, e.g.:

```
[00:00:03 → Speaker 1] Hi, how's it going?
[00:00:05 → Speaker 2] Pretty good, did you get a chance to look...
[00:00:09 → Speaker 1] Yeah, by the way...
```

SRT / VTT outputs include speaker labels in the cue text.

## Live Recording Mode

Record audio (and optionally screen) directly from the CLI, get a
transcribed + diarized output as soon as you press `Ctrl+C`.

```bash
# mic only -> .wav + transcript
python -m video_transcriber.main --record-live voice

# screen + mic -> .mp4 + transcript
python -m video_transcriber.main --record-live screen

# screen + mic + system-audio loopback -> .mp4 + transcript
# (perfect for transcribing Zoom / Meet calls including the other side)
python -m video_transcriber.main --record-live full
```

Output goes to a timestamped folder under the configured `processing.output_folder`:

```
recordings/2026-05-28_04-15-22/
├── audio.wav           # mixed mic + system audio (mono 16k)
├── screen.mp4          # only for screen / full modes
├── transcript.txt      # speaker-tagged transcript
└── transcript.srt      # subtitles with speaker labels
```

### Platform notes for system-audio loopback (`full` mode)

| OS | How it works | Extra setup |
|---|---|---|
| **Windows 10/11** | WASAPI loopback via `soundcard` | None — works on a vanilla machine |
| **macOS 13+** | ScreenCaptureKit when `soundcard` supports it | Otherwise install [BlackHole](https://existential.audio/blackhole/) and select it as input |
| **Linux** | PulseAudio / PipeWire monitor source | Most distros have it out of the box |

Install the live-recording extra:

```bash
pip install video-transcriber[live-record]
```

## Credits

This fork builds on top of [`checkerup/video-transcriber`](https://github.com/checkerup/video-transcriber)
and is heavily inspired by:

- **[VoxTerm](https://github.com/dmarzzz/VoxTerm)** by [@dmarzzz](https://github.com/dmarzzz) — the project that demonstrated this diarization stack works fully on-device, cross-platform, with no HF token. The new `diarizer_voxterm.py` re-implements its conceptual pipeline (VAD → segmentation → speaker embedding → cosine clustering) on top of `sherpa-onnx`. **No code is copied verbatim from VoxTerm**, but the design owes a clear debt to it. MIT-licensed; see [`NOTICE.md`](NOTICE.md) for the full attribution.

Underlying ML components:

- **[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)** — Apache-2.0 — ONNX inference runtime.
- **[3D-Speaker](https://github.com/modelscope/3D-Speaker)** (CAM++ / ERes2NetV2) — Apache-2.0 — speaker embeddings.
- **[pyannote.audio](https://github.com/pyannote/pyannote-audio)** — MIT (code) / CC-BY 4.0 (model) — segmentation 3.0.
- **[Silero VAD](https://github.com/snakers4/silero-vad)** — MIT — voice-activity detection.
- **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** — MIT — transcription.

Full third-party notices: [`NOTICE.md`](NOTICE.md).

## License

MIT
