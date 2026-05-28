"""Tests for the GUI's Python-side JsApi + JobManager.

These cover everything that's testable without actually opening a window:
config round-trip, history scanning, transcript read, job enqueue/cancel,
override mapping, and the partial-update YAML editor.
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from video_transcriber.config import AppConfig, DiarizationConfig, load_config
from video_transcriber.webui.api import JsApi
from video_transcriber.webui.jobs import JobManager, JobState


# ---------- fixtures ----------

@pytest.fixture
def project(tmp_path: Path):
    """Set up a fake project root with config.yaml + output folder."""
    root = tmp_path / "project"
    root.mkdir()
    out = root / "out"
    out.mkdir()
    cfg_path = root / "config.yaml"
    cfg_path.write_text(textwrap.dedent(f"""\
        watch:
          folder: {root / 'incoming'}
        processing:
          output_folder: {out}
        transcription:
          model_size: tiny
          language: ru
        diarization:
          enabled: false
          backend: voxterm
          cluster_threshold: 0.7
    """))
    cfg = load_config(config_path=cfg_path)
    api = JsApi(config=cfg, config_path=cfg_path, project_root=root)
    return {"root": root, "out": out, "cfg_path": cfg_path, "api": api}


# ---------- meta ----------

def test_ping(project):
    p = project["api"].ping()
    assert p["ok"] is True
    assert "python" in p
    assert "os" in p


# ---------- config round-trip ----------

def test_get_config_returns_dict(project):
    d = project["api"].get_config()
    assert d["diarization"]["enabled"] is False
    assert d["diarization"]["backend"] == "voxterm"
    assert d["transcription"]["model_size"] == "tiny"


def test_get_config_yaml_returns_raw_text(project):
    raw = project["api"].get_config_yaml()
    assert "watch:" in raw
    assert "diarization" in raw


def test_save_config_yaml_round_trip(project):
    api = project["api"]
    new_yaml = api.get_config_yaml().replace("model_size: tiny", "model_size: medium")
    res = api.save_config_yaml(new_yaml)
    assert res["ok"] is True
    assert res["config"]["transcription"]["model_size"] == "medium"
    assert api.config.transcription.model_size == "medium"


def test_save_config_yaml_invalid_returns_error(project):
    api = project["api"]
    res = api.save_config_yaml("this is: : not: valid: yaml: :")
    assert res["ok"] is False
    assert "error" in res


def test_update_config_dotted_patch(project):
    api = project["api"]
    res = api.update_config({
        "diarization.enabled": True,
        "diarization.num_speakers": 5,
        "diarization.cluster_threshold": 0.65,
    })
    assert res["ok"] is True
    assert res["config"]["diarization"]["enabled"] is True
    assert res["config"]["diarization"]["num_speakers"] == 5
    # cluster_threshold ends up as float
    assert abs(res["config"]["diarization"]["cluster_threshold"] - 0.65) < 1e-6
    # the YAML on disk has the patched values
    raw = project["cfg_path"].read_text()
    assert "num_speakers: 5" in raw


# ---------- history scanning ----------

def test_list_history_empty(project):
    assert project["api"].list_history() == []


def test_list_history_finds_timing_reports(project):
    out = project["out"]
    # fake a finished run
    (out / "my_video.txt").write_text("hello world")
    (out / "my_video.timing.json").write_text(json.dumps({
        "total_elapsed_human": "00:42:15",
        "source_duration_seconds": 5340.0,
        "speedup_vs_source": 2.1,
        "stages": [{"name": "transcribe", "elapsed_human": "00:41:55"}],
    }))
    items = project["api"].list_history()
    assert len(items) == 1
    h = items[0]
    assert h["name"] == "my_video"
    assert h["total_elapsed_human"] == "00:42:15"
    assert h["transcripts"] and h["transcripts"][0].endswith("my_video.txt")
    assert h["stages"][0]["name"] == "transcribe"


def test_read_transcript_returns_text(project):
    p = project["out"] / "x.txt"
    p.write_text("hello\nworld\n")
    res = project["api"].read_transcript(str(p))
    assert res["ok"] is True
    assert res["text"].startswith("hello")
    assert res["truncated"] is False


def test_read_transcript_truncates(project):
    p = project["out"] / "big.txt"
    p.write_text("x" * 1000)
    res = project["api"].read_transcript(str(p), max_chars=100)
    assert res["ok"] is True
    assert len(res["text"]) == 100
    assert res["truncated"] is True


def test_read_transcript_missing(project):
    res = project["api"].read_transcript(str(project["out"] / "nope.txt"))
    assert res["ok"] is False


# ---------- job manager ----------

def test_start_process_rejects_missing_file(project):
    res = project["api"].start_process("/no/such/file.mp4")
    assert res["ok"] is False


def test_start_process_enqueues(project, tmp_path):
    f = tmp_path / "fake.mp4"
    f.write_bytes(b"x" * 10)
    # never let the worker actually call process_file
    with patch("video_transcriber.webui.jobs.JobManager._execute"):
        res = project["api"].start_process(str(f), {"diarize": False})
        assert res["ok"] is True
        assert "job_id" in res
        # let the worker thread schedule + execute the patched _execute
        time.sleep(0.2)
        snap = project["api"].get_job(res["job_id"])
        assert snap is not None
        # status will be 'running' (patched _execute returns immediately
        # without flipping the status to done — that's fine for the test)


def test_cancel_job_unknown_returns_false(project):
    assert project["api"].cancel_job("does-not-exist")["ok"] is False


def test_list_jobs_returns_list(project):
    assert isinstance(project["api"].list_jobs(), list)


# ---------- override mapping ----------

def test_apply_overrides_diarization_fields(project):
    jm = JobManager(project["api"].config)
    cfg2 = jm._apply_overrides({
        "diarize": True,
        "num_speakers": 4,
        "cluster_threshold": 0.55,
        "diar_backend": "pyannote",
        "diar_model": "eres2net",
        "model_size": "medium",
    })
    assert cfg2.diarization.enabled is True
    assert cfg2.diarization.num_speakers == 4
    assert abs(cfg2.diarization.cluster_threshold - 0.55) < 1e-6
    assert cfg2.diarization.backend == "pyannote"
    assert cfg2.diarization.model == "eres2net"
    assert cfg2.transcription.model_size == "medium"
    # original config untouched
    assert project["api"].config.diarization.enabled is False


def test_apply_overrides_summarize_translate(project):
    jm = JobManager(project["api"].config)
    cfg2 = jm._apply_overrides({"summarize": True, "translate_to": "en"})
    assert cfg2.summarization.enabled is True
    assert cfg2.transcription.translate_to == "en"


# ---------- snapshot shape ----------

def test_jobstate_snapshot_round_trip():
    s = JobState(job_id="abc", file_path="/tmp/v.mp4", kind="process",
                 status="running", stage="transcribe",
                 progress=0.5, elapsed_seconds=42.0, eta_seconds=42.0)
    snap = s.snapshot()
    assert snap["job_id"] == "abc"
    assert snap["status"] == "running"
    assert snap["progress"] == 0.5
    assert snap["elapsed_human"] == "00:00:42"
    assert snap["eta_human"] == "00:00:42"
    assert isinstance(snap["log_tail"], list)


# ---------- send_telegram_test ----------

def test_send_telegram_test_not_configured(tmp_path):
    from video_transcriber.config import AppConfig, TelegramConfig
    from video_transcriber.webui.api import JsApi
    cfg = AppConfig()
    api = JsApi(cfg, tmp_path / "config.yaml", tmp_path)
    res = api.send_telegram_test()
    assert res["ok"] is False
    assert "configured" in res["error"].lower()


def test_send_telegram_test_calls_telegram(tmp_path):
    from unittest.mock import patch
    from video_transcriber.config import AppConfig, TelegramConfig
    from video_transcriber.webui.api import JsApi
    cfg = AppConfig(telegram=TelegramConfig(bot_token="TOK", chat_id="42"))
    api = JsApi(cfg, tmp_path / "config.yaml", tmp_path)
    with patch("requests.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        res = api.send_telegram_test()
        assert res["ok"] is True
        url = mock_post.call_args.args[0]
        assert "/botTOK/sendMessage" in url
        assert mock_post.call_args.kwargs["json"]["chat_id"] == "42"
