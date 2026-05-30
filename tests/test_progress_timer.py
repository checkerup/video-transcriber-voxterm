"""Tests for ProgressTimer."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from video_transcriber.progress_timer import ProgressTimer, format_hms


def test_format_hms_basic():
    assert format_hms(0) == "00:00:00"
    assert format_hms(59) == "00:00:59"
    assert format_hms(60) == "00:00:60" or format_hms(60) == "00:01:00"
    # canonicalise: 60s should round to 00:01:00
    assert format_hms(60.0) == "00:01:00"
    assert format_hms(3661) == "01:01:01"
    assert format_hms(None) == "--:--:--"
    assert format_hms(-1) == "--:--:--"


def test_stage_context_manager_records_elapsed():
    t = ProgressTimer()
    with t.stage("alpha"):
        time.sleep(0.02)
    elapsed = t.stage_elapsed("alpha")
    assert elapsed is not None
    assert elapsed >= 0.015  # generous lower bound


def test_multiple_stages_aggregate():
    t = ProgressTimer()
    with t.stage("a"):
        time.sleep(0.01)
    with t.stage("b"):
        time.sleep(0.01)
    with t.stage("a"):  # second invocation
        time.sleep(0.01)
    # 'a' should sum both invocations
    a_total = t.stage_elapsed("a")
    b_total = t.stage_elapsed("b")
    assert a_total >= 0.018
    assert b_total >= 0.008
    assert b_total < a_total


def test_estimate_eta_proportional():
    t = ProgressTimer()
    t.begin("stage")
    # fake-elapsed by sleeping a bit
    time.sleep(0.05)
    eta_half = t.estimate_eta(0.5, stage_name="stage")
    # at 50% progress, ETA should be roughly equal to elapsed-so-far
    elapsed = t.stage_elapsed("stage")
    assert eta_half is not None
    assert abs(eta_half - elapsed) < 0.02  # within ~20ms tolerance


def test_estimate_eta_edge_cases():
    t = ProgressTimer()
    t.begin("x")
    assert t.estimate_eta(0.0, stage_name="x") is None
    assert t.estimate_eta(1.0, stage_name="x") is None
    assert t.estimate_eta(-0.1, stage_name="x") is None
    assert t.estimate_eta(1.5, stage_name="x") is None


def test_format_progress_contains_pct_and_eta():
    t = ProgressTimer()
    t.begin("transcribe")
    time.sleep(0.01)
    line = t.format_progress("transcribe", 0.5)
    assert "50.0%" in line
    assert "elapsed" in line
    assert "ETA" in line


def test_format_summary_includes_speedup():
    t = ProgressTimer()
    with t.stage("transcribe"):
        time.sleep(0.05)
    # pretend the source was 10s long while we took ~50ms — speedup ~200x
    summary = t.format_summary(source_duration_s=10.0)
    assert "Processed in" in summary
    assert "speedup" in summary
    assert "stages" in summary


def test_write_json(tmp_path: Path):
    t = ProgressTimer()
    with t.stage("alpha"):
        time.sleep(0.01)
    with t.stage("beta"):
        time.sleep(0.01)
    out = tmp_path / "deep" / "nested" / "report.timing.json"
    written = t.write_json(out, source_duration_s=1.0)
    assert written.exists()
    data = json.loads(written.read_text())
    assert data["total_elapsed_seconds"] > 0
    assert isinstance(data["stages"], list)
    names = [s["name"] for s in data["stages"]]
    assert names == ["alpha", "beta"]
    assert "speedup_vs_source" in data
    assert data["source_duration_seconds"] == 1.0
