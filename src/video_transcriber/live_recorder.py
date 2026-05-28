"""
Live recording mode.

Three sub-modes, all cross-platform:

  - voice        : microphone only        -> .wav (mono 16k)
  - screen       : screen + microphone    -> .mp4 (with embedded audio)
  - full         : screen + microphone + system audio loopback -> .mp4

When recording finishes (Ctrl+C), the produced media file is automatically
fed back through ``pipeline.process_file`` for transcription + (optional)
diarization.

The "system audio loopback" path is what makes this useful for transcribing
calls: we pull what's currently playing on the speakers (Zoom voices,
YouTube, etc.) without needing virtual cables (BlackHole / VB-Audio).

Platform support for the system-audio loopback:
    Windows  : WASAPI loopback via the ``soundcard`` package — works on a
               vanilla machine, no extra drivers.
    macOS    : ScreenCaptureKit-based loopback (macOS 13+) when the
               ``soundcard`` package supports it on the host; otherwise the
               user is told that ``BlackHole`` / similar is needed.
    Linux    : PulseAudio monitor source via ``soundcard``.

The microphone path uses ``sounddevice`` (cross-platform PortAudio).

If a user only has the bare ``requirements.txt`` deps installed, importing
this module will not crash — the heavy audio deps are imported lazily inside
the recorder class so ``--help`` and unrelated CLI invocations stay fast.

Inspired by VoxTerm's live-capture flow (https://github.com/dmarzzz/VoxTerm),
adapted here for offline, file-producing batch mode on Windows/macOS/Linux.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


SAMPLE_RATE = 16_000  # mono 16k matches what whisper + sherpa-onnx want
CHANNELS = 1


class LiveRecorder:
    """Threaded live recorder.

    Usage:
        rec = LiveRecorder(config, mode="voice")
        rec.start()
        # ... user presses Ctrl+C ...
        media_path = rec.stop()
    """

    def __init__(self, config, mode: str = "voice", session_dir: Optional[Path] = None):
        if mode not in ("voice", "screen", "full"):
            raise ValueError(
                f"Unknown live-recording mode: {mode!r}. "
                "Expected 'voice' | 'screen' | 'full'."
            )
        self.config = config
        self.mode = mode

        # Resolve output directory: <output_folder>/live_<timestamp>/
        out_root = Path(config.processing.output_folder)
        out_root.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_dir = session_dir or (out_root / f"live_{ts}")
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._mic_path: Optional[Path] = None
        self._sys_path: Optional[Path] = None
        self._screen_path: Optional[Path] = None
        self._final_path: Optional[Path] = None
        self._ffmpeg_screen: Optional[subprocess.Popen] = None
        self._mic_handle = None  # internal handle for graceful close
        self._sys_handle = None

    # ----------------------------- Public API -----------------------------

    def start(self) -> None:
        """Start all sub-recorders for the selected mode (non-blocking)."""
        logger.info("Live recorder starting in mode=%s session=%s", self.mode, self.session_dir)

        # Microphone is always captured (in all modes)
        self._mic_path = self.session_dir / "mic.wav"
        t_mic = threading.Thread(
            target=self._record_microphone, args=(self._mic_path,), daemon=True
        )
        t_mic.start()
        self._threads.append(t_mic)

        if self.mode == "full":
            self._sys_path = self.session_dir / "system.wav"
            t_sys = threading.Thread(
                target=self._record_system_audio, args=(self._sys_path,), daemon=True
            )
            t_sys.start()
            self._threads.append(t_sys)

        if self.mode in ("screen", "full"):
            self._screen_path = self.session_dir / "screen.mp4"
            # ffmpeg manages itself; not a Python thread
            self._start_screen_capture(self._screen_path)

        # Brief settle time so all recorders are actually running before we
        # report success to the caller.
        time.sleep(0.5)
        logger.info("Live recorder running. Press Ctrl+C to stop.")

    def stop(self) -> Optional[Path]:
        """Stop all sub-recorders and produce a single final media file.

        Returns the path to the final media file:
          - voice  : <session>/audio.wav
          - screen : <session>/recording.mp4
          - full   : <session>/recording.mp4
        """
        if self._stop_event.is_set():
            return self._final_path

        logger.info("Stopping live recorder...")
        self._stop_event.set()

        # Stop screen ffmpeg first; it's external
        if self._ffmpeg_screen is not None:
            self._stop_ffmpeg(self._ffmpeg_screen)
            self._ffmpeg_screen = None

        # Wait for audio threads — they tail off on the stop event
        for t in self._threads:
            t.join(timeout=15)

        # Combine into the final media file
        self._final_path = self._finalize()
        logger.info("Live recording finalized: %s", self._final_path)
        return self._final_path

    # ----------------------------- Internals ------------------------------

    def _record_microphone(self, out_path: Path) -> None:
        try:
            import sounddevice as sd
            import soundfile as sf
        except ImportError:
            logger.error(
                "Microphone capture requires 'sounddevice' and 'soundfile'. "
                "Install with: pip install -e .[live-record]"
            )
            return

        logger.info("Microphone capture starting -> %s", out_path)
        try:
            with sf.SoundFile(
                str(out_path),
                mode="w",
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                subtype="PCM_16",
            ) as f, sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=int(SAMPLE_RATE * 0.1),
            ) as stream:
                self._mic_handle = stream
                while not self._stop_event.is_set():
                    data, _ = stream.read(int(SAMPLE_RATE * 0.1))
                    f.write(data)
        except Exception as e:
            logger.exception("Microphone capture failed: %s", e)
        finally:
            logger.info("Microphone capture stopped")

    def _record_system_audio(self, out_path: Path) -> None:
        """Capture whatever is currently playing through the system speakers.

        Implementation: ``soundcard`` library exposes WASAPI loopback on
        Windows, ScreenCaptureKit on recent macOS, and PulseAudio monitors
        on Linux — all through a uniform Python API. No virtual audio
        cables required on Windows.
        """
        try:
            import soundcard as sc
            import soundfile as sf
            import numpy as np
        except ImportError:
            logger.error(
                "System-audio loopback requires the 'soundcard' package. "
                "Install with: pip install -e .[live-record]"
            )
            return

        try:
            default_speaker = sc.default_speaker()
            loopback = sc.get_microphone(id=str(default_speaker.name), include_loopback=True)
        except Exception as e:
            logger.error(
                "Could not open a loopback device for system audio: %s. "
                "On macOS you may need an additional virtual loopback driver "
                "(e.g. BlackHole). Skipping system-audio track.",
                e,
            )
            return

        logger.info("System-audio loopback starting -> %s", out_path)
        try:
            with loopback.recorder(
                samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=int(SAMPLE_RATE * 0.1)
            ) as rec, sf.SoundFile(
                str(out_path),
                mode="w",
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                subtype="PCM_16",
            ) as f:
                self._sys_handle = rec
                while not self._stop_event.is_set():
                    data = rec.record(numframes=int(SAMPLE_RATE * 0.1))
                    if data is None:
                        continue
                    if data.ndim == 2:
                        data = data.mean(axis=1, keepdims=False)
                    pcm = np.clip(data * 32767.0, -32768, 32767).astype("int16")
                    f.write(pcm)
        except Exception as e:
            logger.exception("System-audio loopback failed: %s", e)
        finally:
            logger.info("System-audio loopback stopped")

    def _start_screen_capture(self, out_path: Path) -> None:
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found in PATH — required for screen capture")

        recorder_cfg = getattr(self.config, "recorder", None)
        fps = recorder_cfg.fps if recorder_cfg else 30

        os_name = platform.system()
        if os_name == "Windows":
            cmd = [
                "ffmpeg",
                "-f", "gdigrab", "-framerate", str(fps), "-i", "desktop",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-an",
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                "-y", str(out_path),
            ]
        elif os_name == "Darwin":
            cmd = [
                "ffmpeg",
                "-f", "avfoundation", "-framerate", str(fps), "-i", "1",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-an",
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                "-y", str(out_path),
            ]
        else:
            # Linux: x11grab. Headless? Then the user shouldn't be in screen mode.
            video_size = (recorder_cfg.video_size if recorder_cfg else None) or "1920x1080"
            cmd = [
                "ffmpeg",
                "-f", "x11grab", "-framerate", str(fps), "-video_size", video_size,
                "-i", ":0.0",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-an",
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                "-y", str(out_path),
            ]

        logger.info("Screen capture starting -> %s (fps=%s)", out_path, fps)
        logger.debug("ffmpeg screen cmd: %s", " ".join(cmd))
        _popen_kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if sys.platform == "win32":
            _popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        self._ffmpeg_screen = subprocess.Popen(cmd, **_popen_kwargs)
        # Give ffmpeg a moment to fail fast (e.g. missing display)
        time.sleep(0.5)
        if self._ffmpeg_screen.poll() is not None:
            err = (self._ffmpeg_screen.stderr.read() or b"").decode(errors="replace")[:500]
            self._ffmpeg_screen = None
            raise RuntimeError(f"ffmpeg screen capture failed to start: {err}")

    def _stop_ffmpeg(self, proc: subprocess.Popen) -> None:
        """Gracefully stop ffmpeg so the output mp4 is finalized.

        - Windows: CTRL_BREAK_EVENT (works because we launched with
          CREATE_NEW_PROCESS_GROUP). Wait up to 15s.
        - Other platforms or if Ctrl+Break didn't work: stdin 'q\\n'
          + flush + close. Wait up to 15s.
        - Last resort: proc.kill() (output file will be corrupt).
        """
        import signal as _sig
        if sys.platform == "win32":
            try:
                proc.send_signal(_sig.CTRL_BREAK_EVENT)
                proc.wait(timeout=15)
                return
            except (subprocess.TimeoutExpired, Exception) as e:
                logger.warning("ffmpeg Ctrl+Break failed (%s), trying stdin 'q'...", e)
        try:
            if proc.stdin:
                proc.stdin.write(b"q\n")
                proc.stdin.flush()
                proc.stdin.close()
            proc.wait(timeout=15)
            return
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.warning("ffmpeg didn't stop on stdin 'q' (%s), killing — output may be corrupt", e)
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    def _finalize(self) -> Path:
        """Combine the recorded tracks into a single output file.

        - voice : just the mic WAV (renamed audio.wav)
        - screen: mux screen.mp4 + mic.wav -> recording.mp4
        - full  : mix mic.wav + system.wav -> mixed.wav, then mux with
                  screen.mp4 -> recording.mp4
        """
        if self.mode == "voice":
            final = self.session_dir / "audio.wav"
            if self._mic_path and self._mic_path.exists():
                if self._mic_path.resolve() != final.resolve():
                    shutil.move(str(self._mic_path), str(final))
            return final

        # We're doing video output: mix audio first if needed
        if self.mode == "full" and self._sys_path and self._sys_path.exists():
            mixed = self.session_dir / "mixed.wav"
            self._ffmpeg_mix_audio(self._mic_path, self._sys_path, mixed)
            audio_track = mixed
        else:
            audio_track = self._mic_path

        final = self.session_dir / "recording.mp4"
        self._ffmpeg_mux(self._screen_path, audio_track, final)
        return final

    @staticmethod
    def _ffmpeg_mix_audio(mic: Path, sys_audio: Path, out: Path) -> None:
        if not (mic and mic.exists()):
            shutil.copy2(sys_audio, out)
            return
        if not (sys_audio and sys_audio.exists()):
            shutil.copy2(mic, out)
            return
        cmd = [
            "ffmpeg", "-loglevel", "error", "-y",
            "-i", str(mic), "-i", str(sys_audio),
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0",
            "-ac", "1", "-ar", str(SAMPLE_RATE), str(out),
        ]
        subprocess.run(cmd, check=True)

    @staticmethod
    def _ffmpeg_mux(video: Path, audio: Path, out: Path) -> None:
        cmd = [
            "ffmpeg", "-loglevel", "error", "-y",
            "-i", str(video),
        ]
        if audio and audio.exists():
            cmd += ["-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-shortest"]
        else:
            cmd += ["-c:v", "copy"]
        cmd += [str(out)]
        subprocess.run(cmd, check=True)


def run_live_recording(config, mode: str) -> Path:
    """High-level helper used by the CLI: record until Ctrl+C, then return
    the final media file path."""
    import signal

    rec = LiveRecorder(config, mode=mode)
    rec.start()

    stop_evt = threading.Event()

    def _on_signal(signum, frame):  # noqa: ARG001
        stop_evt.set()

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    try:
        while not stop_evt.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass

    return rec.stop()
