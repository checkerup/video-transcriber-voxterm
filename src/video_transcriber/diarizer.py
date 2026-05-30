"""
Speaker diarization dispatcher.

Two backends are supported:

- ``voxterm`` (default) — fully offline, no HuggingFace token required.
  Uses sherpa-onnx with a pyannote-3.0 segmentation model plus a 3D-Speaker
  embedding model. Inspired by VoxTerm (https://github.com/dmarzzz/VoxTerm)
  by @dmarzzz, which proved that this stack is viable cross-platform.
  See ``diarizer_voxterm.py`` for the actual implementation.

- ``pyannote`` (legacy) — calls the original pyannote.audio pipeline,
  requires a HuggingFace API token and accepting model terms on HF.
"""

from __future__ import annotations

import logging

from video_transcriber.config import AppConfig

logger = logging.getLogger(__name__)


def diarize_audio(audio_path: str, config: AppConfig) -> list[dict]:
    """Run speaker diarization and return chronological speaker turns.

    Each turn is ``{"start": float, "end": float, "speaker": str}``.

    The backend is selected via ``config.diarization.backend``. Returns
    an empty list when diarization is disabled.
    """
    if not config.diarization.enabled:
        logger.debug("Speaker diarization is disabled.")
        return []

    backend = (getattr(config.diarization, "backend", "voxterm") or "voxterm").lower()

    if backend in ("voxterm", "sherpa-onnx", "sherpa", "onnx", "offline"):
        from .diarizer_voxterm import diarize_audio_voxterm
        return diarize_audio_voxterm(audio_path, config)

    if backend in ("pyannote", "pyannote.audio", "hf"):
        return _diarize_audio_pyannote(audio_path, config)

    raise ValueError(
        f"Unknown diarization backend: {backend!r}. "
        "Expected one of: 'voxterm' (default, offline), 'pyannote' (legacy)."
    )


def _diarize_audio_pyannote(audio_path: str, config: AppConfig) -> list[dict]:
    """Legacy backend: pyannote.audio from HuggingFace.

    Requires a valid HF token and acceptance of the pyannote model terms.
    """
    token = (config.diarization.auth_token or "").strip()
    if not token:
        raise ValueError(
            "Hugging Face API token (auth_token) is required for the "
            "'pyannote' diarization backend. Set diarization.auth_token in "
            "config.yaml, or HF_TOKEN env var. Alternatively, switch to the "
            "offline backend by setting diarization.backend: voxterm."
        )

    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as e:
        raise ImportError(
            "The 'pyannote.audio' library is required for the pyannote "
            "backend. Install it with: pip install -e .[diarization-pyannote] "
            "or switch to diarization.backend: voxterm (no extra install needed)."
        ) from e

    logger.info("Initializing PyAnnote speaker diarization pipeline...")
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=token,
        )
    except Exception as e:
        logger.error("Failed to load PyAnnote pipeline from Hugging Face: %s", e)
        raise RuntimeError(
            "Failed to load speaker diarization pipeline. Make sure you "
            "accepted the terms for 'pyannote/speaker-diarization-3.1' and "
            "'pyannote/segmentation-3.0' on Hugging Face, and that your API "
            f"token is correct. Error: {e}"
        )

    device = torch.device(
        "cuda" if torch.cuda.is_available() and config.transcription.device == "cuda" else "cpu"
    )
    logger.info("Running pyannote diarization on device: %s", device)
    pipeline.to(device)

    diarization_result = pipeline(
        audio_path,
        min_speakers=config.diarization.min_speakers,
        max_speakers=config.diarization.max_speakers,
    )

    turns = [
        {"start": turn.start, "end": turn.end, "speaker": speaker}
        for turn, _, speaker in diarization_result.itertracks(yield_label=True)
    ]
    logger.info("Speaker diarization complete. Found %d speaker turns.", len(turns))
    return turns
