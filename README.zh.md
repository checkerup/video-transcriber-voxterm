[![English](https://img.shields.io/badge/lang-English-blue.svg)](README.md) [![Русский](https://img.shields.io/badge/lang-Русский-red.svg)](README.ru.md) [![中文](https://img.shields.io/badge/lang-中文-green.svg)](README.zh.md)

> **本仓库是 fork** ：基于 [`checkerup/video-transcriber`](https://github.com/checkerup/video-transcriber)
> ，新增了 **离线说话人分离**（谁说了什么，不需要 HuggingFace token）
> 和 **实时录音模式**（麦克风 / 麦克风+屏幕 / 麦克风+屏幕+系统声音，
> 停止时自动转录）。
>
> 说话人分离流程的灵感来自 [@dmarzzz](https://github.com/dmarzzz) 的
> [`VoxTerm`](https://github.com/dmarzzz/VoxTerm) — 完整署名见 [`NOTICE.md`](NOTICE.md)。

> 🎨 **想要图形界面？**
> 基于 PyWebView 的桌面版本（文件选择、实时进度条、设置面板、历史、一键重新说话人分离）
> 位于 [`feat/desktop-ui`](https://github.com/checkerup/video-transcriber-voxterm/tree/feat/desktop-ui) 分支。
> 此分支仅 CLI。


# Video Transcriber

自动视频转录：监控文件夹或程序启动，录制屏幕，本地转录（免费！），发送 Telegram 通知。

**Whisper 是完全免费的模型（MIT 许可证）。** 所有内容在本地运行，不会上传到云端。

## 功能特点

- **自动屏幕录制** — 当目标程序（Zoom、OBS 等）启动时，自动开始屏幕录制；关闭时停止录制并开始转录
- **硬件自动检测** — 检查 CPU/RAM/GPU 并推荐最优 Whisper 模型
- **首次运行向导** — 首次启动时自动运行 6 步交互式设置
- **文件夹监控** — watchdog 自动捕获新视频文件
- **音频提取** — FFmpeg 无需重编码即可提取 MP3
- **转录** — faster-whisper（本地、免费、隐私）带时间戳
- **通知** — Telegram 机器人完成后发送文件路径通知
- **🤖 多供应商 LLM 摘要** — Gemini、OpenAI、Anthropic、OpenRouter，或任何 OpenAI 兼容端点（通过 `api_base`）。
- **📎 可选 Telegram 附件** — 发送字幕文件（或内联文本）、摘要 .md、音频、视频，全部可配置。
- **🔁 重新标注说话人** — 在现有字幕上仅重跑说话人分离，无需重新运行 Whisper（`--retag-speakers PATH --num-speakers N`）。
- **自动启动** — 一键安装为自启动服务（Windows/macOS/Linux）
- **交互式菜单** — `menu.bat` / `menu.sh` 包含所有模式
- **跨平台** — Windows、macOS、Linux
- **离线说话人分离** — sherpa-onnx + 3D-Speaker（CAM++ / ERes2NetV2）+ pyannote-3.0 segmentation。完全本地运行，无需 HF token，首次运行自动下载模型（约 30 MB）。灵感来自 VoxTerm。
- **实时录音模式** — `--record-live voice|screen|full` 录制麦克风（可选 + 屏幕 + 系统声音回环），停止时自动转录。Windows 使用 WASAPI loopback，**无需 VB-Cable**。

## 快速开始

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

**首次运行**时，设置向导会自动启动：
1. 硬件检测 → 模型推荐
2. 文件夹设置（监控文件夹、输出文件夹）
3. 语言和转录格式选择（txt/srt/vtt）
4. Telegram 设置（机器人令牌 + 聊天 ID）
5. 进程监控器设置（程序启动时自动录制）
6. 自启动安装提示

## 交互式菜单

运行 `menu.bat`（Windows）或 `./menu.sh`（macOS/Linux）：

```
  ╔══════════════════════════════════════════════╗
  ║       Video Transcriber — Main Menu          ║
  ╚══════════════════════════════════════════════╝

  [1]  Setup / Install           (首次运行)
  [2]  Start daemon              (监控文件夹)
  [3]  Process single file       (单文件处理)
  [4]  Screen recording          (手动录制，Ctrl+C 停止)
  [5]  Watch process + record    (程序启动时自动录制)
  [6]  Check hardware            (CPU/RAM/GPU)
  [7]  Re-run setup wizard       (重新运行设置向导)
  [8]  Install autostart         (安装自启动)
  [9]  Uninstall autostart       (卸载自启动)
  [10] Push to GitHub
  [0]  Exit
```

## 运行模式

### 1. 守护进程 — 文件夹监控

监控文件夹，新视频自动处理。如果配置了 `program_names`，进程监控器会并行运行。

```bash
python -m video_transcriber.main
```

### 2. 进程监控器 — 程序启动时自动录制

当目标程序（如 Zoom）启动时，自动开始屏幕录制。关闭时停止录制并开始转录。

在 `config.yaml` 中：
```yaml
process_watcher:
  program_names: ["Zoom.exe", "obs64.exe"]
  poll_interval: 5
```

或通过命令行：
```bash
python -m video_transcriber.main --watch-process "Zoom.exe"
```

监控多个程序：
```bash
python -m video_transcriber.main --watch-process "Zoom.exe,Teams.exe"
```

### 3. 手动屏幕录制

开始录制 → Ctrl+C → 停止 → 转录：

```bash
python -m video_transcriber.main --record
```

### 4. 单文件处理

处理特定视频，无需守护进程：

```bash
python -m video_transcriber.main --file "video.mp4"
```

## 完整流程

```
视频出现在文件夹中（或屏幕录制完成）
  → FFmpeg 提取音轨为 MP3
  → faster-whisper 转录（带时间戳）
  → 文本保存（txt/srt/vtt）
  → Telegram 机器人发送通知及文件路径
```

## 命令行（所有参数）

```bash
python -m video_transcriber.main                        # 守护进程（文件夹 + 进程监控）
python -m video_transcriber.main --file "vid.mp4"       # 单文件
python -m video_transcriber.main --record               # 手动屏幕录制
python -m video_transcriber.main --watch-process "Zoom" # 程序启动时自动录制
python -m video_transcriber.main --setup                # 重新运行设置向导
python -m video_transcriber.main --check-hardware       # 检测硬件
python -m video_transcriber.main --install-autostart    # 安装自启动
python -m video_transcriber.main --uninstall-autostart  # 卸载自启动
python -m video_transcriber.main --config my.yaml       # 自定义配置
python -m video_transcriber.main --verbose              # 调试日志
```

## 配置

`config.yaml`（由向导自动创建，或从 `config.example.yaml` 手动创建）：

```yaml
watch:
  folder: "~/Videos/Incoming"       # 监控的文件夹
  extensions: [.mp4, .mkv, .avi, .mov, .webm]
  delay_seconds: 10                 # 处理前等待时间（文件必须写入完成）

processing:
  output_folder: "~/Videos/Processed"  # 结果保存位置
  audio_format: "mp3"
  audio_bitrate: "192k"
  keep_audio: true                  # 转录后保留 MP3

transcription:
  model_size: "base"               # tiny/base/small/medium/large-v2
  device: "auto"                    # auto/cpu/cuda（auto = 自动检测 GPU）
  compute_type: "int8"             # int8/int8_float16/float16
  language: "zh"                    # 语言或 "auto" 自动检测
  output_format: "txt"             # txt/srt/vtt
  word_timestamps: true             # 每个词的时间戳

telegram:
  bot_token: ""                    # 来自 @BotFather（或在 .env 中）
  chat_id: ""                      # 你的聊天 ID（或在 .env 中）

recorder:
  fps: 30                          # 屏幕录制帧率
  # video_size: "1920x1080"        # 分辨率（仅 Linux/x11grab）

process_watcher:
  program_names: ["Zoom.exe"]       # 要监控的进程名称
  poll_interval: 5                  # 检查间隔（秒）
```

通过 `.env` 设置密钥（config.yaml 的替代方案）：
```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=123456789
```

## 进程监控器工作原理

```
Zoom.exe 启动
  → psutil 检测到进程（每 5 秒）
  → FFmpeg 开始屏幕录制（gdigrab/avfoundation/x11grab）
Zoom.exe 退出
  → FFmpeg 停止（发送 'q' 信号）
  → 视频保存到 ~/Videos/Processed/screen_2025-01-15_14-30-00.mp4
  → 运行流程：MP3 → 转录 → Telegram 通知
```

## 屏幕录制 — 平台支持

| 操作系统 | FFmpeg 方法 | 备注 |
|---------|------------|------|
| Windows | `-f gdigrab -i desktop` | 开箱即用 |
| macOS | `-f avfoundation -i 1` | 需要在系统设置 → 隐私 → 屏幕录制中授权 |
| Linux | `-f x11grab -i :0.0` | 需要 X11。Wayland 下：使用 pipewire 或切换到 X11 |

## Whisper 模型（免费，MIT 许可证）

模型在首次运行时**自动下载一次**。所有 OpenAI Whisper 模型都是开源的（MIT），永久免费。

| 大小 | RAM/VRAM | 速度 | 质量 | 自动选择条件 |
|------|----------|------|------|------------|
| tiny | ~1 GB | 最快 | 基础 | < 4GB RAM，无 GPU |
| base | ~1 GB | 快 | 良好 | 4-8GB RAM 或 1.5GB VRAM |
| small | ~2 GB | 中等 | 很好 | 8-16GB RAM 或 2.5GB VRAM |
| medium | ~5 GB | 慢 | 优秀 | 16GB+ RAM 或 5GB+ VRAM |
| large-v2 | ~10 GB | 很慢 | 最佳 | 10GB+ VRAM |

## 自启动（操作系统特定）

| 操作系统 | 方法 | 位置 |
|---------|------|------|
| Windows | 任务计划程序 | `schtasks /Create /SC ONLOGON` |
| macOS | LaunchAgent | `~/Library/LaunchAgents/com.video-transcriber.plist` |
| Linux | systemd 用户服务 | `~/.config/systemd/user/video-transcriber.service` |

## CUDA（GPU 加速）

脚本通过 `torch.cuda` 或 `nvidia-smi` 自动检测 NVIDIA GPU。如果 CUDA 可用，转录将在 GPU 上运行（比 CPU 快 3-10 倍）。

手动安装 CUDA 依赖：
```bash
pip install video-transcriber[cuda]
```

在配置中：`device: "cuda"`（或 `"auto"` — 自动检测）。

## 系统要求

- **Python 3.10+**
- **FFmpeg** — 通过 `install.bat`（winget）或 `install.sh`（brew/apt）自动安装
- **NVIDIA GPU**（可选）— 用于 GPU 加速

## 项目结构

```
video-transcriber/
├── src/video_transcriber/
│   ├── hardware.py          # CPU/RAM/GPU 检测，模型推荐
│   ├── setup_wizard.py      # 首次运行交互式向导
│   ├── autostart.py         # 自启动（Windows/macOS/Linux）
│   ├── process_watcher.py   # 进程监控（psutil）
│   ├── screen_recorder.py   # 屏幕录制（FFmpeg）
│   ├── config.py            # 配置加载（YAML + .env）
│   ├── diarizer.py          # 说话人分离调度器（voxterm | pyannote）
│   ├── diarizer_voxterm.py  # 离线说话人分离（sherpa-onnx，VoxTerm 风格）
│   ├── live_recorder.py     # 实时录音 麦克风/屏幕/完整 + 自动转录
│   ├── watcher.py           # 文件夹监控（watchdog）
│   ├── extractor.py         # FFmpeg → MP3
│   ├── transcriber.py       # faster-whisper 转录
│   ├── notifier.py          # Telegram 通知
│   ├── pipeline.py          # 流程编排
│   └── main.py              # 命令行入口
├── menu.bat / menu.sh       # 交互式菜单
├── install.bat / install.sh # 自动安装
├── start.bat / start.sh     # 快速启动
├── stop.bat / stop.sh       # 停止服务
├── config.example.yaml      # 配置示例
├── .env.example             # 密钥示例
├── pyproject.toml           # Python 包
├── requirements.txt         # 依赖
└── LICENSE                  # MIT
```

## 说话人分离（谁说了什么）

提供两种后端，可在 `config.yaml` 的 `diarization:` 部分配置。

### `voxterm` 后端 — *默认，完全离线，无需 HF token* ⭐

使用 [`sherpa-onnx`](https://github.com/k2-fsa/sherpa-onnx) 加载 pyannote-3.0
分段模型 + 3D-Speaker embedding 模型（默认 CAM++，可选 ERes2NetV2）。
灵感来自 [`VoxTerm`](https://github.com/dmarzzz/VoxTerm) — 完整署名见
[`NOTICE.md`](NOTICE.md)。

```bash
pip install video-transcriber[diarization-voxterm]
```

```yaml
diarization:
  enabled: true
  backend: "voxterm"      # 默认
  model: "cam++"          # 或 "eres2net"
  cluster_threshold: 0.5  # 越低 = 说话人越多，越高 = 越少
  num_speakers: null      # 已知说话人数量时可指定整数
```

模型（约 30 MB）只下载一次到 `~/.cache/video-transcriber/diarization/`，
之后完全离线复用。

### `pyannote` 后端 — *旧版，需要 HF token*

原始后端，调用受限的 `pyannote/speaker-diarization-3.1` 流水线，
需要 HuggingFace token 并在 HF 页面接受模型条款。

```bash
pip install video-transcriber[diarization-pyannote]
```

```yaml
diarization:
  enabled: true
  backend: "pyannote"
  hf_token: "hf_xxx"
```

### 输出

转录文本每一行会带上说话人标签：

```
[00:00:03 → 说话人 1] 你好，最近怎么样？
[00:00:05 → 说话人 2] 还不错，你看过那个...
[00:00:09 → 说话人 1] 看了，对了...
```

SRT / VTT 字幕也会把说话人标签写进文本中。

## 实时录音模式

直接在命令行录制音频（可选屏幕），按 `Ctrl+C` 停止后自动转录 + 分离说话人。

```bash
# 只录麦克风 -> .wav + 转录文本
python -m video_transcriber.main --record-live voice

# 屏幕 + 麦克风 -> .mp4 + 转录文本
python -m video_transcriber.main --record-live screen

# 屏幕 + 麦克风 + 系统声音回环 -> .mp4 + 转录文本
# （非常适合录制 Zoom / Meet 会议，连对方说话都能录到）
python -m video_transcriber.main --record-live full
```

输出保存在 `processing.output_folder` 下的带时间戳的子文件夹中：

```
recordings/2026-05-28_04-15-22/
├── audio.wav           # 麦克风 + 系统声音混音 (mono 16k)
├── screen.mp4          # 仅 screen / full 模式
├── transcript.txt      # 带说话人标签的转录文本
└── transcript.srt      # 带说话人标签的字幕
```

### 各平台系统声音（`full` 模式）说明

| 操作系统 | 工作方式 | 额外安装 |
|---|---|---|
| **Windows 10/11** | 通过 `soundcard` 使用 WASAPI loopback | 无 — 全新机器即可使用 |
| **macOS 13+** | `soundcard` 支持时使用 ScreenCaptureKit | 否则安装 [BlackHole](https://existential.audio/blackhole/) 并设为输入设备 |
| **Linux** | PulseAudio / PipeWire monitor source | 大多数发行版开箱即用 |

安装实时录音可选依赖：

```bash
pip install video-transcriber[live-record]
```

## 致谢

本仓库 fork 自 [`checkerup/video-transcriber`](https://github.com/checkerup/video-transcriber)，
重度受以下项目启发：

- **[VoxTerm](https://github.com/dmarzzz/VoxTerm)** by [@dmarzzz](https://github.com/dmarzzz) — 这是证明本套说话人分离方案可以完全本地、跨平台、无需 HF token 运行的项目。新的 `diarizer_voxterm.py` 模块在 `sherpa-onnx` 之上重新实现了它的概念流水线（VAD → 分段 → 说话人 embedding → 余弦聚类）。**没有从 VoxTerm 复制原始代码**，但设计明显借鉴了它。MIT 许可证；完整署名见 [`NOTICE.md`](NOTICE.md)。

底层 ML 组件：

- **[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)** — Apache-2.0 — ONNX 推理运行时。
- **[3D-Speaker](https://github.com/modelscope/3D-Speaker)**（CAM++ / ERes2NetV2）— Apache-2.0 — 说话人 embedding。
- **[pyannote.audio](https://github.com/pyannote/pyannote-audio)** — MIT（代码）/ CC-BY 4.0（模型）— segmentation 3.0。
- **[Silero VAD](https://github.com/snakers4/silero-vad)** — MIT — 语音活动检测。
- **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** — MIT — 转录。

完整第三方署名： [`NOTICE.md`](NOTICE.md)。

## 许可证

MIT
