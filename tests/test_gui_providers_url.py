"""The GUI's Ollama default URL must be read at call time so values loaded
from .env (after gui.providers is imported) are honoured."""

import pytest

from gui.providers import default_url_for


def test_ollama_default_is_localhost(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_LLM_BACKEND_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert default_url_for("ollama") == "http://localhost:11434/v1"


def test_ollama_backend_url_wins_over_base_url(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_LLM_BACKEND_URL", "http://a:1/v1")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://b:2/v1")
    assert default_url_for("ollama") == "http://a:1/v1"


def test_ollama_falls_back_to_ollama_base_url(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_LLM_BACKEND_URL", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.3.146:8080/v1")
    assert default_url_for("ollama") == "http://192.168.3.146:8080/v1"


@pytest.mark.parametrize("provider,expected", [
    ("openai", "https://api.openai.com/v1"),
    ("google", None),
])
def test_other_providers_unchanged(monkeypatch, provider, expected):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://x/v1")
    assert default_url_for(provider) == expected
