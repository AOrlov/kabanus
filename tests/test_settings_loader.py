from src import config, settings_loader
from src.settings_models import ModelSpec, Settings


def _reset_config_cache() -> None:
    config._SETTINGS_CACHE = None
    config._SETTINGS_CACHE_TS = 0.0
    config._CACHE_TTL = 1.0


def _reset_loader_cache() -> None:
    settings_loader.set_cache_state(None, 0.0, 1.0)


def _set_base_openai_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_config_reexports_settings_models() -> None:
    assert config.Settings is Settings
    assert config.ModelSpec is ModelSpec


def test_settings_loader_matches_config_facade_behavior(monkeypatch) -> None:
    _set_base_openai_env(monkeypatch)
    monkeypatch.setenv("BOT_ALIASES", "Kaban, Helper")
    monkeypatch.setenv("TELEGRAM_USE_MESSAGE_DRAFTS", "true")
    monkeypatch.setenv("REACTION_CONTEXT_TURNS", "5")
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    _reset_config_cache()
    _reset_loader_cache()

    facade_settings = config.get_settings(force=True)
    _reset_loader_cache()
    loader_settings = settings_loader.get_settings(force=True, reload_env_func=lambda: None)

    assert loader_settings == facade_settings
    assert loader_settings.bot_aliases == ["kaban", "helper"]
    assert loader_settings.telegram_use_message_drafts is True
    assert loader_settings.reaction_context_turns == 5


def test_legacy_cache_reset_globals_still_refresh_settings(monkeypatch) -> None:
    _set_base_openai_env(monkeypatch)
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    _reset_config_cache()
    _reset_loader_cache()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-a")
    first = config.get_settings(force=False)
    assert first.telegram_bot_token == "token-a"

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-b")
    config._SETTINGS_CACHE = None
    config._SETTINGS_CACHE_TS = 0.0

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
    _reset_loader_cache()

    first = config.get_settings(force=False)
    second = config.get_settings(force=False)

    assert calls["count"] == 1
    assert first is second
