"""Typed settings models shared by config facade and loader internals."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class ModelSpec:
    name: str
    rpm: Optional[int]
    rpd: Optional[int]


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    admin_chat_id: Optional[str]
    features: dict
    model_provider: str
    gemini_api_key: str
    google_api_key: str
    gemini_model: str
    gemini_models: List[ModelSpec]
    openai_api_key: str
    openai_auth_json_path: str
    openai_refresh_url: str
    openai_refresh_client_id: str
    openai_refresh_grant_type: str
    openai_auth_leeway_secs: int
    openai_auth_timeout_secs: float
    openai_codex_base_url: str
    openai_codex_default_model: str
    openai_model: str
    openai_low_cost_model: str
    openai_reaction_model: str
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
    memory_enabled: bool
    memory_recent_turns: int
    memory_recent_budget_ratio: float
    memory_summary_enabled: bool
    memory_summary_budget_ratio: float
    memory_summary_chunk_size: int
    memory_summary_max_items: int
    memory_summary_max_chunks_per_run: int
    debug_mode: bool
    settings_refresh_interval: float
    reaction_enabled: bool
    reaction_cooldown_secs: float
    reaction_daily_budget: int
    reaction_messages_threshold: int
    reaction_gemini_model: str
    reaction_context_turns: int
    reaction_context_token_limit: int
    telegram_format_ai_replies: bool
    telegram_use_message_drafts: bool
    telegram_draft_update_interval_secs: float
