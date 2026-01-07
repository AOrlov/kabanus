"""Runtime settings loader with dotenv reload and caching.

Environment behavior:
- Reads from .env if present (override=True) and refreshes on mtime change.
- Caches settings for a short TTL to avoid reloading on every access.

Tuning:
- DOTENV_PATH can point to a specific env file.
- SETTINGS_CACHE_TTL controls the in-process cache window (seconds, default 1.0).
- SETTINGS_REFRESH_INTERVAL is used by the app's periodic refresh job (seconds, default 1.0).
"""
import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import List, Optional

from dotenv import find_dotenv, load_dotenv

_DOTENV_PATH = os.getenv("DOTENV_PATH") or find_dotenv(usecwd=True)
_DOTENV_MTIME = None
_ENV_LOCK = Lock()
_SETTINGS_CACHE = None
_SETTINGS_CACHE_TS = 0.0
_CACHE_TTL = 1.0


def _reload_env() -> None:
    global _DOTENV_MTIME
    if _DOTENV_PATH:
        try:
            mtime = os.path.getmtime(_DOTENV_PATH)
        except OSError:
            mtime = None
        if mtime != _DOTENV_MTIME:
            load_dotenv(_DOTENV_PATH, override=True)
            _DOTENV_MTIME = mtime
    else:
        load_dotenv(override=True)


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() == "true"


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    admin_chat_id: Optional[str]
    features: dict
    gemini_api_key: str
    google_api_key: str
    gemini_model: str
    thinking_budget: int
    use_google_search: bool
    ai_system_instructions_path: str
    google_calendar_id: Optional[str]
    google_credentials_path: Optional[str]
    google_credentials_json: Optional[str]
    allowed_chat_ids: List[str]
    bot_aliases: List[str]
    language: str
    token_limit: int
    chat_messages_store_path: str
    debug_mode: bool
    settings_refresh_interval: float
    reaction_enabled: bool
    reaction_cooldown_secs: float
    reaction_daily_budget: int
    reaction_messages_threshold: int


def get_settings(force: bool = False) -> Settings:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TS, _CACHE_TTL
    now = time.monotonic()
    if not force and _SETTINGS_CACHE and (now - _SETTINGS_CACHE_TS) < _CACHE_TTL:
        return _SETTINGS_CACHE
    with _ENV_LOCK:
        _reload_env()
        _CACHE_TTL = float(os.getenv("SETTINGS_CACHE_TTL", "1.0"))

    telegram_bot_token = _require_env("TELEGRAM_BOT_TOKEN")
    gemini_api_key = _require_env("GEMINI_API_KEY")
    google_api_key = os.getenv("GOOGLE_API_KEY") or gemini_api_key
    os.environ["GOOGLE_API_KEY"] = google_api_key

    allowed_chat_ids_raw = _require_env("ALLOWED_CHAT_IDS")
    allowed_chat_ids = [item for item in allowed_chat_ids_raw.split(",") if item]

    features = {
        "commands": {
            "hi": True,
        },
        "message_handling": _env_bool("ENABLE_MESSAGE_HANDLING"),
        "schedule_events": _env_bool("ENABLE_SCHEDULE_EVENTS"),
    }

    settings = Settings(
        telegram_bot_token=telegram_bot_token,
        admin_chat_id=os.getenv("ADMIN_CHAT_ID"),
        features=features,
        gemini_api_key=gemini_api_key,
        google_api_key=google_api_key,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash").lower(),
        thinking_budget=int(os.getenv("THINKING_BUDGET", 0)),
        use_google_search=_env_bool("USE_GOOGLE_SEARCH"),
        ai_system_instructions_path=os.getenv("SYSTEM_INSTRUCTIONS_PATH", "system_instructions.txt"),
        google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID"),
        google_credentials_path=os.getenv("GOOGLE_CREDENTIALS_PATH"),
        google_credentials_json=os.getenv("GOOGLE_CREDENTIALS_JSON"),
        allowed_chat_ids=allowed_chat_ids,
        bot_aliases=[alias.lower() for alias in os.getenv("BOT_ALIASES", "").split(",") if alias],
        language=os.getenv("LANGUAGE", "ru").lower(),
        token_limit=int(os.getenv("TOKEN_LIMIT", 500_000)),
        chat_messages_store_path=os.getenv("CHAT_MESSAGES_STORE_PATH", "messages.jsonl"),
        debug_mode=_env_bool("DEBUG_MODE"),
        settings_refresh_interval=float(os.getenv("SETTINGS_REFRESH_INTERVAL", "1.0")),
        reaction_enabled=_env_bool("REACTION_ENABLED"),
        reaction_cooldown_secs=float(os.getenv("REACTION_COOLDOWN_SECS", "600")),
        reaction_daily_budget=int(os.getenv("REACTION_DAILY_BUDGET", "50")),
        reaction_messages_threshold=int(os.getenv("REACTION_MESSAGES_THRESHOLD", "10"))
    )
    _SETTINGS_CACHE = settings
    _SETTINGS_CACHE_TS = now
    return settings


def __getattr__(name: str):
    settings = get_settings()
    mapping = {
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "ADMIN_CHAT_ID": settings.admin_chat_id,
        "FEATURES": settings.features,
        "GEMINI_API_KEY": settings.gemini_api_key,
        "GOOGLE_API_KEY": settings.google_api_key,
        "GEMINI_MODEL": settings.gemini_model,
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
        "DEBUG_MODE": settings.debug_mode,
        "SETTINGS_REFRESH_INTERVAL": settings.settings_refresh_interval,
        "REACTION_ENABLED": settings.reaction_enabled,
        "REACTION_COOLDOWN_SECS": settings.reaction_cooldown_secs,
        "REACTION_DAILY_BUDGET": settings.reaction_daily_budget,
        "REACTION_MESSAGES_THRESHOLD": settings.reaction_messages_threshold,
    }
    if name in mapping:
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
