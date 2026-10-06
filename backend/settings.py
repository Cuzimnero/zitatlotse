"""Local LLM settings. API keys live in the operating system credential store."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse


DATA_DIR = Path(__file__).parent / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"
SERVICE_NAME = "Zitatlotse"
PROVIDERS = {"none", "openai", "anthropic", "deepseek", "ollama"}
DEFAULT_MODELS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-sonnet-5-5",
    "deepseek": "deepseek-flash",
    "ollama": "gemma3:4b",
}


def _keyring():
    import keyring
    return keyring


def get_key(provider: str) -> str:
    if provider not in {"openai", "anthropic", "deepseek"}:
        return ""
    return _keyring().get_password(SERVICE_NAME, provider) or ""


def get_settings() -> dict:
    if SETTINGS_PATH.exists():
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    else:
        data = {}
    provider = data.get("provider", os.environ.get("ZQS_LLM_PROVIDER", "none"))
    if provider not in PROVIDERS:
        provider = "none"
    model = data.get("model") or os.environ.get("ZQS_LLM_MODEL") or DEFAULT_MODELS.get(provider, "")
    ollama_url = data.get("ollama_url", "http://127.0.0.1:11434")
    return {"provider": provider, "model": model, "ollama_url": ollama_url,
            "agentic_enabled": data.get("agentic_enabled", True) is True,
            "show_ai_activity": data.get("show_ai_activity", True) is True,
            "agentic_max_steps": max(1, min(6, int(data.get("agentic_max_steps", 3)))),
            "has_key": bool(get_key(provider)) if provider in {"openai", "anthropic", "deepseek"} else False}


def validate_ollama_url(value: str) -> str:
    ollama_url = str(value).strip().rstrip("/")
    parsed = urlparse(ollama_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path not in {"", "/"}:
        raise ValueError("Ollama-Adresse muss ein lokaler HTTP-Server sein")
    if parsed.port is None:
        raise ValueError("Ollama-Port fehlt")
    return ollama_url


def save_settings(data: dict) -> dict:
    current = get_settings()
    provider = str(data.get("provider", current["provider"]))
    if provider not in PROVIDERS:
        raise ValueError("Unbekannter Anbieter")
    model = str(data.get("model", current["model"] if provider == current["provider"] else "")).strip() or DEFAULT_MODELS.get(provider, "")
    if provider != "none" and not model:
        raise ValueError("Modellname fehlt")
    ollama_url = validate_ollama_url(data.get("ollama_url", current["ollama_url"]))
    agentic_enabled = data.get("agentic_enabled", current["agentic_enabled"])
    agentic_max_steps = data.get("agentic_max_steps", current["agentic_max_steps"])
    show_ai_activity = data.get("show_ai_activity", current["show_ai_activity"])
    if type(show_ai_activity) is not bool:
        raise ValueError("KI-Ablaufanzeige: Schalter prüfen")
    if type(agentic_enabled) is not bool or type(agentic_max_steps) is not int or not 1 <= agentic_max_steps <= 6:
        raise ValueError("Mehrstufige Suche: Schalter und Anzahl der Suchschritte (1–6) prüfen")
    key = str(data.get("api_key", "")).strip()
    if key and provider in {"openai", "anthropic", "deepseek"}:
        _keyring().set_password(SERVICE_NAME, provider, key)
    if data.get("clear_key") and provider in {"openai", "anthropic", "deepseek"}:
        try:
            _keyring().delete_password(SERVICE_NAME, provider)
        except _keyring().errors.PasswordDeleteError:
            pass
    DATA_DIR.mkdir(exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps({"provider": provider, "model": model,
                                          "ollama_url": ollama_url, "agentic_enabled": agentic_enabled,
                                          "agentic_max_steps": agentic_max_steps,
                                          "show_ai_activity": show_ai_activity}, ensure_ascii=False), encoding="utf-8")
    return get_settings()
