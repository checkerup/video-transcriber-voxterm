import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from .autostart import install_autostart, is_autostart_installed, uninstall_autostart
from .config import load_config
from .hardware import detect_hardware, print_hardware_report
from .pipeline import process_file
from .process_watcher import run_process_watcher
from .screen_recorder import start_recording, stop_recording
from .setup_wizard import is_setup_done, run_setup_wizard
from .watcher import start_watcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("video_transcriber")

queue: list[str] = []
lock = threading.Lock()
shutdown_event = threading.Event()


def _on_new_file(file_path: str, config):
    try:
        process_file(file_path, config)
    except Exception:
        logger.exception("Unhandled error processing: %s", file_path)


def _enqueue_file(file_path: str):
    with lock:
        if file_path not in queue:
            queue.append(file_path)
            logger.info("Queued for processing: %s", file_path)


def _signal_handler(sig, frame):
    logger.info("Shutdown signal received (%s)", sig)
    shutdown_event.set()


def queue_worker(queue: list[str], lock: threading.Lock, config, callback):
    while not shutdown_event.is_set():
        file_path = None
        with lock:
            if queue:
                file_path = queue.pop(0)
        if file_path:
            try:
                callback(file_path, config)
            except Exception:
                logger.exception("Error processing queued file: %s", file_path)
        else:
            time.sleep(0.1)


def run_once(config, video_path: str):
    result = process_file(video_path, config)
    if result["error"]:
        logger.error("Failed: %s", result["error"])
        sys.exit(1)
    logger.info("Done. Transcript: %s", result["transcript"])


def run_daemon(config):
    has_pw = config.process_watcher and config.process_watcher.program_names

    if has_pw:
        pw_thread = threading.Thread(
            target=run_process_watcher,
            args=(config, _enqueue_file, shutdown_event),
            daemon=True,
        )
        pw_thread.start()
        logger.info("Process watcher: monitoring %s", config.process_watcher.program_names)

    # Start queue worker thread
    worker_thread = threading.Thread(
        target=queue_worker,
        args=(queue, lock, config, _on_new_file),
        daemon=True
    )
    worker_thread.start()

    observer, handler = start_watcher(config, queue, lock)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("Video Transcriber daemon running. Press Ctrl+C to stop.")
    logger.info("Watching: %s", config.watch.folder)
    logger.info("Output: %s", config.processing.output_folder)
    if has_pw:
        logger.info("Process watcher: %s", config.process_watcher.program_names)

    try:
        while not shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")

    observer.stop()
    handler.cleanup()
    observer.join(timeout=5)
    if has_pw:
        pw_thread.join(timeout=5)
    worker_thread.join(timeout=5)
    logger.info("Stopped.")


def run_record(config):
    logger.info("Starting manual screen recording...")
    output = start_recording(config)
    if not output:
        logger.error("Failed to start recording")
        sys.exit(1)

    logger.info("Recording to: %s", output)
    logger.info("Press Ctrl+C to stop recording")

    signal.signal(signal.SIGINT, _signal_handler)
    try:
        while not shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    video_path = stop_recording()
    if video_path:
        logger.info("Recording saved: %s", video_path)
        result = process_file(video_path, config)
        if result["error"]:
            logger.error("Pipeline failed: %s", result["error"])
        else:
            logger.info("Done. Transcript: %s", result["transcript"])


def run_live(config, mode: str):
    """Live recording mode (voice / screen / full).

    Records until Ctrl+C, then feeds the resulting media file through the
    transcription + diarization pipeline.
    """
    from .live_recorder import run_live_recording

    logger.info("Starting live recording (mode=%s). Press Ctrl+C to stop.", mode)
    media_path = run_live_recording(config, mode=mode)
    if not media_path:
        logger.error("Live recording produced no output")
        sys.exit(1)

    logger.info("Recording saved: %s", media_path)
    result = process_file(str(media_path), config)
    if result["error"]:
        logger.error("Pipeline failed: %s", result["error"])
    else:
        logger.info("Done. Transcript: %s", result["transcript"])


def main():
    parser = argparse.ArgumentParser(
        description="Video Transcriber — auto-transcribe videos with Telegram notifications",
    )
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    parser.add_argument("--file", type=str, default=None, help="Process a single video file (one-shot mode)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--setup", action="store_true", help="Run first-time setup wizard")
    parser.add_argument("--install-autostart", action="store_true", help="Install as autostart service")
    parser.add_argument("--uninstall-autostart", action="store_true", help="Remove autostart service")
    parser.add_argument("--check-hardware", action="store_true", help="Detect hardware and print report")
    parser.add_argument("--record", action="store_true", help="Manual screen recording mode (Ctrl+C to stop)")
    parser.add_argument(
        "--watch-process", type=str, default=None,
        help="Watch for process name and auto-record (e.g. 'Zoom.exe')",
    )
    parser.add_argument(
        "--convert-mp3", nargs="+", type=str, default=None,
        help="Convert specified video file(s) to MP3",
    )
    parser.add_argument(
        "--silence-removal", action="store_true", default=None,
        help="Enable silence removal via FFmpeg",
    )
    parser.add_argument(
        "--no-silence-removal", action="store_true", default=None,
        help="Disable silence removal via FFmpeg",
    )
    parser.add_argument(
        "--translate-to", type=str, default=None,
        help="Translate transcript to specified language (e.g. 'ru')",
    )
    parser.add_argument(
        "--clean-paragraphs", action="store_true", default=None,
        help="Format output as clean paragraphs without timestamps",
    )
    parser.add_argument(
        "--summarize", action="store_true", default=None,
        help="Enable AI summarization using Gemini",
    )
    parser.add_argument(
        "--no-summarize", action="store_true", default=None,
        help="Disable AI summarization",
    )
    parser.add_argument(
        "--summarization-model", type=str, default=None,
        help="Model to use for summarization (e.g. gemini-1.5-pro)",
    )
    parser.add_argument(
        "--summarization-prompt", type=str, default=None,
        help="Custom prompt for summarization (can include {text})",
    )
    parser.add_argument(
        "--diarize", action="store_true", default=None,
        help="Enable speaker diarization (splitting by speakers)",
    )
    parser.add_argument(
        "--no-diarize", action="store_true", default=None,
        help="Disable speaker diarization",
    )
    parser.add_argument(
        "--hf-token", type=str, default=None,
        help="Hugging Face API token for loading pyannote model",
    )
    parser.add_argument(
        "--min-speakers", type=int, default=None,
        help="Minimum number of expected speakers",
    )
    parser.add_argument(
        "--max-speakers", type=int, default=None,
        help="Maximum number of expected speakers",
    )
    parser.add_argument(
        "--diar-backend", type=str, default=None,
        choices=["voxterm", "pyannote"],
        help="Diarization backend: 'voxterm' (offline, default) or 'pyannote' (HF).",
    )
    parser.add_argument(
        "--diar-model", type=str, default=None,
        choices=["cam++", "eres2net"],
        help="Speaker-embedding model for the voxterm backend (default: cam++).",
    )
    parser.add_argument(
        "--record-live",
        choices=["voice", "screen", "full"],
        default=None,
        help=(
            "Live recording mode: 'voice' (mic only), 'screen' (screen+mic), "
            "or 'full' (screen+mic+system audio)."
        ),
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the GUI"
    )
    parser.add_argument(
        "--gui-debug",
        action="store_true",
        help="Enable debug logging for the GUI"
    )
    parser.add_argument(
        "--retag-speakers",
        type=str,
        default=None,
        metavar="TRANSCRIPT",
        help=(
            "Re-tag speakers on an existing transcript (.txt/.srt/.vtt) "
            "WITHOUT re-running Whisper. Uses --audio if given, else "
            "auto-discovers the audio file next to the transcript. "
            "Combine with --num-speakers / --cluster-threshold / "
            "--diar-model to tune."
        ),
    )
    parser.add_argument(
        "--audio",
        type=str,
        default=None,
        metavar="PATH",
        help="Explicit audio file to use with --retag-speakers.",
    )
    parser.add_argument(
        "--num-speakers",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Force exact number of speakers (overrides clustering threshold)."
        ),
    )
    parser.add_argument(
        "--cluster-threshold",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Clustering threshold for speaker separation.",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config_path = Path(args.config) if args.config else None
    project_root = Path(__file__).resolve().parent.parent.parent

    if args.check_hardware:
        hw = detect_hardware()
        print_hardware_report(hw)
        return

    if args.install_autostart:
        ok = install_autostart(config_path=config_path)
        print("Autostart installed." if ok else "Autostart installation failed.")
        return

    if args.uninstall_autostart:
        ok = uninstall_autostart()
        print("Autostart removed." if ok else "Autostart removal failed.")
        return

    if args.setup or not is_setup_done(project_root):
        if not is_setup_done(project_root):
            logger.info("First run detected — launching setup wizard")
        run_setup_wizard(config_path=config_path if config_path else project_root / "config.yaml")
        if args.setup:
            return

    config = load_config(args.config)

    # Ensure watch and output folders exist
    Path(config.watch.folder).mkdir(parents=True, exist_ok=True)
    Path(config.processing.output_folder).mkdir(parents=True, exist_ok=True)

    if args.watch_process:
        config.process_watcher.program_names = [p.strip() for p in args.watch_process.split(",")]
        logger.info("CLI override: watching processes %s", config.process_watcher.program_names)

    if args.silence_removal is True:
        config.processing.silence_removal = True
    elif args.no_silence_removal is True:
        config.processing.silence_removal = False

    if args.translate_to is not None:
        config.transcription.translate_to = args.translate_to

    if args.clean_paragraphs is True:
        config.transcription.clean_paragraphs = True

    if args.summarize is True:
        config.summarization.enabled = True
    elif args.no_summarize is True:
        config.summarization.enabled = False

    if args.summarization_model is not None:
        config.summarization.model = args.summarization_model

    if args.summarization_prompt is not None:
        config.summarization.prompt = args.summarization_prompt

    if args.diarize is True:
        config.diarization.enabled = True
    elif args.no_diarize is True:
        config.diarization.enabled = False

    if args.hf_token is not None:
        config.diarization.auth_token = args.hf_token

    if args.min_speakers is not None:
        config.diarization.min_speakers = args.min_speakers

    if args.max_speakers is not None:
        config.diarization.max_speakers = args.max_speakers

    if args.diar_backend is not None:
        config.diarization.backend = args.diar_backend

    if args.diar_model is not None:
        config.diarization.model = args.diar_model

    if args.convert_mp3:
        from .extractor import convert_video_to_mp3
        for file_path in args.convert_mp3:
            logger.info("Converting file to MP3: %s", file_path)
            try:
                out = convert_video_to_mp3(file_path, config)
                logger.info("Successfully converted to MP3: %s", out)
            except Exception as e:
                logger.error("Failed to convert %s to MP3: %s", file_path, e)
                sys.exit(1)
        return

    hw = detect_hardware()
    logger.info(
        "Hardware: %s, RAM=%.1fGB, GPU=%s, model=%s/%s",
        hw.os_name, hw.ram_gb,
        hw.gpu_name if hw.has_cuda else "none",
        config.transcription.model_size,
        config.transcription.device,
    )

    if args.retag_speakers:
        from .retag_speakers import retag_speakers
        retag_speakers(
            args.retag_speakers,
            config,
            audio_path=args.audio,
            num_speakers=args.num_speakers,
            cluster_threshold=args.cluster_threshold,
        )
        sys.exit(0)
    elif args.file:
        run_once(config, args.file)
    elif args.record_live:
        run_live(config, args.record_live)
    elif args.record:
        run_record(config)
    elif args.gui:
        from video_transcriber.webui import launch as _launch_gui
        gui_cfg_path = config_path if config_path else (project_root / "config.yaml")
        _launch_gui(
            config=config,
            config_path=gui_cfg_path,
            project_root=project_root,
            debug=args.gui_debug,
        )
        sys.exit(0)
    else:
        run_daemon(config)


if __name__ == "__main__":
    main()
