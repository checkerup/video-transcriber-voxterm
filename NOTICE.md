# Third-Party Notices

This project (`video-transcriber-voxterm`) is a derivative of
[`video-transcriber`](https://github.com/checkerup/video-transcriber)
by **checkerup**, extended with an offline speaker-diarization backend and
a live-recording mode.

It bundles, depends on, or is directly inspired by the following
third-party projects. Their respective licenses are reproduced (or linked)
below.

---

## VoxTerm — *primary inspiration for the new diarization pipeline*

- **Project:** [`VoxTerm`](https://github.com/dmarzzz/VoxTerm)
- **Author:** David Marzocchi ([`@dmarzzz`](https://github.com/dmarzzz))
- **License:** MIT

VoxTerm is a local, real-time voice-transcription terminal built around an
ONNX-based diarization stack (3D-Speaker embeddings + pyannote
segmentation + online cosine clustering). VoxTerm itself is optimized for
macOS (Apple MLX for inference, Swift + ScreenCaptureKit for
system-audio capture, Apple Keychain for speaker-profile storage), but it
was the project that demonstrated to us that this *conceptual* pipeline
can run fully on-device, cross-platform, and without a HuggingFace token.

The new diarization backend in this repository — `diarizer_voxterm.py` —
**reimplements the same pipeline** (VAD → segmentation → speaker
embedding → cosine clustering) on top of [`sherpa-onnx`](https://github.com/k2-fsa/sherpa-onnx)
so that it works out-of-the-box on Windows, macOS and Linux without any
of VoxTerm's platform-specific dependencies. No source code from VoxTerm
is copied verbatim, but the design owes a clear debt to it and to the
public documentation in the VoxTerm repository.

The live-recording feature (`live_recorder.py`) is also functionally
inspired by VoxTerm's "live capture" UX (mic + system-audio + optional
screen, then transcribe on stop), although the implementation is
independent and uses `sounddevice` / `soundcard` / `ffmpeg` rather than
VoxTerm's Swift capture code.

> VoxTerm is © David Marzocchi and is distributed under the MIT License.
> See <https://github.com/dmarzzz/VoxTerm/blob/main/LICENSE>.

---

## sherpa-onnx — ONNX runtime for speech models

- **Project:** [`k2-fsa/sherpa-onnx`](https://github.com/k2-fsa/sherpa-onnx)
- **License:** Apache License 2.0
- **Used for:** Speaker segmentation + speaker embedding inference in the
  `voxterm` diarization backend. Pulled in via the optional
  `diarization-voxterm` extra.

---

## 3D-Speaker (CAM++ / ERes2NetV2)

- **Project:** [`modelscope/3D-Speaker`](https://github.com/modelscope/3D-Speaker)
- **Authors:** Speech Lab, Alibaba Group; Zhengyang Chen et al.
- **License:** Apache License 2.0
- **Used for:** Speaker-embedding ONNX models downloaded by the `voxterm`
  backend at first run (default: `3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx`).
- **Citation:**
  > Wang, H., Zheng, S., Chen, Y., Cheng, L., Chen, Q.
  > "CAM++: A Fast and Efficient Network for Speaker Verification
  > Using Context-Aware Masking." *Interspeech 2023.*

---

## pyannote.audio — segmentation model (3.0)

- **Project:** [`pyannote/pyannote-audio`](https://github.com/pyannote/pyannote-audio)
- **Author:** Hervé Bredin et al.
- **License:** MIT (code), CC-BY 4.0 (model weights)
- **Used for:** Speaker-segmentation ONNX model (a community-converted
  build of `pyannote/segmentation-3.0`) downloaded by the `voxterm`
  backend at first run. Also used directly by the legacy `pyannote`
  diarization backend in `diarizer.py`.

---

## Silero VAD

- **Project:** [`snakers4/silero-vad`](https://github.com/snakers4/silero-vad)
- **License:** MIT
- **Used for:** Optional voice-activity detection in the live-recording
  pipeline (silence trimming before diarization).

---

## faster-whisper

- **Project:** [`SYSTRAN/faster-whisper`](https://github.com/SYSTRAN/faster-whisper)
- **License:** MIT
- **Used for:** Transcription (already used by the upstream
  `video-transcriber` project; unchanged).

---

## soundcard / sounddevice / soundfile

- `soundcard` — BSD-3-Clause — WASAPI loopback for Windows system-audio
  capture in the live-recording mode.
- `sounddevice` — MIT — microphone capture in the live-recording mode.
- `soundfile` — BSD-3-Clause — WAV file I/O used throughout the new
  modules.

---

## Upstream project

This is a fork of [`checkerup/video-transcriber`](https://github.com/checkerup/video-transcriber).
The upstream project's `LICENSE` continues to apply to all files that
existed before this fork; new files added under this fork (notably
`diarizer_voxterm.py`, `live_recorder.py`, the corresponding tests, and
this `NOTICE.md`) are released under the same terms unless their file
header states otherwise.
