"""
Lightweight timing utility for the video-transcriber pipeline.

Tracks total elapsed time + per-stage timings and can project an ETA when
given a progress fraction (0..1). Designed to be embedded in long-running
loops with cheap calls (no threads, no extra deps).
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


def format_hms(seconds: float | int | None) -> str:
    """Format a duration as HH:MM:SS (or --:--:-- if None / negative)."""
    if seconds is None or seconds < 0 or seconds != seconds:  # NaN check
        return "--:--:--"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class _Stage:
    name: str
    started_at: float
    ended_at: float | None = None

    @property
    def elapsed(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.monotonic()
        return max(0.0, end - self.started_at)

    @property
    def finished(self) -> bool:
        return self.ended_at is not None


@dataclass
class ProgressTimer:
    """Tracks pipeline timing across named stages.

    All times are seconds. ``time.monotonic`` is used internally so the
    timings are immune to wall-clock changes.
    """

    _started_at: float = field(default_factory=time.monotonic)
    _stages: list[_Stage] = field(default_factory=list)

    # ----- core api -----

    def begin(self, name: str) -> None:
        """Mark the beginning of a stage (idempotent for the same name)."""
        # If a stage with the same name is already open, leave it alone.
        for st in self._stages:
            if st.name == name and not st.finished:
                return
        self._stages.append(_Stage(name=name, started_at=time.monotonic()))

    def end(self, name: str) -> None:
        """Mark the end of the most recent open stage with this name."""
        for st in reversed(self._stages):
            if st.name == name and not st.finished:
                st.ended_at = time.monotonic()
                return

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Context manager — begin/end a stage automatically."""
        self.begin(name)
        try:
            yield
        finally:
            self.end(name)

    # ----- queries -----

    @property
    def total_elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._started_at)

    def stage_elapsed(self, name: str) -> float | None:
        """Total elapsed for a stage (sums multiple invocations of same name)."""
        matches = [s for s in self._stages if s.name == name]
        if not matches:
            return None
        return sum(s.elapsed for s in matches)

    def stages_summary(self) -> list[dict]:
        out = []
        for s in self._stages:
            out.append(
                {
                    "name": s.name,
                    "elapsed_seconds": round(s.elapsed, 3),
                    "elapsed_human": format_hms(s.elapsed),
                    "finished": s.finished,
                }
            )
        return out

    # ----- progress / eta -----

    def estimate_eta(self, progress: float, stage_name: str | None = None) -> float | None:
        """Estimate seconds remaining given a progress fraction in [0,1].

        If ``stage_name`` is provided, ETA is computed relative to that stage's
        own elapsed time; otherwise total pipeline elapsed is used.
        Returns ``None`` if progress is non-positive or >= 1.
        """
        if progress is None or progress <= 0 or progress >= 1:
            return None
        elapsed = (
            self.stage_elapsed(stage_name) if stage_name else self.total_elapsed
        )
        if elapsed is None or elapsed <= 0:
            return None
        total_estimated = elapsed / progress
        return max(0.0, total_estimated - elapsed)

    def format_progress(
        self,
        stage_name: str,
        progress: float,
        prefix: str = "",
    ) -> str:
        """Produce a human-readable progress line.

        Example: ``Transcription progress: 47.3% — elapsed 00:12:34, ETA 00:14:01``
        """
        elapsed = self.stage_elapsed(stage_name) or 0.0
        eta = self.estimate_eta(progress, stage_name=stage_name)
        pct = max(0.0, min(progress, 1.0)) * 100
        head = prefix or f"{stage_name} progress"
        return (
            f"{head}: {pct:.1f}% — elapsed {format_hms(elapsed)}, "
            f"ETA {format_hms(eta)}"
        )

    # ----- summary / persistence -----

    def format_summary(self, source_duration_s: float | None = None) -> str:
        """One-line human summary suitable for end-of-run logging."""
        total = self.total_elapsed
        parts = [f"Processed in {format_hms(total)}"]
        if source_duration_s and source_duration_s > 0 and total > 0:
            speedup = source_duration_s / total
            parts.append(f"speedup vs source: {speedup:.2f}x")
        # add brief per-stage breakdown
        seen: dict[str, float] = {}
        for s in self._stages:
            seen[s.name] = seen.get(s.name, 0.0) + s.elapsed
        if seen:
            breakdown = ", ".join(f"{n}={format_hms(t)}" for n, t in seen.items())
            parts.append(f"stages: {breakdown}")
        return " | ".join(parts)

    def as_dict(self, source_duration_s: float | None = None) -> dict:
        total = self.total_elapsed
        d: dict = {
            "total_elapsed_seconds": round(total, 3),
            "total_elapsed_human": format_hms(total),
            "source_duration_seconds": (
                round(source_duration_s, 3)
                if source_duration_s is not None and source_duration_s >= 0
                else None
            ),
            "stages": self.stages_summary(),
        }
        if source_duration_s and source_duration_s > 0 and total > 0:
            d["speedup_vs_source"] = round(source_duration_s / total, 3)
        return d

    def write_json(
        self,
        path: str | Path,
        source_duration_s: float | None = None,
    ) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.as_dict(source_duration_s), f, indent=2, ensure_ascii=False)
        return p
