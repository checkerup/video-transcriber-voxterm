"""Tests for the VoxTerm-style (sherpa-onnx) diarization backend.

Most of these tests run without downloading any models — they verify the
plumbing (config wiring, audio loading, error paths). The actual end-to-end
test downloads ~30MB of models and is opt-in via VIDEO_TRANSCRIBER_E2E=1.
"""

from __future__ import annotations

import os
import sys
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_transcriber.config import AppConfig, DiarizationConfig
from video_transcriber.diarizer_voxterm import (
    _ensure_embedding_model,
    _ensure_segmentation_model,
    _load_audio_16k_mono,
    _models_dir,
    _resample,
    diarize_audio_voxterm,
)


# --------------------------- Audio helpers ---------------------------


def _write_sine_wav(path: Path, freq_hz: float, duration_s: float, sample_rate: int = 16000):
    """Write a mono 16-bit PCM sine wave to disk. Used as cheap test audio."""
    import math
    import struct

    n_samples = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        for i in range(n_samples):
            v = int(0.6 * 32767 * math.sin(2 * math.pi * freq_hz * i / sample_rate))
            w.writeframes(struct.pack("<h", v))


def _concat_wavs(out_path: Path, *parts: Path) -> None:
    """Glue multiple mono 16-bit PCM wavs into one."""
    with wave.open(str(out_path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        with wave.open(str(parts[0]), "rb") as first:
            out.setframerate(first.getframerate())
        for part in parts:
            with wave.open(str(part), "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))


# --------------------------- Unit-style tests ---------------------------


def test_models_dir_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_TRANSCRIBER_MODELS_DIR", str(tmp_path / "custom"))
    d = _models_dir()
    assert d == (tmp_path / "custom").resolve()


def test_resample_identity():
    import numpy as np

    x = np.array([0.0, 0.5, -0.5, 1.0], dtype=np.float32)
    out = _resample(x, 16000, 16000)
    assert (out == x).all()


def test_resample_changes_length():
    import numpy as np

    x = np.zeros(16000, dtype=np.float32)  # 1s @ 16k
    out = _resample(x, 16000, 8000)
    assert len(out) == 8000


def test_load_audio_16k_mono_wav(tmp_path):
    """Loading a wav already at 16k mono should be a no-op."""
    wav = tmp_path / "tone.wav"
    _write_sine_wav(wav, freq_hz=440.0, duration_s=0.5, sample_rate=16000)
    data, sr = _load_audio_16k_mono(wav)
    assert sr == 16000
    assert len(data) == 8000
    # Sine wave should have non-trivial energy.
    assert (data * data).sum() > 0.01


def test_load_audio_16k_mono_resample(tmp_path):
    """Loading a 22050Hz wav should resample down to 16k."""
    wav = tmp_path / "tone.wav"
    _write_sine_wav(wav, freq_hz=440.0, duration_s=0.5, sample_rate=22050)
    data, sr = _load_audio_16k_mono(wav)
    assert sr == 16000
    # 0.5s @ 16k = 8000 samples (allow rounding)
    assert 7980 <= len(data) <= 8020


def test_diarize_voxterm_missing_audio_file_raises():
    config = AppConfig(
        diarization=DiarizationConfig(enabled=True, backend="voxterm")
    )
    with pytest.raises(FileNotFoundError):
        diarize_audio_voxterm("/this/does/not/exist.wav", config)


def test_diarize_voxterm_missing_deps(tmp_path, monkeypatch):
    """If sherpa_onnx isn't importable, we should get a clean ImportError
    with an actionable message — not a NameError."""
    wav = tmp_path / "tone.wav"
    _write_sine_wav(wav, freq_hz=440.0, duration_s=0.2)

    config = AppConfig(diarization=DiarizationConfig(enabled=True, backend="voxterm"))

    # Drop sherpa_onnx from sys.modules and shadow it so re-import fails
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sherpa_onnx":
            raise ImportError("simulated: sherpa_onnx not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError) as excinfo:
        diarize_audio_voxterm(str(wav), config)
    assert "sherpa-onnx" in str(excinfo.value) or "sherpa_onnx" in str(excinfo.value)


# --------------------------- End-to-end test ---------------------------

@pytest.mark.skipif(
    os.environ.get("VIDEO_TRANSCRIBER_E2E") != "1",
    reason="Downloads ~30MB of ONNX models. Opt in with VIDEO_TRANSCRIBER_E2E=1.",
)
def test_diarize_voxterm_two_synthetic_speakers(tmp_path):
    """End-to-end: two distinct sine-wave 'speakers' should produce >=1 turn.

    This is NOT a quality benchmark — synthetic tones are not speech, so the
    embedding model may collapse them into a single cluster. We only assert
    that the pipeline runs without errors and returns a well-formed list.
    """
    speaker_a = tmp_path / "a.wav"
    speaker_b = tmp_path / "b.wav"
    combined = tmp_path / "two_speakers.wav"
    _write_sine_wav(speaker_a, freq_hz=440.0, duration_s=3.0)
    _write_sine_wav(speaker_b, freq_hz=220.0, duration_s=3.0)
    _concat_wavs(combined, speaker_a, speaker_b)

    config = AppConfig(
        diarization=DiarizationConfig(
            enabled=True,
            backend="voxterm",
            cluster_threshold=0.5,
            num_threads=1,
        )
    )

    turns = diarize_audio_voxterm(str(combined), config)
    assert isinstance(turns, list)
    for t in turns:
        assert set(t.keys()) == {"start", "end", "speaker"}
        assert 0.0 <= t["start"] <= t["end"] <= 10.0
        assert t["speaker"].startswith("SPEAKER_")
