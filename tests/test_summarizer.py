import pytest
from unittest.mock import patch, MagicMock
import requests

from video_transcriber.config import AppConfig, SummarizationConfig
from video_transcriber.summarizer import generate_summary

def test_generate_summary_disabled():
    config = AppConfig(
        summarization=SummarizationConfig(
            enabled=False,
            api_key="test_key"
        )
    )
    result = generate_summary("some transcript text", config)
    assert result == ""

def test_generate_summary_missing_api_key():
    config = AppConfig(
        summarization=SummarizationConfig(
            enabled=True,
            api_key=""
        )
    )
    result = generate_summary("some transcript text", config)
    assert result == ""

@patch("requests.post")
def test_generate_summary_success(mock_post):
    config = AppConfig(
        summarization=SummarizationConfig(
            enabled=True,
            provider="gemini",
            api_key="test_key",
            model="gemini-1.5-flash"
        )
    )
    
    # Mock successful response from Gemini API
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "This is the mocked summary from Gemini."
                        }
                    ]
                }
            }
        ]
    }
    mock_post.return_value = mock_response

    transcript_text = "Hello world transcription text"
    result = generate_summary(transcript_text, config)

    assert result == "This is the mocked summary from Gemini."
    
    # Verify mock call details
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    url = args[0]
    assert "gemini-1.5-flash" in url
    assert "test_key" in url
    
    json_data = kwargs["json"]
    assert "contents" in json_data
    prompt_text = json_data["contents"][0]["parts"][0]["text"]
    assert transcript_text in prompt_text

@patch("requests.post")
def test_generate_summary_http_error(mock_post):
    config = AppConfig(
        summarization=SummarizationConfig(
            enabled=True,
            provider="gemini",
            api_key="test_key"
        )
    )
    
    # Mock failing response
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = requests.HTTPError("Server Error")
    mock_post.return_value = mock_response

    result = generate_summary("transcript", config)
    assert result == ""


@patch("requests.post")
def test_generate_summary_custom_prompt(mock_post):
    config = AppConfig(
        summarization=SummarizationConfig(
            enabled=True,
            provider="gemini",
            api_key="test_key",
            model="gemini-custom-model",
            prompt="Summarize in one sentence: {text}"
        )
    )
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "Single sentence summary."
                        }
                    ]
                }
            }
        ]
    }
    mock_post.return_value = mock_response

    transcript_text = "Detailed transcription text here."
    result = generate_summary(transcript_text, config)

    assert result == "Single sentence summary."
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    url = args[0]
    assert "gemini-custom-model" in url
    
    json_data = kwargs["json"]
    prompt_text = json_data["contents"][0]["parts"][0]["text"]
    assert prompt_text == "Summarize in one sentence: Detailed transcription text here."

"""Tests for the multi-provider summarizer."""

from unittest.mock import patch, MagicMock

import pytest

from video_transcriber.config import AppConfig, SummarizationConfig
from video_transcriber.summarizer import generate_summary, _build_prompt, _language_clause


def _make_cfg(provider="gemini", api_key="k", model="m", api_base=""):
    return AppConfig(summarization=SummarizationConfig(
        enabled=True, provider=provider, api_key=api_key, model=model, api_base=api_base,
    ))


def test_disabled_returns_empty():
    cfg = _make_cfg()
    cfg.summarization.enabled = False
    assert generate_summary("hi", cfg) == ""


def test_empty_text_returns_empty():
    assert generate_summary("", _make_cfg()) == ""


def test_no_api_key_returns_empty():
    cfg = _make_cfg(api_key="")
    assert generate_summary("hi", cfg) == ""


@patch("video_transcriber.summarizer.requests.post")
def test_gemini_provider(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"candidates": [{"content": {"parts": [{"text": "summary OK"}]}}]},
    )
    mock_post.return_value.raise_for_status = MagicMock()
    out = generate_summary("hello", _make_cfg("gemini"))
    assert out == "summary OK"
    url = mock_post.call_args[0][0]
    assert "generativelanguage.googleapis.com" in url


@patch("video_transcriber.summarizer.requests.post")
def test_openai_provider(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"choices": [{"message": {"content": "openai summary"}}]},
    )
    mock_post.return_value.raise_for_status = MagicMock()
    out = generate_summary("hi", _make_cfg("openai"))
    assert out == "openai summary"
    assert "api.openai.com" in mock_post.call_args[0][0]


@patch("video_transcriber.summarizer.requests.post")
def test_anthropic_provider(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"content": [{"type": "text", "text": "claude summary"}]},
    )
    mock_post.return_value.raise_for_status = MagicMock()
    out = generate_summary("hi", _make_cfg("anthropic"))
    assert out == "claude summary"
    assert "api.anthropic.com" in mock_post.call_args[0][0]


@patch("video_transcriber.summarizer.requests.post")
def test_openrouter_provider(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"choices": [{"message": {"content": "router summary"}}]},
    )
    mock_post.return_value.raise_for_status = MagicMock()
    out = generate_summary("hi", _make_cfg("openrouter"))
    assert out == "router summary"
    assert "openrouter.ai" in mock_post.call_args[0][0]


@patch("video_transcriber.summarizer.requests.post")
def test_custom_provider_requires_api_base(mock_post):
    cfg = _make_cfg("custom", api_base="")
    assert generate_summary("hi", cfg) == ""
    mock_post.assert_not_called()


@patch("video_transcriber.summarizer.requests.post")
def test_custom_provider_uses_api_base(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"choices": [{"message": {"content": "custom summary"}}]},
    )
    mock_post.return_value.raise_for_status = MagicMock()
    cfg = _make_cfg("custom", api_base="https://my.llm.host/v1", api_key="k")
    out = generate_summary("hi", cfg)
    assert out == "custom summary"
    assert mock_post.call_args[0][0] == "https://my.llm.host/v1/chat/completions"


def test_unknown_provider_returns_empty():
    assert generate_summary("hi", _make_cfg("does-not-exist")) == ""


def test_build_prompt_uses_default_when_empty():
    cfg = _make_cfg()
    sys_p, user_p = _build_prompt("transcript text", cfg)
    assert "expert summarizer" in sys_p.lower()
    assert "transcript text" in user_p


def test_build_prompt_with_text_placeholder():
    cfg = _make_cfg()
    cfg.summarization.prompt = "Summarize:\n{text}"
    sys_p, user_p = _build_prompt("hello", cfg)
    assert user_p.startswith("Summarize:")
    assert "hello" in user_p


def test_language_clause_known():
    assert "Russian" in _language_clause("ru")
    assert "Chinese" in _language_clause("zh")


def test_language_clause_auto():
    assert "same language" in _language_clause("auto").lower()
    assert "same language" in _language_clause("").lower()
