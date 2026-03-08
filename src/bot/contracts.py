from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol

from telegram import Update
from src.providers.contracts import (
    AudioTranscriptionRequest,
    EventPayload,
    ImageToEventRequest,
    ImageToTextRequest,
    ReactionSelectionRequest,
    TextGenerationRequest,
)


class BotSettings(Protocol):
    features: Mapping[str, Any]
    bot_aliases: Sequence[str]
    debug_mode: bool
    model_provider: str
    telegram_format_ai_replies: bool
    telegram_use_message_drafts: bool
    telegram_bot_token: str
    telegram_draft_update_interval_secs: float
    reaction_enabled: bool
    reaction_cooldown_secs: float
    reaction_daily_budget: int
    reaction_messages_threshold: int
    reaction_context_turns: int
    reaction_context_token_limit: int


class ProductProvider(Protocol):
    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str: ...

    def generate_text(self, request: TextGenerationRequest) -> str: ...

    def generate_text_stream(self, request: TextGenerationRequest) -> Iterable[str]: ...

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str: ...

    def select_reaction(self, request: ReactionSelectionRequest) -> str: ...

    def parse_image_event(self, request: ImageToEventRequest) -> EventPayload: ...

    def extract_image_text(self, request: ImageToTextRequest) -> str: ...


class SettingsGetter(Protocol):
    def __call__(self) -> BotSettings: ...


class ProviderGetter(Protocol):
    def __call__(self) -> ProductProvider: ...


class IsAllowedFn(Protocol):
    def __call__(self, update: Update) -> bool: ...


class StorageIdFn(Protocol):
    def __call__(self, update: Update) -> Optional[str]: ...


class LogContextFn(Protocol):
    def __call__(self, update: Optional[Update]) -> Dict[str, Any]: ...


class AddMessageFn(Protocol):
    def __call__(
        self,
        sender: str,
        text: str,
        chat_id: str,
        is_bot: bool = False,
        telegram_message_id: Optional[int] = None,
        reply_to_telegram_message_id: Optional[int] = None,
    ) -> None: ...


class GetAllMessagesFn(Protocol):
    def __call__(self, chat_id: str) -> List[Dict[str, Any]]: ...


class GetMessageByTelegramMessageIdFn(Protocol):
    def __call__(
        self, chat_id: str, telegram_message_id: int
    ) -> Optional[Dict[str, Any]]: ...


class BuildContextFn(Protocol):
    def __call__(
        self,
        chat_id: str,
        latest_user_text: str = "",
        token_limit: Optional[int] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        summarize_fn: Optional[Callable[[str], str]] = None,
    ) -> str: ...


class AssembleContextFn(Protocol):
    def __call__(self, messages: list, token_limit: Optional[int] = None) -> str: ...


class GetSummaryViewTextFn(Protocol):
    def __call__(
        self,
        *,
        chat_id: str,
        head: int = 0,
        tail: int = 0,
        index: Optional[int] = None,
        grep: str = "",
    ) -> str: ...


class CalendarProvider(Protocol):
    def create_event(
        self,
        *,
        title: str,
        is_all_day: bool,
        start_time: datetime,
        location: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None: ...


class CalendarProviderFactory(Protocol):
    def __call__(self) -> CalendarProvider: ...
