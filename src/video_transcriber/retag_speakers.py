"""Re-tag speakers in an existing transcript WITHOUT re-running Whisper.

Fast iteration path when diarization quality is bad: keep the expensive
Whisper output, only re-run the relatively cheap speaker diarization
with different parameters (threshold / num_speakers / model / backend).

Inputs:
  - a transcript produced by an earlier run (.txt / .srt / .vtt)
  - an audio file (.mp3/.wav/...) supplied via --audio or auto-discovered
    next to the transcript

Output: a new transcript written next to the original with a
``.retagged.{ext}`` suffix.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .config import AppConfig, DiarizationConfig
from .diarizer import diarize_audio

logger = logging.getLogger(__name__)


# ---------- transcript parsing ----------

# Bracketed format produced by our transcriber:
#   [hh:mm:ss.ms] SPEAKER_NN: text
#   [hh:mm:ss.ms] text             (no diarization)
_RE_TXT = re.compile(
    r"^\[(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})(?:\.(?P<ms>\d{1,3}))?\]\s*"
    r"(?:SPEAKER_\d+:\s*)?"
    r"(?P<text>.*)$"
)

_RE_SRT_TIME = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})\s*-->\s*"
    r"(?P<h2>\d{2}):(?P<m2>\d{2}):(?P<s2>\d{2}),(?P<ms2>\d{3})"
)

_RE_VTT_TIME = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{3})\s*-->\s*"
    r"(?P<h2>\d{2}):(?P<m2>\d{2}):(?P<s2>\d{2})\.(?P<ms2>\d{3})"
)


def _ts_to_sec(h: str, m: str, s: str, ms: str | None) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + (int(ms or 0) / (10 ** len(ms or "")))


def _fmt_brackets(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    return f"[{h:02d}:{m:02d}:{s:06.3f}]"


def _parse_txt(lines: Iterable[str]) -> list[dict]:
    """Parse our bracketed .txt output into segment dicts with start/text."""
    out: list[dict] = []
    for line in lines:
        line = line.rstrip("\n")
        m = _RE_TXT.match(line)
        if not m:
            continue
        start = _ts_to_sec(m["h"], m["m"], m["s"], m["ms"])
        out.append({"start": start, "end": None, "text": m["text"].strip()})
    # derive ends from next-start (last segment uses +5s heuristic)
    for i in range(len(out) - 1):
        out[i]["end"] = out[i + 1]["start"]
    if out:
        out[-1]["end"] = out[-1]["start"] + 5.0
    return out


def _parse_srt(text: str) -> list[dict]:
    """Parse SRT blocks; ignores numeric counters and speaker tags."""
    blocks = re.split(r"\n\s*\n", text.strip())
    out: list[dict] = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        # first line may be a counter, find the timing line
        time_idx = next((i for i, ln in enumerate(lines) if _RE_SRT_TIME.search(ln)), None)
        if time_idx is None:
            continue
        m = _RE_SRT_TIME.search(lines[time_idx])
        start = _ts_to_sec(m["h"], m["m"], m["s"], m["ms"])
        end = _ts_to_sec(m["h2"], m["m2"], m["s2"], m["ms2"])
        text_lines = lines[time_idx + 1 :]
        # strip leading "SPEAKER_NN: " if present
        body = " ".join(text_lines).strip()
        body = re.sub(r"^SPEAKER_\d+:\s*", "", body)
        out.append({"start": start, "end": end, "text": body})
    return out


def _parse_vtt(text: str) -> list[dict]:
    """Parse WebVTT (very similar to SRT, dot instead of comma in timing)."""
    blocks = re.split(r"\n\s*\n", text.strip())
    out: list[dict] = []
    for block in blocks:
        if block.strip().upper().startswith("WEBVTT"):
            continue
        lines = [ln for ln in block.splitlines() if ln.strip()]
        time_idx = next((i for i, ln in enumerate(lines) if _RE_VTT_TIME.search(ln)), None)
        if time_idx is None:
            continue
        m = _RE_VTT_TIME.search(lines[time_idx])
        start = _ts_to_sec(m["h"], m["m"], m["s"], m["ms"])
        end = _ts_to_sec(m["h2"], m["m2"], m["s2"], m["ms2"])
        body = " ".join(lines[time_idx + 1 :]).strip()
        body = re.sub(r"^SPEAKER_\d+:\s*", "", body)
        out.append({"start": start, "end": end, "text": body})
    return out


def parse_transcript(path: Path) -> tuple[str, list[dict]]:
    """Returns (format, segments) where format is 'txt' | 'srt' | 'vtt'."""
    ext = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if ext == ".srt":
        return "srt", _parse_srt(text)
    if ext == ".vtt":
        return "vtt", _parse_vtt(text)
    # default to our bracketed txt
    return "txt", _parse_txt(text.splitlines())


# ---------- audio auto-discovery ----------

_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac")


def find_audio_for(transcript_path: Path) -> Path | None:
    """Look for an audio file next to the transcript with the same stem."""
    stem = transcript_path.stem
    # transcript may have suffixes like ".retagged" etc.; strip ours
    for suf in (".retagged",):
        if stem.endswith(suf):
            stem = stem[: -len(suf)]
    parent = transcript_path.parent
    for ext in _AUDIO_EXTS:
        cand = parent / f"{stem}{ext}"
        if cand.exists():
            return cand
    # also try parent's parent (transcripts often live next to audio in same dir)
    return None


# ---------- speaker assignment ----------

def assign_speakers(
    segments: list[dict],
    speaker_turns: list[dict],
) -> list[dict]:
    """Assign a speaker label to each transcript segment by max-overlap.

    Each segment gets the speaker whose turn overlaps it most in time.
    Segments with zero overlap stay unlabeled (speaker=None).
    """
    out = []
    for seg in segments:
        s0, s1 = float(seg["start"]), float(seg["end"] or seg["start"])
        best_spk = None
        best_overlap = 0.0
        for t in speaker_turns:
            t0, t1 = float(t["start"]), float(t["end"])
            ov = max(0.0, min(s1, t1) - max(s0, t0))
            if ov > best_overlap:
                best_overlap = ov
                best_spk = t["speaker"]
        out.append({**seg, "speaker": best_spk})
    return out


# ---------- output formatting ----------

def _render_txt(tagged: list[dict]) -> str:
    out_lines = []
    for seg in tagged:
        ts = _fmt_brackets(float(seg["start"]))
        spk = seg.get("speaker")
        prefix = f"{ts} {spk}: " if spk else f"{ts} "
        out_lines.append(prefix + (seg["text"] or ""))
    return "\n".join(out_lines) + "\n"


def _fmt_srt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _render_srt(tagged: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(tagged, start=1):
        spk = seg.get("speaker")
        body = (f"{spk}: " if spk else "") + (seg["text"] or "")
        lines += [
            str(i),
            f"{_fmt_srt_time(float(seg['start']))} --> {_fmt_srt_time(float(seg['end']))}",
            body,
            "",
        ]
    return "\n".join(lines)


def _render_vtt(tagged: list[dict]) -> str:
    lines = ["WEBVTT", ""]
    for seg in tagged:
        spk = seg.get("speaker")
        body = (f"{spk}: " if spk else "") + (seg["text"] or "")
        s0 = _fmt_srt_time(float(seg["start"])).replace(",", ".")
        s1 = _fmt_srt_time(float(seg["end"])).replace(",", ".")
        lines += [f"{s0} --> {s1}", body, ""]
    return "\n".join(lines)


# ---------- main entry ----------

def retag_speakers(
    transcript_path: str,
    config: AppConfig,
    *,
    audio_path: str | None = None,
    backend: str | None = None,
    model: str | None = None,
    cluster_threshold: float | None = None,
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> Path:
    """Re-tag speakers in an existing transcript.

    Returns the path of the newly-written transcript file.
    """
    tpath = Path(transcript_path).expanduser().resolve()
    if not tpath.exists():
        raise FileNotFoundError(f"Transcript not found: {tpath}")

    apath = Path(audio_path).expanduser().resolve() if audio_path else find_audio_for(tpath)
    if apath is None or not apath.exists():
        raise FileNotFoundError(
            f"Audio not found. Pass --audio explicitly. Looked next to {tpath}"
        )

    fmt, segments = parse_transcript(tpath)
    if not segments:
        raise ValueError(f"No segments parsed from transcript ({fmt}): {tpath}")
    logger.info("Parsed %d segments from %s (%s)", len(segments), tpath.name, fmt)

    # Build a fresh DiarizationConfig from the user's config + overrides.
    base = config.diarization
    diar_cfg = replace(
        base,
        enabled=True,
        backend=backend or base.backend,
        model=model or base.model,
        cluster_threshold=(
            cluster_threshold if cluster_threshold is not None else base.cluster_threshold
        ),
        num_speakers=num_speakers if num_speakers is not None else getattr(base, "num_speakers", None),
        min_speakers=min_speakers if min_speakers is not None else base.min_speakers,
        max_speakers=max_speakers if max_speakers is not None else base.max_speakers,
    )
    cfg_for_diar = replace(config, diarization=diar_cfg)

    logger.info(
        "Re-diarizing %s (backend=%s model=%s threshold=%.2f num=%s min=%s max=%s)",
        apath.name,
        diar_cfg.backend,
        diar_cfg.model,
        diar_cfg.cluster_threshold,
        diar_cfg.num_speakers,
        diar_cfg.min_speakers,
        diar_cfg.max_speakers,
    )

    turns = diarize_audio(str(apath), cfg_for_diar)
    if not turns:
        raise RuntimeError("Diarization returned no speaker turns")
    n_speakers = len({t["speaker"] for t in turns})
    logger.info("Got %d turns across %d distinct speakers", len(turns), n_speakers)

    tagged = assign_speakers(segments, turns)

    if fmt == "srt":
        body = _render_srt(tagged)
    elif fmt == "vtt":
        body = _render_vtt(tagged)
    else:
        body = _render_txt(tagged)

    out_path = tpath.with_suffix(f".retagged{tpath.suffix}")
    out_path.write_text(body, encoding="utf-8")
    logger.info("Wrote re-tagged transcript: %s", out_path)
    return out_path
