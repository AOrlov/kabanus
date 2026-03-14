"""Typed settings models shared by config facade and loader internals."""

from dataclasses import dataclass
from typing import List, Optional

from src.providers.contracts import ProviderRouting


@dataclass(frozen=True)
class ModelSpec:
    name: str
    rpm: Optional[int]
    rpd: Optional[int]


@dataclass(frozen=True)
class OpenAISettings:
    api_key: str
    auth_json_path: str
    refresh_url: str
    refresh_client_id: str
    refresh_grant_type: str
    auth_leeway_secs: int
    auth_timeout_secs: float
    codex_base_url: str
    codex_default_model: str
    text_model: str
    low_cost_model: str
    reaction_model: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key or self.auth_json_path)


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str
    default_model: str
    low_cost_model: str
    model_specs: List[ModelSpec]
    thinking_budget: int
    use_google_search: bool
    system_instructions_path: str
    reaction_model: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class AISettings:
    routing: ProviderRouting
    openai: OpenAISettings
    gemini: GeminiSettings

    @property
    def default_provider(self) -> str:
        return self.routing.text_generation


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    admin_chat_id: Optional[str]
    features: dict
    ai: AISettings
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
    reaction_context_turns: int
    reaction_context_token_limit: int
    telegram_format_ai_replies: bool
    telegram_use_message_drafts: bool
    telegram_draft_update_interval_secs: float

    @property
    def model_provider(self) -> str:
        return self.ai.default_provider

    @property
    def provider_routing(self) -> ProviderRouting:
        return self.ai.routing

    @property
    def gemini_api_key(self) -> str:
        return self.ai.gemini.api_key

    @property
    def google_api_key(self) -> str:
        return self.ai.gemini.api_key

    @property
    def gemini_model(self) -> str:
        return self.ai.gemini.default_model

    @property
    def gemini_models(self) -> List[ModelSpec]:
        return self.ai.gemini.model_specs

    @property
    def openai_api_key(self) -> str:
        return self.ai.openai.api_key

    @property
    def openai_auth_json_path(self) -> str:
        return self.ai.openai.auth_json_path

    @property
    def openai_refresh_url(self) -> str:
        return self.ai.openai.refresh_url

    @property
    def openai_refresh_client_id(self) -> str:
        return self.ai.openai.refresh_client_id

    @property
    def openai_refresh_grant_type(self) -> str:
        return self.ai.openai.refresh_grant_type

    @property
    def openai_auth_leeway_secs(self) -> int:
        return self.ai.openai.auth_leeway_secs

    @property
    def openai_auth_timeout_secs(self) -> float:
        return self.ai.openai.auth_timeout_secs

    @property
    def openai_codex_base_url(self) -> str:
        return self.ai.openai.codex_base_url

    @property
    def openai_codex_default_model(self) -> str:
        return self.ai.openai.codex_default_model

    @property
    def openai_model(self) -> str:
        return self.ai.openai.text_model

    @property
    def openai_low_cost_model(self) -> str:
        return self.ai.openai.low_cost_model

    @property
    def openai_reaction_model(self) -> str:
        return self.ai.openai.reaction_model

    @property
    def thinking_budget(self) -> int:
        return self.ai.gemini.thinking_budget

    @property
    def use_google_search(self) -> bool:
        return self.ai.gemini.use_google_search

    @property
    def ai_system_instructions_path(self) -> str:
        return self.ai.gemini.system_instructions_path

    @property
    def reaction_gemini_model(self) -> str:
        return self.ai.gemini.reaction_model

    @property
    def gemini_low_cost_model(self) -> str:
        return self.ai.gemini.low_cost_model
