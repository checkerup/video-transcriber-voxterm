"""Tests for the retag-speakers re-tagging path."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from video_transcriber.config import AppConfig, DiarizationConfig
from video_transcriber.retag_speakers import (
    assign_speakers,
    find_audio_for,
    parse_transcript,
    retag_speakers,
    _fmt_brackets,
    _render_srt,
    _render_txt,
    _render_vtt,
)


# ---------- parser tests ----------

def test_parse_txt_with_speaker_tags(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text(
        textwrap.dedent(
            """\
            [00:00:00.000] SPEAKER_07: hello world
            [00:00:03.500] SPEAKER_12: how are you
            [00:00:05.250] fine thanks
            """
        )
    )
    fmt, segs = parse_transcript(p)
    assert fmt == "txt"
    assert len(segs) == 3
    assert segs[0]["start"] == 0.0
    assert segs[1]["start"] == 3.5
    assert segs[2]["text"] == "fine thanks"
    # ends derived from next-start
    assert segs[0]["end"] == 3.5
    assert segs[1]["end"] == 5.25


def test_parse_srt(tmp_path):
    p = tmp_path / "a.srt"
    p.write_text(
        textwrap.dedent(
            """\
            1
            00:00:01,000 --> 00:00:03,500
            SPEAKER_03: hello

            2
            00:00:04,000 --> 00:00:06,000
            world
            """
        )
    )
    fmt, segs = parse_transcript(p)
    assert fmt == "srt"
    assert len(segs) == 2
    assert segs[0]["start"] == 1.0
    assert segs[0]["end"] == 3.5
    assert segs[0]["text"] == "hello"  # SPEAKER_ tag stripped
    assert segs[1]["text"] == "world"


def test_parse_vtt(tmp_path):
    p = tmp_path / "a.vtt"
    p.write_text(
        textwrap.dedent(
            """\
            WEBVTT

            00:00:01.000 --> 00:00:03.500
            SPEAKER_03: hello

            00:00:04.000 --> 00:00:06.000
            world
            """
        )
    )
    fmt, segs = parse_transcript(p)
    assert fmt == "vtt"
    assert len(segs) == 2
    assert segs[0]["text"] == "hello"


# ---------- assign_speakers tests ----------

def test_assign_speakers_max_overlap():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "a"},
        {"start": 2.0, "end": 4.0, "text": "b"},
        {"start": 5.0, "end": 7.0, "text": "c"},
    ]
    turns = [
        {"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"},
        {"start": 1.5, "end": 4.5, "speaker": "SPEAKER_01"},
        {"start": 6.0, "end": 8.0, "speaker": "SPEAKER_02"},
    ]
    tagged = assign_speakers(segments, turns)
    # seg0 (0-2): 1.5s with 00, 0.5s with 01 -> 00
    assert tagged[0]["speaker"] == "SPEAKER_00"
    # seg1 (2-4): fully inside 01 -> 01
    assert tagged[1]["speaker"] == "SPEAKER_01"
    # seg2 (5-7): 1s with 02 -> 02
    assert tagged[2]["speaker"] == "SPEAKER_02"


def test_assign_speakers_no_overlap_leaves_none():
    segments = [{"start": 100.0, "end": 101.0, "text": "x"}]
    turns = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
    tagged = assign_speakers(segments, turns)
    assert tagged[0]["speaker"] is None


# ---------- rendering tests ----------

def test_render_txt_roundtrip():
    tagged = [
        {"start": 0.0, "end": 2.0, "text": "hi", "speaker": "SPEAKER_00"},
        {"start": 2.5, "end": 4.0, "text": "yo", "speaker": None},
    ]
    out = _render_txt(tagged)
    assert "[00:00:00.000] SPEAKER_00: hi" in out
    assert "[00:00:02.500] yo" in out


def test_render_srt_includes_speaker():
    tagged = [
        {"start": 0.0, "end": 2.0, "text": "hi", "speaker": "SPEAKER_00"},
    ]
    out = _render_srt(tagged)
    assert "00:00:00,000 --> 00:00:02,000" in out
    assert "SPEAKER_00: hi" in out


def test_render_vtt_includes_speaker():
    tagged = [
        {"start": 0.0, "end": 2.0, "text": "hi", "speaker": "SPEAKER_00"},
    ]
    out = _render_vtt(tagged)
    assert out.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.000" in out
    assert "SPEAKER_00: hi" in out


def test_fmt_brackets_padding():
    assert _fmt_brackets(0) == "[00:00:00.000]"
    assert _fmt_brackets(3725.5) == "[01:02:05.500]"


# ---------- audio auto-discovery ----------

def test_find_audio_for_strips_retagged_suffix(tmp_path):
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"")
    transcript = tmp_path / "meeting.retagged.txt"
    transcript.write_text("")
    assert find_audio_for(transcript) == audio


# ---------- top-level orchestrator ----------

def test_retag_speakers_end_to_end(tmp_path):
    """Mocks diarize_audio and verifies a full retag round-trip."""
    transcript = tmp_path / "video.txt"
    transcript.write_text(
        "[00:00:00.000] SPEAKER_99: hello\n"
        "[00:00:03.000] SPEAKER_42: world\n"
    )
    audio = tmp_path / "video.mp3"
    audio.write_bytes(b"")

    fake_turns = [
        {"start": 0.0, "end": 2.5, "speaker": "SPEAKER_00"},
        {"start": 2.5, "end": 6.0, "speaker": "SPEAKER_01"},
    ]
    cfg = AppConfig(diarization=DiarizationConfig(enabled=True, backend="voxterm"))

    with patch("video_transcriber.retag_speakers.diarize_audio", return_value=fake_turns):
        out = retag_speakers(
            str(transcript),
            audio_path=None,
            config=cfg,
            num_speakers=2,
        )

    body = Path(out).read_text()
    assert out.name == "video.retagged.txt"
    # New labels should reflect the mocked turns, NOT the old SPEAKER_99/42
    assert "SPEAKER_00: hello" in body
    assert "SPEAKER_01: world" in body
    assert "SPEAKER_99" not in body
    assert "SPEAKER_42" not in body
