"""Multi-provider LLM summarization.

Supported providers (configured via ``summarization.provider``):

    gemini      - Google Generative Language API (default).
    openai      - OpenAI Chat Completions API.
    anthropic   - Anthropic Messages API.
    openrouter  - OpenRouter (OpenAI-compatible).
    custom      - Any OpenAI-compatible endpoint via ``summarization.api_base``.

All providers read ``summarization.{api_key, model, prompt, system_prompt,
temperature, max_output_tokens, language}`` from the config. The legacy
single-provider Gemini behaviour is preserved as the default.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from video_transcriber.config import AppConfig

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "You are an expert summarizer. Produce a detailed summary plus a chapter-style "
    "table of contents for the given transcript. Always respond in Markdown."
)

_DEFAULT_USER_PROMPT = (
    "Make a detailed summary (summary) and chapter-style table of contents for the following "
    "transcript. Format the answer in Markdown. {language_clause}\n\nTranscript:\n\n{text}"
)


def _language_clause(language: str) -> str:
    code = (language or "").lower().strip()
    if not code or code == "auto":
        return "Respond in the same language as the transcript."
    names = {
        "ru": "Russian", "en": "English", "zh": "Chinese", "es": "Spanish",
        "fr": "French", "de": "German", "ja": "Japanese", "ko": "Korean",
        "pt": "Portuguese", "it": "Italian", "tr": "Turkish",
    }
    return f"Respond in {names.get(code, code)}."


def _build_prompt(text: str, config: AppConfig) -> tuple[str, str]:
    s = config.summarization
    sys_prompt = (s.system_prompt or "").strip() or _DEFAULT_SYSTEM_PROMPT
    user_template = (s.prompt or "").strip() or _DEFAULT_USER_PROMPT
    lang_clause = _language_clause(getattr(s, "language", "auto"))
    if "{text}" in user_template:
        try:
            user_prompt = user_template.format(text=text, language_clause=lang_clause)
        except (KeyError, IndexError):
            user_prompt = user_template.replace("{text}", text)
    else:
        user_prompt = f"{user_template}\n\n{lang_clause}\n\n{text}"
    return sys_prompt, user_prompt


def generate_summary(text: str, config: AppConfig) -> str:
    """Dispatch to the configured provider and return the markdown summary, or "" on failure."""
    if not config.summarization.enabled:
        logger.debug("Summarization is disabled in config.")
        return ""
    if not (text or "").strip():
        logger.warning("Empty transcription text. Skipping summarization.")
        return ""
    api_key = (config.summarization.api_key or "").strip()
    provider = (config.summarization.provider or "gemini").lower().strip()
    if not api_key and provider != "custom":
        logger.warning("API key for provider %r is missing. Skipping summarization.", provider)
        return ""
    sys_prompt, user_prompt = _build_prompt(text, config)
    try:
        if provider == "gemini":
            return _call_gemini(api_key, sys_prompt, user_prompt, config)
        if provider == "openai":
            return _call_openai_compatible("https://api.openai.com/v1", api_key, sys_prompt, user_prompt, config)
        if provider == "openrouter":
            return _call_openai_compatible("https://openrouter.ai/api/v1", api_key, sys_prompt, user_prompt, config)
        if provider == "anthropic":
            return _call_anthropic(api_key, sys_prompt, user_prompt, config)
        if provider == "custom":
            base = (config.summarization.api_base or "").strip()
            if not base:
                logger.warning("provider=custom requires summarization.api_base; skipping.")
                return ""
            return _call_openai_compatible(base.rstrip("/"), api_key, sys_prompt, user_prompt, config)
        logger.warning("Unknown LLM provider: %r. Skipping summarization.", provider)
        return ""
    except Exception as e:
        logger.exception("Error calling %s for summarization: %s", provider, e)
        return ""


def _call_gemini(api_key: str, sys_prompt: str, user_prompt: str, config: AppConfig) -> str:
    s = config.summarization
    model = s.model or "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": float(s.temperature),
            "maxOutputTokens": int(s.max_output_tokens),
        },
    }
    if sys_prompt:
        payload["systemInstruction"] = {"parts": [{"text": sys_prompt}]}
    resp = requests.post(url, json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            t = parts[0].get("text", "").strip()
            if t:
                logger.info("Gemini summary OK (%d chars).", len(t))
                return t
    logger.warning("Unexpected Gemini response: %s", data)
    return ""


def _call_openai_compatible(base_url: str, api_key: str, sys_prompt: str, user_prompt: str, config: AppConfig) -> str:
    s = config.summarization
    model = s.model or "gpt-4o-mini"
    url = f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    messages = []
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": user_prompt})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(s.temperature),
        "max_tokens": int(s.max_output_tokens),
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices", [])
    if choices:
        msg = choices[0].get("message", {})
        t = (msg.get("content") or "").strip()
        if t:
            logger.info("OpenAI-compatible summary OK (%d chars) via %s.", len(t), base_url)
            return t
    logger.warning("Unexpected response from %s: %s", base_url, data)
    return ""


def _call_anthropic(api_key: str, sys_prompt: str, user_prompt: str, config: AppConfig) -> str:
    s = config.summarization
    model = s.model or "claude-3-5-sonnet-20241022"
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": int(s.max_output_tokens),
        "temperature": float(s.temperature),
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if sys_prompt:
        payload["system"] = sys_prompt
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    content = data.get("content", [])
    if content:
        parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        t = "\n".join(p for p in parts if p).strip()
        if t:
            logger.info("Anthropic summary OK (%d chars).", len(t))
            return t
    logger.warning("Unexpected Anthropic response: %s", data)
    return ""
