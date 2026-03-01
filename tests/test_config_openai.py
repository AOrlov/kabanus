import pytest

from src import config


def _reset_settings_cache() -> None:
    config._SETTINGS_CACHE = None
    config._SETTINGS_CACHE_TS = 0.0


def test_openai_provider_requires_openai_api_key(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _reset_settings_cache()

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY|OPENAI_AUTH_JSON_PATH|OpenAI mode requires"):
        config.get_settings(force=True)


def test_openai_provider_defaults(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_LOW_COST_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_REACTION_MODEL", raising=False)
    _reset_settings_cache()

    settings = config.get_settings(force=True)
    assert settings.model_provider == "openai"
    assert settings.openai_model == "gpt-5.3-codex"
    assert settings.openai_low_cost_model == settings.openai_model
    assert settings.openai_reaction_model == settings.openai_low_cost_model
    assert settings.openai_refresh_url == "https://auth.openai.com/oauth/token"
    assert settings.openai_codex_base_url == "https://chatgpt.com/backend-api"
    assert settings.openai_codex_default_model == "gpt-5.3-codex"


def test_openai_provider_accepts_auth_json_without_api_key(monkeypatch, tmp_path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text('{"refresh_token":"r1"}', encoding="utf-8")
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_AUTH_JSON_PATH", str(auth_file))
    _reset_settings_cache()

    settings = config.get_settings(force=True)
    assert settings.openai_auth_json_path == str(auth_file)
    assert settings.openai_model == "gpt-5.3-codex"
    assert settings.openai_low_cost_model == "gpt-5.3-codex"
    assert settings.openai_reaction_model == "gpt-5.3-codex"
