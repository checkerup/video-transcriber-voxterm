"""Tests for Telegram attachment behaviour (transcript / summary / audio / video)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from video_transcriber.config import AppConfig, TelegramConfig
from video_transcriber.notifier import (
    _attach_optional_files,
    _send_document,
    _send_transcript_as_text,
    send_notification,
)


def _mk_tg(**over) -> TelegramConfig:
    base = dict(bot_token="TOK", chat_id="1", send_transcript="none",
                send_summary_file=False, attach_audio=False, attach_video=False,
                max_attachment_mb=49)
    base.update(over)
    return TelegramConfig(**base)


# ---------- _send_document ----------

def test_send_document_uploads_file(tmp_path):
    f = tmp_path / "tr.txt"
    f.write_text("hello\nworld")
    with patch("video_transcriber.notifier.requests.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        _send_document("TOK", "1", f, "📝 Test", max_bytes=10 * 1024 * 1024)
        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert "/botTOK/sendDocument" in args[0]
        assert "document" in kwargs["files"]
        assert kwargs["data"]["chat_id"] == "1"
        assert kwargs["data"]["parse_mode"] == "HTML"
        assert "📝 Test" in kwargs["data"]["caption"]
        assert "tr.txt" in kwargs["data"]["caption"]


def test_send_document_skips_oversize(tmp_path):
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * 2048)
    with patch("video_transcriber.notifier.requests.post") as mock_post:
        _send_document("TOK", "1", f, "x", max_bytes=1024)
        assert not mock_post.called


def test_send_document_skips_missing(tmp_path):
    with patch("video_transcriber.notifier.requests.post") as mock_post:
        _send_document("TOK", "1", tmp_path / "nope.txt", "x", max_bytes=10**9)
        assert not mock_post.called


def test_send_document_soft_fails_on_network_error(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("x")
    with patch("video_transcriber.notifier.requests.post",
               side_effect=requests.ConnectionError("boom")):
        # must not raise
        _send_document("TOK", "1", f, "x", max_bytes=10**9)


# ---------- _send_transcript_as_text ----------

def test_send_transcript_as_text_chunks(tmp_path):
    f = tmp_path / "tr.txt"
    f.write_text("line\n" * 2000)  # >4000 chars -> at least 2 messages
    with patch("video_transcriber.notifier.requests.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        _send_transcript_as_text("TOK", "1", f)
        assert mock_post.call_count >= 2
        # first call must be sendMessage, not sendDocument
        url = mock_post.call_args_list[0][0][0]
        assert "/sendMessage" in url


def test_send_transcript_as_text_skips_empty(tmp_path):
    f = tmp_path / "tr.txt"
    f.write_text("   \n  ")
    with patch("video_transcriber.notifier.requests.post") as mock_post:
        _send_transcript_as_text("TOK", "1", f)
        assert not mock_post.called


# ---------- _attach_optional_files dispatcher ----------

def test_attach_files_mode_file_only_transcript(tmp_path):
    tr = tmp_path / "out.txt"; tr.write_text("hi")
    sm = tmp_path / "sum.txt"; sm.write_text("s")
    au = tmp_path / "a.mp3"; au.write_text("a")
    vi = tmp_path / "v.mp4"; vi.write_text("v")
    cfg = AppConfig(telegram=_mk_tg(send_transcript="file"))
    with patch("video_transcriber.notifier._send_document") as mock_doc, \
         patch("video_transcriber.notifier._send_transcript_as_text") as mock_txt:
        _attach_optional_files(cfg, transcript_path=tr, summary_path=sm,
                               audio_path=au, video_path=vi)
        assert mock_doc.call_count == 1
        assert mock_doc.call_args.args[2] == tr
        mock_txt.assert_not_called()


def test_attach_files_all_switches_on(tmp_path):
    tr = tmp_path / "out.txt"; tr.write_text("hi")
    sm = tmp_path / "sum.txt"; sm.write_text("s")
    au = tmp_path / "a.mp3"; au.write_text("a")
    vi = tmp_path / "v.mp4"; vi.write_text("v")
    cfg = AppConfig(telegram=_mk_tg(send_transcript="file",
                                    send_summary_file=True,
                                    attach_audio=True, attach_video=True))
    with patch("video_transcriber.notifier._send_document") as mock_doc:
        _attach_optional_files(cfg, transcript_path=tr, summary_path=sm,
                               audio_path=au, video_path=vi)
        assert mock_doc.call_count == 4
        sent_paths = [c.args[2] for c in mock_doc.call_args_list]
        assert tr in sent_paths and sm in sent_paths
        assert au in sent_paths and vi in sent_paths


def test_attach_files_text_mode_routes_to_text(tmp_path):
    tr = tmp_path / "out.txt"; tr.write_text("hi")
    cfg = AppConfig(telegram=_mk_tg(send_transcript="text"))
    with patch("video_transcriber.notifier._send_document") as mock_doc, \
         patch("video_transcriber.notifier._send_transcript_as_text") as mock_txt:
        _attach_optional_files(cfg, transcript_path=tr, summary_path=None,
                               audio_path=None, video_path=None)
        mock_doc.assert_not_called()
        mock_txt.assert_called_once()


def test_attach_files_none_mode_sends_nothing(tmp_path):
    tr = tmp_path / "out.txt"; tr.write_text("hi")
    cfg = AppConfig(telegram=_mk_tg(send_transcript="none"))
    with patch("video_transcriber.notifier._send_document") as mock_doc, \
         patch("video_transcriber.notifier._send_transcript_as_text") as mock_txt:
        _attach_optional_files(cfg, transcript_path=tr, summary_path=None,
                               audio_path=None, video_path=None)
        mock_doc.assert_not_called()
        mock_txt.assert_not_called()


# ---------- end-to-end via send_notification ----------

def test_send_notification_invokes_attachments_on_success(tmp_path):
    tr = tmp_path / "out.txt"; tr.write_text("hi")
    cfg = AppConfig(telegram=_mk_tg(send_transcript="file"))
    with patch("video_transcriber.notifier.requests.post") as mock_post, \
         patch("video_transcriber.notifier._attach_optional_files") as mock_attach:
        mock_post.return_value.raise_for_status.return_value = None
        send_notification(cfg, video_path=None, audio_path=None,
                          transcript_path=tr)
        mock_attach.assert_called_once()


def test_send_notification_skips_attachments_on_error(tmp_path):
    tr = tmp_path / "out.txt"; tr.write_text("hi")
    cfg = AppConfig(telegram=_mk_tg(send_transcript="file"))
    with patch("video_transcriber.notifier.requests.post") as mock_post, \
         patch("video_transcriber.notifier._attach_optional_files") as mock_attach:
        mock_post.return_value.raise_for_status.return_value = None
        send_notification(cfg, video_path=None, audio_path=None,
                          transcript_path=tr, error="boom")
        mock_attach.assert_not_called()
