import os
import platform
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


def _default_videos_dir() -> Path:
    home = Path.home()
    if platform.system() == "Windows":
        videos = home / "Videos"
    else:
        videos = home / "Videos" if (home / "Videos").exists() else home / "videos"
    if not videos.exists():
        videos = home / "Videos"
    return videos


_DEFAULT_WATCH = str(_default_videos_dir() / "Incoming")
_DEFAULT_OUTPUT = str(_default_videos_dir() / "Processed")


@dataclass
class WatchConfig:
    folder: str = _DEFAULT_WATCH
    extensions: list[str] = field(default_factory=lambda: [".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"])
    delay_seconds: int = 10


@dataclass
class ProcessingConfig:
    output_folder: str = _DEFAULT_OUTPUT
    audio_format: str = "mp3"
    audio_bitrate: str = "192k"
    keep_audio: bool = True
    silence_removal: bool = False


@dataclass
class TranscriptionConfig:
    model_size: str = "base"
    device: str = "auto"
    compute_type: str = "int8"
    language: str = "ru"
    output_format: str = "txt"
    word_timestamps: bool = True
    translate_to: str = "none"
    clean_paragraphs: bool = False


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    # How to deliver the transcript itself.
    #   "file" — send the transcript file as a document (default).
    #   "text" — inline the transcript text in messages (chunked at 4000ch).
    #   "none" — just the metadata message, no transcript content.
    send_transcript: str = "file"
    # If True and a summary file exists, also attach it as a document.
    send_summary_file: bool = False
    # If True, also attach the produced audio/video as documents (heavy).
    attach_audio: bool = False
    attach_video: bool = False
    # Telegram bot API hard limit is 50
    max_attachment_mb: int = 49


@dataclass
class RecorderConfig:
    fps: int = 30
    video_size: str | None = None


@dataclass
class ProcessWatcherConfig:
    program_names: list[str] = field(default_factory=list)
    poll_interval: int = 5


@dataclass
class SummarizationConfig:
    enabled: bool = False
    # Provider: "gemini" (default), "openai", "anthropic", "openrouter",
    # or "custom" (any OpenAI-compatible endpoint via api_base).
    provider: str = "gemini"
    api_key: str = ""
    api_base: str = ""        # Custom base URL (only required for provider="custom").
    model: str = "gemini-1.5-flash"
    prompt: str = ""          # If empty, a sensible default is used (see summarizer.py).
    system_prompt: str = ""  # Optional system instruction (OpenAI / Anthropic style).
    temperature: float = 0.3
    max_output_tokens: int = 8192
    language: str = "auto"   # "auto" = follow transcript language; or "ru", "en", "zh", ...


@dataclass
class DiarizationConfig:
    enabled: bool = False
    # Backend: "voxterm" (offline, default) or "pyannote" (HF, legacy).
    backend: str = "voxterm"
    # Speaker-embedding model id for the voxterm backend.
    # Supported: "cam++" (default, fast), "eres2net" (slightly better).
    model: str = "cam++"
    # Cosine-distance clustering threshold (voxterm backend). Higher = more
    # permissive grouping = fewer speakers detected. 0.5 is too aggressive on
    # noisy long-form recordings (it splits one person across many clusters);
    # 0.7 is a better default for typical meeting / call audio.
    cluster_threshold: float = 0.7
    # Number of CPU threads used by the ONNX runtime for diarization.
    num_threads: int = 1
    # Minimum on/off speech durations passed to the segmentation model.
    # Slightly larger
    min_duration_on: float = 0.5
    # Min duration (s) of a silence gap (voxterm backend).
    min_duration_off: float = 0.7
    # HF API token for the legacy pyannote backend (ignored by voxterm).
    auth_token: str = ""
    min_speakers: int | None = None
    max_speakers: int | None = None
    num_speakers: int | None = None


@dataclass
class AppConfig:
    watch: WatchConfig = field(default_factory=WatchConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    recorder: RecorderConfig = field(default_factory=RecorderConfig)
    process_watcher: ProcessWatcherConfig = field(default_factory=ProcessWatcherConfig)
    summarization: SummarizationConfig = field(default_factory=SummarizationConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _as_bool(val, default: bool) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


def _as_int(val, default: int) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _as_list(val, default: list) -> list:
    if val is None:
        return default
    if isinstance(val, str):
        return [item.strip() for item in val.split(",") if item.strip()]
    if isinstance(val, list):
        return [str(item).strip() for item in val]
    return default


def _llm_api_key_from_env(provider: str) -> str | None:
    """Pick an API key from environment variables based on the configured LLM provider."""
    p = (provider or "").lower().strip()
    env_map = {
        "gemini":     ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "openai":     ["OPENAI_API_KEY"],
        "anthropic":  ["ANTHROPIC_API_KEY"],
        "openrouter": ["OPENROUTER_API_KEY"],
        "custom":     ["LLM_API_KEY"],
    }
    for var in env_map.get(p, []):
        val = os.getenv(var)
        if val:
            return val
    return None


def _get_dict_section(raw: dict, name: str) -> dict:
    section = raw.get(name)
    return section if isinstance(section, dict) else {}


def load_config(config_path: str | Path | None = None, load_env_file: bool = True) -> AppConfig:
    project_root = Path(__file__).resolve().parent.parent.parent
    if load_env_file:
        load_dotenv(project_root / ".env")

    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    else:
        config_path = Path(config_path)

    raw = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}

    watch_raw = _get_dict_section(raw, "watch")
    proc_raw = _get_dict_section(raw, "processing")
    trans_raw = _get_dict_section(raw, "transcription")
    tg_raw = _get_dict_section(raw, "telegram")
    rec_raw = _get_dict_section(raw, "recorder")
    pw_raw = _get_dict_section(raw, "process_watcher")
    sum_raw = _get_dict_section(raw, "summarization")
    diar_raw = _get_dict_section(raw, "diarization")

    bot_token = tg_raw.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
    chat_id = tg_raw.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID") or ""

    device = _resolve_device(trans_raw.get("device") or "auto")

    default_watch = WatchConfig()
    default_proc = ProcessingConfig()
    default_trans = TranscriptionConfig()
    default_rec = RecorderConfig()
    default_pw = ProcessWatcherConfig()
    default_sum = SummarizationConfig()
    default_diar = DiarizationConfig()

    watch_folder = os.path.expanduser(str(watch_raw.get("folder") or default_watch.folder))
    output_folder = os.path.expanduser(str(proc_raw.get("output_folder") or default_proc.output_folder))

    delay_seconds = _as_int(watch_raw.get("delay_seconds"), default_watch.delay_seconds)
    keep_audio = _as_bool(proc_raw.get("keep_audio"), default_proc.keep_audio)
    silence_removal = _as_bool(proc_raw.get("silence_removal"), default_proc.silence_removal)
    word_timestamps = _as_bool(trans_raw.get("word_timestamps"), default_trans.word_timestamps)
    translate_to = str(trans_raw.get("translate_to") or default_trans.translate_to)
    clean_paragraphs = _as_bool(trans_raw.get("clean_paragraphs"), default_trans.clean_paragraphs)
    fps = _as_int(rec_raw.get("fps"), default_rec.fps)
    poll_interval = _as_int(pw_raw.get("poll_interval"), default_pw.poll_interval)

    cfg = AppConfig(
        watch=WatchConfig(
            folder=watch_folder,
            extensions=_as_list(watch_raw.get("extensions"), default_watch.extensions),
            delay_seconds=delay_seconds,
        ),
        processing=ProcessingConfig(
            output_folder=output_folder,
            audio_format=proc_raw.get("audio_format") or default_proc.audio_format,
            audio_bitrate=proc_raw.get("audio_bitrate") or default_proc.audio_bitrate,
            keep_audio=keep_audio,
            silence_removal=silence_removal,
        ),
        transcription=TranscriptionConfig(
            model_size=trans_raw.get("model_size") or default_trans.model_size,
            device=device,
            compute_type=trans_raw.get("compute_type") or default_trans.compute_type,
            language=trans_raw.get("language") or default_trans.language,
            output_format=trans_raw.get("output_format") or default_trans.output_format,
            word_timestamps=word_timestamps,
            translate_to=translate_to,
            clean_paragraphs=clean_paragraphs,
        ),
        telegram=TelegramConfig(
            bot_token=bot_token,
            chat_id=chat_id,
            send_transcript=str(
                tg_raw.get("send_transcript")
                if tg_raw.get("send_transcript") is not None
                else TelegramConfig.send_transcript
            ).lower().strip() or "file",
            send_summary_file=_as_bool(
                tg_raw.get("send_summary_file"),
                TelegramConfig.send_summary_file
            ),
            attach_audio=_as_bool(
                tg_raw.get("attach_audio"),
                TelegramConfig.attach_audio
            ),
            attach_video=_as_bool(
                tg_raw.get("attach_video"),
                TelegramConfig.attach_video
            ),
            max_attachment_mb=_as_int(
                tg_raw.get("max_attachment_mb"),
                TelegramConfig.max_attachment_mb
            ),
        ),
        recorder=RecorderConfig(
            fps=fps,
            video_size=rec_raw.get("video_size") if rec_raw.get("video_size") is not None else default_rec.video_size,
        ),
        process_watcher=ProcessWatcherConfig(
            program_names=_as_list(pw_raw.get("program_names"), default_pw.program_names),
            poll_interval=poll_interval,
        ),
        summarization=SummarizationConfig(
            enabled=_as_bool(sum_raw.get("enabled"), default_sum.enabled),
            provider=str(sum_raw.get("provider") or default_sum.provider),
            api_key=str(sum_raw.get("api_key") or _llm_api_key_from_env(str(sum_raw.get("provider") or default_sum.provider)) or default_sum.api_key or ""),
            api_base=str(sum_raw.get("api_base") or default_sum.api_base),
            model=str(sum_raw.get("model") or default_sum.model),
            prompt=str(sum_raw.get("prompt") or default_sum.prompt),
            system_prompt=str(sum_raw.get("system_prompt") or default_sum.system_prompt),
            temperature=float(sum_raw.get("temperature") or default_sum.temperature),
            max_output_tokens=int(sum_raw.get("max_output_tokens") or default_sum.max_output_tokens),
            language=str(sum_raw.get("language") or default_sum.language),
        ),
        diarization=DiarizationConfig(
            enabled=_as_bool(diar_raw.get("enabled"), default_diar.enabled),
            backend=str(diar_raw.get("backend") or default_diar.backend),
            model=str(diar_raw.get("model") or default_diar.model),
            cluster_threshold=float(
                diar_raw.get("cluster_threshold")
                if diar_raw.get("cluster_threshold") is not None
                else default_diar.cluster_threshold
            ),
            num_threads=_as_int(diar_raw.get("num_threads"), default_diar.num_threads),
            min_duration_on=float(
                diar_raw.get("min_duration_on")
                if diar_raw.get("min_duration_on") is not None
                else default_diar.min_duration_on
            ),
            min_duration_off=float(
                diar_raw.get("min_duration_off")
                if diar_raw.get("min_duration_off") is not None
                else default_diar.min_duration_off
            ),
            auth_token=str(diar_raw.get("auth_token") or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or default_diar.auth_token or ""),
            min_speakers=None if diar_raw.get("min_speakers") is None else _as_int(diar_raw.get("min_speakers"), 0) or None,
            max_speakers=None if diar_raw.get("max_speakers") is None else _as_int(diar_raw.get("max_speakers"), 0) or None,
            num_speakers=None if diar_raw.get("num_speakers") is None else _as_int(diar_raw.get("num_speakers"), 0) or None,
        ),
    )

    return cfg

