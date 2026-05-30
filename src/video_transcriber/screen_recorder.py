import logging
import platform
import subprocess
import threading
import time
import sys
from datetime import datetime
from pathlib import Path

from .config import AppConfig

logger = logging.getLogger(__name__)

_current_recording: subprocess.Popen | None = None
_current_output: str | None = None
_recording_lock = threading.Lock()


def _ffmpeg_record_cmd(output_path: str, config: AppConfig) -> list[str]:
    os_name = platform.system()
    recorder_cfg = getattr(config, "recorder", None)

    fps = recorder_cfg.fps if recorder_cfg else 30
    video_size = recorder_cfg.video_size if recorder_cfg else None

    if os_name == "Windows":
        size = video_size or "desktop"
        cmd = [
            "ffmpeg",
            "-f", "gdigrab",
            "-framerate", str(fps),
            "-i", "desktop",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
            "-y",
            output_path,
        ]
    elif os_name == "Darwin":
        cmd = [
            "ffmpeg",
            "-f", "avfoundation",
            "-framerate", str(fps),
            "-i", "1",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
            "-y",
            output_path,
        ]
    else:
        display = ":0.0"
        size = video_size or "1920x1080"
        cmd = [
            "ffmpeg",
            "-f", "x11grab",
            "-framerate", str(fps),
            "-video_size", size,
            "-i", display,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
            "-y",
            output_path,
        ]

    return cmd


def start_recording(config: AppConfig) -> str | None:
    global _current_recording, _current_output

    with _recording_lock:
        if _current_recording is not None and _current_recording.poll() is None:
            logger.warning("Recording already in progress: %s", _current_output)
            return _current_output

        output_dir = Path(config.processing.output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = str(output_dir / f"screen_{timestamp}.mp4")

        cmd = _ffmpeg_record_cmd(output_path, config)

        logger.info("Starting screen recording: %s", output_path)
        logger.debug("FFmpeg cmd: %s", " ".join(cmd))

        try:
            _popen_kw = dict(
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            if sys.platform == "win32":
                _popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            _current_recording = subprocess.Popen(cmd, **_popen_kw)
            _current_output = output_path

            time.sleep(1)
            if _current_recording.poll() is not None:
                stderr = _current_recording.stderr.read().decode(errors="replace")[:500]
                logger.error("FFmpeg exited immediately: %s", stderr)
                _current_recording = None
                _current_output = None
                return None

            logger.info("Recording started: %s (PID %d)", output_path, _current_recording.pid)
            return output_path

        except FileNotFoundError:
            logger.error("FFmpeg not found — cannot record screen")
            return None
        except Exception as e:
            logger.error("Failed to start recording: %s", e)
            _current_recording = None
            _current_output = None
            return None


def stop_recording() -> str | None:
    global _current_recording, _current_output

    with _recording_lock:
        if _current_recording is None:
            logger.warning("No recording in progress")
            return None

        logger.info("Stopping screen recording...")
        proc = _current_recording

        # 1) Windows: CTRL_BREAK_EVENT first (cleanest finalize for fragmented mp4).
        if sys.platform == "win32":
            try:
                import signal as _sig
                proc.send_signal(_sig.CTRL_BREAK_EVENT)
                try:
                    proc.wait(timeout=8)
                    logger.info("FFmpeg stopped via CTRL_BREAK_EVENT")
                except subprocess.TimeoutExpired:
                    pass
            except Exception as e:
                logger.debug("CTRL_BREAK_EVENT failed: %s", e)

        # 2) If still alive: send 'q\n' on stdin and close it.
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(b"q\n")
                    proc.stdin.flush()
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=8)
                logger.info("FFmpeg stopped via stdin 'q'")
            except subprocess.TimeoutExpired:
                pass

        # 3) Last resort: kill (output is still recoverable thanks to
        #    fragmented-mp4 movflags above).
        if proc.poll() is None:
            logger.warning("FFmpeg didn't stop gracefully, killing...")
            proc.kill()
            proc.wait(timeout=5)

        output = _current_output
        logger.info("Recording stopped: %s", output)

        _current_recording = None
        _current_output = None
        return output


def is_recording() -> bool:
    with _recording_lock:
        return _current_recording is not None and _current_recording.poll() is None


def get_current_output() -> str | None:
    with _recording_lock:
        return _current_output
