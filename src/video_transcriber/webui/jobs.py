"""Background job manager for the GUI.

Runs pipeline jobs in worker threads, tracks per-job state (progress, ETA,
stage, log tail), and exposes a thread-safe snapshot API for the JS API to
poll every ~500ms.

Why polling and not push? PyWebView's window.evaluate_js round-trip works,
but a poll loop is simpler, robust to JS reloads, and good enough at 2 Hz.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import AppConfig
from ..progress_timer import format_hms


logger = logging.getLogger(__name__)


@dataclass
class JobState:
    job_id: str
    file_path: str
    kind: str  # "process" | "retag" | "live"
    created_at: float = field(default_factory=time.time)
    status: str = "queued"  # queued | running | done | failed | cancelled
    stage: str = ""
    progress: float = 0.0  # 0..1
    elapsed_seconds: float = 0.0
    eta_seconds: float | None = None
    result: dict | None = None
    error: str | None = None
    log_tail: deque = field(default_factory=lambda: deque(maxlen=200))

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "file_path": self.file_path,
            "kind": self.kind,
            "created_at": self.created_at,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 4),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "elapsed_human": format_hms(self.elapsed_seconds),
            "eta_seconds": (None if self.eta_seconds is None
                            else round(self.eta_seconds, 2)),
            "eta_human": format_hms(self.eta_seconds) if self.eta_seconds is not None else None,
            "result": self.result,
            "error": self.error,
            "log_tail": list(self.log_tail)[-30:],
        }


class _GuiLogHandler(logging.Handler):
    """Forwards every log record into the currently-running job's tail."""

    def __init__(self, manager: "JobManager"):
        super().__init__(level=logging.INFO)
        self.manager = manager
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self.manager._lock:
                job = self.manager._active_job
                if job is not None:
                    job.log_tail.append(msg)
        except Exception:  # pragma: no cover - logging must never raise
            pass


class JobManager:
    """Thread-safe queue + executor for pipeline jobs."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._lock = threading.RLock()
        self._jobs: dict[str, JobState] = {}
        self._order: list[str] = []
        self._active_job: JobState | None = None
        self._worker: threading.Thread | None = None
        self._cancel_flags: dict[str, threading.Event] = {}
        # install the log forwarder once
        self._log_handler = _GuiLogHandler(self)
        root = logging.getLogger()
        if self._log_handler not in root.handlers:
            root.addHandler(self._log_handler)

    # ---------- public API ----------

    def enqueue_process(self, file_path: str, overrides: dict | None = None) -> str:
        """Queue a file for the full pipeline (extract + transcribe + diarize)."""
        return self._enqueue("process", file_path, overrides or {})

    def enqueue_retag(self, transcript_path: str, overrides: dict | None = None) -> str:
        """Queue a retag-speakers run on an existing transcript."""
        return self._enqueue("retag", transcript_path, overrides or {})

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            flag = self._cancel_flags.get(job_id)
            if flag is None:
                return False
            flag.set()
            job = self._jobs.get(job_id)
            if job and job.status == "queued":
                job.status = "cancelled"
            return True

    def snapshot_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._jobs[jid].snapshot() for jid in self._order]

    def snapshot_one(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.snapshot() if job else None

    def active_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return self._active_job.snapshot() if self._active_job else None

    # ---------- internals ----------

    def _enqueue(self, kind: str, target: str, overrides: dict) -> str:
        job_id = uuid.uuid4().hex[:12]
        state = JobState(job_id=job_id, file_path=target, kind=kind)
        with self._lock:
            self._jobs[job_id] = state
            self._order.append(job_id)
            self._cancel_flags[job_id] = threading.Event()
            state._overrides = overrides  # type: ignore[attr-defined]
            state._kind = kind  # type: ignore[attr-defined]
        self._ensure_worker()
        return job_id

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._run_loop, daemon=True,
                                            name="vt-gui-worker")
            self._worker.start()

    def _run_loop(self) -> None:
        while True:
            with self._lock:
                next_job = next(
                    (self._jobs[jid] for jid in self._order
                     if self._jobs[jid].status == "queued"),
                    None,
                )
                if next_job is None:
                    self._active_job = None
                    self._worker = None
                    return
                self._active_job = next_job
                next_job.status = "running"
                cancel_flag = self._cancel_flags[next_job.job_id]
            try:
                self._execute(next_job, cancel_flag)
            except Exception as e:
                logger.exception("Job %s failed: %s", next_job.job_id, e)
                with self._lock:
                    next_job.status = "failed"
                    next_job.error = str(e)

    def _apply_overrides(self, overrides: dict) -> AppConfig:
        """Return a *new* AppConfig with the given GUI overrides applied.

        Only a flat allow-list of fields is supported; everything else is
        left untouched. We never mutate self.config in-place from a worker.
        """
        import copy

        cfg = copy.deepcopy(self.config)
        if "diarize" in overrides:
            cfg.diarization.enabled = bool(overrides["diarize"])
        if "num_speakers" in overrides and overrides["num_speakers"]:
            cfg.diarization.num_speakers = int(overrides["num_speakers"])
        if "cluster_threshold" in overrides and overrides["cluster_threshold"] is not None:
            cfg.diarization.cluster_threshold = float(overrides["cluster_threshold"])
        if "diar_backend" in overrides and overrides["diar_backend"]:
            cfg.diarization.backend = str(overrides["diar_backend"])
        if "diar_model" in overrides and overrides["diar_model"]:
            cfg.diarization.model = str(overrides["diar_model"])
        if "model_size" in overrides and overrides["model_size"]:
            cfg.transcription.model_size = str(overrides["model_size"])
        if "language" in overrides and overrides["language"]:
            cfg.transcription.language = str(overrides["language"])
        if "translate_to" in overrides and overrides["translate_to"] is not None:
            cfg.transcription.translate_to = str(overrides["translate_to"]) or None
        if "summarize" in overrides:
            cfg.summarization.enabled = bool(overrides["summarize"])
        return cfg

    def _execute(self, job: JobState, cancel_flag: threading.Event) -> None:
        from ..pipeline import process_file
        from ..retag_speakers import retag_speakers

        overrides = getattr(job, "_overrides", {})
        kind = getattr(job, "_kind", job.kind)
        cfg = self._apply_overrides(overrides)

        # bridge: attach a callback the pipeline can invoke after each stage
        def on_stage_change(stage_name: str, progress: float, elapsed: float,
                            eta: float | None) -> None:
            with self._lock:
                job.stage = stage_name
                job.progress = max(0.0, min(1.0, float(progress)))
                job.elapsed_seconds = float(elapsed)
                job.eta_seconds = eta
            if cancel_flag.is_set():
                raise InterruptedError("cancelled by user")

        cfg._gui_progress_cb = on_stage_change  # type: ignore[attr-defined]

        try:
            if kind == "process":
                result = process_file(job.file_path, cfg)
            elif kind == "retag":
                audio = overrides.get("audio_path") or None
                num = overrides.get("num_speakers")
                thr = overrides.get("cluster_threshold")
                out_path = retag_speakers(
                    job.file_path,
                    cfg,
                    audio_path=audio,
                    num_speakers=int(num) if num else None,
                    cluster_threshold=float(thr) if thr is not None else None,
                )
                result = {"retagged_path": str(out_path)}
            else:
                raise ValueError(f"unknown job kind: {kind}")

            with self._lock:
                job.status = "done"
                job.progress = 1.0
                job.result = result
        except InterruptedError:
            with self._lock:
                job.status = "cancelled"
        except Exception as e:
            with self._lock:
                job.status = "failed"
                job.error = str(e)
            raise
