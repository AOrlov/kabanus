from __future__ import annotations

from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
)

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
    @property
    def features(self) -> Mapping[str, Any]: ...

    @property
    def bot_aliases(self) -> Sequence[str]: ...

    @property
    def debug_mode(self) -> bool: ...

    @property
    def model_provider(self) -> str: ...

    @property
    def telegram_format_ai_replies(self) -> bool: ...

    @property
    def telegram_use_message_drafts(self) -> bool: ...

    @property
    def telegram_bot_token(self) -> str: ...

    @property
    def telegram_draft_update_interval_secs(self) -> float: ...

    @property
    def reaction_enabled(self) -> bool: ...

    @property
    def reaction_cooldown_secs(self) -> float: ...

    @property
    def reaction_daily_budget(self) -> int: ...

    @property
    def reaction_messages_threshold(self) -> int: ...

    @property
    def reaction_context_turns(self) -> int: ...

    @property
    def reaction_context_token_limit(self) -> int: ...


class ProductProvider(Protocol):
    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str: ...

    def generate_text(self, request: TextGenerationRequest) -> str: ...

    def generate_text_stream(self, request: TextGenerationRequest) -> Iterable[str]: ...

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str: ...

    def select_reaction(self, request: ReactionSelectionRequest) -> str: ...

    def parse_image_event(self, request: ImageToEventRequest) -> EventPayload: ...

    def extract_image_text(self, request: ImageToTextRequest) -> str: ...


SettingsGetter = Callable[[], BotSettings]
ProviderGetter = Callable[[], ProductProvider]
IsAllowedFn = Callable[[Update], bool]
StorageIdFn = Callable[[Update], Optional[str]]
LogContextFn = Callable[[Optional[Update]], Mapping[str, Any]]
AddMessageFn = Callable[..., None]
GetAllMessagesFn = Callable[[str], Sequence[Mapping[str, Any]]]
GetMessageByTelegramMessageIdFn = Callable[[str, int], Optional[Mapping[str, Any]]]
BuildContextFn = Callable[..., str]
AssembleContextFn = Callable[..., str]
GetSummaryViewTextFn = Callable[..., str]


class CalendarProvider(Protocol):
    def create_event(self, *args: Any, **kwargs: Any) -> Any: ...

CalendarProviderFactory = Callable[[], CalendarProvider]
