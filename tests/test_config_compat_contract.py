import pytest

from src import config

# Contract note for this refactor baseline:
# - Stable: environment variable names/defaults/parsing/validation through config.get_settings().
# - Allowed to change: legacy module-level attribute facade access (config.<UPPERCASE_NAME>).


def _reset_settings_cache() -> None:
    config._SETTINGS_CACHE = None
    config._SETTINGS_CACHE_TS = 0.0


def _set_base_openai_env(monkeypatch) -> None:
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    for env_name in [
        "OPENAI_MODEL",
        "OPENAI_LOW_COST_MODEL",
        "OPENAI_REACTION_MODEL",
        "BOT_ALIASES",
        "LANGUAGE",
        "TOKEN_LIMIT",
        "CHAT_MESSAGES_STORE_PATH",
        "MEMORY_ENABLED",
        "MEMORY_RECENT_TURNS",
        "MEMORY_RECENT_BUDGET_RATIO",
        "MEMORY_SUMMARY_ENABLED",
        "MEMORY_SUMMARY_BUDGET_RATIO",
        "MEMORY_SUMMARY_CHUNK_SIZE",
        "MEMORY_SUMMARY_MAX_ITEMS",
        "MEMORY_SUMMARY_MAX_CHUNKS_PER_RUN",
        "REACTION_ENABLED",
        "REACTION_COOLDOWN_SECS",
        "REACTION_DAILY_BUDGET",
        "REACTION_MESSAGES_THRESHOLD",
        "REACTION_CONTEXT_TURNS",
        "REACTION_CONTEXT_TOKEN_LIMIT",
        "TELEGRAM_FORMAT_AI_REPLIES",
        "TELEGRAM_USE_MESSAGE_DRAFTS",
        "TELEGRAM_DRAFT_UPDATE_INTERVAL_SECS",
        "SYSTEM_INSTRUCTIONS_PATH",
    ]:
        monkeypatch.delenv(env_name, raising=False)


def test_config_default_contract_snapshot(monkeypatch) -> None:
    _set_base_openai_env(monkeypatch)
    _reset_settings_cache()

    settings = config.get_settings(force=True)

    assert settings.model_provider == "openai"
    assert settings.openai_model == "gpt-5.3-codex"
    assert settings.openai_low_cost_model == "gpt-5.3-codex"
    assert settings.openai_reaction_model == "gpt-5.3-codex"
    assert settings.allowed_chat_ids == ["1"]
    assert settings.bot_aliases == []
    assert settings.language == "ru"
    assert settings.token_limit == 500_000
    assert settings.chat_messages_store_path == "messages.jsonl"
    assert settings.memory_enabled is True
    assert settings.memory_recent_turns == 20
    assert settings.memory_recent_budget_ratio == pytest.approx(0.85)
    assert settings.memory_summary_enabled is False
    assert settings.memory_summary_budget_ratio == pytest.approx(0.15)
    assert settings.memory_summary_chunk_size == 16
    assert settings.memory_summary_max_items == 4
    assert settings.memory_summary_max_chunks_per_run == 1
    assert settings.reaction_enabled is False
    assert settings.reaction_cooldown_secs == pytest.approx(600.0)
    assert settings.reaction_daily_budget == 50
    assert settings.reaction_messages_threshold == 10
    assert settings.reaction_context_turns == 8
    assert settings.reaction_context_token_limit == 1200
    assert settings.telegram_format_ai_replies is True
    assert settings.telegram_use_message_drafts is False
    assert settings.telegram_draft_update_interval_secs == pytest.approx(0.15)


@pytest.mark.parametrize(
    ("env_name", "env_value", "attr_name", "expected"),
    [
        ("SYSTEM_INSTRUCTIONS_PATH", "/tmp/system.txt", "ai_system_instructions_path", "/tmp/system.txt"),
        ("LANGUAGE", "EN", "language", "en"),
        ("TOKEN_LIMIT", "321", "token_limit", 321),
        ("CHAT_MESSAGES_STORE_PATH", "custom/messages.jsonl", "chat_messages_store_path", "custom/messages.jsonl"),
        ("MEMORY_ENABLED", "false", "memory_enabled", False),
        ("MEMORY_RECENT_TURNS", "7", "memory_recent_turns", 7),
        ("MEMORY_SUMMARY_ENABLED", "true", "memory_summary_enabled", True),
        ("REACTION_ENABLED", "true", "reaction_enabled", True),
        ("REACTION_MESSAGES_THRESHOLD", "3", "reaction_messages_threshold", 3),
        ("REACTION_CONTEXT_TOKEN_LIMIT", "55", "reaction_context_token_limit", 55),
        ("TELEGRAM_USE_MESSAGE_DRAFTS", "true", "telegram_use_message_drafts", True),
        ("TELEGRAM_DRAFT_UPDATE_INTERVAL_SECS", "0.2", "telegram_draft_update_interval_secs", 0.2),
        ("ALLOWED_CHAT_IDS", " 1, 2 ,,3 ", "allowed_chat_ids", ["1", "2", "3"]),
        ("BOT_ALIASES", " Bot, Helper ,", "bot_aliases", ["bot", "helper"]),
    ],
)
def test_env_var_name_contract(monkeypatch, env_name, env_value, attr_name, expected) -> None:
    _set_base_openai_env(monkeypatch)
    monkeypatch.setenv(env_name, env_value)
    _reset_settings_cache()

    settings = config.get_settings(force=True)
    actual = getattr(settings, attr_name)

    if isinstance(expected, float):
        assert actual == pytest.approx(expected)
        return
    assert actual == expected


@pytest.mark.parametrize(
    ("env_updates", "removed_env", "error_pattern"),
    [
        (
            {"MODEL_PROVIDER": "unsupported"},
            [],
            "MODEL_PROVIDER must be either 'openai' or 'gemini'",
        ),
        (
            {"MODEL_PROVIDER": "gemini"},
            ["GEMINI_API_KEY"],
            "Missing required environment variable: GEMINI_API_KEY",
        ),
        (
            {"MODEL_PROVIDER": "openai"},
            ["OPENAI_API_KEY", "OPENAI_AUTH_JSON_PATH"],
            "OpenAI mode requires OPENAI_API_KEY or OPENAI_AUTH_JSON_PATH",
        ),
        (
            {"ENABLE_MESSAGE_HANDLING": "true", "ENABLE_SCHEDULE_EVENTS": "true"},
            [],
            "mutually exclusive",
        ),
    ],
)
def test_config_validation_contract(monkeypatch, env_updates, removed_env, error_pattern) -> None:
    _set_base_openai_env(monkeypatch)
    for env_name, env_value in env_updates.items():
        monkeypatch.setenv(env_name, env_value)
    for env_name in removed_env:
        monkeypatch.delenv(env_name, raising=False)
    _reset_settings_cache()

    with pytest.raises(RuntimeError, match=error_pattern):
        config.get_settings(force=True)


@pytest.mark.skip(
    reason="Legacy module-level facade compatibility is not part of the required config contract."
)
def test_legacy_module_attribute_contract(monkeypatch) -> None:
    _set_base_openai_env(monkeypatch)
    monkeypatch.setenv("BOT_ALIASES", "kaban,helper")
    monkeypatch.setenv("REACTION_ENABLED", "true")
    _reset_settings_cache()
    settings = config.get_settings(force=True)

    assert config.TELEGRAM_BOT_TOKEN == settings.telegram_bot_token
    assert config.MODEL_PROVIDER == settings.model_provider
    assert config.OPENAI_MODEL == settings.openai_model
    assert config.OPENAI_LOW_COST_MODEL == settings.openai_low_cost_model
    assert config.OPENAI_REACTION_MODEL == settings.openai_reaction_model
    assert config.ALLOWED_CHAT_IDS == settings.allowed_chat_ids
    assert config.BOT_ALIASES == settings.bot_aliases
    assert config.TOKEN_LIMIT == settings.token_limit
    assert config.MEMORY_RECENT_TURNS == settings.memory_recent_turns
    assert config.MEMORY_SUMMARY_ENABLED == settings.memory_summary_enabled
    assert config.REACTION_ENABLED == settings.reaction_enabled
    assert config.REACTION_CONTEXT_TURNS == settings.reaction_context_turns
    assert config.TELEGRAM_USE_MESSAGE_DRAFTS == settings.telegram_use_message_drafts


@pytest.mark.skip(
    reason="Legacy module-level facade compatibility is not part of the required config contract."
)
def test_unknown_legacy_module_attribute_raises(monkeypatch) -> None:
    _set_base_openai_env(monkeypatch)
    _reset_settings_cache()
    config.get_settings(force=True)

    with pytest.raises(AttributeError):
        _ = config.THIS_DOES_NOT_EXIST
