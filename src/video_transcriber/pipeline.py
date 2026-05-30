import logging
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any

from .config import AppConfig
from .extractor import copy_video_to_output, extract_audio, copy_audio_to_output
from .notifier import send_notification
from .progress_timer import ProgressTimer, format_hms
from .transcriber import transcribe
from .summarizer import generate_summary

logger = logging.getLogger(__name__)


def _probe_duration_seconds(media_path: str | Path) -> float | None:
    """Best-effort media-duration probe using ffprobe; returns None on failure."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(media_path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        val = out.stdout.strip()
        return float(val) if val else None
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def process_file(file_path: str, config: AppConfig) -> dict:
    logger.info("=" * 60)
    logger.info("Processing: %s", file_path)
    logger.info("=" * 60)

    timer = ProgressTimer()
    config.__dict__["_progress_timer"] = timer  # so transcriber can access it

    cb = getattr(config, "_gui_progress_cb", None)
    def _notify_stage(name: str, progress: float) -> None:
        if cb is None:
            return
        try:
            elapsed = timer.total_elapsed
            cb(name, progress, float(elapsed), 0.0)
        except Exception:
            pass

    result: dict = {
        "video": None,
        "audio": None,
        "transcript": None,
        "summary": None,
        "error": None,
        "timing_path": None,
        "timing_summary": None,
    }

    was_video = False
    audio_path = None
    source_duration: float | None = None
    try:
        path = Path(file_path)
        suffix = path.suffix.lower()

        audio_extensions = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
        video_extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}

        if suffix in audio_extensions:
            _notify_stage("copy_audio", 0.02)
            with timer.stage("copy_audio"):
                output_audio = copy_audio_to_output(file_path, config)
            result["audio"] = output_audio
            audio_path = output_audio

        elif suffix in video_extensions:
            was_video = True
            _notify_stage("copy_video", 0.02)
            with timer.stage("copy_video"):
                output_video = copy_video_to_output(file_path, config)
            result["video"] = output_video

            _notify_stage("extract_audio", 0.05)
            with timer.stage("extract_audio"):
                extracted_audio = extract_audio(output_video, config)
            result["audio"] = extracted_audio
            audio_path = extracted_audio

        else:
            raise ValueError(f"Unsupported file format: {suffix}")

        # Probe duration for speedup ratio + ETA — best effort.
        source_duration = _probe_duration_seconds(audio_path or file_path)
        if source_duration:
            logger.info("Source duration: %s", format_hms(source_duration))

        speaker_turns = None
        if audio_path and getattr(config, "diarization", None) and config.diarization.enabled:
            _notify_stage("diarize", 0.10)
            with timer.stage("diarize"):
                from .diarizer import diarize_audio
                speaker_turns = diarize_audio(audio_path, config)

        if audio_path:
            _notify_stage("transcribe", 0.35)
            with timer.stage("transcribe"):
                transcript_path = transcribe(audio_path, config, speaker_turns=speaker_turns)
            result["transcript"] = transcript_path

        if config.summarization.enabled and result["transcript"]:
            _notify_stage("summarize", 0.95)
            with timer.stage("summarize"):
                with open(result["transcript"], "r", encoding="utf-8") as f:
                    transcript_text = f.read()
                summary = generate_summary(transcript_text, config)
                if summary:
                    t_path = Path(result["transcript"])
                    summary_path = t_path.parent / f"{t_path.stem}_summary.md"
                    with open(summary_path, "w", encoding="utf-8") as f:
                        f.write(summary)
                    result["summary"] = str(summary_path)
                    logger.info("Summary saved to: %s", summary_path)

        if not config.processing.keep_audio and was_video and audio_path:
            try:
                p_audio = Path(audio_path)
                if p_audio.exists():
                    p_audio.unlink()
                    logger.info("Deleted temporary audio file: %s", audio_path)
            except Exception as e:
                logger.warning("Failed to delete temporary audio file: %s", e)

        logger.info("Pipeline complete for: %s", file_path)
        _notify_stage("complete", 1.0)

    except Exception as e:
        logger.exception("Pipeline failed for: %s", file_path)
        result["error"] = str(e)

    # ----- timing summary (always, success or fail) -----
    summary_line = timer.format_summary(source_duration_s=source_duration)
    result["timing_summary"] = summary_line
    logger.info(summary_line)

    timing_target: Path | None = None
    if result["transcript"]:
        tp = Path(result["transcript"])
        timing_target = tp.parent / f"{tp.stem}.timing.json"
    elif result["audio"]:
        ap = Path(result["audio"])
        timing_target = ap.parent / f"{ap.stem}.timing.json"
    if timing_target is not None:
        try:
            timer.write_json(timing_target, source_duration_s=source_duration)
            result["timing_path"] = str(timing_target)
            logger.info("Timing report: %s", timing_target)
        except OSError as e:
            logger.warning("Failed to write timing report: %s", e)

    send_notification(
        config=config,
        video_path=result["video"],
        audio_path=result["audio"],
        transcript_path=result["transcript"],
        error=result["error"],
        summary_path=result["summary"],
        timing_summary=result["timing_summary"],
    )

    return result


def process_video(video_path: str, config: AppConfig) -> dict:
    """Compatibility alias for process_file."""
    logger.warning("process_video is deprecated, use process_file instead")
    return process_file(video_path, config)
