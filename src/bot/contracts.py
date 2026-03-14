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
from src.providers.capabilities import (
    AudioTranscriptionProvider,
    EventParsingProvider,
    LowCostTextGenerationProvider,
    OcrProvider,
    ReactionSelectionProvider,
    StreamingTextGenerationProvider,
    TextGenerationProvider,
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


class ProductProvider(
    AudioTranscriptionProvider,
    TextGenerationProvider,
    StreamingTextGenerationProvider,
    LowCostTextGenerationProvider,
    ReactionSelectionProvider,
    EventParsingProvider,
    OcrProvider,
    Protocol,
):
    pass


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
