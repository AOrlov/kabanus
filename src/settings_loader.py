"""Settings parser and cache implementation."""

import json
import logging
import os
import time
from threading import Lock
from typing import Callable, List, Optional, cast

from dotenv import find_dotenv, load_dotenv

from src.providers.contracts import CapabilityName, ProviderName, ProviderRouting
from src.settings_models import (
    AISettings,
    GeminiSettings,
    ModelSpec,
    OpenAISettings,
    Settings,
)

_DOTENV_PATH = os.getenv("DOTENV_PATH") or find_dotenv(usecwd=True)
_DOTENV_MTIME = None
_ENV_LOCK = Lock()
_SETTINGS_CACHE: Optional[Settings] = None
_SETTINGS_CACHE_TS = 0.0
_CACHE_TTL = 1.0
_DEFAULT_OPENAI_TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"
logger = logging.getLogger(__name__)


def reload_env() -> None:
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


def _csv_list(raw_value: str, *, lowercase: bool = False) -> List[str]:
    items: List[str] = []
    for raw_item in raw_value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        items.append(item.lower() if lowercase else item)
    return items


_ROUTABLE_CAPABILITIES: tuple[CapabilityName, ...] = (
    "text_generation",
    "streaming_text_generation",
    "low_cost_text_generation",
    "audio_transcription",
    "ocr",
    "reaction_selection",
    "event_parsing",
)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _parse_provider_name(raw_value: str, *, env_name: str) -> ProviderName:
    provider = raw_value.strip().lower()
    if provider not in {"openai", "gemini"}:
        raise RuntimeError(f"{env_name} must be either 'openai' or 'gemini'")
    return cast(ProviderName, provider)


def _load_provider_routing(default_provider: ProviderName) -> ProviderRouting:
    return ProviderRouting(
        text_generation=_parse_provider_name(
            os.getenv("AI_PROVIDER_TEXT_GENERATION", default_provider),
            env_name="AI_PROVIDER_TEXT_GENERATION",
        ),
        streaming_text_generation=_parse_provider_name(
            os.getenv("AI_PROVIDER_STREAMING_TEXT_GENERATION", default_provider),
            env_name="AI_PROVIDER_STREAMING_TEXT_GENERATION",
        ),
        low_cost_text_generation=_parse_provider_name(
            os.getenv("AI_PROVIDER_LOW_COST_TEXT_GENERATION", default_provider),
            env_name="AI_PROVIDER_LOW_COST_TEXT_GENERATION",
        ),
        audio_transcription=_parse_provider_name(
            os.getenv("AI_PROVIDER_AUDIO_TRANSCRIPTION", default_provider),
            env_name="AI_PROVIDER_AUDIO_TRANSCRIPTION",
        ),
        ocr=_parse_provider_name(
            os.getenv("AI_PROVIDER_OCR", default_provider),
            env_name="AI_PROVIDER_OCR",
        ),
        reaction_selection=_parse_provider_name(
            os.getenv("AI_PROVIDER_REACTION_SELECTION", default_provider),
            env_name="AI_PROVIDER_REACTION_SELECTION",
        ),
        event_parsing=_parse_provider_name(
            os.getenv("AI_PROVIDER_EVENT_PARSING", default_provider),
            env_name="AI_PROVIDER_EVENT_PARSING",
        ),
    )


def _validate_routed_credentials(
    routing: ProviderRouting,
    *,
    openai_settings: OpenAISettings,
    gemini_settings: GeminiSettings,
) -> None:
    routed_openai_capabilities = [
        capability
        for capability in _ROUTABLE_CAPABILITIES
        if routing.provider_for(capability) == "openai"
    ]
    if routed_openai_capabilities and not openai_settings.configured:
        raise RuntimeError(
            "OpenAI is routed for "
            + ", ".join(routed_openai_capabilities)
            + " but OPENAI_API_KEY or OPENAI_AUTH_JSON_PATH is missing"
        )

    routed_gemini_capabilities = [
        capability
        for capability in _ROUTABLE_CAPABILITIES
        if routing.provider_for(capability) == "gemini"
    ]
    if routed_gemini_capabilities and not gemini_settings.configured:
        raise RuntimeError(
            "Gemini is routed for "
            + ", ".join(routed_gemini_capabilities)
            + " but GEMINI_API_KEY or GOOGLE_API_KEY is missing"
        )


def _load_settings_from_env() -> Settings:
    telegram_bot_token = _require_env("TELEGRAM_BOT_TOKEN")
    model_provider = _parse_provider_name(
        os.getenv("MODEL_PROVIDER", "openai"),
        env_name="MODEL_PROVIDER",
    )
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_auth_json_path = os.getenv("OPENAI_AUTH_JSON_PATH", "").strip()
    openai_refresh_url = os.getenv(
        "OPENAI_REFRESH_URL", "https://auth.openai.com/oauth/token"
    ).strip()
    openai_refresh_client_id = os.getenv("OPENAI_REFRESH_CLIENT_ID", "").strip()
    openai_refresh_grant_type = (
        os.getenv("OPENAI_REFRESH_GRANT_TYPE", "refresh_token").strip()
        or "refresh_token"
    )
    openai_auth_leeway_secs = int(os.getenv("OPENAI_AUTH_LEEWAY_SECS", "60"))
    openai_auth_timeout_secs = float(os.getenv("OPENAI_AUTH_TIMEOUT_SECS", "20"))
    openai_codex_base_url = os.getenv(
        "OPENAI_CODEX_BASE_URL", "https://chatgpt.com/backend-api"
    ).strip()
    openai_codex_default_model = (
        os.getenv("OPENAI_CODEX_DEFAULT_MODEL", "gpt-5.3-codex").strip()
        or "gpt-5.3-codex"
    )
    openai_model_env = os.getenv("OPENAI_MODEL")
    openai_low_cost_model_env = os.getenv("OPENAI_LOW_COST_MODEL")
    openai_reaction_model_env = os.getenv("OPENAI_REACTION_MODEL")
    openai_model = (openai_model_env or "gpt-5.3-codex").strip()
    openai_low_cost_model = (openai_low_cost_model_env or openai_model).strip()
    openai_reaction_model = (openai_reaction_model_env or openai_low_cost_model).strip()
    openai_transcription_model = (
        os.getenv(
            "OPENAI_TRANSCRIPTION_MODEL",
            _DEFAULT_OPENAI_TRANSCRIPTION_MODEL,
        ).strip()
        or _DEFAULT_OPENAI_TRANSCRIPTION_MODEL
    )
    if openai_auth_json_path:
        if openai_model_env is None:
            openai_model = openai_codex_default_model
        if openai_low_cost_model_env is None:
            openai_low_cost_model = openai_model
        if openai_reaction_model_env is None:
            openai_reaction_model = openai_low_cost_model
    google_api_key = os.getenv("GOOGLE_API_KEY")
    gemini_api_key_source = (
        google_api_key
        if google_api_key is not None
        else os.getenv("GEMINI_API_KEY", "")
    )
    gemini_api_key = gemini_api_key_source.strip()

    allowed_chat_ids_raw = _require_env("ALLOWED_CHAT_IDS")
    allowed_chat_ids = _csv_list(allowed_chat_ids_raw)

    features = {
        "commands": {
            "hi": True,
        },
        "message_handling": _env_bool("ENABLE_MESSAGE_HANDLING"),
        "schedule_events": _env_bool("ENABLE_SCHEDULE_EVENTS"),
    }
    if features["message_handling"] and features["schedule_events"]:
        raise RuntimeError(
            "ENABLE_MESSAGE_HANDLING and ENABLE_SCHEDULE_EVENTS are mutually exclusive; enable only one."
        )

    gemini_model = (
        os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip().lower()
        or "gemini-2.0-flash"
    )

    gemini_models_raw = os.getenv("GEMINI_MODELS", "").strip()
    gemini_models: List[ModelSpec] = []
    if gemini_models_raw:
        try:
            parsed = json.loads(gemini_models_raw)
            if not isinstance(parsed, list):
                raise ValueError("GEMINI_MODELS must be a JSON list")
            for item in parsed:
                if not isinstance(item, dict):
                    raise ValueError("Each GEMINI_MODELS item must be an object")
                name = str(item.get("name", "")).strip().lower()
                if not name:
                    raise ValueError("Each GEMINI_MODELS item requires a name")
                rpm = item.get("rpm")
                rpd = item.get("rpd")
                gemini_models.append(
                    ModelSpec(
                        name=name,
                        rpm=int(rpm) if rpm is not None else None,
                        rpd=int(rpd) if rpd is not None else None,
                    )
                )
        except (ValueError, json.JSONDecodeError) as exc:
            logger.error("Failed to parse GEMINI_MODELS: %s", exc)
            gemini_models = []
    if not gemini_models:
        gemini_models = [ModelSpec(name=gemini_model, rpm=None, rpd=None)]

    openai_settings = OpenAISettings(
        api_key=openai_api_key,
        auth_json_path=openai_auth_json_path,
        refresh_url=openai_refresh_url,
        refresh_client_id=openai_refresh_client_id,
        refresh_grant_type=openai_refresh_grant_type,
        auth_leeway_secs=openai_auth_leeway_secs,
        auth_timeout_secs=openai_auth_timeout_secs,
        codex_base_url=openai_codex_base_url,
        codex_default_model=openai_codex_default_model,
        text_model=openai_model,
        low_cost_model=openai_low_cost_model,
        reaction_model=openai_reaction_model,
        transcription_model=openai_transcription_model,
    )
    gemini_settings = GeminiSettings(
        api_key=gemini_api_key,
        default_model=gemini_model,
        low_cost_model=(
            os.getenv("GEMINI_LOW_COST_MODEL", gemini_model).strip().lower()
            or gemini_model
        ),
        model_specs=gemini_models,
        thinking_budget=int(os.getenv("THINKING_BUDGET", 0)),
        use_google_search=_env_bool("USE_GOOGLE_SEARCH"),
        system_instructions_path=os.getenv("SYSTEM_INSTRUCTIONS_PATH", ""),
        reaction_model=(
            os.getenv("REACTION_GEMINI_MODEL", gemini_model).strip().lower()
            or gemini_model
        ),
    )
    routing = _load_provider_routing(model_provider)
    _validate_routed_credentials(
        routing,
        openai_settings=openai_settings,
        gemini_settings=gemini_settings,
    )

    return Settings(
        telegram_bot_token=telegram_bot_token,
        admin_chat_id=os.getenv("ADMIN_CHAT_ID"),
        features=features,
        ai=AISettings(
            routing=routing,
            openai=openai_settings,
            gemini=gemini_settings,
        ),
        google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID"),
        google_credentials_path=os.getenv("GOOGLE_CREDENTIALS_PATH"),
        google_credentials_json=os.getenv("GOOGLE_CREDENTIALS_JSON"),
        allowed_chat_ids=allowed_chat_ids,
        bot_aliases=_csv_list(os.getenv("BOT_ALIASES", ""), lowercase=True),
        language=os.getenv("LANGUAGE", "ru").lower(),
        token_limit=int(os.getenv("TOKEN_LIMIT", 500_000)),
        chat_messages_store_path=os.getenv(
            "CHAT_MESSAGES_STORE_PATH", "messages.jsonl"
        ),
        memory_enabled=_env_bool("MEMORY_ENABLED", "true"),
        memory_recent_turns=max(1, int(os.getenv("MEMORY_RECENT_TURNS", "20"))),
        memory_recent_budget_ratio=min(
            1.0, max(0.0, float(os.getenv("MEMORY_RECENT_BUDGET_RATIO", "0.85")))
        ),
        memory_summary_enabled=_env_bool("MEMORY_SUMMARY_ENABLED"),
        memory_summary_budget_ratio=min(
            1.0, max(0.0, float(os.getenv("MEMORY_SUMMARY_BUDGET_RATIO", "0.15")))
        ),
        memory_summary_chunk_size=max(
            2, int(os.getenv("MEMORY_SUMMARY_CHUNK_SIZE", "16"))
        ),
        memory_summary_max_items=max(
            0, int(os.getenv("MEMORY_SUMMARY_MAX_ITEMS", "4"))
        ),
        memory_summary_max_chunks_per_run=max(
            1, int(os.getenv("MEMORY_SUMMARY_MAX_CHUNKS_PER_RUN", "1"))
        ),
        debug_mode=_env_bool("DEBUG_MODE"),
        settings_refresh_interval=float(os.getenv("SETTINGS_REFRESH_INTERVAL", "1.0")),
        reaction_enabled=_env_bool("REACTION_ENABLED"),
        reaction_cooldown_secs=float(os.getenv("REACTION_COOLDOWN_SECS", "600")),
        reaction_daily_budget=int(os.getenv("REACTION_DAILY_BUDGET", "50")),
        reaction_messages_threshold=int(os.getenv("REACTION_MESSAGES_THRESHOLD", "10")),
        reaction_context_turns=max(1, int(os.getenv("REACTION_CONTEXT_TURNS", "8"))),
        reaction_context_token_limit=max(
            1, int(os.getenv("REACTION_CONTEXT_TOKEN_LIMIT", "1200"))
        ),
        telegram_format_ai_replies=_env_bool("TELEGRAM_FORMAT_AI_REPLIES", "true"),
        telegram_use_message_drafts=_env_bool("TELEGRAM_USE_MESSAGE_DRAFTS"),
        telegram_draft_update_interval_secs=max(
            0.05, float(os.getenv("TELEGRAM_DRAFT_UPDATE_INTERVAL_SECS", "0.15"))
        ),
    )


def reset_settings_cache() -> None:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TS, _CACHE_TTL
    _SETTINGS_CACHE = None
    _SETTINGS_CACHE_TS = 0.0
    _CACHE_TTL = 1.0


def get_settings(
    force: bool = False,
    reload_env_func: Optional[Callable[[], None]] = None,
) -> Settings:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TS, _CACHE_TTL
    now = time.monotonic()
    if not force and _SETTINGS_CACHE and (now - _SETTINGS_CACHE_TS) < _CACHE_TTL:
        return _SETTINGS_CACHE

    with _ENV_LOCK:
        if reload_env_func is None:
            reload_env()
        else:
            reload_env_func()
        _CACHE_TTL = float(os.getenv("SETTINGS_CACHE_TTL", "1.0"))

    settings = _load_settings_from_env()
    _SETTINGS_CACHE = settings
    _SETTINGS_CACHE_TS = now
    return settings
