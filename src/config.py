"""Runtime settings compatibility facade.

Public API compatibility:
- Exposes `Settings`, `ModelSpec`, `get_settings(force=False)`.
- Supports legacy module-level attribute access via `__getattr__`.
"""

from typing import Optional

from src import settings_loader
from src.settings_models import ModelSpec, Settings

_SETTINGS_CACHE: Optional[Settings] = None
_SETTINGS_CACHE_TS = 0.0
_CACHE_TTL = 1.0
_reload_env = settings_loader.reload_env


def _sync_loader_cache_state() -> None:
    settings_loader.set_cache_state(
        cache=_SETTINGS_CACHE,
        cache_ts=_SETTINGS_CACHE_TS,
        cache_ttl=_CACHE_TTL,
    )


def _sync_facade_cache_state() -> None:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TS, _CACHE_TTL
    _SETTINGS_CACHE, _SETTINGS_CACHE_TS, _CACHE_TTL = settings_loader.get_cache_state()


def get_settings(force: bool = False) -> Settings:
    _sync_loader_cache_state()
    settings = settings_loader.get_settings(force=force, reload_env_func=_reload_env)
    _sync_facade_cache_state()
    return settings


def __getattr__(name: str):
    settings = get_settings()
    mapping = {
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "ADMIN_CHAT_ID": settings.admin_chat_id,
        "FEATURES": settings.features,
        "MODEL_PROVIDER": settings.model_provider,
        "GEMINI_API_KEY": settings.gemini_api_key,
        "GOOGLE_API_KEY": settings.google_api_key,
        "GEMINI_MODEL": settings.gemini_model,
        "GEMINI_MODELS": settings.gemini_models,
        "OPENAI_API_KEY": settings.openai_api_key,
        "OPENAI_AUTH_JSON_PATH": settings.openai_auth_json_path,
        "OPENAI_REFRESH_URL": settings.openai_refresh_url,
        "OPENAI_REFRESH_CLIENT_ID": settings.openai_refresh_client_id,
        "OPENAI_REFRESH_GRANT_TYPE": settings.openai_refresh_grant_type,
        "OPENAI_AUTH_LEEWAY_SECS": settings.openai_auth_leeway_secs,
        "OPENAI_AUTH_TIMEOUT_SECS": settings.openai_auth_timeout_secs,
        "OPENAI_CODEX_BASE_URL": settings.openai_codex_base_url,
        "OPENAI_CODEX_DEFAULT_MODEL": settings.openai_codex_default_model,
        "OPENAI_MODEL": settings.openai_model,
        "OPENAI_LOW_COST_MODEL": settings.openai_low_cost_model,
        "OPENAI_REACTION_MODEL": settings.openai_reaction_model,
        "THINKING_BUDGET": settings.thinking_budget,
        "USE_GOOGLE_SEARCH": settings.use_google_search,
        "AI_SYSTEM_INSTRUCTIONS_PATH": settings.ai_system_instructions_path,
        "GOOGLE_CALENDAR_ID": settings.google_calendar_id,
        "GOOGLE_CREDENTIALS_PATH": settings.google_credentials_path,
        "GOOGLE_CREDENTIALS_JSON": settings.google_credentials_json,
        "ALLOWED_CHAT_IDS": settings.allowed_chat_ids,
        "BOT_ALIASES": settings.bot_aliases,
        "LANGUAGE": settings.language,
        "TOKEN_LIMIT": settings.token_limit,
        "CHAT_MESSAGES_STORE_PATH": settings.chat_messages_store_path,
        "MEMORY_ENABLED": settings.memory_enabled,
        "MEMORY_RECENT_TURNS": settings.memory_recent_turns,
        "MEMORY_RECENT_BUDGET_RATIO": settings.memory_recent_budget_ratio,
        "MEMORY_SUMMARY_ENABLED": settings.memory_summary_enabled,
        "MEMORY_SUMMARY_BUDGET_RATIO": settings.memory_summary_budget_ratio,
        "MEMORY_SUMMARY_CHUNK_SIZE": settings.memory_summary_chunk_size,
        "MEMORY_SUMMARY_MAX_ITEMS": settings.memory_summary_max_items,
        "MEMORY_SUMMARY_MAX_CHUNKS_PER_RUN": settings.memory_summary_max_chunks_per_run,
        "DEBUG_MODE": settings.debug_mode,
        "SETTINGS_REFRESH_INTERVAL": settings.settings_refresh_interval,
        "REACTION_ENABLED": settings.reaction_enabled,
        "REACTION_COOLDOWN_SECS": settings.reaction_cooldown_secs,
        "REACTION_DAILY_BUDGET": settings.reaction_daily_budget,
        "REACTION_MESSAGES_THRESHOLD": settings.reaction_messages_threshold,
        "REACTION_GEMINI_MODEL": settings.reaction_gemini_model,
        "REACTION_CONTEXT_TURNS": settings.reaction_context_turns,
        "REACTION_CONTEXT_TOKEN_LIMIT": settings.reaction_context_token_limit,
        "TELEGRAM_FORMAT_AI_REPLIES": settings.telegram_format_ai_replies,
        "TELEGRAM_USE_MESSAGE_DRAFTS": settings.telegram_use_message_drafts,
        "TELEGRAM_DRAFT_UPDATE_INTERVAL_SECS": settings.telegram_draft_update_interval_secs,
    }
    if name in mapping:
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
