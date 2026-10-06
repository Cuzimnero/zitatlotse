"""Provider discovery with useful, explicitly unverified offline suggestions."""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlencode

SUGGESTIONS = {
    "openai": [("gpt-4.1-mini", "GPT-4.1 Mini"), ("gpt-4.1", "GPT-4.1"), ("gpt-5-mini", "GPT-5 Mini")],
    "anthropic": [("claude-sonnet-5-5", "Claude Sonnet 5.5"), ("claude-opus-5-5", "Claude Opus 5.5"),
                  ("claude-fable-5-1", "Claude Fable 5.1"), ("claude-haiku-4-5-20251001", "Claude Haiku 4.5")],
}


def suggestions(provider, reason):
    return {"provider": provider, "source": "suggestions", "reason": reason,
            "models": [{"id": model, "label": label + " (" + model + ")"}
                       for model, label in SUGGESTIONS[provider]]}


def chat_model(model):
    # The endpoint also lists image, audio, embedding and other specialized models.
    base = model.split(":")[1] if model.startswith("ft:") and ":" in model else model
    return (base.startswith(("gpt-", "chatgpt-", "chat-latest")) or bool(re.match(r"^o[1-9]", base))) and not any(
        token in base for token in ("image", "audio", "realtime", "transcribe", "tts", "instruct", "search-preview"))


def discover_models(data, get_key, validate_ollama_url):
    provider = str(data.get("provider", ""))
    headers = {}
    if provider == "ollama":
        url = validate_ollama_url(data.get("ollama_url", "http://127.0.0.1:11434")) + "/api/tags"
    elif provider in {"openai", "anthropic", "deepseek"}:
        key = str(data.get("api_key", "")).strip() or get_key(provider)
        if not key:
            if provider in SUGGESTIONS:
                return suggestions(provider, "no_key")
            raise ValueError("Bitte zuerst einen API-Schlüssel eingeben oder speichern")
        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/models"
            headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        else:
            url = "https://api.openai.com/v1/models" if provider == "openai" else "https://api.deepseek.com/models"
            headers["Authorization"] = "Bearer " + key
    else:
        raise ValueError("Bitte einen Anbieter wählen")
    models, seen, cursors = [], set(), set()
    try:
        # Claude defaults to twenty entries. Follow cursors, including on accounts
        # with legacy releases; never silently present only the first page.
        for _ in range(20):
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8) as response:
                listing = json.load(response)
            for entry in listing.get("models" if provider == "ollama" else "data", []):
                model = str(entry.get("name" if provider == "ollama" else "id", "")).strip()
                if not model or len(model) > 150 or model in seen or (provider == "openai" and not chat_model(model)):
                    continue
                seen.add(model)
                display = str(entry.get("name" if provider == "deepseek" else "display_name", "") or model).strip()[:150]
                models.append({"id": model, "label": display + " (" + model + ")" if display != model else model})
            if provider != "anthropic" or not listing.get("has_more"):
                break
            cursor = listing.get("last_id")
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("Ungültige Seitennavigation der Modellliste")
            cursors.add(cursor)
            url = "https://api.anthropic.com/v1/models?" + urlencode({"after_id": cursor, "limit": 1000})
        else:
            raise ValueError("Modellliste enthält zu viele Seiten")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        if provider in SUGGESTIONS:
            return suggestions(provider, "key_rejected" if getattr(exc, "code", 0) in {401, 403} else "unavailable")
        if getattr(exc, "code", 0) == 401:
            raise ValueError(provider + ": API-Schlüssel wurde abgelehnt") from None
        if isinstance(exc, urllib.error.HTTPError):
            raise ValueError(provider + f": Modellliste nicht verfügbar (HTTP {exc.code})") from None
        raise ValueError("Ollama ist nicht erreichbar" if provider == "ollama" else provider + " ist nicht erreichbar") from None
    if not models and provider in SUGGESTIONS:
        return suggestions(provider, "empty")
    models.sort(key=lambda item: item["id"].casefold())
    return {"provider": provider, "models": models, "source": "installed" if provider == "ollama" else "api"}
