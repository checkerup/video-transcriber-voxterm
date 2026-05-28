from typing import Any
import html
import logging
from pathlib import Path

import requests

from .config import AppConfig

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}"


def send_notification(
    config: AppConfig,
    video_path: Any,
    audio_path: Any,
    transcript_path: Any,
    error: Any = None,
    summary_path: Any = None,
    timing_summary: Any = None,
) -> bool:
    if not config.telegram.bot_token or not config.telegram.chat_id:
        logger.warning("Telegram not configured — skipping notification")
        return False

    url = _API_BASE.format(token=config.telegram.bot_token) + "/sendMessage"

    video_escaped = html.escape(str(video_path)) if video_path is not None else None
    audio_escaped = html.escape(str(audio_path)) if audio_path is not None else None
    transcript_escaped = html.escape(str(transcript_path)) if transcript_path is not None else None
    error_escaped = html.escape(str(error)) if error is not None else None
    summary_path_escaped = html.escape(str(summary_path)) if summary_path is not None else None

    if error_escaped is not None:
        file_label = "Видео" if video_path is not None else "Аудио"
        file_val = video_escaped if video_path is not None else (audio_escaped if audio_escaped else "Неизвестно")
        text = (
            f"❌ <b>Ошибка при обработке {file_label.lower()}</b>\n\n"
            f"📁 <b>Файл:</b> <code>{file_val}</code>\n"
            f"⚠️ <b>Ошибка:</b> <code>{error_escaped}</code>"
        )
        payload = {
            "chat_id": config.telegram.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error("Telegram notification failed: %s", e)
            return False

    # Success path
    lines = ["✅ <b>Расшифровка готова!</b>\n"]
    if video_escaped is not None:
        lines.append(f"📁 <b>Видео:</b> <code>{video_escaped}</code>")
        if audio_escaped is not None:
            lines.append(f"🎵 <b>Аудио:</b> <code>{audio_escaped}</code>")
    elif audio_escaped is not None:
        lines.append(f"🎵 <b>Аудио:</b> <code>{audio_escaped}</code>")
    else:
        lines.append("📁 <b>Видео:</b> <code>Неизвестно</code>")
    if transcript_escaped is not None:
        lines.append(f"📝 <b>Текст:</b> <code>{transcript_escaped}</code>")
    if summary_path_escaped is not None:
        lines.append(f"📊 <b>Сводка:</b> <code>{summary_path_escaped}</code>")
    if timing_summary:
        lines.append(f"⏱ <b>Время обработки:</b> <code>{html.escape(str(timing_summary))}</code>")

    base_text = "\n".join(lines)

    # Read summary content if present
    summary_text = ""
    if summary_path and Path(summary_path).exists():
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_text = f.read().strip()
        except Exception as e:
            logger.warning("Failed to read summary file: %s", e)

    payload = {
        "chat_id": config.telegram.chat_id,
        "parse_mode": "HTML",
    }

    try:
        if summary_text:
            summary_section = f"\n\n📖 <b>Краткое содержание:</b>\n{html.escape(summary_text)}"
            if len(base_text) + len(summary_section) <= 4096:
                payload["text"] = base_text + summary_section
                resp = requests.post(url, json=payload, timeout=15)
                resp.raise_for_status()
            else:
                # Send first message (metadata)
                payload["text"] = base_text
                resp = requests.post(url, json=payload, timeout=15)
                resp.raise_for_status()
                
                # Send second message (summary) - potentially chunked
                summary_header = "📖 <b>Краткое содержание:</b>\n"
                _send_message_in_chunks(url, payload, summary_header + html.escape(summary_text))
        else:
            payload["text"] = base_text
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()

        # Optional attachments (only on success — never on error path).
        if error is None:
            _attach_optional_files(
                config=config,
                transcript_path=transcript_path,
                summary_path=summary_path,
                audio_path=audio_path,
                video_path=video_path,
            )

        logger.info("Telegram notification sent successfully")
        return True
    except requests.RequestException as e:
        logger.error("Telegram notification failed: %s", e)
        return False


def _send_message_in_chunks(url: str, payload: dict, text_to_send: str) -> None:
    max_len = 4000
    lines = text_to_send.split("\n")
    current_chunk = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > max_len:
            if current_chunk:
                payload["text"] = "\n".join(current_chunk)
                resp = requests.post(url, json=payload, timeout=15)
                resp.raise_for_status()
                current_chunk = [line]
                current_len = len(line)
            else:
                # Line itself is longer than max_len, split it
                payload["text"] = line
                resp = requests.post(url, json=payload, timeout=15)
                resp.raise_for_status()
                current_chunk = []
                current_len = 0
        else:
            current_chunk.append(line)
            current_len += len(line) + 1
    if current_chunk:
        payload["text"] = "\n".join(current_chunk)
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()


# ---------- attachments ----------

_DOC_URL = "https://api.telegram.org/bot{token}/sendDocument"


def _attach_optional_files(
    config: AppConfig,
    *,
    transcript_path,
    summary_path,
    audio_path,
    video_path,
) -> None:
    """Send any optional documents (transcript / summary / audio / video) if enabled in config."""
    token = config.telegram.bot_token
    chat_id = config.telegram.chat_id
    max_bytes = int(config.telegram.max_attachment_mb) * 1024 * 1024
    mode = (config.telegram.send_transcript or "file").lower().strip()

    if transcript_path is not None and mode == "file":
        _send_document(token, chat_id, Path(str(transcript_path)),
                       caption="📝 Расшифровка", max_bytes=max_bytes)
    elif transcript_path is not None and mode == "text":
        _send_transcript_as_text(token, chat_id, Path(str(transcript_path)))

    if config.telegram.send_summary_file and summary_path is not None:
        _send_document(token, chat_id, Path(str(summary_path)),
                       caption="📖 Саммари", max_bytes=max_bytes)

    if config.telegram.attach_audio and audio_path is not None:
        _send_document(token, chat_id, Path(str(audio_path)),
                       caption="🎧 Аудио", max_bytes=max_bytes)

    if config.telegram.attach_video and video_path is not None:
        _send_document(token, chat_id, Path(str(video_path)),
                       caption="🎬 Видео", max_bytes=max_bytes)


def _send_document(token: str, chat_id: int, file_path: Path, caption: str, max_bytes: int) -> None:
    """Upload a single file via Telegram sendDocument; soft-fail with a log."""
    try:
        if not file_path.exists():
            logger.warning("Telegram attach: file not found: %s", file_path)
            return
        size = file_path.stat().st_size
        if size > max_bytes:
            logger.warning(
                "Telegram attach: skipping %s (%.1f MB > limit %.0f MB)",
                file_path, size / 1024 / 1024, max_bytes / 1024 / 1024,
            )
            return
        with file_path.open("rb") as fh:
            files = {"document": (file_path.name, fh)}
            data = {
                "chat_id": chat_id,
                "caption": f"{html.escape(caption)} <code>{html.escape(file_path.name)}</code>",
                "parse_mode": "HTML",
            }
            resp = requests.post(
                _DOC_URL.format(token=token),
                files=files, data=data, timeout=60,
            )
            resp.raise_for_status()
        logger.info("Telegram attach: sent %s", file_path.name)
    except Exception as e:  # noqa: BLE001 - never let attachments break notifications
        logger.error("Telegram attach: %s failed: %s", file_path, e)


def _send_transcript_as_text(token: str, chat_id: int, file_path: Path) -> None:
    """Inline the transcript text into one or more sendMessage calls (4000 ch chunks)."""
    try:
        if not file_path.exists():
            logger.warning("Telegram text: transcript not found: %s", file_path)
            return
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return
        url = _API_BASE.format(token=token) + "/sendMessage"
        payload = {"chat_id": chat_id, "parse_mode": "HTML"}
        header = "📝 <b>Расшифровка:</b>\n"
        _send_message_in_chunks(url, payload, header + html.escape(text))
    except Exception as e:  # noqa: BLE001
        logger.error("Telegram text: send failed: %s", e)