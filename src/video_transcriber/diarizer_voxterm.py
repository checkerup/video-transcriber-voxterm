"""
Offline speaker diarization backend powered by sherpa-onnx.

This backend was inspired by VoxTerm (https://github.com/dmarzzz/VoxTerm) by
@dmarzzz, which demonstrated that a fully local, cross-platform diarization
pipeline can be assembled from publicly available ONNX models (3D-Speaker for
speaker embeddings + a segmentation model + online cosine clustering).

VoxTerm itself is macOS-focused (MLX inference, Swift system-audio capture,
Apple Keychain for speaker profile storage). For the purposes of this project
the same conceptual pipeline is implemented on top of `sherpa-onnx`, which
ships pre-built cross-platform binaries (Windows/macOS/Linux) and exposes the
same kind of segmentation + embedding + clustering primitives.

Acknowledgements:
- VoxTerm (MIT, Apache-2.0 for vendored components) — @dmarzzz
- 3D-Speaker — Alibaba DAMO Academy (Apache-2.0)
- pyannote segmentation 3.0 — Hervé Bredin et al. (MIT)
- sherpa-onnx — the k2-fsa project (Apache-2.0)

The user-facing benefit over the existing pyannote backend is that NO
HuggingFace token or model license acceptance is required: models are
downloaded once on first use from public ONNX mirrors.
"""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# -------------------------- Model registry --------------------------

# Public mirrors maintained by the sherpa-onnx project. Each entry is a tarball
# containing the ONNX model file(s).
_SEGMENTATION_MODELS = {
    "pyannote-3.0": {
        "url": (
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
            "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
        ),
        # File inside the tarball relative to its top-level directory
        "model_file": "model.onnx",
        "dirname": "sherpa-onnx-pyannote-segmentation-3-0",
    },
}

_EMBEDDING_MODELS = {
    # CAM++ — the same family used by VoxTerm; 7.2M parameters, fast.
    "cam++": {
        "url": (
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
            "speaker-recongition-models/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
        ),
        "filename": "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx",
    },
    # ERes2NetV2 — slightly larger, sometimes more accurate. Also from 3D-Speaker.
    "eres2net": {
        "url": (
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
            "speaker-recongition-models/3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx"
        ),
        "filename": "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx",
    },
}


def _models_dir() -> Path:
    """Return the directory where downloaded ONNX models live.

    Honours the ``VIDEO_TRANSCRIBER_MODELS_DIR`` env var so power users (and
    tests) can override the location. Defaults to ``~/.cache/video-transcriber/models``.
    """
    env = os.environ.get("VIDEO_TRANSCRIBER_MODELS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".cache" / "video-transcriber" / "models"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    logger.info("Downloading %s -> %s", url, dest)
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out, length=1 << 20)
    tmp.replace(dest)


def _ensure_segmentation_model(name: str) -> Path:
    info = _SEGMENTATION_MODELS.get(name)
    if info is None:
        raise ValueError(
            f"Unknown segmentation model: {name!r}. "
            f"Available: {list(_SEGMENTATION_MODELS)}"
        )
    target_dir = _models_dir() / info["dirname"]
    model_path = target_dir / info["model_file"]
    if model_path.exists():
        return model_path

    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpd:
        tar_path = Path(tmpd) / "model.tar.bz2"
        _download(info["url"], tar_path)
        logger.info("Extracting segmentation tarball...")
        with tarfile.open(tar_path, "r:bz2") as tar:
            tar.extractall(tmpd)
        # Find the actual model.onnx in the extracted tree (handles nested
        # top-level directory naming).
        candidates = list(Path(tmpd).rglob(info["model_file"]))
        if not candidates:
            raise RuntimeError(
                f"Could not find {info['model_file']} inside downloaded tarball"
            )
        shutil.copy2(candidates[0], model_path)
    return model_path


def _ensure_embedding_model(name: str) -> Path:
    info = _EMBEDDING_MODELS.get(name)
    if info is None:
        raise ValueError(
            f"Unknown embedding model: {name!r}. "
            f"Available: {list(_EMBEDDING_MODELS)}"
        )
    target = _models_dir() / info["filename"]
    if target.exists():
        return target
    _download(info["url"], target)
    return target


# -------------------------- Main entry point --------------------------


@dataclass
class _Segment:
    start: float
    end: float
    speaker: str


def diarize_audio_voxterm(audio_path: str, config) -> list[dict]:
    """Run offline speaker diarization on a 16kHz mono audio file.

    Returns a list of speaker turns: ``[{"start", "end", "speaker"}, ...]``
    in chronological order. The function accepts an arbitrary audio file —
    it will resample/downmix as needed using soundfile + numpy.

    Args:
        audio_path: Path to an audio file (any format readable by soundfile;
            for compatibility we accept the same files the rest of the
            pipeline produces, e.g. .mp3/.wav).
        config: The application's :class:`AppConfig`. Reads
            ``diarization.{model, min_speakers, max_speakers,
            cluster_threshold, num_threads}``.

    Raises:
        ImportError: If sherpa-onnx or soundfile are not installed.
        FileNotFoundError: If the audio file does not exist.
    """
    audio_p = Path(audio_path)
    if not audio_p.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    try:
        import numpy as np
        import sherpa_onnx
        import soundfile as sf
    except ImportError as e:
        raise ImportError(
            "VoxTerm-style diarization requires 'sherpa-onnx', 'soundfile' "
            "and 'numpy'. Install with: pip install -e .[diarization-voxterm]"
        ) from e

    diar_cfg = config.diarization
    embedding_model_name = getattr(diar_cfg, "model", None) or "cam++"
    num_threads = max(1, int(getattr(diar_cfg, "num_threads", 1) or 1))
    threshold = float(getattr(diar_cfg, "cluster_threshold", 0.7) or 0.7)
    min_speakers = getattr(diar_cfg, "min_speakers", None)
    max_speakers = getattr(diar_cfg, "max_speakers", None)
    num_speakers = getattr(diar_cfg, "num_speakers", None)

    # Load audio (decoder via libsndfile handles wav/flac; for mp3/m4a we use
    # ffmpeg as a fallback. Most of our audio_path inputs come straight from
    # the extractor which produces mp3 — handle that).
    samples, sample_rate = _load_audio_16k_mono(audio_p)

    # Models
    logger.info(
        "Preparing diarization models (segmentation=pyannote-3.0, embedding=%s)...",
        embedding_model_name,
    )
    seg_path = _ensure_segmentation_model("pyannote-3.0")
    emb_path = _ensure_embedding_model(embedding_model_name)

    seg_cfg = sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
        pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
            model=str(seg_path)
        ),
        num_threads=num_threads,
        debug=False,
        provider="cpu",
    )
    emb_cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(emb_path),
        num_threads=num_threads,
        debug=False,
        provider="cpu",
    )

    # Clustering: sherpa-onnx exposes num_clusters (=-1 for auto) and
    # cosine-distance threshold (lower = harder to merge speakers).
    # num_speakers (exact override) wins over min/max heuristics
    if num_speakers is not None and num_speakers > 0:
        num_clusters = int(num_speakers)
    elif min_speakers is not None and max_speakers is not None and min_speakers == max_speakers:
        num_clusters = int(min_speakers)
    elif max_speakers is not None and max_speakers > 0:
        # Treat as a hint via threshold tweak; sherpa-onnx itself only supports
        # exact num_clusters, so we use it only when fully constrained.
        num_clusters = -1
    else:
        num_clusters = -1

    cluster_cfg = sherpa_onnx.FastClusteringConfig(
        num_clusters=num_clusters,
        threshold=threshold,
    )

    diar_config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=seg_cfg,
        embedding=emb_cfg,
        clustering=cluster_cfg,
        min_duration_on=float(getattr(diar_cfg, "min_duration_on", 0.3) or 0.3),
        min_duration_off=float(getattr(diar_cfg, "min_duration_off", 0.5) or 0.5),
    )
    if not diar_config.validate():
        raise RuntimeError(
            "sherpa-onnx rejected the diarization config. Check that the "
            "downloaded model files exist and are not corrupted: "
            f"{seg_path}, {emb_path}"
        )

    sd = sherpa_onnx.OfflineSpeakerDiarization(diar_config)

    # sherpa-onnx expects 16kHz mono float samples.
    if sd.sample_rate != sample_rate:
        samples = _resample(samples, sample_rate, sd.sample_rate)
        sample_rate = sd.sample_rate

    logger.info("Running speaker diarization (%.1fs of audio)...", len(samples) / sample_rate)
    progress_state = {"last": 0}

    def _progress(processed_chunks, total_chunks):  # noqa: ARG001
        if total_chunks <= 0:
            return 0
        pct = int(processed_chunks * 100 / total_chunks)
        if pct - progress_state["last"] >= 10:
            logger.info("Diarization progress: %d%%", pct)
            progress_state["last"] = pct
        return 0

    result = sd.process(samples.tolist(), callback=_progress).sort_by_start_time()
    turns = [
        {"start": float(s.start), "end": float(s.end), "speaker": f"SPEAKER_{int(s.speaker):02d}"}
        for s in result
    ]

    # If the caller asked for exactly N speakers but auto-clustering gave us
    # fewer, that's fine — they probably picked a hint, not a hard constraint.
    if turns:
        unique = sorted({t["speaker"] for t in turns})
        logger.info(
            "Diarization done: %d turns across %d speakers (%s).",
            len(turns),
            len(unique),
            ", ".join(unique),
        )
    else:
        logger.warning("Diarization produced no turns. Audio may be silent or too short.")
    return turns


# -------------------------- Audio loading helpers --------------------------


def _load_audio_16k_mono(path: Path):
    """Load an audio file as float32 mono at 16kHz.

    Tries soundfile first (handles wav/flac/ogg/opus). For mp3/m4a/aac we
    transparently fall back to ffmpeg piping raw PCM.
    """
    import numpy as np
    import soundfile as sf

    suffix = path.suffix.lower()
    if suffix in (".wav", ".flac", ".ogg", ".opus"):
        data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    else:
        data, sr = _ffmpeg_decode(path)

    if data.ndim == 2:
        # Downmix to mono
        data = data.mean(axis=1)
    data = data.astype(np.float32, copy=False)

    if sr != 16000:
        data = _resample(data, sr, 16000)
        sr = 16000
    return data, sr


def _ffmpeg_decode(path: Path):
    """Decode an arbitrary audio/video file to mono float32 PCM via ffmpeg.

    Returns (numpy_array, sample_rate=16000).
    """
    import subprocess

    import numpy as np

    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            f"Cannot decode {path.name}: ffmpeg not found in PATH. "
            "Install ffmpeg, or pass a .wav/.flac file."
        )

    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-i", str(path),
        "-ac", "1", "-ar", "16000",
        "-f", "f32le", "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=True)
    pcm = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    return pcm, 16000


def _resample(data, src_sr: int, dst_sr: int):
    """Linear resampling — good enough for speaker-embedding inputs and adds
    no dependencies. (sherpa-onnx's segmentation/embedding models expect a
    relatively smooth 16k signal; the difference vs. a polyphase resampler is
    negligible at speech band.)"""
    import numpy as np

    if src_sr == dst_sr:
        return data
    ratio = dst_sr / src_sr
    n_out = int(round(len(data) * ratio))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, num=len(data), endpoint=False, dtype=np.float64)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False, dtype=np.float64)
    return np.interp(x_new, x_old, data).astype(np.float32)
