import logging
import urllib.parse
import time
from pathlib import Path
import requests

from .config import AppConfig

logger = logging.getLogger(__name__)

_model_cache: dict = {}


def google_translate(text: str, target_lang: str) -> str:
    if not text.strip():
        return text
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(text)}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        parts = resp.json()[0]
        return "".join([part[0] for part in parts if part[0]])
    except Exception as e:
        logger.warning("Google Translate failed: %s", e)
        return text


def _get_model(config: AppConfig):
    key = f"{config.transcription.model_size}_{config.transcription.device}_{config.transcription.compute_type}"
    if key in _model_cache:
        return _model_cache[key]

    from faster_whisper import WhisperModel

    logger.info(
        "Loading Whisper model: size=%s device=%s compute_type=%s",
        config.transcription.model_size,
        config.transcription.device,
        config.transcription.compute_type,
    )
    model = WhisperModel(
        config.transcription.model_size,
        device=config.transcription.device,
        compute_type=config.transcription.compute_type,
    )
    _model_cache[key] = model
    return model


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _format_srt(segments) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = format_timestamp(seg.start).replace(".", ",")
        end = format_timestamp(seg.end).replace(".", ",")
        lines.append(f"{i}\n{start} --> {end}\n{seg.text.strip()}\n")
    return "\n".join(lines)


def _format_vtt(segments) -> str:
    lines = ["WEBVTT\n"]
    for seg in segments:
        start = format_timestamp(seg.start)
        end = format_timestamp(seg.end)
        lines.append(f"{start} --> {end}\n{seg.text.strip()}\n")
    return "\n".join(lines)


def _format_txt(segments) -> str:
    parts = []
    for seg in segments:
        ts = format_timestamp(seg.start)
        text = seg.text.strip()
        parts.append(f"[{ts}] {text}")
    return "\n".join(parts)


def _format_paragraphs(segments) -> str:
    text_blocks = []
    current_block = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        current_block.append(text)
        if text[-1] in (".", "?", "!"):
            text_blocks.append(" ".join(current_block))
            current_block = []
    if current_block:
        text_blocks.append(" ".join(current_block))
    return "\n\n".join(text_blocks)


def find_speaker_for_time(time_sec: float, speaker_turns: list[dict]) -> str:
    for turn in speaker_turns:
        if turn["start"] <= time_sec <= turn["end"]:
            return turn["speaker"]
    if not speaker_turns:
        return "UNKNOWN"
    # Fallback to closest speaker turn
    closest_turn = min(speaker_turns, key=lambda t: min(abs(t["start"] - time_sec), abs(t["end"] - time_sec)))
    return closest_turn["speaker"]


def align_words_with_speakers(segments, speaker_turns: list[dict]) -> list[dict]:
    aligned_parts = []
    current_speaker = None
    current_text_words = []
    current_start = None
    current_end = None

    for seg in segments:
        if not getattr(seg, "words", None):
            # Segment level fallback
            seg_center = (seg.start + seg.end) / 2
            speaker = find_speaker_for_time(seg_center, speaker_turns)
            aligned_parts.append({
                "speaker": speaker,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip()
            })
            continue

        for word in seg.words:
            word_center = (word.start + word.end) / 2
            speaker = find_speaker_for_time(word_center, speaker_turns)

            if speaker != current_speaker:
                if current_speaker is not None:
                    aligned_parts.append({
                        "speaker": current_speaker,
                        "start": current_start,
                        "end": current_end,
                        "text": "".join(current_text_words).strip()
                    })
                current_speaker = speaker
                current_start = word.start
                current_text_words = [word.word]
                current_end = word.end
            else:
                current_text_words.append(word.word)
                current_end = word.end

    if current_speaker is not None:
        aligned_parts.append({
            "speaker": current_speaker,
            "start": current_start,
            "end": current_end,
            "text": "".join(current_text_words).strip()
        })

    return aligned_parts


def _format_diarized(aligned_parts: list[dict], clean_paragraphs: bool = False) -> str:
    lines = []
    for part in aligned_parts:
        if clean_paragraphs:
            lines.append(f"{part['speaker']}: {part['text']}")
        else:
            ts = format_timestamp(part["start"])
            lines.append(f"[{ts}] {part['speaker']}: {part['text']}")
    return "\n\n".join(lines) if clean_paragraphs else "\n".join(lines)


def transcribe(audio_path: str, config: AppConfig, speaker_turns: list[dict] | None = None) -> str:
    audio = Path(audio_path)
    if not audio.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    output_dir = Path(config.processing.output_folder)
    fmt = config.transcription.output_format

    transcript_path = output_dir / f"{audio.stem}.{fmt}"

    model = _get_model(config)

    logger.info("Transcribing: %s (lang=%s)", audio.name, config.transcription.language)

    word_timestamps = config.transcription.word_timestamps
    if speaker_turns:
        word_timestamps = True

    segments, info = model.transcribe(
        str(audio),
        language=config.transcription.language if config.transcription.language != "auto" else None,
        word_timestamps=word_timestamps,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    segment_list = []
    last_log_time = time.time()
    _local_start = time.time()
    _timer = getattr(config, "_progress_timer", None)
    try:
        from .progress_timer import format_hms as _fmt_hms
    except ImportError:
        def _fmt_hms(s):
            try:
                if s is None or s < 0:
                    return "--:--:--"
                s = int(s); h, r = divmod(s, 3600); m, ss = divmod(r, 60)
                return f"{h:02d}:{m:02d}:{ss:02d}"
            except Exception:
                return "--:--:--"
    for seg in segments:
        segment_list.append(seg)
        current_time = time.time()
        if current_time - last_log_time >= 15:
            progress_frac = (seg.end / info.duration) if info.duration else 0.0
            progress_pct = progress_frac * 100
            if _timer is not None:
                elapsed = _timer.stage_elapsed("transcribe") or 0.0
                eta = _timer.estimate_eta(progress_frac, stage_name="transcribe")
            else:
                elapsed = current_time - _local_start
                eta = (elapsed / progress_frac - elapsed) if 0 < progress_frac < 1 and elapsed > 0 else None
            logger.info(
                "Transcription progress: %.1f%% (%s / %s) — elapsed %s, ETA %s",
                progress_pct,
                format_timestamp(seg.end),
                format_timestamp(info.duration),
                _fmt_hms(elapsed),
                _fmt_hms(eta),
            )
            gui_cb = getattr(config, "_gui_progress_cb", None)
            if gui_cb is not None:
                try:
                    # Map 0..1 transcribe progress into the 0.35..0.90 band
                    # we allocated for the transcribe stage in the pipeline.
                    overall = 0.35 + 0.55 * max(0.0, min(1.0, progress_frac))
                    gui_cb("transcribe", overall, float(elapsed or 0.0), float(eta or 0.0))
                except Exception:
                    pass
            last_log_time = current_time
    logger.info(
        "Transcription complete: %d segments, language=%s (%.1f%% confidence)",
        len(segment_list),
        info.language,
        info.language_probability * 100,
    )

    aligned_parts = []
    if speaker_turns:
        aligned_parts = align_words_with_speakers(segment_list, speaker_turns)

    translate_to = getattr(config.transcription, "translate_to", "none")
    if translate_to and translate_to.lower() != "none":
        detected_lang = info.language
        if detected_lang != translate_to:
            logger.info("Translating transcript from %s to %s...", detected_lang, translate_to)
            if speaker_turns and aligned_parts:
                for part in aligned_parts:
                    part["text"] = google_translate(part["text"], translate_to)
            else:
                for seg in segment_list:
                    seg.text = google_translate(seg.text, translate_to)

    if speaker_turns and aligned_parts:
        text = _format_diarized(aligned_parts, clean_paragraphs=getattr(config.transcription, "clean_paragraphs", False))
    else:
        if getattr(config.transcription, "clean_paragraphs", False):
            text = _format_paragraphs(segment_list)
        else:
            formatters = {"txt": _format_txt, "srt": _format_srt, "vtt": _format_vtt}
            formatter = formatters.get(fmt, _format_txt)
            text = formatter(segment_list)

    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(text)

    logger.info("Transcript saved: %s", transcript_path)
    return str(transcript_path)

