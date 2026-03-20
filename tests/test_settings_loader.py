import pytest

from src import config, settings_loader
from src.settings_models import (
    AISettings,
    GeminiSettings,
    ModelSpec,
    OpenAISettings,
    Settings,
)

# Contract note:
# - Stable: config/settings env parsing and validation behavior.
# - May change: facade-level cache reset internals and module globals.


def _reset_config_cache() -> None:
    config.reset_settings_cache()


def _set_base_openai_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_config_reexports_settings_models() -> None:
    assert config.Settings is Settings
    assert config.ModelSpec is ModelSpec
    assert config.AISettings is AISettings
    assert config.OpenAISettings is OpenAISettings
    assert config.GeminiSettings is GeminiSettings


def test_settings_loader_matches_config_facade_behavior(monkeypatch) -> None:
    _set_base_openai_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setenv("BOT_ALIASES", "Kaban, Helper")
    monkeypatch.setenv("TELEGRAM_USE_MESSAGE_DRAFTS", "true")
    monkeypatch.setenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
    monkeypatch.setenv("REACTION_CONTEXT_TURNS", "5")
    monkeypatch.setenv("AI_PROVIDER_AUDIO_TRANSCRIPTION", "gemini")
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    _reset_config_cache()

    loader_settings = settings_loader.get_settings(
        force=True,
        reload_env_func=lambda: None,
    )
    facade_settings = config.get_settings(force=False)

    assert loader_settings == facade_settings
    assert loader_settings is facade_settings
    assert loader_settings.bot_aliases == ["kaban", "helper"]
    assert loader_settings.telegram_use_message_drafts is True
    assert loader_settings.reaction_context_turns == 5
    assert loader_settings.ai.openai.api_key == "openai-key"
    assert loader_settings.ai.gemini.api_key == "gem-key"
    assert loader_settings.ai.routing.text_generation == "openai"
    assert loader_settings.ai.routing.audio_transcription == "gemini"
    assert loader_settings.ai.openai.transcription_model == "gpt-4o-transcribe"


@pytest.mark.parametrize(
    ("env_updates", "removed_env", "error_pattern"),
    [
        (
            {"MODEL_PROVIDER": "unsupported"},
            [],
            "MODEL_PROVIDER must be either 'openai' or 'gemini'",
        ),
        (
            {"AI_PROVIDER_AUDIO_TRANSCRIPTION": "gemini"},
            ["GEMINI_API_KEY"],
            "Gemini is routed for audio_transcription",
        ),
        (
            {"AI_PROVIDER_STREAMING_TEXT_GENERATION": "bad-provider"},
            [],
            "AI_PROVIDER_STREAMING_TEXT_GENERATION must be either 'openai' or 'gemini'",
        ),
        (
            {},
            ["OPENAI_API_KEY", "OPENAI_AUTH_JSON_PATH"],
            "OPENAI_API_KEY or OPENAI_AUTH_JSON_PATH is missing",
        ),
    ],
)
def test_settings_loader_validation_matches_config_contract(
    monkeypatch,
    env_updates,
    removed_env,
    error_pattern,
) -> None:
    _set_base_openai_env(monkeypatch)
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    for env_name, env_value in env_updates.items():
        monkeypatch.setenv(env_name, env_value)
    for env_name in removed_env:
        monkeypatch.delenv(env_name, raising=False)
    _reset_config_cache()

    with pytest.raises(RuntimeError, match=error_pattern):
        config.get_settings(force=True)

    _reset_config_cache()
    with pytest.raises(RuntimeError, match=error_pattern):
        settings_loader.get_settings(force=True, reload_env_func=lambda: None)


def test_invalid_gemini_models_falls_back_to_default_model(monkeypatch) -> None:
    _set_base_openai_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MODELS", "not-json")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    _reset_config_cache()

    loader_settings = settings_loader.get_settings(
        force=True,
        reload_env_func=lambda: None,
    )
    _reset_config_cache()
    facade_settings = config.get_settings(force=True)

    assert loader_settings.ai.gemini.model_specs == [
        ModelSpec(name="gemini-2.5-flash", rpm=None, rpd=None)
    ]
    assert facade_settings.ai.gemini.model_specs == [
        ModelSpec(name="gemini-2.5-flash", rpm=None, rpd=None)
    ]


@pytest.mark.skip(
    reason="Facade cache globals are a legacy API and not part of the required config contract."
)
def test_legacy_cache_reset_globals_still_refresh_settings(monkeypatch) -> None:
    _set_base_openai_env(monkeypatch)
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    _reset_config_cache()
    config.reset_settings_cache()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-a")
    first = config.get_settings(force=False)
    assert first.telegram_bot_token == "token-a"

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-b")
    config.reset_settings_cache()

    refreshed = config.get_settings(force=False)
    assert refreshed.telegram_bot_token == "token-b"


def test_config_facade_uses_cache_and_reload_hook(monkeypatch) -> None:
    _set_base_openai_env(monkeypatch)
    monkeypatch.setenv("SETTINGS_CACHE_TTL", "120")
    calls = {"count": 0}

    def _fake_reload_env() -> None:
        calls["count"] += 1

    monkeypatch.setattr(config, "_reload_env", _fake_reload_env)
    _reset_config_cache()

    first = config.get_settings(force=False)
    second = config.get_settings(force=False)

    assert calls["count"] == 1
    assert first is second


def test_reset_settings_cache_clears_shared_loader_cache(monkeypatch) -> None:
    _set_base_openai_env(monkeypatch)
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    _reset_config_cache()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-a")
    first = config.get_settings(force=False)
    assert first.telegram_bot_token == "token-a"

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-b")
    cached = settings_loader.get_settings(force=False, reload_env_func=lambda: None)
    assert cached.telegram_bot_token == "token-a"

    config.reset_settings_cache()
    refreshed = settings_loader.get_settings(force=False, reload_env_func=lambda: None)
    assert refreshed.telegram_bot_token == "token-b"
