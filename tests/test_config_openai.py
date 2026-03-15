import pytest

from src import config


def _reset_settings_cache() -> None:
    config.reset_settings_cache()


def test_openai_provider_requires_openai_api_key(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _reset_settings_cache()

    with pytest.raises(
        RuntimeError, match="OPENAI_API_KEY or OPENAI_AUTH_JSON_PATH is missing"
    ):
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
    monkeypatch.delenv("OPENAI_TRANSCRIPTION_MODEL", raising=False)
    _reset_settings_cache()

    settings = config.get_settings(force=True)
    assert settings.ai.routing.text_generation == "openai"
    assert settings.ai.openai.text_model == "gpt-5.3-codex"
    assert settings.ai.openai.low_cost_model == settings.ai.openai.text_model
    assert settings.ai.openai.reaction_model == settings.ai.openai.low_cost_model
    assert settings.ai.openai.transcription_model == "gpt-4o-mini-transcribe"
    assert settings.openai_transcription_model == "gpt-4o-mini-transcribe"
    assert settings.reaction_context_turns == 8
    assert settings.reaction_context_token_limit == 1200
    assert settings.ai.openai.refresh_url == "https://auth.openai.com/oauth/token"
    assert settings.ai.openai.codex_base_url == "https://chatgpt.com/backend-api"
    assert settings.ai.openai.codex_default_model == "gpt-5.3-codex"


def test_openai_provider_accepts_auth_json_without_api_key(
    monkeypatch, tmp_path
) -> None:
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
    assert settings.ai.openai.auth_json_path == str(auth_file)
    assert settings.ai.openai.text_model == "gpt-5.3-codex"
    assert settings.ai.openai.low_cost_model == "gpt-5.3-codex"
    assert settings.ai.openai.reaction_model == "gpt-5.3-codex"
    assert settings.ai.openai.transcription_model == "gpt-4o-mini-transcribe"


def test_openai_provider_accepts_custom_transcription_model(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
    _reset_settings_cache()

    settings = config.get_settings(force=True)

    assert settings.ai.openai.transcription_model == "gpt-4o-transcribe"
    assert settings.openai_transcription_model == "gpt-4o-transcribe"


def test_reaction_context_env_values_are_clamped(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("REACTION_CONTEXT_TURNS", "0")
    monkeypatch.setenv("REACTION_CONTEXT_TOKEN_LIMIT", "-10")
    _reset_settings_cache()

    settings = config.get_settings(force=True)
    assert settings.reaction_context_turns == 1
    assert settings.reaction_context_token_limit == 1


def test_telegram_format_ai_replies_default_true(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("TELEGRAM_FORMAT_AI_REPLIES", raising=False)
    _reset_settings_cache()

    settings = config.get_settings(force=True)
    assert settings.telegram_format_ai_replies is True


def test_telegram_format_ai_replies_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("TELEGRAM_FORMAT_AI_REPLIES", "false")
    _reset_settings_cache()

    settings = config.get_settings(force=True)
    assert settings.telegram_format_ai_replies is False


def test_telegram_use_message_drafts_default_false(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("TELEGRAM_USE_MESSAGE_DRAFTS", raising=False)
    monkeypatch.delenv("TELEGRAM_DRAFT_UPDATE_INTERVAL_SECS", raising=False)
    _reset_settings_cache()

    settings = config.get_settings(force=True)
    assert settings.telegram_use_message_drafts is False
    assert settings.telegram_draft_update_interval_secs == 0.15


def test_telegram_use_message_drafts_can_be_enabled(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("TELEGRAM_USE_MESSAGE_DRAFTS", "true")
    monkeypatch.setenv("TELEGRAM_DRAFT_UPDATE_INTERVAL_SECS", "0.1")
    _reset_settings_cache()

    settings = config.get_settings(force=True)
    assert settings.telegram_use_message_drafts is True
    assert settings.telegram_draft_update_interval_secs == 0.1


def test_csv_env_values_are_trimmed(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", " 1, 2 ,,3 ")
    monkeypatch.setenv("BOT_ALIASES", " BotName, Helper ,")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    _reset_settings_cache()

    settings = config.get_settings(force=True)
    assert settings.allowed_chat_ids == ["1", "2", "3"]
    assert settings.bot_aliases == ["botname", "helper"]


def test_message_handling_and_schedule_events_are_mutually_exclusive(
    monkeypatch,
) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("ENABLE_MESSAGE_HANDLING", "true")
    monkeypatch.setenv("ENABLE_SCHEDULE_EVENTS", "true")
    _reset_settings_cache()

    with pytest.raises(RuntimeError, match="mutually exclusive"):
        config.get_settings(force=True)


def test_legacy_module_attributes_are_not_exposed(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1,2")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-custom")
    monkeypatch.setenv("TELEGRAM_USE_MESSAGE_DRAFTS", "true")
    _reset_settings_cache()

    config.get_settings(force=True)

    with pytest.raises(AttributeError):
        _ = getattr(config, "OPENAI_MODEL")

    with pytest.raises(AttributeError):
        _ = getattr(config, "MODEL_PROVIDER")
