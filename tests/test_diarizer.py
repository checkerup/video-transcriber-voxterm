"""Tests for the diarizer dispatcher and the legacy pyannote backend.

The voxterm backend has dedicated tests in test_diarizer_voxterm.py.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from video_transcriber.config import AppConfig, DiarizationConfig
from video_transcriber.diarizer import diarize_audio


def test_diarize_audio_disabled():
    config = AppConfig(diarization=DiarizationConfig(enabled=False))
    assert diarize_audio("dummy.mp3", config) == []


def test_diarize_audio_unknown_backend():
    config = AppConfig(
        diarization=DiarizationConfig(enabled=True, backend="totally-made-up")
    )
    with pytest.raises(ValueError) as excinfo:
        diarize_audio("dummy.mp3", config)
    assert "backend" in str(excinfo.value).lower()


def test_diarize_audio_pyannote_missing_token():
    """The pyannote backend must complain about missing HF token before it
    even tries to import pyannote (so this works without pyannote installed)."""
    config = AppConfig(
        diarization=DiarizationConfig(enabled=True, backend="pyannote", auth_token="")
    )
    with pytest.raises(ValueError) as excinfo:
        diarize_audio("dummy.mp3", config)
    assert "Hugging Face API token" in str(excinfo.value)


def test_diarize_audio_default_backend_is_voxterm():
    """Default config should pick the voxterm backend (offline, no token)."""
    config = AppConfig(diarization=DiarizationConfig(enabled=True))
    assert config.diarization.backend == "voxterm"


@patch.dict(
    sys.modules,
    {
        "pyannote": MagicMock(),
        "pyannote.audio": MagicMock(),
        "torch": MagicMock(),
    },
)
def test_diarize_audio_pyannote_success():
    """Mocked end-to-end happy path for the legacy pyannote backend."""
    mock_pyannote = sys.modules["pyannote"]
    mock_pyannote_audio = sys.modules["pyannote.audio"]
    mock_pyannote.audio = mock_pyannote_audio

    mock_pipeline_class = mock_pyannote_audio.Pipeline
    mock_pipeline = MagicMock()
    mock_pipeline_class.from_pretrained.return_value = mock_pipeline

    import torch
    torch.cuda.is_available.return_value = False
    torch.device.return_value = "cpu"

    config = AppConfig(
        diarization=DiarizationConfig(
            enabled=True, backend="pyannote", auth_token="hf_test_token"
        )
    )

    mock_turn = MagicMock()
    mock_turn.start = 1.0
    mock_turn.end = 2.5
    mock_diarization_result = MagicMock()
    mock_diarization_result.itertracks.return_value = [(mock_turn, None, "SPEAKER_00")]
    mock_pipeline.return_value = mock_diarization_result

    res = diarize_audio("dummy.mp3", config)

    mock_pipeline_class.from_pretrained.assert_called_once_with(
        "pyannote/speaker-diarization-3.1",
        use_auth_token="hf_test_token",
    )
    assert len(res) == 1
    assert res[0] == {"start": 1.0, "end": 2.5, "speaker": "SPEAKER_00"}
